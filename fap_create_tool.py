"""
fap_create_tool.py — Create a UKG Function Access Profile (FAP) from an Excel file

Reads an Excel sheet of control points + permissions, builds the payload and calls
  POST https://<env url>/api/v1/commons/function_access_profiles

Excel layout (first sheet, header row required, column order does not matter):

  Control Point | ADD | EDIT | DELETE | VIEW | scopeName
  ------------- | --- | ---- | ------ | ---- | ---------
  WFS_BASELINE_STAFF_PATTERN_VIEW | x | x | x | x | ALL
  SA_DISPLAY_DAY_BEFORE_AND_AFTER |   |   |   | x | ONLY_SELF

  Control Point  the controlPointKey ("controlPointKey" is also accepted as the header)
  ADD/EDIT/DELETE/VIEW  mark with x where the profile has that access; an optional ALLOWED
                 column works the same way
  scopeName      ALL, ALL_BUT_SELF, ONLY_SELF or NONE - applies to every x on that row

Each x becomes one entry in permissionTypes:
  {"actionName": "VIEW", "scopeName": "ALL", "controlPointKey": "WFS_..."}

The profile name and description are supplied by the caller (UI field / --name / --description).

Assumption: the UKG API documentation does not say which control points (keys) or which actions
per control point are valid, so Super Access - the built-in profile that has every control point
with all its valid actions - is the basis for correctness. Before anything is sent every row is
checked against it; an unknown control point or an action Super Access lacks for it blocks the
run. (Documented values - the five actions and four scopes - are checked separately.)

Connection (environment + credentials) comes from ukg_env, same as every other UKG tool.

Each run writes output/fap_create/fap_create_<env>_<timestamp>/ with payload.json (what was
sent) and, after a real run, response.json (what UKG returned).

Usage:
  python fap_create_tool.py --env NPR1 --file input/fap_create/person_viewer.xlsx \\
         --name "Person Viewer" --description "Person Viewer" --dry-run
  python fap_create_tool.py --env NPR1 --file input/fap_create/person_viewer.xlsx \\
         --name "Person Viewer" --description "Person Viewer" --no-verify-ssl
  python fap_create_tool.py --template          # write an empty Excel template
"""

import sys
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

import ukg_api_tool as _uat          # folders + logging only; auth comes from ukg_env
import ukg_env
import fap_tool as _fap

REFERENCE_FAP = 'Super Access'   # has every control point with its valid actions
FAP_ENDPOINT = '/api/v1/commons/function_access_profiles'
FAP_CREATE_INPUT_DIR = _uat.INPUT_DIR / 'fap_create'
TEMPLATE_FILE = _uat.BASE_DIR / 'template' / 'fap_create_template.xlsx'

ACTIONS = ('ADD', 'EDIT', 'DELETE', 'VIEW', 'ALLOWED')   # payload order within a control point
REQUIRED_ACTIONS = ('ADD', 'EDIT', 'DELETE', 'VIEW')     # ALLOWED is an optional column
SCOPES = ('ALL', 'ALL_BUT_SELF', 'ONLY_SELF', 'NONE')

_CONTROL_POINT_HEADERS = ('controlpoint', 'controlpointkey')
_SCOPE_HEADERS = ('scopename', 'scope')
_HEADER_SEARCH_ROWS = 10


class FapExcelError(Exception):
    """The Excel file cannot be turned into a payload; str() lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__('\n'.join(problems))


# ---------------------------------------------------------------------------
# Excel -> payload
# ---------------------------------------------------------------------------

def _norm(value) -> str:
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


def _find_header(ws) -> tuple[int, dict[str, int]]:
    """Locate the header row. Returns (row number, {role: column index}) where role is
    'control_point', 'scope' or an action name."""
    for row_no, row in enumerate(ws.iter_rows(max_row=_HEADER_SEARCH_ROWS, values_only=True), 1):
        cols: dict[str, int] = {}
        for idx, cell in enumerate(row):
            key = _norm(cell)
            if key in _CONTROL_POINT_HEADERS:
                cols.setdefault('control_point', idx)
            elif key in _SCOPE_HEADERS:
                cols.setdefault('scope', idx)
            elif key.upper() in ACTIONS:
                cols.setdefault(key.upper(), idx)
        if 'control_point' in cols:
            missing = [h for h in ('scope', *REQUIRED_ACTIONS) if h not in cols]
            if missing:
                raise FapExcelError([
                    f'Header row {row_no} is missing column(s): '
                    + ', '.join('scopeName' if m == 'scope' else m for m in missing)])
            return row_no, cols
    raise FapExcelError([f'No header row with a "Control Point" column in the first '
                         f'{_HEADER_SEARCH_ROWS} rows of the first sheet.'])


def read_permissions(file_path) -> tuple[list[dict], list[str]]:
    """Parse the Excel file. Returns (permissionTypes, warnings); raises FapExcelError listing
    every problem (not just the first) so the sheet can be fixed in one pass."""
    path = Path(file_path)
    if not path.is_file():
        raise FapExcelError([f'File not found: {path}'])
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise FapExcelError([f'Cannot open {path.name} as an Excel workbook: {exc}'])
    try:
        ws = wb.worksheets[0]
        header_row, cols = _find_header(ws)

        problems: list[str] = []
        warnings: list[str] = []
        permissions: list[dict] = []
        unmarked: list[str] = []
        seen: dict[tuple[str, str], int] = {}
        action_cols = [(a, cols[a]) for a in ACTIONS if a in cols]

        for row_no, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True),
                                     header_row + 1):
            def cell(idx):
                return row[idx] if idx < len(row) else None

            key = str(cell(cols['control_point']) or '').strip()
            if not key and not any(str(cell(i) or '').strip() for _, i in action_cols):
                continue                                    # blank row
            if not key:
                problems.append(f'Row {row_no}: access is marked but Control Point is blank.')
                continue

            marked = []
            for action, idx in action_cols:
                mark = str(cell(idx) or '').strip()
                if not mark:
                    continue
                if mark.lower() != 'x':
                    problems.append(f'Row {row_no} ({key}): {action} is "{mark}" - '
                                    'use x to grant access, or leave blank.')
                else:
                    marked.append(action)
            if not marked:
                unmarked.append(f'Row {row_no} ({key}): no access marked - skipped.')
                continue

            scope = re.sub(r'[\s-]+', '_', str(cell(cols['scope']) or '').strip().upper())
            if scope not in SCOPES:
                problems.append(f'Row {row_no} ({key}): scopeName "{cell(cols["scope"]) or ""}" '
                                f'is not one of {", ".join(SCOPES)}.')
                continue

            for action in marked:
                if (key, action) in seen:
                    problems.append(f'Row {row_no} ({key}): {action} already defined on row '
                                    f'{seen[(key, action)]}.')
                    continue
                seen[(key, action)] = row_no
                permissions.append({'actionName': action, 'scopeName': scope,
                                    'controlPointKey': key})

        # A template listing every control point leaves most rows unmarked: summarise those.
        if len(unmarked) > 5:
            warnings.append(f'{len(unmarked)} row(s) have no access marked - skipped '
                            f'(first: {unmarked[0].split(" - ")[0]}).')
        else:
            warnings.extend(unmarked)
        if not problems and not permissions:
            problems.append('No permissions found - mark at least one action with x.')
        if problems:
            raise FapExcelError(problems)
        return permissions, warnings
    finally:
        wb.close()


def build_payload(name: str, description: str, permissions: list[dict]) -> dict:
    return {'name': name, 'permissionTypes': permissions,
            'description': description, 'isDefault': False}


def validate_payload(payload: dict, check_keys: set[str] | None = None) -> list[str]:
    """Problems that must stop a create/update before anything is sent (empty list = OK).

    Checks only what the UKG documentation defines: actionName is one of ACTIONS, scopeName is
    one of SCOPES, every permission has its three fields, and no control point repeats an
    action. Which control points / actions UKG accepts is not documented - UKG's response says.

    check_keys limits the per-permission checks to those control points (Update: only the ones
    taken from the Excel file; the rest are the profile's own data, re-sent as they came).
    None checks every permission. Duplicate actions are always checked."""
    problems: list[str] = []
    if not isinstance(payload.get('name'), str) or not payload['name'].strip():
        problems.append('name is required.')
    if not isinstance(payload.get('description'), str):
        problems.append('description must be text.')
    if not isinstance(payload.get('isDefault'), bool):
        problems.append('isDefault must be true or false.')
    if 'id' in payload and not isinstance(payload['id'], int):
        problems.append(f'id must be a number (got {payload["id"]!r}).')
    perms = payload.get('permissionTypes')
    if not isinstance(perms, list) or not perms:
        return problems + ['permissionTypes must list at least one permission.']

    seen: dict[tuple[str, str], int] = {}
    for n, p in enumerate(perms, 1):
        if not isinstance(p, dict):
            problems.append(f'permission {n}: not an object.')
            continue
        key, action, scope = (p.get(k) for k in ('controlPointKey', 'actionName', 'scopeName'))
        label = f'permission {n} ({key or "no control point"})'
        if check_keys is None or key in check_keys:
            if not isinstance(key, str) or not key.strip():
                problems.append(f'{label}: controlPointKey is missing.')
            elif key != key.strip() or re.search(r'\s', key):
                problems.append(f'{label}: controlPointKey "{key}" contains spaces.')
            if action not in ACTIONS:
                problems.append(f'{label}: actionName "{action}" is not one of {", ".join(ACTIONS)}.')
            if scope not in SCOPES:
                problems.append(f'{label}: scopeName "{scope}" is not one of {", ".join(SCOPES)}.')
        if isinstance(key, str) and action:
            if (key, action) in seen:
                problems.append(f'{label}: {action} is already defined for this control point '
                                f'(permission {seen[(key, action)]}).')
            else:
                seen[(key, action)] = n
    return problems


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

def write_template(path: Path = TEMPLATE_FILE, examples: bool = True) -> Path:
    """Empty template. examples=False leaves the FAP sheet with only the header row."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'FAP'
    headers = ['Control Point', *REQUIRED_ACTIONS, 'scopeName']
    ws.append(headers)
    if examples:
        ws.append(['WFS_BASELINE_STAFF_PATTERN_VIEW', 'x', 'x', 'x', 'x', 'ALL'])
        ws.append(['SA_DISPLAY_DAY_BEFORE_AND_AFTER', None, None, None, 'x', 'ONLY_SELF'])
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F4E78')
    ws.column_dimensions['A'].width = 48
    ws.column_dimensions['F'].width = 16
    ws.freeze_panes = 'A2'
    notes = wb.create_sheet('Notes')
    notes.append(['Mark ADD / EDIT / DELETE / VIEW with x where the profile has access.'])
    notes.append([f'scopeName: {", ".join(SCOPES)} (applies to every x on the row).'])
    notes.append(['Optional: add an ALLOWED column, marked the same way.'])
    notes.append(['The first sheet is read.' + (' The two rows on it are examples - replace them.'
                                                 if examples else
                                                 ' Add one row per control point and scope, e.g. '
                                                 'WFS_BASELINE_STAFF_PATTERN_VIEW | x | x | x | x | ALL.')])
    notes.column_dimensions['A'].width = 80
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def create_fap(client, payload: dict):
    """POST the payload. Returns the requests.Response (caller decides how to report it)."""
    _uat.logger.info(f'POST https://{client.base_url}{FAP_ENDPOINT}')
    _uat.logger.debug(f'POST payload: {json.dumps(payload)}')
    return client.request('POST', FAP_ENDPOINT, json=payload)


def log_would_send(client, method: str, path: str, payload=None):
    """Preview runs: record the write request the real run would send (and its payload) in the
    log, the way the real run does. Nothing is sent."""
    _uat.logger.info(f'WOULD SEND (not sent): {method} https://{client.base_url}{path}')
    if payload is not None:
        _uat.logger.debug(f'{method} payload: {json.dumps(payload)}')


def _safe_name(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_')[:60] or 'fap'


def check_against_reference(permissions: list[dict], reference: list[dict]) -> list[str]:
    """Compare Excel permissions with the reference profile (Super Access). Returns errors.

    ASSUMPTION: Super Access holds every control point (key) UKG has, each with every action
    valid for it. The UKG API documentation does not list valid control points or actions, so
    Super Access is the basis for correctness. A control point that is not in it, or an action
    it does not have for that control point, is an error and blocks the run. Scopes are not
    checked here (the documented values are checked by validate_payload)."""
    valid: dict[str, set[str]] = {}
    for p in reference:
        if p.get('controlPointKey') and p.get('actionName'):
            valid.setdefault(p['controlPointKey'], set()).add(p['actionName'])
    errors, unknown = [], set()
    for p in permissions:
        key, action = p['controlPointKey'], p['actionName']
        if key not in valid:
            if key not in unknown:
                unknown.add(key)
                errors.append(f'{key}: control point not found in {REFERENCE_FAP} - check the spelling.')
        elif action not in valid[key]:
            errors.append(f'{key}: {action} is not valid for this control point. '
                          f'Valid: {", ".join(a for a in ACTIONS if a in valid[key]) or "none"}')
    return errors


def reference_check(client, permissions: list[dict], consequence: str) -> bool:
    """Check every row against Super Access (see check_against_reference for the assumption).

    Prints the outcome and returns False - blocking the run - on any unknown control point or
    invalid action. If Super Access cannot be read the check cannot be done, so that blocks too."""
    try:
        found = _fap.fetch_fap(client, REFERENCE_FAP)
        reference = next((r for r in found
                          if str(r.get('name', '')).strip().lower() == REFERENCE_FAP.lower()), None)
    except Exception as exc:
        print(f'\nERROR: could not read "{REFERENCE_FAP}" ({exc}) - the check against it could '
              f'not be done, {consequence}.')
        return False
    if reference is None:
        print(f'\nERROR: "{REFERENCE_FAP}" not found in {client.env} - the check against it could '
              f'not be done, {consequence}.')
        return False
    errors = check_against_reference(permissions, reference.get('permissionTypes', []))
    if errors:
        print(f'\nERROR: {len(errors)} problem(s) found against "{REFERENCE_FAP}" - {consequence}:')
        for e in errors:
            print(f'  - {e}')
        return False
    print(f'Checked every control point and action against "{REFERENCE_FAP}": OK.')
    return True


def save_payload(file_path, name: str, description: str, output_dir: Path, client=None) -> bool:
    """Excel -> create payload JSON only. Nothing is ever sent to create anything.

    Without a client there is no connection at all. With a client the Super Access check also
    runs (read-only lookups) and a wrong action stops the save.

    Saves <output_dir>/fap_payload/<name>_<ts>.json - the same payload "Create FAP" builds
    from the same file. Returns True if saved."""
    name = name.strip()
    description = description.strip() or name
    if not name:
        print('ERROR: FAP name is required - nothing was saved.')
        return False
    print(f'FAP name:    {name}')
    print(f'Description: {description}')
    print(f'File:        {file_path}')
    try:
        permissions, warnings = read_permissions(file_path)
    except FapExcelError as exc:
        print(f'\nERROR: {len(exc.problems)} problem(s) in the Excel file - nothing was saved:')
        for p in exc.problems:
            print(f'  - {p}')
        return False
    for w in warnings:
        print(f'WARNING: {w}')
    payload = build_payload(name, description, permissions)
    problems = validate_payload(payload)
    if problems:
        print(f'\nERROR: {len(problems)} problem(s) in the payload - nothing was saved:')
        for p in problems:
            print(f'  - {p}')
        return False
    if client is not None:
        client.generate_access_token()
        _uat.logger.info('Authentication successful')
        if not reference_check(client, permissions, 'nothing was saved'):
            return False
    path = Path(output_dir) / 'fap_payload' / \
        f'dry_run_{_safe_name(name)}_{datetime.now():%Y%m%d_%H%M%S}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    control_points = len({p['controlPointKey'] for p in permissions})
    print(f'\nCOMPLETED - payload saved: {path}')
    print(f'{len(permissions)} permission(s) across {control_points} control point(s). '
          + ('Checked against Super Access.' if client is not None
             else 'Not checked against UKG (no connection was made).'))
    return True


def run(client, file_path, name: str, description: str, output_dir: Path,
        dry_run: bool = False) -> bool:
    """Parse the Excel file and create the FAP. Returns True on success (dry run: valid file).

    Results go to <output_dir>/fap_create/fap_create_<env>_<ts>/."""
    env = client.env
    name, description = name.strip(), description.strip() or name.strip()
    if not name:
        raise ValueError('FAP name is required.')

    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_create_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'FAP name:    {name}')
    print(f'Description: {description}')
    print(f'File:        {file_path}')

    try:
        permissions, warnings = read_permissions(file_path)
    except FapExcelError as exc:
        print(f'\nERROR: {len(exc.problems)} problem(s) in the Excel file - nothing was sent:')
        for p in exc.problems:
            print(f'  - {p}')
        return False
    for w in warnings:
        print(f'WARNING: {w}')

    payload = build_payload(name, description, permissions)
    out_dir = output_dir / 'fap_create' / f'fap_create_{env}_{ts}'
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_file = out_dir / (f'dry_run_{_safe_name(name)}_{env}_{ts}.json' if dry_run
                              else 'payload.json')
    payload_file.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    control_points = len({p['controlPointKey'] for p in permissions})
    print(f'\nParsed {len(permissions)} permission(s) across {control_points} control point(s).')
    print(f'Payload saved: {payload_file}')

    problems = validate_payload(payload)
    if problems:
        print(f'\nERROR: {len(problems)} problem(s) in the payload - nothing was sent:')
        for p in problems:
            print(f'  - {p}')
        return False
    print('Payload validated: OK.')

    # Connect (needed for the reference check, and for the create itself).
    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    # The name must not already exist (UKG's name lookup is an exact match).
    existing = [r for r in _fap.fetch_fap(client, name)
                if str(r.get('name', '')).strip().lower() == name.lower()]
    if existing:
        print(f'\nFAILED - a FAP named "{name}" already exists in {env} '
              f'(id {existing[0].get("id")}). Choose a different name; nothing was created.')
        return False
    print(f'"{name}" does not exist in {env} yet.')

    if not reference_check(client, permissions, 'nothing was created'):
        return False

    if dry_run:
        log_would_send(client, 'POST', FAP_ENDPOINT, payload)
        print('\nDRY RUN - the Excel file is valid and the payload above is exactly what '
              '"Create FAP" would send. Nothing was created (only read-only lookups were made).')
        return True

    resp = create_fap(client, payload)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    (out_dir / 'response.json').write_text(
        json.dumps({'status': resp.status_code, 'body': body}, indent=2), encoding='utf-8')

    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code}: {resp.text}')
        print(f'\nFAILED - FAP "{name}" was NOT created in {env} (HTTP {resp.status_code}).')
        return False
    print(f'\nCOMPLETED - FAP "{name}" created in {env} (HTTP {resp.status_code}).')
    print(f'Response saved: {out_dir / "response.json"}')
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Create a UKG Function Access Profile from an Excel file')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--template', action='store_true',
                        help=f'Write an empty Excel template to {TEMPLATE_FILE} and exit')
    parser.add_argument('--file', help='Excel file of control points and permissions')
    parser.add_argument('--name', help='Function Access Profile name')
    parser.add_argument('--description', default='',
                        help='Profile description (default: same as --name)')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; results go to <dir>/fap_create/')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate the Excel file and save the payload without calling the API')
    # --env is required by the shared flags but not for --template
    if '--template' in sys.argv:
        print(f'Template written: {write_template()}')
        return
    args = parser.parse_args()
    if not args.file or not args.name:
        parser.error('--file and --name are required')

    try:
        client = ukg_env.client_from_args(args)
        ok = run(client, args.file, args.name, args.description, Path(args.output_dir),
                 dry_run=args.dry_run)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
