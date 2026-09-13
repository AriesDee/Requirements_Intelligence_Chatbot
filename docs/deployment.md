# RIC — Local Network Deployment Guide

How to host the app on your laptop so colleagues on the same Albertsons network or VPN can access it for testing.

---

## One-Time Setup

### 1. Find your laptop's IP address

```powershell
ipconfig | Select-String "IPv4"
```

   IPv4 Address. . . . . . . . . . . : 10.14.136.74
   IPv4 Address. . . . . . . . . . . : 192.168.1.140

Note the address (e.g. `10.45.12.87`). This is what you share with testers.

### 2. Open Windows Firewall for port 8501

Run PowerShell **as Administrator**, then:

```powershell
New-NetFirewallRule -DisplayName "RIC Streamlit" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow
```

You only need to do this once. To remove it later:

```powershell
Remove-NetFirewallRule -DisplayName "RIC Streamlit"
```

---

## Every Time You Want to Host

Run this in a regular PowerShell window (no need for Admin):

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json"
streamlit run "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\Documents\GitHub\Requirements-Intelligence-Chatbot\app.py" --server.address 0.0.0.0 --server.port 8501
```

Then share the URL with your testers:

```
http://<your-ip>:8501
```

Example: `http://10.45.12.87:8501`

The app stays up as long as this terminal window is open. Close the window to shut it down.

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "Site can't be reached" | Firewall rule not applied | Re-run the `New-NetFirewallRule` step as Admin |
| "Site can't be reached" | Colleague not on VPN | Ask them to connect to VPN first |
| App loads but analysis fails | Credentials env var not set | Make sure the `$env:GOOGLE_APPLICATION_CREDENTIALS` line ran in the same terminal |
| URL stopped working mid-session | Laptop went to sleep | Go to Power Options and set "Sleep" to Never while on AC power |

---

## Notes

- Your laptop IP can change if you reconnect to Wi-Fi. Re-run `ipconfig` if the URL stops working.
- Each colleague gets their own independent session in their browser — uploads and results are not shared between users.
- The Gemini API is called once per analysis run, so multiple testers running analyses at the same time will each consume separate API quota.



### Option 2 — ngrok (access from outside VPN)

Install ngrok once, authenticate with your authtoken from ngrok.com, then run two terminals:

**Terminal 1 — start the app:**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\.credentials\ric-vertex-sa.json"
streamlit run "C:\Users\adomi01.SAFEWAY01\OneDrive - Safeway, Inc\Documents\GitHub\Requirements-Intelligence-Chatbot\app.py" --server.port 8501
```

**Terminal 2 — create the tunnel:**
```powershell
ngrok http 8501
```

Ngrok prints a URL like `https://abc123.ngrok-free.app` — share that with teammates. No VPN required. The URL changes each time ngrok restarts on the free plan.

---

## Production Deployment Considerations

> **Current status:** RIC runs on a developer laptop for team testing. This section documents what needs to change if/when production hosting is set up.

### What works on any platform without code changes

The AI features — Vertex AI calls, quality check, chat, IOC/BRD analysis — all use the `google-genai` library which supports Application Default Credentials (ADC) transparently. No code change is needed for these features regardless of where the app is hosted.

### What requires code changes: the AI Connection Status panel

The credential panel in `app.py` was built for the current laptop setup and has three assumptions that break in cloud or container deployments:

| Assumption | Code location | Breaks when |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` points to a JSON file on disk | `_cred_path = os.getenv(...)` + `open(_cred_path)` | GCP ADC / Workload Identity (no JSON file) |
| JSON file contains `project_id`, `client_email`, `private_key_id` | Panel metadata display block | Same — no file to read |
| Service account has a rotatable key with an expiry date | IAM API call for `validAfterTime` / `validBeforeTime` | VM-attached service accounts have no key expiry |

### Deployment paths and required code changes

**Windows on-prem server (least change)**
- Set `GOOGLE_APPLICATION_CREDENTIALS` as a System environment variable pointing to the JSON file in a secured folder.
- No code changes. The credential panel works as-is.

**GCP (Cloud Run, Compute Engine, GKE) with Workload Identity / ADC**
- Attach the service account to the VM or container — no JSON file needed.
- AI features work automatically via ADC.
- Credential panel needs a fallback: detect ADC via `google.auth.default()`, read project/email from the token metadata, and replace the key-expiry display with a note that no key rotation is required (attached accounts don't expire).

**Docker container with mounted JSON secret**
- Mount the JSON file as a volume secret at a known path; set `GOOGLE_APPLICATION_CREDENTIALS` to that path in the container environment.
- No code changes. Same as on-prem.

**Docker container / any host with a secrets manager (GCP Secret Manager, Azure Key Vault)**
- The JSON content is fetched at startup from the secrets manager API rather than read from disk.
- Code change needed: replace the `open(_cred_path)` file-reading block with a secrets manager fetch that returns the parsed JSON dict. The rest of the panel (IAM expiry check, display) can stay the same since `_run_cred_test()` already uses `from_service_account_info()` (dict-based, not file-based).

### Summary

| If moving to… | AI features | Credential panel |
|---|---|---|
| On-prem Windows server | No change | No change |
| Docker + mounted JSON | No change | No change |
| GCP with ADC / Workload Identity | No change | **Needs ADC fallback** |
| Any host + secrets manager | No change | **Needs secrets manager fetch** |

When the production deployment path is decided, update `app.py` in the credential loading block (the section labeled `# Credential loading & auto-test`) and the `_run_cred_test()` function accordingly.

