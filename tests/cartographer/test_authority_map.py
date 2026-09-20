"""Regressions for the Authority Map (Director OS Phase 3).

The risk of an authority map is that it invents authority. Each test below pins one way
it could: choosing a winner where no rule exists, calling a designed outcome a fault,
reading an unreadable source as "no drift", or assigning a status without evidence.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
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


am = _load('authority_map')
pr = _load('portal_render')
SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_P3'


def _repo(td):
    """A production-shaped git tree with an origin/main ref and every drift class.

    Built the way the accepted Phase 0B drift fixture is built: a real repository, a real
    ref, and a worktree that genuinely differs from it.
    """
    root = Path(td) / 'prod'
    (root / 'scripts').mkdir(parents=True)
    (root / 'data').mkdir(parents=True)
    (root / 'architecture').mkdir(parents=True)

    def g(*args):
        return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)

    g('init')
    g('config', 'user.name', 'T')
    g('config', 'user.email', 't@e.invalid')
    for name in ('same.py', 'changed.py', 'gone.py', 'retired.py'):
        (root / 'scripts' / name).write_text(f'# {name}\n')
    (root / 'architecture/manifest.json').write_text(json.dumps({'agents': [
        {'label': 'com.spa.declared_and_loaded', 'role': 'monitoring', 'layer': 'x',
         'intent': 'active', 'produces': [], 'consumes': [], 'governed_by': []},
        {'label': 'com.spa.declared_not_loaded', 'role': 'ops', 'layer': 'x',
         'intent': 'active', 'produces': [], 'consumes': [], 'governed_by': []}]}))
    (root / 'data/agent_registry.json').write_text(json.dumps({'agents': [
        {'label': 'com.spa.declared_and_loaded', 'role': 'monitoring'},
        {'label': 'com.spa.registry_only', 'role': 'ops'}]}))
    (root / 'data/code_sync_status.json').write_text(json.dumps({
        'timestamp': '2026-09-20T00:00:00+00:00', 'result': 'IN_SYNC',
        'detail': 'no code drift', 'origin_main': 'x' * 40, 'files_changed': 0,
        'retired_code': ['scripts/retired.py'], 'retired_instructions': [],
        'source': 'code_sync_from_origin'}))
    g('add', '.')
    g('commit', '-m', 'A')
    sha_a = g('rev-parse', 'HEAD').decode().strip()
    g('rm', '-q', 'scripts/retired.py')
    g('commit', '-m', 'B: origin retires a file')
    sha_b = g('rev-parse', 'HEAD').decode().strip()
    g('update-ref', 'refs/remotes/origin/main', sha_b)
    g('checkout', '--detach', sha_a)          # worktree keeps the retired file
    (root / 'scripts/changed.py').write_text('# changed on disk\n')
    (root / 'scripts/gone.py').unlink()
    (root / 'scripts/never_delivered.py').write_text('# untracked\n')
    return root, sha_b


def _snapshot(td, **over):
    """A Cartographer set shaped like the accepted contract."""
    carto = Path(td) / 'carto'
    carto.mkdir()
    snap = {
        'schema_version': 'cartographer.snapshot/0.3',
        'started_at': '2026-09-19T10:00:00+00:00',
        'finished_at': '2026-09-19T10:00:09+00:00',
        'declared_plists_in_repo': {'com.spa.declared_not_loaded': '/repo/launchd/x.plist'},
        'entities': [
            {'id': 'com.spa.declared_and_loaded', 'status': 'LIVE', 'intent': 'active',
             'stages': {'DECLARED': True, 'REGISTERED': True, 'INSTALLED': True,
                        'LOADED': True, 'RUNNING': True, 'PRODUCING_OUTPUT': None,
                        'HEALTHY': None},
             'installed_paths': [{'plist': '/home/LaunchAgents/a.plist',
                                  'entrypoint': {'target': '/x/a.sh'}}],
             'declared_outputs': [{'relpath': 'data/fresh.json', 'exists': True,
                                   'fresh': True, 'slo_hours': 3, 'age_seconds': 10},
                                  {'relpath': 'data/stale.json', 'exists': True,
                                   'fresh': False, 'slo_hours': 1, 'age_seconds': 99999}],
             'document_references': []},
            {'id': 'com.spa.declared_not_loaded', 'status': 'DEGRADED', 'intent': 'active',
             'stages': {'DECLARED': True, 'REGISTERED': False, 'INSTALLED': True,
                        'LOADED': False, 'RUNNING': False, 'PRODUCING_OUTPUT': None,
                        'HEALTHY': None},
             'installed_paths': [], 'declared_outputs': [
                 {'relpath': 'data/absent.json', 'exists': False, 'fresh': None,
                  'slo_hours': 2, 'age_seconds': None}],
             'declared_plist_in_repo': '/repo/launchd/x.plist',
             'document_references': []},
            {'id': 'com.spa.registry_only', 'status': 'UNKNOWN', 'intent': None,
             'stages': {'DECLARED': False, 'REGISTERED': True, 'INSTALLED': False,
                        'LOADED': None, 'RUNNING': None, 'PRODUCING_OUTPUT': None,
                        'HEALTHY': None},
             'installed_paths': [], 'declared_outputs': [], 'document_references': []},
        ],
        'repositories': [], 'findings': [],
    }
    snap.update(over)
    (carto / 'snapshot.json').write_text(json.dumps(snap))
    (carto / 'system_map.md').write_text('# map\n')
    return carto, snap


def _build(td, **over):
    root, origin_sha = _repo(td)
    carto, snap = _snapshot(td, **over)
    return am.build_authority_map(root, carto), root, origin_sha, carto


def _by_path(the_map, entity_type=None):
    return {e['path']: e for e in the_map['entities']
            if entity_type is None or e['entity_type'] == entity_type}


class CodeDriftClassification(unittest.TestCase):
    def test_identical_content_is_in_sync_and_aggregated(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        agg = [e for e in the_map['entities']
               if e['entity_type'] == 'code_file_aggregate'][0]
        self.assertEqual(agg['drift_status'], 'IN_SYNC')
        self.assertGreaterEqual(agg['observed']['files_in_sync'], 1)
        self.assertIn('утопить', agg['aggregate_note'])
        # the unchanged file is not listed individually — that is the point of the aggregate
        self.assertNotIn('scripts/same.py', _by_path(the_map, 'code_file'))

    def test_changed_content_is_modified(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'code_file')['scripts/changed.py']
        self.assertEqual(e['drift_status'], 'MODIFIED')
        self.assertEqual(e['severity'], 'WARNING')
        self.assertTrue(e['origin_present'])
        self.assertTrue(e['production_present'])
        self.assertTrue(e['evidence'])

    def test_present_in_origin_absent_on_disk_is_missing_in_production(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'code_file')['scripts/gone.py']
        self.assertEqual(e['drift_status'], 'MISSING_IN_PRODUCTION')
        self.assertTrue(e['origin_present'])
        self.assertFalse(e['production_present'])

    def test_tracked_on_disk_absent_in_origin_is_extra_in_production(self):
        """The designed outcome of the canonical path: a checkout cannot delete."""
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'code_file')['scripts/retired.py']
        self.assertEqual(e['drift_status'], 'EXTRA_IN_PRODUCTION')
        self.assertFalse(e['origin_present'])
        self.assertTrue(e['production_present'])
        self.assertIn('checkout', e['authority_limit'])
        self.assertIn('не удалит', e['severity_basis'])

    def test_untracked_on_disk_is_missing_in_origin_not_extra(self):
        """Two different facts: origin DELETED a file, versus never having had it."""
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'code_file')['scripts/never_delivered.py']
        self.assertEqual(e['drift_status'], 'MISSING_IN_ORIGIN')
        self.assertNotEqual(e['drift_status'], 'EXTRA_IN_PRODUCTION')

    def test_nothing_is_deleted_while_the_map_is_built(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, root, *_ = _build(td)
            self.assertTrue((root / 'scripts/retired.py').is_file())
            self.assertTrue((root / 'scripts/never_delivered.py').is_file())
            self.assertFalse(the_map['auto_fix_performed'])
            index_before = (root / '.git/index').read_bytes()
            am.build_authority_map(root, Path(td) / 'carto')
            self.assertEqual(index_before, (root / '.git/index').read_bytes())


class DeclaredVersusObserved(unittest.TestCase):
    def test_declared_but_not_loaded_is_declared_not_observed(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'launchd_agent')['com.spa.declared_not_loaded']
        self.assertEqual(e['drift_status'], 'DECLARED_NOT_OBSERVED')
        self.assertEqual(len(e['statements']), 3)

    def test_observed_but_not_declared_is_observed_not_declared(self):
        with tempfile.TemporaryDirectory() as td:
            carto, snap = _snapshot(td)
            snap['entities'].append({
                'id': 'com.spa.ghost', 'status': 'LIVE', 'intent': None,
                'stages': {'DECLARED': False, 'REGISTERED': False, 'INSTALLED': True,
                           'LOADED': True, 'RUNNING': True, 'PRODUCING_OUTPUT': None,
                           'HEALTHY': None},
                'installed_paths': [{'plist': '/home/LaunchAgents/g.plist',
                                     'entrypoint': {'target': '/x/g.sh'}}],
                'declared_outputs': [], 'document_references': []})
            (carto / 'snapshot.json').write_text(json.dumps(snap))
            root, _ = _repo(td)
            the_map = am.build_authority_map(root, carto)
        e = _by_path(the_map, 'launchd_agent')['com.spa.ghost']
        self.assertEqual(e['drift_status'], 'OBSERVED_NOT_DECLARED')

    def test_membership_disagreement_is_authority_undefined_not_a_winner(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        e = _by_path(the_map, 'launchd_agent')['com.spa.registry_only']
        self.assertEqual(e['authority_status'], 'AUTHORITY_UNDEFINED')
        self.assertIsNone(e['authoritative_source'])
        self.assertIsNone(e['authority_established_by'])
        self.assertIn('правила', e['authority_limit'])

    def test_a_stale_artifact_uses_the_declared_slo(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        stale = [e for e in the_map['entities']
                 if e['entity_type'] == 'declared_artifact'
                 and e['drift_status'] == 'STALE']
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]['observed']['slo_hours'], 1)
        self.assertEqual(stale[0]['observed']['producer_attribution'], 'UNKNOWN')
        fresh = [e for e in the_map['entities'] if e['path'] == 'data/fresh.json']
        self.assertEqual(fresh, [], 'артефакт в норме не должен попадать в расхождения')


class ExcludedAndGenerated(unittest.TestCase):
    def test_paths_the_sync_never_carries_are_ignored_not_drift(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        excluded = _by_path(the_map, 'excluded_path')
        self.assertIn('data', excluded)
        self.assertEqual(excluded['data']['drift_status'], 'IGNORED')
        self.assertEqual(excluded['data']['severity'], 'INFO')
        self.assertIn('NEVER data/', excluded['data']['evidence'][0]['detail'])

    def test_generated_files_are_generated_not_compared_to_origin(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        gen = _by_path(the_map, 'generated_state')
        self.assertIn('data/agent_registry.json', gen)
        self.assertEqual(gen['data/agent_registry.json']['drift_status'], 'GENERATED')
        self.assertIsNone(gen['data/agent_registry.json']['origin_present'])

    def test_the_sync_report_is_derived_and_names_its_own_limit(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        report = [e for e in the_map['entities'] if e['entity_type'] == 'sync_report'][0]
        self.assertEqual(report['drift_status'], 'GENERATED')
        self.assertEqual(report['observed']['result'], 'IN_SYNC')
        self.assertEqual(report['observed']['retired_code_count'], 1)
        self.assertIn('не удаляет', report['authority_limit'])


class ContractAndRefusals(unittest.TestCase):
    def test_every_status_carries_evidence_and_a_known_vocabulary(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        for e in the_map['entities']:
            self.assertIn(e['drift_status'], am.DRIFT_STATUSES, e['entity_id'])
            self.assertIn(e['severity'], am.SEVERITIES, e['entity_id'])
            self.assertTrue(e['evidence'], e['entity_id'])
            self.assertTrue(e['entity_id'] and e['entity_type'])

    def test_an_unresolvable_authoritative_commit_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'bare'
            root.mkdir()
            subprocess.check_output(['git', 'init'], cwd=root, stderr=subprocess.DEVNULL)
            carto, _ = _snapshot(td)
            with self.assertRaises(am.AuthorityInputError) as ctx:
                am.build_authority_map(root, carto)
        self.assertIn('НЕ', str(ctx.exception))
        self.assertIn('расхождений нет', str(ctx.exception))

    def test_an_unreadable_git_read_is_a_refusal_not_no_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root, sha = _repo(td)
            with patch.object(am, '_git', return_value=None):
                with self.assertRaises(am.AuthorityInputError) as ctx:
                    am.compare_scope(root, sha)
        self.assertIn('НЕ значит «расхождений нет»', str(ctx.exception))

    def test_a_malformed_snapshot_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto = Path(td) / 'broken'
            carto.mkdir()
            (carto / 'snapshot.json').write_text('{"schema_version":"x"}')
            with self.assertRaises(am.AuthorityInputError):
                am.build_authority_map(root, carto)

    def test_validate_rejects_a_duplicate_id_and_a_bad_count(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        dup = copy.deepcopy(the_map)
        dup['entities'].append(dict(dup['entities'][0]))
        dup['counts']['entities'] = len(dup['entities'])
        with self.assertRaises(am.AuthorityInputError) as ctx:
            am.validate_authority_map(dup, 'test')
        self.assertIn('дубль entity_id', str(ctx.exception))
        wrong = copy.deepcopy(the_map)
        wrong['counts']['entities'] = 999
        with self.assertRaises(am.AuthorityInputError) as ctx:
            am.validate_authority_map(wrong, 'test')
        self.assertIn('расходится', str(ctx.exception))

    def test_validate_rejects_a_status_outside_the_vocabulary(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        bad = copy.deepcopy(the_map)
        bad['entities'][0]['drift_status'] = 'PROBABLY_FINE'
        with self.assertRaises(am.AuthorityInputError):
            am.validate_authority_map(bad, 'test')

    def test_the_output_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            out = Path(td) / 'out'
            out.mkdir()
            (out / 'precious.txt').write_text('earlier')
            with self.assertRaises(SystemExit):
                am.main(['--production', str(root), '--cartographer', str(carto),
                         '--output', str(out)])
            self.assertEqual((out / 'precious.txt').read_text(), 'earlier')

    def test_a_symlink_into_production_cannot_receive_the_map(self):
        """The output guard of the accepted phases is reused, symlinks resolved."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            alias = Path(td) / 'alias'
            alias.symlink_to(root)
            d = _load('diff')
            with self.assertRaises(ValueError):
                d.validate_output(alias / 'inside', [root])


class DeterminismAndSafety(unittest.TestCase):
    def test_the_same_tree_gives_the_same_semantic_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            a = am.build_authority_map(root, carto)
            b = am.build_authority_map(root, carto)
        self.assertEqual(am.semantic_view(a), am.semantic_view(b))
        self.assertEqual(a['semantic_digest'], b['semantic_digest'])

    def test_the_digest_ignores_the_clock(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        moved = copy.deepcopy(the_map)
        moved['built_at'] = '2027-01-01T00:00:00+00:00'
        for e in moved['entities']:
            e['observed_at'] = '2027-01-01T00:00:00+00:00'
        self.assertEqual(am.semantic_digest(the_map), am.semantic_digest(moved))

    def test_no_secret_reaches_the_map(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            (root / 'scripts/never_delivered.py').write_text(f'TOKEN = "{SENTINEL}"\n')
            carto, snap = _snapshot(td)
            snap['raw_stderr'] = SENTINEL
            (carto / 'snapshot.json').write_text(json.dumps(snap))
            the_map = am.build_authority_map(root, carto)
        self.assertNotIn(SENTINEL, json.dumps(the_map, ensure_ascii=False))
        self.assertNotIn(SENTINEL, pr._authority(the_map, {'authority_map.json'}))

    def test_file_contents_are_never_copied_only_hashes_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            (root / 'scripts/changed.py').write_text('# unique-marker-in-content\n')
            carto, _ = _snapshot(td)
            the_map = am.build_authority_map(root, carto)
        blob = json.dumps(the_map, ensure_ascii=False)
        self.assertNotIn('unique-marker-in-content', blob)
        e = _by_path(the_map, 'code_file')['scripts/changed.py']
        self.assertRegex(e['observed']['sha256'], r'^[0-9a-f]{64}$')


class RenderedSection(unittest.TestCase):
    def _page(self, the_map):
        return pr._authority(the_map, {'authority_map.json'})

    def test_the_section_offers_no_control_that_could_act(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        import re
        html = self._page(the_map)
        low = html.lower()
        # no machinery that could act
        for forbidden in ('<button', '<form', 'onclick', 'onsubmit', 'fetch(',
                          'xmlhttprequest'):
            self.assertNotIn(forbidden, low, forbidden)
        # and no action word as the LABEL OF A CONTROL. Checking the raw text instead
        # would flag the disclaimer sentence that says these buttons do not exist —
        # the same over-crude check that already misfired once in Phase 2.
        labels = (re.findall(r'<a\b[^>]*>(.*?)</a>', low, re.S)
                  + re.findall(r'<option\b[^>]*>(.*?)</option>', low, re.S)
                  + re.findall(r'<summary\b[^>]*>(.*?)</summary>', low, re.S))
        for label in labels:
            for verb in ('repair', 'sync', 'delete', 'deploy', 'restart', 'удалить',
                         'починить', 'синхронизировать', 'принять', 'перезапустить'):
                self.assertNotIn(verb, label, f'подпись контрола: {label!r}')
        self.assertIn('только читает', low)
        self.assertTrue(labels, 'контролы на странице должны быть (ссылки, фасеты)')

    def test_counts_in_the_section_match_the_map(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        html = self._page(the_map)
        st = the_map['counts']['by_drift_status']
        self.assertIn(f'>{st["EXTRA_IN_PRODUCTION"]}</dd>', html)
        drift_keys = ('MODIFIED', 'MISSING_IN_PRODUCTION', 'EXTRA_IN_PRODUCTION',
                      'MISSING_IN_ORIGIN', 'DECLARED_NOT_OBSERVED',
                      'OBSERVED_NOT_DECLARED', 'STALE')
        total = sum(st.get(k, 0) for k in drift_keys)
        self.assertIn(f'Расхождения ({total})', html)
        self.assertEqual(html.count('class="row"'), total)

    def test_every_problem_row_carries_the_filter_attributes(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        html = self._page(the_map)
        for e in the_map['entities']:
            if e['drift_status'] in ('IN_SYNC', 'IGNORED', 'GENERATED',
                                     'AUTHORITY_UNDEFINED', 'UNKNOWN'):
                continue
            self.assertIn(f'data-astatus="{e["drift_status"]}"', html)
            self.assertIn(f'data-atype="{e["entity_type"]}"', html)
            self.assertIn(f'data-asev="{e["severity"]}"', html)

    def test_hostile_text_in_a_path_is_escaped(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        evil = copy.deepcopy(the_map)
        evil['entities'][0]['path'] = '<img src=x onerror="alert(1)">'
        html = self._page(evil)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img', html)

    def test_an_absent_map_is_named_not_silently_empty(self):
        html = pr._authority(None, set())
        self.assertIn('НЕ значит, что расхождений нет', html)

    def test_the_delivery_chain_is_shown_with_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        html = self._page(the_map)
        self.assertIn('Цепочка доставки', html)
        for step in the_map['delivery_chain']:
            self.assertIn(step['mechanism'][:24], html)


class RetiredCodeIsDetectedWithoutDeleting(unittest.TestCase):
    """The class of drift the live machine carries: origin deleted a file, the checkout
    cannot remove it, so production keeps executing from a tree the authoritative commit
    no longer describes.

    Proven on a fixture this test OWNS. The earlier version looked for an authority map
    under the owner's home directory and SKIPPED when it was absent — a verdict that
    depended on one machine's local files, and a skip that reads exactly like a pass.
    """

    def test_a_retired_file_is_found_named_and_left_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, root, origin_sha, _ = _build(td)
            extra = [e for e in the_map['entities']
                     if e['drift_status'] == 'EXTRA_IN_PRODUCTION']
            self.assertEqual([e['path'] for e in extra], ['scripts/retired.py'])
            for e in extra:
                self.assertFalse(e['origin_present'])
                self.assertTrue(e['production_present'])
                self.assertTrue((root / e['path']).is_file(),
                                'файл обязан остаться на месте: ничего не удаляем')
            # and it is genuinely absent from the authoritative commit
            missing = subprocess.run(
                ['git', 'cat-file', '-e', f'{origin_sha}:scripts/retired.py'],
                cwd=root, capture_output=True)
            self.assertNotEqual(missing.returncode, 0)

    def test_the_sync_report_count_agrees_with_the_detected_files(self):
        """The sync's own witness and the map must tell the same story."""
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        report = [e for e in the_map['entities'] if e['entity_type'] == 'sync_report'][0]
        extra = sum(1 for e in the_map['entities']
                    if e['drift_status'] == 'EXTRA_IN_PRODUCTION')
        self.assertEqual(report['observed']['retired_code_count'], extra)
        self.assertEqual(report['observed']['result'], 'IN_SYNC')
        self.assertEqual(report['observed']['files_changed'], 0)
        self.assertIn('не удаляет', report['authority_limit'])

    def test_a_named_live_map_is_checked_when_one_is_given(self):
        """Opt-in live check. Without the variable no location is invented, and the
        behaviour above is already proven on an owned fixture."""
        path = os.environ.get('CARTOGRAPHER_LIVE_AUTHORITY_MAP')
        if not path:
            self.skipTest('CARTOGRAPHER_LIVE_AUTHORITY_MAP не задан — поведение доказано '
                          'на собственной фикстуре выше')
        given = Path(path)
        the_map = json.loads(
            (given if given.is_file() else given / 'authority_map.json').read_text())
        am.validate_authority_map(the_map, str(given))
        extra = [e for e in the_map['entities']
                 if e['drift_status'] == 'EXTRA_IN_PRODUCTION']
        self.assertGreater(len(extra), 0)
        for e in extra:
            self.assertFalse(e['origin_present'])
            self.assertTrue(Path(the_map['production_root'], e['path']).exists(),
                            f'{e["path"]} обязан быть на месте: ничего не удаляем')


class TheEvidenceGuardIsItselfGuarded(unittest.TestCase):
    """A guard no scene violates is an ornament: removing it changed nothing, because
    every entity in the fixture happens to carry evidence. These scenes break it."""

    def test_build_refuses_an_entity_without_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            real = am.excluded_entities

            def stripped(production):
                rows = real(production)
                rows[0] = {**rows[0], 'evidence': []}
                return rows

            with patch.object(am, 'excluded_entities', stripped):
                with self.assertRaises(am.AuthorityInputError) as ctx:
                    am.build_authority_map(root, carto)
        self.assertIn('без evidence', str(ctx.exception))

    def test_build_refuses_a_status_outside_the_vocabulary(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            real = am.excluded_entities

            def bad_status(production):
                rows = real(production)
                rows[0] = {**rows[0], 'drift_status': 'PROBABLY_FINE'}
                return rows

            with patch.object(am, 'excluded_entities', bad_status):
                with self.assertRaises(am.AuthorityInputError) as ctx:
                    am.build_authority_map(root, carto)
        self.assertIn('неизвестный drift_status', str(ctx.exception))

    def test_build_refuses_duplicate_entity_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _repo(td)
            carto, _ = _snapshot(td)
            real = am.excluded_entities

            def duplicated(production):
                rows = real(production)
                return rows + [dict(rows[0])]

            with patch.object(am, 'excluded_entities', duplicated):
                with self.assertRaises(am.AuthorityInputError) as ctx:
                    am.build_authority_map(root, carto)
        self.assertIn('уникальны', str(ctx.exception))

    def test_validate_refuses_an_entity_whose_evidence_was_stripped(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        stripped = copy.deepcopy(the_map)
        stripped['entities'][0]['evidence'] = []
        with self.assertRaises(am.AuthorityInputError) as ctx:
            am.validate_authority_map(stripped, 'test')
        self.assertIn('evidence', str(ctx.exception))


class TheTaxonomyIsDisjointNotJustDifferentlyNamed(unittest.TestCase):
    """EXTRA_IN_PRODUCTION, MISSING_IN_ORIGIN and OBSERVED_NOT_DECLARED read alike —
    "absent from origin" is literally true of the first two. What separates them is the
    DISCRIMINATOR, and it has to be stated, not implied by the name."""

    def test_every_status_has_a_definition(self):
        for status in am.DRIFT_STATUSES:
            self.assertIn(status, am.DRIFT_STATUS_DEFINITIONS, status)
            self.assertTrue(am.DRIFT_STATUS_DEFINITIONS[status].strip())

    def test_the_definitions_name_the_discriminator(self):
        extra = am.DRIFT_STATUS_DEFINITIONS['EXTRA_IN_PRODUCTION']
        local = am.DRIFT_STATUS_DEFINITIONS['MISSING_IN_ORIGIN']
        self.assertIn('ОТСЛЕЖИВАЕТСЯ', extra)
        self.assertIn('НЕ отслеживается', local)
        self.assertIn('Дискриминатор', local)
        self.assertIn('сущностях', am.DRIFT_STATUS_DEFINITIONS['OBSERVED_NOT_DECLARED'])

    def test_the_three_statuses_never_meet_on_one_entity(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        sets = {s: {e['entity_id'] for e in the_map['entities']
                    if e['drift_status'] == s}
                for s in ('EXTRA_IN_PRODUCTION', 'MISSING_IN_ORIGIN',
                          'OBSERVED_NOT_DECLARED')}
        for a in sets:
            for b in sets:
                if a < b:
                    self.assertEqual(sets[a] & sets[b], set(), f'{a} ∩ {b}')

    def test_one_path_never_receives_two_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        paths = [e['path'] for e in the_map['entities']
                 if e['entity_type'] in ('code_file', 'instruction_file')]
        self.assertEqual(len(paths), len(set(paths)))

    def test_a_status_used_outside_its_scope_is_refused(self):
        """The scope is enforced, not merely documented."""
        with tempfile.TemporaryDirectory() as td:
            the_map, *_ = _build(td)
        wrong = copy.deepcopy(the_map)
        target = [e for e in wrong['entities'] if e['entity_type'] == 'launchd_agent'][0]
        target['drift_status'] = 'EXTRA_IN_PRODUCTION'
        with self.assertRaises(am.AuthorityInputError) as ctx:
            am.validate_authority_map(wrong, 'test')
        self.assertIn('не применим к типу', str(ctx.exception))

    def test_tracked_and_untracked_are_what_actually_separates_them(self):
        """Measured, not asserted: the retired file is tracked, the local one is not."""
        with tempfile.TemporaryDirectory() as td:
            the_map, root, *_ = _build(td)
            for status, expect_tracked in (('EXTRA_IN_PRODUCTION', True),
                                           ('MISSING_IN_ORIGIN', False)):
                for e in [x for x in the_map['entities']
                          if x['drift_status'] == status]:
                    tracked = subprocess.run(
                        ['git', 'ls-files', '--error-unmatch', e['path']],
                        cwd=root, capture_output=True).returncode == 0
                    self.assertEqual(tracked, expect_tracked,
                                     f'{e["path"]} ({status})')
