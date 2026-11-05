"""
fap_manager_help.py — documentation for FAP Manager: the in-app Help window and the user manual

One source for both, so they cannot drift apart:
  - FapManagerUI's "? Help" button calls show_help(parent)
  - docs/fap_manager_user_manual.md is generated from the same content:
        python fap_manager_help.py --write-markdown          (writes docs/fap_manager_user_manual.md)

HELP is a list of (kind, text) or (kind, label, text) entries:
  h1 / h2 / h3   headings           body   paragraph           bullet  list item
  step           (label, text)      note   side remark         warn    warning
  code           command-line text  gap    blank line (window only)
Edit the content here, then regenerate the manual.
"""

import re
import sys
import argparse
from pathlib import Path

DOC_FILE = Path(__file__).parent / 'docs' / 'fap_manager_user_manual.md'

HELP = [
    ('h1', 'FAP Manager - User Guide'),
    ('body', 'FAP Manager creates, copies, updates and deletes UKG Function Access Profiles (FAPs) '
             'without writing any API calls. It is a separate app from UKG Tools and uses the same '
             'connection method: pick the environment and a saved credential profile once, and every '
             'tab uses it.'),
    ('body', 'A FAP is a list of permissions. Each permission is a control point (controlPointKey), '
             'an action (ADD, EDIT, DELETE, VIEW or ALLOWED) and a scope (ALL, ALL_BUT_SELF, ONLY_SELF '
             'or NONE).'),

    ('h2', 'Quick start'),
    ('step', '1.', 'Choose the Environment and Grant type, then pick a credential Profile '
                   '(or create one with Save / Update Profile...).'),
    ('step', '2.', 'Click Test Connection once to confirm the credentials work.'),
    ('step', '3.', 'Open the tab for what you want to do. Every tab that changes UKG has a '
                   'read-only Preview / Validate + Save Payload button - run it first, read the Output, '
                   'then run the real action.'),
    ('step', '4.', 'Everything the app does is written to the Output area at the bottom, and '
                   'files are saved in the output folder (see "Output and log files").'),

    ('h2', 'Tabs at a glance'),
    ('bullet', 'Read - list all FAPs, or read the FAPs you name with their permissions, into an Excel report.'),
    ('bullet', 'Copy - copy an existing FAP to a new name (same or another environment), or export it to '
               'an Excel file you can edit.'),
    ('bullet', 'Create - create a new FAP from an Excel file. Also: blank templates, and Validate + Save Payload '
               '(which saves the payload, optionally without connecting).'),
    ('bullet', 'Update - change control points of an existing FAP from an Excel file.'),
    ('bullet', 'Delete - delete one or more FAPs by name.'),

    ('h2', 'Connection panel (top of the window)'),
    ('body', 'Used by every tab. For the Copy tab it is the source. Your last Environment, Grant type '
             'and SSL choice are remembered.'),
    ('step', 'Environment', 'NPR1, UAT or PRD. PRD shows a red PRODUCTION warning; every action that changes '
                            'PRD asks for an extra confirmation.'),
    ('step', 'Grant type', 'client_credentials or password. Each environment has its own profiles per grant type.'),
    ('step', 'Profile', 'The saved credentials to use. FAP Manager uses saved local profiles only '
                        '(secrets are kept in Windows Credential Manager). The last profile used for an '
                        'environment is selected automatically.'),
    ('step', 'Save / Update Profile...', 'Create a new profile for the chosen environment and grant type, or '
                                         'update the selected one. Saving a name that already exists overwrites it.'),
    ('step', 'Delete', 'Delete the selected profile and its stored secrets. Profiles are shared with UKG Tools '
                       'and the Stonebranch UI, so this removes it there too.'),
    ('step', 'Test Connection', 'Requests a token with the selected profile and says whether it worked.'),
    ('step', 'Skip SSL verification', 'Needed on the corporate network. Leave it ticked unless told otherwise.'),
    ('note', 'Key Vault credentials are not offered here. They can only be set up in the Stonebranch UI.'),

    ('h2', 'The Excel file (Create, Update)'),
    ('body', 'The first sheet is read. A header row is searched for in the first 10 rows; column order does '
             'not matter.'),
    ('code', 'Control Point                      | ADD | EDIT | DELETE | VIEW | ALLOWED | scopeName\n'
             'WFS_BASELINE_STAFF_PATTERN_VIEW   |  x  |  x   |   x    |  x   |         | ALL\n'
             'SA_DISPLAY_DAY_BEFORE_AND_AFTER   |     |      |        |      |    x    | ALL\n'
             'PERSON                            |  x  |      |        |      |         | ALL\n'
             'PERSON                            |     |  x   |        |      |         | ALL_BUT_SELF'),
    ('step', 'Control Point', 'The controlPointKey ("controlPointKey" is also accepted as the header).'),
    ('step', 'ADD, EDIT, DELETE, VIEW', 'These four columns are required. Put x where the profile has that '
                                        'action; leave blank otherwise. Anything other than x is an error.'),
    ('step', 'ALLOWED', 'Optional column, marked the same way. Many control points use ALLOWED instead of '
                        'ADD/EDIT/DELETE/VIEW.'),
    ('step', 'scopeName', 'ALL, ALL_BUT_SELF, ONLY_SELF or NONE. It applies to every x on that row '
                          '(upper/lower case, spaces or hyphens are fine: "all but self" works).'),
    ('bullet', 'A control point can have several rows when its actions need different scopes (see PERSON above).'),
    ('bullet', 'The same control point + action twice is an error.'),
    ('bullet', 'A row with no x is skipped with a warning (when there are many, one summary line); blank rows '
               'are ignored.'),
    ('bullet', 'All problems found in the file are listed together, with row numbers, so you can fix them in one pass.'),
    ('note', 'The easiest way to get a correct file: Copy tab -> Copy to "Excel file" from a FAP that is '
             'close to what you want, then edit it. Or start from the Create tab\'s templates.'),

    ('h2', 'Checks before anything is sent'),
    ('body', 'Create and Update stop - and send nothing - if any of these fail. All problems of a check '
             'are listed at once.'),
    ('step', '1. Excel file', 'Valid layout, only x marks, valid scope names, no repeated control point + action.'),
    ('step', '2. Payload', 'The request itself is validated: a name is present; every action is one of ADD, EDIT, '
                           'DELETE, VIEW, ALLOWED; every scope is one of ALL, ALL_BUT_SELF, ONLY_SELF, NONE; every '
                           'permission has all three fields; control point keys contain no spaces; no control '
                           'point repeats an action.'),
    ('step', '3. Name (Create, Copy)', 'A FAP with that exact name must not already exist in the environment '
                                       '(upper/lower case is ignored). Update and Delete need the name to exist.'),
    ('step', '4. Super Access', 'Every control point and action is compared with the built-in Super Access profile '
                                'in that environment (Create, Update). Skipped by Create\'s Offline option.'),
    ('warn', 'Assumption: the UKG API documentation does not say which control points (keys) or which actions '
             'per control point are valid. FAP Manager assumes Super Access contains every control point and '
             'every action that is valid for it, and uses it as the basis for correctness. An unknown '
             'control point, an action Super Access does not have for that control point, or Super Access '
             'being unreadable, stops the run.'),
    ('note', 'Scopes are only checked against the four documented values. Anything else UKG might reject '
             'is reported by UKG itself when the request is sent, and its message is shown in the Output.'),

    ('h2', 'Read tab'),
    ('body', 'Reads FAPs from the Connection panel environment and saves an Excel report. Read-only.'),
    ('warn', 'UKG does not return permissions when all FAPs are listed. To get permissions you must give the '
             'FAP name(s).'),
    ('step', 'FAP name(s)', 'One name per line. Leave blank to list ALL FAPs. Names must match exactly (case is '
                            'ignored): a partial or misspelled name finds nothing (UKG: WCO-127822 "A Function '
                            'Access Profile does not exist with specified name"). A name that is not found is '
                            'skipped and the others are still read.'),
    ('step', 'Put each FAP\'s permissions on its own tab', 'Off by default (one Permissions tab for all the FAPs, '
                                                          'with the FAP name on every row). On: no Permissions '
                                                          'tab; instead one tab per FAP, named after it (cut to '
                                                          '31 characters, as Excel requires), with Control '
                                                          'Point, actionName and scopeName. Only used when '
                                                          'names are given.'),
    ('step', 'Read to Excel (no names)', 'One request. Saves fap_read_<env>_all_<time>.xlsx with a FAPs sheet '
                                         '(id, name, description) and a Notes sheet. No permissions.'),
    ('step', 'Read to Excel (with names)', 'One request per name. Saves fap_read_<env>_<name or N_faps>_<time>.xlsx '
                                           'with a FAPs sheet (id, name, description, isDefault, permission '
                                           'count, control point count), a Permissions sheet (FAP, id, control '
                                           'point, action, scope) and a Notes sheet.'),
    ('step', 'Open Read Folder', 'Opens the folder where reports are saved.'),
    ('note', 'The report is for looking at. To get a FAP in the layout the Create and Update tabs read, use '
             'Copy -> "Excel file".'),

    ('h2', 'Copy tab'),
    ('body', 'Reads an existing FAP and creates a new one with exactly the same permissions. The source is '
             'only read, so built-in profiles such as Super Access can be copied.'),
    ('step', 'Source FAP name', 'The FAP to copy, in the Connection panel environment. Exact name match.'),
    ('step', 'Destination environment', 'Same as the Connection panel for a copy within one environment, or '
                                        'another environment for a cross-environment copy (for example NPR1 '
                                        'to UAT). The line under it says which kind of copy this is.'),
    ('step', 'Profile', 'Credentials for the destination environment (cross-environment only; same grant type). '
                        'The last profile used for that environment is selected. If there is none, create one '
                        'by selecting that environment in the Connection panel and using Save / Update Profile...'),
    ('step', 'New FAP name', 'Required. Must differ from the source name when copying within one environment, '
                             'and must not already exist in the destination.'),
    ('step', 'Description', 'Optional; defaults to the new name.'),
    ('step', 'Preview + Save Payload', 'Runs every check and saves the payload as dry_run_...json. Creates nothing.'),
    ('step', 'Copy FAP', 'Asks for confirmation (with an extra PRODUCTION warning when the destination is PRD), '
                         'then creates the FAP.'),
    ('note', 'A cross-environment copy fails at UKG if a control point does not exist in the destination '
             'environment; UKG\'s message is shown and the payload is kept in the output folder.'),

    ('h3', 'Copy to: Excel file (template for Create)'),
    ('body', 'Choose "Excel file" under "Copy to" to export the source FAP instead of creating a new one. '
             'Edit the file (add or delete control points, change actions and scopes), then use it on the '
             'Create tab. Destination, New FAP name and Description are not used.'),
    ('step', 'Create Template', 'Writes the Excel file with one row per control point and scope, an ALLOWED '
                                'column, and a Notes sheet that says which FAP and environment it came from. '
                                'Saved in output/fap_template/.'),
    ('step', 'Open Template Folder', 'Opens the folder where templates are saved.'),
    ('bullet', 'After writing, the file is read back and compared with the FAP; the Output says whether it '
               'matches exactly.'),
    ('bullet', 'An action that has no column (anything other than ADD, EDIT, DELETE, VIEW, ALLOWED) is left out '
               'with a warning.'),

    ('h2', 'Create tab'),
    ('body', 'Creates a new FAP from an Excel file.'),
    ('step', 'Name', 'Required. The new FAP\'s name.'),
    ('step', 'Description', 'Optional; defaults to the name.'),
    ('step', 'Excel file', 'Choose it with Browse....'),
    ('step', 'Validate + Save Payload', 'Runs every check (it connects to UKG, read-only) and saves the exact payload '
                              'as dry_run_...json. Creates nothing. "DRY RUN - the Excel file is valid..." '
                              'means the file passed.'),
    ('step', 'Create FAP', 'Asks for confirmation (extra warning on PRD), runs the same checks, then creates '
                           'the FAP. The payload it sends is the same one Validate + Save Payload saved.'),
    ('step', 'Offline', 'Tick it to make Validate + Save Payload work without connecting to UKG: it checks just the Excel '
                        'file and the payload (no name check, no Super Access check) and saves the payload as '
                        'dry_run_<name>_<time>.json in output/fap_payload/. Create FAP is not available while '
                        'Offline is ticked.'),
    ('step', 'Open Output Folder', 'Opens the output folder.'),
    ('step', 'Blank Template...', 'Saves an Excel file with only the header row. No connection is needed. '
                                  'Use it to build a FAP from scratch.'),
    ('step', 'All Control Points Template', 'Lists every control point of Super Access (from the Connection '
                                            'panel environment), with the action and scope cells empty. Mark x '
                                            'and fill scopeName on the rows you want; rows with nothing marked '
                                            'are ignored. A "Valid Actions" sheet shows which actions each '
                                            'control point accepts. Saved in output/fap_template/.'),
    ('step', 'Open Template Folder', 'Opens the folder where templates are saved.'),
    ('note', 'Order of checks: Excel file, payload, name does not exist, Super Access. isDefault is always false.'),

    ('h2', 'Update tab'),
    ('body', 'Changes control points of an existing FAP from an Excel file.'),
    ('warn', 'UKG replaces the whole permission list on update: anything left out of the request is removed. '
             'So FAP Manager reads the profile as it is now, changes only the control points in your Excel '
             'file, and sends the complete list back. Every other control point stays exactly as it is.'),
    ('step', 'FAP name', 'The FAP to update. Exact name match. The name cannot be changed here.'),
    ('step', 'Description', 'Optional. Leave blank to keep the existing description.'),
    ('step', 'Excel file', 'Only the control points listed in it are looked at.'),
    ('step', 'Add control points that are not in the profile', 'Off by default. Off: a control point that is '
                                                              'not in the profile is skipped ("not in profile, '
                                                              'not added"). On: it is added.'),
    ('step', 'Allow removing actions', 'Off by default. Off: a control point whose Excel row leaves out an '
                                       'action the profile has is skipped (nothing is removed). On: the '
                                       'left-out action is removed.'),
    ('step', 'Export Current FAP to Excel', 'Writes the FAP named above to an Excel file (same file as Copy -> '
                                            '"Excel file") and puts it in the Excel file box, ready to edit. '
                                            'Edit it, save and close it, then run Preview.'),
    ('step', 'Preview + Save Payload', 'Shows what would change and saves the payload as dry_run_...json.'),
    ('step', 'Update FAP', 'Asks for confirmation (extra warning on PRD; the dialog repeats any option that is '
                           'on), then sends the update.'),
    ('body', 'The Output lists each control point:'),
    ('bullet', 'UPDATE - changed; shows before and after. "** REMOVES VIEW **" marks removed actions.'),
    ('bullet', 'ADD - a new control point added to the profile.'),
    ('bullet', 'SAME - already matches the Excel file.'),
    ('bullet', 'SKIP - not changed, with the reason.'),
    ('body', 'Before sending, the profile is saved to a backup file. After a successful update it is read '
             'back and compared: "Verified: the profile now has exactly the N permission(s) sent."'),
    ('body', 'The run stops without sending anything when: the Excel file or payload is invalid, the name is '
             'not found or matches more than one FAP, the FAP is built-in (negative id, for example Super '
             'Access), a control point or action fails the Super Access check, or nothing would change.'),
    ('note', 'To restore a profile, use the backup_...json file saved in the run\'s folder.'),

    ('h2', 'Delete tab'),
    ('warn', 'Deleting a FAP cannot be undone. A backup of each profile is saved first, but UKG has no restore.'),
    ('step', 'FAP name(s)', 'One name per line. Names must match exactly (case is ignored).'),
    ('step', 'Preview (read-only)', 'Looks every name up and lists what would be deleted. Deletes nothing.'),
    ('step', 'Delete FAP(s)', 'Looks the names up, shows a list (id, name, permission count) and asks you to '
                              'type DELETE (DELETE PRD in the PRD environment). The Delete button in that '
                              'dialog stays disabled until the word is typed exactly.'),
    ('bullet', 'A name that is not found, matches more than one FAP, or is a built-in profile is skipped; '
               'the others carry on.'),
    ('bullet', 'Each profile is saved to a backup file, deleted, then looked up again to confirm it is gone.'),
    ('bullet', 'One failure does not stop the rest. A summary at the end shows deleted / failed / skipped.'),
    ('warn', 'UKG refuses to delete a profile that is assigned to users or is Gold Data: "WCO-127807: This '
             'Function Access Profile is already in use or Gold Data, so could not be deleted." Remove the '
             'profile\'s assignments in UKG, then try again.'),

    ('h2', 'Payloads and the log'),
    ('body', 'Preview + Save Payload (Copy, Update) and Validate + Save Payload (Create) build the exact payload '
             'the real action sends - the same code builds both - and save it as dry_run_...json. The real '
             'action sends that same payload and saves it as payload.json. Delete has no payload (a DELETE '
             'sends no body); its Preview lists the FAPs and the requests it would send.'),
    ('body', 'Every run writes a log file in log/. It records each request with its URL (GET lookups, and the '
             'POST / PUT / DELETE for real runs). A real run also logs the full payload sent. A preview '
             'logs the write request as "WOULD SEND (not sent): <method> <url>" followed by the payload, so '
             'you can see the endpoint and body before running it for real.'),

    ('h2', 'Output and log files'),
    ('body', 'Folders are next to the program. Each run creates its own timestamped folder under output/.'),
    ('step', 'output/fap_create/', 'dry_run_<name>_<env>_<time>.json (Validate + Save Payload), or payload.json and '
                                   'response.json (real create).'),
    ('step', 'output/fap_read/', 'fap_read_<env>_<all, name or N_faps>_<time>.xlsx.'),
    ('step', 'output/fap_copy/', 'source.json (the FAP copied), payload.json or dry_run_...json, response.json.'),
    ('step', 'output/fap_update/', 'backup_<FAP>.json (before the update), payload.json or dry_run_...json, '
                                   'response.json.'),
    ('step', 'output/fap_delete/', 'backup/<FAP>_<id>.json for every deleted FAP, and results.json.'),
    ('step', 'output/fap_template/', '<FAP>_<env>_<time>.xlsx (Copy to Excel), all_control_points_<env>_<time>.xlsx.'),
    ('step', 'output/fap_payload/', 'dry_run_<name>_<time>.json (Create with Offline ticked).'),
    ('step', 'log/', 'A log file for each run (fap_create_..., fap_copy_..., fap_update_..., fap_delete_..., '
                     'fap_template_...).'),
    ('note', 'dry_run_ files are only for looking at; delete them whenever you like.'),

    ('h2', 'Messages and what to do'),
    ('step', 'Illegal value provided for actionName: X (HTTP 400, WCO-127815)',
     'UKG rejected an action for a control point and does not say which one. The Super Access check normally '
     'catches this first and names the control point.'),
    ('step', 'This Function Access Profile is already in use or Gold Data (WCO-127807)',
     'The FAP is assigned to users. Remove the assignments in UKG, then delete again.'),
    ('step', 'a FAP named "..." already exists', 'Choose a different name, or use the Update tab to change that FAP.'),
    ('step', 'FAP "..." does not exist', 'Check the spelling. The Output suggests similar names when it can.'),
    ('step', 'matches N FAPs; cannot choose', 'More than one FAP has that exact name. Nothing is changed.'),
    ('step', 'built-in profile (id -1)', 'Built-in profiles can be copied but not updated or deleted.'),
    ('step', 'control point not found in Super Access', 'Check the control point spelling in the Excel file.'),
    ('step', 'No Credential Profile', 'Create a profile with Save / Update Profile... for that environment '
                                      'and grant type.'),
    ('step', 'Authentication fails', 'Use Test Connection; check the profile with Save / Update Profile....'),

    ('h2', 'Command line'),
    ('body', 'Every tab also works as a command, from the UKG Tools folder. --env, --grant-type, --profile and '
             '--no-verify-ssl choose the connection; --dry-run runs the read-only checks only.'),
    ('code', 'python fap_create_tool.py --env NPR1 --file my_fap.xlsx --name "My FAP" --dry-run\n'
             'python fap_copy_tool.py --env NPR1 --dest-env UAT --source "Super Access" --name "My FAP" --dry-run\n'
             'python fap_template_tool.py --env NPR1 --source "Super Access"\n'
             'python fap_update_tool.py --env NPR1 --name "My FAP" --file changes.xlsx --add-new --allow-removals --dry-run\n'
             'python fap_delete_tool.py --env NPR1 --name "My FAP" --name "My FAP 2" --dry-run\n'
             'python fap_delete_tool.py --env NPR1 --name "My FAP" --confirm DELETE'),
    ('note', 'fap_delete_tool.py only deletes when --confirm DELETE (DELETE PRD in PRD) is given; otherwise it '
             'runs as a preview.'),

    ('h2', 'Tips'),
    ('bullet', 'Always run Preview / Validate + Save Payload first and read the Output before the real action.'),
    ('bullet', 'Test changes in NPR1 before UAT or PRD.'),
    ('bullet', 'Start from a template of a similar FAP instead of building a file by hand.'),
    ('bullet', 'Keep the backup files from Update and Delete runs until you are sure the change is right.'),
]


# ── Markdown ───────────────────────────────────────────────────────────────

def render_markdown(items=HELP) -> str:
    lines, in_list = [], False
    for item in items:
        kind = item[0]
        if kind != 'bullet' and kind != 'step' and in_list:
            lines.append('')
            in_list = False
        if kind == 'h1':
            lines += [f'# {item[1]}', '']
        elif kind == 'h2':
            lines += [f'## {item[1]}', '']
        elif kind == 'h3':
            lines += [f'### {item[1]}', '']
        elif kind == 'body':
            lines += [item[1], '']
        elif kind == 'bullet':
            lines.append(f'- {item[1]}')
            in_list = True
        elif kind == 'step':
            if re.fullmatch(r'\d+\.', item[1]):            # numbered step: "1. text"
                lines.append(f'{item[1]} {item[2]}')
            else:
                lines.append(f'- **{item[1]}** - {item[2]}')
            in_list = True
        elif kind == 'note':
            lines += [f'> **Note:** {item[1]}', '']
        elif kind == 'warn':
            lines += [f'> **Warning:** {item[1]}', '']
        elif kind == 'code':
            lines += ['```', item[1], '```', '']
        elif kind == 'gap':
            pass
    if in_list:
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def write_markdown(path: Path = DOC_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<!-- Generated from fap_manager_help.py - edit that file, then run: '
                    'python fap_manager_help.py --write-markdown -->\n\n' + render_markdown(),
                    encoding='utf-8')
    return path


# ── Help window ────────────────────────────────────────────────────────────

def show_help(parent):
    """Open the Help window (modal). Same look as the UKG Tools help."""
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(parent)
    win.title('FAP Manager - Help')
    win.minsize(760, 640)
    win.geometry('820x720')
    win.transient(parent)
    win.grab_set()

    txt = tk.Text(win, wrap='word', font=('Verdana', 10), bg='#ffffff', fg='#1a1a1a',
                  relief='flat', borderwidth=0, padx=16, pady=12, cursor='arrow')
    scroll = ttk.Scrollbar(win, command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    txt.pack(fill='both', expand=True)

    txt.tag_configure('h1', font=('Verdana', 13, 'bold'), spacing3=6)
    txt.tag_configure('h2', font=('Verdana', 10, 'bold'), spacing1=14, spacing3=4, foreground='#1f4e78')
    txt.tag_configure('h3', font=('Verdana', 10, 'bold'), spacing1=8, spacing3=2)
    txt.tag_configure('body', font=('Verdana', 10), lmargin1=16, lmargin2=16, spacing3=4)
    txt.tag_configure('label', font=('Verdana', 10, 'bold'), foreground='#0066cc')
    txt.tag_configure('item', font=('Verdana', 10), lmargin1=16, lmargin2=34, spacing3=3)
    txt.tag_configure('note', font=('Verdana', 9, 'italic'), lmargin1=16, lmargin2=16,
                      foreground='#666666', spacing3=4)
    txt.tag_configure('warn', font=('Verdana', 10), lmargin1=16, lmargin2=34,
                      foreground='#cc4400', spacing3=4)
    txt.tag_configure('code', font=('Courier New', 9), lmargin1=24, lmargin2=24,
                      background='#f3f3f3', spacing3=6)

    for item in HELP:
        kind = item[0]
        if kind in ('h1', 'h2', 'h3'):
            txt.insert('end', item[1] + '\n', kind)
        elif kind == 'body':
            txt.insert('end', item[1] + '\n', 'body')
        elif kind == 'bullet':
            txt.insert('end', '  •  ' + item[1] + '\n', 'item')
        elif kind == 'step':
            txt.insert('end', '  ' + item[1] + '  ', ('item', 'label'))
            txt.insert('end', item[2] + '\n', 'item')
        elif kind == 'note':
            txt.insert('end', '  ℹ  ' + item[1] + '\n', 'note')
        elif kind == 'warn':
            txt.insert('end', '  ⚠  ' + item[1] + '\n', 'warn')
        elif kind == 'code':
            txt.insert('end', item[1] + '\n', 'code')
        elif kind == 'gap':
            txt.insert('end', '\n')
    txt.configure(state='disabled')
    win.bind('<Escape>', lambda _: win.destroy())
    return win


def main():
    parser = argparse.ArgumentParser(description='FAP Manager documentation')
    parser.add_argument('--write-markdown', action='store_true',
                        help=f'Write the user manual to {DOC_FILE}')
    args = parser.parse_args()
    if args.write_markdown:
        print(f'Written: {write_markdown()}')
    else:
        sys.stdout.write(render_markdown())


if __name__ == '__main__':
    main()
