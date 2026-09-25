import json
from collections.abc import Callable

import google.genai as genai
from google.genai import types
from pydantic import BaseModel

from ric._vertex import make_client
from ric.ioc.models import IOCChange, IOCParseResult
from ric.models import Requirement

from .filter import filter_by_la_scope
from .models import ChangeMatch, RequirementMatch

_SYSTEM = """\
You are a labor agreement requirements analyst at a grocery retailer.

You are given a single CHANGE extracted from an IOC (Inter-Office Communication) and a list of
CANDIDATE REQUIREMENTS from a Requirements Inventory (RI) or Foundational Requirements
Inventory (FRI). Both describe timekeeping and payroll rules that must be configured in a
Workbrain/WFM system.

Your task: identify which candidates are relevant to this change and must be reviewed when
implementing the change in the WFM system.

## Relevance levels
- direct: The requirement directly describes the behavior that is changing. A WFM analyst MUST
  review and likely update this requirement (e.g., a wage-rate requirement when there is a
  wage increase; a holiday list requirement when a new holiday is added).
- indirect: The requirement describes logic that depends on the changed value or may be
  downstream of it. An analyst SHOULD consider it (e.g., an overtime premium requirement
  when the base wage rate changes, because the OT dollar amount is derived from the base rate).

## When a requirement has NO relevance
Do not include it. Only return requirements that genuinely require attention.

## Rules
1. Only use IDs from the candidate list — never invent IDs.
2. Prefer false positives over false negatives — this is a human-review tool; missing something
   is worse than including an extra.
3. For changes where timekeeping_relevant is False (e.g., H&W contribution amounts, pension),
   most timekeeping requirements are irrelevant. Only include any that reference those
   contribution amounts, deduction earn codes, or benefit-hours logic.
4. In your rationale, reference specific content from both the change and the requirement.
5. If no candidates match, set no_match_reason to a brief explanation.

## delta_description — what the analyst must do
For every matched requirement, write a concrete action statement:
- Direct match: state what to change, from what value to what value, citing the effective date.
  Example: "Update earn code REG base rate from $18.50 to $19.25 effective 2026-01-01 per
  the new wage scale. Verify all step rates in the wage schedule are updated accordingly."
- Indirect match: state what to verify and the condition that would trigger a change.
  Example: "Verify the OT premium calculation — if the dollar amount is derived from the base
  rate it will self-adjust; if it is hardcoded, recalculate using the new $19.25 base rate."
Keep delta_description to 1–3 sentences. Be specific — use amounts, earn codes, and dates
directly from the change text where available.\
"""


class _LLMMatchResult(BaseModel):
    matches: list[RequirementMatch]
    no_match_reason: str | None = None


def _format_requirements(reqs: list[Requirement]) -> str:
    parts = []
    for r in reqs:
        desc = r.description[:300].replace("\n", " ")
        line = f"[{r.id}] section={r.section!r}"
        if r.earn_codes:
            line += f" earn_codes={r.earn_codes}"
        if r.hour_types:
            line += f" hour_types={r.hour_types}"
        line += f"\n  {desc}"
        parts.append(line)
    return "\n".join(parts)


def _match_change(
    change: IOCChange,
    candidates: list[Requirement],
    client: genai.Client,
    model: str,
) -> ChangeMatch:
    if not candidates:
        return ChangeMatch(
            change=change,
            matched_requirements=[],
            no_match_reason="No requirements in scope for the affected LAs",
        )

    change_text = (
        f"Change type: {change.change_type.value}\n"
        f"Timekeeping relevant: {change.timekeeping_relevant}\n"
        f"Summary: {change.summary}\n"
        f"Applies to LAs: {', '.join(change.labor_agreements) or 'all IOC LAs'}\n"
        f"Source text:\n{change.source_text}"
    )

    schema_str = json.dumps(_LLMMatchResult.model_json_schema(), indent=2)

    prompt = (
        f"CHANGE:\n{change_text}\n\n"
        f"CANDIDATE REQUIREMENTS ({len(candidates)}):\n"
        f"{_format_requirements(candidates)}\n\n"
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
    result = _LLMMatchResult.model_validate(json.loads(response.text))

    # Guard against hallucinated IDs
    candidate_ids = {r.id for r in candidates}
    valid_matches = [m for m in result.matches if m.requirement_id in candidate_ids]

    return ChangeMatch(
        change=change,
        matched_requirements=valid_matches,
        no_match_reason=result.no_match_reason if not valid_matches else None,
    )


def match_changes(
    ioc: IOCParseResult,
    requirements: list[Requirement],
    *,
    model: str = "gemini-2.5-flash",
    on_progress: Callable[[int, int, IOCChange], None] | None = None,
) -> list[ChangeMatch]:
    """For each IOC change, find the requirements that need review."""
    client = make_client()

    results = []
    total = len(ioc.changes)
    for i, change in enumerate(ioc.changes, 1):
        if on_progress:
            on_progress(i, total, change)
        candidates = filter_by_la_scope(requirements, change, ioc.labor_agreement_ids)
        results.append(_match_change(change, candidates, client, model))
    return results
