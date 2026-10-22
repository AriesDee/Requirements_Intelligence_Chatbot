"""Environment-aware UKGClient factory (NPR1 / UAT / PRD).

Reuses the settings the stonebranch tools already maintain in ~/.ukg_hwfd/:
    profiles.json     named credential profiles; secrets live in Windows Credential Manager
                      (keyring service "UKG_HWFD_v2"), saved from call_UKG_HWFD_jobs_v2_ui.py
    akv_config.json   per-environment Key Vault / managed identity / secret names

Nothing environment-specific is stored in UKG Tools/input any more: pick an environment
and a credential profile and everything else (URL, organization, token host) follows.

Example
    from ukg_env import build_client
    client = build_client("UAT", grant_type="client_credentials", cred_mode="local")
"""
import json
import os

import ukg_auth

KEYRING_SERVICE = "UKG_HWFD_v2"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ukg_hwfd")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
AKV_CONFIG_FILE = os.path.join(CONFIG_DIR, "akv_config.json")

# Same values as call_UKG_HWFD_jobs_v2_ui.py (none of these are secrets).
ENV_PROFILES = {
    "NPR1": {"url": "albertsons-npr1.npr.mykronos.com", "organization": "org_aR9lK2W3h7SSYHMK"},
    "UAT": {"url": "albertsons-uat.npr.mykronos.com", "organization": "org_vYcUtBwokQiXwpzm"},
    "PRD": {"url": "albertsons.prd.mykronos.com", "organization": "org_WbZwfc4ZPXpcT8p1"},
}
TOKEN_ENDPOINT_DEFAULTS = {
    "password": "/api/authentication/access_token",
    "client_credentials": "/oauth/token",
}
# client_credentials tokens come from a different host in non-prod
AUTH_BASE_URL_CC = {"NPR1": "welcome-test-us.ukg.net", "UAT": "welcome-test-us.ukg.net",
                    "PRD": "welcome-us.ukg.net"}
AUDIENCE = "https://wfm.ukg.net/api"

ENVIRONMENTS = list(ENV_PROFILES)
GRANT_TYPES = ("client_credentials", "password")
CRED_MODES = ("local", "local_akv", "akv")
_AKV_MODE_KEY = {"local_akv": "akv_local_machine", "akv": "akv_stonebranch_server"}


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------- profiles
def list_profiles(env, grant_type):
    """Saved credential profile names for an environment + grant type (sorted)."""
    profiles = _read_json(PROFILES_FILE, {}).get("profiles", {})
    return sorted(n for n, m in profiles.items()
                  if m.get("env") == env and m.get("grant_type") == grant_type)


def default_profile(env, grant_type):
    """Last-used profile for this environment + grant type, else the first one, else None."""
    data = _read_json(PROFILES_FILE, {})
    names = list_profiles(env, grant_type)
    last = data.get("last_used", {}).get("%s:%s" % (env, grant_type))
    return last if last in names else (names[0] if names else None)


def remember_profile(env, grant_type, name):
    """Record the profile as last-used (shared with the stonebranch UI)."""
    data = _read_json(PROFILES_FILE, {"last_used": {}, "profiles": {}})
    data.setdefault("last_used", {})["%s:%s" % (env, grant_type)] = name
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def profile_prefix(env, grant_type):
    """Profile names are '<env>_<password|client>_<name>', same convention as the stonebranch UI."""
    return "%s_%s_" % (env.lower(), "password" if grant_type == "password" else "client")


def credential_fields(grant_type):
    """WFM_* variables a profile stores for this grant type."""
    base = ["WFM_CLIENT_ID", "WFM_CLIENT_SECRET"]
    return ["WFM_USERNAME", "WFM_PASSWORD"] + base if grant_type == "password" else base


def save_profile(env, grant_type, unique_name, values):
    """Create or overwrite a profile. values: {WFM_*: str}. Returns the full profile name.

    Secrets go to Windows Credential Manager; profiles.json holds only names and metadata,
    in the same format the stonebranch UI reads and writes."""
    try:
        import keyring
    except ImportError:
        raise ukg_auth.UKGAuthError("keyring is not installed - run: pip install keyring")
    unique = unique_name.strip().lower().replace(" ", "_")
    if not unique:
        raise ValueError("Profile name is required.")
    fields = credential_fields(grant_type)
    empty = [f for f in fields if not values.get(f)]
    if empty:
        raise ValueError("Missing value for: " + ", ".join(empty))
    name = unique if unique.startswith(profile_prefix(env, grant_type)) \
        else profile_prefix(env, grant_type) + unique
    for var in fields:
        keyring.set_password(KEYRING_SERVICE, "%s:%s" % (name, var), values[var])
    data = _read_json(PROFILES_FILE, {"last_used": {}, "profiles": {}})
    data.setdefault("profiles", {})[name] = {"env": env, "grant_type": grant_type, "vars": fields}
    data.setdefault("last_used", {})["%s:%s" % (env, grant_type)] = name
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return name


def delete_profile(name):
    """Remove a profile's secrets and its entry in profiles.json."""
    try:
        import keyring
    except ImportError:
        raise ukg_auth.UKGAuthError("keyring is not installed - run: pip install keyring")
    data = _read_json(PROFILES_FILE, {"last_used": {}, "profiles": {}})
    meta = data.get("profiles", {}).pop(name, None)
    if meta is None:
        return
    for var in meta.get("vars", []):
        try:
            keyring.delete_password(KEYRING_SERVICE, "%s:%s" % (name, var))
        except keyring.errors.PasswordDeleteError:
            pass
    data["last_used"] = {k: v for k, v in data.get("last_used", {}).items() if v != name}
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_profile_credentials(name):
    """Read a profile's secrets from Windows Credential Manager."""
    try:
        import keyring
    except ImportError:
        raise ukg_auth.UKGAuthError("keyring is not installed - run: pip install keyring")
    meta = _read_json(PROFILES_FILE, {}).get("profiles", {}).get(name)
    if meta is None:
        raise ukg_auth.UKGAuthError("Credential profile '%s' not found in %s" % (name, PROFILES_FILE))
    creds = {}
    for var in meta.get("vars", []):
        val = keyring.get_password(KEYRING_SERVICE, "%s:%s" % (name, var))
        creds[var[len("WFM_"):].lower()] = val or ""      # WFM_CLIENT_ID -> client_id
    missing = [v for v in ("client_id", "client_secret") if not creds.get(v)]
    if missing:
        raise ukg_auth.UKGAuthError("Profile '%s' has no stored value for: %s"
                                    % (name, ", ".join(missing)))
    return creds


# ---------------------------------------------------------------------- Key Vault
def _akv_kwargs(env, cred_mode, grant_type):
    entry = _read_json(AKV_CONFIG_FILE, {}).get(env, {}).get(_AKV_MODE_KEY[cred_mode])
    if not entry:
        raise ukg_auth.UKGAuthError(
            "No '%s' settings for %s in %s - save them from the stonebranch UI first."
            % (_AKV_MODE_KEY[cred_mode], env, AKV_CONFIG_FILE))
    keys = entry.get("secret_keys", {}).get(grant_type, {})
    kwargs = {"keyvault_name": entry["keyvault_name"],
              "tenant_id": entry.get("tenant_id", ""),
              "ssl_verify": entry.get("ssl_verify", False)}
    if entry.get("managed_identity_id"):
        kwargs["managed_identity_id"] = entry["managed_identity_id"]
    for ours, theirs in (("secret_username", "hwfd_username"), ("secret_password", "hwfd_password"),
                         ("secret_client_id", "hwfd_client_id"),
                         ("secret_client_secret", "hwfd_client_secret")):
        if keys.get(theirs):
            kwargs[ours] = keys[theirs]
    return kwargs


# ---------------------------------------------------------------------- factory
def build_client(env, grant_type="client_credentials", cred_mode="local", profile=None,
                 ssl_verify=False):
    """UKGClient for one environment.

    cred_mode "local":     secrets from a saved profile (default: last used for env + grant type),
                           or WFM_* environment variables when no profile exists.
    cred_mode "local_akv": Azure Key Vault via browser login (names from akv_config.json).
    cred_mode "akv":       Azure Key Vault via managed identity (names from akv_config.json).
    """
    if env not in ENV_PROFILES:
        raise ValueError("environment must be one of %s" % (ENVIRONMENTS,))
    if grant_type not in GRANT_TYPES:
        raise ValueError("grant_type must be one of %s" % (GRANT_TYPES,))
    if cred_mode not in CRED_MODES:
        raise ValueError("cred_mode must be one of %s" % (CRED_MODES,))

    prof = ENV_PROFILES[env]
    kwargs = dict(
        base_url=prof["url"], mode=cred_mode, grant_type=grant_type,
        token_endpoint=TOKEN_ENDPOINT_DEFAULTS[grant_type],
        ssl_verify=ssl_verify,
    )
    if grant_type == "client_credentials":
        kwargs.update(auth_base_url=AUTH_BASE_URL_CC[env], audience=AUDIENCE,
                      organization=prof["organization"])

    if cred_mode == "local":
        profile = profile or default_profile(env, grant_type)
        if profile:
            kwargs["credentials"] = load_profile_credentials(profile)
    else:
        kwargs.update(_akv_kwargs(env, cred_mode, grant_type))
        kwargs["ssl_verify"] = ssl_verify
    client = ukg_auth.UKGClient(**kwargs)
    client.env = env
    client.profile_name = profile if cred_mode == "local" else None
    return client


# ---------------------------------------------------------------------- CLI helpers
def add_cli_args(parser):
    """Connection flags shared by every UKG Tools command-line tool."""
    parser.add_argument("--env", required=True, choices=ENVIRONMENTS, help="Target environment")
    parser.add_argument("--grant-type", choices=GRANT_TYPES, default="client_credentials")
    parser.add_argument("--cred-mode", choices=CRED_MODES, default="local",
                        help="local = saved profile / WFM_* env vars; local_akv / akv = Azure Key Vault")
    parser.add_argument("--profile", default=None,
                        help="Saved credential profile (default: last used for env + grant type)")
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="Disable SSL certificate verification (corporate proxy)")


def client_from_args(args):
    return build_client(args.env, args.grant_type, args.cred_mode, args.profile,
                        ssl_verify=not args.no_verify_ssl)


def describe(client, grant_type):
    """One-line-per-fact summary of a connection, safe to print (no secrets)."""
    if client.profile_name:
        src = "profile=%s" % client.profile_name
    elif client.mode == "local":
        src = "WFM_* environment variables"
    else:
        src = "Key Vault %s" % client.keyvault_name
    return ["Environment: %s  (%s)" % (client.env, client.base_url),
            "Grant type:  %s" % grant_type,
            "Credentials: %s  (%s)" % (client.mode, src)]
