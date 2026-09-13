import json
from pathlib import Path

from google.genai import types

from ric._vertex import make_client
from ric.ioc.models import IOCParseResult

from .reader import extract_text

_SYSTEM = """\
You analyze Business Requirements Documents (BRDs) from a grocery retailer's WFM/labor team.
BRDs describe changes to union Labor Agreements (LAs) that must be implemented in a
Workbrain/WFM timekeeping system.

BRDs in this organization use a standard Albertsons template with these key sections:
- Cover table: ticket number, date, paygroup/division, brief description
- Introduction / Business Case: plain-language description of what is changing and why
- Scope: which pay groups, calc groups, and contracts are affected
- Requirements / Details of Old and New Language: tables with requirement numbers
  (formatted like PAY_087_NU_10.30) showing the current and new rule text
- Testing / Test Scenarios: maps each requirement to a test case

## Your job
Extract every distinct change described in the BRD as an IOCChange object.

A single BRD typically describes one business change (e.g. adding a new LA to a set of rules,
changing a wage rate, updating a premium). However, if the BRD covers multiple changes to
different requirement types, extract each as a separate IOCChange.

## Change Type Classification
- wage_rate: base wages, wage rates, wage scales, wage step increases
- premium_value: premium pay amounts, shift differentials, holiday pay rates, bonuses
- eligibility: changes to who qualifies — including adding a new labor agreement (LA) to
  existing rules so that a new employee population is covered
- list_operation: adding or removing items from a defined list (holiday list, job class list)
- holiday_composition: changes to which holidays are recognized in the contract
- benefit: H&W/health & welfare, dental, vision, or pension contribution amounts (NOT timekeeping)
- other: procedural, language corrections, or anything that doesn't fit above

## timekeeping_relevant Rules
TRUE — affects WFM earn codes, hour types, or pay calculations:
  Wage rates, premiums, holiday rules, new LAs added to timekeeping rules, retroactive pay
FALSE — purely benefits-side:
  H&W/dental/vision/pension contribution amounts

## Labor Agreement IDs
Use 6-character codes (e.g. HAPHBE, HAGTNPH, 1400WA) when they appear in the document.
If the BRD says "add LA X", list X in labor_agreements. If it maps a new LA to existing rules,
note both the new LA and the reference LA (e.g. "HAPHBE mirrors HAGTNPH") in the summary.

## Requirement Numbers
BRDs often list requirement numbers (e.g. PAY_087_NU_10.30) in the "Old/New Language" tables.
Include these in source_text so the analyst can cross-reference the inventory directly.
If all listed requirements share the same change, consolidate into one IOCChange with all
requirement numbers in the source_text.

## IOCParseResult top-level fields
- contract_ids: paygroup code(s) found on the cover (e.g. ["087"])
- labor_agreement_ids: all LA codes mentioned (new and existing)
- effective_date: migration target date or effective date from the cover table (ISO 8601)
- union_locals: union name if stated, otherwise leave empty

## Output Rules
1. source_text: quote the key sentence(s) and/or requirement numbers verbatim from the BRD.
2. effective_date on individual changes: use the migration target date if given.
3. Be thorough — every change that would require WFM configuration is relevant.\
"""


def parse_brd(path: str | Path, *, model: str = "gemini-2.5-flash") -> IOCParseResult:
    """Parse a BRD Word document into the same IOCParseResult structure used by the IOC pipeline."""
    text = extract_text(path)
    client = make_client()

    schema_str = json.dumps(IOCParseResult.model_json_schema(), indent=2)

    prompt = (
        "Parse all changes from this Business Requirements Document (BRD).\n\n"
        f"Return JSON matching this schema:\n{schema_str}\n\n"
        f"BRD Document:\n{text}"
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
