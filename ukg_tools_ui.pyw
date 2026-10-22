"""
ukg_tools_ui.pyw — Launcher UI for UKG Tools

Double-click this file to launch (no console window, no server needed).

Covers:
  • Audit Report Tool — run the audit report with configurable dates and format
  • UKG API Tool      — execute any UKG API endpoint defined in input/ukg_request.json
  • Same Env, Diff FAPs — compare Function Access Profiles side by side
  • Same FAP, Diff Envs — compare one FAP between two environments (e.g. NPR1 vs UAT)

All tools share one Connection panel at the top: pick the environment (NPR1 / UAT / PRD),
grant type and credential profile once. Profiles can be created, updated and deleted from the
panel itself (secrets are stored in Windows Credential Manager).
"""

import os
import sys
import queue
import threading
import copy
import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime, timedelta

import urllib3

sys.path.insert(0, str(Path(__file__).parent))

import audit_report_tool as _art
import ukg_api_tool as _uat
import fap_tool as _fap
import ukg_env as _env
import ukg_conn_dialogs as _dlg


BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
INPUT_DIR  = BASE_DIR / 'input'
OUTPUT_DIR = BASE_DIR / 'output'

# Last-used connection choices (never secrets) — remembered between sessions
UI_SETTINGS_FILE = Path(_env.CONFIG_DIR) / 'ukg_tools_ui.json'


# ---------------------------------------------------------------------------
# Stdout/stderr redirector → thread-safe queue
# ---------------------------------------------------------------------------

class _QueueWriter:
    """Captures print() and logging output from any thread and feeds it to the UI queue."""
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text):
        if text:
            self._q.put(text)

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class UKGToolsUI(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('UKG Tools')
        self.minsize(820, 640)
        self.resizable(True, True)

        # Redirect stdout/stderr so all print() / logging output flows to the UI
        self._out_q = queue.Queue()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _QueueWriter(self._out_q)
        sys.stderr = _QueueWriter(self._out_q)

        self._busy      = False
        self._active_txt = None   # output area for the currently-running tool

        self._apply_theme()
        self._build_ui()
        self._fit_to_screen()
        self.after(100, self._poll_output)

    def _fit_to_screen(self):
        """Open centred, as large as the content needs but never bigger than the screen."""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(max(self.winfo_reqwidth(), self.winfo_width()), sw - 40)
        h = min(max(self.winfo_reqheight(), self.winfo_height()), sh - 100)   # room for the taskbar
        self.minsize(min(self.minsize()[0], w), min(self.minsize()[1], h))
        self.geometry(f'{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 2 - 20, 0)}')

    # ── Theme ─────────────────────────────────────────────────────────────

    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use('vista')
        base = ('Verdana', 10)
        bold = ('Verdana', 10, 'bold')
        for widget in ('TLabel', 'TButton', 'TCheckbutton', 'TRadiobutton',
                       'TEntry', 'TCombobox', 'TSpinbox', 'TLabelframe.Label',
                       'TNotebook.Tab'):
            style.configure(widget, font=base)
        style.configure('TLabelframe.Label', font=bold)
        self.option_add('*Font', base)
        # Named Tk fonts cover dialogs, message boxes and combobox drop-downs
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont',
                     'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
            tkfont.nametofont(name).configure(family='Verdana', size=10)
        tkfont.nametofont('TkFixedFont').configure(family='Courier New', size=9)
        self.option_add('*TCombobox*Listbox.font', base)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        self._build_connection_panel()

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill='both', expand=True, padx=8, pady=8)

        tab_audit = ttk.Frame(self._nb)
        tab_api   = ttk.Frame(self._nb)
        tab_fap   = ttk.Frame(self._nb)
        tab_fapenv = ttk.Frame(self._nb)
        self._nb.add(tab_audit, text='  Audit Report  ')
        self._nb.add(tab_api,   text='  UKG API Tool  ')
        self._nb.add(tab_fap,   text='  Same Env, Diff FAPs  ')
        self._nb.add(tab_fapenv, text='  Same FAP, Diff Envs  ')

        self._build_audit_tab(tab_audit)
        self._build_api_tab(tab_api)
        self._build_fap_tab(tab_fap)
        self._build_fapenv_tab(tab_fapenv)
        # Output area of each tab, in notebook order (for connection-panel messages)
        self._tab_txts = [self._audit_txt, self._api_txt, self._fap_txt, self._fapenv_txt]

        self._status = tk.StringVar(value='Ready')
        ttk.Label(self, textvariable=self._status, anchor='w',
                  relief='sunken').pack(fill='x', padx=8, pady=(0, 6))

    # =========================================================================
    # Connection panel — shared by every tab
    # =========================================================================

    def _build_connection_panel(self):
        saved = {}
        try:
            saved = json.loads(UI_SETTINGS_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        pick = lambda key, allowed, default: saved.get(key) if saved.get(key) in allowed else default

        self._conn_env   = tk.StringVar(value=pick('environment', _env.ENVIRONMENTS, 'NPR1'))
        self._conn_grant = tk.StringVar(value=pick('grant_type', _env.GRANT_TYPES, 'client_credentials'))
        self._conn_mode  = tk.StringVar(value='local')   # saved profiles only; Key Vault modes are not offered here
        self._conn_prof  = tk.StringVar()
        self._conn_no_ssl = tk.BooleanVar(value=saved.get('skip_ssl', True))

        frm = ttk.LabelFrame(self, text='Connection  (used by all tools)')
        frm.pack(fill='x', padx=8, pady=(8, 0))

        row1 = ttk.Frame(frm)
        row1.pack(fill='x', padx=6, pady=(6, 2))
        ttk.Label(row1, text='Environment:').pack(side='left', padx=(0, 4))
        ttk.Combobox(row1, textvariable=self._conn_env, values=_env.ENVIRONMENTS,
                     width=7, state='readonly').pack(side='left', padx=(0, 16))
        ttk.Label(row1, text='Grant type:').pack(side='left', padx=(0, 4))
        ttk.Combobox(row1, textvariable=self._conn_grant, values=list(_env.GRANT_TYPES),
                     width=18, state='readonly').pack(side='left', padx=(0, 16))
        row2 = ttk.Frame(frm)
        row2.pack(fill='x', padx=6, pady=(2, 2))
        ttk.Label(row2, text='Profile:').pack(side='left', padx=(0, 4))
        self._conn_prof_cb = ttk.Combobox(row2, textvariable=self._conn_prof,
                                          width=34, state='readonly')
        self._conn_prof_cb.pack(side='left', padx=(0, 8))
        self._conn_btn_save = ttk.Button(row2, text='Save / Update Profile…',
                                         command=self._profile_dialog)
        self._conn_btn_save.pack(side='left', padx=2)
        self._conn_btn_del = ttk.Button(row2, text='Delete', width=8,
                                        command=self._delete_profile)
        self._conn_btn_del.pack(side='left', padx=2)
        self._conn_btn_test = ttk.Button(row2, text='Test Connection', command=self._on_test_connection)
        self._conn_btn_test.pack(side='left', padx=(12, 2))

        row3 = ttk.Frame(frm)
        row3.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Checkbutton(row3, text='Skip SSL verification (required on corporate network)',
                        variable=self._conn_no_ssl).pack(side='left')
        self._conn_warn = ttk.Label(row3, text='', foreground='#cc0000',
                                    font=('Verdana', 10, 'bold'))
        self._conn_warn.pack(side='left', padx=(24, 0))

        for var in (self._conn_env, self._conn_grant, self._conn_mode):
            var.trace_add('write', lambda *_: self._on_connection_change())
        self._conn_no_ssl.trace_add('write', lambda *_: self._save_ui_settings())
        self._conn_prof.trace_add('write', lambda *_: self._save_ui_settings())
        self._on_connection_change()

    def _update_ui_settings(self, **values):
        """Merge values into the remembered-settings file (never secrets)."""
        try:
            try:
                saved = json.loads(UI_SETTINGS_FILE.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                saved = {}
            saved.update(values)
            UI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            UI_SETTINGS_FILE.write_text(json.dumps(saved, indent=2), encoding='utf-8')
        except OSError:
            pass   # remembering the last choice is a convenience only

    def _save_ui_settings(self):
        self._update_ui_settings(
            environment=self._conn_env.get(), grant_type=self._conn_grant.get(),
            cred_mode=self._conn_mode.get(), skip_ssl=self._conn_no_ssl.get())

    def _on_connection_change(self):
        """Environment / grant type / mode changed: refresh the profile list and the PRD warning."""
        env, grant = self._conn_env.get(), self._conn_grant.get()
        names = _env.list_profiles(env, grant)
        self._conn_prof_cb.configure(values=names)
        self._conn_prof.set(_env.default_profile(env, grant) or '')
        local = self._conn_mode.get() == 'local'
        self._conn_prof_cb.configure(state='readonly' if local and names else 'disabled')
        for btn in (self._conn_btn_save, self._conn_btn_del):
            btn.configure(state='normal' if local else 'disabled')
        self._conn_warn.configure(text='⚠ PRODUCTION' if env == 'PRD' else '')
        self._save_ui_settings()

    def _apply_ssl(self, ssl_verify: bool):
        """Make the tools' own requests (report/API calls) follow the panel's SSL setting."""
        for mod in (_art, _uat):
            mod.SSL_VERIFY = ssl_verify
        if not ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _build_client(self):
        """UKGClient for the panel's current selection; shows an error and returns None on failure.
        Must be called on the main thread (reads Tk variables)."""
        return self._make_client(self._conn_env.get(), self._conn_prof.get())

    def _make_client(self, env: str, profile: str):
        """Client for env + profile, with grant type / credentials mode / SSL from the panel."""
        grant, mode = self._conn_grant.get(), self._conn_mode.get()
        profile = (profile or None) if mode == 'local' else None
        if mode == 'local' and not profile and not os.environ.get('WFM_CLIENT_ID'):
            messagebox.showerror(
                'No Credential Profile',
                f'There is no saved profile for {env} / {grant}.\n\n'
                'Click "Save / Update Profile…" in the Connection panel to create one.')
            return None
        ssl_verify = not self._conn_no_ssl.get()
        try:
            client = _env.build_client(env, grant, mode, profile, ssl_verify)
        except Exception as exc:
            messagebox.showerror('Connection Error', str(exc))
            return None
        self._apply_ssl(ssl_verify)
        return client

    def _current_txt(self) -> tk.Text:
        return self._tab_txts[self._nb.index('current')]

    def _on_test_connection(self):
        if self._busy:
            return
        client = self._build_client()
        if client is None:
            return
        self._active_txt = self._current_txt()
        self._set_busy(True, 'Testing connection...')

        def _work():
            try:
                print('\n'.join(_env.describe(client, client.grant_type)))
                print('Requesting token ...')
                token = client.generate_access_token()
                print(f'Token generated - authenticated OK ({token[:12]}...)')
                if client.profile_name:
                    _env.remember_profile(client.env, client.grant_type, client.profile_name)
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    # ── Profile management ────────────────────────────────────────────────

    def _profile_dialog(self):
        """Create a new profile or update an existing one for the selected environment + grant type."""
        saved = _dlg.profile_dialog(self, self._conn_env.get(), self._conn_grant.get(),
                                    self._conn_prof.get())
        if saved:
            self._on_connection_change()
            self._conn_prof.set(saved)

    def _delete_profile(self):
        if _dlg.delete_profile(self, self._conn_prof.get()):
            self._on_connection_change()

    # =========================================================================
    # TAB 1 — Audit Report
    # =========================================================================

    def _build_audit_tab(self, parent):
        pad = dict(padx=8, pady=4)

        # Parameters
        frm_params = ttk.LabelFrame(parent, text='Report Parameters')
        frm_params.pack(fill='x', **pad)

        today    = datetime.now()
        week_ago = today - timedelta(days=7)

        row1 = ttk.Frame(frm_params)
        row1.pack(fill='x', padx=6, pady=6)

        ttk.Label(row1, text='Start Date:').pack(side='left', padx=(0, 4))
        self._audit_start = tk.StringVar(value=week_ago.strftime('%Y-%m-%d'))
        ttk.Entry(row1, textvariable=self._audit_start, width=14).pack(side='left', padx=(0, 16))

        ttk.Label(row1, text='End Date:').pack(side='left', padx=(0, 4))
        self._audit_end = tk.StringVar(value=today.strftime('%Y-%m-%d'))
        ttk.Entry(row1, textvariable=self._audit_end, width=14).pack(side='left', padx=(0, 16))

        ttk.Label(row1, text='(YYYY-MM-DD)', foreground='gray').pack(side='left')

        row2 = ttk.Frame(frm_params)
        row2.pack(fill='x', padx=6, pady=(0, 6))

        ttk.Label(row2, text='Output Format:').pack(side='left', padx=(0, 8))
        self._audit_fmt = tk.StringVar(value='xlsx')
        ttk.Radiobutton(row2, text='XLSX', variable=self._audit_fmt, value='xlsx').pack(side='left', padx=4)
        ttk.Radiobutton(row2, text='PDF',  variable=self._audit_fmt, value='pdf').pack(side='left', padx=4)

        # Audit types: a list of remembered choices; the highlighted ones are sent
        saved = {}
        try:
            saved = json.loads(UI_SETTINGS_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        if saved.get('audit_types_v') != 2:
            # Earlier versions upper-cased what was typed (INTEGRATION_INSTANCES); keys are now kept as typed
            fix = lambda k: k.replace('_', ' ').title() if k.isupper() else k
            saved['audit_types'] = [fix(k) for k in saved.get('audit_types', [])]
            saved['audit_types_selected'] = [fix(k) for k in saved.get('audit_types_selected', [])]
            self._update_ui_settings(audit_types=saved['audit_types'],
                                     audit_types_selected=saved['audit_types_selected'],
                                     audit_types_v=2)
        self._audit_choices = []
        for key in ['Integration', *saved.get('audit_types', [])]:
            if key.lower() not in (c.lower() for c in self._audit_choices):
                self._audit_choices.append(key)
        wanted = [k.lower() for k in (saved.get('audit_types_selected') or ['Integration'])]
        chosen = [c for c in self._audit_choices if c.lower() in wanted]

        row3 = ttk.Frame(frm_params)
        row3.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Label(row3, text='Audit Types:').pack(side='left', anchor='n', padx=(0, 8))
        self._audit_types_lb = tk.Listbox(row3, height=3, width=28, selectmode='multiple',
                                          exportselection=False, activestyle='none')
        self._audit_types_lb.pack(side='left', anchor='n')
        for key in self._audit_choices:
            self._audit_types_lb.insert('end', key)
            if key in chosen:
                self._audit_types_lb.selection_set('end')
        side = ttk.Frame(row3)
        side.pack(side='left', anchor='n', padx=10)
        self._audit_type_new = tk.StringVar()
        add_row = ttk.Frame(side)
        add_row.pack(anchor='w')
        ttk.Entry(add_row, textvariable=self._audit_type_new, width=22).pack(side='left')
        ttk.Button(add_row, text='Add', width=8, command=self._add_audit_type).pack(side='left', padx=(6, 2))
        ttk.Button(add_row, text='Remove', width=8, command=self._remove_audit_type).pack(side='left', padx=2)
        ttk.Label(side, text='Highlighted types are sent. Type a key exactly as UKG expects it (e.g. Integration Instances) and click Add.',
                  foreground='gray').pack(anchor='w', pady=(4, 0))

        # Optional filters (blank for most runs)
        row4 = ttk.Frame(frm_params)
        row4.pack(fill='x', padx=6, pady=(0, 6))
        self._audit_user = tk.StringVar()
        self._audit_user_ids = tk.StringVar()
        ttk.Label(row4, text='User:').pack(side='left', padx=(0, 4))
        ttk.Entry(row4, textvariable=self._audit_user, width=18).pack(side='left', padx=(0, 16))
        ttk.Label(row4, text='Audit User IDs:').pack(side='left', padx=(0, 4))
        ttk.Entry(row4, textvariable=self._audit_user_ids, width=22).pack(side='left', padx=(0, 16))
        ttk.Label(row4, text='(optional - leave blank unless needed)', foreground='gray').pack(side='left')

        # Payload preview: exactly what will be sent
        frm_payload = ttk.LabelFrame(parent, text='Report Payload  (built from the fields above)')
        frm_payload.pack(fill='x', **pad)

        payload_inner = ttk.Frame(frm_payload)
        payload_inner.pack(fill='x', padx=6, pady=6)

        self._audit_payload_txt = tk.Text(
            payload_inner, wrap='none', height=4,
            font=('Courier New', 9),
            bg='#f5f5f5', fg='#1a1a1a',
            relief='flat', state='disabled',
        )
        payload_scroll_y = ttk.Scrollbar(payload_inner, command=self._audit_payload_txt.yview)
        payload_scroll_x = ttk.Scrollbar(payload_inner, orient='horizontal',
                                         command=self._audit_payload_txt.xview)
        self._audit_payload_txt.configure(yscrollcommand=payload_scroll_y.set,
                                          xscrollcommand=payload_scroll_x.set)
        payload_scroll_y.pack(side='right', fill='y')
        payload_scroll_x.pack(side='bottom', fill='x')
        self._audit_payload_txt.pack(fill='x')

        for var in (self._audit_start, self._audit_end, self._audit_fmt,
                    self._audit_user, self._audit_user_ids):
            var.trace_add('write', lambda *_: self._reload_audit_payload())
        self._audit_types_lb.bind('<<ListboxSelect>>', lambda _e: self._on_audit_types_changed())
        self._reload_audit_payload()

        # Actions
        frm_act = ttk.LabelFrame(parent, text='Actions')
        frm_act.pack(fill='x', **pad)

        btn_row = ttk.Frame(frm_act)
        btn_row.pack(fill='x', padx=6, pady=8)

        self._audit_btn_run = ttk.Button(btn_row, text='Run', width=14,
                                          command=self._on_audit_run)

        self._audit_btn_dry = ttk.Button(btn_row, text='Dry Run', width=14,
                                          command=self._on_audit_dry)
        self._audit_btn_dry.pack(side='left', padx=4)
        self._audit_btn_run.pack(side='left', padx=4)
        self._audit_email = tk.BooleanVar(value=False)
        ttk.Checkbutton(btn_row, text='Send email after download',
                        variable=self._audit_email).pack(side='left', padx=(24, 0))

        # Output
        self._audit_txt = self._make_output_area(parent, pad)

    def _on_audit_run(self):
        self._run_audit(dry_run=False)

    def _on_audit_dry(self):
        self._run_audit(dry_run=True)

    def _run_audit(self, dry_run: bool):
        if self._busy:
            return
        start  = self._audit_start.get().strip()
        end    = self._audit_end.get().strip()
        fmt    = self._audit_fmt.get()
        email  = self._audit_email.get()

        try:
            datetime.strptime(start, '%Y-%m-%d')
            datetime.strptime(end,   '%Y-%m-%d')
        except ValueError:
            messagebox.showerror('Invalid Date', 'Dates must be in YYYY-MM-DD format.\nExample: 2026-08-01')
            return

        if not self._selected_audit_types():
            messagebox.showerror('Audit Types', 'Highlight at least one audit type (or add one).')
            return
        client = self._build_client()
        if client is None:
            return
        payload = self._build_audit_payload()

        self._active_txt = self._audit_txt
        label = 'Running dry run...' if dry_run else 'Running audit report...'
        self._set_busy(True, label)

        def _work():
            try:
                # Reset logger handlers to avoid duplicates on repeated runs
                for h in list(_art.logger.handlers):
                    _art.logger.removeHandler(h)

                _art.run(
                    payload       = payload,
                    output_dir    = OUTPUT_DIR,
                    client        = client,
                    poll_interval = 5,
                    timeout       = 600,
                    dry_run       = dry_run,
                    email         = email,
                )
            except SystemExit:
                pass
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    # =========================================================================
    # TAB 2 — UKG API Tool
    # =========================================================================

    def _build_api_tab(self, parent):
        pad = dict(padx=8, pady=4)

        # Request form
        frm_cfg = ttk.LabelFrame(parent, text='Request  (saved to input/ukg_request.json on Run)')
        frm_cfg.pack(fill='x', **pad)

        top = ttk.Frame(frm_cfg)
        top.pack(fill='x', padx=6, pady=(6, 2))
        self._api_method = tk.StringVar(value='GET')
        self._api_endpoint = tk.StringVar()
        ttk.Label(top, text='Method:').pack(side='left', padx=(0, 4))
        ttk.Combobox(top, textvariable=self._api_method, width=8, state='readonly',
                     values=list(_uat.BODY_METHODS) + ['GET', 'DELETE']).pack(side='left', padx=(0, 16))
        ttk.Label(top, text='Endpoint:').pack(side='left', padx=(0, 4))
        ttk.Entry(top, textvariable=self._api_endpoint).pack(side='left', fill='x', expand=True)

        ttk.Label(frm_cfg, text='Payload (JSON request body):').pack(anchor='w', padx=10, pady=(4, 0))
        cfg_inner = ttk.Frame(frm_cfg)
        cfg_inner.pack(fill='x', padx=6, pady=(2, 6))

        self._api_cfg_txt = tk.Text(
            cfg_inner, wrap='none', height=8, undo=True,
            font=('Courier New', 9), bg='#ffffff', fg='#1a1a1a',
            relief='solid', borderwidth=1,
        )
        cfg_scroll_y = ttk.Scrollbar(cfg_inner, command=self._api_cfg_txt.yview)
        cfg_scroll_x = ttk.Scrollbar(cfg_inner, orient='horizontal',
                                      command=self._api_cfg_txt.xview)
        self._api_cfg_txt.configure(yscrollcommand=cfg_scroll_y.set,
                                     xscrollcommand=cfg_scroll_x.set)
        cfg_scroll_y.pack(side='right', fill='y')
        cfg_scroll_x.pack(side='bottom', fill='x')
        self._api_cfg_txt.pack(fill='x')

        reload_row = ttk.Frame(frm_cfg)
        reload_row.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Button(reload_row, text='↻ Reload',
                   command=self._reload_api_config).pack(side='left', padx=4)
        ttk.Button(reload_row, text='Edit File',
                   command=self._open_api_config).pack(side='left', padx=4)
        ttk.Button(reload_row, text='Format JSON',
                   command=self._format_api_payload).pack(side='left', padx=4)
        self._api_hint = ttk.Label(reload_row, text='', foreground='gray')
        self._api_hint.pack(side='left', padx=8)

        self._api_method.trace_add('write', lambda *_: self._on_api_method_change())
        self._reload_api_config()

        # Actions
        frm_act = ttk.LabelFrame(parent, text='Actions')
        frm_act.pack(fill='x', **pad)

        btn_row = ttk.Frame(frm_act)
        btn_row.pack(fill='x', padx=6, pady=8)

        self._api_btn_run = ttk.Button(btn_row, text='Run', width=14,
                                        command=self._on_api_run)

        self._api_btn_dry = ttk.Button(btn_row, text='Dry Run', width=14,
                                        command=self._on_api_dry)
        self._api_btn_dry.pack(side='left', padx=4)
        self._api_btn_run.pack(side='left', padx=4)

        # Output
        self._api_txt = self._make_output_area(parent, pad)

    @staticmethod
    def _show_json_file(txt: tk.Text, path: Path):
        """Pretty-print a JSON file into a read-only preview box; show the problem if it can't be read."""
        txt.configure(state='normal')
        txt.delete('1.0', 'end')
        label = f'input/{path.name}'
        if not path.exists():
            txt.insert('end', f'({label} not found)')
        else:
            try:
                with open(path, encoding='utf-8') as f:
                    txt.insert('end', json.dumps(json.load(f), indent=2))
            except (OSError, ValueError) as exc:
                txt.insert('end', f'({label} could not be read: {exc})')
        txt.configure(state='disabled')

    def _selected_audit_types(self) -> list[str]:
        return [self._audit_types_lb.get(i) for i in self._audit_types_lb.curselection()]

    def _build_audit_payload(self) -> dict:
        """The AuditReport request body, built from the form."""
        params = [
            {'name': 'Audit Types', 'value': [{'key': k} for k in self._selected_audit_types()]},
            {'name': 'DateRange', 'value': {'startDate': self._audit_start.get().strip(),
                                            'endDate':   self._audit_end.get().strip()}},
            {'name': 'Output Format', 'value': {'key': self._audit_fmt.get()}},
        ]
        # Optional filters: always present, blank ("") when not filled in
        params.append({'name': 'user', 'value': self._audit_user.get().strip()})
        params.append({'name': 'auditUserIds', 'value': self._audit_user_ids.get().strip()})
        return {'parameters': params}

    def _reload_audit_payload(self):
        """Refresh the preview from the form."""
        txt = self._audit_payload_txt
        txt.configure(state='normal')
        txt.delete('1.0', 'end')
        txt.insert('end', json.dumps(self._build_audit_payload(), indent=2))
        txt.configure(state='disabled')

    def _on_audit_types_changed(self):
        self._update_ui_settings(audit_types=self._audit_choices,
                                 audit_types_selected=self._selected_audit_types())
        self._reload_audit_payload()

    def _add_audit_type(self):
        key = ' '.join(self._audit_type_new.get().split())
        if not key:
            return
        existing = [c for c in self._audit_choices if c.lower() == key.lower()]
        if existing:
            key = existing[0]
        else:
            self._audit_choices.append(key)
            self._audit_types_lb.insert('end', key)
        idx = self._audit_choices.index(key)
        self._audit_types_lb.selection_set(idx)
        self._audit_types_lb.see(idx)
        self._audit_type_new.set('')
        self._on_audit_types_changed()

    def _remove_audit_type(self):
        for i in reversed(self._audit_types_lb.curselection()):
            self._audit_types_lb.delete(i)
            del self._audit_choices[i]
        self._on_audit_types_changed()

    def _on_api_method_change(self):
        """The body is only sent for POST / PUT / PATCH; grey it out otherwise."""
        sends_body = self._api_method.get() in _uat.BODY_METHODS
        self._api_cfg_txt.configure(state='normal' if sends_body else 'disabled',
                                    bg='#ffffff' if sends_body else '#ececec')
        self._api_hint.configure(
            text='' if sends_body else f'{self._api_method.get()} sends no body; the payload is ignored.')

    def _reload_api_config(self):
        """Fill the form from input/ukg_request.json."""
        cfg_file = INPUT_DIR / 'ukg_request.json'
        cfg = {}
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                messagebox.showerror('Request File', f'input/ukg_request.json could not be read:\n{exc}')
        self._api_headers = cfg.get('headers') or {}     # not shown; kept when the file is saved
        method = str(cfg.get('method', 'GET')).upper()
        self._api_method.set(method if method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') else 'GET')
        self._api_endpoint.set(cfg.get('endpoint', ''))
        self._api_cfg_txt.configure(state='normal')
        self._api_cfg_txt.delete('1.0', 'end')
        if cfg.get('payload') is not None:
            self._api_cfg_txt.insert('end', json.dumps(cfg['payload'], indent=2))
        self._on_api_method_change()

    def _format_api_payload(self):
        if self._api_cfg_txt.cget('state') == 'disabled':
            return
        text = self._api_cfg_txt.get('1.0', 'end').strip()
        if not text:
            return
        try:
            pretty = json.dumps(json.loads(text), indent=2)
        except ValueError as exc:
            messagebox.showerror('Invalid JSON', f'The payload is not valid JSON:\n{exc}')
            return
        self._api_cfg_txt.delete('1.0', 'end')
        self._api_cfg_txt.insert('end', pretty)

    def _save_api_request(self):
        """Validate the form and write input/ukg_request.json. Returns its path, or None after an error."""
        method, endpoint = self._api_method.get(), self._api_endpoint.get().strip()
        if not endpoint.startswith('/'):
            messagebox.showerror('Endpoint', 'Enter the endpoint path, starting with "/"\n'
                                 'e.g. /api/v1/commons/function_access_profiles?name=ACI%20CDX%20Access')
            return None
        text = self._api_cfg_txt.get('1.0', 'end').strip()
        payload = None
        if text:
            try:
                payload = json.loads(text)
            except ValueError as exc:
                if method in _uat.BODY_METHODS:
                    messagebox.showerror('Invalid JSON', f'The payload is not valid JSON:\n{exc}')
                    return None
        path = INPUT_DIR / 'ukg_request.json'
        try:
            INPUT_DIR.mkdir(exist_ok=True)
            path.write_text(json.dumps({'method': method, 'endpoint': endpoint,
                                        'headers': getattr(self, '_api_headers', {}),
                                        'payload': payload}, indent=2), encoding='utf-8')
        except OSError as exc:
            messagebox.showerror('Request File', f'Could not save input/ukg_request.json:\n{exc}')
            return None
        return path

    def _open_api_config(self):
        """Save the form, then open the file in the default editor (Reload afterwards)."""
        import os
        path = self._save_api_request()
        if path is not None:
            os.startfile(path)

    def _on_api_run(self):
        self._run_api(dry_run=False)

    def _on_api_dry(self):
        self._run_api(dry_run=True)

    def _run_api(self, dry_run: bool):
        if self._busy:
            return
        client = self._build_client()
        if client is None:
            return
        cfg_path = self._save_api_request()
        if cfg_path is None:
            return
        method = self._api_method.get()
        if not dry_run and method != 'GET':
            env = self._conn_env.get()
            warn = '\n\n⚠ THIS IS PRODUCTION.' if env == 'PRD' else ''
            if not messagebox.askyesno(
                    'Confirm Request',
                    f'Send {method} to {env}?\n\n{self._api_endpoint.get().strip()}{warn}',
                    icon='warning'):
                return

        self._active_txt = self._api_txt
        label = 'Running dry run...' if dry_run else 'Running API request...'
        self._set_busy(True, label)

        def _work():
            try:
                for h in list(_uat.logger.handlers):
                    _uat.logger.removeHandler(h)

                _uat.run(
                    config_file = str(cfg_path),
                    output_dir  = OUTPUT_DIR,
                    client      = client,
                    dry_run     = dry_run,
                )
            except SystemExit:
                pass
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    # =========================================================================
    # TAB 3 — Same Env, Diff FAPs
    # =========================================================================

    def _build_fap_tab(self, parent):
        pad = dict(padx=8, pady=4)

        frm_names = ttk.LabelFrame(parent, text='Function Access Profiles  (one name per line)')
        frm_names.pack(fill='x', **pad)

        names_inner = ttk.Frame(frm_names)
        names_inner.pack(fill='x', padx=6, pady=6)
        self._fap_names_txt = tk.Text(names_inner, wrap='none', height=7,
                                      font=('Verdana', 10), relief='solid', borderwidth=1)
        names_scroll = ttk.Scrollbar(names_inner, command=self._fap_names_txt.yview)
        self._fap_names_txt.configure(yscrollcommand=names_scroll.set)
        names_scroll.pack(side='right', fill='y')
        self._fap_names_txt.pack(fill='x')
        names = _fap.load_names(None, None)
        self._fap_names_txt.insert('end', '\n'.join(names))

        hint_row = ttk.Frame(frm_names)
        hint_row.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Label(hint_row, text='Example: ACI CDX Access   (names are saved to input/fap_tool/fap_names.txt on Run)',
                  foreground='gray').pack(side='left', padx=4)

        # Pair comparisons — extra tabs in the comparison workbook
        frm_pairs = ttk.LabelFrame(parent, text='Pair comparisons  (optional extra tabs in the comparison file)')
        frm_pairs.pack(fill='x', **pad)

        self._fap_all_pairs = tk.BooleanVar(value=False)
        self._fap_use_base  = tk.BooleanVar(value=False)
        self._fap_base      = tk.StringVar()
        self._fap_pair_a    = tk.StringVar()
        self._fap_pair_b    = tk.StringVar()
        self._fap_pairs: list[tuple[str, str]] = []

        row_a = ttk.Frame(frm_pairs)
        row_a.pack(fill='x', padx=6, pady=(6, 2))
        ttk.Checkbutton(row_a, text='All pairs', variable=self._fap_all_pairs).pack(side='left', padx=(4, 24))
        ttk.Checkbutton(row_a, text='Baseline vs all others:',
                        variable=self._fap_use_base).pack(side='left')
        self._fap_base_cb = ttk.Combobox(row_a, textvariable=self._fap_base, width=32,
                                         postcommand=lambda: self._refresh_fap_choices())
        self._fap_base_cb.pack(side='left', padx=6)

        row_b = ttk.Frame(frm_pairs)
        row_b.pack(fill='x', padx=6, pady=2)
        ttk.Label(row_b, text='Pair:').pack(side='left', padx=(4, 4))
        self._fap_pair_a_cb = ttk.Combobox(row_b, textvariable=self._fap_pair_a, width=28,
                                           postcommand=lambda: self._refresh_fap_choices())
        self._fap_pair_a_cb.pack(side='left')
        ttk.Label(row_b, text='vs').pack(side='left', padx=6)
        self._fap_pair_b_cb = ttk.Combobox(row_b, textvariable=self._fap_pair_b, width=28,
                                           postcommand=lambda: self._refresh_fap_choices())
        self._fap_pair_b_cb.pack(side='left')
        ttk.Button(row_b, text='Add Pair', command=self._add_fap_pair).pack(side='left', padx=8)
        ttk.Button(row_b, text='Remove Selected', command=self._remove_fap_pair).pack(side='left')

        row_c = ttk.Frame(frm_pairs)
        row_c.pack(fill='x', padx=6, pady=(2, 6))
        self._fap_pairs_lb = tk.Listbox(row_c, height=3, font=('Verdana', 10), activestyle='none')
        self._fap_pairs_lb.pack(fill='x', padx=4)

        # Actions
        frm_act = ttk.LabelFrame(parent, text='Actions')
        frm_act.pack(fill='x', **pad)

        btn_row = ttk.Frame(frm_act)
        btn_row.pack(fill='x', padx=6, pady=8)

        self._fap_btn_run = ttk.Button(btn_row, text='Run', width=14, command=self._on_fap_run)
        self._fap_btn_dry = ttk.Button(btn_row, text='Dry Run', width=14, command=self._on_fap_dry)
        self._fap_btn_dry.pack(side='left', padx=4)
        self._fap_btn_run.pack(side='left', padx=4)
        ttk.Button(btn_row, text='Open Output Folder',
                   command=self._open_output_folder).pack(side='left', padx=12)

        self._fap_txt = self._make_output_area(parent, pad)

    def _open_output_folder(self):
        import os
        folder = OUTPUT_DIR / 'fap_tool'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _fap_names(self) -> list[str]:
        lines = (ln.strip() for ln in self._fap_names_txt.get('1.0', 'end').splitlines())
        return [ln for ln in lines if ln and not ln.startswith('#')]

    def _refresh_fap_choices(self):
        names = self._fap_names()
        for cb in (self._fap_base_cb, self._fap_pair_a_cb, self._fap_pair_b_cb):
            cb['values'] = names

    def _add_fap_pair(self):
        a, b = self._fap_pair_a.get().strip(), self._fap_pair_b.get().strip()
        if not a or not b:
            messagebox.showerror('Pair', 'Choose both FAPs for the pair.')
            return
        if a.lower() == b.lower():
            messagebox.showerror('Pair', 'Choose two different FAPs.')
            return
        if any({a.lower(), b.lower()} == {x.lower(), y.lower()} for x, y in self._fap_pairs):
            return
        self._fap_pairs.append((a, b))
        self._fap_pairs_lb.insert('end', f'{a}  vs  {b}')

    def _remove_fap_pair(self):
        for i in reversed(self._fap_pairs_lb.curselection()):
            self._fap_pairs_lb.delete(i)
            del self._fap_pairs[i]

    def _on_fap_run(self):
        self._run_fap(dry_run=False)

    def _on_fap_dry(self):
        self._run_fap(dry_run=True)

    def _run_fap(self, dry_run: bool):
        if self._busy:
            return
        names = self._fap_names()
        if not names:
            messagebox.showerror('No FAP Names', 'Enter at least one Function Access Profile name.')
            return
        baseline = self._fap_base.get().strip() if self._fap_use_base.get() else None
        if self._fap_use_base.get() and not baseline:
            messagebox.showerror('Baseline', 'Choose the baseline FAP, or untick "Baseline vs all others".')
            return
        all_pairs = self._fap_all_pairs.get()
        pairs = list(self._fap_pairs)
        client = self._build_client()
        if client is None:
            return

        try:
            _fap.FAP_INPUT_DIR.mkdir(parents=True, exist_ok=True)
            _fap.DEFAULT_NAMES_FILE.write_text('\n'.join(names) + '\n', encoding='utf-8')
        except OSError:
            pass   # saving the list is a convenience only

        self._active_txt = self._fap_txt
        self._set_busy(True, 'Running dry run...' if dry_run else 'Fetching FAPs...')

        def _work():
            try:
                for h in list(_uat.logger.handlers):
                    _uat.logger.removeHandler(h)

                _fap.run(names, client, OUTPUT_DIR, dry_run,
                         pairs=pairs, all_pairs=all_pairs, baseline=baseline)
            except SystemExit:
                pass
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    # =========================================================================
    # TAB 4 — Same FAP, Diff Envs
    # =========================================================================

    def _build_fapenv_tab(self, parent):
        pad = dict(padx=8, pady=4)

        frm_names = ttk.LabelFrame(parent, text='Function Access Profiles  (one name per line)')
        frm_names.pack(fill='x', **pad)
        inner = ttk.Frame(frm_names)
        inner.pack(fill='x', padx=6, pady=6)
        self._fapenv_names_txt = tk.Text(inner, wrap='none', height=5,
                                         font=('Verdana', 10), relief='solid', borderwidth=1)
        scroll = ttk.Scrollbar(inner, command=self._fapenv_names_txt.yview)
        self._fapenv_names_txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self._fapenv_names_txt.pack(fill='x')
        names = _fap.load_names(None, str(_fap.ENV_NAMES_FILE)) if _fap.ENV_NAMES_FILE.exists() \
            else _fap.load_names(None, None)
        self._fapenv_names_txt.insert('end', '\n'.join(names))
        ttk.Label(frm_names, foreground='gray',
                  text='Example: WFM Corporate Team   (saved to input/fap_tool/fap_env_names.txt on Run)'
                  ).pack(anchor='w', padx=10, pady=(0, 4))

        frm_sides = ttk.LabelFrame(parent, text='Environments to compare')
        frm_sides.pack(fill='x', **pad)
        self._fapenv_env  = {'A': tk.StringVar(value='NPR1'), 'B': tk.StringVar(value='UAT')}
        self._fapenv_prof = {'A': tk.StringVar(), 'B': tk.StringVar()}
        self._fapenv_prof_cb = {}
        for side in ('A', 'B'):
            row = ttk.Frame(frm_sides)
            row.pack(fill='x', padx=6, pady=3)
            ttk.Label(row, text=f'Side {side}   Environment:').pack(side='left', padx=(4, 4))
            ttk.Combobox(row, textvariable=self._fapenv_env[side], values=_env.ENVIRONMENTS,
                         width=7, state='readonly').pack(side='left', padx=(0, 16))
            ttk.Label(row, text='Profile:').pack(side='left', padx=(0, 4))
            cb = ttk.Combobox(row, textvariable=self._fapenv_prof[side], width=34, state='readonly')
            cb.pack(side='left')
            self._fapenv_prof_cb[side] = cb
            self._fapenv_env[side].trace_add('write', lambda *_: self._refresh_fapenv_profiles())
        ttk.Label(frm_sides, foreground='gray',
                  text='Grant type, credentials mode and SSL come from the Connection panel. '
                       'To add a profile for an environment, select it in the panel first.'
                  ).pack(anchor='w', padx=10, pady=(0, 4))
        self._conn_grant.trace_add('write', lambda *_: self._refresh_fapenv_profiles())
        self._conn_mode.trace_add('write', lambda *_: self._refresh_fapenv_profiles())
        self._refresh_fapenv_profiles()

        frm_act = ttk.LabelFrame(parent, text='Actions')
        frm_act.pack(fill='x', **pad)
        btn_row = ttk.Frame(frm_act)
        btn_row.pack(fill='x', padx=6, pady=8)
        self._fapenv_btn_run = ttk.Button(btn_row, text='Run', width=14,
                                          command=lambda: self._run_fapenv(False))
        self._fapenv_btn_dry = ttk.Button(btn_row, text='Dry Run', width=14,
                                          command=lambda: self._run_fapenv(True))
        self._fapenv_btn_dry.pack(side='left', padx=4)
        self._fapenv_btn_run.pack(side='left', padx=4)
        ttk.Button(btn_row, text='Open Output Folder',
                   command=self._open_output_folder).pack(side='left', padx=12)

        self._fapenv_txt = self._make_output_area(parent, pad)

    def _refresh_fapenv_profiles(self):
        grant = self._conn_grant.get()
        local = self._conn_mode.get() == 'local'
        for side in ('A', 'B'):
            env = self._fapenv_env[side].get()
            names = _env.list_profiles(env, grant)
            cb = self._fapenv_prof_cb[side]
            cb.configure(values=names, state='readonly' if local and names else 'disabled')
            self._fapenv_prof[side].set(_env.default_profile(env, grant) or '' if local else '')

    def _run_fapenv(self, dry_run: bool):
        if self._busy:
            return
        lines = (ln.strip() for ln in self._fapenv_names_txt.get('1.0', 'end').splitlines())
        names = [ln for ln in lines if ln and not ln.startswith('#')]
        if not names:
            messagebox.showerror('No FAP Names', 'Enter at least one Function Access Profile name.')
            return
        if self._fapenv_env['A'].get() == self._fapenv_env['B'].get():
            messagebox.showerror('Environments', 'Choose two different environments.')
            return
        client_a = self._make_client(self._fapenv_env['A'].get(), self._fapenv_prof['A'].get())
        if client_a is None:
            return
        client_b = self._make_client(self._fapenv_env['B'].get(), self._fapenv_prof['B'].get())
        if client_b is None:
            return

        try:
            _fap.FAP_INPUT_DIR.mkdir(parents=True, exist_ok=True)
            _fap.ENV_NAMES_FILE.write_text('\n'.join(names) + '\n', encoding='utf-8')
        except OSError:
            pass   # saving the list is a convenience only

        self._active_txt = self._fapenv_txt
        self._set_busy(True, 'Running dry run...' if dry_run else 'Comparing environments...')

        def _work():
            try:
                for h in list(_uat.logger.handlers):
                    _uat.logger.removeHandler(h)
                _fap.run_envs(names, client_a, client_b, OUTPUT_DIR, dry_run)
            except SystemExit:
                pass
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    # =========================================================================
    # Shared helpers
    # =========================================================================

    def _make_output_area(self, parent, pad) -> tk.Text:
        frm_out = ttk.LabelFrame(parent, text='Output')
        frm_out.pack(fill='both', expand=True, **pad)

        # Buttons are packed first (bottom) so a short window shrinks the log, not the buttons
        btn_row = ttk.Frame(frm_out)
        btn_row.pack(side='bottom', fill='x', padx=4, pady=(0, 4))
        ttk.Button(btn_row, text='Clear Output',
                   command=lambda: self._clear_txt(txt)).pack(side='right', padx=2)
        ttk.Button(btn_row, text='? Help',
                   command=self._show_help).pack(side='right', padx=2)

        txt = tk.Text(
            frm_out, wrap='word', state='disabled', height=8,
            bg='#1e1e1e', fg='#d4d4d4',
            font=('Courier New', 9),
            relief='flat', borderwidth=0,
            insertbackground='white',
        )
        scroll = ttk.Scrollbar(frm_out, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True, padx=4, pady=(4, 0))

        txt.tag_configure('ok',   foreground='#6adc6a')
        txt.tag_configure('err',  foreground='#f44747')
        txt.tag_configure('warn', foreground='#ffcc00')
        txt.tag_configure('info', foreground='#9cdcfe')

        return txt

    def _clear_txt(self, txt: tk.Text):
        txt.configure(state='normal')
        txt.delete('1.0', 'end')
        txt.configure(state='disabled')

    def _append_output(self, txt: tk.Text, text: str):
        txt.configure(state='normal')
        start = txt.index('end-1c')
        txt.insert('end', text)
        end = txt.index('end-1c')
        up = text.upper()
        if any(w in up for w in ('COMPLETED', 'SUCCESSFUL', 'SAVED', 'SENT', 'AUTHENTICATED')):
            txt.tag_add('ok', start, end)
        elif any(w in up for w in ('ERROR', 'FAILED', 'FAIL')):
            txt.tag_add('err', start, end)
        elif any(w in up for w in ('WARNING', 'DRY RUN')):
            txt.tag_add('warn', start, end)
        elif any(w in up for w in ('INFO', 'AUTHENTICATING', 'POLLING', 'DOWNLOADING', 'RUNNING')):
            txt.tag_add('info', start, end)
        txt.see('end')
        txt.configure(state='disabled')

    def _poll_output(self):
        try:
            while True:
                text = self._out_q.get_nowait()
                if self._active_txt:
                    self._append_output(self._active_txt, text)
        except queue.Empty:
            pass
        self.after(100, self._poll_output)

    def _set_busy(self, busy: bool, status: str = ''):
        self._busy = busy
        state = 'disabled' if busy else 'normal'
        for btn in (self._audit_btn_run, self._audit_btn_dry,
                    self._api_btn_run,   self._api_btn_dry,
                    self._fap_btn_run,   self._fap_btn_dry,
                    self._fapenv_btn_run, self._fapenv_btn_dry,
                    self._conn_btn_test):
            btn.configure(state=state)
        # Profile editing only applies to local credentials
        edit = 'normal' if not busy and self._conn_mode.get() == 'local' else 'disabled'
        for btn in (self._conn_btn_save, self._conn_btn_del):
            btn.configure(state=edit)
        self._status.set(status if busy else 'Ready')

    # ── Help window ───────────────────────────────────────────────────────

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title('UKG Tools — Help')
        win.minsize(660, 600)
        win.resizable(True, True)
        win.grab_set()

        txt = tk.Text(
            win, wrap='word', state='normal',
            font=('Verdana', 10),
            bg='#ffffff', fg='#1a1a1a',
            relief='flat', borderwidth=0,
            padx=16, pady=12,
            cursor='arrow',
        )
        scroll = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True)

        txt.tag_configure('h1',   font=('Verdana', 13, 'bold'), spacing3=6)
        txt.tag_configure('h2',   font=('Verdana', 10, 'bold'), spacing1=10, spacing3=2)
        txt.tag_configure('body', font=('Verdana', 10),         lmargin1=16, lmargin2=16)
        txt.tag_configure('step', font=('Verdana', 10, 'bold'), lmargin1=16, lmargin2=32,
                          foreground='#0066cc')
        txt.tag_configure('note', font=('Verdana', 9, 'italic'), lmargin1=16, lmargin2=16,
                          foreground='#666666')
        txt.tag_configure('warn', font=('Verdana', 10),          lmargin1=16, lmargin2=16,
                          foreground='#cc4400')

        def h1(t):    txt.insert('end', t + '\n', 'h1')
        def h2(t):    txt.insert('end', t + '\n', 'h2')
        def body(t):  txt.insert('end', t + '\n', 'body')
        def step(l, t): txt.insert('end', f'  {l}  ', 'step'); txt.insert('end', t + '\n', 'body')
        def note(t):  txt.insert('end', '  ℹ  ' + t + '\n', 'note')
        def warn(t):  txt.insert('end', '  ⚠  ' + t + '\n', 'warn')
        def gap():    txt.insert('end', '\n')

        h1('UKG Tools — Help Guide')
        body('This launcher gives you access to four tools for working with the UKG Pro '
             'Workforce Management system without needing to open a terminal or remember '
             'any commands. Every tab has a Dry Run (shows what would happen, no API calls), a '
             'Run, an Output area, and Clear Output / ? Help buttons.')
        gap()

        h2('━━  Connection panel  (top of the window — used by every tab)')
        gap()
        body('Choose where and how to connect once; all four tabs use it. Your last choice is '
             'remembered. (The Same FAP, Diff Envs tab picks its own environments and profiles but '
             'still uses the grant type, credentials mode and SSL setting from here.)')
        gap()
        step('Environment',
             'NPR1, UAT or PRD. The URL, organization and token host switch automatically. '
             'PRD shows a red PRODUCTION warning.')
        step('Grant type',
             'client_credentials or password. Each environment has its own profiles per grant type.')
        step('Credentials',
             '"local" uses a saved profile (secrets in Windows Credential Manager). "local_akv" '
             'and "akv" read from the environment\'s Azure Key Vault (names come from '
             '~/.ukg_hwfd/akv_config.json).')
        step('Profile',
             'The saved credential profile to use. Defaults to the last one you used for the '
             'selected environment and grant type.')
        step('Save / Update Profile…',
             'Creates a profile, or updates one: keep the same name to overwrite it. Enter the '
             'client ID / secret (and username / password for the password grant). '
             'Profiles are shared with the stonebranch UI.')
        step('Delete', 'Removes the selected profile and its stored secrets.')
        step('Test Connection',
             'Requests a token for the current selection — no other API calls. Use it after '
             'creating or updating a profile.')
        step('Skip SSL verification',
             'Must be checked on the corporate network or VPN. Leave it checked unless IT tells you otherwise.')
        gap()

        h2('━━  Tab 1 — Audit Report')
        gap()
        body('Runs the UKG Audit Report for a given date range and downloads the result '
             'to the output/ folder. Optionally emails the file to the configured recipients.')
        gap()
        step('Start Date / End Date',
             'The date range for the audit. Enter in YYYY-MM-DD format (e.g. 2026-09-01). '
             'Defaults to the last 7 days.')
        step('Output Format',
             'Choose XLSX for an Excel spreadsheet or PDF for a PDF document.')
        step('Audit Types',
             'The highlighted types are sent, exactly as written (e.g. Integration, '
             'Integration Instances). To use another, type it in the box and click Add; it is '
             'remembered for next time. Remove deletes the highlighted choices from the list.')
        step('User / Audit User IDs',
             'Optional filters. Leave them blank for most runs; the payload then carries them as '
             'blank ("") entries.')
        step('Report Payload',
             'Shows exactly what will be sent: Audit Types, DateRange (start and end date) and '
             'Output Format, plus the User and Audit User IDs entries (blank unless filled in). It updates as you change '
             'the fields.')
        step('Send email after download',
             'When checked, the downloaded file is automatically emailed to the recipients '
             'configured in input/config.json (smtp_to). The subject line is also set there.')
        step('Dry Run',
             'Validates your configuration and shows what would happen — no API calls are made '
             'and no file is downloaded.')
        step('Run',
             'Authenticates with UKG, submits the report, waits for it to complete, '
             'and downloads the file to the output/ folder. Progress is shown in the Output area.')
        gap()

        h2('━━  Tab 2 — UKG API Tool')
        gap()
        body('Executes any UKG API endpoint. This is a general-purpose tool for developers '
             'and power users who need to call endpoints not covered by the Audit Report tab.')
        gap()
        step('Method / Endpoint',
             'Pick GET, POST, PUT, PATCH or DELETE and enter the endpoint path, e.g. '
             '/api/v1/commons/function_access_profiles?name=ACI%20CDX%20Access. The URL, token '
             'and headers (Authorization, Accept, Content-Type) are added for you.')
        step('Payload',
             'The JSON request body. Edit it right in the box. It is only sent for POST, PUT '
             'and PATCH; for GET and DELETE the box is greyed out. Format JSON tidies it up.')
        step('Edit File / ↻ Reload',
             'Everything is saved to input/ukg_request.json when you Run. Edit File saves the form '
             'and opens that file in your text editor; click Reload to bring your changes back in.')
        step('Dry Run',
             'Shows the request that would be sent and exits without making any API call.')
        step('Run',
             'Authenticates and executes the request. POST, PUT, PATCH and DELETE ask for '
             'confirmation first (with a stronger warning for PRD). The response is printed to '
             'the Output area and saved to the output/ folder. The log file in log/ records the '
             'full request: method, URL, headers (token masked) and the complete JSON body.')
        gap()
        body('The saved file (input/ukg_request.json), also usable from the command line:')
        body('  {\n'
             '    "method":   "GET",\n'
             '    "endpoint": "/api/v1/commons/persons",\n'
             '    "headers":  {},\n'
             '    "payload":  null\n'
             '  }')
        gap()
        note('Supported methods: GET, POST, PUT, PATCH, DELETE. '
             'Set payload to null or omit it for GET/DELETE requests.')
        gap()

        h2('━━  Tab 3 — Same Env, Diff FAPs')
        gap()
        body('Fetches one or more Function Access Profiles and writes Excel workbooks so you can '
             'see exactly where they differ.')
        gap()
        step('FAP names',
             'One Function Access Profile name per line (e.g. ACI CDX Access). The list is '
             'saved to input/fap_tool/fap_names.txt each time you click Run.')
        step('Pair comparisons',
             'Optional extra tabs in the comparison file. "All pairs" adds a tab for every '
             'combination; "Baseline vs all others" compares one FAP with each of the rest; '
             'or build specific pairs with Add Pair. A Pairs tab lists them all.')
        step('Dry Run',
             'Shows the FAPs and pairs that would be compared. No API calls are made.')
        step('Run',
             'Connects using the Connection panel, calls '
             'GET /api/v1/commons/function_access_profiles?name=<FAP> for each name, and saves '
             'a folder output/fap_tool/fap_<env>_<timestamp>/. A FAP that does not exist in the '
             'environment is skipped and noted in the log; the rest still run.')
        step('Open Output Folder', 'Opens the output/fap_tool/ folder in Explorer.')
        gap()
        note('Each run folder holds three workbooks plus a json/ folder:')
        note('  fap_comparison  Comparison (one row per setting, one column per FAP; rows that '
             'differ are highlighted), Differences (those rows only), and any pair tabs.')
        note('  fap_actions     one tab each for ADD, DELETE, EDIT, VIEW and ALLOWED, with the '
             'FAPs side by side.')
        note('  fap_definitions one tab per FAP: control points down the side, actions across.')
        note('  json/           each FAP exactly as UKG returned it, one file per FAP.')
        gap()
        note('Reading the cells: an "X [scope]" means the JSON lists that action for that '
             'control point, with its scopeName (ALL, ALL_BUT_SELF, NONE) in brackets. A blank '
             'cell means the JSON does not list it. Control points are matched by key, one row '
             'each. On the Comparison tab a control point reads like "ADD [ALL], EDIT [ALL_BUT_SELF]".')
        note('id, name and description are listed but never counted as differences, because '
             'they are expected to differ between FAPs.')
        gap()

        h2('━━  Tab 4 — Same FAP, Diff Envs')
        gap()
        body('Compares the same Function Access Profile between two environments, e.g. '
             'WFM Corporate Team in NPR1 vs UAT, or UAT vs PRD.')
        gap()
        step('Environments',
             'Pick the environment and credential profile for Side A and Side B. Grant type, '
             'credentials mode and SSL come from the Connection panel.')
        step('FAP names',
             'One name per line. Saved to input/fap_tool/fap_env_names.txt on Run.')
        step('Dry Run',
             'Shows both connections and the FAPs. No API calls are made.')
        step('Run',
             'Signs in to both environments, fetches each FAP from both, and saves '
             'output/fap_tool/fap_<A>_vs_<B>_<timestamp>/ with one workbook and a json/ folder '
             '(json/<env>/ per side). The workbook has a Summary tab (which FAPs were found where '
             'and how many settings differ) and one tab per FAP found in both, with a column for '
             'each environment and a Differs column.')
        gap()
        note('A FAP that is missing from one or both environments is skipped; the log says '
             'where it exists and where it does not, and it still appears on the Summary tab as '
             '"not compared". Cells use the same "ADD [ALL], EDIT [...]" format as Tab 3. Only the '
             'FAP id is ignored when counting differences, because it always differs between '
             'environments.')
        gap()

        h2('━━  Config Files  (in the input/ folder)')
        gap()
        step('config.json',
             'Email settings only (smtp_from, smtp_to, smtp_subject, smtp_host, smtp_port). '
             'The UKG URL and credentials now come from the Connection panel.')
        step('fap_tool/fap_names.txt',
             'The FAP names from the Same Env, Diff FAPs tab, saved on each Run.')
        step('fap_tool/fap_env_names.txt',
             'The FAP names from the Same FAP, Diff Envs tab, saved on each Run.')
        step('audit_report_payload.json',
             'Parameters for the Audit Report. The Audit Report tab overrides the dates and '
             'output format from the UI, but reads everything else (audit type, priority, etc.) '
             'from this file.')
        step('ukg_request.json',
             'The request config for the UKG API Tool tab.')
        gap()

        h2('━━  Output')
        gap()
        step('output/',
             'Downloaded reports and API responses are saved here, with a timestamp in the filename. '
             'FAP results go in output/fap_tool/, one subfolder per run.')
        step('log/',
             'Detailed log files are saved here for each run. Share these with support if '
             'you encounter an error.')
        gap()

        h2('━━  Common Questions')
        gap()
        step('Authentication failed.',
             'Click Test Connection. A 401 "access_denied" means UKG rejected that profile\'s '
             'client ID / secret for the selected environment — update the profile or pick '
             'another. Also check "Skip SSL verification" if you are on the corporate network.')
        step('A FAP is missing from the results.',
             'UKG reports it as not existing in that environment. The log says which environment '
             'has it and which does not; check the exact name (case does not matter).')
        step('The file is not downloading.',
             'The report may still be processing. The tool waits up to 10 minutes — '
             'if it times out, try again during off-peak hours.')
        step('Email is not being sent.',
             'Confirm that smtp_from and smtp_to are set in input/config.json and that '
             'you are connected to the corporate network (the mail relay requires it).')
        step('I need to change who receives the email.',
             'Edit input/config.json and update the smtp_to list. '
             'You can add multiple addresses separated by commas.')
        gap()
        note('For technical issues, share the log file from the log/ folder with your WFD team.')
        gap()

        txt.configure(state='disabled')
        txt.see('1.0')
        ttk.Button(win, text='Close', command=win.destroy).pack(pady=8)

    # ── Cleanup ───────────────────────────────────────────────────────────

    def destroy(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        super().destroy()


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app = UKGToolsUI()
    app.mainloop()
