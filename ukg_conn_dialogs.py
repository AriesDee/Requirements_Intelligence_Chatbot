"""
ukg_conn_dialogs.py — credential-profile dialogs shared by the UKG Tools and FAP Manager UIs

Both apps keep their own Connection panel; these helpers hold the parts that must behave the same
in each, so a profile saved in one app is created, overwritten and deleted identically in the other.
Profiles themselves live in ukg_env (names in ~/.ukg_hwfd/profiles.json, secrets in Windows
Credential Manager) and are shared with the stonebranch UI.
"""

import tkinter as tk
from tkinter import ttk, messagebox

import ukg_env as _env

_LABELS = {'WFM_USERNAME': 'Username', 'WFM_PASSWORD': 'Password',
           'WFM_CLIENT_ID': 'Client ID', 'WFM_CLIENT_SECRET': 'Client Secret'}
_SECRET = {'WFM_PASSWORD', 'WFM_CLIENT_SECRET'}


def profile_dialog(parent, env: str, grant: str, current: str = '') -> str | None:
    """Create a new profile, or update `current`, for env + grant type.

    Modal. Returns the saved profile's full name, or None if the user cancelled."""
    prefix = _env.profile_prefix(env, grant)
    fields = _env.credential_fields(grant)

    existing = {}
    if current:
        try:
            existing = _env.load_profile_credentials(current)
        except Exception:
            pass   # unreadable profile — start from blank fields

    dlg = tk.Toplevel(parent)
    dlg.title(f'Save / Update Profile — {env} / {grant}')
    dlg.transient(parent)
    dlg.resizable(False, False)
    dlg.grab_set()

    body = ttk.Frame(dlg, padding=12)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text=f'Environment: {env}    Grant type: {grant}',
              foreground='#555555').grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))

    ttk.Label(body, text='Profile name:').grid(row=1, column=0, sticky='w', pady=3)
    name_frame = ttk.Frame(body)
    name_frame.grid(row=1, column=1, columnspan=2, sticky='w')
    ttk.Label(name_frame, text=prefix, foreground='#555555').pack(side='left')
    name_var = tk.StringVar(value=current[len(prefix):] if current.startswith(prefix) else '')
    ttk.Entry(name_frame, textvariable=name_var, width=24).pack(side='left')

    vars_, entries = {}, []
    for i, var in enumerate(fields, start=2):
        ttk.Label(body, text=_LABELS[var] + ':').grid(row=i, column=0, sticky='w', pady=3)
        key = var[len('WFM_'):].lower()
        vars_[var] = tk.StringVar(value=existing.get(key, ''))
        ent = ttk.Entry(body, textvariable=vars_[var], width=52,
                        show='•' if var in _SECRET else '')
        ent.grid(row=i, column=1, columnspan=2, sticky='w', pady=3)
        entries.append((var, ent))

    show = tk.BooleanVar(value=False)

    def toggle():
        for var, ent in entries:
            if var in _SECRET:
                ent.configure(show='' if show.get() else '•')

    ttk.Checkbutton(body, text='Show secrets', variable=show,
                    command=toggle).grid(row=len(fields) + 2, column=1, sticky='w')
    ttk.Label(body, text='Saving a name that already exists overwrites that profile.\n'
                         'Secrets are stored in Windows Credential Manager.',
              foreground='#777777').grid(row=len(fields) + 3, column=0, columnspan=3,
                                         sticky='w', pady=(8, 0))

    result = {'name': None}

    def save():
        unique = name_var.get().strip()
        if not unique:
            messagebox.showerror('Profile Name', 'Enter a profile name.', parent=dlg)
            return
        full = prefix + unique.lower().replace(' ', '_')
        if full in _env.list_profiles(env, grant) and full != current:
            if not messagebox.askyesno('Overwrite Profile',
                                       f'Profile "{full}" already exists. Overwrite it?',
                                       parent=dlg):
                return
        try:
            result['name'] = _env.save_profile(
                env, grant, unique, {k: v.get().strip() for k, v in vars_.items()})
        except Exception as exc:
            messagebox.showerror('Could Not Save Profile', str(exc), parent=dlg)
            return
        dlg.destroy()

    btns = ttk.Frame(body)
    btns.grid(row=len(fields) + 4, column=0, columnspan=3, sticky='e', pady=(12, 0))
    ttk.Button(btns, text='Save', width=10, command=save).pack(side='left', padx=4)
    ttk.Button(btns, text='Cancel', width=10, command=dlg.destroy).pack(side='left')
    dlg.bind('<Escape>', lambda _: dlg.destroy())
    dlg.wait_window()

    if result['name']:
        messagebox.showinfo('Profile Saved', f'Profile "{result["name"]}" saved.\n\n'
                            'Click "Test Connection" to verify it.', parent=parent)
    return result['name']


def delete_profile(parent, name: str) -> bool:
    """Confirm, then delete a profile and its stored secrets. True if it was deleted."""
    if not name:
        return False
    if not messagebox.askyesno('Delete Profile',
                               f'Delete profile "{name}" and its stored secrets?\n\n'
                               'This also removes it from the stonebranch UI.', parent=parent):
        return False
    try:
        _env.delete_profile(name)
    except Exception as exc:
        messagebox.showerror('Could Not Delete Profile', str(exc), parent=parent)
        return False
    return True
