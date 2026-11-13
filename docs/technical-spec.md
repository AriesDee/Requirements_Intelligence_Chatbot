# Requirements Intelligence Chatbot — Technical Specification

**Audience:** Support engineers, maintenance developers, and technical leads responsible for operating and extending RIC.  
**Last updated:** September 2026  
**Author:** Associate Experience Center / WFM Team, Albertsons

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository Structure](#3-repository-structure)
4. [Architecture and Data Flow](#4-architecture-and-data-flow)
5. [Data Models](#5-data-models)
6. [Processing Pipeline — Stage by Stage](#6-processing-pipeline--stage-by-stage)
7. [LLM Integration — Complete Prompt Reference](#7-llm-integration--complete-prompt-reference)
8. [Requirements File Adapters](#8-requirements-file-adapters)
9. [Report Generation](#9-report-generation)
10. [Streamlit UI](#10-streamlit-ui)
11. [CLI Interface](#11-cli-interface)
12. [Configuration Reference](#12-configuration-reference)
13. [Authentication and Credentials](#13-authentication-and-credentials)
14. [Extension Guide](#14-extension-guide)
15. [Known Issues and Troubleshooting](#15-known-issues-and-troubleshooting)

---

## 1. System Overview

RIC is a decision-support tool for the WFM (Workforce Management) team at Albertsons/Safeway. It automates the process of reading labor agreement change documents (IOCs and BRDs) and mapping each change to the specific timekeeping requirements that need to be reviewed or updated in the Workbrain/WFM system.

### What it replaces

Previously, an analyst would manually read an IOC or BRD, identify every change, and then search the Requirements Inventory (RI) or Foundational Requirements Inventory (FRI) spreadsheet for affected rules. This could take many hours per document. RIC performs this in minutes and produces a structured Excel/HTML report.

### What it does NOT do

- It does not make changes to Workbrain or any production system.
- It does not send emails or notifications.
- It does not store any data persistently (all state is in-session in Streamlit).
- It does not access the internet at runtime (only the GCP Vertex AI endpoint is called).

---

## 2. Technology Stack

| Component | Library / Service | Version |
|---|---|---|
| UI | Streamlit | ≥ 1.35 |
| LLM (inference) | Google Vertex AI (Gemini) | via `google-genai ≥ 1.0` |
| Default model | `gemini-2.5-flash` | GCP project `gcp-abs-sbt01-psbx-sbx-prj-01` |
| Data models / validation | Pydantic v2 | ≥ 2.0 |
| PDF text extraction | pdfplumber | ≥ 0.10 |
| Word document parsing | python-docx | ≥ 1.0 |
| Excel report generation | openpyxl | ≥ 3.1 |
| Python runtime | CPython | ≥ 3.11 |
| Package build | Hatchling | any |

### GCP Details

- **Project:** `gcp-abs-sbt01-psbx-sbx-prj-01`
- **Location:** `us-central1` (overridable via `GOOGLE_CLOUD_LOCATION` env var)
- **Auth mechanism:** Application Default Credentials (ADC) — service account JSON file pointed to by `GOOGLE_APPLICATION_CREDENTIALS`
- **Model availability:** Only models whitelisted in the GCP project can be called. Tested: `gemini-2.5-flash`. Do NOT use `gemini-2.0-flash-001` or `gemini-1.5-flash-001` — those return 404 in this project.

---

## 3. Repository Structure

```
Requirements-Intelligence-Chatbot/
├── app.py                          # Streamlit UI (entry point)
├── pyproject.toml                  # Package definition and dependencies
├── README.md                       # User-facing documentation
├── docs/
│   └── technical-spec.md           # This file
├── src/
│   └── ric/
│       ├── __init__.py
│       ├── models.py               # Requirement data model (shared)
│       ├── _vertex.py              # Shared Vertex AI client factory
│       ├── demo.py                 # Demo mode sample data
│       ├── chat.py                 # Chat Q&A module
│       ├── cli.py                  # Command-line interface
│       ├── ioc/
│       │   ├── __init__.py         # exports parse_ioc
│       │   ├── models.py           # IOCChange, IOCParseResult, ChangeType
│       │   ├── parser.py           # Stage 1 LLM call (IOC PDF → structured changes)
│       │   └── reader.py           # pdfplumber text extraction
│       ├── brd/
│       │   ├── __init__.py         # exports parse_brd
│       │   ├── parser.py           # Stage 1 LLM call (BRD Word → structured changes)
│       │   └── reader.py           # python-docx text extraction
│       ├── matcher/
│       │   ├── __init__.py
│       │   ├── models.py           # ChangeMatch, RequirementMatch
│       │   ├── filter.py           # LA-scope pre-filter (no LLM)
│       │   └── matcher.py          # Stage 2+3 LLM call (change → requirements)
│       ├── flagging/
│       │   ├── __init__.py
│       │   ├── models.py           # RiskFlag, FlagSeverity, FlagType
│       │   └── flagger.py          # Stage 4 LLM call (risk flags)
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── fri.py              # FRI xlsx adapter (Format C)
│       │   └── ri.py               # RI xlsx/csv adapter (Format A)
│       ├── report/
│       │   ├── __init__.py
│       │   ├── excel.py            # 3-sheet Excel workbook
│       │   └── html.py             # HTML report
│       └── parsing/
│           └── scope.py            # RI scope parser (LA include/exclude regex)
└── tests/
    └── (pytest test files)
```

---

## 4. Architecture and Data Flow

### High-level flow

```
User uploads IOC (PDF) or BRD (.docx)
        │
        ▼
[Stage 1] Document Parser
  • pdfplumber (PDF) or python-docx (Word) extracts raw text
  • 1 Gemini LLM call → IOCParseResult
    (list of IOCChange objects with type, summary, LAs, source_text)
        │
        ▼
[Stage 2+3] Requirement Matcher  (1 Gemini call per change)
  • filter.py pre-filters requirements by LA scope (no LLM)
  • matcher.py sends each change + filtered candidates to Gemini
  • returns list[ChangeMatch] with matched requirements + delta descriptions
        │
        ▼
[Stage 4] Risk Flagger  (1 Gemini call per change)
  • flagger.py sends each change + its matches back to Gemini
  • enriches each ChangeMatch.risk_flags in place
        │
        ▼
[Reports] Excel + HTML
  • excel.py writes 3-sheet workbook
  • html.py writes styled HTML report
        │
        ▼
[Chat] Optional Q&A
  • chat.py builds context string from full analysis
  • multi-turn Gemini chat session over that context
```

### LLM call budget

For a document with N changes:
- Stage 1: 1 call (full document → all changes)
- Stages 2+3: N calls (1 per change)
- Stage 4: N calls (1 per change)
- **Total: 2N + 1 calls**

For a typical IOC with 8 changes this is 17 Gemini calls. Each call uses `gemini-2.5-flash`.

---

## 5. Data Models

All models use Pydantic v2. Source files are in `src/ric/`.

### 5.1 `Requirement` — `models.py`

Represents a single timekeeping rule from an RI or FRI spreadsheet.

```python
class Requirement(BaseModel):
    id: str                          # Generated: {SOURCE}-{PAYGROUP}-{SECTION_SLUG}-{NNN}
    source: Literal["RI", "FRI"]
    paygroup: str                    # e.g. "025", "025R", "087"
    section: str                     # Sheet/section name from the spreadsheet
    category: str | None             # FRI only: Requirements Category column
    contract_reference: str | None
    description: str                 # Full requirement text
    scope_type: Literal["all","include","exclude"]
    labor_agreements: list[str]      # LA codes if scope is include/exclude
    hour_types: list[str]
    earn_codes: list[str]
    adj_earn_codes: list[str]
    extra: dict[str, Any]            # Adapter-specific extras (sheet name, people group, etc.)
```

**`applies_to(target_las: set[str]) -> bool`** — the method used by the LA pre-filter:
- `scope_type="all"` → always True
- `scope_type="include"` → True if any target LA is in the include list
- `scope_type="exclude"` → True if any target LA is NOT in the exclude list

### 5.2 `ChangeType` — `ioc/models.py`

```python
class ChangeType(str, Enum):
    WAGE_RATE         = "wage_rate"
    PREMIUM_VALUE     = "premium_value"
    ELIGIBILITY       = "eligibility"
    LIST_OPERATION    = "list_operation"
    HOLIDAY_COMPOSITION = "holiday_composition"
    BENEFIT           = "benefit"
    OTHER             = "other"
```

> **Important for developers:** Always use the Python attribute name in code (e.g., `ChangeType.WAGE_RATE`), not the string value. The string value (lowercase) is what the LLM produces and what is stored in JSON/Excel.

### 5.3 `IOCChange` — `ioc/models.py`

One change extracted from an IOC or BRD.

| Field | Type | Description |
|---|---|---|
| `change_type` | `ChangeType` | Category of change |
| `timekeeping_relevant` | `bool` | False for H&W/pension contribution amounts |
| `summary` | `str` | 1–2 sentence plain-language summary |
| `effective_date` | `str \| None` | Date for this change specifically; None = same as IOC date |
| `labor_agreements` | `list[str]` | 6-char LA codes (e.g. `["1400WA", "1401PM"]`) |
| `source_text` | `str` | Verbatim text from the document |
| `notes` | `str \| None` | Any uncertainty flagged by the LLM |

### 5.4 `IOCParseResult` — `ioc/models.py`

Top-level output of Stage 1 (used for both IOC and BRD).

| Field | Type | Description |
|---|---|---|
| `contract_ids` | `list[str]` | 4-char contract IDs (e.g. `["1400"]`) |
| `labor_agreement_ids` | `list[str]` | 6-char LA IDs (e.g. `["1400WA","1401PM"]`) |
| `effective_date` | `str \| None` | Overall document effective date |
| `union_locals` | `list[str]` | Union names mentioned |
| `changes` | `list[IOCChange]` | All changes extracted |

### 5.5 `RequirementMatch` — `matcher/models.py`

One matched requirement within a `ChangeMatch`.

| Field | Type | Description |
|---|---|---|
| `requirement_id` | `str` | ID of the matched `Requirement` |
| `relevance` | `"direct" \| "indirect"` | `direct` = must update; `indirect` = verify |
| `rationale` | `str` | One sentence why this requirement is relevant |
| `delta_description` | `str` | Concrete action for the WFM analyst (1–3 sentences with amounts/dates/earn codes) |

### 5.6 `ChangeMatch` — `matcher/models.py`

Pairs one `IOCChange` with its matched requirements and risk flags.

| Field | Type | Description |
|---|---|---|
| `change` | `IOCChange` | The source change |
| `matched_requirements` | `list[RequirementMatch]` | Requirements that need review |
| `no_match_reason` | `str \| None` | Why nothing matched (if empty list) |
| `risk_flags` | `list[RiskFlag]` | Populated by Stage 4 |

### 5.7 `RiskFlag` — `flagging/models.py`

One risk or clarification flag.

| Field | Type | Description |
|---|---|---|
| `flag_type` | `FlagType` (Literal) | One of 7 categories (see Stage 4 below) |
| `severity` | `FlagSeverity` | `"high"` / `"medium"` / `"low"` |
| `description` | `str` | What the issue is |
| `recommendation` | `str` | Concrete next step to resolve it |

---

## 6. Processing Pipeline — Stage by Stage

### Stage 1 — Document Parsing

**For IOC (PDF):**
- File: `src/ric/ioc/reader.py` — `extract_text(path)`  
  Uses `pdfplumber.open(path)`, joins all pages with `"\n\n"`.  
  Only `.pdf` is supported; raises `ValueError` for other extensions.

- File: `src/ric/ioc/parser.py` — `parse_ioc(path, *, model="gemini-2.5-flash")`  
  1. Calls `extract_text()` to get raw string
  2. Calls `make_client()` for a Vertex AI client
  3. Dumps `IOCParseResult.model_json_schema()` as JSON into the prompt
  4. Sends one `generate_content` call with `response_mime_type="application/json"`
  5. Validates the JSON response against `IOCParseResult` via `model_validate`

**For BRD (Word .docx):**
- File: `src/ric/brd/reader.py` — `extract_text(path)`  
  Uses `python-docx`. Iterates `doc.element.body.iterchildren()` to preserve paragraph/table order.  
  - Paragraphs: strips whitespace; adds `# Heading 1`, `## Heading 2` prefixes for heading styles.  
  - Tables: joins cells with ` | `; skips merged cell duplicates by tracking `id(cell._tc)`.

- File: `src/ric/brd/parser.py` — `parse_brd(path, *, model="gemini-2.5-flash")`  
  Same pattern as IOC parser but uses the BRD-tuned system prompt. Returns the same `IOCParseResult` type so downstream stages are unchanged.

### Stage 2+3 — Requirement Matching

**File:** `src/ric/matcher/filter.py` — `filter_by_la_scope(requirements, change, ioc_la_ids)`

Pre-filters requirements without any LLM call:
```python
las = set(change.labor_agreements) or set(ioc_la_ids)
if not las:
    return list(requirements)   # no LA info → include everything
return [r for r in requirements if r.applies_to(las)]
```
This reduces LLM prompt size and focuses the model's attention.

**File:** `src/ric/matcher/matcher.py` — `match_changes(ioc, requirements, *, model, on_progress)`

For each `IOCChange`:
1. Calls `filter_by_la_scope()` to get candidate requirements
2. If no candidates, returns `ChangeMatch` with `no_match_reason="No requirements in scope"`
3. Otherwise, formats each candidate as:
   ```
   [FRI-087-SECTION-001] section='Shift Differential' earn_codes=['SD1']
     description text (first 300 chars)
   ```
4. Sends one Gemini call with the change text + formatted candidates
5. Validates response against `_LLMMatchResult` (internal model with `matches` + `no_match_reason`)
6. **Hallucination guard:** filters `result.matches` to only IDs in the candidate set
7. Returns `ChangeMatch`

### Stage 4 — Risk Flagging

**File:** `src/ric/flagging/flagger.py` — `flag_changes(ioc, results, *, model, on_progress)`

For each `ChangeMatch` from Stage 2+3:
1. Builds a delta summary from matched requirements:
   ```
   [direct] FRI-087-WAGES-001: Update earn code REG base rate from $18.50 to $19.25...
   [indirect] FRI-087-OT-001: Verify OT premium calculation...
   ```
2. Sends one Gemini call with the change text + delta summary
3. Validates response against `_FlagResult` (internal model with `flags: list[RiskFlag]`)
4. Sets `cm.risk_flags = result.flags` (mutates the `ChangeMatch` in place)
5. Returns the same list (now enriched)

---

## 7. LLM Integration — Complete Prompt Reference

All four modules use the same call pattern:

```python
client = make_client()
response = client.models.generate_content(
    model=model,
    contents=user_prompt,
    config=types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        response_mime_type="application/json",
    ),
)
result = MyModel.model_validate(json.loads(response.text))
```

The `response_mime_type="application/json"` forces Gemini to return parseable JSON. The schema is embedded in the user prompt (not as a formal JSON Schema declaration) so the model knows the exact shape expected.

### 7.1 Shared Client Factory — `src/ric/_vertex.py`

```python
import os
import google.genai as genai

_PROJECT  = os.getenv("GOOGLE_CLOUD_PROJECT",  "gcp-abs-sbt01-psbx-sbx-prj-01")
_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

def make_client() -> genai.Client:
    return genai.Client(vertexai=True, project=_PROJECT, location=_LOCATION)
```

**To change the GCP project or region:** set `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_LOCATION` environment variables before launching Streamlit.

**To change the model for all stages at once:** the model name is passed as a parameter from the UI (`model` kwarg). The default `"gemini-2.5-flash"` is set individually in each module's function signature but overridden at call time.

---

### 7.2 IOC Parser System Prompt — `src/ric/ioc/parser.py`

**Location in code:** `_SYSTEM` string, lines 11–49

```
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
- premium_value: premium pay amounts, shift differentials, holiday pay rates, ratification bonuses
- eligibility: changes to who qualifies for a benefit or rule
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
5. Be thorough — small changes matter (e.g. a $0.25 H&W increase is still a change).
```

**When to modify this prompt:**
- New change types appear in IOCs → add a new bullet under "Change Type Classification"
- IOC template structure changes → update "IOC Document Structure"
- timekeeping_relevant logic needs adjustment → update "timekeeping_relevant Rules"
- LLM is merging separate changes into one → reinforce rule 1 with an explicit example

---

### 7.3 BRD Parser System Prompt — `src/ric/brd/parser.py`

**Location in code:** `_SYSTEM` string, lines 11–67

```
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
3. Be thorough — every change that would require WFM configuration is relevant.
```

**When to modify this prompt:**
- BRD template structure changes → update the "BRDs in this organization use..." section
- Requirement number format changes (e.g. away from `PAY_087_NU_10.30`) → update "Requirement Numbers"
- New LA code formats appear → update "Labor Agreement IDs"

---

### 7.4 Matcher System Prompt — `src/ric/matcher/matcher.py`

**Location in code:** `_SYSTEM` string, lines 15–57

```
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
directly from the change text where available.
```

**When to modify this prompt:**
- Analysts want different phrasing of `direct` vs `indirect` → update "Relevance levels"
- delta_descriptions are too vague → strengthen the example in "delta_description"
- LLM is hallucinating requirement IDs → reinforce rule 1 (the code also has a hard filter as a safety net)

---

### 7.5 Flagger System Prompt — `src/ric/flagging/flagger.py`

**Location in code:** `_SYSTEM` string, lines 14–66

```
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
- If no flags apply, return an empty list.
```

**When to modify this prompt:**
- Add a new flag type → add a new named block under "Flag types to look for" and add the string to `FlagType` in `flagging/models.py`
- Severity thresholds need adjustment → update the "Rules" section
- LLM flags too many or too few issues → add/remove examples of real vs. non-issues

---

### 7.6 Chat System Prompt — `src/ric/chat.py`

**Location in code:** `_SYSTEM` string, lines 10–25

```
You are a helpful analyst assistant for the Requirements Intelligence Chatbot (RIC).

You have been given a complete IOC (Inter-Office Communication) impact analysis as context.
The analysis shows:
- The IOC metadata (contract IDs, labor agreement IDs, effective dates, union locals)
- Each change extracted from the IOC (type, summary, source text, which LAs it affects)
- Which WFM/timekeeping requirements are matched to each change
- The relevance level (direct = must update, indirect = verify)
- The rationale for each match
- The delta description — a concrete action statement for the WFM analyst

Answer the user's questions about this analysis accurately and concisely.
Use the context provided. Do not invent requirement IDs, change details, or dollar amounts
that are not in the context. If you are unsure, say so.
You may provide general labor agreement or WFM/Workbrain guidance when it adds value.
```

The full analysis is appended to `_SYSTEM` when the chat session is created:
```python
config=types.GenerateContentConfig(
    system_instruction=_SYSTEM + "\n\n" + context,
)
```

The `context` block is structured text built by `build_context(ioc, results)` in `chat.py`.

**Chat history format** (Vertex AI `client.chats.create` requires this structure):
```python
history_contents = [
    types.Content(role=msg["role"], parts=[types.Part(text=msg["content"])])
    for msg in history
]
```
Where `msg["role"]` is `"user"` or `"model"` (Gemini uses `"model"`, not `"assistant"`).

---

## 8. Requirements File Adapters

### 8.1 FRI Adapter — `src/ric/adapters/fri.py`

**Format:** "Format C" FRI Standard Template Excel (.xlsx)

**Entry point:** `load_fri(path, *, paygroup=None) -> list[Requirement]`

**ID generation:** `FRI-{paygroup}-{SECTION_SLUG}-{n:03d}`
- Section slug: sheet name lowercased, non-alphanumeric → underscore, max 24 chars

**Paygroup inference:** regex `\b(\d{3}[A-Za-z]?)\b` applied to the file path string.
- Matches: `025`, `025R`, `087`, `140`
- Fallback when no match: sanitized filename stem (spaces→underscores, max 24 chars)

**Metadata sheet skip:** sheets matching any of these patterns are skipped:
`Legend`, `Change History`, `Lists`, `Instructions`, `Summary`, `Cover`, `Index`, `Template`

**File locking fix:** `wb.close()` is called in a `finally` block after all sheets are read. Without this, Windows holds the file handle open and the temporary directory cleanup (used by `app.py`) raises `PermissionError: [WinError 32]`.

### 8.2 RI Adapter — `src/ric/adapters/ri.py`

**Format:** "Format A" RI — either multi-sheet .xlsx or single-sheet .csv

**Entry point:** `load_ri(path, *, paygroup=None) -> list[Requirement]`

**ID generation:** `RI-{paygroup}-{SECTION_SLUG}-{n:03d}`

**Paygroup inference:** same regex and fallback as FRI.

**LA scope parsing:** calls `parsing/scope.py` on each requirement's `description` field to extract `(scope_type, labor_agreement_codes)`. The RI embeds scope as free text (e.g., "Labor Agreement: 1400WA, 1401PM") rather than a dedicated column.

**File locking fix:** same `wb.close()` in `finally` pattern.

### 8.3 RI Scope Parser — `src/ric/parsing/scope.py`

Handles 10 surface forms of LA scope declarations embedded in RI description text.

Pattern priority (checked in order):
1. `"Exclude: Labor Agreement(s): <codes>"` → `scope_type="exclude"`
2. `"Labor Agreement(s): Exclude: <codes>"` → `scope_type="exclude"`
3. `"Labor Agreement(s): All"` → `scope_type="all"`
4. `"Labor Agreement(s): <codes>"` → `scope_type="include"`
5. Default (no match) → `scope_type="all"` (safe, over-inclusive)

LA code pattern: `[0-9]{4}[A-Z]{2}` (6-char, e.g., `1400WA`)

---

## 9. Report Generation

### 9.1 Excel Report — `src/ric/report/excel.py`

**Entry point:** `write_excel(ioc, results, path, requirements=None)`

Builds a lookup `{id: Requirement}` from the `requirements` list to fill source/section/description columns.

**Sheet 1: IOC Summary**
- IOC metadata (contract IDs, LAs, effective date, union locals, change count)

**Sheet 2: Impact Analysis** — 14 columns:
`#, Change Type, TK Relevant, Eff. Date, LA Codes, Change Summary, Req ID, Src, Section, Req Description, Relevance, Rationale, Delta Description, Status`

Each row is one `RequirementMatch`. A change with 3 matches produces 3 rows. A change with no matches produces 1 row with the `no_match_reason` in the Rationale column.

**Sheet 3: Risk Flags** — 8 columns:
`#, Change Type, TK, Change Summary, Severity, Flag Type, Description, Recommendation`

One row per flag. Each flag's row includes its parent change summary for context.

### 9.2 HTML Report — `src/ric/report/html.py`

**Entry point:** `write_html(ioc, results, path, requirements=None)`

Produces a self-contained HTML file. Key CSS classes:
- `.flag-box` — container div for a risk flag card
- `.flag-high` — red left border (`#c0392b`)
- `.flag-medium` — orange left border (`#e67e22`)
- `.flag-low` — green left border (`#27ae60`)

The match table has 11 columns (`thead`). Each change is a section with a collapsible flag area below.

---

## 10. Streamlit UI

**File:** `app.py` (root of repo)

**Run command:**
```powershell
streamlit run app.py
```

### 10.1 Session State Keys

| Key | Type | Set by | Purpose |
|---|---|---|---|
| `ioc` | `IOCParseResult` | Analysis run | Parsed document data |
| `results` | `list[ChangeMatch]` | Analysis run | Matched + flagged results |
| `requirements` | `list[Requirement]` | Analysis run | Loaded from FRI/RI files |
| `excel_data` | `bytes` | Analysis run | Excel report in memory |
| `html_data` | `bytes` | Analysis run | HTML report in memory |
| `output_name` | `str` | Analysis run | Basename for download filenames |
| `chat_history` | `list[dict]` | Chat tab | `[{"role": "user/model", "content": "..."}]` |
| `chat_context` | `str` | Analysis run | Serialized analysis for chat |
| `chat_is_demo` | `bool` | Demo button | Whether chat context is demo data |
| `input_doc_type` | `"IOC" \| "BRD"` | Analysis run | Controls metric label on Overview tab |

### 10.2 UI Sections

**Sidebar:**
- RIC branding header (corporate navy banner)
- Status pills (green/grey) for: Vertex AI model name, Requirements loaded (count), Analysis complete
- Document type radio: "IOC (PDF)" or "BRD (Word .docx)"
- Conditional file uploader based on radio selection
- FRI/RI file uploaders (multi-file)
- Model selector (text input, default `gemini-2.5-flash`)
- Run Analysis button
- Demo Mode button
- Download buttons (Excel, HTML) — appear after analysis

**Main tabs (4):**
1. **Overview** — metrics row (`{doc_type} Changes`, `Requirements Matched`, `Risk Flags`), then change cards
2. **Impact Analysis** — full match table with expanders per change
3. **Risk Flags** — colored flag cards grouped by change
4. **Chat** — multi-turn Q&A with context panel

### 10.3 CSS Theme

Injected immediately after `st.set_page_config()` via `st.markdown(..., unsafe_allow_html=True)`:

- **Font:** `Verdana, Geneva, Tahoma, sans-serif !important` on `html, body, [class*="css"]`
- **Top accent bar:** 4px fixed gradient bar `linear-gradient(90deg, #1a4a8a, #2e7dd1, #5ba3e8)`
- **Brand color:** `#1a4a8a` (navy) used for headings, metric tile borders, primary buttons
- **Metric tiles:** white background, `border-top: 3px solid #1a4a8a`, subtle box shadow
- **Primary button** (Run Analysis): `background-color: #1a4a8a`, white text
- **Download button:** `background-color: #1e7e45` (dark green), white text

### 10.4 Dynamic Document Type Label

```python
# In Session State
st.session_state.input_doc_type = "BRD" if brd_file else "IOC"

# On Overview tab
_doc_type_label = (st.session_state.input_doc_type or "IOC") + " Changes"
m1.metric(_doc_type_label, len(results))
```

This ensures the first metric card reads "BRD Changes" when a BRD was uploaded, rather than always showing "IOC Changes".

### 10.5 File Temp Handling

Uploaded files are saved to a `tempfile.TemporaryDirectory(ignore_cleanup_errors=True)` so they can be passed by path to the document parsers. `ignore_cleanup_errors=True` is required on Windows because `openpyxl` holds xlsx file handles briefly after `wb.close()`, and the standard cleanup raises `PermissionError: [WinError 32]` without this flag.

---

## 11. CLI Interface

**File:** `src/ric/cli.py`

**Command:**
```
ric analyze \
  --ioc FILE.pdf \
  --fri FRI1.xlsx FRI2.xlsx \
  --ri RI1.xlsx \
  --paygroup 025 \
  --output results \
  --model gemini-2.5-flash
```

Runs all four stages sequentially and writes `results.xlsx` and `results.html`.

**Install and run:**
```powershell
pip install -e ".[ui]"
ric analyze --help
```

---

## 12. Configuration Reference

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | *(required)* | Absolute path to service account JSON file |
| `GOOGLE_CLOUD_PROJECT` | `gcp-abs-sbt01-psbx-sbx-prj-01` | GCP project for Vertex AI |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | GCP region for Vertex AI |

### Model Selection

The model is selected in the UI sidebar (default: `gemini-2.5-flash`). It is passed through to all four LLM modules as the `model` kwarg. To change the default, update the default value in each module's function signature:

| Module | Function | Line | Default value |
|---|---|---|---|
| `ioc/parser.py` | `parse_ioc` | 52 | `"gemini-2.5-flash"` |
| `brd/parser.py` | `parse_brd` | 71 | `"gemini-2.5-flash"` |
| `matcher/matcher.py` | `match_changes` | 131 | `"gemini-2.5-flash"` |
| `flagging/flagger.py` | `flag_changes` | 116 | `"gemini-2.5-flash"` |
| `chat.py` | `ask` | 74 | `"gemini-2.5-flash"` |

---

## 13. Authentication and Credentials

### Service Account

The app authenticates to Vertex AI via a service account JSON file. This file is stored **outside the repository** at:

```
C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json
```

> **Never commit the service account JSON to git.** It grants programmatic access to the GCP project.

### Setting `GOOGLE_APPLICATION_CREDENTIALS`

**For a single session (PowerShell):**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json"
streamlit run app.py
```

**Persistent (survives reboots — Windows registry, User scope):**
```powershell
[System.Environment]::SetEnvironmentVariable(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json",
    "User"
)
```
Then open a new PowerShell window before running Streamlit.

> The env var must be set **in the same PowerShell session** that runs `streamlit run app.py`, or system-wide before that session starts. Setting it in a different window has no effect on an already-running Streamlit process.

### How Auth Works Under the Hood

`make_client()` calls `genai.Client(vertexai=True, ...)`. The `google-auth` library reads `GOOGLE_APPLICATION_CREDENTIALS`, loads the JSON, and exchanges it for a short-lived access token automatically. No explicit token handling is needed in application code.

---

## 14. Extension Guide

### Adding a New Change Type

1. Add the new string value to `ChangeType` in `src/ric/ioc/models.py`
2. Add a classification rule to the IOC parser system prompt (`ioc/parser.py` `_SYSTEM`)
3. Add the same rule to the BRD parser system prompt (`brd/parser.py` `_SYSTEM`)
4. Update `demo.py` if any sample data needs to use the new type

### Adding a New Risk Flag Type

1. Add the new string literal to `FlagType` in `src/ric/flagging/models.py`
2. Add a named block under "Flag types to look for" in `flagger.py` `_SYSTEM`

### Adding a New Document Format (e.g., CSV BRD)

1. Create `src/ric/newformat/reader.py` with an `extract_text(path) -> str` function
2. Create `src/ric/newformat/parser.py` with a `parse_newformat(path, *, model)` function returning `IOCParseResult`
3. Add a new file uploader option in `app.py` alongside the existing IOC/BRD radio
4. Dispatch to `parse_newformat()` in the analysis run block

### Adding a New Requirements Adapter

1. Create `src/ric/adapters/myformat.py` with `load_myformat(path, *, paygroup=None) -> list[Requirement]`
2. Add a new uploader in the sidebar of `app.py` alongside the existing FRI/RI uploaders
3. Append the result to the `requirements` list before calling `match_changes`

### Changing LLM Prompts Without Touching Code

If you need to iterate on prompt content without changing Python files, consider extracting the `_SYSTEM` string to a `.txt` or `.md` file in a `prompts/` directory and loading it at module import time:
```python
_SYSTEM = Path(__file__).parent.parent.parent / "prompts" / "ioc_parser.md"
_SYSTEM = _SYSTEM.read_text()
```
This makes prompt edits accessible to non-developers and allows git-diffable prompt history.

---

## 15. Known Issues and Troubleshooting

### `PermissionError: [WinError 32] The process cannot access the file`

**Cause:** `openpyxl` holds xlsx file handles open briefly. Windows prevents the temp directory from being deleted while handles are open.

**Fix:** All `TemporaryDirectory()` calls use `ignore_cleanup_errors=True`. All `openpyxl` workbook opens use a `finally` block with `wb.close()`. If this error appears in a new adapter, apply the same pattern.

### `DefaultCredentialsError: File ... was not found`

**Cause:** `GOOGLE_APPLICATION_CREDENTIALS` points to a path that doesn't exist, or it's not set in the current PowerShell session.

**Fix:** Verify the exact file path (the credentials file is in OneDrive, not the local profile). Set the env var in the same session that runs Streamlit.

### `404 NOT_FOUND: Publisher model ... was not found`

**Cause:** The GCP project `gcp-abs-sbt01-psbx-sbx-prj-01` only has access to specific models. Using `gemini-2.0-flash-001` or `gemini-1.5-flash-001` returns 404.

**Fix:** Use `gemini-2.5-flash` (no version suffix). To discover available models:
```python
from ric._vertex import make_client
client = make_client()
for m in client.models.list():
    print(m.name)
```

### `ValueError: Cannot infer paygroup from path: ...`

**Cause:** The FRI/RI filename doesn't contain a 3-digit paygroup code. The regex `\b(\d{3}[A-Za-z]?)\b` found no match.

**Fix:** The adapter falls back to a sanitized slug of the filename. Alternatively, pass `paygroup="025"` explicitly to `load_fri()` or `load_ri()`. In the UI, this is surfaced as a text input if needed.

### LLM produces incorrect change classification or misses changes

**Diagnosis:** Print the raw extracted text from `reader.extract_text()` to see what the LLM actually receives. If the PDF has non-extractable text (scanned image), `pdfplumber` returns empty strings — RIC cannot process scanned PDFs without OCR.

**Fix for classification issues:** Add explicit examples to the relevant `_SYSTEM` prompt. The most effective prompt additions are concrete examples of the edge case, not rule restatements.

### Streamlit does not see changes after editing Python files

Streamlit caches module imports. Press `R` in the Streamlit browser to force a full reload, or stop and restart `streamlit run app.py`.

### `AttributeError` on `ChangeType.wage_rate`

**Cause:** The enum attribute name is uppercase (`WAGE_RATE`) but code used the lowercase string value.

**Fix:** Always access enum members by their Python name: `ChangeType.WAGE_RATE`, `ChangeType.PREMIUM_VALUE`, etc.
