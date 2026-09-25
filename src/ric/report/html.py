import html as _html
from pathlib import Path

from ric.ioc.models import IOCParseResult
from ric.matcher.models import ChangeMatch

_CHANGE_TYPE_COLORS = {
    "wage_rate": "#2e7d32",
    "premium_value": "#e65100",
    "eligibility": "#6a1b9a",
    "list_operation": "#00695c",
    "holiday_composition": "#00695c",
    "benefit": "#546e7a",
    "other": "#757575",
}

_CSS = """
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 14px; background: #f0f2f5; color: #1a1a1a;
}
a { color: inherit; }

/* Page header */
.page-header {
  background: #1a3a5c; color: white;
  padding: 24px 28px; border-radius: 10px; margin-bottom: 20px;
}
.page-header h1 { margin: 0 0 6px 0; font-size: 22px; font-weight: 700; }
.page-header .subtitle { margin: 0; font-size: 13px; opacity: 0.8; }
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-top: 18px;
}
.meta-item label {
  display: block; font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.65; margin-bottom: 2px;
}
.meta-item span { font-size: 13px; }

/* Stats */
.stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.stat {
  background: white; border-radius: 8px; padding: 16px 20px;
  flex: 1; min-width: 110px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.stat-num { font-size: 28px; font-weight: 700; color: #1a3a5c; line-height: 1; }
.stat-label { font-size: 12px; color: #666; margin-top: 4px; }

/* Table container */
.table-wrap {
  background: white; border-radius: 10px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.table-title {
  padding: 16px 20px; border-bottom: 1px solid #eee;
  font-size: 15px; font-weight: 700; color: #1a3a5c;
}

/* Table */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th {
  background: #1a3a5c; color: white;
  padding: 10px 12px; text-align: left;
  font-weight: 600; font-size: 11px; white-space: nowrap;
}
tbody td { padding: 10px 12px; vertical-align: top; border-bottom: 1px solid #f0f2f5; }
tbody tr:last-child td { border-bottom: none; }
tbody tr.row-direct { background: #fff8f0; }
tbody tr.row-indirect { background: #f0f5ff; }
tbody tr.row-no-match { background: #fafafa; }
tbody tr.change-start td { border-top: 2px solid #d0d7e3; }

/* Badges */
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; white-space: nowrap;
}
.badge-direct   { background: #e65100; color: white; }
.badge-indirect { background: #1565c0; color: white; }
.badge-no-match { background: #9e9e9e; color: white; }
.badge-tk-yes   { background: #c62828; color: white; }
.badge-tk-no    { background: #546e7a; color: white; }
.status-box {
  width: 100%; border: 1px dashed #ccc; border-radius: 4px;
  min-height: 30px; background: #fffde7;
}
.muted { color: #9e9e9e; font-style: italic; }
.change-num { font-weight: 700; color: #1a3a5c; }
.flag-box { margin: 4px 0; padding: 6px 10px; border-radius: 5px; font-size: 12px; }
.flag-high   { background: #ffcdd2; border-left: 3px solid #c62828; }
.flag-medium { background: #fff9c4; border-left: 3px solid #f9a825; }
.flag-low    { background: #e8f5e9; border-left: 3px solid #2e7d32; }
.flag-label  { font-weight: 700; text-transform: uppercase; font-size: 10px; margin-right: 6px; }
.flag-rec    { color: #555; margin-top: 3px; font-size: 11px; }

@media print {
  body { background: white; padding: 0; font-size: 11px; }
  .page-header { border-radius: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .table-wrap { box-shadow: none; }
  thead th { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  tbody tr.row-direct { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  tbody tr.row-indirect { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


def _e(text: str) -> str:
    return _html.escape(str(text))


def _badge(text: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{_e(text)}</span>'


def _change_type_badge(ct: str) -> str:
    color = _CHANGE_TYPE_COLORS.get(ct, "#757575")
    label = ct.replace("_", " ")
    return (
        f'<span class="badge" style="background:{color};color:white">'
        f'{_e(label)}</span>'
    )


def _meta(label: str, value: str) -> str:
    return (
        f'<div class="meta-item">'
        f'<label>{_e(label)}</label>'
        f'<span>{_e(value)}</span>'
        f'</div>'
    )


def _stat(num: int | str, label: str) -> str:
    return (
        f'<div class="stat">'
        f'<div class="stat-num">{_e(str(num))}</div>'
        f'<div class="stat-label">{_e(label)}</div>'
        f'</div>'
    )


def _build_header(ioc: IOCParseResult) -> str:
    metas = "".join([
        _meta("Contract IDs", ", ".join(ioc.contract_ids) or "—"),
        _meta("LA IDs", ", ".join(ioc.labor_agreement_ids) or "—"),
        _meta("Effective Date", ioc.effective_date or "—"),
        _meta("Union Locals", ", ".join(ioc.union_locals) or "—"),
    ])
    return (
        '<div class="page-header">'
        '<h1>RIC — Impact Analysis Report</h1>'
        '<p class="subtitle">Requirements Intelligence Chatbot | Human Review Draft</p>'
        f'<div class="meta-grid">{metas}</div>'
        '</div>'
    )


def _build_stats(results: list[ChangeMatch]) -> str:
    total = len(results)
    tk = sum(1 for cm in results if cm.change.timekeeping_relevant)
    total_m = sum(len(cm.matched_requirements) for cm in results)
    direct = sum(
        1 for cm in results for m in cm.matched_requirements if m.relevance == "direct"
    )
    unmatched = sum(1 for cm in results if not cm.matched_requirements)

    return (
        '<div class="stats">'
        + _stat(total, "IOC Changes")
        + _stat(tk, "TK Relevant")
        + _stat(total_m, "Requirements Matched")
        + _stat(direct, "Direct Matches")
        + _stat(total - unmatched, "Changes with Matches")
        + '</div>'
    )


def _build_table(results: list[ChangeMatch], req_lookup: dict | None = None) -> str:
    thead = (
        "<thead><tr>"
        "<th>#</th>"
        "<th>Change Type</th>"
        "<th>TK</th>"
        "<th>Eff. Date</th>"
        "<th>Change Summary</th>"
        "<th>Req ID</th>"
        "<th>Relevance</th>"
        "<th>Section &amp; Description</th>"
        "<th>Rationale</th>"
        "<th>Delta Description</th>"
        "<th>Status</th>"
        "</tr></thead>"
    )

    rows = []
    for idx, cm in enumerate(results, 1):
        ch = cm.change
        tk_badge = _badge("Y", "badge-tk-yes") if ch.timekeeping_relevant else _badge("N", "badge-tk-no")
        ct_badge = _change_type_badge(ch.change_type.value)
        eff = _e(ch.effective_date or "—")

        change_cells = (
            f'<td class="change-num">{idx}</td>'
            f"<td>{ct_badge}</td>"
            f"<td>{tk_badge}</td>"
            f"<td>{eff}</td>"
            f"<td>{_e(ch.summary)}</td>"
        )

        # Render flag boxes in the Change Summary cell of the first row
        flags = getattr(cm, "risk_flags", [])
        flag_html = ""
        for flag in flags:
            sev = flag.severity.value if hasattr(flag.severity, "value") else str(flag.severity)
            ft = flag.flag_type.replace("_", " ")
            flag_html += (
                f'<div class="flag-box flag-{sev}">'
                f'<span class="flag-label">{_e(sev)} — {_e(ft)}</span>{_e(flag.description)}'
                f'<div class="flag-rec">→ {_e(flag.recommendation)}</div>'
                f'</div>'
            )

        if flag_html:
            change_cells = (
                f'<td class="change-num">{idx}</td>'
                f"<td>{ct_badge}</td>"
                f"<td>{tk_badge}</td>"
                f"<td>{eff}</td>"
                f"<td>{_e(ch.summary)}<br>{flag_html}</td>"
            )

        if cm.matched_requirements:
            for mi, m in enumerate(cm.matched_requirements):
                row_class = "row-direct" if m.relevance == "direct" else "row-indirect"
                change_start = " change-start" if mi == 0 else ""
                rel_badge = _badge(m.relevance, f"badge-{m.relevance}")
                req = (req_lookup or {}).get(m.requirement_id)
                req_src = f"{req.source}-{req.paygroup}" if req else ""
                req_sec = req.section if req else ""
                req_desc = req.description[:300] if req else ""
                rows.append(
                    f'<tr class="{row_class}{change_start}">'
                    + (change_cells if mi == 0 else "<td></td><td></td><td></td><td></td><td></td>")
                    + f"<td><code>{_e(m.requirement_id)}</code><br>"
                    + f'<span style="font-size:10px;color:#666">{_e(req_src)}</span></td>'
                    + f"<td>{rel_badge}</td>"
                    + f"<td><strong>{_e(req_sec)}</strong><br><span style='font-size:11px'>{_e(req_desc)}</span></td>"
                    + f"<td>{_e(m.rationale)}</td>"
                    + f"<td>{_e(m.delta_description or '')}</td>"
                    + '<td><div class="status-box"></div></td>'
                    + "</tr>"
                )
        else:
            reason = _e(cm.no_match_reason or "No matching requirements found")
            rows.append(
                '<tr class="row-no-match change-start">'
                + change_cells
                + f'<td colspan="5" class="muted">{reason}</td>'
                + '<td><div class="status-box"></div></td>'
                + "</tr>"
            )

    tbody = "<tbody>" + "".join(rows) + "</tbody>"
    return (
        '<div class="table-wrap">'
        '<div class="table-title">Impact Analysis</div>'
        f"<table>{thead}{tbody}</table>"
        "</div>"
    )


def write_html(
    ioc: IOCParseResult,
    results: list[ChangeMatch],
    path: Path,
    requirements=None,
) -> None:
    """Write a self-contained HTML impact analysis report to path."""
    req_lookup = {r.id: r for r in requirements} if requirements else {}
    body = _build_header(ioc) + _build_stats(results) + _build_table(results, req_lookup)
    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>RIC Impact Analysis</title>\n"
        f"  <style>{_CSS}</style>\n"
        "</head>\n"
        f"<body>{body}</body>\n"
        "</html>\n"
    )
    Path(path).write_text(doc, encoding="utf-8")
