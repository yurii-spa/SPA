"""Regressions for Governance / Operations / Recovery (Director OS Phase 8).

The risk here is quiet reassurance: calling a derived index an authority, inventing an
approval, reading a backup archive as proof of restore, or a written runbook as a tested
one. Each test below pins one of those.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gov = _load('governance')
pr = _load('portal_render')

CLAUDE_MD = """# SPA

## 🔒 Инварианты (нарушать нельзя)

1. **Детерминированный RiskPolicy v1.0 — единственный hard-гейт.** Текст.
7. **Никаких секретов в файлах** — ключи из Keychain.

### 🚦 Граница «решай сам» / «спроси меня» — ПО ПРЕДМЕТУ (ADR-285)

За владельцем остаются ровно три предмета. Всё остальное агент решает сам и фиксирует
записью в журнал, а не вопросом.
"""


def _prod(td, **over):
    root = Path(td) / 'prod'
    for sub in ('docs/decisions', 'docs/adr', '.claude/rules', 'data/backups',
                'scripts'):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / 'CLAUDE.md').write_text(CLAUDE_MD)
    (root / 'docs/decisions/ADR-001-one.md').write_text('# ADR-001 Первое решение\n')
    (root / 'docs/decisions/ADR-050-dup.md').write_text('# ADR-050 В первом реестре\n')
    (root / 'docs/adr/ADR-050-dup.md').write_text('# ADR-050 Во втором реестре\n')
    (root / 'docs/decisions/INDEX.md').write_text('# ADR INDEX\n')
    (root / '.claude/rules/deployment.md').write_text('# Rule · Доставка\n')
    (root / '.claude/rules/risk-engine.md').write_text('# Rule · Risk engine\n')
    (root / 'docs/DISASTER_RECOVERY.md').write_text('# восстановление\nшаги\n')
    (root / 'docs/RUNBOOK.md').write_text('# runbook\n')
    (root / 'scripts/code_sync_from_origin.sh').write_text('#!/bin/bash\n# CODE ONLY\n')
    (root / 'data/backups/spa_state.tar.gz').write_bytes(b'x')

    docs = {
        'restore_drill_status.json': {
            'all_ok': True, 'archive': 'spa_state.tar.gz',
            'last_drill_ts': '2026-09-20T14:58:10+00:00',
            'files_validated': [{'file': 'golive_status.json', 'ok': True}]},
        'dr_offsite_status.json': {'last_offsite_ts': '2026-09-20T14:58:10Z',
                                   'verified': True, 'n_offsite_kept': 28,
                                   'is_real_remote': False},
        'deployment_acceptance.json': {'status': 'OK',
                                       'checked_at': '2026-09-20T06:00:09+00:00',
                                       'entrypoints_total': 81,
                                       'entrypoints_broken': []},
        'code_sync_status.json': {'timestamp': '2026-09-20T16:29:32+00:00',
                                  'result': 'SYNCED', 'files_changed': 4,
                                  'retired_code': ['scripts/old.py']},
        'security_alerts.json': [],
        'kill_switch_status.json': {'generated_at': '2026-09-20T16:38:30+00:00',
                                    'triggered': False, 'reason': 'all triggers clear'},
    }
    docs.update(over)
    for name, body in docs.items():
        (root / 'data' / name).write_text(json.dumps(body, ensure_ascii=False))
    return root


def _build(td, **kw):
    return gov.build_governance_snapshot(kw.get('production') or _prod(td))


def _by(s, gid):
    return [i for i in s['items'] if i['governance_id'] == gid][0]


class AuthorityIsQuotedNotAssumed(unittest.TestCase):
    def test_the_adr_index_is_not_treated_as_the_authority(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rec = [x for x in s['sources'] if x['source'] == 'docs/decisions/INDEX.md'][0]
            self.assertEqual(rec['authority_status'], 'NOT_AUTHORITY')
            self.assertIn('сами решения живут в файлах', rec['authority_quote'])

    def test_the_second_adr_registry_has_undefined_authority(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rec = [x for x in s['sources'] if x['source'] == 'docs/adr/*.md'][0]
            self.assertEqual(rec['authority_status'], 'AUTHORITY_UNDEFINED')
            self.assertIn('коллизи', rec['authority_quote'])

    def test_a_number_collision_is_shown_without_a_winner(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            adr = _by(s, 'ADR-050')
            self.assertEqual(adr['status'], 'NUMBER_COLLISION')
            self.assertEqual(adr['authority_source'], 'AUTHORITY_UNDEFINED')
            self.assertTrue(any('победителя не выбираем' in e['detail']
                                for e in adr['evidence']))
            self.assertEqual(s['counts']['adr_number_collisions'], 1)

    def test_rules_and_invariants_are_authoritative_with_a_quote(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rule = _by(s, 'rule:deployment.md')
            self.assertEqual(rule['authority_source'], 'AUTHORITATIVE')
            inv = [i for i in s['items'] if i['category'] == 'invariant']
            self.assertTrue(inv)
            self.assertTrue(all(i['authority_source'] == 'AUTHORITATIVE' for i in inv))


class ApprovalAndPermissionsAreNeverInvented(unittest.TestCase):
    def test_the_three_owner_subjects_come_from_the_rule(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            gated = [i for i in s['items'] if i['permission_zone'] == 'OWNER_GATED']
            self.assertGreaterEqual(len(gated), 3)
            for i in gated:
                self.assertEqual(i['approval_required'], 'REQUIRED')
                self.assertTrue(i['evidence'])

    def test_a_subject_no_rule_places_stays_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            adr = _by(s, 'ADR-001')
            self.assertEqual(adr['permission_zone'], 'UNKNOWN')
            self.assertEqual(adr['approval_required'], 'UNKNOWN')

    def test_without_the_boundary_rule_no_zone_is_assigned(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'CLAUDE.md').write_text('# SPA\n\nбез границы и без инвариантов\n')
            s = _build(td, production=root)
            self.assertEqual([i for i in s['items']
                              if i['permission_zone'] == 'OWNER_GATED'
                              and i['category'] == 'permission'
                              and i['decision_ref'] == 'ADR-285'], [])

    def test_the_contract_refuses_an_unknown_permission_zone(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            broken['items'][0]['permission_zone'] = 'ЗЕЛЁНАЯ'
            with self.assertRaises(gov.GovernanceInputError):
                gov.validate_governance_snapshot(broken, 'mutated')


class ABackupIsNotARestore(unittest.TestCase):
    def test_a_drill_with_a_result_is_the_only_proof_of_restore(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            drill = _by(s, 'recovery:restore_drill')
            self.assertEqual(drill['recovery_status'], 'TESTED')
            self.assertTrue(drill['recovery_evidence'])
            self.assertEqual(s['counts']['restore_proven'], 1)

    def test_a_failed_drill_is_not_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'restore_drill_status.json': {
                'all_ok': False, 'last_drill_ts': '2026-09-20T14:58:10+00:00',
                'files_validated': []}})
            s = _build(td, production=root)
            self.assertEqual(_by(s, 'recovery:restore_drill')['recovery_status'],
                             'DOCUMENTED_UNTESTED')
            self.assertEqual(s['counts']['restore_proven'], 0)

    def test_backup_presence_never_becomes_restore_proof(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for item in [i for i in s['items'] if i['category'] == 'backup']:
                self.assertNotEqual(item['recovery_status'], 'TESTED')
                # регистр и падеж у слова «наличие» в уликах разные — проверяем корень
                self.assertTrue(any('налич' in e['detail'].lower()
                                    for e in item['evidence']),
                                item['governance_id'])
            broken = copy.deepcopy(s)
            victim = [i for i in broken['items'] if i['category'] == 'backup'][0]
            victim['recovery_status'] = 'TESTED'
            with self.assertRaises(gov.GovernanceInputError):
                gov.validate_governance_snapshot(broken, 'mutated')

    def test_a_written_runbook_is_documented_not_tested(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            book = _by(s, 'recovery:DISASTER_RECOVERY.md')
            self.assertEqual(book['recovery_status'], 'DOCUMENTED_UNTESTED')
            self.assertTrue(any('доказательства исполнения НЕ найдено' in e['detail']
                                for e in book['recovery_evidence']))

    def test_a_missing_procedure_stays_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'docs/DISASTER_RECOVERY.md').unlink()
            (root / 'docs/RUNBOOK.md').unlink()
            s = _build(td, production=root)
            self.assertEqual([i for i in s['items']
                              if i['governance_id'].startswith('recovery:DISASTER')], [])

    def test_the_contract_refuses_tested_without_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = _by(broken, 'recovery:DISASTER_RECOVERY.md')
            victim['recovery_status'] = 'TESTED'
            victim['recovery_evidence'] = []
            with self.assertRaises(gov.GovernanceInputError):
                gov.validate_governance_snapshot(broken, 'mutated')


class GapsAreMeasuredNotListed(unittest.TestCase):
    def test_an_autonomous_rule_is_not_an_owner_gate(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            auto = [i for i in s['items'] if i['permission_class'] == 'AUTONOMOUS']
            self.assertTrue(auto)
            for i in auto:
                self.assertNotEqual(i['approval_required'], 'REQUIRED')

    def test_an_emergency_rule_is_not_an_owner_gate_automatically(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            emerg = [i for i in s['items'] if i['permission_class'] == 'EMERGENCY']
            self.assertEqual(len(emerg), 1)
            self.assertEqual(emerg[0]['approval_required'], 'UNKNOWN')
            self.assertTrue(any('НЕ содержит' in e['detail'] for e in emerg[0]['evidence']))

    def test_only_explicit_owner_subjects_are_approval_gates(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            gates = [i for i in s['items'] if i['approval_required'] == 'REQUIRED']
            self.assertTrue(all(i['permission_class'] == 'OWNER_GATED' for i in gates))
            self.assertEqual(s['counts']['approval_required'], len(gates))
            self.assertLess(s['counts']['approval_required'], s['counts']['permissions'])

    def test_the_contract_refuses_an_autonomous_rule_as_a_gate(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = [i for i in broken['items']
                      if i['permission_class'] == 'AUTONOMOUS'][0]
            victim['approval_required'] = 'REQUIRED'
            with self.assertRaises(gov.GovernanceInputError):
                gov.validate_governance_snapshot(broken, 'mutated')

    def test_a_document_outside_the_declared_scope_is_not_a_zone_gap(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            adr = _by(s, 'ADR-001')
            self.assertEqual(adr['zone_scope'], 'ZONE_NOT_APPLICABLE')
            self.assertEqual(adr['permission_zone'], 'UNKNOWN')
            gaps = {i['governance_id'] for i in s['items'] if i['category'] == 'gap'}
            self.assertNotIn('gap:permission_zone_undefined', gaps)
            self.assertGreater(s['counts']['zone_not_applicable'], 0)

    def test_an_action_inside_the_scope_without_a_zone_is_a_gap(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            inside = [i for i in s['items'] if i['zone_scope'] == 'ZONE_REQUIRED']
            self.assertTrue(inside)
            missing = [i for i in inside if i['permission_zone'] == 'UNKNOWN']
            if missing:
                gaps = {i['governance_id'] for i in s['items'] if i['category'] == 'gap'}
                self.assertIn('gap:permission_zone_required_but_missing', gaps)
            self.assertEqual(s['counts']['zone_required_but_missing'], len(missing))

    def test_the_scope_is_quoted_from_the_rule(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIn('ПО ПРЕДМЕТУ', s['zone_scope_basis'])
            self.assertIn('git/PR', s['zone_scope_basis'])
            page = pr._governance(s, {'governance_snapshot.json'})
            self.assertIn('пробелом не', page)

    def test_a_runbook_is_documented_untested_not_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            book = _by(s, 'recovery:RUNBOOK.md')
            self.assertEqual(book['recovery_status'], 'DOCUMENTED_UNTESTED')
            self.assertNotEqual(book['recovery_status'], 'UNKNOWN')
            self.assertEqual(s['counts']['recovery_documented_untested'],
                             len([i for i in s['items']
                                  if i['recovery_status'] == 'DOCUMENTED_UNTESTED']))

    def test_a_backup_never_upgrades_the_recovery_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'data/restore_drill_status.json').unlink()
            s = _build(td, production=root)
            self.assertEqual(s['counts']['recovery_tested'], 0)
            self.assertGreater(s['counts']['backups_observed'], 0)
            gaps = {i['governance_id'] for i in s['items'] if i['category'] == 'gap'}
            self.assertIn('gap:recovery_untested', gaps)

    def test_gaps_are_derived_from_the_measurement(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            gaps = {i['governance_id'] for i in s['items'] if i['category'] == 'gap'}
            self.assertIn('gap:rollback_documented_not_tested', gaps)
            self.assertIn('gap:adr_number_collision', gaps)
            for g in [i for i in s['items'] if i['category'] == 'gap']:
                self.assertTrue(g['evidence'])

    def test_a_clean_tree_produces_fewer_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'docs/adr/ADR-050-dup.md').unlink()
            s = _build(td, production=root)
            gaps = {i['governance_id'] for i in s['items'] if i['category'] == 'gap'}
            self.assertNotIn('gap:adr_number_collision', gaps)
            self.assertEqual(s['counts']['adr_number_collisions'], 0)

    def test_there_is_no_governance_score(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIs(s['has_governance_score'], False)
            self.assertIn('нет намеренно', s['governance_score_note'])
            broken = copy.deepcopy(s)
            broken['has_governance_score'] = True
            with self.assertRaises(gov.GovernanceInputError):
                gov.validate_governance_snapshot(broken, 'mutated')


class NothingIsWrittenAndNothingLeaves(unittest.TestCase):
    def test_no_secret_value_is_copied(self):
        with tempfile.TemporaryDirectory() as td:
            leak = f'ghp_{"d" * 36}'
            root = _prod(td, **{'security_alerts.json': [{'detail': leak}]})
            s = _build(td, production=root)
            blob = json.dumps(s, ensure_ascii=False)
            self.assertNotIn(leak, blob)
            gov.validate_governance_snapshot(s, 'built')

    def test_the_run_writes_nothing_into_production(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            before = {str(p.relative_to(root)): p.stat().st_mtime_ns
                      for p in root.rglob('*') if p.is_file()}
            gov.main(['--production', str(root), '--output', str(Path(td) / 'out')])
            after = {str(p.relative_to(root)): p.stat().st_mtime_ns
                     for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_the_snapshot_declares_it_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIs(s['builds_new_governance'], False)
            self.assertIs(s['changes_permissions'], False)
            self.assertIs(s['executes_recovery'], False)

    def test_the_module_never_imports_a_door_to_the_machine(self):
        source = (_root / 'governance.py').read_text()
        for banned in ('import subprocess', 'import socket', 'import urllib',
                       'from subprocess', 'from socket', 'from urllib'):
            self.assertNotIn(banned, source)

    def test_the_renderer_never_reaches_the_network(self):
        import socket
        import urllib.request

        def refuse(*a, **k):
            raise AssertionError('рендер вышел наружу')

        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            with patch.object(socket, 'socket', refuse), \
                 patch.object(urllib.request, 'urlopen', refuse):
                page = pr._governance(s, {'governance_snapshot.json'})
            self.assertNotIn('http://', page)
            self.assertNotIn('https://', page)

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            with self.assertRaises(ValueError):
                gov.main(['--production', str(root), '--output', str(root / 'data/out')])
            link = Path(td) / 'link'
            os.symlink(root, link)
            with self.assertRaises(ValueError):
                gov.main(['--production', str(root), '--output',
                          str(link / 'data' / 'o')])
            launchd = Path.home() / 'Library/LaunchAgents/cartographer-gov-test'
            with self.assertRaises(ValueError):
                gov.main(['--production', str(root), '--output', str(launchd)])
            self.assertFalse(launchd.exists())

    def test_two_builds_of_the_same_inputs_agree(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            a = gov.build_governance_snapshot(root)
            b = gov.build_governance_snapshot(root)
            self.assertEqual(a['semantic_digest'], b['semantic_digest'])

    def test_a_completed_run_writes_one_file_with_tight_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            out = Path(td) / 'out'
            gov.main(['--production', str(root), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()],
                             ['governance_snapshot.json'])
            self.assertEqual(oct((out / 'governance_snapshot.json').stat().st_mode)[-3:],
                             '600')
            gov.validate_governance_snapshot(
                json.loads((out / 'governance_snapshot.json').read_text()), 'written')


class ThePageActsOnNothing(unittest.TestCase):
    def test_no_control_performs_a_governance_action(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = pr._governance(_build(td), {'governance_snapshot.json'})
            self.assertEqual(page.count('<button'), 0)
            self.assertEqual(page.count('<form'), 0)
            handlers = set(_re.findall(r'on[a-z]+="([A-Za-z_]+)\(', page))
            self.assertLessEqual(handlers, {'spaFilter', 'spaSort'})
            for verb in ('Approve', 'Rollback', 'Restore', 'Rotate secret',
                         'Change permission', 'Change RiskPolicy', 'Trigger kill-switch',
                         'Deploy', 'Delete', 'Repair', 'Одобрить', 'Откатить',
                         'Восстановить', 'Сменить'):
                for label in _re.findall(r'<(?:button|a|input|select)\b[^>]*>([^<]*)',
                                         page):
                    self.assertNotIn(verb.lower(), label.strip().lower())

    def test_every_facet_option_exists_in_the_data(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._governance(s, {'governance_snapshot.json'})
            block = page[page.index('id="governance-scope"'):]
            block = block[:block.index('data-role="list"')]
            facets = _re.findall(r'<select[^>]*data-role="facet"[^>]*>(.*?)</select>',
                                 block, _re.S)
            self.assertEqual(len(facets), 8)
            options = {o for f in facets
                       for o in _re.findall(r'<option value="([^"]*)"', f)} - {''}
            present = ({i['category'] for i in s['items']}
                       | {i['permission_zone'] for i in s['items']}
                       | {i['recovery_status'] for i in s['items']}
                       | {i['authority_source'] for i in s['items']}
                       | {str(i['owner']) for i in s['items']}
                       | {i['approval_required'] for i in s['items']}
                       | {i['permission_class'] for i in s['items']}
                       | {i['zone_scope'] for i in s['items']})
            self.assertLessEqual(options, present)

    def test_the_page_says_backup_is_not_restore(self):
        with tempfile.TemporaryDirectory() as td:
            page = pr._governance(_build(td), {'governance_snapshot.json'})
            self.assertIn('не является доказательством', page)
            self.assertIn('описано, пробы НЕТ', page)

    def test_an_absent_snapshot_is_not_rendered_as_all_governed(self):
        page = pr._governance(None, set())
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что управление в порядке', page)
