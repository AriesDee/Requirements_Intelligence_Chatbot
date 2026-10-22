#!/usr/bin/python3
"""UI for integration_inventory.py - Setup / Run / Results tabs.

Pulls all integrations, per-integration details and schedules from UKG Pro WFM and
consolidates them into one Excel workbook. Authentication is handled by ukg_auth.py.

Credential profiles use the same Windows Credential Manager service and profiles file as
stonebranch/call_UKG_HWFD_jobs_v2_ui.py, so profiles saved there are available here.
"""
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import keyring
    _KEYRING_OK = True
except ImportError:
    _KEYRING_OK = False

# ukg_auth.py lives in the repo root (one level up), shared with the other UKG tools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integration_inventory  # noqa: E402
import ukg_auth  # noqa: E402

UI_FONT = "Verdana"
UI_FONT_SIZE = 10
LOG_FONT = "Courier New"

KEYRING_SERVICE = "UKG_HWFD_v2"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ukg_hwfd")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "inventory_ui_settings.json")

ENV_PROFILES = {
    "NPR1": {"url": "albertsons-npr1.npr.mykronos.com", "organization": "org_aR9lK2W3h7SSYHMK"},
    "UAT": {"url": "albertsons-uat.npr.mykronos.com", "organization": "org_vYcUtBwokQiXwpzm"},
    "PRD": {"url": "albertsons.prd.mykronos.com", "organization": "org_WbZwfc4ZPXpcT8p1"},
}
TOKEN_ENDPOINT_DEFAULTS = {
    "password": "/api/authentication/access_token",
    "client_credentials": "/oauth/token",
}
AUTH_BASE_URL_CC = {"NPR1": "welcome-test-us.ukg.net", "UAT": "welcome-test-us.ukg.net",
                    "PRD": "welcome-us.ukg.net"}
URLS = [p["url"] for p in ENV_PROFILES.values()]
URL_TO_ENV = {p["url"]: env for env, p in ENV_PROFILES.items()}
TOKEN_ENDPOINTS = list(TOKEN_ENDPOINT_DEFAULTS.values())
AUTH_BASE_URLS = sorted(set(AUTH_BASE_URL_CC.values()))
CRED_MODES = [
    ("local", "Local Credentials", "Typed here, or from Credential Manager profile / env vars."),
    ("local_akv", "AKV - Local Machine", "Azure Key Vault via your Azure AD browser login."),
    ("akv", "AKV - Stonebranch / Azure VM", "Azure Key Vault via managed identity."),
]
# Settings persisted between sessions (never passwords/secrets)
PERSISTED = ("environment", "cred_mode", "grant_type", "keyvault_name", "managed_identity_id",
             "tenant_id", "secret_username", "secret_password", "secret_client_id",
             "secret_client_secret", "output_path", "from_date", "to_date", "open_when_done")


class InventoryUI:
    def __init__(self, root):
        self.root = root
        root.title("UKG Integration Inventory")
        root.geometry("1100x800")
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._frames = None
        self._apply_fonts()
        self._init_vars()
        self._build_ui()
        self._load_settings()
        self._apply_env()
        self._auto_load_last_profile(clear=False)
        self._refresh_visibility()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._drain_queue)

    def _apply_fonts(self):
        """Use Verdana everywhere (named Tk fonts cover all ttk widgets, menus, dialogs)."""
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                     "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont",
                     "TkFixedFont"):
            tkfont.nametofont(name).configure(family=UI_FONT, size=UI_FONT_SIZE)
        style = ttk.Style()
        style.configure("Treeview", rowheight=int(UI_FONT_SIZE * 2.6))
        style.configure("Treeview.Heading", font=(UI_FONT, UI_FONT_SIZE, "bold"))
        style.configure("TNotebook.Tab", padding=(6, 3))

    # ------------------------------------------------------------------ vars
    def _init_vars(self):
        sv = tk.StringVar
        self.environment = sv(value="NPR1")
        self.cred_mode = sv(value="local")
        self.base_url = sv(value=ENV_PROFILES["NPR1"]["url"])
        self.grant_type = sv(value="password")
        self.token_endpoint = sv(value=TOKEN_ENDPOINT_DEFAULTS["password"])
        self.auth_base_url = sv()
        self.audience = sv(value="https://wfm.ukg.net/api")
        self.organization = sv()
        self.username = sv(value=os.environ.get("WFM_USERNAME", ""))
        self.password = sv(value=os.environ.get("WFM_PASSWORD", ""))
        self.client_id = sv(value=os.environ.get("WFM_CLIENT_ID", ""))
        self.client_secret = sv(value=os.environ.get("WFM_CLIENT_SECRET", ""))
        self.active_profile = sv()
        self.keyvault_name = sv(value="hwfd-dev-wu-kv-01")
        self.managed_identity_id = sv(value="ae15b0de-4039-4949-9f71-fb8ac389dba4")
        self.tenant_id = sv()
        self.secret_username = sv(value="npr1-wfm-pg-username")
        self.secret_password = sv(value="npr1-wfm-pg-password")
        self.secret_client_id = sv(value="npr1-wfm-pg-client-id")
        self.secret_client_secret = sv(value="npr1-wfm-pg-client-secret")
        self.ssl_verify = tk.BooleanVar(value=False)
        self.from_date = sv(value="2020-01-01")
        self.to_date = sv(value="2026-12-31")
        self.output_path = sv(value=os.path.join(os.path.expanduser("~"), "Documents",
                                                 "integration_inventory.xlsx"))
        self.open_when_done = tk.BooleanVar(value=True)
        self.status = sv(value="Idle")
        self.last_output = ""
        self.filter_text = sv()
        self.environment.trace_add("write", lambda *_: self._apply_env())
        self.grant_type.trace_add("write", lambda *_: self._on_grant_change())
        self.base_url.trace_add("write", lambda *_: self._on_url_change())
        # Credentials are per environment + grant type, so swap them when either changes
        self.environment.trace_add("write", lambda *_: self._auto_load_last_profile())
        self.grant_type.trace_add("write", lambda *_: self._auto_load_last_profile())

    # ------------------------------------------------------------------ layout
    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        t1, t2, t3 = (ttk.Frame(self.nb, padding=10) for _ in range(3))
        for t, title in ((t1, "  1 · Setup  "), (t2, "  2 · Run  "), (t3, "  3 · Results  ")):
            t.columnconfigure(0, weight=1)
            self.nb.add(t, text=title)
        self._build_setup(t1)
        self._build_run(t2)
        self._build_results(t3)

    def _entry(self, parent, row, label, var, show=None, readonly=False, width=None):
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        ent = ttk.Entry(parent, textvariable=var, show=show or "", width=width or 40,
                        state="readonly" if readonly else "normal")
        ent.grid(row=row, column=1, sticky="ew", pady=2)
        return lbl, ent

    def _combo(self, parent, row, label, var, values, width=40):
        lbl = ttk.Label(parent, text=label)
        lbl.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        cb = ttk.Combobox(parent, textvariable=var, values=values, width=width, state="readonly")
        cb.grid(row=row, column=1, sticky="w", pady=2)
        return lbl, cb

    def _masked_row(self, parent, row, label, var):
        lbl, ent = self._entry(parent, row, label, var, show="●")
        btn = ttk.Button(parent, text="Show", width=6)

        def toggle():
            hidden = ent.cget("show") == "●"
            ent.configure(show="" if hidden else "●")
            btn.configure(text="Hide" if hidden else "Show")
        btn.configure(command=toggle)
        btn.grid(row=row, column=2, padx=(4, 0))
        return lbl, ent, btn

    def _build_setup(self, p):
        r = 0
        ef = ttk.LabelFrame(p, text="Environment", padding=8)
        ef.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        ttk.Label(ef, text="Target Environment:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(ef, textvariable=self.environment, values=list(ENV_PROFILES),
                     width=10, state="readonly").grid(row=0, column=1, sticky="w")

        mf = ttk.LabelFrame(p, text="Credential Mode", padding=8)
        mf.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        for val, label, desc in CRED_MODES:
            row = ttk.Frame(mf)
            row.pack(anchor="w", pady=1)
            ttk.Radiobutton(row, text=label, value=val, variable=self.cred_mode,
                            command=self._refresh_visibility).pack(side="left")
            ttk.Label(row, text="- " + desc, foreground="#555555").pack(side="left", padx=(4, 0))

        cf = ttk.LabelFrame(p, text="Connection", padding=8)
        cf.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        cf.columnconfigure(1, weight=1)
        self._combo(cf, 0, "URL:", self.base_url, URLS)
        ttk.Label(cf, text="Grant Type:").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(cf, textvariable=self.grant_type, values=["password", "client_credentials"],
                     width=22, state="readonly").grid(row=1, column=1, sticky="w", pady=2)
        self._combo(cf, 2, "Token Endpoint:", self.token_endpoint, TOKEN_ENDPOINTS)
        self._cc_widgets = []
        self._cc_widgets.append(self._combo(cf, 3, "Auth Base URL:", self.auth_base_url, AUTH_BASE_URLS))
        self._cc_widgets.append(self._entry(cf, 4, "Audience:", self.audience))
        self._cc_widgets.append(self._entry(cf, 5, "Organization:", self.organization))

        # Local credentials
        self.local_frame = ttk.LabelFrame(p, text="Credentials - Local", padding=8)
        self.local_frame.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        lf = self.local_frame
        lf.columnconfigure(1, weight=1)
        ttk.Label(lf, textvariable=self.active_profile, foreground="#555555").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._pw_widgets = [self._entry(lf, 1, "Username:", self.username),
                            self._masked_row(lf, 2, "Password:", self.password)]
        self._entry(lf, 3, "Client ID:", self.client_id)
        self._masked_row(lf, 4, "Client Secret:", self.client_secret)
        bf = ttk.Frame(lf)
        bf.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(bf, text="Load from Environment", command=self._load_from_env).pack(side="left", padx=(0, 6))
        ttk.Button(bf, text="Load Profile…", command=self._load_profile).pack(side="left", padx=(0, 6))
        ttk.Button(bf, text="Save Profile…", command=self._save_profile).pack(side="left")

        # AKV
        self.akv_frame = ttk.LabelFrame(p, text="Credentials - Azure Key Vault", padding=8)
        self.akv_frame.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        af = self.akv_frame
        af.columnconfigure(1, weight=1)
        self._entry(af, 0, "Key Vault Name:", self.keyvault_name)
        self._mi_widgets = self._entry(af, 1, "Managed Identity Client ID:", self.managed_identity_id)
        self._tenant_widgets = self._entry(af, 2, "Tenant ID (optional):", self.tenant_id)
        self._akv_pw_widgets = [self._entry(af, 3, "Username Secret:", self.secret_username),
                                self._entry(af, 4, "Password Secret:", self.secret_password)]
        self._entry(af, 5, "Client ID Secret:", self.secret_client_id)
        self._entry(af, 6, "Client Secret Secret:", self.secret_client_secret)
        ttk.Checkbutton(af, text="Verify SSL certificate", variable=self.ssl_verify).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Test + save
        tf = ttk.LabelFrame(p, text="Test", padding=8)
        tf.grid(row=r, column=0, sticky="ew", pady=(0, 6)); r += 1
        self.conn_btn = ttk.Button(tf, text="▶  Test Connection", command=self._test_connection)
        self.conn_btn.pack(side="left")
        self.test_btn = ttk.Button(tf, text="▶  Test Token", command=self._test_token)
        self.test_btn.pack(side="left", padx=(6, 0))
        ttk.Button(tf, text="Save Settings", command=self._save_settings).pack(side="left", padx=(8, 0))
        self.test_status = ttk.Label(tf, text="Test Connection checks Key Vault access and secret names; "
                                              "Test Token generates a UKG access token.")
        self.test_status.pack(side="left", padx=(12, 0))
        ttk.Label(p, text="Passwords and secrets are never written to the settings file; "
                          "use Save Profile… to store them in Windows Credential Manager.",
                  foreground="#666666", font=(UI_FONT, UI_FONT_SIZE - 2)).grid(row=r, column=0, sticky="w")

    def _build_run(self, p):
        p.rowconfigure(2, weight=1)
        of = ttk.LabelFrame(p, text="Options", padding=8)
        of.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        of.columnconfigure(1, weight=1)
        self._entry(of, 0, "Schedules From (YYYY-MM-DD):", self.from_date, width=14)
        self._entry(of, 1, "Schedules To (YYYY-MM-DD):", self.to_date, width=14)
        ttk.Label(of, text="Output Excel File (base name):").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(of, textvariable=self.output_path).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(of, text="Browse…", command=self._browse_output).grid(row=2, column=2, padx=(4, 0))
        ttk.Label(of, text="A timestamp is added to the name on every run (e.g. integration_inventory_20261016_142530.xlsx), "
                           "so earlier results are never overwritten.",
                  foreground="#666666", font=(UI_FONT, UI_FONT_SIZE - 2)).grid(
            row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(of, text="Open file when done", variable=self.open_when_done).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        bar = ttk.Frame(p)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.run_btn = ttk.Button(bar, text="▶  Run", command=self._run)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="■  Stop", command=self._stop.set, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=(12, 0))
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=(10, 0))

        lf = ttk.Frame(p)
        lf.grid(row=2, column=0, sticky="nsew")
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)
        self.log = tk.Text(lf, wrap="none", height=10, font=(LOG_FONT, UI_FONT_SIZE - 1), state="disabled")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.log.tag_configure("err", foreground="#b00020")
        self.log.tag_configure("ok", foreground="#1b7f1b")

    def _build_results(self, p):
        p.rowconfigure(2, weight=1)
        self.summary_lbl = ttk.Label(p, text="No results yet - run the inventory first.")
        self.summary_lbl.grid(row=0, column=0, sticky="w")
        top = ttk.Frame(p)
        top.grid(row=1, column=0, sticky="ew", pady=6)
        ttk.Label(top, text="Filter:").pack(side="left")
        fe = ttk.Entry(top, textvariable=self.filter_text, width=30)
        fe.pack(side="left", padx=(4, 12))
        self.filter_text.trace_add("write", lambda *_: self._fill_tables())
        ttk.Button(top, text="Open Excel", command=self._open_file).pack(side="left")
        ttk.Button(top, text="Open Folder", command=self._open_folder).pack(side="left", padx=(6, 0))

        self.res_nb = ttk.Notebook(p)
        self.res_nb.grid(row=2, column=0, sticky="nsew")
        self.trees = {}
        for name in ("Integrations", "Parameters", "Schedules"):
            f = ttk.Frame(self.res_nb)
            f.rowconfigure(0, weight=1)
            f.columnconfigure(0, weight=1)
            tv = ttk.Treeview(f, show="headings")
            vs = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
            hs = ttk.Scrollbar(f, orient="horizontal", command=tv.xview)
            tv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            tv.grid(row=0, column=0, sticky="nsew")
            vs.grid(row=0, column=1, sticky="ns")
            hs.grid(row=1, column=0, sticky="ew")
            self.res_nb.add(f, text=name)
            self.trees[name] = tv

    # ------------------------------------------------------------------ setup behaviour
    def _apply_env(self):
        prof = ENV_PROFILES.get(self.environment.get())
        if not prof:
            return
        self.base_url.set(prof["url"])
        self.organization.set(prof["organization"])
        if self.grant_type.get() == "client_credentials":
            self.auth_base_url.set(AUTH_BASE_URL_CC[self.environment.get()])

    def _on_url_change(self):
        env = URL_TO_ENV.get(self.base_url.get())
        if env and env != self.environment.get():
            self.environment.set(env)

    def _on_grant_change(self):
        g = self.grant_type.get()
        self.token_endpoint.set(TOKEN_ENDPOINT_DEFAULTS[g])
        self.auth_base_url.set(AUTH_BASE_URL_CC.get(self.environment.get(), "")
                               if g == "client_credentials" else "")
        self._refresh_visibility()

    def _refresh_visibility(self):
        mode = self.cred_mode.get()
        cc = self.grant_type.get() == "client_credentials"
        for widgets in self._cc_widgets:
            for w in widgets:
                w.grid() if cc else w.grid_remove()
        for widgets in self._pw_widgets:
            for w in widgets:
                w.grid() if not cc else w.grid_remove()
        for widgets in self._akv_pw_widgets:
            for w in widgets:
                w.grid() if not cc else w.grid_remove()
        if mode == "local":
            self.local_frame.grid()
            self.akv_frame.grid_remove()
        else:
            self.akv_frame.grid()
            self.local_frame.grid_remove()
            for w in self._mi_widgets:
                w.grid() if mode == "akv" else w.grid_remove()
            for w in self._tenant_widgets:
                w.grid() if mode == "local_akv" else w.grid_remove()

    def _load_from_env(self):
        self.username.set(os.environ.get("WFM_USERNAME", ""))
        self.password.set(os.environ.get("WFM_PASSWORD", ""))
        self.client_id.set(os.environ.get("WFM_CLIENT_ID", ""))
        self.client_secret.set(os.environ.get("WFM_CLIENT_SECRET", ""))
        self.active_profile.set("Loaded from environment variables")

    def _cred_vars(self):
        v = {"WFM_CLIENT_ID": self.client_id, "WFM_CLIENT_SECRET": self.client_secret}
        if self.grant_type.get() != "client_credentials":
            v = {"WFM_USERNAME": self.username, "WFM_PASSWORD": self.password, **v}
        return v

    # -- profiles (same storage format as call_UKG_HWFD_jobs_v2_ui.py)
    def _read_profiles(self):
        try:
            with open(PROFILES_FILE) as f:
                return json.load(f)
        except Exception:
            return {"last_used": {}, "profiles": {}}

    def _apply_profile(self, name, data):
        targets = {"WFM_USERNAME": self.username, "WFM_PASSWORD": self.password,
                   "WFM_CLIENT_ID": self.client_id, "WFM_CLIENT_SECRET": self.client_secret}
        for v in targets.values():
            v.set("")
        for var in data.get("vars", []):
            val = keyring.get_password(KEYRING_SERVICE, "%s:%s" % (name, var))
            if val and var in targets:
                targets[var].set(val)
        self.active_profile.set("Active profile: %s" % name)

    def _auto_load_last_profile(self, clear=True):
        """Load the last-used (else first) profile for the current environment + grant type.
        With no matching profile the credential fields are cleared so values from the other
        grant type (different client ID/secret) are never reused by mistake."""
        if not _KEYRING_OK:
            return
        env, grant = self.environment.get(), self.grant_type.get()
        data = self._read_profiles()
        profiles = data.get("profiles", {})
        name = data.get("last_used", {}).get("%s:%s" % (env, grant))
        if name not in profiles:
            matching = sorted(n for n, m in profiles.items()
                              if m.get("env") == env and m.get("grant_type") == grant)
            name = matching[0] if matching else None
        if name:
            self._apply_profile(name, profiles[name])
        elif clear:
            for v in (self.username, self.password, self.client_id, self.client_secret):
                v.set("")
            self.active_profile.set("No saved profile for %s / %s" % (env, grant))

    def _need_keyring(self):
        if not _KEYRING_OK:
            messagebox.showerror("keyring not installed", "Run:  pip install keyring\nthen restart the UI.",
                                 parent=self.root)
        return _KEYRING_OK

    def _load_profile(self):
        if not self._need_keyring():
            return
        data = self._read_profiles()
        env, grant = self.environment.get(), self.grant_type.get()
        names = sorted(n for n, m in data.get("profiles", {}).items()
                       if m.get("env") == env and m.get("grant_type") == grant)
        if not names:
            messagebox.showinfo("No matching profiles",
                                "No saved profiles for %s / %s.\nUse 'Save Profile…' to create one." % (env, grant),
                                parent=self.root)
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Load Profile")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text="Select a credential profile:", padding=(12, 10, 12, 4)).pack(anchor="w")
        lb = tk.Listbox(dlg, width=50, height=min(len(names), 12), exportselection=False)
        lb.pack(padx=12, pady=(0, 8))
        for n in names:
            lb.insert("end", n)
        lb.selection_set(0)
        chosen = []

        def ok():
            if lb.curselection():
                chosen.append(names[lb.curselection()[0]])
                dlg.destroy()
        bf = ttk.Frame(dlg, padding=(12, 0, 12, 12))
        bf.pack(fill="x")
        ttk.Button(bf, text="Load", command=ok).pack(side="left", padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=dlg.destroy).pack(side="left")
        dlg.wait_window()
        if not chosen:
            return
        name = chosen[0]
        self._apply_profile(name, data["profiles"][name])
        data.setdefault("last_used", {})["%s:%s" % (env, grant)] = name
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(PROFILES_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _save_profile(self):
        if not self._need_keyring():
            return
        env, grant = self.environment.get(), self.grant_type.get()
        prefix = "%s_%s_" % (env.lower(), "password" if grant == "password" else "client")
        unique = simpledialog.askstring(
            "Save Profile", "Unique name for this credential set.\nSaved as:  %s<name>" % prefix,
            parent=self.root)
        if not unique or not unique.strip():
            return
        name = prefix + unique.strip().lower().replace(" ", "_")
        fields = {k: v.get() for k, v in self._cred_vars().items()}
        if not messagebox.askyesno("Confirm Save", "Save profile '%s' to Windows Credential Manager?" % name,
                                   parent=self.root):
            return
        for var, val in fields.items():
            keyring.set_password(KEYRING_SERVICE, "%s:%s" % (name, var), val)
        data = self._read_profiles()
        data.setdefault("profiles", {})[name] = {"env": env, "grant_type": grant, "vars": list(fields)}
        data.setdefault("last_used", {})["%s:%s" % (env, grant)] = name
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(PROFILES_FILE, "w") as f:
            json.dump(data, f, indent=2)
        self.active_profile.set("Active profile: %s" % name)

    # -- settings persistence
    def _save_settings(self):
        data = {k: (getattr(self, k).get()) for k in PERSISTED}
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        self.test_status.configure(text="Settings saved.", foreground="#1b7f1b")

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
        except Exception:
            return
        for k in PERSISTED:
            if k in data:
                getattr(self, k).set(data[k])

    # ------------------------------------------------------------------ client
    def _build_client(self):
        mode = self.cred_mode.get()
        creds = None
        if mode == "local":
            creds = {"username": self.username.get(), "password": self.password.get(),
                     "client_id": self.client_id.get(), "client_secret": self.client_secret.get()}
        return ukg_auth.UKGClient(
            base_url=self.base_url.get().strip(), mode=mode, grant_type=self.grant_type.get(),
            token_endpoint=self.token_endpoint.get().strip(),
            auth_base_url=self.auth_base_url.get().strip(),
            audience=self.audience.get().strip(), organization=self.organization.get().strip(),
            keyvault_name=self.keyvault_name.get().strip(),
            managed_identity_id=self.managed_identity_id.get().strip(),
            tenant_id=self.tenant_id.get().strip(),
            secret_username=self.secret_username.get().strip(),
            secret_password=self.secret_password.get().strip(),
            secret_client_id=self.secret_client_id.get().strip(),
            secret_client_secret=self.secret_client_secret.get().strip(),
            ssl_verify=self.ssl_verify.get(), credentials=creds)

    def _set_test_buttons(self, enabled):
        for b in (self.test_btn, self.conn_btn):
            b.configure(state="normal" if enabled else "disabled")

    def _test_connection(self):
        """AKV modes: sign in, open the vault and verify every configured secret exists.
        Local mode: verify the required credential fields are filled in."""
        if self.cred_mode.get() == "local":
            missing = [k for k, v in self._cred_vars().items() if not v.get().strip()]
            ok = not missing
            self.test_status.configure(
                text="All required credential fields are filled in." if ok
                else "Missing: " + ", ".join(missing),
                foreground="#1b7f1b" if ok else "#b00020")
            return
        self._set_test_buttons(False)
        self.test_status.configure(
            text="Connecting to Key Vault… (a browser login may open)", foreground="#666666")

        client, vault = self._build_client(), self.keyvault_name.get()

        def work():
            try:
                results = client.check_keyvault()
                ok = all(r[1] for r in results)
                lines = ["Key Vault: %s" % vault, ""] + [
                    "  %-40s %s" % (n, ("OK" if good else "FAILED - " + d)) for n, good, d in results]
                self._queue.put(("test", ok, "Key Vault reachable; all secrets found." if ok
                                 else "Key Vault reachable, but some secrets failed - see details.",
                                 "\n".join(lines)))
            except Exception as exc:
                self._queue.put(("test", False, "Connection failed: %s" % str(exc).splitlines()[0],
                                 "%s: %s" % (type(exc).__name__, exc)))
        threading.Thread(target=work, daemon=True).start()

    def _show_detail(self, title, text):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        t = tk.Text(dlg, width=90, height=min(18, text.count("\n") + 2), font=(UI_FONT, UI_FONT_SIZE - 1), wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(padx=10, pady=10, fill="both", expand=True)
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=(0, 10))

    def _test_token(self):
        self._set_test_buttons(False)
        self.test_status.configure(text="Authenticating…", foreground="#666666")

        client = self._build_client()

        def work():
            try:
                token = client.generate_access_token()
                self._queue.put(("test", True, "Token generated. Preview: %s…" % token[:20], None))
            except Exception as exc:
                self._queue.put(("test", False, "Token failed: %s" % str(exc).splitlines()[0], str(exc)))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ run
    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile=os.path.basename(self.output_path.get()),
            initialdir=os.path.dirname(self.output_path.get()) or None)
        if path:
            self.output_path.set(path)

    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _run(self):
        for label, val in (("From", self.from_date.get()), ("To", self.to_date.get())):
            try:
                datetime.datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid date", "%s date must be YYYY-MM-DD." % label, parent=self.root)
                return
        base = self.output_path.get().strip()
        if not base:
            messagebox.showerror("Missing output", "Choose an output Excel file.", parent=self.root)
            return
        out = integration_inventory.timestamped_path(base)
        self.last_output = out
        self._stop.clear()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start(12)
        self.status.set("Running…")
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        self.nb.select(1)
        from_d, to_d = self.from_date.get(), self.to_date.get()
        client = self._build_client()  # Tk variables must be read on the main thread
        self._log("Environment: %s (%s)" % (self.environment.get(), self.base_url.get()))

        def work():
            try:
                self._queue.put(("log", "Generating access token…", None))
                client.generate_access_token()
                self._queue.put(("log", "Token OK.", "ok"))
                frames = integration_inventory.collect_inventory(
                    client, from_d, to_d,
                    log=lambda m: self._queue.put(("log", m, None)),
                    should_stop=self._stop.is_set)
                if frames is None:
                    self._queue.put(("done", None, "Stopped."))
                    return
                os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
                integration_inventory.write_workbook(frames, out)
                self._queue.put(("log", "Wrote %s" % out, "ok"))
                self._queue.put(("done", frames, "Done."))
            except PermissionError:
                self._queue.put(("fail", "Cannot write %s - is it open in Excel?" % out))
            except Exception as exc:
                self._queue.put(("fail", "%s: %s" % (type(exc).__name__, exc)))
        threading.Thread(target=work, daemon=True).start()

    def _drain_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1], msg[2])
                elif kind == "test":
                    self._set_test_buttons(True)
                    self.test_status.configure(text=msg[2], foreground="#1b7f1b" if msg[1] else "#b00020")
                    if msg[3] and (not msg[1] or "secrets" in msg[2]):
                        self._show_detail("Test Result", msg[3])
                elif kind in ("done", "fail"):
                    self._finish(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _finish(self, msg):
        self.progress.stop()
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if msg[0] == "fail":
            self.status.set("Failed")
            self._log("*** ERROR: " + msg[1], "err")
            return
        self.status.set(msg[2])
        self._log(msg[2], "ok" if msg[1] is not None else None)
        if msg[1] is None:
            return
        self._frames = msg[1]
        self._fill_tables()
        self.nb.select(2)
        if self.open_when_done.get():
            self._open_file()

    # ------------------------------------------------------------------ results
    def _fill_tables(self):
        if not self._frames:
            return
        needle = self.filter_text.get().strip().lower()
        counts = []
        for name, tv in self.trees.items():
            df = self._frames[name]
            tv.delete(*tv.get_children())
            tv["columns"] = list(df.columns)
            for c in df.columns:
                tv.heading(c, text=c)
                tv.column(c, width=max(80, min(len(c) * 9, 220)), stretch=False)
            shown = 0
            for row in df.itertuples(index=False):
                vals = ["" if v is None or v != v else str(v) for v in row]
                if needle and not any(needle in v.lower() for v in vals):
                    continue
                tv.insert("", "end", values=vals)
                shown += 1
            counts.append("%s: %d" % (name, len(df)))
        self.summary_lbl.configure(text="   ".join(counts) + "     →  " + self.last_output)

    def _open_file(self):
        path = self.last_output
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("Not found", "No output file yet - run the inventory first.", parent=self.root)

    def _open_folder(self):
        folder = os.path.dirname(os.path.abspath(self.last_output or self.output_path.get()))
        if os.path.isdir(folder):
            subprocess.Popen(["explorer", folder])

    def _on_close(self):
        self._stop.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    InventoryUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
