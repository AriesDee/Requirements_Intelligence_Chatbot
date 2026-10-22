"""Reusable UKG Pro WFM authentication + API client.

Ported from stonebranch/call_UKG_HWFD_jobs_v2.py (same modes, defaults and token logic),
but importable: no argparse at import time and no sys.exit() in library code.

Modes
    local      credentials from env vars WFM_USERNAME / WFM_PASSWORD / WFM_CLIENT_ID / WFM_CLIENT_SECRET
    local_akv  credentials from Azure Key Vault via interactive browser login
    akv        credentials from Azure Key Vault via managed identity (Stonebranch / Azure VM)

Example
    from ukg_auth import UKGClient
    client = UKGClient(base_url="albertsons-npr1.npr.mykronos.com", mode="local")
    integrations = client.get_json("/api/v1/platform/integrations")

CLI scripts can reuse the same flags as the Stonebranch script:
    parser = argparse.ArgumentParser()
    ukg_auth.add_auth_args(parser)
    client = ukg_auth.client_from_args(parser.parse_args())
"""
import os

import requests
import urllib3

MODES = ("local", "local_akv", "akv")

# Browser-login credentials are cached so repeated clients (e.g. from a UI) don't re-prompt.
_BROWSER_CREDENTIALS = {}


class UKGAuthError(Exception):
    """Raised when credentials cannot be loaded or a token cannot be obtained."""


class UKGClient:
    def __init__(self,
                 base_url="albertsons-npr1.npr.mykronos.com",
                 mode="local",
                 grant_type="password",
                 token_endpoint="/api/authentication/access_token",
                 auth_base_url="",
                 audience="",
                 organization="",
                 keyvault_name="hwfd-dev-wu-kv-01",
                 managed_identity_id="ae15b0de-4039-4949-9f71-fb8ac389dba4",
                 tenant_id="",
                 secret_username="npr1-wfm-pg-username",
                 secret_password="npr1-wfm-pg-password",
                 secret_client_id="npr1-wfm-pg-client-id",
                 secret_client_secret="npr1-wfm-pg-client-secret",
                 ssl_verify=False,
                 credentials=None):
        """credentials: optional dict(username, password, client_id, client_secret) used in
        'local' mode instead of the WFM_* environment variables (e.g. values typed in a UI)."""
        if mode not in MODES:
            raise ValueError("mode must be one of %s" % (MODES,))
        if grant_type not in ("password", "client_credentials"):
            raise ValueError("grant_type must be 'password' or 'client_credentials'")
        if grant_type == "client_credentials" and not (audience and organization):
            raise ValueError("audience and organization are required for client_credentials")

        self.base_url = base_url
        self.mode = mode
        self.grant_type = grant_type
        self.token_endpoint = token_endpoint
        self.auth_base_url = auth_base_url
        self.audience = audience
        self.organization = organization
        self.keyvault_name = keyvault_name
        self.managed_identity_id = managed_identity_id
        self.tenant_id = tenant_id
        self.secret_names = {
            "username": secret_username,
            "password": secret_password,
            "client_id": secret_client_id,
            "client_secret": secret_client_secret,
        }
        self.ssl_verify = ssl_verify
        if not ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self._secrets = None
        self._token = None
        self._credentials = credentials

    # ------------------------------------------------------------------ credentials
    def get_secrets(self):
        if self._secrets is None:
            self._secrets = (self._secrets_from_env() if self.mode == "local"
                             else self._secrets_from_keyvault())
        return self._secrets

    def _secrets_from_env(self):
        if self._credentials is not None:
            src = {"WFM_USERNAME": self._credentials.get("username", ""),
                   "WFM_PASSWORD": self._credentials.get("password", ""),
                   "WFM_CLIENT_ID": self._credentials.get("client_id", ""),
                   "WFM_CLIENT_SECRET": self._credentials.get("client_secret", "")}
        else:
            src = os.environ
        if self.grant_type == "client_credentials":
            required = ["WFM_CLIENT_ID", "WFM_CLIENT_SECRET"]
        else:
            required = ["WFM_USERNAME", "WFM_PASSWORD", "WFM_CLIENT_ID", "WFM_CLIENT_SECRET"]
        missing = [v for v in required if not src.get(v)]
        if missing:
            raise UKGAuthError("Missing required environment variables for local mode: "
                               + ", ".join(missing))
        return {
            "username": src.get("WFM_USERNAME", ""),
            "password": src.get("WFM_PASSWORD", ""),
            "client_id": src["WFM_CLIENT_ID"],
            "client_secret": src["WFM_CLIENT_SECRET"],
            "appkey": "",
        }

    def _keyvault_client(self):
        # Imported lazily so local-mode users don't need the Azure SDK installed.
        from azure.keyvault.secrets import SecretClient
        from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential

        cred_kwargs = {}
        if self.mode == "local_akv":
            cred_kwargs["tenant_id"] = self.tenant_id or None
            credential_cls = InteractiveBrowserCredential
        else:
            cred_kwargs["managed_identity_client_id"] = self.managed_identity_id
            credential_cls = DefaultAzureCredential
        if not self.ssl_verify:
            cred_kwargs["connection_verify"] = False
        if self.mode == "local_akv":
            key = (self.tenant_id, self.ssl_verify)
            credential = _BROWSER_CREDENTIALS.get(key)
            if credential is None:
                credential = _BROWSER_CREDENTIALS[key] = credential_cls(**cred_kwargs)
        else:
            credential = credential_cls(**cred_kwargs)

        kv_kwargs = {"vault_url": "https://%s.vault.azure.net/" % self.keyvault_name,
                     "credential": credential}
        if not self.ssl_verify:
            from azure.core.pipeline.transport import RequestsTransport
            kv_kwargs["transport"] = RequestsTransport(connection_verify=False)
        return SecretClient(**kv_kwargs)

    def _required_secret_keys(self):
        keys = ["client_id", "client_secret"]
        return keys + ["username", "password"] if self.grant_type == "password" else keys

    def check_keyvault(self):
        """Authenticate to Azure, open the vault and check each required secret exists.

        Returns [(secret_name, ok, detail)]. Values are never returned. Raises on auth/vault errors."""
        if self.mode == "local":
            raise UKGAuthError("Key Vault check applies to AKV modes only.")
        client = self._keyvault_client()
        results = []
        for key in self._required_secret_keys():
            name = self.secret_names[key]
            try:
                client.get_secret(name)
                results.append((name, True, "found"))
            except Exception as exc:
                results.append((name, False, type(exc).__name__ + ": " + str(exc).splitlines()[0]))
        return results

    def _secrets_from_keyvault(self):
        client = self._keyvault_client()
        secrets = {
            "username": "",
            "password": "",
            "client_id": client.get_secret(self.secret_names["client_id"]).value,
            "client_secret": client.get_secret(self.secret_names["client_secret"]).value,
            "appkey": "",
        }
        if self.grant_type == "password":
            secrets["username"] = client.get_secret(self.secret_names["username"]).value
            secrets["password"] = client.get_secret(self.secret_names["password"]).value
        return secrets

    # ------------------------------------------------------------------ token
    def generate_access_token(self):
        secrets = self.get_secrets()
        base = self.auth_base_url or self.base_url
        url = "https://%s%s" % (base, self.token_endpoint)
        headers = {}
        if secrets.get("appkey"):
            headers["appkey"] = secrets["appkey"]

        if self.grant_type == "client_credentials":
            body = {
                "client_id": secrets["client_id"],
                "client_secret": secrets["client_secret"],
                "grant_type": "client_credentials",
                "audience": self.audience,
                "organization": self.organization,
            }
            response = requests.post(url, json=body, headers=headers, verify=self.ssl_verify)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            # requests url-encodes dict values; the original hand-built string did not.
            form = {
                "username": secrets["username"],
                "password": secrets["password"],
                "client_id": secrets["client_id"],
                "client_secret": secrets["client_secret"],
                "grant_type": "password",
                "auth_chain": "OAuthLdapService",
            }
            response = requests.post(url, headers=headers, data=form, verify=self.ssl_verify)

        if not response.ok:
            raise UKGAuthError("Token request failed - HTTP %s: %s"
                               % (response.status_code, response.text))
        self._token = response.json()["access_token"]
        return self._token

    @property
    def token(self):
        if self._token is None:
            self.generate_access_token()
        return self._token

    def build_headers(self):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.token}
        appkey = self.get_secrets().get("appkey")
        if appkey:
            headers["AppKey"] = appkey
        return headers

    # ------------------------------------------------------------------ requests
    def request(self, method, path, **kwargs):
        """Authenticated request to https://<base_url><path>; refreshes the token once on 401."""
        url = "https://%s%s" % (self.base_url, path)
        kwargs.setdefault("verify", self.ssl_verify)
        kwargs.setdefault("timeout", 60)
        response = requests.request(method, url, headers=self.build_headers(), **kwargs)
        if response.status_code == 401:
            self.generate_access_token()
            response = requests.request(method, url, headers=self.build_headers(), **kwargs)
        return response

    def get_json(self, path, params=None):
        response = self.request("GET", path, params=params)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------- CLI helpers
def add_auth_args(parser):
    """Add the same auth flags as call_UKG_HWFD_jobs_v2.py (plus --base_url) to a parser."""
    parser.add_argument("--base_url", default="albertsons-npr1.npr.mykronos.com")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--local_mode", action="store_true",
                       help="Credentials from WFM_* env vars.")
    group.add_argument("--local_akv", action="store_true",
                       help="Credentials from Azure Key Vault via browser login.")
    parser.add_argument("--keyvault_name", default="hwfd-dev-wu-kv-01")
    parser.add_argument("--managed_identity_id", default="ae15b0de-4039-4949-9f71-fb8ac389dba4")
    parser.add_argument("--hwfd_username", default="npr1-wfm-pg-username")
    parser.add_argument("--hwfd_password", default="npr1-wfm-pg-password")
    parser.add_argument("--hwfd_client_id", default="npr1-wfm-pg-client-id")
    parser.add_argument("--hwfd_client_secret", default="npr1-wfm-pg-client-secret")
    parser.add_argument("--token_endpoint", default="/api/authentication/access_token")
    parser.add_argument("--grant_type", default="password",
                        choices=["password", "client_credentials"])
    parser.add_argument("--audience", default="")
    parser.add_argument("--organization", default="")
    parser.add_argument("--auth_base_url", default="")
    parser.add_argument("--tenant_id", default="")
    parser.add_argument("--ssl_verify", action="store_true")


def client_from_args(args):
    mode = "local" if args.local_mode else "local_akv" if args.local_akv else "akv"
    return UKGClient(
        base_url=args.base_url, mode=mode, grant_type=args.grant_type,
        token_endpoint=args.token_endpoint, auth_base_url=args.auth_base_url,
        audience=args.audience, organization=args.organization,
        keyvault_name=args.keyvault_name, managed_identity_id=args.managed_identity_id,
        tenant_id=args.tenant_id,
        secret_username=args.hwfd_username, secret_password=args.hwfd_password,
        secret_client_id=args.hwfd_client_id, secret_client_secret=args.hwfd_client_secret,
        ssl_verify=args.ssl_verify,
    )
