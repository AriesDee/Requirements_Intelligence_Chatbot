# Requirements Intelligence Chatbot (RIC)

A decision-support tool for the WFM Team that reads labor agreement documents and Requirements Inventories, then produces human-reviewed impact analyses identifying which timekeeping rules are affected and what actions analysts need to take.

RIC is a **read-only** tool — it never edits the inventory. The analyst stays fully in control; the tool's job is to make sure nothing gets overlooked.

---

## Modes

RIC has two operating modes, selectable from the sidebar:

| Mode | Description |
|---|---|
| **IOC / BRD Analysis** | Upload a labor agreement change document (IOC PDF or BRD Word doc) and your FRI/RI files. RIC extracts all changes, matches them to requirements, flags risks, and opens a chat for follow-up questions. |
| **Inventory Explorer** | Upload FRI or RI files only — no IOC or BRD required. RIC produces an inventory summary, AI quality check, and Excel export. Use this to audit a new file or review a paygroup's requirements independently. |

---

## What it does

### IOC / BRD Analysis
1. **Parses the document** — extracts every labor agreement change (wage rates, premiums, holidays, H&W, etc.) with its effective date, affected LAs, and source text.
2. **Matches changes to requirements** — for each change, identifies which requirements in your FRI/RI need review, rated as *Direct* (must update) or *Indirect* (verify).
3. **Generates delta descriptions** — concrete action statements telling the analyst exactly what to change, from what value to what, citing the effective date.
4. **Flags risks** — identifies retroactive pay deadlines, missing earn codes, ambiguous language, conflicting dates, and other blockers before implementation begins.
5. **Produces reports** — downloadable Excel and HTML reports with all findings.
6. **Chat / Q&A** — ask plain-English follow-up questions about the analysis results.

### Inventory Explorer
1. **Loads requirements** — parses all data sheets from uploaded FRI or RI files.
2. **Overview stats** — counts by section, Labor Agreement, scope type, and People Group.
3. **Gap detection** — flags requirements with missing scope codes or very short descriptions.
4. **AI quality check** — one Gemini call per file; identifies ambiguous language, missing implementation detail, potential duplicates, scope conflicts, and earn code mismatches with cross-section awareness.
5. **Excel export** — downloadable workbook with all requirements and quality findings.
6. **Chat / Q&A** — ask plain-English questions about the loaded requirements.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.11+ | [python.org](https://python.org) |
| Google Cloud project | With Vertex AI API enabled |
| Service account JSON | With `roles/aiplatform.user` or Vertex AI access; stored **outside** the repo |
| IOC document | PDF format (IOC / BRD Analysis mode only) |
| Requirements file | FRI (xlsx) and/or RI (xlsx or csv) |

---

## Setup

### 1. Install dependencies

```powershell
cd "Requirements-Intelligence-Chatbot"
python -m pip install -e ".[ui]" --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### 2. Place your service account credentials

Save your Google Cloud service account JSON file somewhere **outside** the repo (never commit it):

```
C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json
```

### 3. Set the credentials environment variable

In PowerShell — set for this session **and** persist to the Windows user profile:

```powershell
$credPath = "C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json"
[System.Environment]::SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", $credPath, "User")
$env:GOOGLE_APPLICATION_CREDENTIALS = $credPath
```

> After setting via the registry, new PowerShell sessions will inherit it automatically.
> For the **current** session you must also set `$env:GOOGLE_APPLICATION_CREDENTIALS`.

### 4. Run the app

```powershell
python -m streamlit run app.py
```

App opens at **http://localhost:8501**. If running on a server with a static IP address, teammates on the same VPN can reach it at `http://<server-ip>:8501`.

---

## Sidebar layout

The sidebar uses a **step-based layout** that guides you through the workflow. Steps are labeled 1–4 and always shown so you know what's coming next.

### IOC / BRD Analysis steps

| Step | Label | What to do |
|---|---|---|
| 1 | Documents | Choose document type (IOC PDF or BRD .docx), upload the document, upload FRI/RI files |
| 2 | Options | Select Gemini model, enter paygroup override if needed |
| 3 | Run | Click ▶ Run Analysis |
| 4 | Download | Download Excel or HTML report after analysis completes |

### Inventory Explorer steps

| Step | Label | What to do |
|---|---|---|
| 1 | Requirements | Upload FRI files and/or RI files (1 RI + associated FRIs per run recommended) |
| 2 | Options | Select Gemini model |
| 3 | Load | Click ▶ Load Inventory |
| 4 | Export & Analyze | Download Excel export or run AI quality check |

> **RI + FRI uploads:** Upload 1 RI and all FRI files that belong to that contract in a single run. Uploading multiple RIs from different contracts is supported but the quality check will analyze each file independently.

---

## AI Connection Status panel

The **AI Connection Status** expander appears at the top of the sidebar, just below the RIC header. It shows whether Gemini AI features (quality check and chat) are working and how long the service account key is valid.

### Reading the label

The expander label updates automatically on every page load:

| Label | Meaning |
|---|---|
| 🟢 AI Connected · Key expires in N days | Connected; key is healthy (>45 days remaining) |
| 🟡 AI Connected · Key expires in N days | Connected; key rotation should be planned (15–45 days remaining) |
| 🔴 AI Connected · Key expires in N days | Connected but key rotation is urgent (≤14 days remaining) |
| 🔴 AI: Connection Failed | Cannot connect to Vertex AI — AI features will not work |
| 🤖 AI Status — not yet tested | First load not yet complete (auto-test runs on startup) |

### Inside the expander

Expand the panel to see:

| Field | Description |
|---|---|
| Project | GCP project ID |
| Account Type | Should be `service_account` |
| Client Email | The service account email |
| Key ID | First 16 characters of the private key ID |
| Connected ✓ / Failed ✗ | Result of the last connection test with timestamp |
| Created | Key creation date/time (local timezone with UTC offset) |
| Expires | Key expiry date/time with days-remaining count |

### Key rotation reminders

| Days remaining | Indicator |
|---|---|
| > 45 | Green — no action needed |
| 31–45 | Yellow — plan rotation |
| 15–30 | Yellow — rotate soon |
| ≤ 14 | Red — rotate immediately |

### Where credentials come from

The app reads the `GOOGLE_APPLICATION_CREDENTIALS` **Windows User environment variable**, which holds the path to the service account JSON file. This variable is set once via PowerShell and persists across sessions (see Setup). The JSON file itself lives outside the repo at a path like:

```
C:\Users\<you>\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json
```

### Re-test button

The connection is tested automatically on the first page load. Click **Re-test Connection** to re-run the test without restarting the app.

**Use Re-test when:**
- You rotated the key — replaced the JSON file at the same path. The app already loaded the old key; Re-test picks up the new file immediately.
- VPN dropped and reconnected — Re-test confirms the network path to GCP is live again.
- A quality check or chat failed mid-session — Re-test confirms whether the AI connection itself is broken or whether the failure was unrelated (bad input, rate limit, etc.).
- The app has been running overnight — Re-test gives a fresh timestamp before starting a long analysis run.
- You fixed a bad credential file (e.g., re-downloaded due to encoding error) — Re-test validates the fix without restarting.

**Re-test does NOT help when:**
- `GOOGLE_APPLICATION_CREDENTIALS` was never set, or was changed to a different path after the app started — the app reads the environment at startup and cannot see changes made after. **Restart the app** in a new terminal session where the variable is correctly set.
- The GCP project or Vertex AI API is not enabled — Re-test will still fail; resolve the GCP-side issue first.

### Production deployment note

> **The credential panel is designed for the current Windows on-prem / laptop setup.**
> If the production deployment path changes (e.g., GCP Cloud Run with Application Default Credentials, Docker with a secrets manager, or a Linux server), the credential panel in `app.py` will need code updates because it assumes a JSON file on disk pointed to by `GOOGLE_APPLICATION_CREDENTIALS`. Specifically:
> - The AI features themselves (`_vertex.py`, quality check, chat) will likely work without changes on any platform.
> - The panel's file-reading block, the project/email/key ID display, and the IAM key-expiry API call all depend on a JSON file being present.
> - See `docs/deployment.md` → Production Deployment Considerations for details on what each deployment path requires.

### Key rotation process

When a key is near expiry:
1. Create a new key for the service account in GCP IAM console
2. Download the new JSON file and replace the existing credential file at the path in `GOOGLE_APPLICATION_CREDENTIALS`
3. Click **Re-test Connection** — the expander label should update to reflect the new expiry date

---

## File format reference

### IOC PDF
Standard Inter-Office Communication memo from Labor Relations. Must be a text-based PDF (not a scanned image). One IOC per run.

### BRD (.docx)
Business Requirements Document in Word format. One BRD per run.

### FRI (Format C — Foundational Requirements Inventory)
- File type: `.xlsx`
- Template: FRI Standard Template
- Sheets: one sheet per population; metadata sheets (Legend, Lists, Change History, etc.) are skipped automatically
- Paygroup: inferred from a 2–4 character code in the filename (e.g. `087`, `025R`, `34B`); use the Paygroup Override field if not present
- Header detection: the adapter scans the first 5 rows to find the real header, so files with junk rows above the header are handled automatically

### RI (Format A — Requirements Inventory)
- File type: `.xlsx` or `.csv`
- Structure: multi-sheet xlsx where each tab (master contract) covers one or more Labor Agreements for the paygroup; section-header rows separate requirement categories within each tab; LA scope is embedded in the description text or implicit from the sheet header
- One RI file contains all Labor Agreements for the entire paygroup — not just one contract
- Paygroup: same inference rules as FRI

> You can upload FRI and RI files together in a single run. The tool combines them and labels each requirement with its source (`FRI` or `RI`) and paygroup.

---

## Gemini model selection

The default model is `gemini-2.5-flash`. Available options in the sidebar:

| Model | Speed | Quality | Notes |
|---|---|---|---|
| `gemini-2.5-flash` | Fast | Good | Default; recommended for most analyses |
| `gemini-2.5-flash-lite` | Fastest | Adequate | Use for very large files where speed matters |
| `gemini-2.5-pro` | Slower | Best | Use for complex IOCs or when flash misses matches |

---

## Troubleshooting

**AI Connection Status shows 🔴 AI: Connection Failed**
Open the expander to see the error detail. Common causes:
- `GOOGLE_APPLICATION_CREDENTIALS` not set in the terminal session running Streamlit — set it (`$env:GOOGLE_APPLICATION_CREDENTIALS = "..."`) and restart the app; Re-test Connection will not help here since the variable is read at startup
- Credential file path is wrong or file doesn't exist — verify with `Test-Path $env:GOOGLE_APPLICATION_CREDENTIALS`
- Key has expired — rotate the service account key (see Key rotation process above), then click Re-test Connection
- VPN disconnected or firewall blocking `iam.googleapis.com` — reconnect and click Re-test Connection

**AI Connection Status shows 🤖 AI Status — not yet tested after several seconds**
The auto-test could not find a valid credential file. Check that `GOOGLE_APPLICATION_CREDENTIALS` is set and points to an existing JSON file.

**Re-test Connection button keeps showing Failed after fixing credentials**
If you changed `GOOGLE_APPLICATION_CREDENTIALS` to a new path (not just replaced the JSON file), the running app cannot see the new value — restart the app in a terminal where the variable is correctly set. Re-test only helps when the JSON file itself changed at the same path.

**Credential file encoding error (`'utf-8' codec can't decode byte...`)**
The JSON credential file was saved with a non-UTF-8 encoding. The app tries `utf-8-sig`, `utf-8`, and `latin-1` automatically — if all fail, re-download the key from GCP IAM console.

**`404 NOT_FOUND: Publisher model was not found`**
The selected Gemini model isn't available in your project or region. Switch to `gemini-2.5-flash` in the sidebar, or check that the Vertex AI API is enabled in your GCP project.

**`ValueError: Cannot infer paygroup from path`**
The filename doesn't contain a recognizable paygroup code. Enter the paygroup manually in the **Paygroup Override** field.

**Load Inventory shows an error with a traceback**
An error box with the full traceback will appear below the Load button. Read the traceback — the most common causes are:
- Excel file is password-protected
- File is not a valid FRI/RI format (wrong template version)
- File has an unusual encoding

**Scanned/image PDFs produce no changes**
The IOC must be a text-based PDF. If your IOC was scanned, ask Labor Relations for the original digital version.

---

## Paygroup codes

The paygroup is a 2–4 character code used to label requirements and make IDs unique across files. Common codes:

| Division | Paygroup |
|---|---|
| NorCal Retail | 025R |
| NorCal Non-Retail | 025 |
| Seattle Retail | 027 |
| Haggen | 087 |

If the filename doesn't contain the paygroup code, enter it in the **Paygroup Override** field before uploading.

---

## Project structure

```
Requirements-Intelligence-Chatbot/
├── app.py                          # Streamlit UI (both modes)
├── pyproject.toml                  # Package metadata and dependencies
├── src/ric/
│   ├── _vertex.py                  # Vertex AI client factory
│   ├── models.py                   # Requirement data model
│   ├── chat.py                     # Chat Q&A module (IOC/BRD mode)
│   ├── cli.py                      # Command-line interface
│   ├── adapters/
│   │   ├── fri.py                  # FRI xlsx loader (Format C)
│   │   └── ri.py                   # RI xlsx/csv loader (Format A)
│   ├── ioc/
│   │   ├── models.py               # IOC data models (IOCChange, ChangeType, etc.)
│   │   ├── parser.py               # LLM-based IOC PDF parser
│   │   └── reader.py               # PDF text extraction (pdfplumber)
│   ├── matcher/
│   │   ├── models.py               # ChangeMatch, RequirementMatch models
│   │   ├── filter.py               # LA-scope pre-filter
│   │   └── matcher.py              # LLM-based requirement matcher
│   ├── flagging/
│   │   ├── models.py               # RiskFlag, FlagSeverity models
│   │   └── flagger.py              # LLM-based risk flagger
│   ├── inventory/
│   │   ├── analyzer.py             # Pure-Python inventory statistics and gap detection
│   │   ├── quality.py              # LLM-based quality checker (per-file, cross-section)
│   │   └── chat.py                 # Inventory chat context builder
│   └── report/
│       ├── excel.py                # Excel report writer (openpyxl)
│       └── html.py                 # HTML report writer
└── docs/
    ├── design-spec.md              # Original design specification
    ├── inventory-format-report.md  # FRI/RI file format analysis
    ├── technical-spec.md           # Technical implementation details
    └── deployment.md               # Deployment and hosting notes
```

---

## Security notes

- The service account JSON is stored **outside** the repository and referenced only via `GOOGLE_APPLICATION_CREDENTIALS`. Never commit it.
- API keys are stored as Windows User environment variables — not hardcoded in the app.
- User email addresses are used only for identification within the app and are never sent to external services.
- RIC never writes to or modifies your FRI/RI files.
