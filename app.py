"""
Requirements Intelligence Chatbot — Streamlit UI.

Run with:
    streamlit run app.py
"""
import os
import tempfile
from pathlib import Path

import openpyxl
import streamlit as st


def _detect_format(path: Path) -> str:
    """Return 'FRI' if the file looks like a FRI Standard Template, else 'RI'."""
    if path.suffix.lower() == ".csv":
        return "RI"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for name in wb.sheetnames:
            ws = wb[name]
            row = next(ws.iter_rows(values_only=True), None)
            if row and len(row) > 2 and str(row[2] or "").strip() == "People Group":
                return "FRI"
    except Exception:
        pass
    return "RI"

st.set_page_config(
    page_title="RIC — Impact Analysis",
    page_icon="📋",
    layout="wide",
)

# ---- Session state init ----
for _k in ("ioc", "results", "requirements", "excel_data", "html_data", "output_name",
           "chat_history", "chat_context", "chat_is_demo"):
    if _k not in st.session_state:
        st.session_state[_k] = None


# ---- Sidebar ----
with st.sidebar:
    st.title("📋 RIC")
    st.caption("Requirements Intelligence Chatbot")
    st.divider()

    demo_mode = st.toggle(
        "Demo mode (no API key needed)",
        value=False,
        help="Load sample data so you can explore the UI without uploading files or an API key.",
    )
    st.divider()

    st.subheader("1 · Upload documents")
    ioc_file = st.file_uploader(
        "IOC Document (PDF)",
        type=["pdf"],
        help="The Inter-Office Communication PDF to analyze.",
    )

    st.markdown("**Requirements files** — upload FRI, RI, or both")
    fri_files = st.file_uploader(
        "FRI files (xlsx) — optional",
        type=["xlsx"],
        accept_multiple_files=True,
        key="fri",
        help="Foundational Requirements Inventory xlsx files.",
    )
    ri_files = st.file_uploader(
        "RI files (xlsx / csv) — optional",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
        key="ri",
        help="Requirements Inventory xlsx or csv files.",
    )

    st.subheader("2 · Options")
    model = st.selectbox(
        "Gemini model",
        ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
        index=0,
        help="gemini-2.0-flash is free and fast; 1.5-pro is more capable.",
    )
    paygroup_input = st.text_input(
        "Paygroup override",
        placeholder="e.g. 087  (inferred from filename if blank)",
    )
    output_name = st.text_input("Report filename (no extension)", value="impact_analysis")

    st.divider()

    if demo_mode:
        st.caption("✅ IOC PDF uploaded")
        st.caption("✅ FRI or RI file uploaded")
        st.caption("✅ GOOGLE_API_KEY set")
        st.caption("_Demo mode — using sample data_")
        can_run = False
        run_btn = False
        demo_btn = st.button(
            "▶  Load Demo Analysis",
            type="primary",
            use_container_width=True,
        )
    else:
        _ioc_ok  = bool(ioc_file)
        _reqs_ok = bool(fri_files) or bool(ri_files)
        _key_ok  = bool(os.getenv("GOOGLE_API_KEY"))

        def _req(ok: bool, label: str) -> None:
            st.caption(("✅ " if ok else "⬜ ") + label)

        _req(_ioc_ok,  "IOC PDF uploaded")
        _req(_reqs_ok, "FRI or RI file uploaded")
        _req(_key_ok,  "GOOGLE_API_KEY set")

        can_run = _ioc_ok and _reqs_ok and _key_ok
        run_btn = st.button(
            "▶  Run Analysis",
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )
        demo_btn = False


# ---- Demo mode ----
if demo_btn:
    from ric.chat import build_context
    from ric.demo import sample_chat_history, sample_ioc, sample_requirements, sample_results
    from ric.report.excel import write_excel
    from ric.report.html import write_html
    import tempfile
    ioc = sample_ioc()
    results = sample_results(ioc)
    reqs = sample_requirements()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        out = output_name or "impact_analysis"
        xlsx_path = tmp / f"{out}.xlsx"
        html_path = tmp / f"{out}.html"
        write_excel(ioc, results, xlsx_path, requirements=reqs)
        write_html(ioc, results, html_path, requirements=reqs)
        st.session_state.ioc = ioc
        st.session_state.results = results
        st.session_state.requirements = reqs
        st.session_state.excel_data = xlsx_path.read_bytes()
        st.session_state.html_data = html_path.read_bytes()
        st.session_state.output_name = out
        st.session_state.chat_history = sample_chat_history()
        st.session_state.chat_context = build_context(ioc, results)
        st.session_state.chat_is_demo = True
    st.rerun()


# ---- Run analysis ----
if run_btn and can_run:
    pg = paygroup_input.strip() or None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Save uploads to disk (parsers need real file paths)
        ioc_path = tmp / ioc_file.name
        ioc_path.write_bytes(ioc_file.getbuffer())

        fri_paths, ri_paths = [], []
        for f in fri_files:
            p = tmp / f.name; p.write_bytes(f.getbuffer()); fri_paths.append(p)
        for f in ri_files:
            p = tmp / f.name; p.write_bytes(f.getbuffer()); ri_paths.append(p)

        from ric.adapters.fri import load_fri
        from ric.adapters.ri import load_ri
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

            # Parse IOC
            st.write(f"Parsing IOC: *{ioc_file.name}*…")
            ioc = parse_ioc(ioc_path, model=model)
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


# ---- Display results ----
if st.session_state.results:
    ioc = st.session_state.ioc
    results = st.session_state.results
    out = st.session_state.output_name or "impact_analysis"

    # Header
    st.title("Impact Analysis")
    st.caption(
        f"Contract IDs: **{', '.join(ioc.contract_ids)}**  ·  "
        f"LAs: **{', '.join(ioc.labor_agreement_ids)}**  ·  "
        f"Effective: **{ioc.effective_date or '—'}**  ·  "
        f"Union: **{', '.join(ioc.union_locals) or '—'}**"
    )

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
    m1.metric("IOC Changes", len(results))
    m2.metric("TK Relevant", tk_count)
    m3.metric("Reqs Matched", total_m)
    m4.metric("Direct", direct)
    m5.metric("Risk Flags", total_flags)
    m6.metric("High Severity", high_flags)

    # Download buttons
    st.divider()
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "📥  Download Excel Report",
            data=st.session_state.excel_data,
            file_name=f"{out}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            "📥  Download HTML Report",
            data=st.session_state.html_data,
            file_name=f"{out}.html",
            mime="text/html",
            use_container_width=True,
        )

    st.divider()

    tab1, tab2 = st.tabs(["📊 Impact Analysis", "💬 Chat"])

    # ---- Tab 1: per-change detail ----
    with tab1:
        st.subheader("Changes & Matched Requirements")

        for i, cm in enumerate(results, 1):
            ch = cm.change
            n = len(cm.matched_requirements)
            tk_icon = "🔴" if ch.timekeeping_relevant else "⚪"
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
            header = (
                f"{tk_icon} &nbsp; **{i}.** &nbsp; "
                f"`{ch.change_type.value}` &nbsp;—&nbsp; "
                f"{ch.summary[:90]}"
                f"{'…' if len(ch.summary) > 90 else ''}"
                f"  ·  *{match_label}*"
                f"{flag_label}"
            )

            with st.expander(header, expanded=(i <= 2 and n > 0)):
                left, right = st.columns([3, 1])

                with left:
                    st.markdown(f"**Summary:** {ch.summary}")
                    st.caption("Source text from IOC:")
                    st.code(ch.source_text[:600], language=None)

                with right:
                    st.markdown(f"**Change type:** `{ch.change_type.value}`")
                    st.markdown(
                        f"**TK Relevant:** {'🔴 Yes' if ch.timekeeping_relevant else 'No'}"
                    )
                    st.markdown(
                        "**LAs:** "
                        + (", ".join(f"`{la}`" for la in ch.labor_agreements) or "All IOC LAs")
                    )
                    if ch.effective_date:
                        st.markdown(f"**Effective:** {ch.effective_date}")

                # Risk flags
                flags = getattr(cm, "risk_flags", [])
                if flags:
                    st.divider()
                    st.caption("**Risk & Clarification Flags**")
                    for flag in flags:
                        sev = flag.severity.value if hasattr(flag.severity, "value") else str(flag.severity)
                        color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
                        ft = flag.flag_type.replace("_", " ").title()
                        with st.container(border=True):
                            st.markdown(
                                f"{color} **{sev.upper()} — {ft}**  \n"
                                f"{flag.description}  \n"
                                f"*→ {flag.recommendation}*"
                            )

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

        _has_key = bool(os.getenv("GOOGLE_API_KEY"))
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
                "Set GOOGLE_API_KEY and restart the app to ask your own questions.",
                icon="⚠️",
            )

else:
    # Landing state
    st.title("Requirements Intelligence Chatbot")
    st.markdown(
        """
        This tool reads an IOC (Inter-Office Communication) document and your Requirements
        Inventory, then identifies which requirements need to be reviewed for each contract change.

        **To get started:**
        1. Upload an **IOC PDF** in the sidebar
        2. Upload one or more requirements files — **FRI**, **RI**, or both
           *(format is detected automatically)*
        3. Click **▶ Run Analysis**

        The analysis will produce an **Excel** and **HTML** report you can share with your team.
        """
    )
