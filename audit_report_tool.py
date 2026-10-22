"""
audit_report_tool.py — UKG Audit Report automation tool

Runs the Audit Report via the UKG Pro WFM API and downloads the resulting file.

Flow:
  1. Authenticate  → token for the chosen environment / credential profile (see ukg_env.py)
  2. Run report    → POST /api/v1/platform/reports/AuditReport/execute  → execution id
  3. Poll status   → GET  /api/v1/platform/report_executions/<id>  (until Completed)
  4. Download file → GET  /api/v1/platform/report_executions/<id>/file

Connection: --env NPR1|UAT|PRD, --grant-type, --cred-mode, --profile.
input/config.json holds email settings only (smtp_*).

Payload (report parameters):
  Place a JSON file in input/ — the tool picks it up automatically (newest non-reserved file).
  Pass --payload-file <path> to target a specific file.

Usage:
  python audit_report_tool.py --env UAT
  python audit_report_tool.py --env UAT --test    # step-by-step with prompts
  python audit_report_tool.py --env UAT --dry-run # validate config only
  python audit_report_tool.py --env PRD --poll-interval 5 --timeout 300
  python audit_report_tool.py --env PRD --payload-file input/my_payload.json
"""

import sys
import argparse
import json
import time
import logging
import warnings
from datetime import datetime
from pathlib import Path

import requests
import urllib3

import ukg_env

# ---------------------------------------------------------------------------
# SSL verification
# ---------------------------------------------------------------------------

SSL_VERIFY = True


def _disable_ssl():
    global SSL_VERIFY
    SSL_VERIFY = False
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    warnings.warn(
        'SSL verification disabled. Only use this on a trusted corporate network.',
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Folder structure
# ---------------------------------------------------------------------------

BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
INPUT_DIR  = BASE_DIR / 'input'
OUTPUT_DIR = BASE_DIR / 'output'
LOG_DIR    = BASE_DIR / 'log'

# mailer.py lives at repo root; ensure it's importable regardless of CWD
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

REPORT_RUN_PATH        = '/api/v1/platform/reports/AuditReport/execute'
REPORT_STATUS_PATH     = '/api/v1/platform/report_executions/{id}'
REPORT_FILE_PATH       = '/api/v1/platform/report_executions/{id}/file'

STATUS_COMPLETED = 'Completed'
STATUS_FAILED    = {'Failed', 'Error', 'Cancelled'}

# Files in input/ that hold config/auth — never treated as report payloads
_RESERVED_INPUT_FILES = {
    'config.json',
    'auth_client_credentials.json',
    'auth_password_grant.json',
}


def _output_format(payload: dict) -> str:
    for param in payload.get('parameters', []):
        if param.get('name') == 'Output Format':
            return param.get('value', {}).get('key', 'xlsx')
    return 'xlsx'


DEFAULT_PAYLOAD = {
    "parameters": [
        {"name": "Audit Types",   "value": [{"key": "Integration"}]},
        {"name": "DateRange",     "value": {"startDate": "2026-08-10", "endDate": "2026-08-17"}},
        {"name": "Output Format", "value": {"key": "xlsx"}},
        {"name": "user",          "value": ""},
        {"name": "auditUserIds",  "value": ""},
    ]
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger('audit_report_tool')


def setup_logging(log_path: Path):
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)


# ---------------------------------------------------------------------------
# Step 2 — Run the report
# ---------------------------------------------------------------------------

def run_report(basic_url: str, access_token: str, payload: dict) -> int:
    url = basic_url.rstrip('/') + REPORT_RUN_PATH
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type':  'application/json',
        'Accept':        'application/json',
    }
    logger.info(f'Running report — POST {url}')
    shown = {k: ('Bearer ***' if k.lower() == 'authorization' else v) for k, v in headers.items()}
    logger.info('Request headers:\n' + json.dumps(shown, indent=2))
    logger.info('Request body:\n' + json.dumps(payload, indent=2))
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60, verify=SSL_VERIFY)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f'Run report failed: {exc}')
        if hasattr(exc, 'response') and exc.response is not None:
            logger.error(f'Response: {exc.response.text}')
        raise
    data         = resp.json()
    execution_id = data.get('id')
    status       = data.get('status', {}).get('qualifier', 'unknown')
    logger.info(f'Execution started — id={execution_id}, status={status}')
    logger.debug(f'Full response: {json.dumps(data)}')
    print(f'Report execution started — id={execution_id}, status={status}')
    if not execution_id:
        raise RuntimeError(f'No execution id in response: {data}')
    return execution_id


# ---------------------------------------------------------------------------
# Step 3 — Poll until completed
# ---------------------------------------------------------------------------

def check_status(basic_url: str, access_token: str, execution_id: int) -> str:
    url = basic_url.rstrip('/') + REPORT_STATUS_PATH.format(id=execution_id)
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}
    resp = requests.get(url, headers=headers, timeout=30, verify=SSL_VERIFY)
    resp.raise_for_status()
    status = resp.json().get('status', {}).get('qualifier', 'unknown')
    logger.debug(f'Status check id={execution_id}: {status}')
    return status


def poll_until_complete(basic_url: str, access_token: str, execution_id: int,
                        poll_interval: int = 10, timeout: int = 600):
    deadline = time.time() + timeout
    elapsed  = 0
    logger.info(f'Polling id={execution_id} every {poll_interval}s (timeout={timeout}s)')
    while time.time() < deadline:
        status = check_status(basic_url, access_token, execution_id)
        if status == STATUS_COMPLETED:
            logger.info(f'Report completed after ~{elapsed}s')
            print(f'  Status: {status} — ready to download')
            return
        if status in STATUS_FAILED:
            raise RuntimeError(f'Report execution id={execution_id} ended with status: {status}')
        elapsed += poll_interval
        print(f'  [{elapsed:>4}s elapsed]  Status: {status} — '
              f'checking again in {poll_interval}s ...', flush=True)
        time.sleep(poll_interval)
    raise TimeoutError(f'Report execution id={execution_id} did not complete within {timeout}s')


# ---------------------------------------------------------------------------
# Step 4 — Download the file
# ---------------------------------------------------------------------------

def download_report(basic_url: str, access_token: str, execution_id: int, output_path: Path):
    url = basic_url.rstrip('/') + REPORT_FILE_PATH.format(id=execution_id)
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, '
            'application/octet-stream, */*'
        ),
    }
    logger.info(f'Downloading report — GET {url}')
    resp = requests.get(url, headers=headers, timeout=120, stream=True, verify=SSL_VERIFY)
    resp.raise_for_status()
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_kb = output_path.stat().st_size / 1024
    logger.info(f'Saved: {output_path}  ({size_kb:.1f} KB)')
    print(f'\nReport saved:  output/{output_path.name}  ({size_kb:.1f} KB)')


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def run(payload: dict, output_dir: Path, client,
        poll_interval: int = 10, timeout: int = 600,
        dry_run: bool = False, email: bool = False):

    basic_url = f'https://{client.base_url}'

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f'audit_report_{ts}.log'
    setup_logging(log_path)
    logger.info(f'audit_report_tool starting  dry_run={dry_run}')

    if dry_run:
        print('DRY RUN — configuration looks good.')
        print('  ' + '\n  '.join(ukg_env.describe(client, client.grant_type)))
        logger.info(f'Request: POST {basic_url.rstrip("/") + REPORT_RUN_PATH}')
        logger.info('Request body:\n' + json.dumps(payload, indent=2))
        print('No API calls were made.')
        return

    access_token = client.generate_access_token()
    logger.info('Authentication successful — access token obtained')
    print(f'Authenticated against {basic_url}')

    execution_id = run_report(basic_url, access_token, payload)
    poll_until_complete(basic_url, access_token, execution_id,
                        poll_interval=poll_interval, timeout=timeout)

    fmt         = _output_format(payload)
    output_file = output_dir / f'AuditReport_{execution_id}_{ts}.{fmt}'
    download_report(basic_url, access_token, execution_id, output_file)

    if email:
        import mailer
        try:
            mailer.send(output_file, is_test=False)
        except Exception as exc:
            logger.error(f'Email failed (report still saved): {exc}')
            print(f'WARNING: Email failed — {exc}')
            print(f'         Report is still saved at: {output_file}')

    logger.info('Done')
    print(f'Log file:      log/audit_report_{ts}.log')


# ---------------------------------------------------------------------------
# Test mode — step-by-step with raw response output
# ---------------------------------------------------------------------------

def _sep(title: str):
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print(f'{"=" * 60}')


def _ask(prompt: str) -> bool:
    return input(f'\n{prompt} [y/N]: ').strip().lower() == 'y'


def _print_response(resp: requests.Response):
    print(f'  HTTP status : {resp.status_code}')
    content_type = resp.headers.get('Content-Type', '')
    print(f'  Content-Type: {content_type}')
    if 'json' in content_type:
        try:
            print(f'  Body:\n{json.dumps(resp.json(), indent=4)}')
        except Exception:
            print(f'  Body: {resp.text[:500]}')
    elif 'octet' in content_type or 'spreadsheet' in content_type:
        print(f'  Body: <binary file — {len(resp.content):,} bytes>')
    else:
        print(f'  Body: {resp.text[:500]}')


def test_run(payload: dict, output_dir: Path, client, email: bool = False):
    basic_url = f'https://{client.base_url}'

    LOG_DIR.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = LOG_DIR / f'audit_report_test_{ts}.log'
    setup_logging(log_path)

    print(f'\nTarget URL : {basic_url}')
    print(f'Log file   : log/{log_path.name}')

    # ------------------------------------------------------------------
    # Step 1 — Auth
    # ------------------------------------------------------------------
    _sep('STEP 1 — Authenticate')
    print('  ' + '\n  '.join(ukg_env.describe(client, client.grant_type)))
    print(f'  Token endpoint: https://{client.auth_base_url or client.base_url}{client.token_endpoint}')

    if not _ask('Request a token?'):
        print('Aborted.')
        return

    try:
        access_token = client.generate_access_token()
    except Exception as exc:
        print(f'\nERROR: {exc}')
        return
    print(f'\n  access_token:{access_token[:20]}...  (truncated for display)')

    # ------------------------------------------------------------------
    # Step 2 — Run report
    # ------------------------------------------------------------------
    _sep('STEP 2 — Run Report')
    url = basic_url.rstrip('/') + REPORT_RUN_PATH
    print(f'  POST {url}')
    print(f'  Headers:')
    print(f'    Authorization: Bearer {access_token[:20]}...  (truncated)')
    print(f'    Content-Type : application/json')
    print(f'    Accept       : application/json')
    print(f'  Payload:\n{json.dumps(payload, indent=4)}')

    if not _ask('Send this request?'):
        print('Aborted.')
        return

    try:
        resp = requests.post(
            url, json=payload,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type':  'application/json',
                'Accept':        'application/json',
            },
            timeout=60, verify=SSL_VERIFY,
        )
        _print_response(resp)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f'\nERROR: {exc}')
        return

    execution_id = resp.json().get('id')
    if not execution_id:
        print('\nERROR: No execution id in response.')
        return
    print(f'\n  execution_id: {execution_id}')

    # ------------------------------------------------------------------
    # Step 3 — Poll status
    # ------------------------------------------------------------------
    _sep('STEP 3 — Poll Execution Status (loops until Completed or Failed)')
    url = basic_url.rstrip('/') + REPORT_STATUS_PATH.format(id=execution_id)
    print(f'  GET {url}')

    poll_interval = 10
    try:
        raw = input(f'\n  Poll interval in seconds? [default: {poll_interval}]: ').strip()
        if raw.isdigit():
            poll_interval = int(raw)
    except (EOFError, KeyboardInterrupt):
        pass

    if not _ask('Start polling?'):
        print('Aborted.')
        return

    elapsed = 0
    while True:
        try:
            resp = requests.get(
                url,
                headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'},
                timeout=30, verify=SSL_VERIFY,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f'\nERROR: {exc}')
            return

        data   = resp.json()
        status = data.get('status', {}).get('qualifier', 'unknown')
        print(f'  [{elapsed:>4}s elapsed]  Status: {status}')

        if status == STATUS_COMPLETED:
            print(f'\n  Full response:')
            print(json.dumps(data, indent=4))
            break
        if status in STATUS_FAILED:
            print(f'\n  Full response:')
            print(json.dumps(data, indent=4))
            print(f'\nERROR: Report ended with status: {status}')
            return

        elapsed += poll_interval
        time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Step 4 — Download file
    # ------------------------------------------------------------------
    _sep('STEP 4 — Download Report File')
    url = basic_url.rstrip('/') + REPORT_FILE_PATH.format(id=execution_id)
    print(f'  GET {url}')

    if not _ask('Send this request?'):
        print('Aborted.')
        return

    try:
        resp = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': (
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, '
                    'application/octet-stream, */*'
                ),
            },
            timeout=120, stream=True, verify=SSL_VERIFY,
        )
        _print_response(resp)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f'\nERROR: {exc}')
        return

    fmt         = _output_format(payload)
    output_file = output_dir / f'AuditReport_{execution_id}_{ts}.{fmt}'
    with open(output_file, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_kb = output_file.stat().st_size / 1024
    print(f'\n  Saved: output/{output_file.name}  ({size_kb:.1f} KB)')

    if email:
        import mailer
        try:
            mailer.send(output_file, is_test=True)
        except Exception as exc:
            print(f'\nWARNING: Email failed — {exc}')
            print(f'         Report is still saved at: {output_file}')

    _sep('TEST COMPLETE — all 4 steps passed')
    print(f'  Log: log/{log_path.name}\n')


# ---------------------------------------------------------------------------
# Payload loader
# ---------------------------------------------------------------------------

def _extract_payload(data: dict, source: str) -> dict:
    """If the loaded JSON is a request-config (has method/endpoint), extract the inner payload."""
    if 'method' in data or 'endpoint' in data:
        inner = data.get('payload')
        if inner is None:
            print(f'WARNING: {source} looks like a request-config but has no "payload" key — using DEFAULT_PAYLOAD.')
            logger.warning(f'{source} is a request-config with no payload key')
            return DEFAULT_PAYLOAD
        logger.info(f'Extracted inner payload from request-config file: {source}')
        return inner
    return data


def load_payload(payload_file: str | None = None) -> dict:
    if payload_file:
        path = Path(payload_file)
        if not path.exists():
            print(f'ERROR: Payload file not found: {payload_file}')
            sys.exit(1)
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        payload = _extract_payload(data, path.name)
        print(f'Payload loaded from: {path}')
        logger.info(f'Payload loaded from: {path}')
        return payload

    INPUT_DIR.mkdir(exist_ok=True)
    json_files = sorted(
        (p for p in INPUT_DIR.glob('*.json') if p.name not in _RESERVED_INPUT_FILES),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if json_files:
        path = json_files[0]
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        payload = _extract_payload(data, path.name)
        print(f'Payload loaded from: input/{path.name}')
        logger.info(f'Payload loaded from: input/{path.name}')
        if len(json_files) > 1:
            others = ', '.join(p.name for p in json_files[1:])
            print(f'  (other .json files in input/ ignored: {others})')
        return payload

    print('No payload file found in input/ — using default payload.')
    logger.info('Using DEFAULT_PAYLOAD')
    return DEFAULT_PAYLOAD


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='UKG Audit Report automation tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Connection: --env NPR1|UAT|PRD plus a saved credential profile (see ukg_env.py).\n'
            'input/config.json holds email settings only (smtp_*).\n\n'
            'Examples:\n'
            '  python audit_report_tool.py --env UAT --test     # step-by-step with prompts\n'
            '  python audit_report_tool.py --env UAT --dry-run  # validate config only\n'
            '  python audit_report_tool.py --env PRD            # full automated run\n'
            '  python audit_report_tool.py --env PRD --grant-type password --profile <name>\n'
            '  python audit_report_tool.py --env UAT --payload-file input/my_payload.json\n'
        ),
    )
    ukg_env.add_cli_args(parser)
    parser.add_argument('--output-dir',     default=str(OUTPUT_DIR),
                        help='Directory to save the downloaded report (default: output/)')
    parser.add_argument('--poll-interval',  type=int, default=5,
                        help='Seconds between status checks (default: 5)')
    parser.add_argument('--timeout',        type=int, default=600,
                        help='Max seconds to wait for completion (default: 600)')
    parser.add_argument('--payload-file',   default=None,
                        help='Path to a JSON file with the report request payload')
    parser.add_argument('--dry-run',        action='store_true',
                        help='Validate config and exit without calling the API')
    parser.add_argument('--test',           action='store_true',
                        help='Step through each API call one at a time with prompts')
    parser.add_argument('--email',          action='store_true',
                        help='Email the downloaded report (requires smtp_* in input/config.json)')

    args = parser.parse_args()

    if args.no_verify_ssl:
        _disable_ssl()

    payload = load_payload(args.payload_file)

    if args.test:
        test_run(payload=payload, output_dir=Path(args.output_dir),
                 client=ukg_env.client_from_args(args), email=args.email)
        return

    run(
        payload       = payload,
        output_dir    = Path(args.output_dir),
        client        = ukg_env.client_from_args(args),
        poll_interval = args.poll_interval,
        timeout       = args.timeout,
        dry_run       = args.dry_run,
        email         = args.email,
    )


if __name__ == '__main__':
    main()
