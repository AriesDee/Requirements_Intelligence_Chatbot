"""Automated tests for the FAP Manager tools (no network: a fake UKG is used).

Run from the UKG Tools folder:   python -m pytest tests/test_fap_manager.py
"""
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

import fap_copy_tool as copy_t
import fap_create_tool as fc
import fap_delete_tool as delete_t
import fap_read_tool as read_t
import fap_template_tool as tpl_t
import fap_tool
import fap_update_tool as upd_t
from fap_fakes import FakeUKG, perm, super_access


def methods(ukg):
    return [m for m, _ in ukg.calls]


# ─────────────────────────────── Excel parsing ────────────────────────────────

class TestReadPermissions:
    def test_valid_file(self, make_excel):
        path = make_excel([['PERSON', 'x', 'x', None, 'x', 'ALL'], ['TIMECARD', None, None, None, 'x', 'ONLY_SELF']])
        perms, warnings = fc.read_permissions(path)
        assert {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in perms} == {
            ('PERSON', 'ADD', 'ALL'), ('PERSON', 'EDIT', 'ALL'), ('PERSON', 'VIEW', 'ALL'),
            ('TIMECARD', 'VIEW', 'ONLY_SELF')}
        assert warnings == []

    def test_allowed_column_is_optional_but_read(self, make_excel):
        path = make_excel([['REPORTS', None, None, None, None, 'x', 'ALL']],
                          headers=['Control Point', 'ADD', 'EDIT', 'DELETE', 'VIEW', 'ALLOWED', 'scopeName'])
        perms, _ = fc.read_permissions(path)
        assert perms == [{'actionName': 'ALLOWED', 'scopeName': 'ALL', 'controlPointKey': 'REPORTS'}]

    def test_several_rows_per_control_point_with_different_scopes(self, make_excel):
        path = make_excel([['PERSON', 'x', None, None, None, 'ALL'], ['PERSON', None, 'x', None, None, 'ALL_BUT_SELF']])
        perms, _ = fc.read_permissions(path)
        assert {(p['actionName'], p['scopeName']) for p in perms} == {('ADD', 'ALL'), ('EDIT', 'ALL_BUT_SELF')}

    def test_scope_is_normalised(self, make_excel):
        perms, _ = fc.read_permissions(make_excel([['PERSON', 'x', None, None, None, 'all but self']]))
        assert perms[0]['scopeName'] == 'ALL_BUT_SELF'

    def test_all_problems_are_listed_together(self, make_excel):
        path = make_excel([['A', 'yes', None, None, None, 'ALL'],       # not x
                           ['B', 'x', None, None, None, 'EVERYONE'],     # bad scope
                           ['C', 'x', None, None, None, 'ALL'],
                           ['C', 'x', None, None, None, 'ALL']])         # duplicate
        with pytest.raises(fc.FapExcelError) as exc:
            fc.read_permissions(path)
        text = ' | '.join(exc.value.problems)
        assert len(exc.value.problems) == 3
        assert 'use x' in text and 'EVERYONE' in text and 'already defined' in text

    def test_missing_scope_column(self, make_excel):
        path = make_excel([], headers=['Control Point', 'ADD', 'EDIT', 'DELETE', 'VIEW'])
        with pytest.raises(fc.FapExcelError, match='scopeName'):
            fc.read_permissions(path)

    def test_no_header(self, make_excel):
        path = make_excel([], headers=['foo', 'bar'])
        with pytest.raises(fc.FapExcelError, match='No header row'):
            fc.read_permissions(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(fc.FapExcelError, match='File not found'):
            fc.read_permissions(tmp_path / 'nope.xlsx')

    def test_empty_template_has_no_permissions(self, tmp_path):
        path = fc.write_template(tmp_path / 'blank.xlsx', examples=False)
        assert [r for r in load_workbook(path)['FAP'].iter_rows(values_only=True)] == [
            ('Control Point', 'ADD', 'EDIT', 'DELETE', 'VIEW', 'scopeName')]
        with pytest.raises(fc.FapExcelError, match='No permissions'):
            fc.read_permissions(path)

    def test_many_unmarked_rows_give_one_warning(self, make_excel):
        rows = [[f'CP{i}', None, None, None, None, None] for i in range(20)] + [['PERSON', 'x', None, None, None, 'ALL']]
        perms, warnings = fc.read_permissions(make_excel(rows))
        assert len(perms) == 1 and len(warnings) == 1 and '20 row(s)' in warnings[0]

    def test_few_unmarked_rows_are_listed_individually(self, make_excel):
        rows = [['A', None, None, None, None, None], ['B', None, None, None, None, None],
                ['PERSON', 'x', None, None, None, 'ALL']]
        _, warnings = fc.read_permissions(make_excel(rows))
        assert len(warnings) == 2


# ───────────────────────────── payload validation ─────────────────────────────

class TestValidatePayload:
    def payload(self, perms=None, **over):
        p = fc.build_payload('X', 'desc', perms if perms is not None else [perm('PERSON', 'VIEW')])
        p.update(over)
        return p

    def test_good_payload(self):
        assert fc.validate_payload(self.payload()) == []

    def test_is_default_is_false(self):
        assert self.payload()['isDefault'] is False

    @pytest.mark.parametrize('bad,fragment', [
        (perm('PERSON', 'ADDD'), 'ADDD'),
        (perm('PERSON', 'VIEW', 'EVERYONE'), 'EVERYONE'),
        (perm('PER SON', 'VIEW'), 'PER SON'),
    ])
    def test_bad_permission(self, bad, fragment):
        problems = fc.validate_payload(self.payload([bad]))
        assert problems and any(fragment in p for p in problems)

    def test_duplicate_action(self):
        problems = fc.validate_payload(self.payload([perm('PERSON', 'VIEW'), perm('PERSON', 'VIEW', 'ONLY_SELF')]))
        assert any('PERSON' in p for p in problems)

    def test_empty_permissions_and_name(self):
        assert fc.validate_payload(self.payload([]))
        assert fc.validate_payload(self.payload(name=''))

    def test_check_keys_limits_per_permission_checks_but_not_duplicates(self):
        bad_other = perm('OTHER', 'NOPE')
        assert fc.validate_payload(self.payload([perm('PERSON', 'VIEW'), bad_other]), check_keys={'PERSON'}) == []
        dup = [perm('OTHER', 'VIEW'), perm('OTHER', 'VIEW')]
        assert fc.validate_payload(self.payload(dup), check_keys={'PERSON'})


# ───────────────────────── Super Access reference check ───────────────────────

class TestReferenceCheck:
    ref = super_access()['permissionTypes']

    def test_ok(self):
        assert fc.check_against_reference([perm('PERSON', 'ADD'), perm('REPORTS', 'ALLOWED')], self.ref) == []

    def test_unknown_control_point_reported_once(self):
        errs = fc.check_against_reference([perm('NOPE', 'ADD'), perm('NOPE', 'VIEW')], self.ref)
        assert len(errs) == 1 and 'NOPE' in errs[0]

    def test_invalid_action_for_control_point_names_it(self):
        errs = fc.check_against_reference([perm('TIMECARD', 'ADD')], self.ref)
        assert len(errs) == 1 and 'TIMECARD' in errs[0] and 'EDIT, VIEW' in errs[0]

    def test_reference_check_blocks_when_super_access_missing(self, capsys):
        assert fc.reference_check(FakeUKG(faps=[]), [perm('PERSON', 'ADD')], 'nothing was sent') is False
        assert 'not found' in capsys.readouterr().out

    def test_reference_check_passes(self, ukg, capsys):
        assert fc.reference_check(ukg, [perm('PERSON', 'ADD')], 'x') is True
        assert 'OK' in capsys.readouterr().out


# ───────────────────────────────── plan_update ────────────────────────────────

class TestPlanUpdate:
    current = [perm('PERSON', 'ADD'), perm('PERSON', 'VIEW'), perm('TIMECARD', 'VIEW'), perm('REPORTS', 'ALLOWED')]

    def test_changes_only_listed_control_points_and_keeps_the_rest(self):
        excel = [perm('PERSON', 'ADD', 'ONLY_SELF'), perm('PERSON', 'VIEW', 'ONLY_SELF')]
        new, updates, unchanged, skips = upd_t.plan_update(self.current, excel)
        assert [u[0] for u in updates] == ['PERSON'] and not unchanged and not skips
        assert {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in new} == {
            ('PERSON', 'ADD', 'ONLY_SELF'), ('PERSON', 'VIEW', 'ONLY_SELF'),
            ('TIMECARD', 'VIEW', 'ALL'), ('REPORTS', 'ALLOWED', 'ALL')}
        assert len(new) == 4

    def test_same_is_unchanged(self):
        _, updates, unchanged, _ = upd_t.plan_update(self.current, [perm('TIMECARD', 'VIEW')])
        assert not updates and unchanged == ['TIMECARD']

    def test_unknown_control_point_skipped_by_default(self):
        new, updates, _, skips = upd_t.plan_update(self.current, [perm('NEW', 'VIEW')])
        assert not updates and skips[0][0] == 'NEW' and len(new) == 4

    def test_add_new_adds(self):
        new, updates, _, skips = upd_t.plan_update(self.current, [perm('NEW', 'VIEW')], add_new=True)
        assert [u[0] for u in updates] == ['NEW'] and not skips and len(new) == 5

    def test_missing_action_skipped_by_default(self):
        new, updates, _, skips = upd_t.plan_update(self.current, [perm('PERSON', 'ADD')])
        assert not updates and 'VIEW' in skips[0][1] and len(new) == 4

    def test_allow_removals_removes_the_missing_action(self):
        new, updates, _, _ = upd_t.plan_update(self.current, [perm('PERSON', 'ADD')], allow_removals=True)
        assert [u[0] for u in updates] == ['PERSON']
        assert ('PERSON', 'VIEW', 'ALL') not in {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in new}
        assert len(new) == 3

    def test_input_is_not_modified(self):
        before = json.dumps(self.current)
        upd_t.plan_update(self.current, [perm('PERSON', 'ADD', 'NONE')], allow_removals=True)
        assert json.dumps(self.current) == before


# ──────────────────────────────── Create flow ─────────────────────────────────

class TestCreateRun:
    rows = [['PERSON', 'x', 'x', None, 'x', 'ALL']]

    def test_dry_run_saves_dry_run_file_and_creates_nothing(self, ukg, make_excel, tmp_path, capsys):
        assert fc.run(ukg, make_excel(self.rows), 'New FAP', '', tmp_path / 'out', dry_run=True)
        assert 'POST' not in methods(ukg) and ukg.by_name('New FAP') is None
        assert list((tmp_path / 'out' / 'fap_create').rglob('dry_run_New_FAP_NPR1_*.json'))
        assert 'DRY RUN' in capsys.readouterr().out

    def test_real_run_creates_with_the_same_payload(self, ukg, make_excel, tmp_path):
        out = tmp_path / 'out'
        assert fc.run(ukg, make_excel(self.rows), 'New FAP', 'my desc', out)
        created = ukg.by_name('New FAP')
        assert created['description'] == 'my desc' and len(created['permissionTypes']) == 3
        saved = json.loads(next((out / 'fap_create').rglob('payload.json')).read_text())
        assert saved['permissionTypes'] == created['permissionTypes'] and saved['isDefault'] is False

    def test_description_defaults_to_name(self, ukg, make_excel, tmp_path):
        fc.run(ukg, make_excel(self.rows), 'New FAP', '', tmp_path)
        assert ukg.by_name('New FAP')['description'] == 'New FAP'

    def test_existing_name_blocks_in_any_case(self, ukg, make_excel, tmp_path, capsys):
        ukg.add('New FAP', [perm('PERSON', 'VIEW')])
        assert not fc.run(ukg, make_excel(self.rows), 'new fap', '', tmp_path)
        assert 'POST' not in methods(ukg) and 'already exists' in capsys.readouterr().out

    def test_unknown_control_point_blocks(self, ukg, make_excel, tmp_path, capsys):
        assert not fc.run(ukg, make_excel([['NOPE', 'x', None, None, None, 'ALL']]), 'X1', '', tmp_path)
        assert 'POST' not in methods(ukg) and 'NOPE' in capsys.readouterr().out

    def test_invalid_action_blocks_and_names_the_control_point(self, ukg, make_excel, tmp_path, capsys):
        assert not fc.run(ukg, make_excel([['TIMECARD', 'x', None, None, None, 'ALL']]), 'X1', '', tmp_path)
        assert 'POST' not in methods(ukg) and 'TIMECARD' in capsys.readouterr().out

    def test_blocks_when_super_access_unreadable(self, make_excel, tmp_path):
        empty = FakeUKG(faps=[])
        assert not fc.run(empty, make_excel(self.rows), 'X1', '', tmp_path)
        assert 'POST' not in methods(empty)

    def test_bad_excel_blocks_before_connecting(self, ukg, make_excel, tmp_path):
        assert not fc.run(ukg, make_excel([['A', 'maybe', None, None, None, 'ALL']]), 'X1', '', tmp_path)
        assert ukg.calls == []

    def test_offline_save_payload_makes_no_calls(self, ukg, make_excel, tmp_path):
        assert fc.save_payload(make_excel(self.rows), 'Off', '', tmp_path)
        assert ukg.calls == []
        files = list((tmp_path / 'fap_payload').glob('dry_run_Off_*.json'))
        assert len(files) == 1 and json.loads(files[0].read_text())['name'] == 'Off'

    def test_save_payload_with_client_checks_super_access(self, ukg, make_excel, tmp_path):
        assert not fc.save_payload(make_excel([['NOPE', 'x', None, None, None, 'ALL']]), 'Off', '', tmp_path, ukg)
        assert not (tmp_path / 'fap_payload').exists()


# ──────────────────────────────── Update flow ─────────────────────────────────

class TestUpdateRun:
    def setup_method(self):
        self.ukg = FakeUKG()
        self.id = self.ukg.add('Team FAP', [perm('PERSON', 'ADD'), perm('PERSON', 'VIEW'),
                                            perm('TIMECARD', 'VIEW'), perm('REPORTS', 'ALLOWED')],
                               description='keep me')

    def test_update_changes_one_control_point_and_keeps_all_others(self, make_excel, tmp_path, capsys):
        path = make_excel([['PERSON', 'x', None, None, 'x', 'ONLY_SELF']])
        assert upd_t.run(self.ukg, path, 'Team FAP', '', tmp_path)
        got = {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in self.ukg.faps[self.id]['permissionTypes']}
        assert got == {('PERSON', 'ADD', 'ONLY_SELF'), ('PERSON', 'VIEW', 'ONLY_SELF'),
                       ('TIMECARD', 'VIEW', 'ALL'), ('REPORTS', 'ALLOWED', 'ALL')}
        assert self.ukg.faps[self.id]['description'] == 'keep me'
        assert 'Verified' in capsys.readouterr().out

    def test_backup_and_payload_saved(self, make_excel, tmp_path):
        upd_t.run(self.ukg, make_excel([['PERSON', 'x', None, None, 'x', 'NONE']]), 'Team FAP', '', tmp_path)
        folder = next((tmp_path / 'fap_update').iterdir())
        backup = json.loads(next(folder.glob('backup_*.json')).read_text())
        assert len(backup['permissionTypes']) == 4 and (folder / 'payload.json').exists()

    def test_dry_run_sends_no_put(self, make_excel, tmp_path):
        assert upd_t.run(self.ukg, make_excel([['PERSON', 'x', None, None, 'x', 'NONE']]),
                         'Team FAP', '', tmp_path, dry_run=True)
        assert 'PUT' not in methods(self.ukg)
        assert next((tmp_path / 'fap_update').rglob('dry_run_*.json'))

    def test_nothing_to_update(self, make_excel, tmp_path, capsys):
        assert not upd_t.run(self.ukg, make_excel([['TIMECARD', None, None, None, 'x', 'ALL']]), 'Team FAP', '', tmp_path)
        assert 'PUT' not in methods(self.ukg) and 'NOTHING TO UPDATE' in capsys.readouterr().out

    def test_missing_action_is_skipped_unless_removals_allowed(self, make_excel, tmp_path):
        path = make_excel([['PERSON', 'x', None, None, None, 'ALL']])
        assert not upd_t.run(self.ukg, path, 'Team FAP', '', tmp_path)
        assert upd_t.run(self.ukg, path, 'Team FAP', '', tmp_path, allow_removals=True)
        assert ('PERSON', 'VIEW') not in {(p['controlPointKey'], p['actionName'])
                                          for p in self.ukg.faps[self.id]['permissionTypes']}

    def test_new_control_point_needs_add_new(self, make_excel, tmp_path):
        small = FakeUKG()
        small.add('Small', [perm('PERSON', 'VIEW')])
        path = make_excel([['TIMECARD', None, 'x', None, 'x', 'ALL']])
        assert not upd_t.run(small, path, 'Small', '', tmp_path)           # not in profile, not added
        assert upd_t.run(small, path, 'Small', '', tmp_path, add_new=True)
        assert 'TIMECARD' in {p['controlPointKey'] for p in small.by_name('Small')['permissionTypes']}

    def test_built_in_profile_refused(self, make_excel, tmp_path, capsys):
        assert not upd_t.run(self.ukg, make_excel([['PERSON', 'x', None, None, None, 'ALL']]), 'Super Access', '', tmp_path)
        assert 'PUT' not in methods(self.ukg) and 'built-in' in capsys.readouterr().out

    def test_unknown_fap_name(self, make_excel, tmp_path, capsys):
        assert not upd_t.run(self.ukg, make_excel([['PERSON', 'x', None, None, None, 'ALL']]), 'Team FA', '', tmp_path)
        assert 'does not exist' in capsys.readouterr().out and 'PUT' not in methods(self.ukg)

    def test_unknown_control_point_blocks(self, make_excel, tmp_path):
        assert not upd_t.run(self.ukg, make_excel([['NOPE', 'x', None, None, None, 'ALL']]), 'Team FAP', '', tmp_path, add_new=True)
        assert 'PUT' not in methods(self.ukg)

    def test_new_description_is_used(self, make_excel, tmp_path):
        upd_t.run(self.ukg, make_excel([['PERSON', 'x', None, None, 'x', 'NONE']]), 'Team FAP', 'new text', tmp_path)
        assert self.ukg.faps[self.id]['description'] == 'new text'


# ──────────────────────────────── Delete flow ─────────────────────────────────

class TestDelete:
    def test_parse_names(self):
        assert delete_t.parse_names('A\n\n  b \na\nB\nC') == ['A', 'b', 'C']

    def test_confirmation_word(self):
        assert delete_t.confirmation_word('NPR1') == 'DELETE'
        assert delete_t.confirmation_word('PRD') == 'DELETE PRD'

    def test_dry_run_deletes_nothing(self, ukg, tmp_path, capsys):
        ukg.add('Tmp', [perm('PERSON', 'VIEW')])
        assert delete_t.run(ukg, ['Tmp'], tmp_path, dry_run=True)
        assert 'DELETE' not in methods(ukg) and ukg.by_name('Tmp')
        assert 'DRY RUN' in capsys.readouterr().out

    def test_without_confirmation_nothing_is_deleted(self, ukg, tmp_path, capsys):
        ukg.add('Tmp', [perm('PERSON', 'VIEW')])
        assert not delete_t.run(ukg, ['Tmp'], tmp_path)
        assert not delete_t.run(ukg, ['Tmp'], tmp_path, confirm=lambda t, w: False)
        assert ukg.by_name('Tmp') and 'CANCELLED' in capsys.readouterr().out

    def test_confirmed_delete_backs_up_first_and_verifies(self, ukg, tmp_path, capsys):
        fid = ukg.add('Tmp', [perm('PERSON', 'VIEW')])
        asked = []
        assert delete_t.run(ukg, ['tmp'], tmp_path, confirm=lambda t, w: asked.append((len(t), w)) or True)
        assert asked == [(1, 'DELETE')] and ukg.by_name('Tmp') is None
        backups = list((tmp_path / 'fap_delete').rglob(f'*_{fid}.json'))
        assert len(backups) == 1 and json.loads(backups[0].read_text())['name'] == 'Tmp'
        assert 'DELETED' in capsys.readouterr().out

    def test_prd_asks_for_the_longer_word(self, tmp_path):
        prd = FakeUKG(env='PRD')
        prd.add('Tmp', [perm('PERSON', 'VIEW')])
        asked = []
        delete_t.run(prd, ['Tmp'], tmp_path, confirm=lambda t, w: asked.append(w) or False)
        assert asked == ['DELETE PRD']

    def test_in_use_fap_fails_with_ukg_message_and_hint(self, ukg, tmp_path, capsys):
        fid = ukg.add('Used', [perm('PERSON', 'VIEW')])
        ukg.in_use.add(fid)
        assert not delete_t.run(ukg, ['Used'], tmp_path, confirm=lambda t, w: True)
        out = capsys.readouterr().out
        assert ukg.by_name('Used') and 'WCO-127807' in out and 'assigned' in out
        assert json.loads(next((tmp_path / 'fap_delete').rglob('results.json')).read_text())['results'][0]['result'] == 'failed'

    def test_one_failure_does_not_stop_the_rest(self, ukg, tmp_path):
        a = ukg.add('A', [perm('PERSON', 'VIEW')])
        ukg.add('B', [perm('PERSON', 'VIEW')])
        ukg.in_use.add(a)
        assert not delete_t.run(ukg, ['A', 'B'], tmp_path, confirm=lambda t, w: True)
        assert ukg.by_name('A') and ukg.by_name('B') is None

    def test_missing_and_built_in_are_skipped(self, ukg, tmp_path, capsys):
        ukg.add('Tmp', [perm('PERSON', 'VIEW')])
        assert delete_t.run(ukg, ['Nope', 'Super Access', 'Tmp'], tmp_path, confirm=lambda t, w: True)
        out = capsys.readouterr().out
        assert 'does not exist' in out and 'built-in' in out
        assert ukg.by_name('Super Access') and ukg.by_name('Tmp') is None

    def test_no_names(self, ukg, tmp_path):
        assert not delete_t.run(ukg, ['  '], tmp_path, confirm=lambda t, w: True)
        assert ukg.calls == []


# ───────────────────────────────── Copy flow ──────────────────────────────────

class TestCopy:
    def test_same_environment_copy(self, ukg, tmp_path):
        ukg.add('Src', [perm('PERSON', 'VIEW'), perm('TIMECARD', 'EDIT', 'ONLY_SELF')], description='old')
        assert copy_t.run(ukg, ukg, 'Src', 'Dst', '', tmp_path)
        dst = ukg.by_name('Dst')
        assert dst['permissionTypes'] == ukg.by_name('Src')['permissionTypes']
        assert dst['description'] == 'Dst' and dst['isDefault'] is False and dst['id'] != ukg.by_name('Src')['id']

    def test_cross_environment_copy(self, tmp_path):
        npr, uat = FakeUKG('NPR1'), FakeUKG('UAT', faps=[])
        npr.add('Src', [perm('PERSON', 'VIEW')])
        assert copy_t.run(npr, uat, 'Src', 'Dst', 'd', tmp_path)
        assert uat.by_name('Dst') and 'POST' not in methods(npr)

    def test_built_in_can_be_copied(self, ukg, tmp_path):
        assert copy_t.run(ukg, ukg, 'Super Access', 'My Super', '', tmp_path)
        assert len(ukg.by_name('My Super')['permissionTypes']) == len(super_access()['permissionTypes'])

    def test_preview_creates_nothing_and_saves_dry_run_file(self, ukg, tmp_path):
        ukg.add('Src', [perm('PERSON', 'VIEW')])
        assert copy_t.run(ukg, ukg, 'Src', 'Dst', '', tmp_path, dry_run=True)
        assert ukg.by_name('Dst') is None and 'POST' not in methods(ukg)
        assert list((tmp_path / 'fap_copy').rglob('dry_run_Dst_NPR1_*.json'))

    def test_existing_destination_name_blocks(self, ukg, tmp_path):
        ukg.add('Src', [perm('PERSON', 'VIEW')])
        ukg.add('Dst', [perm('PERSON', 'VIEW')])
        assert not copy_t.run(ukg, ukg, 'Src', 'dst', '', tmp_path)

    def test_missing_source_and_same_name(self, ukg, tmp_path):
        assert not copy_t.run(ukg, ukg, 'Nope', 'Dst', '', tmp_path)
        ukg.add('Src', [perm('PERSON', 'VIEW')])
        assert not copy_t.run(ukg, ukg, 'Src', 'SRC', '', tmp_path)
        assert 'POST' not in methods(ukg)


# ───────────────────────── Templates (Copy to Excel, Create) ──────────────────

class TestTemplates:
    def test_exported_template_reads_back_as_the_same_permissions(self, ukg, tmp_path):
        perms = [perm('PERSON', 'ADD'), perm('PERSON', 'EDIT', 'ALL_BUT_SELF'), perm('TIMECARD', 'VIEW', 'ONLY_SELF'),
                 perm('REPORTS', 'ALLOWED', 'NONE')]
        ukg.add('Src', perms)
        result = {}
        assert tpl_t.run(ukg, 'Src', tmp_path, result)
        back, _ = fc.read_permissions(result['path'])
        key = lambda ps: {(p['controlPointKey'], p['actionName'], p['scopeName']) for p in ps}
        assert key(back) == key(perms) and Path(result['path']).parent == tmp_path / 'fap_template'

    def test_export_unknown_fap(self, ukg, tmp_path):
        result = {}
        assert not tpl_t.run(ukg, 'Nope', tmp_path, result) and 'path' not in result

    def test_all_control_points_template_is_sorted_and_empty(self, ukg, tmp_path):
        assert tpl_t.run_all_control_points(ukg, tmp_path)
        f = next((tmp_path / 'fap_template').glob('all_control_points_NPR1_*.xlsx'))
        wb = load_workbook(f)
        rows = list(wb['FAP'].iter_rows(values_only=True))
        assert [r[0] for r in rows[1:]] == ['PERSON', 'REPORTS', 'TIMECARD']
        assert all(not any(r[1:]) for r in rows[1:])
        valid = dict(list(wb['Valid Actions'].iter_rows(values_only=True))[1:])
        assert valid['TIMECARD'] == 'EDIT, VIEW' and valid['REPORTS'] == 'ALLOWED'

    def test_all_control_points_template_is_usable_once_filled(self, ukg, tmp_path):
        tpl_t.run_all_control_points(ukg, tmp_path)
        f = next((tmp_path / 'fap_template').glob('all_control_points_*.xlsx'))
        wb = load_workbook(f)
        ws = wb['FAP']
        ws['E2'], ws['G2'] = 'x', 'ALL'              # PERSON VIEW
        wb.save(f)
        perms, warnings = fc.read_permissions(f)
        assert perms == [{'actionName': 'VIEW', 'scopeName': 'ALL', 'controlPointKey': 'PERSON'}]
        assert len(warnings) == 2                       # the other two control points: warnings only

    def test_all_control_points_needs_super_access(self, tmp_path):
        assert not tpl_t.run_all_control_points(FakeUKG(faps=[]), tmp_path)


# ───────────────────────────────── Read flow ──────────────────────────────────

class TestRead:
    def test_read_all(self, ukg, tmp_path):
        ukg.add('B', [perm('PERSON', 'VIEW'), perm('PERSON', 'ADD')])
        assert read_t.run(ukg, '', tmp_path)
        f = next((tmp_path / 'fap_read').glob('fap_read_NPR1_all_*.xlsx'))
        wb = load_workbook(f)
        fap_rows = list(wb['FAPs'].iter_rows(values_only=True))
        assert [r[1] for r in fap_rows[1:]] == ['B', 'Super Access']        # sorted, case-insensitive
        assert fap_rows[1][4] == 2 and fap_rows[1][5] == 1                  # permissions, control points
        assert wb['Permissions'].max_row == 1 + 2 + len(super_access()['permissionTypes'])
        assert ukg.calls[-1] == ('GET', '/api/v1/commons/function_access_profiles')

    def test_read_one_by_exact_name(self, ukg, tmp_path):
        ukg.add('Team', [perm('PERSON', 'VIEW')])
        assert read_t.run(ukg, 'team', tmp_path)
        f = next((tmp_path / 'fap_read').glob('fap_read_NPR1_team_*.xlsx'))
        assert load_workbook(f)['FAPs'].max_row == 2
        assert ukg.calls[-1][1].endswith('?name=team')

    def test_partial_name_finds_nothing(self, ukg, tmp_path, capsys):
        assert not read_t.run(ukg, 'Super Acces', tmp_path)
        out = capsys.readouterr().out
        assert 'NOTHING FOUND' in out and 'WCO-127822' in out
        assert not (tmp_path / 'fap_read').exists()


# ─────────────────────────────── fap_tool lookup ──────────────────────────────

class TestFetchFap:
    def test_unknown_name_gives_empty_list(self, ukg):
        assert fap_tool.fetch_fap(ukg, 'Nope') == []

    def test_unknown_name_is_recognised_whatever_the_status(self):
        class Odd(FakeUKG):
            def request(self, method, path, **k):
                r = super().request(method, path, **k)
                r.status_code = 400
                return r
        assert fap_tool.fetch_fap(Odd(), 'Nope') == []

    def test_other_errors_still_raise(self):
        class Broken(FakeUKG):
            def request(self, *a, **k):
                from fap_fakes import FakeResponse
                return FakeResponse(500, {'message': 'boom'})
        with pytest.raises(Exception):
            fap_tool.fetch_fap(Broken(), 'X')

    def test_name_is_url_encoded(self, ukg):
        fap_tool.fetch_fap(ukg, 'Super Access')
        assert ukg.calls[-1][1].endswith('?name=Super%20Access')


# ───────────────────── payload / endpoint recorded in the log ─────────────────

class TestLogging:
    """The tools log through ukg_api_tool.logger; the log file gets the same records."""

    @pytest.fixture(autouse=True)
    def _capture(self, caplog):
        import logging
        import ukg_api_tool
        ukg_api_tool.logger.propagate = True
        caplog.set_level(logging.DEBUG, logger=ukg_api_tool.logger.name)
        self.caplog = caplog

    def test_create_preview_logs_would_send_with_payload(self, ukg, make_excel, tmp_path):
        fc.run(ukg, make_excel([['PERSON', 'x', None, None, None, 'ALL']]), 'LogMe', '', tmp_path, dry_run=True)
        text = self.caplog.text
        assert 'WOULD SEND (not sent): POST https://npr1.example.com/api/v1/commons/function_access_profiles' in text
        assert '"name": "LogMe"' in text and 'POST' not in methods(ukg)

    def test_create_real_run_logs_endpoint_and_payload(self, ukg, make_excel, tmp_path):
        fc.run(ukg, make_excel([['PERSON', 'x', None, None, None, 'ALL']]), 'LogMe', '', tmp_path)
        text = self.caplog.text
        assert 'POST https://npr1.example.com' in text and 'POST payload:' in text and 'WOULD SEND' not in text

    def test_update_and_delete_preview_log_the_endpoint(self, ukg, make_excel, tmp_path):
        fid = ukg.add('Team', [perm('PERSON', 'ADD'), perm('PERSON', 'VIEW')])
        upd_t.run(ukg, make_excel([['PERSON', 'x', None, None, 'x', 'NONE']]), 'Team', '', tmp_path, dry_run=True)
        delete_t.run(ukg, ['Team'], tmp_path, dry_run=True)
        text = self.caplog.text
        base = 'https://npr1.example.com/api/v1/commons/function_access_profiles'
        assert f'WOULD SEND (not sent): PUT {base}/{fid}' in text and 'PUT payload:' in text
        assert f'WOULD SEND (not sent): DELETE {base}/{fid}' in text
