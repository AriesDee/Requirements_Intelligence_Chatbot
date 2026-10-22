<!-- Generated from fap_manager_help.py - edit that file, then run: python fap_manager_help.py --write-markdown -->

# FAP Manager - User Guide

FAP Manager creates, copies, updates and deletes UKG Function Access Profiles (FAPs) without writing any API calls. It is a separate app from UKG Tools and uses the same connection method: pick the environment and a saved credential profile once, and every tab uses it.

A FAP is a list of permissions. Each permission is a control point (controlPointKey), an action (ADD, EDIT, DELETE, VIEW or ALLOWED) and a scope (ALL, ALL_BUT_SELF, ONLY_SELF or NONE).

## Quick start

1. Choose the Environment and Grant type, then pick a credential Profile (or create one with Save / Update Profile...).
2. Click Test Connection once to confirm the credentials work.
3. Open the tab for what you want to do. Every tab that changes UKG has a read-only Preview / Validate + Save Payload button - run it first, read the Output, then run the real action.
4. Everything the app does is written to the Output area at the bottom, and files are saved in the output folder (see "Output and log files").

## Tabs at a glance

- Read - read all FAPs, or the one FAP with a given name, into an Excel report.
- Copy - copy an existing FAP to a new name (same or another environment), or export it to an Excel file you can edit.
- Create - create a new FAP from an Excel file. Also: blank templates, and Validate + Save Payload (which saves the payload, optionally without connecting).
- Update - change control points of an existing FAP from an Excel file.
- Delete - delete one or more FAPs by name.

## Connection panel (top of the window)

Used by every tab. For the Copy tab it is the source. Your last Environment, Grant type and SSL choice are remembered.

- **Environment** - NPR1, UAT or PRD. PRD shows a red PRODUCTION warning; every action that changes PRD asks for an extra confirmation.
- **Grant type** - client_credentials or password. Each environment has its own profiles per grant type.
- **Profile** - The saved credentials to use. FAP Manager uses saved local profiles only (secrets are kept in Windows Credential Manager). The last profile used for an environment is selected automatically.
- **Save / Update Profile...** - Create a new profile for the chosen environment and grant type, or update the selected one. Saving a name that already exists overwrites it.
- **Delete** - Delete the selected profile and its stored secrets. Profiles are shared with UKG Tools and the Stonebranch UI, so this removes it there too.
- **Test Connection** - Requests a token with the selected profile and says whether it worked.
- **Skip SSL verification** - Needed on the corporate network. Leave it ticked unless told otherwise.

> **Note:** Key Vault credentials are not offered here. They can only be set up in the Stonebranch UI.

## The Excel file (Create, Update)

The first sheet is read. A header row is searched for in the first 10 rows; column order does not matter.

```
Control Point                      | ADD | EDIT | DELETE | VIEW | ALLOWED | scopeName
WFS_BASELINE_STAFF_PATTERN_VIEW   |  x  |  x   |   x    |  x   |         | ALL
SA_DISPLAY_DAY_BEFORE_AND_AFTER   |     |      |        |      |    x    | ALL
PERSON                            |  x  |      |        |      |         | ALL
PERSON                            |     |  x   |        |      |         | ALL_BUT_SELF
```

- **Control Point** - The controlPointKey ("controlPointKey" is also accepted as the header).
- **ADD, EDIT, DELETE, VIEW** - These four columns are required. Put x where the profile has that action; leave blank otherwise. Anything other than x is an error.
- **ALLOWED** - Optional column, marked the same way. Many control points use ALLOWED instead of ADD/EDIT/DELETE/VIEW.
- **scopeName** - ALL, ALL_BUT_SELF, ONLY_SELF or NONE. It applies to every x on that row (upper/lower case, spaces or hyphens are fine: "all but self" works).
- A control point can have several rows when its actions need different scopes (see PERSON above).
- The same control point + action twice is an error.
- A row with no x is skipped with a warning (when there are many, one summary line); blank rows are ignored.
- All problems found in the file are listed together, with row numbers, so you can fix them in one pass.

> **Note:** The easiest way to get a correct file: Copy tab -> Copy to "Excel file" from a FAP that is close to what you want, then edit it. Or start from the Create tab's templates.

## Checks before anything is sent

Create and Update stop - and send nothing - if any of these fail. All problems of a check are listed at once.

- **1. Excel file** - Valid layout, only x marks, valid scope names, no repeated control point + action.
- **2. Payload** - The request itself is validated: a name is present; every action is one of ADD, EDIT, DELETE, VIEW, ALLOWED; every scope is one of ALL, ALL_BUT_SELF, ONLY_SELF, NONE; every permission has all three fields; control point keys contain no spaces; no control point repeats an action.
- **3. Name (Create, Copy)** - A FAP with that exact name must not already exist in the environment (upper/lower case is ignored). Update and Delete need the name to exist.
- **4. Super Access** - Every control point and action is compared with the built-in Super Access profile in that environment (Create, Update). Skipped by Create's Offline option.

> **Warning:** Assumption: the UKG API documentation does not say which control points (keys) or which actions per control point are valid. FAP Manager assumes Super Access contains every control point and every action that is valid for it, and uses it as the basis for correctness. An unknown control point, an action Super Access does not have for that control point, or Super Access being unreadable, stops the run.

> **Note:** Scopes are only checked against the four documented values. Anything else UKG might reject is reported by UKG itself when the request is sent, and its message is shown in the Output.

## Read tab

Reads FAPs from the Connection panel environment and saves an Excel report. Read-only.

- **FAP name** - Leave blank to read ALL FAPs. With a name, only the FAP with exactly that name is read. A partial or misspelled name finds nothing: UKG answers WCO-127822 "A Function Access Profile does not exist with specified name".
- **Read to Excel** - Saves output/fap_read/fap_read_<env>_<all or name>_<time>.xlsx with a FAPs sheet (id, name, description, isDefault, permission count, control point count), a Permissions sheet (FAP, id, control point, action, scope) and a Notes sheet.
- **Open Read Folder** - Opens the folder where reports are saved.

> **Note:** The report is for looking at. To get a FAP in the layout the Create and Update tabs read, use Copy -> "Excel file".

## Copy tab

Reads an existing FAP and creates a new one with exactly the same permissions. The source is only read, so built-in profiles such as Super Access can be copied.

- **Source FAP name** - The FAP to copy, in the Connection panel environment. Exact name match.
- **Destination environment** - Same as the Connection panel for a copy within one environment, or another environment for a cross-environment copy (for example NPR1 to UAT). The line under it says which kind of copy this is.
- **Profile** - Credentials for the destination environment (cross-environment only; same grant type). The last profile used for that environment is selected. If there is none, create one by selecting that environment in the Connection panel and using Save / Update Profile...
- **New FAP name** - Required. Must differ from the source name when copying within one environment, and must not already exist in the destination.
- **Description** - Optional; defaults to the new name.
- **Preview + Save Payload** - Runs every check and saves the payload as dry_run_...json. Creates nothing.
- **Copy FAP** - Asks for confirmation (with an extra PRODUCTION warning when the destination is PRD), then creates the FAP.

> **Note:** A cross-environment copy fails at UKG if a control point does not exist in the destination environment; UKG's message is shown and the payload is kept in the output folder.

### Copy to: Excel file (template for Create)

Choose "Excel file" under "Copy to" to export the source FAP instead of creating a new one. Edit the file (add or delete control points, change actions and scopes), then use it on the Create tab. Destination, New FAP name and Description are not used.

- **Create Template** - Writes the Excel file with one row per control point and scope, an ALLOWED column, and a Notes sheet that says which FAP and environment it came from. Saved in output/fap_template/.
- **Open Template Folder** - Opens the folder where templates are saved.
- After writing, the file is read back and compared with the FAP; the Output says whether it matches exactly.
- An action that has no column (anything other than ADD, EDIT, DELETE, VIEW, ALLOWED) is left out with a warning.

## Create tab

Creates a new FAP from an Excel file.

- **Name** - Required. The new FAP's name.
- **Description** - Optional; defaults to the name.
- **Excel file** - Choose it with Browse....
- **Validate + Save Payload** - Runs every check (it connects to UKG, read-only) and saves the exact payload as dry_run_...json. Creates nothing. "DRY RUN - the Excel file is valid..." means the file passed.
- **Create FAP** - Asks for confirmation (extra warning on PRD), runs the same checks, then creates the FAP. The payload it sends is the same one Validate + Save Payload saved.
- **Offline** - Tick it to make Validate + Save Payload work without connecting to UKG: it checks just the Excel file and the payload (no name check, no Super Access check) and saves the payload as dry_run_<name>_<time>.json in output/fap_payload/. Create FAP is not available while Offline is ticked.
- **Open Output Folder** - Opens the output folder.
- **Blank Template...** - Saves an Excel file with only the header row. No connection is needed. Use it to build a FAP from scratch.
- **All Control Points Template** - Lists every control point of Super Access (from the Connection panel environment), with the action and scope cells empty. Mark x and fill scopeName on the rows you want; rows with nothing marked are ignored. A "Valid Actions" sheet shows which actions each control point accepts. Saved in output/fap_template/.
- **Open Template Folder** - Opens the folder where templates are saved.

> **Note:** Order of checks: Excel file, payload, name does not exist, Super Access. isDefault is always false.

## Update tab

Changes control points of an existing FAP from an Excel file.

> **Warning:** UKG replaces the whole permission list on update: anything left out of the request is removed. So FAP Manager reads the profile as it is now, changes only the control points in your Excel file, and sends the complete list back. Every other control point stays exactly as it is.

- **FAP name** - The FAP to update. Exact name match. The name cannot be changed here.
- **Description** - Optional. Leave blank to keep the existing description.
- **Excel file** - Only the control points listed in it are looked at.
- **Add control points that are not in the profile** - Off by default. Off: a control point that is not in the profile is skipped ("not in profile, not added"). On: it is added.
- **Allow removing actions** - Off by default. Off: a control point whose Excel row leaves out an action the profile has is skipped (nothing is removed). On: the left-out action is removed.
- **Export Current FAP to Excel** - Writes the FAP named above to an Excel file (same file as Copy -> "Excel file") and puts it in the Excel file box, ready to edit. Edit it, save and close it, then run Preview.
- **Preview + Save Payload** - Shows what would change and saves the payload as dry_run_...json.
- **Update FAP** - Asks for confirmation (extra warning on PRD; the dialog repeats any option that is on), then sends the update.

The Output lists each control point:

- UPDATE - changed; shows before and after. "** REMOVES VIEW **" marks removed actions.
- ADD - a new control point added to the profile.
- SAME - already matches the Excel file.
- SKIP - not changed, with the reason.

Before sending, the profile is saved to a backup file. After a successful update it is read back and compared: "Verified: the profile now has exactly the N permission(s) sent."

The run stops without sending anything when: the Excel file or payload is invalid, the name is not found or matches more than one FAP, the FAP is built-in (negative id, for example Super Access), a control point or action fails the Super Access check, or nothing would change.

> **Note:** To restore a profile, use the backup_...json file saved in the run's folder.

## Delete tab

> **Warning:** Deleting a FAP cannot be undone. A backup of each profile is saved first, but UKG has no restore.

- **FAP name(s)** - One name per line. Names must match exactly (case is ignored).
- **Preview (read-only)** - Looks every name up and lists what would be deleted. Deletes nothing.
- **Delete FAP(s)** - Looks the names up, shows a list (id, name, permission count) and asks you to type DELETE (DELETE PRD in the PRD environment). The Delete button in that dialog stays disabled until the word is typed exactly.
- A name that is not found, matches more than one FAP, or is a built-in profile is skipped; the others carry on.
- Each profile is saved to a backup file, deleted, then looked up again to confirm it is gone.
- One failure does not stop the rest. A summary at the end shows deleted / failed / skipped.

> **Warning:** UKG refuses to delete a profile that is assigned to users or is Gold Data: "WCO-127807: This Function Access Profile is already in use or Gold Data, so could not be deleted." Remove the profile's assignments in UKG, then try again.

## Payloads and the log

Preview + Save Payload (Copy, Update) and Validate + Save Payload (Create) build the exact payload the real action sends - the same code builds both - and save it as dry_run_...json. The real action sends that same payload and saves it as payload.json. Delete has no payload (a DELETE sends no body); its Preview lists the FAPs and the requests it would send.

Every run writes a log file in log/. It records each request with its URL (GET lookups, and the POST / PUT / DELETE for real runs). A real run also logs the full payload sent. A preview logs the write request as "WOULD SEND (not sent): <method> <url>" followed by the payload, so you can see the endpoint and body before running it for real.

## Output and log files

Folders are next to the program. Each run creates its own timestamped folder under output/.

- **output/fap_create/** - dry_run_<name>_<env>_<time>.json (Validate + Save Payload), or payload.json and response.json (real create).
- **output/fap_read/** - fap_read_<env>_<all or name>_<time>.xlsx.
- **output/fap_copy/** - source.json (the FAP copied), payload.json or dry_run_...json, response.json.
- **output/fap_update/** - backup_<FAP>.json (before the update), payload.json or dry_run_...json, response.json.
- **output/fap_delete/** - backup/<FAP>_<id>.json for every deleted FAP, and results.json.
- **output/fap_template/** - <FAP>_<env>_<time>.xlsx (Copy to Excel), all_control_points_<env>_<time>.xlsx.
- **output/fap_payload/** - dry_run_<name>_<time>.json (Create with Offline ticked).
- **log/** - A log file for each run (fap_create_..., fap_copy_..., fap_update_..., fap_delete_..., fap_template_...).

> **Note:** dry_run_ files are only for looking at; delete them whenever you like.

## Messages and what to do

- **Illegal value provided for actionName: X (HTTP 400, WCO-127815)** - UKG rejected an action for a control point and does not say which one. The Super Access check normally catches this first and names the control point.
- **This Function Access Profile is already in use or Gold Data (WCO-127807)** - The FAP is assigned to users. Remove the assignments in UKG, then delete again.
- **a FAP named "..." already exists** - Choose a different name, or use the Update tab to change that FAP.
- **FAP "..." does not exist** - Check the spelling. The Output suggests similar names when it can.
- **matches N FAPs; cannot choose** - More than one FAP has that exact name. Nothing is changed.
- **built-in profile (id -1)** - Built-in profiles can be copied but not updated or deleted.
- **control point not found in Super Access** - Check the control point spelling in the Excel file.
- **No Credential Profile** - Create a profile with Save / Update Profile... for that environment and grant type.
- **Authentication fails** - Use Test Connection; check the profile with Save / Update Profile....

## Command line

Every tab also works as a command, from the UKG Tools folder. --env, --grant-type, --profile and --no-verify-ssl choose the connection; --dry-run runs the read-only checks only.

```
python fap_create_tool.py --env NPR1 --file my_fap.xlsx --name "My FAP" --dry-run
python fap_copy_tool.py --env NPR1 --dest-env UAT --source "Super Access" --name "My FAP" --dry-run
python fap_template_tool.py --env NPR1 --source "Super Access"
python fap_update_tool.py --env NPR1 --name "My FAP" --file changes.xlsx --add-new --allow-removals --dry-run
python fap_delete_tool.py --env NPR1 --name "My FAP" --name "My FAP 2" --dry-run
python fap_delete_tool.py --env NPR1 --name "My FAP" --confirm DELETE
```

> **Note:** fap_delete_tool.py only deletes when --confirm DELETE (DELETE PRD in PRD) is given; otherwise it runs as a preview.

## Tips

- Always run Preview / Validate + Save Payload first and read the Output before the real action.
- Test changes in NPR1 before UAT or PRD.
- Start from a template of a similar FAP instead of building a file by hand.
- Keep the backup files from Update and Delete runs until you are sure the change is right.
