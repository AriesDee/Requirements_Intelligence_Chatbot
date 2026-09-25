"""
Requirements Intelligence Chatbot — Streamlit UI.

Run with:
    streamlit run app.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Make src/ric importable whether running locally or on Streamlit Cloud
sys.path.insert(0, str(Path(__file__).parent / "src"))

import openpyxl
import streamlit as st

# ── GCP credentials bootstrap (Streamlit Community Cloud) ────────────────────
# Locally the GOOGLE_APPLICATION_CREDENTIALS env var points to the JSON file.
# On Streamlit Cloud, paste the JSON fields under [gcp_service_account] in
# the app's Secrets UI — this block writes them to a temp file automatically.
if "gcp_service_account" in st.secrets and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    _sa_dict = dict(st.secrets["gcp_service_account"])
    _sa_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(_sa_dict, _sa_tmp)
    _sa_tmp.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _sa_tmp.name


def _status_pill(ok: bool, label: str) -> str:
    if ok:
        return (f'<div style="display:flex;align-items:center;gap:6px;margin:3px 0;">'
                f'<span style="width:8px;height:8px;border-radius:50%;background:#1e7e45;flex-shrink:0;"></span>'
                f'<span style="font-size:1rem;color:#1a3a2a;font-weight:600;">{label}</span></div>')
    return (f'<div style="display:flex;align-items:center;gap:6px;margin:3px 0;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:#c5cfe0;flex-shrink:0;"></span>'
            f'<span style="font-size:1rem;color:#8a96aa;">{label}</span></div>')


def _detect_format(path: Path) -> str:
    """Return 'FRI' if the file looks like a FRI Standard Template, else 'RI'."""
    if path.suffix.lower() == ".csv":
        return "RI"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for name in wb.sheetnames:
                ws = wb[name]
                row = next(ws.iter_rows(values_only=True), None)
                if row and any(str(c or "").strip() == "People Group" for c in row):
                    return "FRI"
        finally:
            wb.close()
    except Exception:
        pass
    return "RI"

st.set_page_config(
    page_title="RIC — Requirements Intelligence Chatbot",
    page_icon="📋",
    layout="wide",
    menu_items={
        "About": "Requirements Intelligence Chatbot (RIC) — Labor Agreement Impact Analysis Tool",
    },
)

# ---- Custom theme ----
st.markdown("""
<style>
/* ── Base font ──────────────────────────────────────────────────────── */
html, body, [class*="css"], .stMarkdown, .stText,
button, input, select, textarea, label {
    font-family: 'Segoe UI', Calibri, 'Trebuchet MS', Arial, sans-serif !important;
    font-size: 1rem !important;
}

/* ── Main content text ──────────────────────────────────────────────── */
.main p, .main li, .main span,
.stMarkdown p, .stMarkdown li,
.stCaption, .stText,
[data-testid="stChatMessage"] p {
    font-size: 1rem !important;
    line-height: 1.6;
}
.main label,
.stSelectbox label, .stTextInput label,
.stTextArea label, .stFileUploader label,
.stRadio label, .stCheckbox label,
.stNumberInput label, .stToggle label {
    font-size: 1rem !important;
    font-weight: 600;
}
/* Selectbox, input, textarea values */
div[data-baseweb="select"] span,
input[type="text"], textarea {
    font-size: 1rem !important;
}
/* Tab labels */
[data-baseweb="tab"] {
    font-size: 1rem !important;
}

/* ── Top accent bar ──────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"]::before {
    content: "";
    display: block;
    height: 4px;
    background: linear-gradient(90deg, #1a4a8a 0%, #2e7dd1 60%, #5ba3e8 100%);
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 9999;
}

/* ── Main content ────────────────────────────────────────────────────── */
.main .block-container {
    padding-top: 1rem;
    padding-bottom: 1.5rem;
    max-width: 1300px;
}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #f0f4f8;
    border-right: 2px solid #d0dcea;
}
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label,
[data-testid="stSidebar"] .stFileUploader label,
[data-testid="stSidebar"] .stToggle label,
[data-testid="stSidebar"] p {
    font-size: 1rem !important;
    color: #3a3a5c;
}
/* Radio button options */
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
    font-size: 1rem !important;
}
/* Select box and text input values */
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] span,
[data-testid="stSidebar"] .stTextInput input {
    font-size: 1rem !important;
}
[data-testid="stSidebar"] h1 {
    color: #1a4a8a;
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: 0.02em;
}
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #1a4a8a;
    font-size: 1rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 0.8rem;
}

/* ── Page headings ───────────────────────────────────────────────────── */
h1 { color: #1a4a8a; font-size: 1.9rem !important; font-weight: 700; }
h2 { color: #1a4a8a; font-size: 1.35rem !important; font-weight: 600; }
h3 { color: #2c5f8a; font-size: 1.15rem !important; font-weight: 600; }

/* ── Metric tiles ────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #d0dcea;
    border-radius: 10px;
    padding: 1rem 1.2rem 0.8rem;
    border-top: 3px solid #1a4a8a;
    box-shadow: 0 1px 4px rgba(26,74,138,0.07);
}
[data-testid="stMetricLabel"] {
    font-size: 0.82rem !important;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #6b7a99 !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.8rem !important;
    font-weight: 700;
    color: #1a4a8a !important;
}

/* ── Primary button (Run Analysis, Load Inventory) ───────────────────── */
[data-testid="stButton"] > button[kind="primary"] {
    background-color: #1a4a8a !important;
    border: none;
    border-radius: 7px;
    padding: 0.55rem 1.2rem;
    transition: background-color 0.2s;
}
[data-testid="stButton"] > button[kind="primary"] p,
[data-testid="stButton"] > button[kind="primary"] div {
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    letter-spacing: 0.03em;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #14387a !important;
}
[data-testid="stButton"] > button[kind="primary"]:disabled {
    background-color: #9babc8 !important;
}
[data-testid="stButton"] > button[kind="primary"]:disabled p,
[data-testid="stButton"] > button[kind="primary"]:disabled div {
    color: #dde4ef !important;
}

/* ── Download buttons ────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    background-color: #1e7e45 !important;
    border: none;
    border-radius: 7px;
    padding: 0.5rem 1rem;
    transition: background-color 0.2s;
}
[data-testid="stDownloadButton"] > button p,
[data-testid="stDownloadButton"] > button div {
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #165c32 !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────── */
[data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 2px solid #d0dcea;
    padding-bottom: 0;
}
[data-baseweb="tab"] {
    border-radius: 7px 7px 0 0;
    font-weight: 600;
    font-size: 0.95rem;
    padding: 0.5rem 1.2rem;
    color: #6b7a99;
    border: 1px solid transparent;
    border-bottom: none;
}
[aria-selected="true"][data-baseweb="tab"] {
    background-color: #ffffff;
    color: #1a4a8a;
    border-color: #d0dcea;
    border-bottom-color: #ffffff;
    margin-bottom: -2px;
}

/* ── Expanders ───────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #d0dcea;
    border-radius: 8px;
    margin-bottom: 0.6rem;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(26,74,138,0.05);
}
[data-testid="stExpander"] summary {
    font-size: 0.95rem;
    font-weight: 600;
    padding: 0.65rem 1rem;
    background: #f7f9fc;
    border-radius: 7px;
}
[data-testid="stExpander"] summary:hover {
    background: #eef2f9;
}
/* ── AI Connection Status expander — distinct header ─────────────────── */
[data-testid="stSidebar"] [data-testid="stExpander"] {
    border: 1px solid #d0dcea;
    border-left: 4px solid #1a4a8a;
    border-radius: 8px;
    box-shadow: 0 2px 6px rgba(26,74,138,0.10);
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    background: #eef4fb;
    border-radius: 6px;
    font-size: 1.05rem !important;
    font-weight: 800 !important;
    color: #1a4a8a !important;
    letter-spacing: 0.02em;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    font-size: 1.05rem !important;
    font-weight: 800 !important;
    color: #1a4a8a !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: #eef2f9;
}

/* ── Containers with border (flag cards) ─────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 8px;
    border-color: #d0dcea !important;
    background: #fafbfd;
}

/* ── Dataframe ───────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #d0dcea;
    border-radius: 8px;
    overflow: hidden;
}

/* ── Progress bar ────────────────────────────────────────────────────── */
[data-testid="stProgressBar"] > div > div {
    background: linear-gradient(90deg, #1a4a8a, #2e7dd1);
    border-radius: 4px;
}

/* ── Status / st.status ──────────────────────────────────────────────── */
[data-testid="stStatusWidget"] {
    border-radius: 8px;
    border-color: #d0dcea;
}

/* ── Info / Warning / Error boxes ────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px;
    font-size: 0.95rem;
}

/* ── Code blocks (source text) ───────────────────────────────────────── */
[data-testid="stCode"] {
    border-radius: 6px;
    border: 1px solid #d0dcea;
    background: #f7f9fc !important;
    font-size: 0.82rem;
}

/* ── Dividers ────────────────────────────────────────────────────────── */
hr {
    border-color: #d0dcea;
    margin: 1rem 0;
}

/* ── Captions / small labels ─────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    font-size: 0.85rem;
    color: #6b7a99;
}

/* ── Chat messages ───────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
    font-size: 0.95rem;
    border: 1px solid #e4eaf5;
}

/* ── Selectbox / file uploader labels ────────────────────────────────── */
[data-testid="stSelectbox"] label,
[data-testid="stFileUploader"] label,
[data-testid="stTextInput"] label,
[data-testid="stRadio"] label {
    font-size: 0.9rem;
    font-weight: 600;
    color: #3a3a5c;
}

/* ── Toggle ──────────────────────────────────────────────────────────── */
[data-testid="stToggle"] label {
    font-size: 0.9rem;
    font-weight: 600;
    color: #1a4a8a;
}
</style>
""", unsafe_allow_html=True)

# ---- Session state init ----
for _k in ("ioc", "results", "requirements", "excel_data", "html_data", "output_name",
           "chat_history", "chat_context", "chat_is_demo", "input_doc_type",
           "inv_requirements", "inv_excel_data", "inv_stats", "inv_output_name",
           "inv_quality_issues", "inv_chat_history", "inv_chat_context"):
    if _k not in st.session_state:
        st.session_state[_k] = None


# ---- Sidebar ----
with st.sidebar:
    st.markdown("""
    <div style="padding: 0.8rem 0 1.2rem 0; border-bottom: 2px solid #d0dcea; margin-bottom: 1rem;">
        <div style="font-size: 1rem; font-weight: 700; letter-spacing: 0.10em;
                    text-transform: uppercase; color: #6b7a99; margin-bottom: 4px;">
            Workforce Management (WFM)
        </div>
        <div style="font-size: 2.8rem; font-weight: 800; color: #1a4a8a;
                    letter-spacing: -0.02em; line-height: 1.05;">
            RIC
        </div>
        <div style="font-size: 1.2rem; color: #4a6080; font-weight: 500; margin-top: 4px;">
            Requirements Intelligence Chatbot
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ---- Credential loading & auto-test (runs before expander so label is current) ----
    _cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    _sa_info   = None
    _sa_load_error = None
    if _cred_path and os.path.exists(_cred_path):
        try:
            import json as _json
            for _enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    with open(_cred_path, encoding=_enc) as _cf:
                        _sa_info = _json.load(_cf)
                    break
                except (UnicodeDecodeError, ValueError):
                    continue
            if not _sa_info:
                _sa_load_error = "Could not parse credential file (encoding issue)."
        except Exception as _e:
            _sa_load_error = f"Could not read credential file: {_e}"

    def _fmt_ts(ts):
        from datetime import datetime as _dt
        try:
            _utc   = _dt.fromisoformat(ts.replace("Z", "+00:00"))
            _local = _utc.astimezone()
            _off   = _local.strftime("%z")
            return _local.strftime("%Y-%m-%d %H:%M") + f" (UTC{_off[:3]}:{_off[3:]})"
        except Exception:
            return ts

    def _parse_exp_dt(ts):
        from datetime import datetime as _dt
        try:
            return _dt.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    def _now_fmt():
        from datetime import datetime as _dt
        _local = _dt.now().astimezone()
        _off   = _local.strftime("%z")
        return _local.strftime("%Y-%m-%d %H:%M") + f" (UTC{_off[:3]}:{_off[3:]})"

    def _run_cred_test(sa_info):
        from google.oauth2 import service_account as _sa_mod
        import google.auth.transport.requests as _gtr
        import requests as _req
        if not sa_info:
            raise ValueError("Could not parse credential file — check encoding.")
        _creds = _sa_mod.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _creds.refresh(_gtr.Request())
        _key_meta = {}
        try:
            _proj    = sa_info.get("project_id", "")
            _sa_mail = sa_info.get("client_email", "")
            _kid     = sa_info.get("private_key_id", "")
            _iam_url = (f"https://iam.googleapis.com/v1/projects/{_proj}"
                        f"/serviceAccounts/{_sa_mail}/keys/{_kid}")
            _resp = _req.get(_iam_url,
                             headers={"Authorization": f"Bearer {_creds.token}"},
                             timeout=10)
            if _resp.ok:
                _kdata = _resp.json()
                _key_meta = {
                    "created":    _fmt_ts(_kdata.get("validAfterTime", "")),
                    "expires":    _fmt_ts(_kdata.get("validBeforeTime", "")),
                    "expires_dt": _parse_exp_dt(_kdata.get("validBeforeTime", "")),
                }
        except Exception:
            pass
        return _key_meta

    if "cred_last_tested" not in st.session_state:
        st.session_state.cred_last_tested = None
        st.session_state.cred_last_status = None
        st.session_state.cred_key_meta    = None

    if st.session_state.cred_last_tested is None and _sa_info:
        try:
            _key_meta = _run_cred_test(_sa_info)
            st.session_state.cred_last_tested = _now_fmt()
            st.session_state.cred_last_status = True
            st.session_state.cred_key_meta    = _key_meta
        except Exception as _ce:
            st.session_state.cred_last_tested = _now_fmt()
            st.session_state.cred_last_status = str(_ce)
            st.session_state.cred_key_meta    = None

    # Build dynamic expander label
    if st.session_state.cred_last_tested is None:
        _ai_exp_label = "🤖 AI Status — not yet tested"
    elif st.session_state.cred_last_status is True:
        _meta_lbl = st.session_state.cred_key_meta or {}
        _exp_dt_lbl = _meta_lbl.get("expires_dt")
        if _exp_dt_lbl:
            from datetime import datetime as _dtl, timezone as _tzl
            _days_lbl = (_exp_dt_lbl - _dtl.now(_tzl.utc)).days
            if _days_lbl <= 14:
                _ai_exp_label = f"🔴 AI Connected · Key expires in {_days_lbl} days"
            elif _days_lbl <= 45:
                _ai_exp_label = f"🟡 AI Connected · Key expires in {_days_lbl} days"
            else:
                _ai_exp_label = f"🟢 AI Connected · Key expires in {_days_lbl} days"
        else:
            _ai_exp_label = "🟢 AI Connected"
    else:
        _ai_exp_label = "🔴 AI: Connection Failed"

    # ---- AI Connection Status expander (just below header, collapsed by default) ----
    with st.expander(_ai_exp_label, expanded=False):
        st.caption(
            "AI features (quality check and chat) use the GCP service account set in the "
            "GOOGLE_APPLICATION_CREDENTIALS Windows User environment variable. "
            "The connection is tested automatically on first load. "
            "Use Re-test Connection after rotating a key, reconnecting VPN, or diagnosing "
            "an AI failure — but not after changing the environment variable itself "
            "(that requires a full app restart)."
        )
        if not _cred_path or not os.path.exists(_cred_path):
            st.error("Credential file not found.\nSet GOOGLE_APPLICATION_CREDENTIALS.")
        elif _sa_load_error:
            st.error(_sa_load_error)
        elif _sa_info:
            st.markdown(f"**Project:** `{_sa_info.get('project_id', 'unknown')}`")
            st.markdown(f"**Account Type:** `{_sa_info.get('type', 'unknown')}`")
            st.markdown(f"**Client Email:** `{_sa_info.get('client_email', 'unknown')}`")
            st.markdown(f"**Key ID:** `{_sa_info.get('private_key_id', 'unknown')[:16]}…`")

        if st.session_state.cred_last_tested:
            if st.session_state.cred_last_status is True:
                st.success(f"Connected ✓  — tested {st.session_state.cred_last_tested}")
                _meta = st.session_state.cred_key_meta
                if _meta:
                    st.markdown(f"**Created:** {_meta.get('created', 'n/a')}")
                    _exp    = _meta.get("expires", "")
                    _exp_dt = _meta.get("expires_dt")
                    if _exp and "9999" not in _exp and _exp_dt:
                        from datetime import datetime as _dt2, timezone as _tz2
                        _days_left = (_exp_dt - _dt2.now(_tz2.utc)).days
                        if _days_left <= 14:
                            st.error(f"**Expires:** {_exp}  \n🚨 **{_days_left} days left — rotate immediately!**")
                        elif _days_left <= 30:
                            st.warning(f"**Expires:** {_exp}  \n⚠️ **{_days_left} days left — rotate soon.**")
                        elif _days_left <= 45:
                            st.warning(f"**Expires:** {_exp}  \n⏳ **{_days_left} days left** — plan rotation.")
                        else:
                            st.success(f"**Expires:** {_exp}  \n✓ **{_days_left} days remaining**")
                    elif _exp and "9999" not in _exp:
                        st.markdown(f"**Expires:** {_exp}")
                    else:
                        st.markdown("**Expires:** No expiry set")
            else:
                st.error(f"Failed ✗  — tested {st.session_state.cred_last_tested}\n{st.session_state.cred_last_status}")

        if st.button("Re-test Connection", use_container_width=True, key="cred_test_btn",
                     help="Re-runs the GCP connection test without restarting the app. "
                          "Use after: rotating a key (replaced the JSON file), reconnecting VPN, "
                          "or diagnosing an AI failure mid-session. "
                          "Does NOT help if GOOGLE_APPLICATION_CREDENTIALS was never set — "
                          "that requires restarting the app in a new terminal session."):
            try:
                _key_meta = _run_cred_test(_sa_info)
                st.session_state.cred_last_tested = _now_fmt()
                st.session_state.cred_last_status = True
                st.session_state.cred_key_meta    = _key_meta
                st.rerun()
            except Exception as _ce:
                st.session_state.cred_last_tested = _now_fmt()
                st.session_state.cred_last_status = str(_ce)
                st.session_state.cred_key_meta    = None
                st.rerun()

    st.markdown('<div style="margin-bottom:6px;"></div>', unsafe_allow_html=True)

    st.markdown('<div style="font-size:0.95rem;font-weight:700;color:#3a3a5c;margin-bottom:4px;">Select Mode</div>', unsafe_allow_html=True)
    app_mode = st.radio(
        "Select Mode",
        ["IOC / BRD Analysis", "Inventory Explorer"],
        label_visibility="collapsed",
        horizontal=True,
    )
    st.markdown("""
    <div style="font-size:0.82rem; color:#6b7a99; line-height:1.5; margin-top:2px; margin-bottom:4px;">
        <b style="color:#3a3a5c;">IOC / BRD Analysis</b> — impact analysis from a change document<br>
        <b style="color:#3a3a5c;">Inventory Explorer</b> — standalone quality check &amp; export
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<hr style="margin:6px 0 10px 0; border:none; border-top:1px solid #d0dcea;">', unsafe_allow_html=True)

    if app_mode == "IOC / BRD Analysis":
        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;">Step 1 — Documents</div>', unsafe_allow_html=True)
        doc_type = st.radio(
            "Document type",
            ["IOC (PDF)", "BRD (Word .docx)"],
            horizontal=True,
            help="Upload an IOC memo PDF or a Business Requirements Document (.docx).",
        )
        if doc_type == "IOC (PDF)":
            ioc_file = st.file_uploader(
                "IOC Document (PDF)",
                type=["pdf"],
                help="The Inter-Office Communication PDF to analyze.",
            )
            brd_file = None
        else:
            brd_file = st.file_uploader(
                "BRD Document (.docx)",
                type=["docx"],
                help="Business Requirements Document in Word format.",
            )
            ioc_file = None

        st.markdown("**Requirements files** — at least one required")
        fri_files = st.file_uploader(
            "FRI files (xlsx)",
            type=["xlsx"],
            accept_multiple_files=True,
            key="fri",
            help="Foundational Requirements Inventory xlsx files. Upload FRI, RI, or both.",
        )
        ri_files = st.file_uploader(
            "RI files (xlsx / csv)",
            type=["xlsx", "csv"],
            accept_multiple_files=True,
            key="ri",
            help="Requirements Inventory xlsx or csv files. Upload FRI, RI, or both.",
        )
        paygroup_input = st.text_input(
            "Paygroup override",
            placeholder="e.g. 087  (inferred from filename if blank)",
        )
        output_name = st.text_input("Report filename (no extension)", value="impact_analysis")

        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:4px;">Step 2 — Options</div>', unsafe_allow_html=True)
        model = st.selectbox(
            "Gemini model",
            ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
            index=0,
            help="gemini-2.5-flash is fast and capable; 2.5-pro is most accurate.",
        )

        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:4px;">Step 3 — Run</div>', unsafe_allow_html=True)

        _doc_ok  = bool(ioc_file) or bool(brd_file)
        _reqs_ok = bool(fri_files) or bool(ri_files)
        _key_ok  = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

        _doc_label = "IOC uploaded" if doc_type == "IOC (PDF)" else "BRD uploaded"
        st.markdown(
            _status_pill(_doc_ok, _doc_label) +
            _status_pill(_reqs_ok, "Requirements uploaded") +
            _status_pill(_key_ok, "Credentials set"),
            unsafe_allow_html=True,
        )

        can_run = _doc_ok and _reqs_ok and _key_ok
        run_btn = st.button(
            "▶  Run Analysis",
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )
        demo_btn = False
        inv_load_btn = False
        quality_btn = False

        # Download buttons for IOC/BRD mode
        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:12px;">Step 4 — Download</div>', unsafe_allow_html=True)

        if st.session_state.excel_data:
            _out = st.session_state.output_name or "impact_analysis"
            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    "⬇ Excel",
                    data=st.session_state.excel_data,
                    file_name=f"{_out}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            with dl2:
                st.download_button(
                    "⬇ HTML",
                    data=st.session_state.html_data,
                    file_name=f"{_out}.html",
                    mime="text/html",
                    use_container_width=True,
                )
        else:
            st.caption("Run analysis first to enable downloads.")

    else:  # Inventory Explorer
        demo_btn = False
        can_run = False
        run_btn = False
        ioc_file = None
        brd_file = None
        doc_type = "IOC (PDF)"
        model = "gemini-2.5-flash"

        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;">Step 1 — Requirements</div>', unsafe_allow_html=True)
        st.markdown("Upload **1 RI** + all associated **FRI** files for that paygroup")
        fri_files = st.file_uploader(
            "FRI files (xlsx)",
            type=["xlsx"],
            accept_multiple_files=True,
            key="fri",
            help="Foundational Requirements Inventory xlsx files. Upload all FRIs associated with the RI.",
        )
        ri_files = st.file_uploader(
            "RI file (xlsx / csv)",
            type=["xlsx", "csv"],
            accept_multiple_files=True,
            key="ri",
            help="Requirements Inventory file. Typically one per labor contract.",
        )

        if ri_files and len(ri_files) > 1:
            st.warning(
                f"⚠️ {len(ri_files)} RI files uploaded. Each RI covers all Labor Agreements "
                "for one paygroup — analysis is most accurate with one RI per session. "
                "Consider running separate sessions per paygroup.",
                icon=None,
            )

        paygroup_input = st.text_input(
            "Paygroup override",
            placeholder="e.g. 087  (inferred from filename if blank)",
        )
        output_name = st.text_input("Report filename (no extension)", value="inventory")

        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:4px;">Step 2 — Options</div>', unsafe_allow_html=True)
        model = st.selectbox(
            "Gemini model",
            ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
            index=0,
            help="gemini-2.5-flash is fast and capable; 2.5-pro is most accurate.",
            key="inv_model",
        )

        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:4px;">Step 3 — Load</div>', unsafe_allow_html=True)

        _reqs_ok = bool(fri_files) or bool(ri_files)
        st.markdown(_status_pill(_reqs_ok, "Requirements uploaded"), unsafe_allow_html=True)

        inv_load_btn = st.button(
            "▶  Load Inventory",
            type="primary",
            use_container_width=True,
            disabled=not _reqs_ok,
        )

        # Download + quality check buttons (shown after inventory is loaded)
        st.markdown('<div style="font-size:0.9rem;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;color:#1a4a8a;background:#e8f0fb;padding:4px 10px;border-radius:4px;display:inline-block;margin-bottom:6px;margin-top:12px;">Step 4 — Export &amp; Analyze</div>', unsafe_allow_html=True)

        if st.session_state.inv_excel_data:
            _inv_out = st.session_state.inv_output_name or "inventory"
            st.download_button(
                "⬇  Download Inventory Report (.xlsx)",
                data=st.session_state.inv_excel_data,
                file_name=f"{_inv_out}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.caption("Load inventory first to enable export and quality check.")

        if st.session_state.inv_requirements:
            _key_ok_inv = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            if _key_ok_inv:
                quality_btn = st.button(
                    "🔍  Run AI Quality Check",
                    use_container_width=True,
                    help="Uses Gemini to detect ambiguous language, missing details, duplicates, and scope conflicts.",
                )
            else:
                st.caption("Set GOOGLE_APPLICATION_CREDENTIALS to enable AI quality check and chat.")
                quality_btn = False
        else:
            quality_btn = False



# ---- Run analysis ----
if run_btn and can_run:
    pg = paygroup_input.strip() or None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)

        # Save uploads to disk (parsers need real file paths)
        doc_file = ioc_file or brd_file
        doc_path = tmp / doc_file.name
        doc_path.write_bytes(doc_file.getbuffer())

        fri_paths, ri_paths = [], []
        for f in fri_files:
            p = tmp / f.name; p.write_bytes(f.getbuffer()); fri_paths.append(p)
        for f in ri_files:
            p = tmp / f.name; p.write_bytes(f.getbuffer()); ri_paths.append(p)

        from ric.adapters.fri import load_fri
        from ric.adapters.ri import load_ri
        from ric.brd import parse_brd
        from ric.flagging import flag_changes
        from ric.ioc.parser import parse_ioc
        from ric.matcher import match_changes
        from ric.report.excel import write_excel
        from ric.report.html import write_html

        with st.status("Running analysis…", expanded=True) as status:

            # Load requirements
            st.write("Loading requirements…")
            requirements = []
            for p in fri_paths:
                st.write(f"  FRI: {p.name}")
                requirements.extend(load_fri(p, paygroup=pg))
            for p in ri_paths:
                st.write(f"  RI:  {p.name}")
                requirements.extend(load_ri(p, paygroup=pg))
            st.write(f"✓ {len(requirements)} requirements loaded")

            # Parse IOC or BRD
            if brd_file:
                st.write(f"Parsing BRD: *{doc_path.name}*…")
                ioc = parse_brd(doc_path, model=model)
            else:
                st.write(f"Parsing IOC: *{doc_path.name}*…")
                ioc = parse_ioc(doc_path, model=model)
            st.write(f"✓ {len(ioc.changes)} changes extracted")

            # Match
            st.write("Matching changes to requirements…")
            prog_bar = st.progress(0.0)
            prog_msg = st.empty()

            def _on_progress(i: int, total: int, change) -> None:
                prog_bar.progress(i / total)
                prog_msg.caption(
                    f"[{i}/{total}]  {change.change_type.value}:  "
                    f"{change.summary[:80]}…"
                )

            results = match_changes(
                ioc, requirements, model=model, on_progress=_on_progress
            )
            prog_bar.empty()
            prog_msg.empty()

            n_matches = sum(len(r.matched_requirements) for r in results)
            st.write(f"✓ {n_matches} requirement matches found")

            # Flag (Stage 4)
            st.write("Flagging risks and clarifications…")
            flag_prog = st.progress(0.0)
            flag_msg  = st.empty()

            def _on_flag_progress(i: int, total: int, change) -> None:
                flag_prog.progress(i / total)
                flag_msg.caption(f"[{i}/{total}] flagging: {change.summary[:80]}…")

            results = flag_changes(
                ioc, results, model=model, on_progress=_on_flag_progress
            )
            flag_prog.empty(); flag_msg.empty()
            n_flags = sum(len(getattr(r, "risk_flags", [])) for r in results)
            st.write(f"✓ {n_flags} risk flags identified")

            # Generate report bytes
            st.write("Generating reports…")
            xlsx_path = tmp / f"{output_name}.xlsx"
            html_path = tmp / f"{output_name}.html"
            write_excel(ioc, results, xlsx_path, requirements=requirements)
            write_html(ioc, results, html_path, requirements=requirements)
            excel_data = xlsx_path.read_bytes()
            html_data = html_path.read_bytes()

            status.update(label="Analysis complete ✓", state="complete", expanded=False)

        # Persist across re-renders
        from ric.chat import build_context
        st.session_state.ioc = ioc
        st.session_state.results = results
        st.session_state.requirements = requirements
        st.session_state.excel_data = excel_data
        st.session_state.html_data = html_data
        st.session_state.output_name = output_name
        st.session_state.chat_history = []
        st.session_state.chat_context = build_context(ioc, results)
        st.session_state.chat_is_demo = False
        st.session_state.input_doc_type = "BRD" if brd_file else "IOC"


# ---- Inventory Explorer: load handler ----
if inv_load_btn:
    pg = paygroup_input.strip() or None
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            tmp = Path(tmpdir)
            fri_paths, ri_paths = [], []
            for f in fri_files:
                p = tmp / f.name; p.write_bytes(f.getbuffer()); fri_paths.append(p)
            for f in ri_files:
                p = tmp / f.name; p.write_bytes(f.getbuffer()); ri_paths.append(p)

            from ric.adapters.fri import load_fri
            from ric.adapters.ri import load_ri
            from ric.inventory import analyze, build_inventory_context, write_inventory_excel

            with st.status("Loading inventory…", expanded=True) as status:
                requirements = []
                for p in fri_paths:
                    st.write(f"  FRI: {p.name}")
                    requirements.extend(load_fri(p, paygroup=pg))
                for p in ri_paths:
                    st.write(f"  RI:  {p.name}")
                    requirements.extend(load_ri(p, paygroup=pg))
                st.write(f"✓ {len(requirements)} requirements loaded")

                st.write("Computing statistics…")
                stats = analyze(requirements)
                st.write(f"✓ {len(stats.gaps)} quality gaps identified")

                st.write("Generating Excel export…")
                xlsx_path = tmp / f"{output_name}.xlsx"
                write_inventory_excel(requirements, stats, xlsx_path)
                excel_data = xlsx_path.read_bytes()
                status.update(label="Inventory loaded ✓", state="complete", expanded=False)

            st.session_state.inv_requirements = requirements
            st.session_state.inv_stats = stats
            st.session_state.inv_excel_data = excel_data
            st.session_state.inv_output_name = output_name
            st.session_state.inv_chat_context = build_inventory_context(requirements)
            st.session_state.inv_chat_history = []
            st.session_state.inv_quality_issues = None
        st.rerun()
    except Exception as _inv_err:
        st.error(f"**Load failed:** {_inv_err}")
        import traceback
        st.code(traceback.format_exc(), language="python")


# ---- Inventory Explorer: quality check handler ----
if quality_btn:
    from ric.inventory import check_quality

    with st.status("Running AI quality check…", expanded=True) as status:
        prog_bar = st.progress(0.0)
        prog_msg = st.empty()

        def _on_quality_progress(i: int, total: int, label: str) -> None:
            prog_bar.progress(i / total)
            prog_msg.caption(f"[{i}/{total}] Checking: {label}")

        issues = check_quality(
            st.session_state.inv_requirements,
            model=model,
            on_progress=_on_quality_progress,
        )
        prog_bar.empty()
        prog_msg.empty()
        status.update(
            label=f"Quality check complete — {len(issues)} issue{'s' if len(issues) != 1 else ''} found ✓",
            state="complete",
            expanded=False,
        )

    st.session_state.inv_quality_issues = [iss.model_dump() for iss in issues]
    st.rerun()


# ---- Display results ----
if app_mode == "Inventory Explorer":
    if st.session_state.inv_requirements:
        reqs = st.session_state.inv_requirements
        stats = st.session_state.inv_stats
        inv_out = st.session_state.inv_output_name or "inventory"

        st.markdown(f"""
        <div style="display:flex; align-items:baseline; gap:1rem; margin-bottom:0.5rem;">
            <h1 style="color:#1a4a8a; font-size:1.7rem; font-weight:700; margin:0;">Requirements Inventory</h1>
            <span style="font-size:0.88rem; color:#6b7a99; font-weight:600; background:#eef2f9;
                  padding:3px 10px; border-radius:20px; border:1px solid #d0dcea;">
                {stats.total} requirements loaded
            </span>
        </div>
        """, unsafe_allow_html=True)

        # Metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Requirements", stats.total)
        m2.metric("Sections", len(stats.by_section))
        m3.metric("LAs Referenced", len(stats.by_la))
        m4.metric("Quality Gaps", len(stats.gaps))
        m5.metric("Scope: All LAs", stats.by_scope_type.get("all", 0))

        st.divider()
        tab_ov, tab_gaps, tab_ai, tab_chat = st.tabs(
            ["📊 Overview", "⚠️ Field Gaps", "🔍 AI Quality Check", "💬 Chat"]
        )

        with tab_ov:
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**By Source**")
                st.dataframe(
                    [{"Source": k, "Requirements": v} for k, v in stats.by_source.items()],
                    hide_index=True, use_container_width=True,
                )
                st.markdown("**By Scope Type**")
                scope_labels = {"all": "All LAs", "include": "Include list", "exclude": "Exclude list"}
                st.dataframe(
                    [{"Scope": scope_labels.get(k, k), "Requirements": v}
                     for k, v in stats.by_scope_type.items()],
                    hide_index=True, use_container_width=True,
                )
                if stats.by_people_group:
                    st.markdown("**By People Group** (top 15)")
                    st.dataframe(
                        [{"People Group": k, "Requirements": v}
                         for k, v in list(stats.by_people_group.items())[:15]],
                        hide_index=True, use_container_width=True,
                    )
            with col_b:
                st.markdown("**Top Sections by Requirement Count**")
                st.dataframe(
                    [{"Section": k, "Requirements": v} for k, v in stats.by_section.items()],
                    hide_index=True, use_container_width=True,
                )
                if stats.by_la:
                    st.markdown("**Top Labor Agreements Referenced**")
                    st.dataframe(
                        [{"Labor Agreement": k, "Requirements": v}
                         for k, v in list(stats.by_la.items())[:20]],
                        hide_index=True, use_container_width=True,
                    )

        with tab_gaps:
            if stats.gaps:
                st.caption(
                    f"{len(stats.gaps)} requirement{'s' if len(stats.gaps) != 1 else ''} "
                    f"with missing or incomplete fields. Exported to 'Quality Gaps' sheet in the Excel download."
                )
                st.dataframe(
                    stats.gaps,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "ID": st.column_config.TextColumn(width="medium"),
                        "Source": st.column_config.TextColumn(width="small"),
                        "Paygroup": st.column_config.TextColumn(width="small"),
                        "Section": st.column_config.TextColumn(width="medium"),
                        "Issue": st.column_config.TextColumn(width="large"),
                    },
                )
            else:
                st.success("No field gaps found — all requirements have the expected fields.", icon="✅")

        with tab_ai:
            ai_issues = st.session_state.inv_quality_issues
            if ai_issues is None:
                st.info(
                    "Click **🔍 Run AI Quality Check** in the sidebar to analyze requirements "
                    "for ambiguous language, missing details, duplicates, and scope conflicts.",
                    icon="💡",
                )
            elif not ai_issues:
                st.success("No quality issues found — all requirements passed the AI review.", icon="✅")
            else:
                high   = [i for i in ai_issues if i["severity"] == "high"]
                medium = [i for i in ai_issues if i["severity"] == "medium"]
                low    = [i for i in ai_issues if i["severity"] == "low"]

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Issues", len(ai_issues))
                c2.metric("High", len(high))
                c3.metric("Medium", len(medium))
                c4.metric("Low", len(low))
                st.divider()

                type_order = [
                    "ambiguous_language", "missing_implementation_detail",
                    "potential_duplicate", "scope_conflict", "earn_code_mismatch",
                ]
                for sev, sev_issues in [("high", high), ("medium", medium), ("low", low)]:
                    if not sev_issues:
                        continue
                    border = {"high": "#c0392b", "medium": "#e67e22", "low": "#27ae60"}[sev]
                    bg     = {"high": "#fdecea", "medium": "#fef5e7", "low": "#eafaf1"}[sev]
                    txt    = {"high": "#922b21", "medium": "#a04000", "low": "#1e6b3a"}[sev]
                    st.markdown(
                        f'<div style="font-size:0.85rem;font-weight:800;text-transform:uppercase;'
                        f'letter-spacing:0.08em;color:{txt};margin:0.8rem 0 0.3rem 0;">'
                        f'{sev.upper()} — {len(sev_issues)} issue{"s" if len(sev_issues) != 1 else ""}</div>',
                        unsafe_allow_html=True,
                    )
                    for iss in sev_issues:
                        ft = iss["issue_type"].replace("_", " ").title()
                        st.markdown(f"""
                        <div style="border-left:4px solid {border};background:{bg};
                                    border-radius:0 8px 8px 0;padding:0.7rem 1rem;margin-bottom:6px;">
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                                <span style="background:{border};color:white;font-size:0.75rem;
                                             font-weight:800;text-transform:uppercase;letter-spacing:0.08em;
                                             padding:2px 7px;border-radius:3px;">{sev}</span>
                                <span style="font-weight:700;color:{txt};font-size:0.92rem;">{ft}</span>
                                <span style="font-size:0.85rem;color:#6b7a99;font-family:'Segoe UI',Calibri,'Trebuchet MS',Arial,sans-serif;">{iss["requirement_id"]}</span>
                            </div>
                            <div style="font-size:0.92rem;color:#2c3e50;margin-bottom:4px;">{iss["description"]}</div>
                            <div style="font-size:0.9rem;color:#4a6080;font-style:italic;">→ {iss["recommendation"]}</div>
                        </div>
                        """, unsafe_allow_html=True)

        with tab_chat:
            from ric.chat import ask as _ask

            _has_key_inv = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            _inv_context = st.session_state.inv_chat_context or ""

            st.caption(
                "Ask questions about your requirements inventory in plain English. "
                "Examples: *Which requirements apply to LA 1400WA?* · "
                "*List all earn codes used for shift differentials.* · "
                "*Which sections have no earn codes defined?*"
            )

            _inv_history = st.session_state.inv_chat_history or []
            for msg in _inv_history:
                role = "assistant" if msg["role"] == "model" else msg["role"]
                with st.chat_message(role):
                    st.markdown(msg["content"])

            if _has_key_inv:
                inv_user_input = st.chat_input("Ask something about your requirements…")
                if inv_user_input:
                    with st.chat_message("user"):
                        st.markdown(inv_user_input)
                    with st.chat_message("assistant"):
                        with st.spinner("Thinking…"):
                            _inv_answer = _ask(
                                inv_user_input,
                                _inv_context,
                                _inv_history,
                                model=model,
                            )
                        st.markdown(_inv_answer)
                    st.session_state.inv_chat_history = _inv_history + [
                        {"role": "user", "content": inv_user_input},
                        {"role": "model", "content": _inv_answer},
                    ]
                    st.rerun()
            else:
                st.warning(
                    "Set GOOGLE_APPLICATION_CREDENTIALS and restart the app to use chat.",
                    icon="⚠️",
                )
    else:
        # Inventory Explorer landing
        st.markdown("""
        <div style="padding: 1.2rem 0 0.5rem 0;">
            <h1 style="color:#1a4a8a; font-size:2rem; font-weight:700; margin-bottom:0.3rem;">
                Inventory Explorer
            </h1>
            <p style="color:#6b7a99; font-size:1.05rem; margin-top:0; margin-bottom:0.8rem;">
                Upload FRI or RI files to get a standalone summary, quality report, and Excel export — no IOC or BRD required.
            </p>
        </div>
        """, unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("""
            <div style="background:#f7f9fc;border:1px solid #d0dcea;border-top:3px solid #1a4a8a;
                        border-radius:10px;padding:1.2rem 1.4rem;">
                <div style="font-size:1.6rem;margin-bottom:0.5rem;">📋</div>
                <div style="font-size:1.05rem;font-weight:700;color:#1a4a8a;margin-bottom:0.4rem;">Overview Stats</div>
                <div style="font-size:0.97rem;color:#4a5568;">
                    Count requirements by section, Labor Agreement, scope type, and people group.
                </div>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown("""
            <div style="background:#f7f9fc;border:1px solid #d0dcea;border-top:3px solid #2e7dd1;
                        border-radius:10px;padding:1.2rem 1.4rem;">
                <div style="font-size:1.6rem;margin-bottom:0.5rem;">⚠️</div>
                <div style="font-size:1.05rem;font-weight:700;color:#1a4a8a;margin-bottom:0.4rem;">Quality Gaps</div>
                <div style="font-size:0.97rem;color:#4a5568;">
                    Flag requirements missing earn codes, LA scope declarations, or descriptions.
                </div>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown("""
            <div style="background:#f7f9fc;border:1px solid #d0dcea;border-top:3px solid #5ba3e8;
                        border-radius:10px;padding:1.2rem 1.4rem;">
                <div style="font-size:1.6rem;margin-bottom:0.5rem;">📥</div>
                <div style="font-size:1.05rem;font-weight:700;color:#1a4a8a;margin-bottom:0.4rem;">Excel Export</div>
                <div style="font-size:0.97rem;color:#4a5568;">
                    Download a 3-sheet workbook: Full Inventory, Quality Gaps, and Summary.
                </div>
            </div>""", unsafe_allow_html=True)
        with c4:
            st.markdown("""
            <div style="background:#f7f9fc;border:1px solid #d0dcea;border-top:3px solid #27ae60;
                        border-radius:10px;padding:1.2rem 1.4rem;">
                <div style="font-size:1.6rem;margin-bottom:0.5rem;">💬</div>
                <div style="font-size:1.05rem;font-weight:700;color:#1a4a8a;margin-bottom:0.4rem;">Chat / Q&amp;A</div>
                <div style="font-size:0.97rem;color:#4a5568;">
                    Ask plain-English questions like "Which requirements apply to 1400WA?"
                    or "List all rounding rules."
                </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("""
        <div style="background:#eef4fb; border:1px solid #c3d8f0; border-radius:10px;
                    margin-top:0.8rem; padding:1rem 1.4rem; font-size:1rem; color:#2c4a6e;">
            <strong>Getting started:</strong>&nbsp;
            Upload your FRI files and/or RI file in the sidebar — Step 1 (1 RI + all associated FRIs per paygroup),
            select your model in Step 2, then click <strong>▶ Load Inventory</strong> in Step 3.
            Once loaded, use Step 4 to download the Excel export or run an AI quality check on the loaded requirements.
        </div>
        """, unsafe_allow_html=True)

elif st.session_state.results:
    ioc = st.session_state.ioc
    results = st.session_state.results
    out = st.session_state.output_name or "impact_analysis"

    # Header
    st.markdown(f"""
    <div style="display:flex; align-items:baseline; gap:1rem; margin-bottom:0.5rem;">
        <h1 style="color:#1a4a8a; font-size:1.7rem; font-weight:700; margin:0;">Impact Analysis</h1>
        <span style="font-size:0.88rem; color:#6b7a99; font-weight:600; background:#eef2f9;
              padding:3px 10px; border-radius:20px; border:1px solid #d0dcea;">
            {ioc.effective_date or 'Date TBD'}
        </span>
    </div>
    <div style="font-size:0.9rem; color:#6b7a99; margin-bottom:1rem;">
        Contract:&nbsp;<strong>{', '.join(ioc.contract_ids) or '—'}</strong>
        &nbsp;·&nbsp;
        LAs:&nbsp;<strong>{', '.join(ioc.labor_agreement_ids) or '—'}</strong>
        &nbsp;·&nbsp;
        Union:&nbsp;<strong>{', '.join(ioc.union_locals) or '—'}</strong>
    </div>
    """, unsafe_allow_html=True)

    # Metrics
    total_m = sum(len(r.matched_requirements) for r in results)
    direct = sum(
        1 for r in results for m in r.matched_requirements if m.relevance == "direct"
    )
    tk_count = sum(1 for r in results if r.change.timekeeping_relevant)
    unmatched = sum(1 for r in results if not r.matched_requirements)

    total_flags  = sum(len(getattr(r, "risk_flags", [])) for r in results)
    high_flags   = sum(
        1 for r in results for f in getattr(r, "risk_flags", [])
        if (f.severity.value if hasattr(f.severity, "value") else f.severity) == "high"
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    _doc_type_label = (st.session_state.input_doc_type or "IOC") + " Changes"
    m1.metric(_doc_type_label, len(results))
    m2.metric("TK Relevant", tk_count)
    m3.metric("Reqs Matched", total_m)
    m4.metric("Direct", direct)
    m5.metric("Risk Flags", total_flags)
    m6.metric("High Severity", high_flags)

    st.divider()

    tab1, tab2 = st.tabs(["📊 Impact Analysis", "💬 Chat"])

    # ---- Tab 1: per-change detail ----
    with tab1:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:1rem;">
            <span style="font-size:1.05rem;font-weight:700;color:#1a4a8a;">Changes &amp; Matched Requirements</span>
            <span style="font-size:0.82rem;color:#6b7a99;background:#f0f4f8;
                         padding:3px 10px;border-radius:10px;border:1px solid #d0dcea;">
                Expand each change to view matched requirements and risk flags
            </span>
        </div>
        """, unsafe_allow_html=True)

        for i, cm in enumerate(results, 1):
            ch = cm.change
            n = len(cm.matched_requirements)
            match_label = (
                f"{n} match{'es' if n != 1 else ''}"
                if n else "no matches"
            )
            flags = getattr(cm, "risk_flags", [])
            flag_sevs = [
                f.severity.value if hasattr(f.severity, "value") else str(f.severity)
                for f in flags
            ]
            flag_label = ""
            if flag_sevs:
                icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                flag_label = "  ·  " + " ".join(icons.get(s, "⚪") for s in flag_sevs)
            tk_label = "TK" if ch.timekeeping_relevant else ""
            header = (
                f"**{i}.** &nbsp; "
                f"`{ch.change_type.value}`"
                + (f" &nbsp;`TK`" if ch.timekeeping_relevant else "")
                + f" &nbsp;— {ch.summary[:90]}"
                f"{'…' if len(ch.summary) > 90 else ''}"
                f"  ·  *{match_label}*"
                f"{flag_label}"
            )

            with st.expander(header, expanded=(i <= 2 and n > 0)):
                left, right = st.columns([3, 1])

                with left:
                    st.markdown(f"**Summary:** {ch.summary}")
                    _src_label = (st.session_state.input_doc_type or "IOC") + " Source Text"
                    st.markdown(f'<span style="font-size:0.82rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#6b7a99;">{_src_label}</span>', unsafe_allow_html=True)
                    st.code(ch.source_text[:600], language=None)

                with right:
                    tk_color = "#c0392b" if ch.timekeeping_relevant else "#6b7a99"
                    tk_bg    = "#fdecea" if ch.timekeeping_relevant else "#f0f2f5"
                    tk_text  = "TK Relevant" if ch.timekeeping_relevant else "Non-TK"
                    las = ", ".join(ch.labor_agreements) or "All IOC LAs"
                    eff = ch.effective_date or "—"
                    ct  = ch.change_type.value.replace("_", " ").title()
                    st.markdown(f"""
                    <div style="background:#f7f9fc;border:1px solid #d0dcea;border-radius:8px;
                                padding:0.9rem 1rem;font-size:0.9rem;line-height:1.8;">
                        <div style="margin-bottom:6px;">
                            <span style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                                         letter-spacing:0.08em;color:#6b7a99;">Change Type</span><br>
                            <strong style="color:#1a4a8a;">{ct}</strong>
                        </div>
                        <div style="margin-bottom:6px;">
                            <span style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                                         letter-spacing:0.08em;color:#6b7a99;">Timekeeping</span><br>
                            <span style="background:{tk_bg};color:{tk_color};font-weight:700;
                                         padding:1px 8px;border-radius:10px;font-size:0.85rem;">
                                {tk_text}
                            </span>
                        </div>
                        <div style="margin-bottom:6px;">
                            <span style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                                         letter-spacing:0.08em;color:#6b7a99;">Labor Agreements</span><br>
                            <span style="color:#2c4a6e;">{las}</span>
                        </div>
                        <div>
                            <span style="font-size:0.78rem;font-weight:700;text-transform:uppercase;
                                         letter-spacing:0.08em;color:#6b7a99;">Effective Date</span><br>
                            <span style="color:#2c4a6e;">{eff}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                # Risk flags
                flags = getattr(cm, "risk_flags", [])
                if flags:
                    st.divider()
                    st.markdown('<span style="font-size:0.82rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#6b7a99;">Risk &amp; Clarification Flags</span>', unsafe_allow_html=True)
                    for flag in flags:
                        sev = flag.severity.value if hasattr(flag.severity, "value") else str(flag.severity)
                        border_color = {"high": "#c0392b", "medium": "#e67e22", "low": "#27ae60"}.get(sev, "#aaa")
                        sev_bg       = {"high": "#fdecea", "medium": "#fef5e7", "low": "#eafaf1"}.get(sev, "#f5f5f5")
                        sev_text     = {"high": "#922b21", "medium": "#a04000", "low": "#1e6b3a"}.get(sev, "#555")
                        ft = flag.flag_type.replace("_", " ").title()
                        st.markdown(f"""
                        <div style="border-left:4px solid {border_color};background:{sev_bg};
                                    border-radius:0 8px 8px 0;padding:0.7rem 1rem;margin-bottom:6px;">
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                                <span style="background:{border_color};color:white;font-size:0.75rem;
                                             font-weight:800;text-transform:uppercase;letter-spacing:0.08em;
                                             padding:2px 7px;border-radius:3px;">{sev}</span>
                                <span style="font-weight:700;color:{sev_text};font-size:0.92rem;">{ft}</span>
                            </div>
                            <div style="font-size:0.92rem;color:#2c3e50;margin-bottom:4px;">{flag.description}</div>
                            <div style="font-size:0.9rem;color:#4a6080;font-style:italic;">→ {flag.recommendation}</div>
                        </div>
                        """, unsafe_allow_html=True)

                st.divider()

                if cm.matched_requirements:
                    req_lookup = {
                        r.id: r for r in (st.session_state.requirements or [])
                    }
                    rows = [
                        {
                            "Req ID": m.requirement_id,
                            "Src": (
                                f"{req_lookup[m.requirement_id].source}-"
                                f"{req_lookup[m.requirement_id].paygroup}"
                                if m.requirement_id in req_lookup else ""
                            ),
                            "Section": (
                                req_lookup[m.requirement_id].section
                                if m.requirement_id in req_lookup else ""
                            ),
                            "Description": (
                                req_lookup[m.requirement_id].description[:200]
                                if m.requirement_id in req_lookup else ""
                            ),
                            "Relevance": m.relevance,
                            "Rationale": m.rationale,
                            "Delta Description": m.delta_description or "",
                        }
                        for m in cm.matched_requirements
                    ]
                    st.dataframe(
                        rows,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Req ID": st.column_config.TextColumn(width="small"),
                            "Src": st.column_config.TextColumn(width="small"),
                            "Section": st.column_config.TextColumn(width="medium"),
                            "Description": st.column_config.TextColumn(width="large"),
                            "Relevance": st.column_config.TextColumn(width="small"),
                            "Rationale": st.column_config.TextColumn(width="medium"),
                            "Delta Description": st.column_config.TextColumn(width="large"),
                        },
                    )
                else:
                    st.info(cm.no_match_reason or "No matching requirements found.")

    # ---- Tab 2: chat ----
    with tab2:
        from ric.chat import ask

        _has_key = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        _is_demo_chat = st.session_state.get("chat_is_demo", False)

        if _is_demo_chat:
            st.info(
                "**Demo conversation** — these are sample questions and answers to show "
                "what you can ask once you run a real analysis. "
                "Set GOOGLE_API_KEY to continue the conversation with your own questions.",
                icon="💡",
            )
        else:
            st.caption(
                "Ask questions about this analysis — the chat knows all IOC changes, "
                "matched requirements, and delta descriptions."
            )

        # Display history (demo or live)
        history = st.session_state.chat_history or []
        for msg in history:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            with st.chat_message(role):
                st.markdown(msg["content"])

        # Live input — shown when key is available (demo or not)
        if _has_key:
            if _is_demo_chat:
                st.divider()
                st.caption("Your API key is set — you can continue this conversation with your own questions:")

            user_input = st.chat_input("Ask something about this analysis…")
            if user_input:
                with st.chat_message("user"):
                    st.markdown(user_input)

                with st.chat_message("assistant"):
                    with st.spinner("Thinking…"):
                        answer = ask(
                            user_input,
                            st.session_state.chat_context or "",
                            history,
                            model=model,
                        )
                    st.markdown(answer)

                st.session_state.chat_history = history + [
                    {"role": "user", "content": user_input},
                    {"role": "model", "content": answer},
                ]
                st.session_state.chat_is_demo = False
                st.rerun()
        else:
            st.warning(
                "Set GOOGLE_APPLICATION_CREDENTIALS and restart the app to ask your own questions.",
                icon="⚠️",
            )

else:
    # IOC/BRD Analysis landing state
    st.markdown("""
    <div style="padding: 1.2rem 0 0.5rem 0;">
        <h1 style="color:#1a4a8a; font-size:2rem; font-weight:700; margin-bottom:0.3rem;">
            IOC / BRD Analysis
        </h1>
        <p style="color:#6b7a99; font-size:1.05rem; margin-top:0; margin-bottom:0.8rem;">
            Upload a labor agreement change document and your FRI/RI files to get a requirements impact analysis, risk flags, and a chat to explore the results.
        </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""
        <div style="background:#f7f9fc; border:1px solid #d0dcea; border-top:3px solid #1a4a8a;
                    border-radius:10px; padding:1.2rem 1.4rem;">
            <div style="font-size:1.6rem; margin-bottom:0.5rem;">📄</div>
            <div style="font-size:1.05rem; font-weight:700; color:#1a4a8a; margin-bottom:0.4rem;">Parse the Document</div>
            <div style="font-size:0.97rem; color:#4a5568;">
                Upload an IOC PDF or BRD Word doc. The AI extracts every labor agreement
                change — wage rates, premiums, holidays, H&W, and more.
            </div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div style="background:#f7f9fc; border:1px solid #d0dcea; border-top:3px solid #2e7dd1;
                    border-radius:10px; padding:1.2rem 1.4rem;">
            <div style="font-size:1.6rem; margin-bottom:0.5rem;">🔗</div>
            <div style="font-size:1.05rem; font-weight:700; color:#1a4a8a; margin-bottom:0.4rem;">Match Requirements</div>
            <div style="font-size:0.97rem; color:#4a5568;">
                Each change is matched against your FRI/RI inventory. Requirements are rated
                <em>Direct</em> (must update) or <em>Indirect</em> (verify), with delta actions.
            </div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div style="background:#f7f9fc; border:1px solid #d0dcea; border-top:3px solid #5ba3e8;
                    border-radius:10px; padding:1.2rem 1.4rem;">
            <div style="font-size:1.6rem; margin-bottom:0.5rem;">🚩</div>
            <div style="font-size:1.05rem; font-weight:700; color:#1a4a8a; margin-bottom:0.4rem;">Flag Risks</div>
            <div style="font-size:0.97rem; color:#4a5568;">
                Retroactive pay deadlines, missing earn codes, ambiguous language, and other
                blockers are surfaced before implementation begins.
            </div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown("""
        <div style="background:#f7f9fc; border:1px solid #d0dcea; border-top:3px solid #27ae60;
                    border-radius:10px; padding:1.2rem 1.4rem;">
            <div style="font-size:1.6rem; margin-bottom:0.5rem;">💬</div>
            <div style="font-size:1.05rem; font-weight:700; color:#1a4a8a; margin-bottom:0.4rem;">Chat / Q&amp;A</div>
            <div style="font-size:0.97rem; color:#4a5568;">
                Ask plain-English questions about the analysis — which requirements are
                affected, what actions to take, and why a flag was raised.
            </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#eef4fb; border:1px solid #c3d8f0; border-radius:10px;
                margin-top:0.8rem; padding:1rem 1.4rem; font-size:1rem; color:#2c4a6e;">
        <strong>Getting started:</strong>&nbsp;
        Select the document type in the sidebar, upload your IOC or BRD and at least one
        requirements file (FRI or RI), then click <strong>▶ Run Analysis</strong>.
    </div>
    """, unsafe_allow_html=True)
