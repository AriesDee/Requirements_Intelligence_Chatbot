"""
fap_delete_tool.py — Delete one or more UKG Function Access Profiles (FAPs) by name

  GET    https://<env url>/api/v1/commons/function_access_profiles?name=<FAP>
  DELETE https://<env url>/api/v1/commons/function_access_profiles/<id>      (204 = deleted)

Deleting cannot be undone, so every run goes through the same steps:
  1. Each name is looked up (UKG's name lookup is an exact match).
     A name is skipped - the others carry on - when it is not found, matches more than one FAP,
     or is a built-in profile (negative id, e.g. Super Access).
  2. The profiles that will be deleted are listed (id, name, description, permission count).
  3. The user must confirm by typing DELETE (DELETE PRD in the PRD environment). Preview / dry
     run stops here and deletes nothing.
  4. Each profile's full record is saved to a backup file, then deleted. One failure does not
     stop the rest. Afterwards each profile is looked up again to confirm it is gone.

UKG refuses to delete a profile that is assigned to users or is Gold Data (HTTP 400,
WCO-127807 "This Function Access Profile is already in use or Gold Data, so could not be
deleted."). UKG's message is shown as is, with a hint to remove the assignments and try again.

Output: output/fap_delete/fap_delete_<env>_<timestamp>/backup/<FAP>.json and results.json

Usage:
  python fap_delete_tool.py --env NPR1 --name "ADOMI01 Test FAP" --name "ADOMI01 Test FAP 2" --dry-run
  python fap_delete_tool.py --env NPR1 --name "ADOMI01 Test FAP" --confirm DELETE
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

IN_USE_HINT = ('Hint: the profile is probably still assigned to users (or is Gold Data). '
               'Remove its assignments, then try again.')


def confirmation_word(env: str) -> str:
    """What the user must type to confirm: DELETE, or DELETE PRD in the PRD environment."""
    return 'DELETE PRD' if env == 'PRD' else 'DELETE'


def parse_names(text: str) -> list[str]:
    """One name per line; blank lines and repeats (any capitalisation) are dropped."""
    seen, names = set(), []
    for line in text.splitlines():
        name = line.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def delete_fap(client, fap_id):
    """DELETE by id. Returns the requests.Response (caller decides how to report it)."""
    path = f'{_fc.FAP_ENDPOINT}/{fap_id}'
    _uat.logger.info(f'DELETE https://{client.base_url}{path}')
    return client.request('DELETE', path)


def _error_text(resp) -> str:
    """UKG's error as 'WCO-xxxxx: message' (falls back to the raw body)."""
    try:
        body = resp.json()
        if isinstance(body, dict) and (body.get('message') or body.get('errorCode')):
            return f'{body.get("errorCode", "")}: {body.get("message", "")}'.strip(': ')
    except ValueError:
        pass
    return (resp.text or '').strip() or f'HTTP {resp.status_code}'


def _is_in_use(resp) -> bool:
    text = (resp.text or '').lower()
    return 'wco-127807' in text or 'already in use' in text or 'gold data' in text


def resolve(client, names: list[str]):
    """Look each name up. Returns (targets, skipped): targets are FAP records to delete,
    skipped is [(name, reason)]."""
    targets, skipped = [], []
    for name in names:
        matches = _fcopy.find_exact(_fap.fetch_fap(client, name), name)
        if not matches:
            skipped.append((name, f'does not exist in {client.env}'))
        elif len(matches) > 1:
            skipped.append((name, f'matches {len(matches)} FAPs - cannot choose'))
        elif not isinstance(matches[0].get('id'), int) or matches[0]['id'] < 0:
            skipped.append((name, f'is a built-in profile (id {matches[0].get("id")}) - cannot be deleted'))
        else:
            targets.append(matches[0])
    return targets, skipped


def run(client, names: list[str], output_dir: Path, dry_run: bool = False, confirm=None) -> bool:
    """Delete the FAPs called `names`.

    dry_run: look up and list, delete nothing. confirm: callable(targets, word) -> bool that
    asks the user to type `word`; a real run without it deletes nothing. Returns True when
    nothing failed and at least one FAP was deleted (dry run: at least one could be)."""
    names = parse_names('\n'.join(names))
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_delete_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    if not names:
        print('\nERROR: enter at least one FAP name - nothing was deleted.')
        return False
    print(f'FAP(s) to delete: {len(names)}')

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    targets, skipped = resolve(client, names)
    for name, reason in skipped:
        print(f'  SKIP    "{name}" {reason}')
    if not targets:
        print('\nNOTHING TO DELETE - no listed FAP can be deleted.')
        return False
    print(f'\nWill delete {len(targets)} FAP(s) in {env}:')
    for r in targets:
        print(f'  id {r["id"]:<6} {r.get("name")}  -  {r.get("description") or ""}  '
              f'({len(r.get("permissionTypes", []))} permission(s))')

    if dry_run:
        for r in targets:
            _fc.log_would_send(client, 'DELETE', f'{_fc.FAP_ENDPOINT}/{r["id"]}')
        print('\nDRY RUN - nothing was deleted. A DELETE has no payload; the requests above are '
              'what "Delete FAP(s)" would send.')
        return True
    word = confirmation_word(env)
    if confirm is None or not confirm(targets, word):
        print(f'\nCANCELLED - "{word}" was not confirmed; nothing was deleted.')
        return False

    out_dir = Path(output_dir) / 'fap_delete' / f'fap_delete_{env}_{ts}'
    (out_dir / 'backup').mkdir(parents=True, exist_ok=True)
    results = []
    print('')
    for r in targets:
        name, fap_id = r.get('name'), r['id']
        backup = out_dir / 'backup' / f'{_fc._safe_name(str(name))}_{fap_id}.json'
        backup.write_text(json.dumps(r, indent=2), encoding='utf-8')
        try:
            resp = delete_fap(client, fap_id)
        except Exception as exc:
            results.append({'name': name, 'id': fap_id, 'result': 'failed', 'detail': str(exc)})
            print(f'  FAILED  "{name}" (id {fap_id}): {exc}')
            continue
        if resp.ok:
            gone = not _fcopy.find_exact(_fap.fetch_fap(client, str(name)), str(name))
            results.append({'name': name, 'id': fap_id, 'result': 'deleted',
                            'status': resp.status_code, 'verified_gone': gone})
            print(f'  DELETED "{name}" (id {fap_id}), HTTP {resp.status_code}'
                  + ('' if gone else '  - WARNING: it still shows up when looked up again'))
        else:
            detail = _error_text(resp)
            _uat.logger.error(f'HTTP {resp.status_code} deleting {name}: {resp.text}')
            results.append({'name': name, 'id': fap_id, 'result': 'failed',
                            'status': resp.status_code, 'detail': detail})
            print(f'  FAILED  "{name}" (id {fap_id}), HTTP {resp.status_code}: {detail}')
            if _is_in_use(resp):
                print(f'          {IN_USE_HINT}')

    (out_dir / 'results.json').write_text(json.dumps(
        {'environment': env, 'skipped': [{'name': n, 'reason': why} for n, why in skipped],
         'results': results}, indent=2), encoding='utf-8')
    deleted = sum(1 for x in results if x['result'] == 'deleted')
    failed = len(results) - deleted
    print(f'\nSummary: {deleted} deleted, {failed} failed, {len(skipped)} skipped.')
    print(f'Backups and results saved: {out_dir}')
    return failed == 0 and deleted > 0


def main():
    parser = argparse.ArgumentParser(description='Delete UKG Function Access Profiles by name')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--name', action='append', required=True,
                        help='FAP name to delete (repeat --name for several)')
    parser.add_argument('--confirm', default='',
                        help='Type DELETE (DELETE PRD in PRD) to actually delete; without it '
                             'the run is a preview')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; results go to <dir>/fap_delete/')
    parser.add_argument('--dry-run', action='store_true', help='List what would be deleted only')
    args = parser.parse_args()
    try:
        client = ukg_env.client_from_args(args)
        word = confirmation_word(client.env)
        dry = args.dry_run or args.confirm != word
        if not args.dry_run and args.confirm != word:
            print(f'No valid --confirm "{word}" given - running as a preview, nothing will be deleted.')
        ok = run(client, args.name, Path(args.output_dir), dry_run=dry,
                 confirm=lambda targets, w: True)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
