"""
fap_read_tool.py — Read UKG Function Access Profiles and save them to an Excel report

  GET https://<env url>/api/v1/commons/function_access_profiles                 (all FAPs)
  GET https://<env url>/api/v1/commons/function_access_profiles?name=<FAP>      (that FAP)

Read-only. With no name every FAP is returned. With a name UKG returns only the FAP with exactly
that name; if there is none it answers WCO-127822 "A Function Access Profile does not exist with
specified name: <name>." (a partial name such as "Super Acces" finds nothing).

Excel report (output/fap_read/fap_read_<env>_<all|name>_<timestamp>.xlsx):
  FAPs         one row per FAP: id, name, description, isDefault, permission count, control points
  Permissions  one row per permission: FAP, id, control point, action, scope
  Notes        what was read, where and when
To get a FAP in the layout the Create / Update tabs read, use Copy -> "Excel file" instead.

Usage:
  python fap_read_tool.py --env NPR1                          # all FAPs
  python fap_read_tool.py --env NPR1 --name "Super Access"
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

import ukg_api_tool as _uat          # folders + logging only; auth comes from ukg_env
import ukg_env
import fap_tool as _fap
import fap_create_tool as _fc


def fetch_all(client) -> list[dict]:
    """GET every FAP (no name parameter)."""
    path = _fc.FAP_ENDPOINT
    _uat.logger.info(f'GET https://{client.base_url}{path}')
    resp = client.request('GET', path)
    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code}: {resp.text}')
        resp.raise_for_status()
    return _fap._records(resp.json())


def write_report(records: list[dict], path: Path, env: str, name: str = '') -> tuple[int, int]:
    """Write the Excel report. Returns (FAP count, permission count)."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'FAPs'
    ws.append(['id', 'name', 'description', 'isDefault', 'permissions', 'control points'])
    perms = wb.create_sheet('Permissions')
    perms.append(['FAP', 'id', 'Control Point', 'actionName', 'scopeName'])

    total = 0
    for r in sorted(records, key=lambda x: str(x.get('name', '')).lower()):
        pts = r.get('permissionTypes', []) or []
        ws.append([r.get('id'), r.get('name'), r.get('description'), r.get('isDefault'),
                   len(pts), len({p.get('controlPointKey') for p in pts})])
        for p in sorted(pts, key=lambda x: (str(x.get('controlPointKey')), str(x.get('actionName')))):
            perms.append([r.get('name'), r.get('id'), p.get('controlPointKey'),
                          p.get('actionName'), p.get('scopeName')])
        total += len(pts)

    notes = wb.create_sheet('Notes')
    notes.append([f'Read from {env} on {datetime.now():%Y-%m-%d %H:%M}: '
                  + (f'the FAP named "{name}".' if name else 'all FAPs.')])
    notes.append(['This is a read-only report. To get a FAP in the layout the Create / Update tabs '
                  'read, use Copy -> "Excel file".'])

    for sheet, widths in ((ws, {'A': 8, 'B': 40, 'C': 50, 'D': 11, 'E': 13, 'F': 15}),
                          (perms, {'A': 40, 'B': 8, 'C': 48, 'D': 13, 'E': 15}),
                          (notes, {'A': 110})):
        for col, width in widths.items():
            sheet.column_dimensions[col].width = width
    for sheet in (ws, perms):
        for c in sheet[1]:
            c.font = Font(bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor='1F4E78')
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(records), total


def run(client, name: str, output_dir: Path) -> bool:
    """Read all FAPs (blank name) or the FAP named `name` and save the Excel report."""
    name = name.strip()
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_read_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'Reading: {"FAP " + chr(34) + name + chr(34) if name else "all FAPs"}')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    records = _fap.fetch_fap(client, name) if name else fetch_all(client)
    if not records:
        why = (f'no FAP named "{name}" exists in {env} (the name must match exactly; UKG: WCO-127822)'
               if name else f'no FAPs were returned in {env}')
        print(f'\nNOTHING FOUND - {why}; no file was written.')
        return False

    for r in sorted(records, key=lambda x: str(x.get('name', '')).lower())[:50]:
        print(f'  id {r.get("id")!s:<6} {r.get("name")}  ({len(r.get("permissionTypes", []) or [])} permission(s))')
    if len(records) > 50:
        print(f'  ... and {len(records) - 50} more (see the Excel file)')

    label = _fc._safe_name(name) if name else 'all'
    path = Path(output_dir) / 'fap_read' / f'fap_read_{env}_{label}_{ts}.xlsx'
    faps, perms = write_report(records, path, env, name)
    print(f'\nCOMPLETED - report saved: {path}')
    print(f'{faps} FAP(s), {perms} permission(s) in total.')
    return True


def main():
    parser = argparse.ArgumentParser(description='Read UKG Function Access Profiles to an Excel report')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--name', default='', help='FAP name to look up (omit for all FAPs)')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; the file goes to <dir>/fap_read/')
    args = parser.parse_args()
    try:
        ok = run(ukg_env.client_from_args(args), args.name, Path(args.output_dir))
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
