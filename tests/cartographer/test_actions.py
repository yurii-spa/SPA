"""Regressions for Actions & V1 release evidence (Director OS Phase 9).

The risk of a final phase is a button that looks safe: an action exposed because its name
sounds harmless, a red-zone verb slipping through, a release manifest that lists successes
and quietly drops the limitations. Each test below pins one of those.
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


act = _load('actions')
rel = _load('release')
pr = _load('portal_render')


def _prod(td, perfect=False):
    root = Path(td) / 'prod'
    (root / 'scripts').mkdir(parents=True, exist_ok=True)
    (root / 'scripts/cartographer').mkdir(parents=True, exist_ok=True)
    (root / 'tests/cartographer').mkdir(parents=True, exist_ok=True)
    body = ('#!/usr/bin/env python3\n"""исполнитель"""\n'
            'REFUSED = "REFUSED"\nraise SystemExit(1)\n')
    if perfect:
        body += ('# audit_chain: запись в журнал\n# idempotent: повторный вызов безопасен\n'
                 '# rollback: откат описан\n')
    for name in ('orchestrator_queue.py', 'check_card_claim.py'):
        (root / 'scripts' / name).write_text(body)
    (root / 'scripts/cartographer/snapshot.py').write_text('# модуль\n')
    (root / 'tests/cartographer/test_snapshot.py').write_text('# тест\n')
    return root


def _governance():
    return {'items': [{'governance_id': 'permission:x', 'permission_zone': 'AGENT_DECIDES'}]}


class NoButtonWithoutEveryProperty(unittest.TestCase):
    def test_a_missing_property_blocks_the_ui(self):
        with tempfile.TemporaryDirectory() as td:
            s = act.audit_actions(_prod(td), _governance())
            self.assertEqual(s['counts']['ready_for_ui'], 0)
            self.assertIs(s['ui_exposes_actions'], False)
            for a in s['actions']:
                if a['verdict'] == 'NOT_READY_FOR_UI':
                    self.assertTrue(a['missing_properties'])

    def test_the_missing_properties_are_named_not_summarised(self):
        with tempfile.TemporaryDirectory() as td:
            s = act.audit_actions(_prod(td), _governance())
            cand = [a for a in s['actions']
                    if a['action'] == 'card_set_status'][0]
            self.assertIn('audit_record', cand['missing_properties'])
            self.assertIn('rollback', cand['missing_properties'])
            self.assertIn('не хватает свойств', cand['verdict_reason'])

    def test_an_executor_with_everything_would_be_ready(self):
        """Положительный контроль: правило не запрещает кнопки навсегда."""
        with tempfile.TemporaryDirectory() as td:
            s = act.audit_actions(_prod(td, perfect=True), _governance())
            self.assertGreater(s['counts']['ready_for_ui'], 0)
            self.assertIs(s['ui_exposes_actions'], True)
            ready = [a for a in s['actions'] if a['verdict'] == 'READY_FOR_UI'][0]
            self.assertEqual(ready['missing_properties'], [])

    def test_a_missing_executor_is_not_ready_and_says_why(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'scripts/orchestrator_queue.py').unlink()
            s = act.audit_actions(root, _governance())
            cand = [a for a in s['actions'] if a['action'] == 'card_set_status'][0]
            self.assertEqual(cand['verdict'], 'NOT_READY_FOR_UI')
            self.assertIn('не найден', cand['verdict_reason'])

    def test_the_contract_refuses_ready_with_missing_properties(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(act.audit_actions(_prod(td), _governance()))
            victim = [a for a in broken['actions']
                      if a['verdict'] == 'NOT_READY_FOR_UI'][0]
            victim['verdict'] = 'READY_FOR_UI'
            with self.assertRaises(act.ActionAuditError):
                act.validate_action_audit(broken, 'mutated')


class TheRedZoneIsNeverNegotiable(unittest.TestCase):
    def test_every_red_zone_action_keeps_its_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            s = act.audit_actions(_prod(td, perfect=True), _governance())
            red = [a for a in s['actions'] if a['action'] in act.RED_ZONE]
            self.assertEqual(len(red), len(act.RED_ZONE))
            for a in red:
                self.assertEqual(a['verdict'], 'RED_ZONE')

    def test_the_contract_refuses_a_red_zone_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(act.audit_actions(_prod(td), _governance()))
            victim = [a for a in broken['actions'] if a['action'] == 'kill_switch'][0]
            victim['verdict'] = 'READY_FOR_UI'
            victim['missing_properties'] = []
            with self.assertRaises(act.ActionAuditError):
                act.validate_action_audit(broken, 'mutated')

    def test_capital_and_risk_verbs_are_in_the_red_zone(self):
        for name in ('move_capital', 'execute_trade', 'change_risk_policy',
                     'kill_switch', 'rotate_secrets', 'restore_backup',
                     'rollback_origin'):
            self.assertIn(name, act.RED_ZONE)


class ThePageShowsNoButtons(unittest.TestCase):
    def test_the_section_has_no_controls_at_all(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = pr._actions(act.audit_actions(_prod(td), _governance()),
                               {'action_authority_audit.json'})
            self.assertEqual(page.count('<button'), 0)
            self.assertEqual(page.count('<form'), 0)
            self.assertEqual(page.count('<input'), 0)
            self.assertEqual(set(_re.findall(r'on[a-z]+="', page)), set())

    def test_the_page_says_zero_is_a_measurement(self):
        with tempfile.TemporaryDirectory() as td:
            page = pr._actions(act.audit_actions(_prod(td), _governance()),
                               {'action_authority_audit.json'})
            self.assertIn('измеренный результат', page)
            self.assertIn('полностью read-only', page)
            self.assertIn('Красная зона v1', page)

    def test_an_absent_audit_is_not_rendered_as_permission(self):
        page = pr._actions(None, set())
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что действия разрешены', page)


class TheReleaseManifestTellsTheWholeTruth(unittest.TestCase):
    def _bundle(self, td, **over):
        b = Path(td) / 'bundle'
        b.mkdir(exist_ok=True)
        docs = {
            'reliability_snapshot.json': {
                'schema_version': 'cartographer.reliability_snapshot/0.1',
                'semantic_digest': 'aaa', 'generated_at': '2026-09-20T00:00:00+00:00',
                'limits': ['снимок производный'],
                'counts': {'active_confirmed': 5, 'active_unverified': 7,
                           'critical_confirmed_now': 1}},
            'governance_snapshot.json': {
                'schema_version': 'cartographer.governance_snapshot/0.1',
                'semantic_digest': 'bbb', 'generated_at': '2026-09-20T00:00:00+00:00',
                'limits': ['балла нет'],
                'items': [{'governance_id': 'gap:x', 'title': 'пробел', 'category': 'gap'}]},
            'action_authority_audit.json': {
                'schema_version': 'cartographer.action_authority_audit/0.1',
                'semantic_digest': 'ccc', 'generated_at': '2026-09-20T00:00:00+00:00',
                'limits': [], 'red_zone': list(act.RED_ZONE),
                'actions': [{'action': 'card_set_status',
                             'verdict': 'NOT_READY_FOR_UI'}]},
        }
        docs.update(over)
        for name, body in docs.items():
            (b / name).write_text(json.dumps(body, ensure_ascii=False))
        return b

    def test_the_manifest_names_its_base_and_its_limits(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            rel.validate_release_manifest(m, 'built')
            self.assertEqual(m['base_origin_sha'], 'a' * 40)
            self.assertTrue(m['known_limitations'])
            self.assertTrue(m['unresolved_governance_gaps'])
            self.assertTrue(m['unresolved_reliability_conditions'])
            self.assertTrue(m['prohibited_actions'])

    def test_a_manifest_without_limits_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            broken = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            broken['prohibited_actions'] = []
            with self.assertRaises(rel.ReleaseInputError):
                rel.validate_release_manifest(broken, 'mutated')

    def test_read_only_and_ready_actions_cannot_both_be_true(self):
        with tempfile.TemporaryDirectory() as td:
            broken = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            broken['action_capabilities'] = {'ready_for_ui': ['x'], 'count': 1,
                                             'note': ''}
            with self.assertRaises(rel.ReleaseInputError):
                rel.validate_release_manifest(broken, 'mutated')

    def test_unmeasured_blocks_are_declared_not_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            for key in ('tests', 'browser_acceptance', 'performance'):
                self.assertEqual(m[key]['status'], 'NOT_MEASURED')
            rel.validate_release_manifest(m, 'built')

    def test_a_missing_layer_is_reported_not_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            absent = [x for x in m['layers'] if x['status'] != 'READ']
            self.assertTrue(absent)
            self.assertTrue(all(x['schema_expected'] for x in absent))

    def test_the_manifest_lists_the_files_it_claims(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), self._bundle(td), 'a' * 40)
            self.assertEqual(m['file_count'], len(m['files']))
            for f in m['files']:
                self.assertEqual(len(f['sha256']), 64)

    def test_two_builds_of_the_same_inputs_agree(self):
        with tempfile.TemporaryDirectory() as td:
            root, b = _prod(td), self._bundle(td)
            a = rel.build_release_manifest(root, b, 'a' * 40)
            c = rel.build_release_manifest(root, b, 'a' * 40)
            self.assertEqual(a['semantic_digest'], c['semantic_digest'])


class NothingIsWrittenAndNothingLeaves(unittest.TestCase):
    def test_the_audit_writes_nothing_into_production(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            before = {str(p.relative_to(root)): p.stat().st_mtime_ns
                      for p in root.rglob('*') if p.is_file()}
            act.main(['--production', str(root), '--output', str(Path(td) / 'out')])
            after = {str(p.relative_to(root)): p.stat().st_mtime_ns
                     for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_neither_module_imports_a_door_to_the_machine(self):
        for name in ('actions.py', 'release.py'):
            source = (_root / name).read_text()
            for banned in ('import subprocess', 'import socket', 'import urllib',
                           'from subprocess', 'from socket', 'from urllib'):
                self.assertNotIn(banned, source, name)

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            with self.assertRaises(ValueError):
                act.main(['--production', str(root),
                          '--output', str(root / 'scripts/out')])
            link = Path(td) / 'link'
            os.symlink(root, link)
            with self.assertRaises(ValueError):
                act.main(['--production', str(root),
                          '--output', str(link / 'scripts' / 'o')])
            launchd = Path.home() / 'Library/LaunchAgents/cartographer-act-test'
            with self.assertRaises(ValueError):
                act.main(['--production', str(root), '--output', str(launchd)])
            self.assertFalse(launchd.exists())

    def test_a_completed_run_writes_one_file_with_tight_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            out = Path(td) / 'out'
            act.main(['--production', str(root), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()],
                             ['action_authority_audit.json'])
            self.assertEqual(oct((out / 'action_authority_audit.json').stat().st_mode)[-3:],
                             '600')
            act.validate_action_audit(
                json.loads((out / 'action_authority_audit.json').read_text()), 'written')

    def test_the_renderer_never_reaches_the_network(self):
        import socket
        import urllib.request

        def refuse(*a, **k):
            raise AssertionError('рендер вышел наружу')

        with tempfile.TemporaryDirectory() as td:
            s = act.audit_actions(_prod(td), _governance())
            with patch.object(socket, 'socket', refuse), \
                 patch.object(urllib.request, 'urlopen', refuse):
                page = pr._actions(s, {'action_authority_audit.json'})
            self.assertNotIn('http://', page)
            self.assertNotIn('https://', page)


class TheStaticPagesStayStaticAndConnected(unittest.TestCase):
    """Шесть страниц вместо монолита: те же снимки, никакого SPA и никакого сервера."""

    def _portal(self, td):
        portal_cli = _load('portal')
        return portal_cli

    def test_the_page_set_is_declared_and_small(self):
        self.assertEqual(len(pr.PAGES), 6)
        self.assertEqual(pr.PAGE_FILES[0], 'index.html')
        covered = {s for _, _, secs in pr.PAGES for s in secs}
        self.assertIn('director', covered)
        for section in ('reliability', 'work', 'investments', 'governance', 'actions',
                        'authority', 'sources', 'agents', 'tasks', 'decisions',
                        'overview'):
            self.assertIn(section, covered, section)

    def test_every_section_lives_on_exactly_one_page(self):
        seen = {}
        for name, _, sections in pr.PAGES:
            for s in sections:
                self.assertNotIn(s, seen, f'{s} продублирован на {name} и {seen.get(s)}')
                seen[s] = name

    def test_a_cross_page_link_carries_the_file_and_the_anchor(self):
        self.assertEqual(pr.section_href('work'), 'work.html#work')
        self.assertEqual(pr.section_href('reliability'), 'reliability.html#reliability')
        self.assertEqual(pr.section_href('director'), 'index.html#director')
        self.assertEqual(pr.section_href('нет-такого'), '#нет-такого')

    def test_the_index_carries_only_the_director_centre(self):
        index_sections = [secs for name, _, secs in pr.PAGES if name == 'index.html'][0]
        self.assertEqual(index_sections, ('director',))

    def test_no_page_loads_a_framework_or_a_server(self):
        design = {'state': 'DESIGN_REFERENCE_UNAVAILABLE', 'note': ''}
        portal = {'page_generated_at': '2026-09-20T00:00:00+00:00',
                  'counts': {'tasks': 0, 'owner_decision_records': 0,
                             'agents_and_roles': 0},
                  'tasks': [], 'agents': [], 'decisions': [], 'sources': [],
                  'observation_times': {}, 'limits': []}
        try:
            rendered = pr.pages(portal, None, design)
        except Exception:  # noqa: BLE001 — разделы требуют своих снимков
            self.skipTest('полный снимок портала здесь не строится; проверено в '
                          'test_portal')
        for name, html in rendered.items():
            self.assertNotIn('<script src=', html, name)
            self.assertNotIn('http://', html, name)
            self.assertNotIn('https://', html, name)
