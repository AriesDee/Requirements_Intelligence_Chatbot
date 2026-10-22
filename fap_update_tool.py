"""
fap_update_tool.py — Update an existing UKG Function Access Profile (FAP) from an Excel file

  GET https://<env url>/api/v1/commons/function_access_profiles?name=<FAP>
  PUT https://<env url>/api/v1/commons/function_access_profiles/<id>

UKG's PUT REPLACES the whole permission list (verified on NPR1): anything left out of the request
is removed. So the tool reads the profile as it is now, changes only the control points listed in
the Excel file, and sends the complete list back - every other control point stays exactly as is.

Rules for each control point in the Excel file (same layout as the Create tab):
  - it must already exist in the profile, otherwise it is skipped ("not in profile, not added");
    with --add-new (UI: "Add control points that are not in the profile") it is added instead
  - the Excel row(s) must contain every action the profile currently has for it, otherwise it is
    skipped, so by default nothing is removed; with --allow-removals (UI: "Allow removing
    actions") an action the row leaves out is removed - the preview marks it "REMOVES".
  - a control point that already matches the Excel file is reported as unchanged

Whole run stops (nothing is sent) when: the name is empty, the Excel file is invalid, the FAP is
not found or the name matches more than one, the FAP is built-in (negative id, e.g. Super Access),
an action is not valid for its control point (checked against Super Access), or there is nothing
to update.

Each run writes output/fap_update/fap_update_<env>_<timestamp>/:
  backup_<FAP>.json      the profile as it was before the update (use it to restore)
  payload.json           what the PUT sends (dry run: dry_run_<FAP>_<env>_<ts>.json instead)
  response.json          what UKG returned (real run only)
After a real update the profile is read back and compared with what was sent.

Usage:
  python fap_update_tool.py --env NPR1 --name "ADOMI01 Test FAP" --file changes.xlsx --dry-run
  python fap_update_tool.py --env NPR1 --name "ADOMI01 Test FAP" --file changes.xlsx
"""

import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

import ukg_api_tool as _uat          # folders + logging only; auth comes from ukg_env
import ukg_env
import fap_tool as _fap
import fap_create_tool as _fc
import fap_copy_tool as _fcopy

_PERMISSION_FIELDS = ('actionName', 'scopeName', 'controlPointKey')


def _clean(p: dict) -> dict:
    return {k: p[k] for k in _PERMISSION_FIELDS if k in p}


def _fmt(pairs) -> str:
    """[(action, scope), ...] -> 'ADD/ALL, EDIT/ALL' in the Create tab's action order."""
    order = {a: i for i, a in enumerate(_fc.ACTIONS)}
    return ', '.join(f'{a}/{s}' for a, s in
                     sorted(pairs, key=lambda x: (order.get(x[0], 99), x[0], x[1]))) or '(none)'


def plan_update(current: list[dict], excel: list[dict], add_new: bool = False,
                allow_removals: bool = False):
    """Work out the new permission list. Pure, so it can be tested without the API.

    Returns (new_permissions, updates, unchanged, skips) where
      updates   = [(control point, before, after)]  before/after are sets of (action, scope)
      unchanged = [control point]
      skips     = [(control point, reason)]
    new_permissions is the full list to PUT: every current permission, with the control points in
    `updates` replaced by their Excel rows.

    add_new: a control point that is not in the profile is added (default: skipped).
    allow_removals: an action the profile has but the Excel row lacks is removed (default: the
    control point is skipped)."""
    cur: dict[str, list[dict]] = {}
    for p in current:
        cur.setdefault(p['controlPointKey'], []).append(_clean(p))
    xl: dict[str, list[dict]] = {}
    for p in excel:
        xl.setdefault(p['controlPointKey'], []).append(_clean(p))

    updates, unchanged, skips = [], [], []
    for key, rows in xl.items():
        if key not in cur:
            if add_new:
                updates.append((key, set(), {(p['actionName'], p['scopeName']) for p in rows}))
            else:
                skips.append((key, 'not in profile, not added'))
            continue
        before = {(p['actionName'], p['scopeName']) for p in cur[key]}
        after = {(p['actionName'], p['scopeName']) for p in rows}
        missing = {a for a, _ in before} - {a for a, _ in after}
        if missing and not allow_removals:
            skips.append((key, f'Excel is missing action(s) the profile has: {", ".join(sorted(missing))}'
                               ' - provide all actions for the control point'))
        elif before == after:
            unchanged.append(key)
        else:
            updates.append((key, before, after))

    replace = {key for key, _, _ in updates}
    new, done = [], set()
    for p in current:
        key = p['controlPointKey']
        if key not in replace:
            new.append(_clean(p))
        elif key not in done:
            done.add(key)
            new.extend(xl[key])
    for key, _, _ in updates:                 # control points added to the profile
        if key not in done:
            new.extend(xl[key])
    return new, updates, unchanged, skips


def build_payload(record: dict, description: str, permissions: list[dict]) -> dict:
    """The PUT body: the existing profile with the new permission list."""
    return {'name': record.get('name'), 'permissionTypes': permissions,
            'description': description.strip() or record.get('description') or record.get('name'),
            'isDefault': bool(record.get('isDefault', False)), 'id': record.get('id')}


def _as_set(permissions: list[dict]) -> set[tuple[str, str, str]]:
    return {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in permissions
            if p.get('controlPointKey') and p.get('actionName') and p.get('scopeName')}


def update_fap(client, fap_id, payload: dict):
    """PUT the payload. Returns the requests.Response (caller decides how to report it)."""
    path = f'{_fc.FAP_ENDPOINT}/{fap_id}'
    _uat.logger.info(f'PUT https://{client.base_url}{path}')
    _uat.logger.debug(f'PUT payload: {json.dumps(payload)}')
    return client.request('PUT', path, json=payload)


def run(client, file_path, name: str, description: str, output_dir: Path,
        dry_run: bool = False, add_new: bool = False, allow_removals: bool = False) -> bool:
    """Update FAP `name` from the Excel file. Returns True on success (dry run: update is possible)."""
    name, description = name.strip(), description.strip()
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_update_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'FAP to update: {name}')
    print(f'File:          {file_path}')
    if not name:
        print('\nERROR: FAP name is required - nothing was sent.')
        return False

    try:
        excel, warnings = _fc.read_permissions(file_path)
    except _fc.FapExcelError as exc:
        print(f'\nERROR: {len(exc.problems)} problem(s) in the Excel file - nothing was sent:')
        for p in exc.problems:
            print(f'  - {p}')
        return False
    for w in warnings:
        print(f'WARNING: {w}')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    records = _fap.fetch_fap(client, name)
    matches = _fcopy.find_exact(records, name)
    if not matches:
        hint = (' Similar names: ' + ', '.join(str(r.get('name')) for r in records[:5])
                if records else '')
        print(f'\nFAILED - FAP "{name}" does not exist in {env}.{hint}')
        return False
    if len(matches) > 1:
        print(f'\nFAILED - "{name}" matches {len(matches)} FAPs in {env}; cannot choose.')
        return False
    record = matches[0]
    fap_id = record.get('id')
    print(f'Found "{record.get("name")}" (id {fap_id}): '
          f'{len(record.get("permissionTypes", []))} permission(s).')
    if not isinstance(fap_id, int) or fap_id < 0:
        print(f'\nFAILED - "{record.get("name")}" is a built-in profile (id {fap_id}) and cannot '
              'be updated. Copy it to a new FAP instead.')
        return False

    if not _fc.reference_check(client, excel, 'nothing was updated'):
        return False

    new_perms, updates, unchanged, skips = plan_update(
        record.get('permissionTypes', []), excel, add_new, allow_removals)
    print(f'Options: add new control points = {"ON" if add_new else "off"}, '
          f'allow removing actions = {"ON" if allow_removals else "off"}')

    print(f'\nControl points in the Excel file: {len({p["controlPointKey"] for p in excel})}')
    print(f'  to update: {len(updates)}   unchanged: {len(unchanged)}   skipped: {len(skips)}')
    for key, before, after in updates:
        removed = {a for a, _ in before} - {a for a, _ in after}
        print(f'  {"ADD   " if not before else "UPDATE"}  {key}'
              + (f'   ** REMOVES {", ".join(sorted(removed))} **' if removed else ''))
        if before:
            print(f'            before: {_fmt(before)}')
        print(f'            after:  {_fmt(after)}')
    for key in unchanged:
        print(f'  SAME    {key}')
    for key, reason in skips:
        print(f'  SKIP    {key}: {reason}')

    out_dir = Path(output_dir) / 'fap_update' / f'fap_update_{env}_{ts}'
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _fc._safe_name(str(record.get('name')))
    (out_dir / f'backup_{safe}.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(f'\nBackup of the current profile saved: {out_dir / f"backup_{safe}.json"}')

    if not updates:
        print('\nNOTHING TO UPDATE - no control point would change; nothing was sent.')
        return False

    payload = build_payload(record, description, new_perms)
    problems = _fc.validate_payload(payload, check_keys={key for key, _, _ in updates})
    if problems:
        print(f'\nERROR: {len(problems)} problem(s) in the payload - nothing was sent:')
        for p in problems:
            print(f'  - {p}')
        return False
    print('Payload validated: OK.')
    payload_file = out_dir / (f'dry_run_{safe}_{env}_{ts}.json' if dry_run else 'payload.json')
    payload_file.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    kept = len(new_perms) - sum(len(a) for _, _, a in updates)
    print(f'Payload saved: {payload_file}')
    print(f'The PUT sends the full list: {len(new_perms)} permission(s) '
          f'({kept} unchanged from the profile + {sum(len(a) for _, _, a in updates)} updated).')
    if dry_run:
        _fc.log_would_send(client, 'PUT', f'{_fc.FAP_ENDPOINT}/{fap_id}', payload)
        print('\nDRY RUN - the update is valid and the payload above is exactly what '
              '"Update FAP" would send. Nothing was changed (only read-only lookups were made).')
        return True

    resp = update_fap(client, fap_id, payload)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    (out_dir / 'response.json').write_text(
        json.dumps({'status': resp.status_code, 'body': body}, indent=2), encoding='utf-8')
    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code}: {resp.text}')
        print(f'\nFAILED - FAP "{name}" was NOT updated in {env} (HTTP {resp.status_code}).')
        print(f'The profile is unchanged. Response saved: {out_dir / "response.json"}')
        return False

    # Read it back: the PUT replaces everything, so confirm the profile is what we sent.
    try:
        after = _fcopy.find_exact(_fap.fetch_fap(client, name), name)
        if len(after) == 1:
            got, sent = _as_set(after[0].get('permissionTypes', [])), _as_set(new_perms)
            if got == sent:
                print(f'Verified: the profile now has exactly the {len(sent)} permission(s) sent.')
            else:
                print(f'WARNING: profile differs from what was sent: {len(sent - got)} missing, '
                      f'{len(got - sent)} extra. Compare with the backup file.')
        else:
            print('WARNING: could not read the profile back to verify it.')
    except Exception as exc:
        print(f'WARNING: could not read the profile back to verify it ({exc}).')
    print(f'\nCOMPLETED - FAP "{name}" updated in {env} (HTTP {resp.status_code}).')
    print(f'Response saved: {out_dir / "response.json"}')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Update a UKG Function Access Profile from an Excel file')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--name', required=True, help='Name of the FAP to update')
    parser.add_argument('--file', required=True, help='Excel file (same layout as the Create tab)')
    parser.add_argument('--description', default='',
                        help='New description (default: keep the existing one)')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; results go to <dir>/fap_update/')
    parser.add_argument('--add-new', action='store_true',
                        help='Also add control points that are not in the profile (default: skip them)')
    parser.add_argument('--allow-removals', action='store_true',
                        help='Remove actions the Excel row leaves out (default: skip that control point)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run every check and save the payload without updating anything')
    args = parser.parse_args()
    try:
        ok = run(ukg_env.client_from_args(args), args.file, args.name, args.description,
                 Path(args.output_dir), dry_run=args.dry_run,
                 add_new=args.add_new, allow_removals=args.allow_removals)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
