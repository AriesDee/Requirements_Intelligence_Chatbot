"""LLM-based quality checker for FRI/RI requirements inventories.

Groups requirements by (source, paygroup, section) so each call stays within-file.
One Gemini call per section group — typically 5-50 requirements per call.
"""
import json
from collections import defaultdict
from collections.abc import Callable

from google.genai import types
from pydantic import BaseModel, Field
from typing import Literal

from ric._vertex import make_client
from ric.models import Requirement

QualityIssueType = Literal[
    "ambiguous_language",
    "missing_implementation_detail",
    "potential_duplicate",
    "scope_conflict",
    "earn_code_mismatch",
]


class QualityIssue(BaseModel):
    requirement_id: str = Field(description="ID of the requirement with the issue")
    issue_type: QualityIssueType
    severity: Literal["high", "medium", "low"]
    description: str = Field(description="What specifically is wrong (1-2 sentences)")
    recommendation: str = Field(description="Concrete action to resolve (1-2 sentences)")


class _QualityResult(BaseModel):
    issues: list[QualityIssue]


_SYSTEM = """\
You are a quality analyst reviewing WFM (Workforce Management) timekeeping requirements
for a grocery retailer. Requirements come from a Foundational Requirements Inventory (FRI)
or Requirements Inventory (RI) used to configure Workbrain/WFM systems.

## WFM Domain Knowledge
You must apply domain knowledge when evaluating requirements. The following are standard,
complete labor agreement concepts that do NOT need further implementation detail:

- "No pyramiding / no compounding of overtime and/or premium rates" — This is a complete
  CBA policy statement. In WFM practice it means: (a) daily overtime hours do not count
  toward weekly overtime thresholds, and (b) premium pay applies to regular hours only,
  not to hours already receiving overtime pay. The specific premium eligibility rules
  (e.g., "Premiums paid on regular hours, NOT overtime; NOT paid on Sundays/holidays")
  are captured in separate premium requirements — do not flag the anti-pyramiding
  statement as missing detail.
- "Definitions" sections — Requirements that define a term (e.g., define what constitutes
  a "workweek", "workday", or "overtime") are policy definitions, not configuration specs.
  They are complete even without numeric values.
- Rounding rules that include an example (e.g., "5/6 rounding: minutes > 54 round up,
  < 6 round down, with examples") are complete — do not flag them as ambiguous.
- Standard CBA boilerplate ("in accordance with applicable law", "as required by the CBA",
  "per past practice") is expected contract language and is not ambiguous in this context.
- **Default hour exclusion rule** — In WFM/timekeeping, special-category hours are
  excluded from the base threshold of OTHER pay calculations unless the RI/FRI
  explicitly states they are included. This is the industry standard:
    - Holiday Worked hours do NOT count toward weekly OT (40-hr) threshold by default
    - Premium hours do NOT count toward OT thresholds by default
    - OT hours do NOT count toward premium eligibility thresholds by default
    - Holiday hours do NOT count toward premium hour calculations by default
  Do NOT flag a requirement as missing detail about whether these hours are included
  or excluded — the answer is always "excluded" unless the requirement explicitly
  states otherwise. Only flag if the requirement says these hours ARE included, which
  is the non-standard case that genuinely needs clarification or an earn code.

Review the requirements in this section for the following issue types:

ambiguous_language
  Description uses vague terms that prevent unambiguous implementation:
  "may", "at the discretion of", "as mutually agreed", "where applicable",
  "generally", "as needed", undefined terms, or conditions without specific criteria.
  Do NOT flag standard CBA boilerplate or well-understood labor law terms.
  IMPORTANT: Read the ENTIRE description before flagging. Requirements often open
  with a general statement followed by bullet points or sub-clauses that fully
  resolve the apparent ambiguity. Only flag if ambiguity remains unresolved after
  reading the complete description — including all bullets, examples, and conditions.

missing_implementation_detail
  The requirement describes a pay rule, premium, or eligibility condition but is
  missing a specific value needed to implement it — e.g., no dollar amount for a
  wage rule, no rate for a premium, no specific threshold for eligibility.
  Do NOT flag policy/definition statements or anti-pyramiding clauses — those are
  complete by design. Only flag when a concrete numeric value or condition is
  genuinely absent and cannot be inferred from the requirement itself.
  IMPORTANT: Read the ENTIRE description before flagging. Sub-bullets and
  clarifying notes within the same description count as implementation detail.

potential_duplicate
  Two or more requirements in this section describe essentially the same business
  rule, even if worded differently. Only flag when the overlap is significant enough
  that one requirement could replace the other.

scope_conflict
  The description implies a different scope than the scope_type field. E.g.,
  description says "applies to all employees" but scope_type is "include", or
  description lists specific LAs but scope_type is "all".

earn_code_mismatch
  The description explicitly references an earn code or clearly requires one
  (premium, differential, bonus), but the earn_codes field is empty.

## Rules
- Only flag real issues. Do not invent problems.
- A requirement may have zero, one, or multiple issues.
- severity: HIGH = blocks correct implementation; MEDIUM = needs clarification;
  LOW = minor, note for cleanup.
- description: what specifically is wrong — quote relevant text from the requirement.
- recommendation: the concrete next step to resolve it.
- If no issues exist in this section, return an empty list.\
"""


def _format_file(sections: dict[str, list[Requirement]]) -> str:
    """Format all sections of one file so the LLM sees the full cross-section context."""
    lines = []
    for section, reqs in sections.items():
        lines.append(f"\n### Section: {section} ({len(reqs)} requirements)")
        for r in reqs:
            meta = f"scope={r.scope_type}"
            if r.labor_agreements:
                meta += f" LAs={r.labor_agreements}"
            if r.earn_codes:
                meta += f" earn_codes={r.earn_codes}"
            if r.hour_types:
                meta += f" hour_types={r.hour_types}"
            desc = r.description.replace("\n", " ")
            lines.append(f"[{r.id}] {meta}\n  {desc}")
    return "\n".join(lines)


def _check_file(
    label: str,
    sections: dict[str, list[Requirement]],
    client,
    model: str,
) -> list[QualityIssue]:
    """Analyze all requirements in one file (source + paygroup) as a single LLM call.

    Sending the full file lets the LLM resolve cross-section references — e.g. a
    Definitions section clarifying a term flagged as ambiguous in an Overtime section.
    """
    all_reqs = [r for reqs in sections.values() for r in reqs]
    valid_ids = {r.id for r in all_reqs}
    schema_str = json.dumps(_QualityResult.model_json_schema(), indent=2)
    prompt = (
        f"File: {label} — {len(all_reqs)} requirements across {len(sections)} sections\n\n"
        f"IMPORTANT: Evaluate each requirement in the context of the ENTIRE file. "
        f"A term defined in the Definitions section, a base rule stated in Overtime, "
        f"or a scope clarification in another section all apply when assessing any "
        f"individual requirement. Do not flag something as ambiguous or incomplete "
        f"if it is clarified elsewhere in this file.\n\n"
        f"{_format_file(sections)}\n\n"
        f"Return JSON matching this schema:\n{schema_str}"
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
        ),
    )
    result = _QualityResult.model_validate(json.loads(response.text))

    # Guard: only return issues whose IDs belong to this file
    return [iss for iss in result.issues if iss.requirement_id in valid_ids]


def check_quality(
    requirements: list[Requirement],
    *,
    model: str = "gemini-2.5-flash",
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[QualityIssue]:
    """Run LLM quality check on requirements, one call per file (source + paygroup).

    Each call receives all sections of the file so cross-section context is available.
    Returns a flat list of QualityIssue objects across all files.
    """
    # Group by file: (source, paygroup) → {section → [requirements]}
    files: dict[tuple, dict[str, list[Requirement]]] = defaultdict(lambda: defaultdict(list))
    for r in requirements:
        files[(r.source, r.paygroup)][r.section].append(r)

    client = make_client()
    all_issues: list[QualityIssue] = []
    total = len(files)

    for i, ((source, paygroup), sections) in enumerate(files.items(), 1):
        label = f"{source} — Paygroup {paygroup}"
        if on_progress:
            on_progress(i, total, label)
        issues = _check_file(label, sections, client, model)
        all_issues.extend(issues)

    return all_issues
