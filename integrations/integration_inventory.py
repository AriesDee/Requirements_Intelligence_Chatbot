"""Consolidate WFD integrations, integration details and schedules into one Excel workbook.

Authentication lives in ukg_auth.py and takes the same flags as call_UKG_HWFD_jobs_v2.py:
    python integration_inventory.py --local_mode            (WFM_* env vars)
    python integration_inventory.py --local_akv             (Azure Key Vault, browser login)
    python integration_inventory.py                         (Key Vault, managed identity)
Add --base_url, --grant_type client_credentials, etc. as needed.

Sheets produced:
    Integrations  one row per integration (list data merged with detail data)
    Parameters    one row per integration parameter (detail endpoint)
    Schedules     one row per scheduled instance, with integration details joined in
"""
import argparse
import datetime
import json
import os
import sys

import pandas as pd
import requests
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# ukg_auth.py lives in the repo root (one level up), shared with the other UKG tools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ukg_auth  # noqa: E402

FONT_NAME = "Verdana"
FONT_SIZE = 10

# Endpoints (relative to base URL). Adjust if your tenant differs.
INTEGRATIONS_LIST_PATH = "/api/v1/platform/integrations"
INTEGRATION_DETAIL_PATH = "/api/v1/platform/integrations/{id}"
SCHEDULES_PATH = "/api/v1/platform/integration_schedules"


def to_cell(value):
    """Excel cells can't hold dicts/lists; serialise them as JSON text."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def collect_inventory(client, from_date="2020-01-01", to_date="2026-12-31",
                      log=print, should_stop=lambda: False):
    """Call the three endpoints and return {"Integrations", "Parameters", "Schedules"} DataFrames.

    Returns None if should_stop() becomes true part-way through."""
    # 1. All integrations
    integrations = client.get_json(INTEGRATIONS_LIST_PATH)
    log(f"Retrieved {len(integrations)} integrations")

    # 2. Detail for each integration
    details = {}
    for n, item in enumerate(integrations, 1):
        if should_stop():
            return None
        iid = item["id"]
        try:
            details[iid] = client.get_json(INTEGRATION_DETAIL_PATH.format(id=iid))
            log(f"  [{n}/{len(integrations)}] detail for integration {iid}: {item.get('name')}")
        except requests.HTTPError as exc:
            log(f"  WARN: detail for integration {iid} failed: {exc}")

    # 3. All schedules
    if should_stop():
        return None
    schedules = client.get_json(
        SCHEDULES_PATH, params={"fromDate": from_date, "toDate": to_date})
    log(f"Retrieved {len(schedules)} schedules")

    # Integrations sheet: list fields + detail fields (list value wins on clashes)
    integration_rows = []
    parameter_rows = []
    for item in integrations:
        iid = item["id"]
        detail = details.get(iid, {})
        row = {k: to_cell(v) for k, v in item.items() if k != "integrationParameters"}
        for k, v in detail.items():
            if k in ("integrationParameters", "sftpConnection"):
                continue
            row.setdefault(k, to_cell(v))
        row["sftpConnectionId"] = (detail.get("sftpConnection") or {}).get("id")
        row["scheduleCount"] = sum(1 for s in schedules if s.get("integrationId") == iid)
        integration_rows.append(row)

        for p in detail.get("integrationParameters", []):
            parameter_rows.append({
                "integrationId": iid,
                "integrationName": item.get("name"),
                **{k: to_cell(v) for k, v in p.items()},
            })

    integrations_df = pd.DataFrame(integration_rows)
    parameters_df = pd.DataFrame(parameter_rows)

    # Schedules sheet: join in integration description/type/template
    schedules_df = pd.DataFrame([{k: to_cell(v) for k, v in s.items()} for s in schedules])
    join_cols = [c for c in ("id", "description", "integrationType", "integrationTemplate",
                             "runAsSystemUser", "sftpConnectionId") if c in integrations_df.columns]
    if not schedules_df.empty and join_cols:
        info = integrations_df[join_cols].rename(columns={
            "id": "integrationId", "description": "integrationDescription"})
        schedules_df = schedules_df.merge(info, on="integrationId", how="left")

    return {"Integrations": integrations_df, "Parameters": parameters_df,
            "Schedules": schedules_df}


def timestamped_path(path, now=None):
    """integration_inventory.xlsx -> integration_inventory_20261016_142530.xlsx"""
    stem, ext = os.path.splitext(path)
    return "%s_%s%s" % (stem, (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S"), ext or ".xlsx")


# Excel's built-in conditional-format colours
_RED = (PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"), Font(name=FONT_NAME, size=FONT_SIZE, color="9C0006"))
_YELLOW = (PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"), Font(name=FONT_NAME, size=FONT_SIZE, color="9C5700"))
_GREEN = (PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"), Font(name=FONT_NAME, size=FONT_SIZE, color="006100"))

# (sheet, column header) -> {cell value: colour}; bool keys match Excel TRUE/FALSE
CONDITIONAL_FORMATS = {
    ("Integrations", "integrationType"): {"IMPORT": _GREEN, "EXPORT": _YELLOW, "NONE": _RED},
    ("Schedules", "scheduleStatus"): {"Disabled": _RED},
    ("Parameters", "userPrompted"): {False: _RED, True: _GREEN},
}


def write_workbook(frames, path):
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name=FONT_NAME, size=FONT_SIZE, bold=True, color="FFFFFF")
    body_font = Font(name=FONT_NAME, size=FONT_SIZE)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in frames.items():
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for row in ws.iter_rows():
                for cell in row:
                    cell.font = body_font
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(width * 1.2 + 3, 70)
            for (sheet, header), rules in CONDITIONAL_FORMATS.items():
                if sheet != name or header not in df.columns:
                    continue
                letter = get_column_letter(list(df.columns).index(header) + 1)
                rng = "%s2:%s%d" % (letter, letter, max(ws.max_row, 2))
                for value, (fill, font) in rules.items():
                    ws.conditional_formatting.add(
                        rng, CellIsRule(operator="equal", formula=[str(value).upper() if isinstance(value, bool) else '"%s"' % value], fill=fill, font=font))


def main():
    parser = argparse.ArgumentParser()
    ukg_auth.add_auth_args(parser)
    parser.add_argument("-o", "--output", default="integration_inventory.xlsx")
    parser.add_argument("--no-timestamp", action="store_true",
                        help="Write exactly to --output instead of appending _YYYYMMDD_HHMMSS.")
    parser.add_argument("--from-date", default="2020-01-01")
    parser.add_argument("--to-date", default="2026-12-31")
    args = parser.parse_args()

    client = ukg_auth.client_from_args(args)
    frames = collect_inventory(client, args.from_date, args.to_date)
    out = args.output if args.no_timestamp else timestamped_path(args.output)
    write_workbook(frames, out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
