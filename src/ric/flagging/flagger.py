import json
from collections.abc import Callable

import google.genai as genai
from google.genai import types
from pydantic import BaseModel

from ric._vertex import make_client
from ric.ioc.models import IOCChange, IOCParseResult
from ric.matcher.models import ChangeMatch

from .models import RiskFlag

_SYSTEM = """\
You are a labor agreement implementation risk analyst at a grocery retailer.

You are given a single CHANGE extracted from an IOC (Inter-Office Communication) and its
matched WFM requirements with delta descriptions. Your job is to identify risks, ambiguities,
and clarifications that an analyst must resolve BEFORE implementing this change in the
WFM/timekeeping system.

## Flag types to look for

retroactive_pay
  The change involves retroactive pay, a ratification bonus, or a payment deadline that may
  be imminent or already past. Flag when source text mentions "retroactive", "within X days
  of ratification", or an effective date that predates today.

missing_earn_code
  The change implies a new earn code is needed (new premium, new holiday, new bonus type)
  but none is specified in the IOC. Flag when the implementation would require an earn code
  that may not exist.

ambiguous_language
  The IOC uses hedging language: "may", "at the discretion of", "as mutually agreed",
  "where applicable", or defines a rule without specifying all parameters (e.g., "a bonus
  will be paid" without stating amount). Flag when the source text leaves implementation
  details open.

conflicting_dates
  The change has an effective date that differs from or conflicts with the overall IOC
  effective date, or the date is stated ambiguously (e.g., "date of ratification" without
  specifying the actual date).

multi_la_variance
  The change applies to multiple Labor Agreements in this IOC but with different values or
  conditions per LA, requiring separate configurations for each.

implementation_risk
  The change is technically complex, affects many employees or earn codes, requires IT
  lead time (e.g., new earn code creation, system upgrade), or has an unusually tight
  timeline relative to its effective date.

clarification_needed
  Something in the change requires input from Labor Relations, Payroll, or Legal before
  implementation can begin — e.g., an undefined term, a missing dollar amount, or a
  provision that contradicts an existing requirement.

## Rules
- Only flag real issues. Do not invent flags where none exist.
- A single change may have zero, one, or multiple flags.
- severity HIGH = blocks implementation; MEDIUM = must review first; LOW = monitor.
- description: what the issue is (1–2 sentences, specific to the source text).
- recommendation: the concrete next step (1–2 sentences).
- If no flags apply, return an empty list.\
"""


class _FlagResult(BaseModel):
    flags: list[RiskFlag]


def _flag_change(
    change: IOCChange,
    cm: ChangeMatch,
    client: genai.Client,
    model: str,
    ioc_effective_date: str | None,
) -> list[RiskFlag]:
    delta_summary = "\n".join(
        f"  - [{m.relevance}] {m.requirement_id}: {m.delta_description or m.rationale}"
        for m in cm.matched_requirements
    ) or "  (no matched requirements)"

    change_text = (
        f"Change type: {change.change_type.value}\n"
        f"Timekeeping relevant: {change.timekeeping_relevant}\n"
        f"Summary: {change.summary}\n"
        f"Applies to LAs: {', '.join(change.labor_agreements) or 'all IOC LAs'}\n"
        f"Change effective date: {change.effective_date or '(same as IOC)'}\n"
        f"IOC effective date: {ioc_effective_date or '—'}\n"
        f"Source text:\n{change.source_text}\n\n"
        f"Matched requirements and delta actions:\n{delta_summary}"
    )

    schema_str = json.dumps(_FlagResult.model_json_schema(), indent=2)
    prompt = (
        f"Identify risk and clarification flags for this IOC change.\n\n"
        f"CHANGE:\n{change_text}\n\n"
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
    result = _FlagResult.model_validate(json.loads(response.text))
    return result.flags


def flag_changes(
    ioc: IOCParseResult,
    results: list[ChangeMatch],
    *,
    model: str = "gemini-2.5-flash",
    on_progress: Callable[[int, int, IOCChange], None] | None = None,
) -> list[ChangeMatch]:
    """Enrich each ChangeMatch with risk/clarification flags (Stage 4).

    Returns the same list with risk_flags populated on each item.
    """
    client = make_client()

    total = len(results)
    for i, cm in enumerate(results, 1):
        if on_progress:
            on_progress(i, total, cm.change)
        flags = _flag_change(cm.change, cm, client, model, ioc.effective_date)
        cm.risk_flags = flags

    return results
