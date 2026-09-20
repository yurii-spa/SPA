import importlib.util
import json
from pathlib import Path
import unittest

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load('system_map')
SECRET = 'ghp_SENTINEL_NEVER_IN_OUTPUT_0123456789'


def snapshot(**over):
    """Synthetic snapshot in the shape collect() produces. No probes, no filesystem."""
    base = {
        'schema_version': 'cartographer.snapshot/0.2',
        'finished_at': '2026-09-19T00:00:00+00:00',
        'document_index': {'ADR-066': 'docs/decisions/ADR-066-office.md'},
        'entities': [{
            'id': 'com.spa.alpha', 'status': 'LIVE', 'intent': 'active',
            'layer': 'product', 'role': 'monitor', 'schedule': 'interval:3600s',
            'pid': 42, 'last_exit': 0, 'last_exit_basis': 'historical: …',
            'stages': dict.fromkeys(
                ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
                 'PRODUCING_OUTPUT', 'HEALTHY')),
            'domains': {'gui/501': True, 'system': False},
            'declared_consumes': ['data/in.json'],
            'declared_governed_by': ['ADR-066', 'ADR-999'],
            'document_references': [
                {'reference': 'ADR-066', 'kind': 'adr_id', 'outcome': 'resolved',
                 'path': 'docs/decisions/ADR-066-office.md'},
                {'reference': 'docs/CMO_EDITORIAL_LAYER.md', 'kind': 'path',
                 'outcome': 'resolved', 'path': 'docs/CMO_EDITORIAL_LAYER.md'},
                {'reference': 'ADR-999', 'kind': 'adr_id', 'outcome': 'absent', 'path': None},
            ],
            'declared_plist_in_repo': '/repo/launchd/com.spa.alpha.plist',
            'installed_paths': [{
                'plist': '/home/Library/LaunchAgents/com.spa.alpha.plist',
                'plist_domain_dir': '/home/Library/LaunchAgents',
                'working_directory': '/repo', 'keep_alive': None, 'start_interval': 3600,
                'has_calendar_schedule': False, 'environment_keys': ['SPA_ENV'],
                'entrypoint': {'executable': '/bin/bash', 'target_kind': 'script',
                               'target': '/repo/scripts/agent_alpha.sh', 'target_exists': True,
                               'argument_count': 2, 'arguments_omitted': True,
                               'unknown_reason': None},
                'entrypoint_checkout': '/repo',
                'entrypoint_declared_target': 'spa_core.monitoring.alpha',
            }],
            'declared_outputs': [{'relpath': 'data/out.json', 'exists': True, 'fresh': True,
                                  'slo_hours': 3, 'age_seconds': 60, 'is_symlink': False,
                                  'producer_attribution': 'UNKNOWN'}],
        }],
        'repositories': [{'path': '/repo', 'head': 'a' * 40, 'cached_origin_main': 'b' * 40,
                          'remote_origin_main': 'b' * 40, 'drift': {'x': []},
                          'worktrees': [{'worktree': '/wt', 'HEAD': 'c' * 40, 'exists': True,
                                         'detached': True, 'code_drift_vs_cached_ref': None}]}],
    }
    base.update(over)
    return base


class Contract(unittest.TestCase):
    def test_schema_and_vocabularies(self):
        m = sm.build(snapshot())
        self.assertEqual(m['schema_version'], sm.MAP_SCHEMA)
        self.assertEqual(m['evidence_bases'], list(sm.BASES))
        self.assertTrue(m['derived_state'])
        self.assertEqual(m['derived_from']['snapshot_schema'], 'cartographer.snapshot/0.2')

    def test_referential_integrity_holds(self):
        self.assertTrue(sm.validate(sm.build(snapshot())))

    def test_validate_rejects_a_dangling_edge(self):
        m = sm.build(snapshot())
        m['edges'].append({'id': 'x|a|b', 'src': 'launchd_job:ghost', 'dst': 'artifact:ghost',
                           'type': 'produces', 'basis': 'declaration', 'evidence': 'invented'})
        with self.assertRaises(ValueError):
            sm.validate(m)

    def test_validate_rejects_an_edge_without_evidence(self):
        m = sm.build(snapshot())
        m['edges'][0]['evidence'] = ''
        with self.assertRaises(ValueError):
            sm.validate(m)

    def test_every_edge_carries_a_basis_from_the_vocabulary(self):
        m = sm.build(snapshot())
        self.assertTrue(m['edges'])
        for e in m['edges']:
            self.assertIn(e['basis'], sm.BASES)
            self.assertTrue(e['evidence'])

    def test_ids_are_stable_across_rebuilds(self):
        a, b = sm.build(snapshot()), sm.build(snapshot())
        self.assertEqual([n['id'] for n in a['nodes']], [n['id'] for n in b['nodes']])
        self.assertEqual([e['id'] for e in a['edges']], [e['id'] for e in b['edges']])


class Evidence(unittest.TestCase):
    def _edges(self, m, kind):
        return [e for e in m['edges'] if e['type'] == kind]

    def test_produces_and_consumes_are_declarations_not_execution_claims(self):
        m = sm.build(snapshot())
        for kind in ('produces', 'consumes'):
            for e in self._edges(m, kind):
                self.assertEqual(e['basis'], 'declaration')
                self.assertIn('manifest.json', e['evidence'])
        art = [n for n in m['nodes'] if n['id'] == 'artifact:data/out.json'][0]
        self.assertEqual(art['producer_attribution'], 'UNKNOWN')

    def test_wrapper_target_is_static_inference_never_observation(self):
        m = sm.build(snapshot())
        e = self._edges(m, 'declares_target')[0]
        self.assertEqual(e['basis'], 'static_inference')
        self.assertIn('NOT executed', e['evidence'])

    def test_launchd_and_filesystem_edges_are_observations(self):
        m = sm.build(snapshot())
        for kind in ('installed_from', 'declares_entrypoint', 'resides_in', 'declared_in_repo'):
            for e in self._edges(m, kind):
                self.assertEqual(e['basis'], 'observation')

    def test_governed_by_resolves_paths_and_adr_ids_and_names_the_absent_one(self):
        m = sm.build(snapshot())
        docs = {n['key']: n for n in m['nodes'] if n['type'] == 'document'}
        self.assertTrue(docs['ADR-066']['resolved'])
        self.assertEqual(docs['ADR-066']['reference_kind'], 'adr_id')
        self.assertTrue(docs['docs/CMO_EDITORIAL_LAYER.md']['resolved'])
        self.assertEqual(docs['docs/CMO_EDITORIAL_LAYER.md']['reference_kind'], 'path')
        self.assertFalse(docs['ADR-999']['resolved'])
        self.assertEqual(docs['ADR-999']['outcome'], 'absent')
        self.assertTrue(any(u['what'] == 'governed_by_absent' for u in m['unresolved']))

    def test_unverifiable_document_is_not_reported_as_absent(self):
        s = snapshot()
        s['entities'][0]['document_references'] = [
            {'reference': 'docs/X.md', 'kind': None, 'outcome': 'index_unavailable',
             'path': None, 'note': 'listing unavailable'}]
        m = sm.build(s)
        node = [n for n in m['nodes'] if n['type'] == 'document'][0]
        self.assertEqual(node['outcome'], 'index_unavailable')
        self.assertTrue(any(u['what'] == 'governed_by_index_unavailable' for u in m['unresolved']))

    def test_no_governed_by_edge_without_a_declared_reference(self):
        s = snapshot()
        s['entities'][0]['declared_governed_by'] = []
        s['entities'][0]['document_references'] = []
        m = sm.build(s)
        self.assertEqual(self._edges(m, 'governed_by'), [])


class UnknownIsExplicit(unittest.TestCase):
    def test_unresolved_entrypoint_is_recorded_with_a_reason(self):
        s = snapshot()
        s['entities'][0]['installed_paths'][0]['entrypoint'] = {
            'executable': '/bin/bash', 'target_kind': None, 'target': None,
            'target_exists': None, 'argument_count': 3, 'arguments_omitted': True,
            'unknown_reason': '`-c` inline command form'}
        m = sm.build(s)
        self.assertTrue(any(u['what'] == 'entrypoint' and u['reason'] for u in m['unresolved']))
        self.assertEqual([e for e in m['edges'] if e['type'] == 'declares_entrypoint'], [])

    def test_unresolved_wrapper_target_is_recorded_when_no_static_declaration(self):
        s = snapshot()
        s['entities'][0]['installed_paths'][0]['entrypoint_declared_target'] = None
        m = sm.build(s)
        self.assertTrue(any(u['what'] == 'wrapper_target' for u in m['unresolved']))

    def test_missing_checkout_is_unresolved_not_invented(self):
        s = snapshot()
        s['entities'][0]['installed_paths'][0]['entrypoint_checkout'] = None
        m = sm.build(s)
        self.assertTrue(any(u['what'] == 'checkout' for u in m['unresolved']))
        self.assertEqual([e for e in m['edges'] if e['type'] == 'resides_in'], [])


class EntrypointShape(unittest.TestCase):
    def test_missing_script_is_recorded_as_unresolved_not_dropped_silently(self):
        s = snapshot()
        ep = s['entities'][0]['installed_paths'][0]['entrypoint']
        ep.update(target='/gone/agent.sh', target_exists=False)
        s['entities'][0]['installed_paths'][0]['entrypoint_checkout'] = None
        s['entities'][0]['installed_paths'][0]['entrypoint_declared_target'] = None
        m = sm.build(s)
        whats = {u['what'] for u in m['unresolved']}
        self.assertIn('entrypoint_script_missing', whats)
        self.assertIn('checkout', whats)
        self.assertNotIn('wrapper_target', whats)  # a missing script has no target to declare

    def test_module_entrypoint_is_not_treated_as_a_path(self):
        s = snapshot()
        s['entities'][0]['installed_paths'][0]['entrypoint'] = {
            'executable': '/usr/bin/python3', 'target_kind': 'module',
            'target': 'spa_core.monitoring.x', 'target_exists': None,
            'argument_count': 3, 'arguments_omitted': True, 'unknown_reason': None}
        s['entities'][0]['installed_paths'][0]['entrypoint_checkout'] = None
        m = sm.build(s)
        keys = [n['key'] for n in m['nodes'] if n['type'] == 'entrypoint']
        self.assertIn('module:spa_core.monitoring.x', keys)
        self.assertEqual([e for e in m['edges'] if e['type'] == 'resides_in'], [])


class Overview(unittest.TestCase):
    def test_mermaid_groups_instead_of_drawing_every_job(self):
        s = snapshot()
        s['entities'] = [dict(s['entities'][0], id=f'com.spa.j{i}') for i in range(60)]
        m = sm.build(s)
        text = sm.mermaid(m, s)
        drawn = text.count('["')
        self.assertLess(drawn, 20, 'overview must stay readable, not draw 60 jobs')
        self.assertIn('```mermaid', text)
        self.assertIn('does NOT claim', text)

    def test_overview_states_the_unresolved_count(self):
        m = sm.build(snapshot())
        self.assertIn('Unresolved claims:', sm.mermaid(m, snapshot()))

    def test_map_never_carries_argv_or_secrets(self):
        s = snapshot()
        s['entities'][0]['installed_paths'][0]['entrypoint']['argument_count'] = 4
        m = sm.build(s)
        blob = json.dumps(m, ensure_ascii=False) + sm.mermaid(m, s)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn('arguments', {k for n in m['nodes'] for k in n} - {'argument_count', 'arguments_omitted'})


if __name__ == '__main__':
    unittest.main()
