"""
fap_tool.py — UKG Function Access Profile (FAP) export / comparison tool

Calls  GET https://<env url>/api/v1/commons/function_access_profiles?name=<FAP name>
for each FAP requested and writes one Excel workbook so the profiles can be
compared side by side.

Environment (NPR1 / UAT / PRD) and credentials are chosen at run time — nothing
environment-specific lives in input/. See ukg_env.py: the URL, organization and token
host follow the environment, and credentials come from the saved profiles
(~/.ukg_hwfd/profiles.json + Windows Credential Manager) or Azure Key Vault
(~/.ukg_hwfd/akv_config.json), the same ones the stonebranch UI uses.

Each run writes a folder  output/fap_tool/fap_<env>_<timestamp>/  containing:
  fap_comparison_<env>_<ts>.xlsx   Comparison (one row per setting / control point, one column
                                   per FAP, differing rows highlighted), Differences, and, when
                                   requested, a Pairs index plus one tab per pair.
  fap_actions_<env>_<ts>.xlsx      One tab each for ADD, DELETE, EDIT, VIEW, ALLOWED
                                   (control point x FAP, X [scope] where granted).
  fap_definitions_<env>_<ts>.xlsx  One tab per FAP (control point x action, X [scope] where granted).
  json/<FAP name>.json             Each FAP's record exactly as the API returned it.

Pair tabs (in the comparison file):
  --pair "FAP A" "FAP B"   compare two FAPs (repeatable)
  --all-pairs              every combination of the requested FAPs
  --baseline "FAP A"       the baseline against each of the other requested FAPs

Same FAP in two environments:
  python fap_tool.py --env NPR1 --vs-env UAT --name "WFM Corporate Team"
  writes output/fap_tool/fap_NPR1_vs_UAT_<ts>/ with a Summary tab and one tab per FAP
  (columns NPR1 / UAT). The FAP id is ignored when counting differences; it always differs.

FAP names (first one found wins):
  --name "ACI CDX Access" --name "Other FAP"   (repeatable)
  --names-file <path>                          (one name per line, # for comments)
  input/fap_tool/fap_names.txt

Usage:
  python fap_tool.py --env UAT --name "ACI CDX Access" --name "ACI CDX Admin"
  python fap_tool.py --env UAT --names-file input/fap_tool/fap_names.txt --baseline "Super Access"
  python fap_tool.py --env PRD --grant-type password --profile prd_password_prdapiusr --name "..."
  python fap_tool.py --env UAT --list-profiles
  python fap_tool.py --env UAT --name "ACI CDX Access" --dry-run
"""

import sys
import argparse
import itertools
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import ukg_api_tool as _uat          # folders + logging only; auth comes from ukg_env
import ukg_env

FAP_ENDPOINT = '/api/v1/commons/function_access_profiles'
FAP_INPUT_DIR = _uat.INPUT_DIR / 'fap_tool'            # all FAP tool inputs live here
DEFAULT_NAMES_FILE = FAP_INPUT_DIR / 'fap_names.txt'
_LEGACY_NAMES_FILE = _uat.INPUT_DIR / 'fap_names.txt'  # list saved before the fap_tool/ folder

# Keys used to label list items so the same item lines up across FAPs
# regardless of the order the API returns them in.
_ID_KEYS = ('controlPointKey', 'name', 'key', 'qualifier', 'code', 'functionName', 'id')

ABSENT = ''                                   # FAP lacks this setting: leave the cell blank
_DIFF_FILL   = PatternFill('solid', fgColor='FFF2CC')
_HEADER_FILL = PatternFill('solid', fgColor='1F4E78')
_HEADER_FONT = Font(bold=True, color='FFFFFF')


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _records(body) -> list[dict]:
    """Normalise the response to a list of FAP dicts."""
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in ('items', 'data', 'results', 'functionAccessProfiles'):
            if isinstance(body.get(key), list):
                return [r for r in body[key] if isinstance(r, dict)]
        return [body]
    return []


def fetch_fap(client, name: str) -> list[dict]:
    # quote() gives %20 for spaces, matching the documented request format
    path = f'{FAP_ENDPOINT}?name={quote(name, safe="")}'
    _uat.logger.info(f'GET https://{client.base_url}{path}')
    resp = client.request('GET', path)
    if not resp.ok and ('WCO-127822' in resp.text or
                        (resp.status_code == 404 and 'does not exist' in resp.text)):
        _uat.logger.info(f'"{name}" does not exist in {client.env}')   # UKG says 404, not an empty list
        return []
    if not resp.ok:
        _uat.logger.error(f'HTTP {resp.status_code} for "{name}": {resp.text}')
        resp.raise_for_status()
    return _records(resp.json())


# ---------------------------------------------------------------------------
# Flatten / compare
# ---------------------------------------------------------------------------

def _scalar(v) -> str:
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return str(v)


def flatten(obj, prefix: str = '') -> dict[str, str]:
    """Flatten nested JSON to {path: value}; list items are keyed by an id-like field."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f'{prefix}.{k}' if prefix else str(k)))
    elif isinstance(obj, list):
        if all(not isinstance(i, (dict, list)) for i in obj):
            out[prefix] = '; '.join(sorted(_scalar(i) for i in obj))
        else:
            seen: dict[str, int] = {}
            for idx, item in enumerate(obj):
                label = str(idx)
                if isinstance(item, dict):
                    label = next((_scalar(item[k]) for k in _ID_KEYS
                                  if item.get(k) not in (None, '')), label)
                seen[label] = seen.get(label, 0) + 1
                if seen[label] > 1:                       # duplicate label — keep rows distinct
                    label = f'{label}#{seen[label]}'
                out.update(flatten(item, f'{prefix}[{label}]'))
    else:
        out[prefix] = _scalar(obj)
    return out


ACTIONS = ('ADD', 'DELETE', 'EDIT', 'VIEW', 'ALLOWED')
PERM_FIELD = 'permissionTypes'


def permission_map(rec: dict) -> dict[str, dict[str, str]]:
    """{controlPointKey: {actionName: scopeName}} — a control point can hold several actions."""
    out: dict[str, dict[str, str]] = {}
    for item in rec.get(PERM_FIELD) or []:
        if isinstance(item, dict) and item.get('controlPointKey'):
            out.setdefault(str(item['controlPointKey']), {})[_scalar(item.get('actionName'))] =                 _scalar(item.get('scopeName'))
    return out


def _mark(scope: str) -> str:
    """The action is granted ('X'); the scopeName from the JSON follows in brackets."""
    return f'X [{scope}]' if scope else 'X'


def _perm_cell(acts: dict[str, str], order: list[str]) -> str:
    """'ADD [ALL], VIEW [ALL_BUT_SELF]' — each granted action with its scope as in the JSON."""
    return ', '.join(f'{a} [{acts[a]}]' if acts[a] else a for a in order if a in acts)


def _action_order(perms: dict[str, dict[str, dict[str, str]]]) -> list[str]:
    found = {a for m in perms.values() for acts in m.values() for a in acts}
    return [*ACTIONS, *sorted(found - set(ACTIONS))]


# Identity fields: expected to differ between FAPs, so they never count as a difference
IDENTITY_FIELDS = ('id', 'name', 'description')


def build_matrix(profiles: dict[str, dict], ignore=IDENTITY_FIELDS) -> tuple[list[str], list[list[str]]]:
    """Return (column headers, rows) where each row is [setting, value per FAP..., differs].

    Control points get one row per controlPointKey, shared by all FAPs. Rows named in `ignore`
    are still listed but are never flagged as differing."""
    names = list(profiles)
    perms = {n: permission_map(rec) for n, rec in profiles.items()}
    order = _action_order(perms)
    flat = {}
    for n, rec in profiles.items():
        f = flatten({k: v for k, v in rec.items() if k != PERM_FIELD})
        f.update({f'{PERM_FIELD}[{cp}]': _perm_cell(acts, order) for cp, acts in perms[n].items()})
        flat[n] = f
    paths = list(dict.fromkeys(p for f in flat.values() for p in f))
    rows = []
    for p in paths:
        vals = [flat[n].get(p, ABSENT) for n in names]
        rows.append([p, *vals, 'Yes' if len(set(vals)) > 1 and p not in ignore else 'No'])
    return ['Setting', *names, 'Differs'], rows


def build_action_sheets(profiles: dict[str, dict]) -> dict[str, tuple[list[str], list[list[str]]]]:
    """Per action: control point x FAP, each cell 'X [scope]' (blank = not in the JSON)."""
    names = list(profiles)
    perms = {n: permission_map(rec) for n, rec in profiles.items()}
    cps = list(dict.fromkeys(cp for m in perms.values() for cp in m))
    sheets = {}
    for action in _action_order(perms):
        rows = []
        for cp in cps:
            vals = [_mark(perms[n][cp][action]) if action in perms[n].get(cp, {}) else ''
                    for n in names]
            if any(vals):
                rows.append([cp, *vals, 'Yes' if len(set(vals)) > 1 else 'No'])
        if rows:
            sheets[action] = (['Control Point', *names, 'Differs'], rows)
    return sheets


def build_fap_sheet(rec: dict) -> tuple[list[str], list[list[str]]]:
    """One FAP: control point x action. 'X [scope]' = the JSON lists that action (with its
    scopeName); blank = the JSON doesn't list it."""
    perms = permission_map(rec)
    order = _action_order({'x': perms})
    return (['Control Point', *order],
            [[cp, *[_mark(acts[a]) if a in acts else '' for a in order]] for cp, acts in perms.items()])


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

def _write_sheet(ws, headers: list[str], rows: list[list[str]], highlight: bool,
                 diff_col: bool = True, show_diff: bool = True):
    """show_diff=False still highlights differing rows but leaves the Differs column out."""
    flags = [r[-1] == 'Yes' for r in rows]
    wide = diff_col                                   # settings-style sheet: wide value columns
    if not show_diff:
        headers, rows, diff_col = headers[:-1], [r[:-1] for r in rows], False
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = _HEADER_FILL, _HEADER_FONT
        c.alignment = Alignment(vertical='center', wrap_text=True)
    for row, differs in zip(rows, flags):
        ws.append(row)
        if highlight and differs:
            for c in ws[ws.max_row]:
                c.fill = _DIFF_FILL
    ws.freeze_panes = 'B2'
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions
    ws.column_dimensions['A'].width = 60
    for i in range(2, len(headers) + 1):
        last = diff_col and i == len(headers)
        ws.column_dimensions[get_column_letter(i)].width = 10 if last else (30 if wide else 16)


def _sheet_title(wb, label: str) -> str:
    base = re.sub(r'[\/*?:\[\]]+', '_', label).strip("' ")[:31] or 'FAP'
    title, n = base, 2
    while title in wb.sheetnames:
        suffix = f' ({n})'
        title, n = base[:31 - len(suffix)] + suffix, n + 1
    return title


def resolve_pairs(profiles: dict[str, dict], pairs=(), all_pairs=False, baseline=None,
                  aliases=None) -> tuple[list[tuple[str, str]], list[str]]:
    """Turn the pair options into [(label A, label B)] plus warnings for names that didn't resolve.

    aliases maps a requested name to the FAP label it produced."""
    lookup = {k.lower(): k for k in profiles}
    lookup.update({k.lower(): v for k, v in (aliases or {}).items() if v in profiles})
    warnings: list[str] = []

    def find(name):
        label = lookup.get(str(name).strip().lower())
        if label is None:
            warnings.append(f'pair skipped: "{name}" is not one of the FAPs that were found')
        return label

    wanted: list[tuple[str, str]] = []
    for a, b in pairs:
        la, lb = find(a), find(b)
        if la and lb:
            wanted.append((la, lb))
    if all_pairs:
        wanted += itertools.combinations(profiles, 2)
    if baseline:
        base = find(baseline)
        if base:
            wanted += [(base, other) for other in profiles if other != base]

    out, seen = [], set()
    for a, b in wanted:
        if a != b and frozenset((a, b)) not in seen:
            seen.add(frozenset((a, b)))
            out.append((a, b))
    return out, warnings


def write_comparison(profiles: dict[str, dict], out_path: Path, pairs=()) -> int:
    """Comparison + Differences, then (if pairs) a Pairs index and one tab per pair."""
    headers, rows = build_matrix(profiles)
    diffs = [r for r in rows if r[-1] == 'Yes']

    wb = Workbook()
    ws = wb.active
    ws.title = 'Comparison'
    _write_sheet(ws, headers, rows, highlight=True, show_diff=False)
    _write_sheet(wb.create_sheet('Differences'), headers, diffs, highlight=False, show_diff=False)

    if pairs:
        idx = wb.create_sheet('Pairs')
        index, built = [], []
        for n, (a, b) in enumerate(pairs, 1):
            h, r = build_matrix({a: profiles[a], b: profiles[b]})
            full = f'{a} vs {b}'
            ws_pair = wb.create_sheet(_sheet_title(wb, full if len(full) <= 31 else f'Pair {n}'))
            built.append((ws_pair, h, r))
            index.append([ws_pair.title, a, b, sum(1 for x in r if x[-1] == 'Yes')])
        _write_sheet(idx, ['Tab', 'FAP A', 'FAP B', 'Differing settings'], index,
                     highlight=False, diff_col=False)
        idx.column_dimensions['A'].width = 34
        for ws_pair, h, r in built:
            _write_sheet(ws_pair, h, r, highlight=True)
    wb.save(out_path)
    return len(diffs)


def write_actions(profiles: dict[str, dict], out_path: Path):
    wb = Workbook()
    wb.remove(wb.active)
    sheets = build_action_sheets(profiles)
    for action, (h, r) in sheets.items():
        _write_sheet(wb.create_sheet(_sheet_title(wb, action)), h, r, highlight=True)
    if not sheets:                                    # a workbook needs at least one sheet
        wb.create_sheet('No actions')
    wb.save(out_path)


def write_definitions(profiles: dict[str, dict], out_path: Path):
    wb = Workbook()
    wb.remove(wb.active)
    for label, rec in profiles.items():
        h, r = build_fap_sheet(rec)
        _write_sheet(wb.create_sheet(_sheet_title(wb, label)), h, r, highlight=False, diff_col=False)
    wb.save(out_path)


# ---------------------------------------------------------------------------
# Same FAP, different environments
# ---------------------------------------------------------------------------

ENV_NAMES_FILE = FAP_INPUT_DIR / 'fap_env_names.txt'
_ENV_SPECIFIC = {'id'}                      # differs between environments by design


def build_env_matrix(rec_a: dict, rec_b: dict, env_a: str, env_b: str):
    """One FAP in two environments: same layout as build_matrix, columns named by environment."""
    # the same FAP: only the id is expected to differ (name and description should match)
    return build_matrix({env_a: rec_a, env_b: rec_b}, ignore=_ENV_SPECIFIC)


def write_env_comparison(results: dict[str, tuple], env_a: str, env_b: str,
                         out_path: Path) -> list[list]:
    """results: {FAP name: (record in env_a or None, record in env_b or None)}.

    A Summary tab, then one tab per FAP found in both environments. Returns the summary rows."""
    wb = Workbook()
    summary = wb.active
    summary.title = 'Summary'
    summary_rows, tabs = [], []
    for name, (rec_a, rec_b) in results.items():
        if rec_a is not None and rec_b is not None:
            h, r = build_env_matrix(rec_a, rec_b, env_a, env_b)
            ws = wb.create_sheet(_sheet_title(wb, name))
            tabs.append((ws, h, r))
            summary_rows.append([name, 'Yes', 'Yes', sum(1 for x in r if x[-1] == 'Yes')])
        else:
            summary_rows.append([name, 'Yes' if rec_a is not None else 'No',
                                 'Yes' if rec_b is not None else 'No', 'not compared'])
    _write_sheet(summary, ['FAP', f'In {env_a}', f'In {env_b}', 'Differing settings'],
                 summary_rows, highlight=False, diff_col=False)
    for ws, h, r in tabs:
        _write_sheet(ws, h, r, highlight=True)
    wb.save(out_path)
    return summary_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_names(cli_names: list[str] | None, names_file: str | None) -> list[str]:
    if cli_names:
        return cli_names
    path = Path(names_file) if names_file else DEFAULT_NAMES_FILE
    if not path.exists() and not names_file and _LEGACY_NAMES_FILE.exists():
        path = _LEGACY_NAMES_FILE
    if not path.exists():
        return []
    lines = (ln.strip() for ln in path.read_text(encoding='utf-8').splitlines())
    return [ln for ln in lines if ln and not ln.startswith('#')]


def run(names: list[str], client, output_dir: Path, dry_run: bool = False,
        pairs=(), all_pairs: bool = False, baseline: str | None = None):
    """client: a connected-to-be UKGClient from ukg_env.build_client / client_from_args.

    Results go to <output_dir>/fap_tool/fap_<env>_<ts>/."""
    env = client.env
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_tool_{env}_{ts}.log')

    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'FAPs ({len(names)}):')
    for n in names:
        print(f'  - {n}')
    if baseline:
        print(f'Baseline: {baseline}  (compared with each of the other FAPs)')
    if all_pairs:
        print('Pairs: every combination')
    for a, b in pairs:
        print(f'Pair: {a}  vs  {b}')
    if dry_run:
        print('\nDRY RUN — no API calls made.')
        return

    client.generate_access_token()
    _uat.logger.info('Authentication successful')
    if client.profile_name:
        ukg_env.remember_profile(env, client.grant_type, client.profile_name)

    profiles: dict[str, dict] = {}
    aliases: dict[str, str] = {}                      # requested name -> column label it produced
    for name in names:
        records = fetch_fap(client, name)
        if not records:
            _uat.logger.warning(f'No FAP returned for "{name}"')
            print(f'  WARNING: no FAP found for "{name}"')
            continue
        # name= may match more than one FAP; prefer exact matches when present
        exact = [r for r in records if str(r.get('name', '')).lower() == name.lower()]
        for rec in exact or records:
            label = str(rec.get('name') or name)
            if label in profiles:                         # keep columns unique
                label = f'{label} ({rec.get("id", len(profiles))})'
            profiles[label] = rec
            aliases.setdefault(name, label)

    if not profiles:
        raise RuntimeError(f'None of the requested FAPs were found in {env} — nothing to write.')

    pair_list, warns = resolve_pairs(profiles, pairs, all_pairs, baseline, aliases)
    for w in warns:
        _uat.logger.warning(w)
        print(f'  WARNING: {w}')

    run_dir = Path(output_dir) / 'fap_tool' / f'fap_{env}_{ts}'
    json_dir = run_dir / 'json'                       # one reusable JSON file per FAP
    json_dir.mkdir(parents=True, exist_ok=True)
    for label, rec in profiles.items():
        safe = re.sub(r'[<>:"/\\|?*]+', '_', label).strip(' .') or 'fap'
        (json_dir / f'{safe}.json').write_text(json.dumps(rec, indent=2), encoding='utf-8')

    cmp_path = run_dir / f'fap_comparison_{env}_{ts}.xlsx'
    act_path = run_dir / f'fap_actions_{env}_{ts}.xlsx'
    def_path = run_dir / f'fap_definitions_{env}_{ts}.xlsx'
    n_diff = write_comparison(profiles, cmp_path, pair_list)
    write_actions(profiles, act_path)
    write_definitions(profiles, def_path)

    _uat.logger.info(f'Wrote {run_dir} ({len(profiles)} FAPs, {n_diff} differing settings, '
                     f'{len(pair_list)} pair tabs)')
    print(f'\nFAPs compared:       {len(profiles)}')
    print(f'Differing settings:  {n_diff}')
    if pair_list:
        print(f'Pair tabs:           {len(pair_list)}')
    print(f'Folder:              {run_dir}')
    print(f'  Comparison:        {cmp_path.name}')
    print(f'  Actions:           {act_path.name}')
    print(f'  Definitions:       {def_path.name}')
    print(f'  JSON per FAP:      {json_dir.name}/')


def _pick_record(records: list[dict], name: str):
    """The FAP matching name (exact match preferred), or None."""
    exact = [r for r in records if str(r.get('name', '')).lower() == name.lower()]
    found = exact or records
    if len(found) > 1:
        _uat.logger.warning(f'"{name}" matched {len(found)} FAPs; using the first')
    return found[0] if found else None


def run_envs(names: list[str], client_a, client_b, output_dir: Path, dry_run: bool = False):
    """Compare the same FAPs in two environments (client_a vs client_b).

    Results go to <output_dir>/fap_tool/fap_<A>_vs_<B>_<ts>/."""
    env_a, env_b = client_a.env, client_b.env
    if env_a == env_b:
        raise ValueError('Choose two different environments to compare.')
    _uat.LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _uat.setup_logging(_uat.LOG_DIR / f'fap_tool_{env_a}_vs_{env_b}_{ts}.log')

    for tag, c in (('A', client_a), ('B', client_b)):
        print(f'Side {tag}')
        print('\n'.join('  ' + ln for ln in ukg_env.describe(c, c.grant_type)))
    print(f'FAPs ({len(names)}):')
    for n in names:
        print(f'  - {n}')
    if dry_run:
        print('\nDRY RUN — no API calls made.')
        return

    for c in (client_a, client_b):
        c.generate_access_token()
        _uat.logger.info(f'Authentication successful ({c.env})')
        if c.profile_name:
            ukg_env.remember_profile(c.env, c.grant_type, c.profile_name)

    results: dict[str, tuple] = {}
    for name in names:
        rec_a = _pick_record(fetch_fap(client_a, name), name)
        rec_b = _pick_record(fetch_fap(client_b, name), name)
        if rec_a is None and rec_b is None:
            msg = f'"{name}" does not exist in {env_a} or {env_b} - skipped'
        elif rec_a is None or rec_b is None:
            has, lacks = (env_a, env_b) if rec_a is not None else (env_b, env_a)
            msg = f'"{name}" exists in {has} but not in {lacks} - skipped'
        else:
            msg = None
        if msg:
            _uat.logger.warning(msg)
            print(f'  WARNING: {msg}')
        label = str((rec_a or rec_b or {}).get('name') or name)
        results[label] = (rec_a, rec_b)               # missing ones still appear on the Summary tab
    if not any(a is not None and b is not None for a, b in results.values()):
        print('  WARNING: no FAP exists in both environments - only the Summary tab will be written.')

    run_dir = Path(output_dir) / 'fap_tool' / f'fap_{env_a}_vs_{env_b}_{ts}'
    for env, idx in ((env_a, 0), (env_b, 1)):
        env_dir = run_dir / 'json' / env
        env_dir.mkdir(parents=True, exist_ok=True)
        for label, recs in results.items():
            if recs[idx] is not None:
                safe = re.sub(r'[<>:"/\\|?*]+', '_', label).strip(' .') or 'fap'
                (env_dir / f'{safe}.json').write_text(json.dumps(recs[idx], indent=2), encoding='utf-8')
    xlsx = run_dir / f'fap_env_comparison_{env_a}_vs_{env_b}_{ts}.xlsx'
    summary = write_env_comparison(results, env_a, env_b, xlsx)

    _uat.logger.info(f'Wrote {run_dir}')
    print(f'\n{"FAP":40} {env_a:>6} {env_b:>6}  Differing settings')
    for name, in_a, in_b, diffs in summary:
        print(f'{name[:40]:40} {in_a:>6} {in_b:>6}  {diffs}')
    print(f'\nFolder:              {run_dir}')
    print(f'  Comparison:        {xlsx.name}')
    print(f'  JSON per FAP:      json/{env_a}/ and json/{env_b}/')


def main():
    parser = argparse.ArgumentParser(
        description='Export UKG Function Access Profiles to Excel for comparison')
    ukg_env.add_cli_args(parser)
    parser.add_argument('--list-profiles', action='store_true',
                        help='List saved profiles for --env and --grant-type, then exit')
    parser.add_argument('--name', action='append', dest='names', metavar='FAP',
                        help='FAP name (repeatable)')
    parser.add_argument('--names-file', default=None,
                        help='Text file with one FAP name per line (default: input/fap_tool/fap_names.txt)')
    parser.add_argument('--pair', action='append', nargs=2, metavar=('FAP_A', 'FAP_B'), default=[],
                        help='Add a tab comparing two FAPs (repeatable)')
    parser.add_argument('--all-pairs', action='store_true',
                        help='Add a tab for every combination of the requested FAPs')
    parser.add_argument('--baseline', metavar='FAP',
                        help='Add a tab comparing this FAP with each of the other requested FAPs')
    parser.add_argument('--vs-env', choices=ukg_env.ENVIRONMENTS, metavar='ENV',
                        help='Compare the same FAPs between --env and this environment '
                             '(uses the same --grant-type / --cred-mode)')
    parser.add_argument('--vs-profile', metavar='PROFILE',
                        help='Credential profile for --vs-env (default: its last-used profile)')
    parser.add_argument('--output-dir', default=str(_uat.OUTPUT_DIR),
                        help='Root output folder; results go to <dir>/fap_tool/fap_<env>_<ts>/')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would run and exit without calling the API')
    args = parser.parse_args()

    if args.list_profiles:
        default = ukg_env.default_profile(args.env, args.grant_type)
        for p in ukg_env.list_profiles(args.env, args.grant_type):
            print(f'{p}{"   (default)" if p == default else ""}')
        return

    names = load_names(args.names, args.names_file)
    if not names:
        parser.error('no FAP names — use --name, --names-file or input/fap_tool/fap_names.txt')

    try:
        client = ukg_env.client_from_args(args)
        if args.vs_env:
            client_b = ukg_env.build_client(args.vs_env, args.grant_type, args.cred_mode,
                                            args.vs_profile, ssl_verify=not args.no_verify_ssl)
            run_envs(names, client, client_b, Path(args.output_dir), dry_run=args.dry_run)
        else:
            run(names, client, Path(args.output_dir), dry_run=args.dry_run,
                pairs=args.pair, all_pairs=args.all_pairs, baseline=args.baseline)
    except Exception as exc:
        print(f'ERROR: {exc}')
        sys.exit(1)


if __name__ == '__main__':
    main()
