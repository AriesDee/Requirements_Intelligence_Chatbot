"""
fap_read_tool.py — Read UKG Function Access Profiles and save them to an Excel report

  GET https://<env url>/api/v1/commons/function_access_profiles                 (all FAPs)
  GET https://<env url>/api/v1/commons/function_access_profiles?name=<FAP>      (that FAP)

Read-only. Two modes:

  No name  - one request returns every FAP, but UKG's list has only id, name and (sometimes)
             description: NO permissions. The report is a directory listing (FAPs sheet only).
  Names    - one request per name returns the full definition, including permissions. The name
             must match exactly (a partial name such as "Super Acces" gives WCO-127822 "A Function
             Access Profile does not exist with specified name"). A name that is not found or is
             ambiguous is skipped and reported; the others carry on.

Excel report (output/fap_read/fap_read_<env>_<all|name|N_faps>_<timestamp>.xlsx):
  No name: FAPs (id, name, description) and Notes.
  Names:   FAPs (id, name, description, isDefault, permission count, control point count),
           Permissions (one row per permission: FAP, id, control point, action, scope) and Notes.
           Option "separate tabs": instead of Permissions, one tab per FAP (named after it) with
           Control Point, actionName, scopeName.
To get a FAP in the layout the Create / Update tabs read, use Copy -> "Excel file" instead.

Usage:
  python fap_read_tool.py --env NPR1                                    # all FAPs (no permissions)
  python fap_read_tool.py --env NPR1 --name "Super Access"              # with permissions
  python fap_read_tool.py --env NPR1 --name "Super Access" --name "Team FAP"
"""

import re
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
import fap_copy_tool as _fcopy
import fap_delete_tool as _fdel

NO_PERMISSIONS_NOTE = ('UKG does not return permissions when all FAPs are listed. To get a FAP\'s '
                       'permissions, enter its exact name (one or more names) on the Read tab.')


def fetch_all(client) -> list[dict]:
    """GET every FAP (no name parameter). The records have no permissions."""
    path = _fc.FAP_ENDPOINT
    _uat.logger.info(f'GET https://{client.base_url}{path}')
    resp = client.request('GET', path)
    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code}: {resp.text}')
        resp.raise_for_status()
    return _fap._records(resp.json())


def resolve(client, names: list[str]):
    """Look each name up (exact match). Returns (records, skipped) with skipped = [(name, reason)]."""
    records, skipped = [], []
    for name in names:
        try:
            matches = _fcopy.find_exact(_fap.fetch_fap(client, name), name)
        except Exception as exc:
            _uat.logger.error(f'Could not read "{name}": {exc}')
            skipped.append((name, f'could not be read ({exc})'))
            continue
        if not matches:
            skipped.append((name, f'does not exist in {client.env} (the name must match exactly)'))
        elif len(matches) > 1:
            skipped.append((name, f'matches {len(matches)} FAPs - cannot choose'))
        else:
            records.append(matches[0])
    return records, skipped


def _style(sheets_widths):
    for sheet, widths, header in sheets_widths:
        for col, width in widths.items():
            sheet.column_dimensions[col].width = width
        if header:
            for c in sheet[1]:
                c.font = Font(bold=True, color='FFFFFF')
                c.fill = PatternFill('solid', fgColor='1F4E78')
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions


def _by_name(records):
    return sorted(records, key=lambda x: str(x.get('name', '')).lower())


def write_list_report(records: list[dict], path: Path, env: str) -> int:
    """Directory listing: FAPs (id, name, description) and Notes. Returns the FAP count."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'FAPs'
    ws.append(['id', 'name', 'description'])
    for r in _by_name(records):
        ws.append([r.get('id'), r.get('name'), r.get('description')])
    notes = wb.create_sheet('Notes')
    notes.append([f'Read from {env} on {datetime.now():%Y-%m-%d %H:%M}: all FAPs ({len(records)}).'])
    notes.append([NO_PERMISSIONS_NOTE])
    _style([(ws, {'A': 8, 'B': 48, 'C': 70}, True), (notes, {'A': 120}, False)])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(records)


def sheet_title(name: str, used: set[str]) -> str:
    """An Excel-safe, unique sheet name for a FAP: max 31 characters, none of []:*?/\\, not
    already used (case-insensitive; 'FAPs' and 'Notes' are reserved by the caller)."""
    base = re.sub(r'[\[\]:*?/\\]', '_', str(name or 'FAP')).strip().strip("'") or 'FAP'
    title, n = base[:31], 1
    while title.lower() in used:
        n += 1
        suffix = f' ({n})'
        title = base[:31 - len(suffix)] + suffix
    used.add(title.lower())
    return title


def write_report(records: list[dict], path: Path, env: str, names: list[str] | None = None,
                 skipped: list | None = None, separate_tabs: bool = False) -> tuple[int, int]:
    """Full report for FAPs read by name. Returns (FAP count, permission count).

    separate_tabs=False: one Permissions sheet for all FAPs. True: one sheet per FAP (named after
    the FAP) with its permissions, and no combined Permissions sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'FAPs'
    ws.append(['id', 'name', 'description', 'isDefault', 'permissions', 'control points'])
    perms = None if separate_tabs else wb.create_sheet('Permissions')
    if perms is not None:
        perms.append(['FAP', 'id', 'Control Point', 'actionName', 'scopeName'])
    used = {'faps', 'notes'}
    fap_sheets = []

    total = 0
    for r in _by_name(records):
        pts = r.get('permissionTypes', []) or []
        ws.append([r.get('id'), r.get('name'), r.get('description'), r.get('isDefault'),
                   len(pts), len({p.get('controlPointKey') for p in pts})])
        ordered = sorted(pts, key=lambda x: (str(x.get('controlPointKey')), str(x.get('actionName'))))
        if separate_tabs:
            sheet = wb.create_sheet(sheet_title(r.get('name'), used))
            sheet.append(['Control Point', 'actionName', 'scopeName'])
            for p in ordered:
                sheet.append([p.get('controlPointKey'), p.get('actionName'), p.get('scopeName')])
            fap_sheets.append(sheet)
        else:
            for p in ordered:
                perms.append([r.get('name'), r.get('id'), p.get('controlPointKey'),
                              p.get('actionName'), p.get('scopeName')])
        total += len(pts)

    notes = wb.create_sheet('Notes')
    notes.append([f'Read from {env} on {datetime.now():%Y-%m-%d %H:%M}: '
                  + ', '.join(f'"{n}"' for n in (names or [r.get('name') for r in records])) + '.'])
    for n, why in skipped or []:
        notes.append([f'Not included: "{n}" {why}.'])
    notes.append(['This is a read-only report. To get a FAP in the layout the Create / Update tabs '
                  'read, use Copy -> "Excel file".'])
    styled = [(ws, {'A': 8, 'B': 40, 'C': 50, 'D': 11, 'E': 13, 'F': 15}, True),
              (notes, {'A': 120}, False)]
    if perms is not None:
        styled.insert(1, (perms, {'A': 40, 'B': 8, 'C': 48, 'D': 13, 'E': 15}, True))
    styled += [(sheet, {'A': 48, 'B': 13, 'C': 15}, True) for sheet in fap_sheets]
    _style(styled)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(records), total


def run(client, names, output_dir: Path, separate_tabs: bool = False) -> bool:
    """Read all FAPs (no names: list only, no permissions) or the FAPs called `names` (with
    permissions) and save the Excel report. `names` is a list of names or text with one per line."""
    names = _fdel.parse_names(names if isinstance(names, str) else '\n'.join(names))
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_read_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'Reading: {str(len(names)) + " FAP(s) by name" if names else "all FAPs (list only)"}')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    out_dir = Path(output_dir) / 'fap_read'
    if not names:
        records = fetch_all(client)
        if not records:
            print(f'\nNOTHING FOUND - no FAPs were returned in {env}; no file was written.')
            return False
        _uat.logger.debug(f'First record keys: {sorted(records[0])}')
        path = out_dir / f'fap_read_{env}_all_{ts}.xlsx'
        count = write_list_report(records, path, env)
        print(f'\nCOMPLETED - report saved: {path}')
        print(f'{count} FAP(s) listed (id, name, description).')
        print(f'NOTE: {NO_PERMISSIONS_NOTE}')
        return True

    records, skipped = resolve(client, names)
    for n, why in skipped:
        print(f'  SKIP    "{n}" {why}')
    if not records:
        print('\nNOTHING FOUND - none of the names could be read; no file was written.')
        return False
    for r in _by_name(records):
        print(f'  id {r.get("id")!s:<6} {r.get("name")}  ({len(r.get("permissionTypes", []) or [])} permission(s))')

    label = _fc._safe_name(str(records[0].get('name'))) if len(names) == 1 else f'{len(names)}_faps'
    path = out_dir / f'fap_read_{env}_{label}_{ts}.xlsx'
    faps, perms = write_report(records, path, env, names, skipped, separate_tabs)
    print(f'\nCOMPLETED - report saved: {path}')
    print(f'{faps} FAP(s), {perms} permission(s) in total.'
          + (f' {len(skipped)} name(s) skipped.' if skipped else ''))
    return True


def main():
    parser = argparse.ArgumentParser(description='Read UKG Function Access Profiles to an Excel report')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--name', action='append', default=[],
                        help='FAP name to read with its permissions (repeat for several; omit for '
                             'a list of all FAPs without permissions)')
    parser.add_argument('--separate-tabs', action='store_true',
                        help='With --name: one tab per FAP instead of one combined Permissions tab')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; the file goes to <dir>/fap_read/')
    args = parser.parse_args()
    try:
        ok = run(ukg_env.client_from_args(args), args.name, Path(args.output_dir), args.separate_tabs)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
