"""
ukg_api_tool.py — Generic UKG API endpoint executor

Authenticates with UKG and executes any API endpoint.
The request (method, endpoint, payload, headers) is defined in a JSON
config file placed in input/ — edit that file to target any endpoint.

Config file format (input/ukg_request.json):
  {
    "method":   "POST",
    "endpoint": "/api/v1/platform/reports/AuditReport/execute",
    "headers":  {},
    "payload":  { ... }
  }

  method   — HTTP verb: GET, POST, PATCH, PUT, DELETE  (default: GET)
  endpoint — path appended to the selected environment's URL
  headers  — optional extra request headers (merged with defaults)
  payload  — request body sent as JSON (omit or null for GET/DELETE)

Connection (environment + credentials) comes from ukg_env: choose --env NPR1|UAT|PRD and a
saved credential profile (or Azure Key Vault). Nothing environment-specific lives in input/.

Responses:
  JSON  → printed to console and saved to output/<name>_<ts>.json
  File  → saved to output/<name>_<ts>.<ext>  (e.g. .xlsx, .pdf)
  Other → saved to output/<name>_<ts>.txt

Usage:
  python ukg_api_tool.py --env UAT
  python ukg_api_tool.py --env PRD --grant-type password --profile prd_password_prdapiusr
  python ukg_api_tool.py --env NPR1 --config-file input/my_request.json --no-verify-ssl
  python ukg_api_tool.py --env UAT --dry-run
"""

import sys
import argparse
import json
import logging
import warnings
from datetime import datetime
from pathlib import Path

import requests
import urllib3

import ukg_env

# ---------------------------------------------------------------------------
# Folder structure
# ---------------------------------------------------------------------------

BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
INPUT_DIR  = BASE_DIR / 'input'
OUTPUT_DIR = BASE_DIR / 'output'
LOG_DIR    = BASE_DIR / 'log'

# Files in input/ that hold config/auth — never treated as request configs
_RESERVED_INPUT_FILES = {
    'config.json',
    'auth_client_credentials.json',   # legacy single-environment files, no longer read
    'auth_password_grant.json',
}

# ---------------------------------------------------------------------------
# SSL
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
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger('ukg_api_tool')


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
# Request config loader
# ---------------------------------------------------------------------------

def load_request_config(config_file: str | None = None) -> tuple[Path, dict]:
    """
    Load request config in priority order:
      1. --config-file <path>
      2. Most-recently-modified non-reserved .json file in input/
    Returns (source_path, config_dict).
    """
    if config_file:
        path = Path(config_file)
        if not path.exists():
            print(f'ERROR: Config file not found: {config_file}')
            sys.exit(1)
        with open(path, encoding='utf-8') as f:
            return path, json.load(f)

    INPUT_DIR.mkdir(exist_ok=True)
    json_files = sorted(
        (p for p in INPUT_DIR.glob('*.json') if p.name not in _RESERVED_INPUT_FILES),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not json_files:
        print('ERROR: No request config .json file found in input/.')
        print('       Create input/ukg_request.json with "method", "endpoint", and "payload".')
        sys.exit(1)

    cfg = None
    for candidate in json_files:
        with open(candidate, encoding='utf-8') as f:
            data = json.load(f)
        if 'endpoint' in data:
            path = candidate
            cfg  = data
            break

    if cfg is None:
        print('ERROR: No valid request config found in input/ (no file contains an "endpoint" key).')
        print('       Create input/ukg_request.json with "method", "endpoint", and "payload".')
        sys.exit(1)

    skipped = [p.name for p in json_files if p != path]
    if skipped:
        others = ', '.join(skipped)
        print(f'  (other .json files in input/ ignored: {others})')

    return path, cfg


# ---------------------------------------------------------------------------
# Response saver
# ---------------------------------------------------------------------------

_CONTENT_TYPE_EXT = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.ms-excel':   'xls',
    'application/pdf':            'pdf',
    'text/csv':                   'csv',
    'application/json':           'json',
    'text/plain':                 'txt',
    'text/html':                  'html',
    'application/octet-stream':   'bin',
}


def _guess_ext(content_type: str) -> str:
    ct = content_type.split(';')[0].strip().lower()
    for key, ext in _CONTENT_TYPE_EXT.items():
        if key in ct:
            return ext
    return 'bin'


def save_response(resp: requests.Response, stem: str, output_dir: Path) -> Path:
    content_type = resp.headers.get('Content-Type', '')
    ext          = _guess_ext(content_type)
    ts           = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path     = output_dir / f'{stem}_{ts}.{ext}'
    output_dir.mkdir(exist_ok=True)
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_kb = out_path.stat().st_size / 1024
    logger.info(f'Response saved: {out_path}  ({size_kb:.1f} KB)')
    print(f'\nResponse saved: output/{out_path.name}  ({size_kb:.1f} KB)')
    return out_path


# ---------------------------------------------------------------------------
# Execute request
# ---------------------------------------------------------------------------

BODY_METHODS = ('POST', 'PUT', 'PATCH')


def log_request(method: str, url: str, headers: dict | None, payload):
    """Write the complete request (method, URL, headers, full JSON body) to the log.

    The bearer token is masked; everything else is logged as sent."""
    logger.info(f'Request: {method} {url}')
    if headers:
        shown = {k: ('Bearer ***' if k.lower() == 'authorization' else v) for k, v in headers.items()}
        logger.info('Request headers:\n' + json.dumps(shown, indent=2))
    if payload is None:
        logger.info('Request body: (none)')
    elif method in BODY_METHODS:
        logger.info('Request body:\n' + json.dumps(payload, indent=2))
    else:
        logger.info(f'Request body: not sent for {method}; the payload in the config is ignored')

def execute(basic_url: str, access_token: str, cfg: dict, output_dir: Path,
            config_stem: str):
    method    = cfg.get('method', 'GET').upper()
    endpoint  = cfg.get('endpoint', '')
    payload   = cfg.get('payload')
    extra_hdr = cfg.get('headers', {})

    if not endpoint:
        print('ERROR: Config file is missing "endpoint".')
        sys.exit(1)

    url = basic_url.rstrip('/') + endpoint

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept':        'application/json, application/octet-stream, */*',
    }
    if method in BODY_METHODS and payload is not None:
        headers['Content-Type'] = 'application/json'
    headers.update(extra_hdr)

    log_request(method, url, headers, payload)

    try:
        resp = requests.request(
            method  = method,
            url     = url,
            headers = headers,
            json    = payload if method in ('POST', 'PUT', 'PATCH') else None,
            timeout = 120,
            verify  = SSL_VERIFY,
            stream  = True,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f'Request failed: {exc}')
        if hasattr(exc, 'response') and exc.response is not None:
            logger.error(f'Response body: {exc.response.text}')
            print(f'\nHTTP {exc.response.status_code}')
            print(f'Body: {exc.response.text}')
        raise

    content_type = resp.headers.get('Content-Type', '')
    print(f'\nHTTP {resp.status_code}  Content-Type: {content_type}')

    if 'json' in content_type:
        body = resp.json()
        print(json.dumps(body, indent=2))
        out_path = output_dir / f'{config_stem}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        output_dir.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(body, indent=2), encoding='utf-8')
        size_kb = out_path.stat().st_size / 1024
        logger.info(f'Response saved: {out_path}  ({size_kb:.1f} KB)')
        print(f'\nResponse saved: output/{out_path.name}  ({size_kb:.1f} KB)')
    else:
        save_response(resp, config_stem, output_dir)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(config_file: str | None, output_dir: Path, client, dry_run: bool = False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = LOG_DIR / f'ukg_api_{ts}.log'
    setup_logging(log_path)

    basic_url = f'https://{client.base_url}'

    config_path, cfg = load_request_config(config_file)
    config_stem      = config_path.stem

    logger.info(f'ukg_api_tool starting — config={config_path.name}')
    print('\n'.join(ukg_env.describe(client, client.grant_type)))
    print(f'Config:    input/{config_path.name}')
    print(f'Method:    {cfg.get("method", "GET").upper()}')
    print(f'Endpoint:  {cfg.get("endpoint", "(not set)")}')

    if dry_run:
        log_request(cfg.get('method', 'GET').upper(), basic_url.rstrip('/') + cfg.get('endpoint', ''),
                    None, cfg.get('payload'))
        print(f'\nDRY RUN — no API calls made.')
        return

    access_token = client.generate_access_token()
    logger.info('Authentication successful')
    execute(basic_url, access_token, cfg, output_dir, config_stem)

    logger.info('Done')
    print(f'Log:       log/ukg_api_{ts}.log')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generic UKG API endpoint executor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Request config file (input/*.json):\n'
            '  {\n'
            '    "method":   "POST",\n'
            '    "endpoint": "/api/v1/platform/reports/AuditReport/execute",\n'
            '    "headers":  {},\n'
            '    "payload":  { ... }\n'
            '  }\n\n'
            'Examples:\n'
            '  python ukg_api_tool.py\n'
            '  python ukg_api_tool.py --config-file input/my_request.json\n'
            '  python ukg_api_tool.py --no-verify-ssl\n'
            '  python ukg_api_tool.py --dry-run\n'
        ),
    )
    ukg_env.add_cli_args(parser)
    parser.add_argument('--config-file',   default=None,
                        help='Path to request config JSON (default: newest non-reserved .json in input/)')
    parser.add_argument('--output-dir',    default=str(OUTPUT_DIR),
                        help='Directory to save responses (default: output/)')
    parser.add_argument('--dry-run',       action='store_true',
                        help='Print config and exit without calling the API')

    args = parser.parse_args()

    if args.no_verify_ssl:
        _disable_ssl()

    run(
        config_file = args.config_file,
        output_dir  = Path(args.output_dir),
        client      = ukg_env.client_from_args(args),
        dry_run     = args.dry_run,
    )


if __name__ == '__main__':
    main()
