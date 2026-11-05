# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Install (including Streamlit UI dependencies)
python -m pip install -e ".[ui]" --trusted-host pypi.org --trusted-host files.pythonhosted.org

# Run the Streamlit app
python -m streamlit run app.py

# Run all tests
pytest

# Run a single test
pytest tests/test_scope_parser.py::test_all_basic

# CLI (non-interactive, batch mode)
ric analyze --ioc FILE.pdf --fri FILE.xlsx [--ri FILE.xlsx] [--model gemini-2.5-flash] [--output impact_analysis]
```

## Architecture

RIC is a Streamlit app backed by a pipeline of LLM calls to Google Vertex AI (Gemini). It has two operating modes — **IOC/BRD Analysis** and **Inventory Explorer** — both served from `app.py`.

### Core design principle: inventory-agnostic

The analysis engine never sees RI or FRI file structure. Each adapter normalizes its format into `src/ric/models.py::Requirement` (a Pydantic model), and all downstream stages operate on that abstract representation. This means the RI adapter and FRI adapter are the only places that know anything about Excel column layouts.

### Analysis pipeline (IOC/BRD mode)

1. **Read** — `ioc/reader.py` (PDF text via pdfplumber) or `brd/reader.py` (Word via python-docx)
2. **Parse** — `ioc/parser.py` or `brd/parser.py` — LLM call that structures the document into typed `IOCChange` objects (premium change, rate change, list operation, etc.)
3. **Filter** — `matcher/filter.py` — LA-scope pre-filter; applies `Requirement.applies_to()` set logic before the expensive LLM matching step
4. **Match** — `matcher/matcher.py` — LLM call per change; returns `ChangeMatch` with `Direct` / `Indirect` tiers
5. **Flag** — `flagging/flagger.py` — LLM call per change; adds `RiskFlag` objects (retroactive pay, missing earn codes, ambiguous language, etc.)
6. **Report** — `report/excel.py` and `report/html.py`

### Inventory Explorer pipeline

1. **Load** — adapters produce `Requirement` objects
2. **Analyze** — `inventory/analyzer.py` — pure Python; counts by section/LA/scope, gap detection (missing scope codes, short descriptions)
3. **Quality check** — `inventory/quality.py` — one LLM call per file; cross-section awareness
4. **Chat** — `inventory/chat.py` / `chat.py` — builds context from analysis results for Q&A

### Key modules

| Path | Role |
|---|---|
| `src/ric/models.py` | `Requirement` — the shared inventory-agnostic data model |
| `src/ric/_vertex.py` | Vertex AI client factory; reads `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| `src/ric/parsing/scope.py` | Parses LA scope strings (`All`, include list, exclude list) into `(ScopeType, list[str])` |
| `src/ric/adapters/fri.py` | FRI xlsx loader — handles header detection, metadata sheet skipping, paygroup inference |
| `src/ric/adapters/ri.py` | RI xlsx/csv loader — multi-sheet, section-header rows, LA scope in description text |

### Scope logic

`Requirement.applies_to(target_las)` is the single most critical piece of correctness in the system. It resolves three forms: `scope_type == "all"` always matches; `"include"` matches when any target LA is in the named list; `"exclude"` matches when any target LA is NOT in the exclusion list. The exclude case is a known human-error trap — a requirement with "Exclude: 1402OR" applies to every LA that is *not* 1402OR. Tests for `parse_scope()` live in `tests/test_scope_parser.py`.

## Environment

| Variable | Purpose |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON (outside repo) |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (defaults to `gcp-abs-sbt01-psbx-sbx-prj-01`) |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region (defaults to `us-central1`) |

The credential file lives at `C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json`. Set the env var as a Windows User variable so it persists across sessions.

## Data formats

- **FRI** (Format C): multi-sheet xlsx; header auto-detected in first 5 rows; paygroup inferred from filename (2–4 char code like `087`, `025R`)
- **RI** (Format A): multi-sheet xlsx or csv; section-header rows embedded in data; one file covers all Labor Agreements for a paygroup
- Both are normalized to `Requirement` by their adapters. Metadata sheets (Legend, Lists, Change History) are skipped automatically.

## Gemini models

Default is `gemini-2.5-flash`. Also supported: `gemini-2.5-flash-lite` (faster, for large files), `gemini-2.5-pro` (higher quality, slower).
