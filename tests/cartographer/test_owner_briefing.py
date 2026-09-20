"""Behaviour and refusal tests for the Owner Briefing layer (Director OS Phase 1).

The risks of a reporting layer are not arithmetic: it can say more than its evidence, let
a loss of observation read as an improvement, invent a comparison where none was asked
for, or quietly publish half a run. Each test below is one of those.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = _load('diff')
sot = _load('source_of_truth')
ob = _load('owner_briefing')
render = _load('render')
from test_diff import _snap, _write, _without, REPO, SENTINEL  # noqa: E402


def _brief(new_snapshot=None, old_snapshot=None, provenance=None):
    new_snapshot = new_snapshot if new_snapshot is not None else _snap()
    the_diff = None
    if old_snapshot is not None:
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'o', old_snapshot)
            b = _write(Path(td) / 'n', new_snapshot)
            the_diff = d.compare(d.load_set(a), d.load_set(b))
    m = sot.build(new_snapshot, source_dir='/snapshots/new')
    return ob.build(new_snapshot, m, diff=the_diff, provenance=provenance or {})


def _all_texts(b):
    return {'json': json.dumps(b, ensure_ascii=False),
            'md': render.markdown(b), 'html': render.html(b)}


class OneFactOneRepresentation(unittest.TestCase):
    def test_the_same_fact_appears_in_json_markdown_and_html(self):
        old = _snap()
        old['entities'][0]['status'] = 'STALE'
        old['entities'][0]['declared_outputs'][0]['fresh'] = False
        old['findings'] = old['findings'] + [
            {'id': 'STATUS_STALE:com.spa.alpha', 'kind': 'DRIFT', 'rule_code': 'STATUS_STALE',
             'subject': 'com.spa.alpha', 'context': None, 'reason': 'STALE'}]
        b = _brief(new_snapshot=_snap(), old_snapshot=old)
        texts = _all_texts(b)
        # the counts the page leads with must be the counts in the data
        self.assertEqual(b['counts']['attention_items'], len(b['attention']))
        for a in b['attention']:
            self.assertIn(a['headline'], texts['md'])
            self.assertIn(a['headline'], texts['html'])
            self.assertIn(a['rule_code'], texts['md'])
            self.assertIn(a['rule_code'], texts['html'])
        for c in b['owner_decision_candidates']:
            for text in (texts['md'], texts['html']):
                self.assertIn(c['id'], text)
                self.assertIn(c['existing_rule'][:40], text)

    def test_every_attention_item_traces_to_an_artifact_and_pointer(self):
        b = _brief()
        self.assertTrue(b['attention'])
        for group in (b['attention'], b['owner_decision_candidates'], b['unknowns']):
            for item in group:
                self.assertIn('artifact', item['evidence'])
                self.assertIn('pointer', item['evidence'])
                self.assertIn(item['evidence']['artifact'],
                              ('diff.json', 'findings.json', 'snapshot.json',
                               'source_of_truth.json'))

    def test_attention_examples_name_the_concrete_object_not_the_repository(self):
        """A drift finding's subject is the repository; the file lives in `context`.
        Printing the subject would show the same path five times and say nothing."""
        b = _brief()
        drift = [a for a in b['attention'] if a['rule_code'].startswith('DRIFT_')]
        self.assertTrue(drift)
        for a in drift:
            for ex in a['examples']:
                self.assertEqual(ex['label'], ex['context'])
                self.assertNotEqual(ex['label'], REPO)
            self.assertIn(a['examples'][0]['label'], render.markdown(b))


class NoClaimStrongerThanEvidence(unittest.TestCase):
    def test_there_is_no_overall_health_verdict(self):
        b = _brief()
        self.assertIsNone(b['overall_health_score'])
        for name, text in _all_texts(b).items():
            for verdict in ('система здорова', 'всё в порядке', 'всё ок', 'система исправна',
                            'health score:', 'общий статус: ok'):
                self.assertNotIn(verdict, text.lower(), name)
        # the word HEALTHY may appear only as the stage that is NOT measured
        md = render.markdown(b).lower()
        for pos in range(len(md)):
            if md.startswith('healthy', pos):
                window = md[max(0, pos - 120):pos + 120]
                self.assertTrue('неизвест' in window or 'не измеряется' in window
                                or 'не доказ' in window, window)
        self.assertIn('не выводится', render.html(b))

    def test_stale_evidence_is_not_rendered_as_an_unhealthy_system(self):
        old_capture = _snap(finished_at='2026-01-01T00:00:00+00:00',
                            started_at='2026-01-01T00:00:00+00:00')
        b = _brief(new_snapshot=old_capture)
        f = b['freshness_and_coverage']
        self.assertEqual(f['freshness_policy'], 'POLICY_UNDEFINED')
        self.assertIn('сут', f['age_at_generation_human'])
        self.assertIn('НЕ означает, что система неисправна',
                      f['stale_summary_is_not_a_broken_system'])
        self.assertIn('НЕ означает, что система неисправна', render.markdown(b))

    def test_an_unavailable_source_is_shown_as_unknown_not_as_false(self):
        s = _snap()
        s['coverage']['domains_complete'] = None
        s['coverage']['manifest_readable'] = False
        b = _brief(new_snapshot=s)
        states = {x['coverage_key']: x['state'] for x in b['freshness_and_coverage']['sources']}
        self.assertEqual(states['domains_complete'], 'UNKNOWN')
        self.assertEqual(states['manifest_readable'], 'НЕДОСТУПЕН')
        self.assertIn('UNKNOWN', render.html(b))

    def test_unknown_not_rechecked_and_applicability_are_never_called_resolved(self):
        old = _snap()
        old['findings'] = old['findings'] + [
            {'id': 'STATUS_STALE:com.spa.alpha', 'kind': 'DRIFT', 'rule_code': 'STATUS_STALE',
             'subject': 'com.spa.alpha', 'context': None, 'reason': 'STALE'}]
        old['entities'][0]['declared_outputs'][0]['fresh'] = False
        old['entities'][0]['status'] = 'STALE'
        new = _without(_snap(), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'][0]['exists'] = None   # blinded
        new['entities'][0]['declared_outputs'][0]['fresh'] = None
        b = _brief(new_snapshot=new, old_snapshot=old)
        blob = json.dumps(b, ensure_ascii=False)
        self.assertIn('NOT_RECHECKED', blob.upper())
        resolved = [c for c in b['material_changes']['confirmed']
                    if c['type'] == 'FINDING_RESOLVED']
        self.assertEqual(resolved, [])
        groups = {u['rule_code'] for u in b['unknowns']}
        self.assertIn('NOT_RECHECKED', groups)
        self.assertIn('НЕ перепроверено', render.markdown(b))

    def test_a_lost_observation_is_not_presented_as_an_improvement(self):
        new = _snap()
        new['entities'][0]['stages']['LOADED'] = None
        new['entities'][0]['status'] = 'UNKNOWN'
        new['coverage'].update(domains_complete=False, domains_readable={'gui/501': False})
        b = _brief(new_snapshot=new, old_snapshot=_snap())
        self.assertEqual(b['material_changes']['confirmed'], [])
        quality = [c['type'] for c in b['material_changes']['observation_quality']]
        self.assertIn('STAGE_OBSERVATION_LOST', quality)
        headlines = [c['headline'] for c in b['material_changes']['observation_quality']]
        self.assertTrue(any('ПОТЕРЯНО' in h for h in headlines))

    def test_an_unknown_by_design_is_not_turned_into_an_alarm(self):
        b = _brief()
        rules = {a['rule_code'] for a in b['attention']}
        self.assertNotIn('WRAPPER_TARGET_UNDECLARED', rules)
        self.assertNotIn('HEALTH_UNMEASURED', rules)
        by_design = {u['rule_code'] for u in b['unknowns'] if u['is_by_design']}
        self.assertIn('WRAPPER_TARGET_UNDECLARED', by_design)

    def test_unknowns_are_grouped_without_losing_the_detail(self):
        s = _snap()
        s['findings'] = s['findings'] + [
            {'id': f'WRAPPER_TARGET_UNDECLARED:com.spa.w{i}:p.plist', 'kind': 'UNKNOWN',
             'rule_code': 'WRAPPER_TARGET_UNDECLARED', 'subject': f'com.spa.w{i}',
             'context': 'p.plist', 'reason': 'dynamic target'} for i in range(77)]
        b = _brief(new_snapshot=s)
        group = [u for u in b['unknowns'] if u['rule_code'] == 'WRAPPER_TARGET_UNDECLARED'][0]
        self.assertEqual(group['count'], 78)
        self.assertEqual(len(group['finding_ids']), 78)      # detail kept in JSON
        md = render.markdown(b)
        self.assertEqual(md.count('WRAPPER_TARGET_UNDECLARED'), 1)   # one line for a person
        html = render.html(b)
        self.assertIn('com.spa.w42', html)                   # still reachable in the page
        self.assertIn('<details>', html)


class FirstRun(unittest.TestCase):
    def test_first_run_invents_no_change(self):
        b = _brief()                       # no old snapshot at all
        self.assertEqual(b['mode'], 'first_run')
        for bucket in b['material_changes'].values():
            self.assertEqual(bucket, [])
        self.assertEqual(b['owner_decision_candidates'], [])
        self.assertIn('не выдумывается', b['mode_note'])
        self.assertIn('Прошлое наблюдение не выбрано', render.markdown(b))
        self.assertIn('Прошлое наблюдение не выбрано', render.html(b))

    def test_first_run_still_shows_state_and_unknowns(self):
        b = _brief()
        self.assertTrue(b['attention'])
        self.assertTrue(b['unknowns'])
        self.assertIsNone(b['freshness_and_coverage']['compared_sets'])


class Determinism(unittest.TestCase):
    def test_identical_inputs_give_an_identical_semantic_result(self):
        # the SAME directories: input provenance is part of the semantics, so briefing
        # two copies from two temp paths would not be that test
        with tempfile.TemporaryDirectory() as td:
            old_dir = _write(Path(td) / 'o', _snap())
            new_dir = _write(Path(td) / 'n', _snap())
            the_diff = d.compare(d.load_set(old_dir), d.load_set(new_dir))
            m = sot.build(_snap(), source_dir=str(new_dir))
            a = ob.build(_snap(), m, diff=the_diff, provenance={})
            b = ob.build(_snap(), m, diff=the_diff, provenance={})
        self.assertEqual(ob.semantic_view(a), ob.semantic_view(b))
        self.assertEqual(a['semantic_digest'], b['semantic_digest'])
        self.assertEqual(a['volatile_fields'], ['generated_at'])

    def test_the_page_is_a_function_of_the_briefing(self):
        b = _brief(old_snapshot=_snap())
        self.assertEqual(render.html(b), render.html(copy.deepcopy(b)))
        self.assertEqual(render.markdown(b), render.markdown(copy.deepcopy(b)))


class SafeOutput(unittest.TestCase):
    def test_html_escapes_paths_names_and_reasons(self):
        s = _snap()
        evil = '<img src=x onerror="alert(1)">&"\''
        s['entities'][0]['id'] = f'com.spa.{evil}'
        s['findings'] = s['findings'] + [
            {'id': f'STATUS_DEGRADED:{evil}', 'kind': 'DRIFT', 'rule_code': 'STATUS_DEGRADED',
             'subject': f'com.spa.{evil}', 'context': evil, 'reason': f'reason {evil}'}]
        s['repositories'][0]['path'] = f'/repo/{evil}'
        page = render.html(_brief(new_snapshot=s))
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('onerror="alert(1)"', page)
        self.assertIn('&lt;img', page)
        self.assertIn('&amp;', page)

    def test_the_page_makes_no_network_request_and_offers_no_action(self):
        page = render.html(_brief(old_snapshot=_snap()))
        for forbidden in ('http://', 'https://', '<script', 'cdn.', 'fonts.google',
                          '<form', '<button', 'onclick', 'fetch('):
            self.assertNotIn(forbidden, page.lower(), forbidden)
        self.assertIn('<!DOCTYPE html>', page)
        self.assertIn('name="viewport"', page)

    def test_no_sentinel_reaches_any_output(self):
        s = _snap()
        s['entities'][0]['undeclared_extra'] = SENTINEL
        s['code_sync']['detail'] = SENTINEL
        s['processes'] = [{'pid': 1, 'ppid': 0, 'command': SENTINEL}]
        s['raw_stderr'] = SENTINEL
        b = _brief(new_snapshot=s, old_snapshot=_snap())
        for name, text in _all_texts(b).items():
            self.assertNotIn(SENTINEL, text, name)

    def test_the_briefing_modules_import_no_process_socket_or_network_library(self):
        forbidden = {'subprocess', 'socket', 'urllib', 'http', 'requests'}
        for name in ('owner_briefing', 'render'):
            tree = ast.parse((_root / f'{name}.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split('.')[0], forbidden, name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split('.')[0], forbidden, name)

    def test_offline_generation_touches_no_live_source(self):
        def boom(*a, **k):
            raise AssertionError('the offline briefing reached a live source')
        with patch.object(subprocess, 'run', boom), patch.object(subprocess, 'Popen', boom), \
             patch.object(socket, 'socket', boom), patch.object(socket, 'create_connection', boom):
            b = _brief(old_snapshot=_snap())
            render.markdown(b)
            render.html(b)
        self.assertEqual(b['mode'], 'comparison')


class RunContract(unittest.TestCase):
    """The CLI: what must be refused, and what must never be half-published."""

    def _args(self, **over):
        base = dict(new=None, old=None, diff=None, capture=False, capture_into=None,
                    production=Path('/nonexistent-production'), first_run=False,
                    baseline_latest_in=None, output=None)
        base.update(over)
        return types.SimpleNamespace(**base)

    def _sets(self, td, old=None, new=None):
        return (_write(Path(td) / 'old', old or _snap()),
                _write(Path(td) / 'new', new if new is not None else _snap()))

    def test_a_full_offline_run_publishes_every_artifact_with_a_manifest(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a, b = self._sets(td)
            out = Path(td) / 'run'
            final, briefing, manifest = brief_cli.run(
                self._args(old=a, new=b, output=out))
            produced = {p.name for p in final.iterdir()}
        self.assertEqual(produced, {'owner_briefing.json', 'owner_briefing.md', 'index.html',
                                    'source_of_truth.json', 'source_of_truth.md',
                                    'diff.json', 'changes.md', 'run_manifest.json'})
        self.assertEqual(manifest['schema_version'], brief_cli.RUN_MANIFEST_SCHEMA)
        self.assertEqual(manifest['writers_invoked'], 'NONE')
        self.assertFalse(manifest['production_written'])
        self.assertFalse(manifest['production_read_by_this_run'])
        self.assertTrue(all(len(o['sha256']) == 64 for o in manifest['outputs']))
        self.assertEqual(manifest['inputs']['baseline_selection']['mode'], 'explicit')

    def test_capture_comparison_and_page_times_stay_distinct(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a, b = self._sets(td)
            _, briefing, manifest = brief_cli.run(
                self._args(old=a, new=b, output=Path(td) / 'run'))
        self.assertEqual(manifest['inputs']['capture']['observed_at'],
                         _snap()['finished_at'])
        self.assertNotEqual(manifest['inputs']['comparison_generated_at'],
                            manifest['inputs']['capture']['observed_at'])
        self.assertNotEqual(manifest['page_generated_at'],
                            manifest['inputs']['capture']['observed_at'])

    def test_a_diff_from_another_run_is_refused(self):
        brief_cli = _load('brief')
        other = _snap(finished_at='2026-09-19T11:11:11+00:00')
        with tempfile.TemporaryDirectory() as td:
            a, b = self._sets(td)
            c = _write(Path(td) / 'other', other)
            stale = Path(td) / 'stalediff'
            stale.mkdir()
            (stale / 'diff.json').write_text(json.dumps(
                d.compare(d.load_set(a), d.load_set(c))), encoding='utf-8')
            with self.assertRaises(brief_cli.diff_mod.IncompatibleInput) as ctx:
                brief_cli.run(self._args(old=a, new=b, diff=stale, output=Path(td) / 'run'))
        self.assertIn('must come from one run', str(ctx.exception))

    def test_a_corrupt_input_leaves_no_successful_set(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a, _ = self._sets(td)
            broken = Path(td) / 'broken'
            broken.mkdir()
            (broken / 'snapshot.json').write_text(
                '{"schema_version":"cartographer.snapshot/0.3","entities":[]}')
            out = Path(td) / 'run'
            with self.assertRaises(brief_cli.diff_mod.IncompatibleInput):
                brief_cli.run(self._args(old=a, new=broken, output=out))
            self.assertFalse(out.exists())
            self.assertFalse(out.with_name(out.name + '.incomplete').exists())

    def test_main_refuses_loudly_on_a_corrupt_input(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            broken = Path(td) / 'broken'
            broken.mkdir()
            (broken / 'snapshot.json').write_text('{ not json')
            out = Path(td) / 'run'
            with self.assertRaises(SystemExit) as ctx:
                brief_cli.main(['--new', str(broken), '--first-run', '--output', str(out)])
        self.assertIn('INCOMPATIBLE INPUT', str(ctx.exception))
        self.assertIn('NOT "nothing changed"', str(ctx.exception))
        self.assertFalse(out.exists())

    def test_an_existing_output_directory_is_never_overwritten(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a, b = self._sets(td)
            out = Path(td) / 'run'
            out.mkdir()
            (out / 'precious.txt').write_text('earlier result')
            with self.assertRaises(SystemExit):
                brief_cli.run(self._args(old=a, new=b, output=out))
            self.assertEqual((out / 'precious.txt').read_text(), 'earlier result')

    def test_a_baseline_is_required_unless_first_run_is_asked_for(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            _, b = self._sets(td)
            with self.assertRaises(SystemExit) as ctx:
                brief_cli.run(self._args(new=b, output=Path(td) / 'run'))
            self.assertIn('baseline is required', str(ctx.exception))
            final, briefing, manifest = brief_cli.run(
                self._args(new=b, first_run=True, output=Path(td) / 'first'))
            self.assertEqual(briefing['mode'], 'first_run')
            self.assertEqual(manifest['inputs']['baseline_selection']['mode'], 'none')
            self.assertNotIn('diff.json', {p.name for p in final.iterdir()})

    def test_automatic_baseline_selection_must_be_asked_for_and_is_recorded(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / 'store'
            store.mkdir()
            _write(store / 'set-a', _snap())
            _write(store / 'set-b', _snap())
            newest = _write(store / 'set-c', _snap())
            _, briefing, manifest = brief_cli.run(
                self._args(new=newest, baseline_latest_in=store, output=Path(td) / 'run'))
        selection = manifest['inputs']['baseline_selection']
        self.assertEqual(selection['mode'], 'auto-latest-by-name')
        self.assertTrue(selection['chosen'].endswith('set-b'))
        self.assertEqual(selection['considered'], ['set-a', 'set-b'])
        self.assertIn('ЯВНО запрошен', selection['reason'])

    def test_one_shot_wiring_runs_capture_once_and_invokes_no_writer(self):
        brief_cli = _load('brief')
        calls = []
        with tempfile.TemporaryDirectory() as td:
            _, b = self._sets(td)

            def fake_capture(production, output_root, checks, protected=()):
                calls.append((production, tuple(protected)))
                checks.append({'check': 'capture_written', 'result': 'PASS'})
                return str(b)

            with patch.object(brief_cli, '_capture', fake_capture):
                final, briefing, manifest = brief_cli.run(self._args(
                    capture=True, first_run=True, output=Path(td) / 'run'))
            self.assertEqual(len(calls), 1)
            self.assertEqual(manifest['writers_invoked'], 'NONE')
            self.assertTrue(any(c['check'] == 'capture_written' for c in manifest['checks']))
            self.assertTrue((final / 'index.html').is_file())


if __name__ == '__main__':
    unittest.main()


class CaptureOutputIsGuardedAgainstEveryObservedTree(unittest.TestCase):
    """ARB round 4, reproduced: `_capture` checked the target against production only,
    but which trees are observed is known only after collect() returns them — so a
    capture wrote straight into an observed worktree."""

    def _stub_snapshot(self, repositories):
        brief_cli = _load('brief')
        import snapshot as snapshot_mod
        import system_map as map_mod
        snap = _snap()
        snap['repositories'] = repositories
        saved = (snapshot_mod.collect, map_mod.build, map_mod.validate,
                 snapshot_mod.summary, map_mod.mermaid)
        snapshot_mod.collect = lambda *a, **k: snap
        map_mod.build = lambda s: {'nodes': [], 'edges': []}
        map_mod.validate = lambda m: True
        snapshot_mod.summary = lambda s, g=None: 'summary\n'
        map_mod.mermaid = lambda m, s: 'map\n'
        return brief_cli, snapshot_mod, map_mod, saved

    def _restore(self, snapshot_mod, map_mod, saved):
        (snapshot_mod.collect, map_mod.build, map_mod.validate,
         snapshot_mod.summary, map_mod.mermaid) = saved

    def _repos(self, prod, worktree):
        return [{'path': str(prod), 'head': 'h' * 40, 'cached_origin_main': 'a' * 40,
                 'remote_origin_main': 'a' * 40,
                 'drift': {'reference_sha': 'a' * 40, 'changed_or_missing_on_disk': [],
                           'production_only_tracked': [], 'production_only_untracked': []},
                 'worktrees': [{'worktree': str(worktree), 'HEAD': 'c' * 40,
                                'exists': True}]}]

    def test_a_capture_may_not_be_written_inside_an_observed_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            prod, wt = td / 'prod', td / 'observed'
            prod.mkdir()
            wt.mkdir()
            cli, sm, mm, saved = self._stub_snapshot(self._repos(prod, wt))
            try:
                with self.assertRaises(ValueError) as ctx:
                    cli._capture(prod, wt / 'inside', [])
                message = str(ctx.exception)
                self.assertIn('outside', message)
                self.assertIn('observed', message)
                self.assertEqual(list((wt / 'inside').glob('*')) if (wt / 'inside').exists()
                                 else [], [])
            finally:
                self._restore(sm, mm, saved)

    def test_a_symlink_into_an_observed_worktree_is_caught_too(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            prod, wt = td / 'prod', td / 'observed'
            prod.mkdir()
            wt.mkdir()
            (td / 'alias').symlink_to(wt)
            cli, sm, mm, saved = self._stub_snapshot(self._repos(prod, wt))
            try:
                with self.assertRaises(ValueError):
                    cli._capture(prod, td / 'alias' / 'inside', [])
            finally:
                self._restore(sm, mm, saved)

    def test_a_capture_may_not_be_written_inside_the_named_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            prod, wt = td / 'prod', td / 'observed'
            prod.mkdir()
            wt.mkdir()
            baseline = _write(td / 'baseline', _snap())
            cli, sm, mm, saved = self._stub_snapshot(self._repos(prod, wt))
            try:
                with self.assertRaises(ValueError):
                    cli._capture(prod, baseline / 'inside', [], protected=[baseline])
            finally:
                self._restore(sm, mm, saved)

    def test_an_outside_output_is_allowed_and_records_the_check(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            prod, wt = td / 'prod', td / 'observed'
            prod.mkdir()
            wt.mkdir()
            cli, sm, mm, saved = self._stub_snapshot(self._repos(prod, wt))
            checks = []
            try:
                target = cli._capture(prod, td / 'outside', checks)
            finally:
                self._restore(sm, mm, saved)
            self.assertTrue((Path(target) / 'snapshot.json').is_file())
            names = {c['check'] for c in checks}
            self.assertIn('capture_output_outside_every_observed_tree', names)

    def test_a_report_may_not_be_written_inside_its_own_input_set(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap())
            b = _write(Path(td) / 'new', _snap())
            with self.assertRaises(ValueError) as ctx:
                brief_cli.run(types.SimpleNamespace(
                    new=b, old=a, diff=None, capture=False, capture_into=None,
                    production=Path('/nonexistent'), first_run=False,
                    baseline_latest_in=None, output=b / 'report'))
            self.assertIn('outside', str(ctx.exception))


class StoredDiffMustBeTheRealComparison(unittest.TestCase):
    """ARB round 4, reproduced: a file with the right schema, the right input hashes,
    `counts.material = 999` and an empty `changes` list was accepted."""

    def _stage(self, td, mutate=None):
        brief_cli = _load('brief')
        old = _write(Path(td) / 'old', _snap())
        new = _write(Path(td) / 'new', _snap())
        real = brief_cli.diff_mod.compare(brief_cli.diff_mod.load_set(old),
                                          brief_cli.diff_mod.load_set(new))
        stored = copy.deepcopy(real)
        if mutate:
            mutate(stored)
        directory = Path(td) / 'stored'
        directory.mkdir()
        (directory / 'diff.json').write_text(json.dumps(stored), encoding='utf-8')
        return brief_cli, old, new, directory

    def _refuse(self, mutate, fragment, reseal=False):
        def apply(stored):
            mutate(stored)
            if reseal:
                # A self-consistent forgery: its own digest describes its own content, so
                # only recomputing the comparison can expose it. That is the point — a
                # recorded digest proves nothing about correctness.
                stored['semantic_digest'] = _load('diff').semantic_digest(stored)
        with tempfile.TemporaryDirectory() as td:
            cli, old, new, stored = self._stage(td, apply)
            with self.assertRaises(cli.diff_mod.IncompatibleInput) as ctx:
                cli._load_stored_diff(stored, cli.diff_mod.load_set(old),
                                      cli.diff_mod.load_set(new), [])
        self.assertIn(fragment, str(ctx.exception))

    def test_the_reported_bogus_diff_is_refused(self):
        def bogus(stored):
            stored['counts'] = {'material': 999}
            stored['changes'] = []
        self._refuse(bogus, 'does not match a fresh comparison', reseal=True)

    def test_an_incomplete_diff_is_refused(self):
        self._refuse(lambda s: s.pop('findings'), 'incomplete: missing findings')

    def test_contradictory_counts_are_refused(self):
        self._refuse(lambda s: s['counts'].update(material=42),
                     'does not match a fresh comparison', reseal=True)

    def test_altered_content_under_unchanged_input_hashes_is_refused(self):
        def tamper(stored):
            stored['owner_decision_candidates'] = []
        self._refuse(tamper, 'does not match a fresh comparison', reseal=True)

    def test_a_self_inconsistent_digest_is_refused(self):
        self._refuse(lambda s: s.update(semantic_digest='0' * 64),
                     'does not match its own content')

    def test_a_truncated_or_unreadable_file_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cli, old, new, stored = self._stage(td)
            (stored / 'diff.json').write_text('{ not json')
            with self.assertRaises(cli.diff_mod.IncompatibleInput) as ctx:
                cli._load_stored_diff(stored, cli.diff_mod.load_set(old),
                                      cli.diff_mod.load_set(new), [])
            self.assertIn('could not be read', str(ctx.exception))

    def test_a_genuine_stored_diff_is_accepted_and_the_check_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            cli, old, new, stored = self._stage(td)
            checks = []
            got = cli._load_stored_diff(stored, cli.diff_mod.load_set(old),
                                        cli.diff_mod.load_set(new), checks)
            self.assertEqual(got['schema_version'], cli.diff_mod.DIFF_SCHEMA)
            self.assertIn('stored_diff_recomputed_and_identical',
                          {c['check'] for c in checks})

    def test_a_refused_stored_diff_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            def forge(s):
                s['counts'].update(material=999)
                s['semantic_digest'] = _load('diff').semantic_digest(s)
            cli, old, new, stored = self._stage(td, forge)
            out = Path(td) / 'run'
            with self.assertRaises(cli.diff_mod.IncompatibleInput):
                cli.run(types.SimpleNamespace(
                    new=new, old=old, diff=stored, capture=False, capture_into=None,
                    production=Path('/nonexistent'), first_run=False,
                    baseline_latest_in=None, output=out))
            self.assertFalse(out.exists())
            self.assertFalse(out.with_name(out.name + '.incomplete').exists())


class ManifestTellsTheTruthPerStage(unittest.TestCase):
    """ARB round 4: `network_used: false` was written unconditionally, including for
    --capture runs, while the capture asks git for the live remote ref."""

    def _args(self, **over):
        base = dict(new=None, old=None, diff=None, capture=False, capture_into=None,
                    production=Path('/nonexistent'), first_run=False,
                    baseline_latest_in=None, output=None)
        base.update(over)
        return types.SimpleNamespace(**base)

    def test_an_offline_run_claims_no_network_only_for_the_stages_it_ran(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap())
            b = _write(Path(td) / 'new', _snap())
            _, _, manifest = brief_cli.run(self._args(old=a, new=b, output=Path(td) / 'run'))
        stages = manifest['stages']
        self.assertNotIn('network_used', manifest)     # no blanket claim any more
        self.assertFalse(stages['capture']['performed_by_this_run'])
        self.assertIn('not this run', stages['capture']['probes_recorded_by'])
        self.assertFalse(stages['interpretation']['network_used'])
        self.assertFalse(stages['presentation']['network_used'])
        self.assertIn('reaching_modules_imported', stages['offline_evidence'])

    def test_a_capture_run_admits_the_live_probes_it_made(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            b = _write(Path(td) / 'new', _snap())

            def fake_capture(production, output_root, checks, protected=()):
                checks.append({'check': 'capture_written', 'result': 'PASS'})
                return str(b)

            with patch.object(brief_cli, '_capture', fake_capture):
                _, _, manifest = brief_cli.run(self._args(
                    capture=True, first_run=True, output=Path(td) / 'run'))
        capture = manifest['stages']['capture']
        self.assertTrue(capture['performed_by_this_run'])
        self.assertTrue(capture['observes_live_sources'])
        self.assertEqual(capture['probes_recorded_by'], 'this run')
        self.assertTrue(manifest['production_read_by_this_run'])
        remote = [p for p in capture['network_probes'] if 'ls-remote' in p['probe']]
        self.assertTrue(remote)
        self.assertTrue(remote[0]['reaches_beyond_this_machine'])
        self.assertIn(remote[0]['outcome'], ('answered', 'no answer recorded'))

    def test_the_manifest_never_stores_a_remote_url_or_a_raw_response(self):
        brief_cli = _load('brief')
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap())
            b = _write(Path(td) / 'new', _snap())
            _, _, manifest = brief_cli.run(self._args(old=a, new=b, output=Path(td) / 'run'))
        blob = json.dumps(manifest, ensure_ascii=False)
        for forbidden in ('https://', 'git@', 'ssh://', 'Authorization', 'token'):
            self.assertNotIn(forbidden, blob, forbidden)
        self.assertIn('no remote URL', json.dumps(manifest['stages'], ensure_ascii=False))

    def test_an_unanswered_probe_is_recorded_as_unanswered_not_as_false(self):
        brief_cli = _load('brief')
        s = _snap()
        s['repositories'][0]['remote_origin_main'] = None
        s['ollama']['api_reachable'] = False
        with tempfile.TemporaryDirectory() as td:
            b = _write(Path(td) / 'new', s)
            _, _, manifest = brief_cli.run(self._args(new=b, first_run=True,
                                                      output=Path(td) / 'run'))
        outcomes = {p['outcome'] for p in manifest['stages']['capture']['network_probes']}
        self.assertEqual(outcomes, {'no answer recorded'})


class AttentionWordingMatchesTheEvidence(unittest.TestCase):
    """ARB round 4: three attention texts claimed more than the observation shows."""

    def test_drift_does_not_claim_that_the_differing_code_runs(self):
        text = ob.ATTENTION_RULES['DRIFT_CHANGED_OR_MISSING_ON_DISK'][1]
        self.assertIn('РАЗЛИЧИЕ СОДЕРЖИМОГО', text)
        self.assertIn('не равно', text)
        self.assertNotIn('Прод исполняет', text)

    def test_absence_from_a_commit_does_not_claim_the_file_exists_nowhere_else(self):
        for rule in ('DRIFT_PRODUCTION_ONLY_TRACKED', 'DRIFT_PRODUCTION_ONLY_UNTRACKED'):
            text = ob.ATTENTION_RULES[rule][1]
            self.assertNotIn('живёт только на машине', text)
            self.assertNotIn('Существует только локально', text)
        self.assertIn('только на этой машине',
                      ob.ATTENTION_RULES['DRIFT_PRODUCTION_ONLY_TRACKED'][1])

    def test_a_missing_plist_does_not_claim_what_happens_after_a_reboot(self):
        headline, text = ob.ATTENTION_RULES['LOADED_WITHOUT_INSTALLED_PLIST']
        self.assertIn('в проверенных каталогах', headline)
        self.assertIn('три каталога plist', text)
        self.assertIn('после перезагрузки отсюда НЕ следует', text)
        self.assertNotIn('перезагрузка машины его не вернёт', text)

    def test_the_corrected_wording_reaches_the_page(self):
        b = _brief()
        page, md = render.html(b), render.markdown(b)
        for a in b['attention']:
            if a['rule_code'].startswith('DRIFT_'):
                self.assertIn(a['practical_meaning'][:60], md)
                self.assertIn('не наблюдается вовсе', page + md) if \
                    a['rule_code'] == 'DRIFT_CHANGED_OR_MISSING_ON_DISK' else None


class NewFindingsAreCountedNotCrashedOn(unittest.TestCase):
    """Found by the first one-shot run that produced a new finding: `findings.new` in the
    comparison holds IDS, not records, and reading them as dicts raised TypeError. Every
    earlier run had an empty list, so nothing noticed."""

    def test_a_new_finding_is_attributed_to_this_comparison(self):
        old = _snap()
        new = _snap()
        new['findings'] = new['findings'] + [
            {'id': f'DRIFT_PRODUCTION_ONLY_TRACKED:{REPO}:scripts/brand_new.py',
             'kind': 'DRIFT', 'rule_code': 'DRIFT_PRODUCTION_ONLY_TRACKED',
             'subject': REPO, 'context': 'scripts/brand_new.py', 'reason': 'new'}]
        new['repositories'][0]['drift']['production_only_tracked'].append(
            'scripts/brand_new.py')
        b = _brief(new_snapshot=new, old_snapshot=old)
        item = [a for a in b['attention']
                if a['rule_code'] == 'DRIFT_PRODUCTION_ONLY_TRACKED'][0]
        self.assertEqual(item['since_last_observation'],
                         {'new_in_this_comparison': 1, 'carried_over': 0})
        self.assertIn('новых: 1', render.html(b))
