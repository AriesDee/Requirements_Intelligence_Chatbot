"""
fap_template_tool.py — Build a Create-tab Excel template from an existing UKG Function Access Profile

  GET https://<env url>/api/v1/commons/function_access_profiles?name=<FAP>

Writes the profile's permissions in the layout fap_create_tool reads, so the file can be edited
(add or delete control points, change actions and scopes) and then used to create a new FAP:

  Control Point | ADD | EDIT | DELETE | VIEW | ALLOWED | scopeName

One row per control point and scope. A control point whose actions have different scopes
(e.g. PERSON: ADD = ALL, EDIT = ALL_BUT_SELF) gets one row per scope - the Create tool accepts
that. The ALLOWED column is included because many control points use it instead of ADD/EDIT/
DELETE/VIEW. A Notes sheet records which FAP and environment the file came from.

After writing, the file is read back with the Create tool's own parser and compared with the FAP,
so a template that would not create the same permissions is reported instead of trusted.

Output: output/fap_template/<FAP>_<env>_<timestamp>.xlsx

Usage:
  python fap_template_tool.py --env NPR1 --source "Super Access" --no-verify-ssl
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
import fap_copy_tool as _fcopy

_HEADERS = ['Control Point', *_fc.ACTIONS, 'scopeName']   # ADD EDIT DELETE VIEW ALLOWED


def build_rows(permissions: list[dict]) -> tuple[list[list[str]], list[str]]:
    """Rows [control point, one cell per action ('x' or ''), scope] and warnings.

    Rows are grouped by (control point, scope) in the order first seen."""
    grouped: dict[tuple[str, str], set[str]] = {}
    warnings = []
    for p in permissions:
        key, scope, action = p.get('controlPointKey'), p.get('scopeName'), p.get('actionName')
        if not (key and scope and action):
            warnings.append(f'Skipped an incomplete permission: {p}')
        elif action not in _fc.ACTIONS:
            warnings.append(f'{key}: action "{action}" has no column in the template - left out.')
        else:
            grouped.setdefault((key, scope), set()).add(action)
    rows = [[key, *['x' if a in actions else '' for a in _fc.ACTIONS], scope]
            for (key, scope), actions in grouped.items()]
    return rows, warnings


def write_template(record: dict, path: Path, env: str) -> tuple[int, list[str]]:
    """Write the Excel template for a FAP record. Returns (permission count, warnings)."""
    rows, warnings = build_rows(record.get('permissionTypes', []))
    wb = Workbook()
    ws = wb.active
    ws.title = 'FAP'
    ws.append(_HEADERS)
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F4E78')
    ws.column_dimensions['A'].width = 48
    ws.column_dimensions['G'].width = 16
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions

    notes = wb.create_sheet('Notes')
    for line in (
            f'Template built from FAP "{record.get("name")}" (id {record.get("id")}) in {env} '
            f'on {datetime.now():%Y-%m-%d %H:%M}.',
            f'Source description: {record.get("description") or ""}',
            'Edit the FAP sheet: add rows for new control points, delete rows to drop them.',
            'Mark ADD / EDIT / DELETE / VIEW / ALLOWED with x where the profile has access; '
            'leave blank otherwise.',
            f'scopeName: {", ".join(_fc.SCOPES)} (applies to every x on the row). A control point '
            'with different scopes per action has one row per scope.',
            'Use the Create tab with this file to make a new FAP; the first sheet is read.'):
        notes.append([line])
    notes.column_dimensions['A'].width = 110

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(record.get('permissionTypes', [])), warnings


def _as_set(permissions: list[dict]) -> set[tuple[str, str, str]]:
    return {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in permissions
            if p.get('controlPointKey') and p.get('actionName') and p.get('scopeName')}


def run(client, source_name: str, output_dir: Path, result: dict | None = None) -> bool:
    """Fetch source_name and write its template. Returns True on success.

    If `result` is given, result['path'] is set to the file written."""
    source_name = source_name.strip()
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_template_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    if not source_name:
        print('\nERROR: FAP name is required - nothing was written.')
        return False
    print(f'Template from FAP "{source_name}"')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    records = _fap.fetch_fap(client, source_name)
    matches = _fcopy.find_exact(records, source_name)
    if not matches:
        hint = (' Similar names: ' + ', '.join(str(r.get('name')) for r in records[:5])
                if records else '')
        print(f'\nFAILED - FAP "{source_name}" does not exist in {env}.{hint}')
        return False
    if len(matches) > 1:
        print(f'\nFAILED - "{source_name}" matches {len(matches)} FAPs in {env}; cannot choose.')
        return False
    record = matches[0]

    safe = _fc._safe_name(str(record.get('name')))
    path = Path(output_dir) / 'fap_template' / f'{safe}_{env}_{ts}.xlsx'
    count, warnings = write_template(record, path, env)
    if result is not None:
        result['path'] = str(path)
    for w in warnings:
        print(f'WARNING: {w}')

    # Read the file back with the Create tool's parser and compare with the FAP.
    try:
        back, _ = _fc.read_permissions(path)
    except _fc.FapExcelError as exc:
        print('\nFAILED - the template does not read back as a valid Create file:')
        for p in exc.problems:
            print(f'  - {p}')
        return False
    missing = _as_set(record.get('permissionTypes', [])) - _as_set(back)
    extra = _as_set(back) - _as_set(record.get('permissionTypes', []))
    if missing or extra:
        print(f'WARNING: template differs from the FAP: {len(missing)} missing, {len(extra)} extra.')
    else:
        print(f'Verified: the template reads back as exactly the same {len(back)} permission(s).')

    control_points = len({p['controlPointKey'] for p in record.get('permissionTypes', [])})
    print(f'\nCOMPLETED - template saved: {path}')
    print(f'{count} permission(s) across {control_points} control point(s) from "{record.get("name")}" '
          f'(id {record.get("id")}).')
    return True


def write_all_control_points(reference: dict, path: Path, env: str) -> int:
    """Write a template listing every control point of `reference` (Super Access) with the
    action and scope cells left empty. A second sheet shows the actions valid for each control
    point. Returns the number of control points."""
    valid: dict[str, set[str]] = {}
    for p in reference.get('permissionTypes', []):
        if p.get('controlPointKey') and p.get('actionName'):
            valid.setdefault(p['controlPointKey'], set()).add(p['actionName'])
    keys = sorted(valid)

    wb = Workbook()
    ws = wb.active
    ws.title = 'FAP'
    ws.append(_HEADERS)
    for key in keys:
        ws.append([key])
    ws2 = wb.create_sheet('Valid Actions')
    ws2.append(['Control Point', 'Valid actions'])
    for key in keys:
        ws2.append([key, ', '.join(a for a in _fc.ACTIONS if a in valid[key])])
    notes = wb.create_sheet('Notes')
    for line in (
            f'Every control point of "{reference.get("name")}" in {env} on {datetime.now():%Y-%m-%d %H:%M}; '
            'actions and scopes are empty.',
            'On the FAP sheet mark ADD / EDIT / DELETE / VIEW / ALLOWED with x and fill scopeName '
            f'({", ".join(_fc.SCOPES)}) on the rows the new profile should have.',
            'Rows with nothing marked are ignored, so unused control points can stay.',
            'The Valid Actions sheet shows which actions each control point accepts. A control '
            'point whose actions have different scopes needs one row per scope (copy the row).',
            'Use the Create tab with this file; the first sheet is read.'):
        notes.append([line])

    for sheet, widths in ((ws, {'A': 48, 'G': 16}), (ws2, {'A': 48, 'B': 40}), (notes, {'A': 110})):
        for col, width in widths.items():
            sheet.column_dimensions[col].width = width
    for sheet in (ws, ws2):
        for c in sheet[1]:
            c.font = Font(bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor='1F4E78')
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return len(keys)


def run_all_control_points(client, output_dir: Path) -> bool:
    """Write the all-control-points template from Super Access. Returns True on success."""
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_template_{env}_{ts}.log')
    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'Template listing every control point of "{_fc.REFERENCE_FAP}"')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    matches = _fcopy.find_exact(_fap.fetch_fap(client, _fc.REFERENCE_FAP), _fc.REFERENCE_FAP)
    if len(matches) != 1:
        print(f'\nFAILED - "{_fc.REFERENCE_FAP}" was not found (exactly once) in {env}; '
              'no template was written.')
        return False
    path = Path(output_dir) / 'fap_template' / f'all_control_points_{env}_{ts}.xlsx'
    count = write_all_control_points(matches[0], path, env)
    if not count:
        print(f'\nFAILED - "{_fc.REFERENCE_FAP}" has no control points; no template was written.')
        return False
    print(f'\nCOMPLETED - template saved: {path}')
    print(f'{count} control point(s) listed, actions and scopes left empty. Mark what the new '
          'profile needs, then use the file on the Create tab.')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Build a Create-tab Excel template from an existing UKG Function Access Profile')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--source', help='Name of the FAP to build the template from')
    parser.add_argument('--all-control-points', action='store_true',
                        help=f'Instead, list every control point of "{_fc.REFERENCE_FAP}" with '
                             'actions and scopes empty')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; the file goes to <dir>/fap_template/')
    args = parser.parse_args()
    if not args.source and not args.all_control_points:
        parser.error('give --source <FAP name> or --all-control-points')
    try:
        client = ukg_env.client_from_args(args)
        ok = (run_all_control_points(client, Path(args.output_dir)) if args.all_control_points
              else run(client, args.source, Path(args.output_dir)))
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
