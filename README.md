# Requirements Intelligence Chatbot (RIC)

A decision-support tool that reads an IOC (Inter-Office Communication) labor agreement memo and your Requirements Inventory, then produces a human-reviewed impact analysis identifying which timekeeping rules are affected and what actions analysts need to take.

RIC is a **read-only** tool — it never edits the inventory. The analyst stays fully in control; the tool's job is to make sure nothing gets overlooked.

---

## What it does

1. **Parses the IOC PDF** — extracts every change (wage rates, premiums, holidays, H&W, etc.) with its effective date, affected labor agreements, and source text.
2. **Matches changes to requirements** — for each change, identifies which requirements in your FRI/RI need review, rated as *direct* (must update) or *indirect* (verify).
3. **Generates delta descriptions** — concrete action statements telling the analyst exactly what to change, from what value to what, citing the effective date.
4. **Flags risks** — identifies retroactive pay deadlines, missing earn codes, ambiguous language, conflicting dates, and other blockers before implementation begins.
5. **Produces reports** — downloadable Excel and HTML reports with all findings.
6. **Answers questions** — a chat tab lets analysts ask follow-up questions about the analysis results.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.11+ | [python.org](https://python.org) |
| Google Cloud project | With Vertex AI API enabled |
| Service account JSON | With `roles/aiplatform.user` or Vertex AI access |
| IOC document | PDF format |
| Requirements file | FRI (xlsx) and/or RI (xlsx or csv) |

---

## Setup

### 1. Install dependencies

```powershell
cd "Requirements-Intelligence-Chatbot"
python -m pip install -e ".[ui]" --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### 2. Place your service account credentials

Save your Google Cloud service account JSON file somewhere outside the repo:

```
C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json
```

### 3. Set the credentials environment variable

In PowerShell — set for this session **and** persist to Windows registry:

```powershell
$credPath = "C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json"
[System.Environment]::SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", $credPath, "User")
$env:GOOGLE_APPLICATION_CREDENTIALS = $credPath
```

> After setting via registry, new PowerShell sessions will inherit it automatically.
> For the **current** session you must also set `$env:GOOGLE_APPLICATION_CREDENTIALS`.

### 4. Run the app

```powershell
python -m streamlit run app.py
```

App opens at **http://localhost:8501**

---

## Using the app

### Demo mode (no API key or files needed)

Toggle **"Demo mode (no API key needed)"** in the sidebar, then click **▶ Load Demo Analysis**.
This loads a pre-built sample analysis so you can explore the UI without any setup.

### Real analysis

The sidebar checklist must show all three ✅ before Run Analysis activates:

| Checklist item | How to satisfy |
|---|---|
| IOC PDF uploaded | Upload the IOC memo PDF |
| FRI or RI file uploaded | Upload at least one FRI xlsx or RI xlsx/csv |
| Vertex AI credentials set | `GOOGLE_APPLICATION_CREDENTIALS` env var must be set |

**Steps:**
1. Upload the **IOC PDF** (the Inter-Office Communication memo)
2. Upload one or more **FRI files** (Foundational Requirements Inventory xlsx) and/or **RI files** (Requirements Inventory xlsx or csv)
3. If needed, enter a **Paygroup override** (e.g. `025R` for NorCal Retail) — required when the paygroup code isn't in the filename
4. Click **▶ Run Analysis**

Analysis runs in four stages with a live progress display:
- Stage 1: Load requirements
- Stage 2: Parse IOC (LLM call)
- Stage 3: Match changes to requirements (one LLM call per IOC change)
- Stage 4: Flag risks and clarifications (one LLM call per IOC change)

### Outputs

| Output | Description |
|---|---|
| Impact Analysis tab | Per-change expanders with matched requirements, delta descriptions, and risk flags |
| Excel report | 3-sheet workbook: IOC Summary, Impact Analysis, Risk Flags |
| HTML report | Standalone shareable file with the same content |
| Chat tab | Ask questions about the analysis results |

---

## File format reference

### IOC PDF
Standard Inter-Office Communication memo from Labor Relations. Must be a text-based PDF (not a scanned image). One IOC per run.

### FRI (Format C — Foundational Requirements Inventory)
- File type: `.xlsx`
- Template: FRI Standard Template (cell C1 = "People Group")
- Sheets: one sheet per population; metadata sheets (Legend, Lists, Change History, etc.) are skipped automatically
- Paygroup: inferred from a 3-digit code in the filename (e.g. `087`) or a code like `025R`; use the Paygroup Override field if not present

### RI (Format A — Requirements Inventory)
- File type: `.xlsx` or `.csv`
- Structure: multi-sheet xlsx with section-header rows; LA scope embedded in the description column or implicit from the sheet header
- Paygroup: same inference rules as FRI

> You can upload FRI and RI files together in a single run. The tool combines them and labels each requirement with its source (`FRI-025R` or `RI-087`).

---

## Paygroup codes

The paygroup is a 3–4 character code used to label requirements and make IDs unique across files. Common codes:

| Division | Paygroup |
|---|---|
| NorCal Retail | 025R |
| NorCal Non-Retail | 025 |
| Seattle Retail | 027 |
| Haggen | 087 |

If the filename doesn't contain the paygroup code (e.g. files named by union local like "Bakers Local 85"), enter the paygroup in the **Paygroup Override** field before uploading. This applies to all files in that batch — upload files from different paygroups in separate runs.

---

## Gemini model selection

The default model is `gemini-1.5-flash-001`. Available options in the sidebar:

| Model | Speed | Quality | Notes |
|---|---|---|---|
| `gemini-1.5-flash-001` | Fast | Good | Default; recommended for most analyses |
| `gemini-1.5-pro-001` | Slower | Best | Use for complex IOCs or when flash misses matches |
| `gemini-1.5-flash-002` | Fast | Good | Newer flash variant |

The model must be available in your GCP project and region (`us-central1` by default). Override the region by setting `GOOGLE_CLOUD_LOCATION` environment variable.

---

## Troubleshooting

**"Vertex AI credentials set" shows ⬜ even after setting env var**
The env var was set in a different PowerShell session than the one running Streamlit. Set `$env:GOOGLE_APPLICATION_CREDENTIALS` in the same session, then restart.

**`DefaultCredentialsError: File ... was not found`**
The path in `GOOGLE_APPLICATION_CREDENTIALS` is wrong or the file doesn't exist. Verify with `Test-Path $env:GOOGLE_APPLICATION_CREDENTIALS` in PowerShell.

**`404 NOT_FOUND: Publisher model was not found`**
The selected Gemini model isn't available in your project or region. Switch to `gemini-1.5-flash-001` in the sidebar, or check that the Vertex AI API is enabled in your GCP project.

**`ValueError: Cannot infer paygroup from path`**
The filename doesn't contain a recognizable paygroup code. Enter the paygroup manually in the **Paygroup Override** field.

**`PermissionError: The process cannot access the file`**
A temporary file was locked during cleanup. This is handled automatically — retry the upload.

**Scanned/image PDFs produce no changes**
The IOC must be a text-based PDF. If your IOC was scanned, ask Labor Relations for the original digital version.

---

## Project structure

```
Requirements-Intelligence-Chatbot/
├── app.py                     # Streamlit UI
├── pyproject.toml             # Package metadata and dependencies
├── src/ric/
│   ├── _vertex.py             # Vertex AI client factory
│   ├── models.py              # Requirement data model
│   ├── demo.py                # Sample data for demo mode
│   ├── chat.py                # Chat Q&A module
│   ├── cli.py                 # Command-line interface
│   ├── adapters/
│   │   ├── fri.py             # FRI xlsx loader (Format C)
│   │   └── ri.py              # RI xlsx/csv loader (Format A)
│   ├── ioc/
│   │   ├── models.py          # IOC data models (IOCChange, ChangeType, etc.)
│   │   ├── parser.py          # LLM-based IOC PDF parser (Stage 1)
│   │   └── reader.py          # PDF text extraction (pdfplumber)
│   ├── matcher/
│   │   ├── models.py          # ChangeMatch, RequirementMatch models
│   │   ├── filter.py          # LA-scope pre-filter
│   │   └── matcher.py         # LLM-based requirement matcher (Stage 2+3)
│   ├── flagging/
│   │   ├── models.py          # RiskFlag, FlagSeverity models
│   │   └── flagger.py         # LLM-based risk flagger (Stage 4)
│   └── report/
│       ├── excel.py           # Excel report writer (openpyxl)
│       └── html.py            # HTML report writer
└── docs/
    ├── design-spec.md         # Original design specification
    └── inventory-format-report.md  # FRI/RI file format analysis
```

---

## Command-line usage

For batch/scripted runs without the UI:

```powershell
ric analyze --ioc "path\to\ioc.pdf" --fri "path\to\fri.xlsx" --output impact_analysis
```

Options:
```
--ioc FILE          IOC PDF to analyze (required)
--fri FILE [...]    One or more FRI xlsx files
--ri  FILE [...]    One or more RI xlsx or csv files
--paygroup CODE     Paygroup override (e.g. 025R)
--output BASENAME   Output filename without extension (default: impact_analysis)
--model MODEL       Gemini model ID (default: gemini-1.5-flash-001)
```

At least one `--fri` or `--ri` file is required.
