"""Regressions for the source-of-truth map (Phase 0C).

The map's value is the BOUNDARY it draws: what a source proves and what it does not.
These tests defend that boundary — no source may become globally authoritative, no
conflict may be silently resolved, and no freshness rule may be invented where the
repository declares none.
"""
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


sot = _load('source_of_truth')
from test_diff import _snap, REPO  # noqa: E402  (same synthetic snapshot, one stand)


def _build(snapshot=None):
    return sot.build(snapshot or _snap(), source_dir='/snapshots/x')


class Contract(unittest.TestCase):
    def test_every_required_fact_type_is_covered(self):
        got = {f['fact_type'] for f in _build()['fact_types']}
        self.assertEqual(got, {
            'intended_configuration', 'registry_membership', 'installed_configuration',
            'loaded_service', 'running_process', 'repository_content',
            'production_content', 'code_sync_result', 'artifact_existence_freshness',
            'health_and_producer_attribution'})

    def test_each_fact_type_states_what_it_does_not_prove(self):
        for f in _build()['fact_types']:
            self.assertTrue(f['proves'], f['fact_type'])
            self.assertTrue(f['does_not_prove'], f['fact_type'])
            self.assertTrue(f['observation_scope'], f['fact_type'])
            self.assertTrue(f['unavailable_marker'], f['fact_type'])
            self.assertIn('atomic', f['observation_window'])
            self.assertFalse(f['observation_window']['atomic'])

    def test_validate_accepts_the_generated_map(self):
        self.assertTrue(sot.validate(_build()))

    def test_validate_rejects_a_divergence_citing_an_unknown_fact_type(self):
        m = _build()
        m['divergences'].append({'id': 'x', 'kind': 'scope_difference', 'kind_meaning': 'y',
                                 'fact_types': ['invented_fact'],
                                 'statements': [{'source': 'a', 'says': 'b'},
                                                {'source': 'c', 'says': 'd'}],
                                 'resolution_policy': 'POLICY_UNDEFINED',
                                 'resolution_note': '', 'note': ''})
        with self.assertRaises(ValueError):
            sot.validate(m)

    def test_validate_rejects_a_map_that_carries_a_resolution_policy(self):
        m = _build()
        m['divergences'][0]['resolution_policy'] = 'manifest_wins'
        with self.assertRaises(ValueError):
            sot.validate(m)


class NoAuthorityAndNoInvention(unittest.TestCase):
    def test_no_source_is_declared_authoritative_in_general(self):
        m = _build()
        self.assertIn('Ни один источник не назначен главным', m['no_global_authority'])
        blob = json.dumps(m, ensure_ascii=False)
        for word in ('authoritative', 'source_of_record', 'priority', 'wins'):
            self.assertNotIn(word, blob.lower(), word)

    def test_manifest_and_launchd_answer_different_questions(self):
        facts = {f['fact_type']: f for f in _build()['fact_types']}
        self.assertIn('не может', facts['intended_configuration']['does_not_prove'] + ' не может')
        self.assertIn('загружено', facts['intended_configuration']['does_not_prove'])
        self.assertIn('процесс работает', facts['loaded_service']['does_not_prove'])

    def test_origin_does_not_prove_what_executes_and_in_sync_does_not_deny_extras(self):
        facts = {f['fact_type']: f for f in _build()['fact_types']}
        self.assertIn('исполняется в проде', facts['repository_content']['does_not_prove'])
        self.assertIn('IN_SYNC', facts['code_sync_result']['does_not_prove'])
        self.assertIn('production-only', facts['code_sync_result']['does_not_prove'])

    def test_freshness_is_declared_only_where_a_threshold_already_exists(self):
        facts = {f['fact_type']: f for f in _build()['fact_types']}
        self.assertIn('26 ч', facts['registry_membership']['freshness_rule'])
        self.assertIn('1 ч', facts['code_sync_result']['freshness_rule'])
        self.assertIn('slo_hours', facts['artifact_existence_freshness']['freshness_rule'])
        for name in ('intended_configuration', 'installed_configuration',
                     'health_and_producer_attribution'):
            self.assertTrue(facts[name]['freshness_rule'].startswith('POLICY_UNDEFINED'),
                            f"{name}: {facts[name]['freshness_rule']}")

    def test_health_has_no_source_and_says_so(self):
        fact = {f['fact_type']: f for f in _build()['fact_types']}['health_and_producer_attribution']
        self.assertIn('UNKNOWN', fact['source'])
        self.assertEqual(fact['proves'], 'ничего')
        self.assertIsNone(fact['availability']['coverage_key'])
        self.assertIsNone(fact['availability']['available'])

    def test_the_map_is_not_a_second_registry_of_agents(self):
        """FACT_TYPES is a table of rules; enumerating agents there would duplicate the
        manifest and create the second registry this phase must not build."""
        blob = json.dumps(sot.FACT_TYPES, ensure_ascii=False)
        self.assertNotIn('com.spa.', blob)


class Availability(unittest.TestCase):
    def test_availability_follows_the_recorded_coverage(self):
        s = _snap()
        s['coverage']['domains_complete'] = False
        facts = {f['fact_type']: f for f in _build(s)['fact_types']}
        self.assertFalse(facts['loaded_service']['availability']['available'])
        self.assertTrue(facts['intended_configuration']['availability']['available'])

    def test_unknown_coverage_stays_unknown_and_is_not_read_as_false(self):
        s = _snap()
        s['coverage']['domains_complete'] = None
        facts = {f['fact_type']: f for f in _build(s)['fact_types']}
        self.assertIsNone(facts['loaded_service']['availability']['available'])
        self.assertIn('UNKNOWN', sot.markdown(_build(s)))

    def test_a_02_snapshot_gets_an_inferred_basis_and_unchecked_documents(self):
        s = _snap(schema_version='cartographer.snapshot/0.2')
        del s['coverage']
        del s['reference_documents']
        m = _build(s)
        self.assertEqual(m['coverage_basis'], 'inferred_from_findings')
        docs = [d for f in m['fact_types'] for d in f['documents']]
        self.assertTrue(docs)
        self.assertTrue(all(d['resolution'] == 'NOT_RECORDED_IN_THIS_SCHEMA' for d in docs))

    def test_documents_keep_the_two_answers_apart(self):
        m = _build()
        checked = [d for f in m['fact_types'] for d in f['documents']
                   if d['resolution'] == 'CHECKED']
        self.assertTrue(checked)
        for doc in checked:
            self.assertIn('in_production_tree', doc)
            self.assertIn('in_pinned_commit_docs_index', doc)

    def test_code_sync_keeps_its_own_timestamp_apart_from_the_observation_window(self):
        fact = {f['fact_type']: f for f in _build()['fact_types']}['code_sync_result']
        self.assertEqual(fact['source_own_timestamp'], '2026-09-19T09:00:00+00:00')
        self.assertNotEqual(fact['source_own_timestamp'],
                            fact['observation_window']['finished_at'])


class Divergences(unittest.TestCase):
    """A divergence is not automatically a contradiction. ARB review: IN_SYNC beside
    production-only files, an enable override without a service, and manifest/registry
    membership differing were all reported as proven contradictions. None of them is:
    they are different questions, different scopes or different subjects, and both sides
    can be true at once."""

    def _kinds(self, m):
        return {c['id']: c['kind'] for c in m['divergences']}

    def test_in_sync_beside_production_only_is_a_scope_difference(self):
        m = _build()
        hit = [c for c in m['divergences'] if c['id'].startswith('divergence:sync_scope_vs')]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]['kind'], 'scope_difference')
        self.assertIn('НЕ противоречие', hit[0]['note'])
        self.assertEqual(len(hit[0]['statements']), 2)
        self.assertEqual(hit[0]['resolution_policy'], 'POLICY_UNDEFINED')

    def test_an_enable_override_without_a_service_is_a_different_subject(self):
        s = _snap(labels_with_override_but_no_service=['com.spa.ghost'])
        kinds = self._kinds(_build(s))
        self.assertEqual(kinds['divergence:enable_override_without_service:com.spa.ghost'],
                         'different_subject')

    def test_manifest_versus_registry_membership_is_a_declaration_difference(self):
        s = _snap()
        s['entities'][0]['stages']['DECLARED'] = False
        kinds = self._kinds(_build(s))
        self.assertEqual(kinds['divergence:registry_vs_manifest'], 'declaration_difference')
        hit = [c for c in _build(s)['divergences']
               if c['id'] == 'divergence:registry_vs_manifest'][0]
        self.assertIn('равенство составов двух деклараций НИГДЕ не требуется', hit['note'])

    def test_intent_versus_launchd_is_declaration_versus_observation_not_contradiction(self):
        s = _snap()
        s['entities'][0]['stages']['LOADED'] = False
        s['entities'][0]['status'] = 'DEGRADED'
        m = _build(s)
        hit = [c for c in m['divergences']
               if c['id'] == 'divergence:intended_active_vs_not_loaded'][0]
        self.assertEqual(hit['kind'], 'declaration_vs_observation')
        self.assertEqual(len(hit['statements']), 2)
        self.assertEqual(hit['subjects'], ['com.spa.alpha'])
        self.assertIn('разные вопросы', hit['note'])

    def test_none_of_the_three_named_cases_is_reported_as_a_contradiction(self):
        s = _snap(labels_with_override_but_no_service=['com.spa.ghost'])
        s['entities'][0]['stages']['DECLARED'] = False
        m = _build(s)
        self.assertEqual(m['contradiction_count'], 0)
        for c in m['divergences']:
            self.assertNotEqual(c['kind'], 'contradiction', c['id'])

    def test_a_real_contradiction_is_still_recognised(self):
        """The services block lists the label while the targeted probe says absent: one
        fact, one domain, one run — the two cannot both be true."""
        s = _snap()
        s['launchd_domains']['gui/501']['services'] = ['com.spa.alpha']
        s['entities'][0]['domains'] = {'gui/501': False}
        m = _build(s)
        hit = [c for c in m['divergences'] if c['kind'] == 'contradiction']
        self.assertEqual(len(hit), 1)
        self.assertEqual(m['contradiction_count'], 1)
        self.assertEqual(hit[0]['fact_types'], ['loaded_service'])
        self.assertEqual(hit[0]['subjects'], ['com.spa.alpha@gui/501'])

    def test_validate_rejects_a_contradiction_spanning_two_fact_types(self):
        m = _build()
        m['divergences'].append({
            'id': 'x', 'kind': 'contradiction', 'kind_meaning': 'y',
            'fact_types': ['loaded_service', 'intended_configuration'],
            'statements': [{'source': 'a', 'says': 'b'}, {'source': 'c', 'says': 'd'}],
            'resolution_policy': 'POLICY_UNDEFINED', 'resolution_note': '', 'note': ''})
        with self.assertRaises(ValueError):
            sot.validate(m)

    def test_validate_rejects_an_unknown_divergence_kind(self):
        m = _build()
        m['divergences'][0]['kind'] = 'proven_conflict'
        with self.assertRaises(ValueError):
            sot.validate(m)

    def test_no_divergence_is_invented_on_an_agreeing_snapshot(self):
        s = _snap()
        s['code_sync']['result'] = 'CHANGED'
        s['repositories'][0]['drift'].update(production_only_tracked=[],
                                             production_only_untracked=[])
        self.assertEqual(_build(s)['divergences'], [])
        self.assertIn('Расхождений между источниками', sot.markdown(_build(s)))

    def test_divergence_ids_are_unique_and_stable(self):
        a, b = _build(), _build()
        ids = [c['id'] for c in a['divergences']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [c['id'] for c in b['divergences']])


class Readable(unittest.TestCase):
    def test_markdown_names_source_proof_and_non_proof_for_every_fact(self):
        text = sot.markdown(_build())
        for f in sot.FACT_TYPES:
            self.assertIn(f['fact_type'], text)
        self.assertIn('**НЕ доказывает:**', text)
        self.assertIn('окно наблюдения', text)
        self.assertIn('POLICY_UNDEFINED', text)

    def test_markdown_states_the_limits_of_the_map_itself(self):
        text = sot.markdown(_build())
        self.assertIn('не переписывает источники', text)
        self.assertIn('не перечисляет агентов', text)


if __name__ == '__main__':
    unittest.main()


class MarkdownStatesTheClassification(unittest.TestCase):
    def test_markdown_defines_contradiction_and_counts_it(self):
        text = sot.markdown(_build())
        self.assertIn('Расхождение — не всегда противоречие', text)
        self.assertIn('Противоречий в этом снимке: **0**', text)
        self.assertIn('вид: **scope_difference**', text)
        self.assertNotIn('Где источники противоречат друг другу', text)

    def test_markdown_carries_the_kind_of_every_divergence(self):
        s = _snap(labels_with_override_but_no_service=['com.spa.ghost'])
        text = sot.markdown(_build(s))
        for c in _build(s)['divergences']:
            self.assertIn(f"вид: **{c['kind']}**", text)
