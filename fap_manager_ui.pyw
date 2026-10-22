"""
fap_manager_ui.pyw — FAP Manager: create and copy UKG Function Access Profiles

Double-click this file to launch (no console window, no server needed).

Separate app from ukg_tools_ui.pyw but it uses the same connection method (ukg_env): pick the
environment (NPR1 / UAT / PRD), grant type and credential profile once in the Connection panel.
Credential profiles can be created, updated and deleted from the panel, and the connection can be
tested there; profiles are shared with UKG Tools and the stonebranch UI.

Tabs
  Read     — read all FAPs, or the one FAP with a given name, into an Excel report
  Copy     — copy an existing FAP to a new name (same or another environment), or export it
             to an editable Excel file (template for the Create tab)
  Create   — build a new FAP from an Excel file (control point x ADD/EDIT/DELETE/VIEW, scopeName);
             blank templates; Validate + Save Payload saves the payload, optionally offline (no connection)
  Update   — change control points of an existing FAP from an Excel file (full list is re-sent);
             can export the current FAP to Excel first
  Delete   — delete one or more FAPs by name (typed confirmation, backup first)

Name is required; a blank description falls back to the name (Update: keeps the existing one).
The "? Help" button opens the user guide (fap_manager_help.py; manual in docs/fap_manager_user_manual.md).
"""

import os
import sys
import queue
import threading
import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

import urllib3

sys.path.insert(0, str(Path(__file__).parent))

import ukg_api_tool as _uat
import fap_create_tool as _fc
import fap_copy_tool as _fcopy
import fap_template_tool as _ftpl
import fap_read_tool as _fread
import fap_update_tool as _fupd
import fap_delete_tool as _fdel
import fap_manager_help as _help
import ukg_env as _env
import ukg_conn_dialogs as _dlg


BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'output'

# Last-used choices (never secrets) — remembered between sessions
UI_SETTINGS_FILE = Path(_env.CONFIG_DIR) / 'fap_manager_ui.json'


class _QueueWriter:
    """Captures print() and logging output from any thread and feeds it to the UI queue."""
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text):
        if text:
            self._q.put(text)

    def flush(self):
        pass


class FapManagerUI(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('UKG - FAP Manager')
        self.minsize(860, 700)

        self._out_q = queue.Queue()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _QueueWriter(self._out_q)
        sys.stderr = _QueueWriter(self._out_q)

        self._busy = False
        self._action_btns = []
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

    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use('vista')
        base = ('Verdana', 10)
        for widget in ('TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TCombobox',
                       'TLabelframe.Label', 'TNotebook.Tab'):
            style.configure(widget, font=base)
        style.configure('TLabelframe.Label', font=('Verdana', 10, 'bold'))
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
        self._nb.pack(fill='x', padx=8, pady=(8, 0))
        tab_read, tab_copy, tab_create, tab_update, tab_delete = (
            ttk.Frame(self._nb) for _ in range(5))
        self._nb.add(tab_read,   text='  Read  ')
        self._nb.add(tab_copy,   text='  Copy  ')
        self._nb.add(tab_create, text='  Create  ')
        self._nb.add(tab_update, text='  Update  ')
        self._nb.add(tab_delete, text='  Delete  ')
        self._build_read_tab(tab_read)
        self._build_copy_tab(tab_copy)
        self._build_create_tab(tab_create)
        self._build_update_tab(tab_update)
        self._build_delete_tab(tab_delete)

        self._build_output_area()
        self._finish_connection_panel()
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

        frm = ttk.LabelFrame(self, text='Connection  (used by all tabs; for Copy this is the source)')
        frm.pack(fill='x', padx=8, pady=(8, 0))

        row1 = ttk.Frame(frm)
        row1.pack(fill='x', padx=6, pady=(6, 2))
        ttk.Label(row1, text='Environment:').pack(side='left', padx=(0, 4))
        ttk.Combobox(row1, textvariable=self._conn_env, values=_env.ENVIRONMENTS,
                     width=7, state='readonly').pack(side='left', padx=(0, 16))
        ttk.Label(row1, text='Grant type:').pack(side='left', padx=(0, 4))
        ttk.Combobox(row1, textvariable=self._conn_grant, values=list(_env.GRANT_TYPES),
                     width=18, state='readonly').pack(side='left')

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
        self._conn_btn_test = ttk.Button(row2, text='Test Connection',
                                         command=self._on_test_connection)
        self._conn_btn_test.pack(side='left', padx=(12, 2))
        self._action_btns.append(self._conn_btn_test)

        row3 = ttk.Frame(frm)
        row3.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Checkbutton(row3, text='Skip SSL verification (required on corporate network)',
                        variable=self._conn_no_ssl).pack(side='left')
        self._conn_warn = ttk.Label(row3, text='', foreground='#cc0000',
                                    font=('Verdana', 10, 'bold'))
        self._conn_warn.pack(side='left', padx=(24, 0))

        self._conn_no_ssl.trace_add('write', lambda *_: self._save_ui_settings())

    def _finish_connection_panel(self):
        """Wire the change handlers once every tab (which also depends on them) exists."""
        for var in (self._conn_env, self._conn_grant, self._conn_mode, self._conn_prof):
            var.trace_add('write', lambda *_: self._refresh_copy_destination())
        for var in (self._conn_env, self._conn_grant, self._conn_mode):
            var.trace_add('write', lambda *_: self._on_connection_change())
        self._on_connection_change()

    def _save_ui_settings(self):
        try:
            UI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            UI_SETTINGS_FILE.write_text(json.dumps({
                'environment': self._conn_env.get(), 'grant_type': self._conn_grant.get(),
                'cred_mode':   self._conn_mode.get(), 'skip_ssl':   self._conn_no_ssl.get(),
            }, indent=2), encoding='utf-8')
        except OSError:
            pass   # remembering the last choice is a convenience only

    def _on_connection_change(self):
        env, grant = self._conn_env.get(), self._conn_grant.get()
        names = _env.list_profiles(env, grant)
        self._conn_prof_cb.configure(values=names)
        self._conn_prof.set(_env.default_profile(env, grant) or '')
        local = self._conn_mode.get() == 'local'
        self._conn_prof_cb.configure(state='readonly' if local and names else 'disabled')
        self._conn_warn.configure(text='⚠ PRODUCTION' if env == 'PRD' else '')
        self._update_profile_buttons()
        self._save_ui_settings()

    def _update_profile_buttons(self):
        """Profile editing only applies to local credentials, and not while a job runs."""
        state = 'normal' if not self._busy and self._conn_mode.get() == 'local' else 'disabled'
        for btn in (self._conn_btn_save, self._conn_btn_del):
            btn.configure(state=state)

    # ── Profile management and connection test (same behaviour as UKG Tools) ──

    def _profile_dialog(self):
        saved = _dlg.profile_dialog(self, self._conn_env.get(), self._conn_grant.get(),
                                    self._conn_prof.get())
        if saved:
            self._on_connection_change()
            self._conn_prof.set(saved)

    def _delete_profile(self):
        if _dlg.delete_profile(self, self._conn_prof.get()):
            self._on_connection_change()

    def _on_test_connection(self):
        if self._busy:
            return
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return

        def _job():
            print('\n'.join(_env.describe(client, client.grant_type)))
            print('Requesting token ...')
            token = client.generate_access_token()
            print(f'Token generated - authenticated OK ({token[:12]}...)')
            if client.profile_name:
                _env.remember_profile(client.env, client.grant_type, client.profile_name)

        self._start('Testing connection...', _job)

    def _make_client(self, env: str, profile: str):
        """UKGClient for env + profile, with grant type / credentials mode / SSL from the panel.
        Shows an error and returns None on failure. Must be called on the main thread."""
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
        if not ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return client

    # =========================================================================
    # Create tab
    # =========================================================================

    def _build_create_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        self._name = tk.StringVar()
        self._desc = tk.StringVar()
        self._file = tk.StringVar()

        ttk.Label(parent, text='Name:').grid(row=0, column=0, sticky='w', padx=6, pady=(8, 2))
        ttk.Entry(parent, textvariable=self._name).grid(row=0, column=1, columnspan=2,
                                                        sticky='ew', padx=6, pady=(8, 2))
        ttk.Label(parent, text='Description:').grid(row=1, column=0, sticky='w', padx=6, pady=2)
        ttk.Entry(parent, textvariable=self._desc).grid(row=1, column=1, columnspan=2,
                                                        sticky='ew', padx=6, pady=2)
        ttk.Label(parent, text='Excel file:').grid(row=2, column=0, sticky='w', padx=6, pady=2)
        ttk.Entry(parent, textvariable=self._file).grid(row=2, column=1, sticky='ew', padx=6, pady=2)
        ttk.Button(parent, text='Browse…', command=self._browse).grid(row=2, column=2, padx=(0, 6))
        ttk.Label(parent, text='Description defaults to the name when left blank.\n'
                       'Validate + Save Payload saves the exact payload Create FAP would send '
                       '(dry_run_...json) but sends nothing.', justify='left',
                  foreground='gray').grid(row=3, column=1, sticky='w', padx=6)

        self._offline = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text='Offline - do not connect to UKG (Validate + Save Payload checks just the Excel '
                                     'file and payload; no name or Super Access check)',
                        variable=self._offline).grid(row=4, column=1, columnspan=2, sticky='w',
                                                     padx=6, pady=(4, 0))

        btns = ttk.Frame(parent)
        btns.grid(row=5, column=0, columnspan=3, sticky='ew', padx=6, pady=(8, 2))
        for text, cmd in (('Validate + Save Payload', lambda: self._run_create(True)),
                          ('Create FAP', lambda: self._run_create(False))):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side='left', padx=(0, 6))
            self._action_btns.append(b)
        ttk.Button(btns, text='Open Output Folder',
                   command=self._open_output_folder).pack(side='left', padx=6)

        tpl = ttk.Frame(parent)
        tpl.grid(row=6, column=0, columnspan=3, sticky='ew', padx=6, pady=(2, 8))
        ttk.Label(tpl, text='Templates:').pack(side='left', padx=(0, 6))
        ttk.Button(tpl, text='Blank Template…',
                   command=self._save_blank_template).pack(side='left', padx=(0, 6))
        b = ttk.Button(tpl, text='All Control Points Template',
                       command=self._run_all_cp_template)
        b.pack(side='left', padx=6)
        self._action_btns.append(b)
        ttk.Button(tpl, text='Open Template Folder',
                   command=lambda: self._open_folder(OUTPUT_DIR / 'fap_template')).pack(side='left', padx=6)
        ttk.Label(parent, foreground='gray', justify='left',
                  text='Blank: headers only.  All Control Points: every control point of Super Access listed, '
                       'actions and scopes empty (connects to UKG; uses the Connection panel).'
                  ).grid(row=7, column=1, columnspan=2, sticky='w', padx=6, pady=(0, 6))

    def _browse(self, var=None):
        start = _fc.FAP_CREATE_INPUT_DIR if _fc.FAP_CREATE_INPUT_DIR.is_dir() else BASE_DIR
        path = filedialog.askopenfilename(
            title='Select Excel file', initialdir=str(start),
            filetypes=[('Excel files', '*.xlsx *.xlsm'), ('All files', '*.*')])
        if path:
            (var or self._file).set(path)

    def _save_blank_template(self):
        path = filedialog.asksaveasfilename(
            title='Save Excel template', defaultextension='.xlsx',
            initialdir=str(_fc.TEMPLATE_FILE.parent if _fc.TEMPLATE_FILE.parent.is_dir() else BASE_DIR),
            initialfile=_fc.TEMPLATE_FILE.name, filetypes=[('Excel files', '*.xlsx')])
        if not path:
            return
        try:
            _fc.write_template(Path(path), examples=False)
        except OSError as exc:
            messagebox.showerror('Save Template', str(exc))
            return
        self._out_q.put(f'Template saved: {path}\n')

    def _run_all_cp_template(self):
        if self._busy:
            return
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return
        self._start('Building template...', lambda: _ftpl.run_all_control_points(client, OUTPUT_DIR))

    def _run_create(self, dry_run: bool):
        if self._busy:
            return
        name, desc, file = self._name.get().strip(), self._desc.get().strip(), self._file.get().strip()
        if not name:
            messagebox.showerror('Name Required', 'Enter the Function Access Profile name.')
            return
        if not file:
            messagebox.showerror('Excel File Required', 'Choose the Excel file to load.')
            return
        env = self._conn_env.get()
        if self._offline.get():
            if not dry_run:
                messagebox.showerror('Offline', 'Creating a FAP needs a connection to UKG. '
                                     'Untick "Offline" to create it, or use Validate + Save Payload.')
                return
            self._start('Building payload...',
                        lambda: _fc.save_payload(file, name, desc or name, OUTPUT_DIR))
            return
        if not dry_run and not self._confirm(
                f'Create Function Access Profile "{name}" in {env}?', env == 'PRD'):
            return
        client = self._make_client(env, self._conn_prof.get())
        if client is None:
            return
        self._start('Validating...' if dry_run else 'Creating FAP...',
                    lambda: _fc.run(client, file, name, desc or name, OUTPUT_DIR, dry_run))

    # =========================================================================
    # Update tab
    # =========================================================================

    def _build_update_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        self._up_name = tk.StringVar()
        self._up_desc = tk.StringVar()
        self._up_file = tk.StringVar()
        self._up_add_new = tk.BooleanVar(value=False)
        self._up_remove = tk.BooleanVar(value=False)

        ttk.Label(parent, text='FAP name:').grid(row=0, column=0, sticky='w', padx=6, pady=(8, 2))
        ttk.Entry(parent, textvariable=self._up_name).grid(row=0, column=1, columnspan=2,
                                                           sticky='ew', padx=6, pady=(8, 2))
        ttk.Label(parent, text='Description:').grid(row=1, column=0, sticky='w', padx=6, pady=2)
        ttk.Entry(parent, textvariable=self._up_desc).grid(row=1, column=1, columnspan=2,
                                                           sticky='ew', padx=6, pady=2)
        ttk.Label(parent, text='Excel file:').grid(row=2, column=0, sticky='w', padx=6, pady=2)
        ttk.Entry(parent, textvariable=self._up_file).grid(row=2, column=1, sticky='ew', padx=6, pady=2)
        ttk.Button(parent, text='Browse…',
                   command=lambda: self._browse(self._up_file)).grid(row=2, column=2, padx=(0, 6))
        ttk.Label(parent, foreground='gray', justify='left',
                  text='Changes only the control points in the Excel file; every other control point stays as it is. '
                       'Leave Description blank to keep the existing one.\n'
                       'By default a control point must already be in the profile, and its row must list every '
                       'action the profile has for it - otherwise it is skipped (nothing is added or removed).\n'
                       'Built-in profiles (e.g. Super Access) cannot be updated. A backup of the profile is saved first.\n'
                       'Preview + Save Payload builds and saves the exact payload Update FAP would send '
                       '(dry_run_...json) but sends nothing.'
                  ).grid(row=3, column=1, columnspan=2, sticky='w', padx=6)
        opts = ttk.Frame(parent)
        opts.grid(row=4, column=1, columnspan=2, sticky='w', padx=6, pady=(4, 0))
        ttk.Checkbutton(opts, text='Add control points that are not in the profile',
                        variable=self._up_add_new).pack(anchor='w')
        ttk.Checkbutton(opts, text='Allow removing actions (an action left out of the Excel row is removed)',
                        variable=self._up_remove).pack(anchor='w')

        btns = ttk.Frame(parent)
        btns.grid(row=5, column=0, columnspan=3, sticky='ew', padx=6, pady=8)
        for text, cmd in (('Preview + Save Payload', lambda: self._run_update(True)),
                          ('Update FAP', lambda: self._run_update(False))):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side='left', padx=(0, 6))
            self._action_btns.append(b)
        b = ttk.Button(btns, text='Export Current FAP to Excel', command=self._export_for_update)
        b.pack(side='left', padx=6)
        self._action_btns.append(b)
        ttk.Button(btns, text='Open Update Folder',
                   command=lambda: self._open_folder(OUTPUT_DIR / 'fap_update')).pack(side='left', padx=6)

    def _export_for_update(self):
        """Write the FAP named on this tab to an Excel file and put it in the Excel file box."""
        if self._busy:
            return
        name = self._up_name.get().strip()
        if not name:
            messagebox.showerror('Name Required', 'Enter the name of the Function Access Profile to export.')
            return
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return
        result = {}

        def job():
            if _ftpl.run(client, name, OUTPUT_DIR, result):
                path = result['path']
                self.after(0, lambda: self._up_file.set(path))
                print('The file is now selected as the Excel file. Edit it, then run Preview.')
        self._start('Exporting FAP...', job)

    def _run_update(self, dry_run: bool):
        if self._busy:
            return
        name, desc, file = self._up_name.get().strip(), self._up_desc.get().strip(), self._up_file.get().strip()
        if not name:
            messagebox.showerror('Name Required', 'Enter the name of the Function Access Profile to update.')
            return
        if not file:
            messagebox.showerror('Excel File Required', 'Choose the Excel file to load.')
            return
        env = self._conn_env.get()
        add_new, remove = self._up_add_new.get(), self._up_remove.get()
        if not dry_run and not self._confirm(
                f'Update Function Access Profile "{name}" in {env}?\n\n'
                'The profile\'s permissions are replaced with the full list built from the Excel file '
                'and the current profile. Run Preview first to see exactly what changes.\n'
                'A backup of the current profile is saved first.'
                + ('\n\nOption ON: control points not in the profile will be ADDED.' if add_new else '')
                + ('\n\nOption ON: actions left out of an Excel row will be REMOVED.' if remove else ''),
                env == 'PRD'):
            return
        client = self._make_client(env, self._conn_prof.get())
        if client is None:
            return
        self._start('Previewing update...' if dry_run else 'Updating FAP...',
                    lambda: _fupd.run(client, file, name, desc, OUTPUT_DIR, dry_run, add_new, remove))

    # =========================================================================
    # Delete tab
    # =========================================================================

    def _build_delete_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text='FAP name(s):').grid(row=0, column=0, sticky='nw', padx=6, pady=(8, 2))
        self._del_names = tk.Text(parent, height=5, width=60, wrap='none', undo=True)
        self._del_names.grid(row=0, column=1, sticky='ew', padx=6, pady=(8, 2))
        ttk.Label(parent, foreground='gray', justify='left',
                  text='One FAP name per line. Names must match exactly; names that are not found, match more than one '
                       'FAP or are built-in profiles are skipped.\n'
                       'Deleting cannot be undone. You are shown the list and must type DELETE (DELETE PRD in PRD) '
                       'to confirm; a backup of each profile is saved first.\n'
                       'UKG refuses to delete a profile that is still assigned to users - remove the assignment first.'
                  ).grid(row=1, column=1, sticky='w', padx=6)

        btns = ttk.Frame(parent)
        btns.grid(row=2, column=0, columnspan=2, sticky='ew', padx=6, pady=8)
        for text, cmd in (('Preview (read-only)', lambda: self._run_delete(True)),
                          ('Delete FAP(s)', lambda: self._run_delete(False))):
            b = ttk.Button(btns, text=text, command=cmd)
            b.pack(side='left', padx=(0, 6))
            self._action_btns.append(b)
        ttk.Button(btns, text='Open Delete Folder',
                   command=lambda: self._open_folder(OUTPUT_DIR / 'fap_delete')).pack(side='left', padx=6)

    def _run_delete(self, dry_run: bool):
        if self._busy:
            return
        names = _fdel.parse_names(self._del_names.get('1.0', 'end'))
        if not names:
            messagebox.showerror('Name Required', 'Enter at least one FAP name, one per line.')
            return
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return
        self._start('Previewing delete...' if dry_run else 'Deleting...',
                    lambda: _fdel.run(client, names, OUTPUT_DIR, dry_run, self._ask_delete_confirmation))

    def _ask_delete_confirmation(self, targets, word) -> bool:
        """Called from the worker thread: show the typed-confirmation dialog on the UI thread
        and wait for the answer."""
        result, done = {'ok': False}, threading.Event()

        def show():
            try:
                result['ok'] = self._confirm_typed(targets, word)
            finally:
                done.set()

        self.after(0, show)
        done.wait()
        return result['ok']

    def _confirm_typed(self, targets, word) -> bool:
        """Modal: list the FAPs and enable Delete only when `word` has been typed exactly."""
        env = self._conn_env.get()
        dlg = tk.Toplevel(self)
        dlg.title('Confirm Delete' + (' - PRODUCTION' if env == 'PRD' else ''))
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()
        body = ttk.Frame(dlg, padding=12)
        body.pack(fill='both', expand=True)
        ttk.Label(body, justify='left', foreground='#B00020',
                  text=f'Delete {len(targets)} Function Access Profile(s) in {env}?\n'
                       'This cannot be undone (a backup file is saved first).').pack(anchor='w')
        lst = tk.Text(body, height=min(10, len(targets) + 1), width=70, wrap='none')
        for r in targets:
            lst.insert('end', f'id {r["id"]}   {r.get("name")}   '
                              f'({len(r.get("permissionTypes", []))} permissions)\n')
        lst.configure(state='disabled')
        lst.pack(pady=8)
        ttk.Label(body, text=f'Type  {word}  to confirm:').pack(anchor='w')
        typed = tk.StringVar()
        entry = ttk.Entry(body, textvariable=typed, width=30)
        entry.pack(anchor='w', pady=(2, 8))
        entry.focus_set()

        result = {'ok': False}
        btns = ttk.Frame(body)
        btns.pack(anchor='e')
        go = ttk.Button(btns, text='Delete', width=10, state='disabled',
                        command=lambda: (result.update(ok=True), dlg.destroy()))
        go.pack(side='left', padx=4)
        ttk.Button(btns, text='Cancel', width=10, command=dlg.destroy).pack(side='left')
        typed.trace_add('write', lambda *_: go.configure(
            state='normal' if typed.get().strip() == word else 'disabled'))
        dlg.bind('<Escape>', lambda _: dlg.destroy())
        dlg.wait_window()
        return result['ok']

    # =========================================================================
    # Read tab
    # =========================================================================

    def _build_read_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        self._read_name = tk.StringVar()
        ttk.Label(parent, text='FAP name:').grid(row=0, column=0, sticky='w', padx=6, pady=(8, 2))
        ttk.Entry(parent, textvariable=self._read_name).grid(row=0, column=1, sticky='ew',
                                                             padx=6, pady=(8, 2))
        ttk.Label(parent, foreground='gray', justify='left',
                  text='Leave blank to read ALL FAPs in the Connection panel environment. With a name, only the FAP '
                       'with exactly that name is read (a partial name finds nothing).\n'
                       'Saves an Excel report: a FAPs sheet (id, name, description, permission count) and a '
                       'Permissions sheet (one row per control point, action and scope). Read-only.'
                  ).grid(row=1, column=1, sticky='w', padx=6)
        btns = ttk.Frame(parent)
        btns.grid(row=2, column=0, columnspan=2, sticky='ew', padx=6, pady=8)
        b = ttk.Button(btns, text='Read to Excel', command=self._run_read)
        b.pack(side='left', padx=(0, 6))
        self._action_btns.append(b)
        ttk.Button(btns, text='Open Read Folder',
                   command=lambda: self._open_folder(OUTPUT_DIR / 'fap_read')).pack(side='left', padx=6)

    def _run_read(self):
        if self._busy:
            return
        name = self._read_name.get().strip()
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return
        self._start('Reading FAPs...', lambda: _fread.run(client, name, OUTPUT_DIR))

    # =========================================================================
    # Copy tab
    # =========================================================================

    def _build_copy_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        self._copy_mode = tk.StringVar(value='fap')
        self._copy_src  = tk.StringVar()
        self._copy_env  = tk.StringVar(value=self._conn_env.get())
        self._copy_prof = tk.StringVar()
        self._copy_name = tk.StringVar()
        self._copy_desc = tk.StringVar()

        mode = ttk.Frame(parent)
        mode.grid(row=0, column=0, columnspan=2, sticky='w', padx=6, pady=(8, 2))
        ttk.Label(mode, text='Copy to:').pack(side='left', padx=(0, 8))
        ttk.Radiobutton(mode, text='New FAP', value='fap', variable=self._copy_mode,
                        command=self._refresh_copy_mode).pack(side='left', padx=(0, 12))
        ttk.Radiobutton(mode, text='Excel file (template for Create)', value='excel',
                        variable=self._copy_mode,
                        command=self._refresh_copy_mode).pack(side='left')

        ttk.Label(parent, text='Source FAP name:').grid(row=1, column=0, sticky='w', padx=6, pady=2)
        ttk.Entry(parent, textvariable=self._copy_src).grid(row=1, column=1, sticky='ew',
                                                            padx=6, pady=2)

        dest = ttk.Frame(parent)
        dest.grid(row=2, column=0, columnspan=2, sticky='ew', padx=6, pady=2)
        ttk.Label(dest, text='Destination environment:').pack(side='left', padx=(0, 4))
        self._copy_env_cb = ttk.Combobox(dest, textvariable=self._copy_env, values=_env.ENVIRONMENTS,
                                         width=7, state='readonly')
        self._copy_env_cb.pack(side='left', padx=(0, 16))
        ttk.Label(dest, text='Profile:').pack(side='left', padx=(0, 4))
        self._copy_prof_cb = ttk.Combobox(dest, textvariable=self._copy_prof,
                                          width=34, state='readonly')
        self._copy_prof_cb.pack(side='left')

        self._copy_info = ttk.Label(parent, text='', font=('Verdana', 10, 'bold'))
        self._copy_info.grid(row=3, column=1, sticky='w', padx=6)

        ttk.Label(parent, text='New FAP name:').grid(row=4, column=0, sticky='w', padx=6, pady=2)
        self._copy_name_e = ttk.Entry(parent, textvariable=self._copy_name)
        self._copy_name_e.grid(row=4, column=1, sticky='ew', padx=6, pady=2)
        ttk.Label(parent, text='Description:').grid(row=5, column=0, sticky='w', padx=6, pady=2)
        self._copy_desc_e = ttk.Entry(parent, textvariable=self._copy_desc)
        self._copy_desc_e.grid(row=5, column=1, sticky='ew', padx=6, pady=2)
        self._copy_hint = ttk.Label(parent, foreground='gray', justify='left')
        self._copy_hint.grid(row=6, column=1, sticky='w', padx=6)

        # New FAP: Preview / Copy.  Excel file: Create Template.  Only one set is shown.
        self._copy_btns_fap = ttk.Frame(parent)
        for text, cmd in (('Preview + Save Payload', lambda: self._run_copy(True)),
                          ('Copy FAP', lambda: self._run_copy(False))):
            b = ttk.Button(self._copy_btns_fap, text=text, command=cmd)
            b.pack(side='left', padx=(0, 6))
            self._action_btns.append(b)
        ttk.Button(self._copy_btns_fap, text='Open Output Folder',
                   command=self._open_output_folder).pack(side='left', padx=6)

        self._copy_btns_xl = ttk.Frame(parent)
        b = ttk.Button(self._copy_btns_xl, text='Create Template', command=self._run_template)
        b.pack(side='left', padx=(0, 6))
        self._action_btns.append(b)
        ttk.Button(self._copy_btns_xl, text='Open Template Folder',
                   command=lambda: self._open_folder(OUTPUT_DIR / 'fap_template')).pack(side='left', padx=6)

        self._copy_env.trace_add('write', lambda *_: self._refresh_copy_destination())
        self._refresh_copy_mode()

    def _refresh_copy_mode(self):
        """Switch between 'copy to a new FAP' and 'export to an Excel file'."""
        excel = self._copy_mode.get() == 'excel'
        self._copy_env_cb.configure(state='disabled' if excel else 'readonly')
        for e in (self._copy_name_e, self._copy_desc_e):
            e.configure(state='disabled' if excel else 'normal')
        if excel:
            self._copy_btns_fap.grid_remove()
            self._copy_btns_xl.grid(row=7, column=0, columnspan=2, sticky='ew', padx=6, pady=8)
            self._copy_hint.configure(text='Builds an Excel file from this FAP in the Connection panel '
                                           'environment, in the layout the Create tab reads.\n'
                                           'Edit it (add or delete control points, change actions and '
                                           'scopes), then use it on the Create tab.')
            self._copy_prof_cb.configure(state='disabled')
            self._copy_info.configure(text=f'Export from {self._conn_env.get()} to an Excel file',
                                      foreground='#1f4e78')
        else:
            self._copy_btns_xl.grid_remove()
            self._copy_btns_fap.grid(row=7, column=0, columnspan=2, sticky='ew', padx=6, pady=8)
            self._copy_hint.configure(text='The source is the Connection panel environment. Description '
                                           'defaults to the new name when left blank.\n'
                                           'Preview + Save Payload saves the exact payload Copy FAP would send '
                                           '(dry_run_...json) but sends nothing.')
            self._refresh_copy_destination()

    def _run_template(self):
        if self._busy:
            return
        name = self._copy_src.get().strip()
        if not name:
            messagebox.showerror('Name Required', 'Enter the name of the FAP to build the template from.')
            return
        client = self._make_client(self._conn_env.get(), self._conn_prof.get())
        if client is None:
            return
        self._start('Building template...', lambda: _ftpl.run(client, name, OUTPUT_DIR))

    def _refresh_copy_destination(self):
        """Destination env / source connection changed: refresh the destination profile list."""
        if not hasattr(self, '_copy_prof_cb'):
            return
        if self._copy_mode.get() == 'excel':
            self._refresh_copy_mode()
            return
        src, dst = self._conn_env.get(), self._copy_env.get()
        grant, local = self._conn_grant.get(), self._conn_mode.get() == 'local'
        if dst == src:
            self._copy_prof_cb.configure(values=[], state='disabled')
            self._copy_prof.set(self._conn_prof.get())
            self._copy_info.configure(text=f'Same-environment copy within {src}', foreground='#1f4e78')
            return
        names = _env.list_profiles(dst, grant)
        self._copy_prof_cb.configure(values=names, state='readonly' if local and names else 'disabled')
        self._copy_prof.set(_env.default_profile(dst, grant) or '' if local else '')
        text = f'Cross-environment copy: {src}  →  {dst}' + ('   ⚠ PRODUCTION' if dst == 'PRD' else '')
        if local and not names:
            text += f'   (no saved {grant} profile for {dst} - select {dst} in the Connection panel and use Save / Update Profile…)'
        self._copy_info.configure(text=text, foreground='#cc0000' if dst == 'PRD' or not names and local
                                  else '#1f4e78')

    def _run_copy(self, dry_run: bool):
        if self._busy:
            return
        src_name, new_name = self._copy_src.get().strip(), self._copy_name.get().strip()
        desc = self._copy_desc.get().strip()
        src_env, dst_env = self._conn_env.get(), self._copy_env.get()
        same_env = src_env == dst_env

        problems = _fcopy.validate_inputs(src_name, new_name, same_env)
        if problems:
            messagebox.showerror('Check Inputs', '\n'.join('• ' + p for p in problems))
            return
        where = f'within {src_env}' if same_env else f'from {src_env} to {dst_env}'
        if not dry_run and not self._confirm(
                f'Copy "{src_name}" {where} as "{new_name}"?', dst_env == 'PRD'):
            return
        src_client = self._make_client(src_env, self._conn_prof.get())
        if src_client is None:
            return
        dst_client = src_client if same_env else self._make_client(dst_env, self._copy_prof.get())
        if dst_client is None:
            return
        self._start('Checking...' if dry_run else 'Copying FAP...',
                    lambda: _fcopy.run(src_client, dst_client, src_name, new_name,
                                       desc or new_name, OUTPUT_DIR, dry_run))

    # =========================================================================
    # Shared helpers
    # =========================================================================

    def _confirm(self, question: str, production: bool) -> bool:
        if production:
            return messagebox.askyesno(
                'Confirm - PRODUCTION',
                f'{question}\n\n⚠ This changes the PRODUCTION environment.\nContinue?',
                icon='warning', default='no')
        return messagebox.askyesno('Confirm', question)

    def _start(self, status: str, job):
        """Run job() on a worker thread; its output flows to the Output area."""
        self._set_busy(True, status)

        def _work():
            try:
                for h in list(_uat.logger.handlers):
                    _uat.logger.removeHandler(h)
                job()
            except Exception as exc:
                self._out_q.put(f'\nERROR: {exc}\n')
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    def _open_output_folder(self):
        self._open_folder(OUTPUT_DIR)

    def _open_folder(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _build_output_area(self):
        frm = ttk.LabelFrame(self, text='Output')
        frm.pack(fill='both', expand=True, padx=8, pady=8)
        btn_row = ttk.Frame(frm)
        btn_row.pack(side='bottom', fill='x', padx=4, pady=(0, 4))   # packed first so it is never clipped
        ttk.Button(btn_row, text='Clear Output', command=self._clear_output).pack(side='right', padx=2)
        ttk.Button(btn_row, text='? Help', command=lambda: _help.show_help(self)).pack(side='right', padx=2)
        self._txt = tk.Text(frm, wrap='word', state='disabled', height=8, bg='#1e1e1e', fg='#d4d4d4',
                            font=('Courier New', 9), relief='flat', borderwidth=0)
        scroll = ttk.Scrollbar(frm, command=self._txt.yview)
        self._txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self._txt.pack(fill='both', expand=True, padx=4, pady=4)
        self._txt.tag_configure('ok',   foreground='#6adc6a')
        self._txt.tag_configure('err',  foreground='#f44747')
        self._txt.tag_configure('warn', foreground='#ffcc00')
        self._txt.tag_configure('info', foreground='#9cdcfe')

    def _clear_output(self):
        self._txt.configure(state='normal')
        self._txt.delete('1.0', 'end')
        self._txt.configure(state='disabled')

    def _append_output(self, text: str):
        txt = self._txt
        txt.configure(state='normal')
        start = txt.index('end-1c')
        txt.insert('end', text)
        end = txt.index('end-1c')
        up = text.upper()
        if any(w in up for w in ('COMPLETED', 'SAVED', 'AUTHENTICATED', 'PASSED')):
            txt.tag_add('ok', start, end)
        elif any(w in up for w in ('ERROR', 'FAILED', 'FAIL')):
            txt.tag_add('err', start, end)
        elif any(w in up for w in ('WARNING', 'DRY RUN')):
            txt.tag_add('warn', start, end)
        elif any(w in up for w in ('INFO', 'POST ', 'GET ')):
            txt.tag_add('info', start, end)
        txt.see('end')
        txt.configure(state='disabled')

    def _poll_output(self):
        try:
            while True:
                self._append_output(self._out_q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_output)

    def _set_busy(self, busy: bool, status: str = ''):
        self._busy = busy
        for btn in self._action_btns:
            btn.configure(state='disabled' if busy else 'normal')
        self._update_profile_buttons()
        self._status.set(status if busy else 'Ready')

    def destroy(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        super().destroy()


if __name__ == '__main__':
    FapManagerUI().mainloop()
