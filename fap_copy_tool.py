"""
fap_copy_tool.py — Copy a UKG Function Access Profile (FAP), in one environment or to another

  GET  https://<source env>/api/v1/commons/function_access_profiles?name=<source FAP>
  POST https://<destination env>/api/v1/commons/function_access_profiles

The new FAP gets the source's permissionTypes exactly as they are, plus the name and
description you provide (description defaults to the name when left blank). The source is only
read, so built-in profiles (negative ids, e.g. Super Access) can be copied too.

Checks before anything is created (nothing is sent if any fails):
  - source name and new name are provided
  - same-environment copy: the new name differs from the source name
  - the source FAP exists (exact name match) and matches exactly one profile
  - the new name does not already exist in the destination environment

Cross-environment copies fail at the POST if a control point does not exist in the destination;
the API's message is shown and the payload is kept in the output folder.

Each run writes output/fap_copy/fap_copy_<src>_to_<dst>_<timestamp>/ with source.json (the source
record as returned), payload.json (what was sent) and, after a real run, response.json.
A preview (dry run) saves the payload as dry_run_<new name>_<env>_<ts>.json instead.

Connection comes from ukg_env, same as every other UKG tool. The destination uses the same grant
type and credentials mode; its profile defaults to the last one used for that environment.

Usage:
  python fap_copy_tool.py --env NPR1 --source "WFM Corporate Team" --name "WFM Corporate Team 2" \\
         --description "Copy for testing" --dry-run
  python fap_copy_tool.py --env NPR1 --dest-env UAT --source "WFM Corporate Team" \\
         --name "WFM Corporate Team" --description "Promoted from NPR1" --no-verify-ssl
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

_PERMISSION_FIELDS = ('actionName', 'scopeName', 'controlPointKey')


def validate_inputs(source_name: str, new_name: str, same_env: bool) -> list[str]:
    """Problems that block the copy (empty list = OK). Pure, so the UI can call it before running."""
    problems = []
    if not source_name.strip():
        problems.append('Source FAP name is required.')
    if not new_name.strip():
        problems.append('New FAP name is required.')
    elif same_env and new_name.strip().lower() == source_name.strip().lower():
        problems.append('New name must differ from the source name when copying within '
                        'the same environment.')
    return problems


def find_exact(records: list[dict], name: str) -> list[dict]:
    """Records whose name equals name (case-insensitive). UKG's name lookup is an exact match
    (an unknown name gives WCO-127822 "does not exist"), so this is a safety net: anything else
    returned must never be treated as the profile being copied or as a name collision."""
    wanted = name.strip().lower()
    return [r for r in records if str(r.get('name', '')).strip().lower() == wanted]


def build_payload(source: dict, new_name: str, description: str) -> dict:
    permissions = [{k: p[k] for k in _PERMISSION_FIELDS if k in p}
                   for p in source.get('permissionTypes', [])]
    return _fc.build_payload(new_name, description, permissions)


def run(source_client, dest_client, source_name: str, new_name: str, description: str,
        output_dir: Path, dry_run: bool = False) -> bool:
    """Copy source_name (read via source_client) to new_name (created via dest_client).

    Same environment: pass the same client twice. dry_run still reads from the API (source and
    name-collision checks) but creates nothing. Returns True on success."""
    source_name, new_name = source_name.strip(), new_name.strip()
    description = description.strip() or new_name
    src_env, dst_env = source_client.env, dest_client.env
    same_env = src_env == dst_env
    if same_env:
        dest_client = source_client

    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_copy_{src_env}_to_{dst_env}_{ts}.log')

    print('Source')
    print('\n'.join('  ' + ln for ln in ukg_env.describe(source_client, source_client.grant_type)))
    if not same_env:
        print('Destination')
        print('\n'.join('  ' + ln for ln in ukg_env.describe(dest_client, dest_client.grant_type)))
    print(f'Copy "{source_name}"  ->  "{new_name}"  '
          f'({"within " + src_env if same_env else src_env + " to " + dst_env})')
    print(f'Description: {description}')

    problems = validate_inputs(source_name, new_name, same_env)
    if problems:
        print('\nERROR: nothing was copied:')
        for p in problems:
            print(f'  - {p}')
        return False

    for c in ((source_client,) if same_env else (source_client, dest_client)):
        c.generate_access_token()
        _uat.logger.info(f'Authentication successful ({c.env})')
        if c.profile_name:
            ukg_env.remember_profile(c.env, c.grant_type, c.profile_name)

    records = _fap.fetch_fap(source_client, source_name)
    matches = find_exact(records, source_name)
    if not matches:
        hint = (' Similar names: ' + ', '.join(str(r.get('name')) for r in records[:5])
                if records else '')
        print(f'\nFAILED - source FAP "{source_name}" does not exist in {src_env}.{hint}')
        return False
    if len(matches) > 1:
        print(f'\nFAILED - "{source_name}" matches {len(matches)} FAPs in {src_env}; cannot choose.')
        return False
    source = matches[0]

    if find_exact(_fap.fetch_fap(dest_client, new_name), new_name):
        print(f'\nFAILED - a FAP named "{new_name}" already exists in {dst_env}. '
              'Choose a different name; nothing was created.')
        return False

    payload = build_payload(source, new_name, description)
    out_dir = Path(output_dir) / 'fap_copy' / f'fap_copy_{src_env}_to_{dst_env}_{ts}'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'source.json').write_text(json.dumps(source, indent=2), encoding='utf-8')
    payload_file = out_dir / (f'dry_run_{_fc._safe_name(new_name)}_{dst_env}_{ts}.json' if dry_run
                              else 'payload.json')
    payload_file.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    control_points = len({p['controlPointKey'] for p in payload['permissionTypes']})
    print(f'\nSource found (id {source.get("id")}): '
          f'{len(payload["permissionTypes"])} permission(s) across {control_points} control point(s).')
    print(f'"{new_name}" does not exist in {dst_env} yet.')
    print(f'Saved: {out_dir}')
    print(f'Payload: {payload_file.name}')
    if dry_run:
        _fc.log_would_send(dest_client, 'POST', _fc.FAP_ENDPOINT, payload)
        print('\nDRY RUN - read-only checks passed; nothing was created.')
        return True

    resp = _fc.create_fap(dest_client, payload)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    (out_dir / 'response.json').write_text(
        json.dumps({'status': resp.status_code, 'body': body}, indent=2), encoding='utf-8')
    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code}: {resp.text}')
        print(f'\nFAILED - FAP "{new_name}" was NOT created in {dst_env} (HTTP {resp.status_code}).')
        return False
    print(f'\nCOMPLETED - FAP "{new_name}" created in {dst_env} (HTTP {resp.status_code}).')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Copy a UKG Function Access Profile (same environment or to another)')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--source', required=True, help='Name of the FAP to copy')
    parser.add_argument('--name', required=True, help='Name of the new FAP')
    parser.add_argument('--description', default='', help='Description (default: same as --name)')
    parser.add_argument('--dest-env', choices=ukg_env.ENVIRONMENTS, default=None,
                        help='Destination environment (default: same as --env)')
    parser.add_argument('--dest-profile', default=None,
                        help='Credential profile for --dest-env (default: its last-used profile)')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; results go to <dir>/fap_copy/')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run the read-only checks without creating anything')
    args = parser.parse_args()

    try:
        source_client = ukg_env.client_from_args(args)
        if args.dest_env and args.dest_env != args.env:
            dest_client = ukg_env.build_client(args.dest_env, args.grant_type, args.cred_mode,
                                               args.dest_profile, ssl_verify=not args.no_verify_ssl)
        else:
            dest_client = source_client
        ok = run(source_client, dest_client, args.source, args.name, args.description,
                 Path(args.output_dir), dry_run=args.dry_run)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
