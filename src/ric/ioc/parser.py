import json
from pathlib import Path

from google.genai import types

from ric._vertex import make_client
from .models import IOCParseResult
from .reader import extract_text

_SYSTEM = """\
You analyze Inter-Office Communication (IOC) documents from a grocery retailer's labor relations team.

IOCs announce changes to union Labor Agreements (LAs). Extract EVERY change and classify each one.

## IOC Document Structure
- Cover page: TO/FROM/DATE/SUBJECT, ESC CONTRACT ID(S) (6-char codes like 1400WA, 1401PM),
  UNION LOCAL(S), EFFECTIVE DATE
- One "Contract Renewal" section per LA: CONTRACT ID(S), LA ID(S), UNION LOCAL(S), EFFECTIVE DATE,
  followed by subsections: WAGE RATE CHANGES, RETROACTIVE PAY, RATIFICATION BONUS,
  H&W/DENTAL/VISION, PENSION, WORKING HOURS AND OVERTIME PROVISIONS, etc.

## Contract ID Formats
- 4-character (contract_ids / labor_agreement_ids field): e.g. 1400, 1401, 0114
- 6-character (labor_agreement_ids / labor_agreements fields): e.g. 1400WA, 1401PM, 0114BK

## Change Type Classification
- wage_rate: base wages, wage rates, wage scales, wage step increases
- premium_value: premium pay amounts, shift differentials, holiday pay rates, ratification bonuses.
  Use this ONLY when the rate/multiplier/dollar amount itself changes (e.g. OT rate changes from
  1.5x to 1.75x, or a shift differential increases from $1.00 to $1.25).
- eligibility: changes to who qualifies for a pay rule, or changes to the threshold/trigger condition
  for a rule — including overtime hours thresholds (e.g. daily OT now applies after 8 hrs instead
  of 10), schedule eligibility (5/8 vs 4/10), or qualifying conditions for a premium.
- list_operation: adding or removing items from a defined list (holiday list, job class list)
- holiday_composition: changes to which holidays are recognized in the contract
- benefit: H&W/health & welfare, dental, vision, or pension contribution amounts (NOT timekeeping)
- other: procedural, language corrections, or anything that doesn't fit above

## timekeeping_relevant Rules
TRUE — change affects how time is tracked, earn-coded, or paid in a WFM/timekeeping system:
  Wage rate changes, premium/differential amounts, ratification bonuses, holiday schedule changes,
  retroactive pay adjustments
FALSE — purely benefits-side, not tracked in timekeeping:
  H&W/dental/vision contribution amounts, pension contribution amounts

## Output Rules
1. Extract ALL changes from ALL contract sections. Do not merge separate changes into one entry.
2. labor_agreements: list the 6-char LA codes this specific change applies to.
   Use the LA ID from the enclosing section header when no narrower scope is stated.
3. source_text: copy the exact sentence(s) from the IOC. Do not paraphrase.
4. effective_date on individual changes: only set when different from the overall IOC effective date.
5. Be thorough — small changes matter (e.g. a $0.25 H&W increase is still a change).\
"""


def parse_ioc(path: str | Path, *, model: str = "gemini-2.5-flash") -> IOCParseResult:
    """Parse an IOC PDF into structured change events."""
    text = extract_text(path)
    client = make_client()

    schema_str = json.dumps(IOCParseResult.model_json_schema(), indent=2)

    prompt = (
        "Parse all changes from this IOC document.\n\n"
        f"Return JSON matching this schema:\n{schema_str}\n\n"
        f"IOC Document:\n{text}"
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
        ),
    )
    return IOCParseResult.model_validate(json.loads(response.text))
