"""Свойства, которые должны держаться на ЛЮБЫХ данных, и попытки их сломать.

Каждый класс — одно утверждение вида «X не равно Y», где смешение X и Y уже
случалось в этой системе.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import capital_truth as CT         # noqa: E402
import owner_facts as F            # noqa: E402
import service_health as SH        # noqa: E402
import build_stages as BS          # noqa: E402
import bridge_evidence as BE       # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


class MissingIsNotZero(unittest.TestCase):
    def test_missing_position_amount_does_not_become_zero_in_the_total(self):
        # Подозреваемый №1 из разбора молчаливых выводов.
        positions = {'capital_usd': 100.0, 'deployed_usd': 100.0,
                     'generated_at': '2026-09-21T11:00:00+00:00',
                     'execution_mode': 'read_only_simulation',
                     'positions_detail': {'a': {'usd': 60.0}, 'b': {}}}
        facts = CT.capital_totals(positions, currency=None, currency_basis=None, now=NOW)
        dep = next(f for f in facts if f['metric'] == 'deployed_usd')
        self.assertEqual(dep['value'], 100.0)          # объявленное не подменено
        self.assertEqual(dep['verification_state'], 'UNVERIFIED')
        self.assertIn('ноль', dep['note'])

    def test_declared_total_is_preferred_over_the_sum(self):
        positions = {'capital_usd': 100.0, 'deployed_usd': 95.0, 'cash_usd': 5.0,
                     'generated_at': '2026-09-21T11:00:00+00:00',
                     'positions_detail': {'a': {'usd': 95.0}}}
        facts = {f['metric']: f for f in CT.capital_totals(
            positions, currency=None, currency_basis=None, now=NOW)}
        self.assertEqual(facts['deployed_usd']['fact_kind'], 'OBSERVED')
        self.assertEqual(facts['deployed_usd']['verification_state'], 'VERIFIED')

    def test_disagreement_surfaces_instead_of_overwriting(self):
        positions = {'capital_usd': 100.0, 'deployed_usd': 95.0,
                     'generated_at': '2026-09-21T11:00:00+00:00',
                     'positions_detail': {'a': {'usd': 70.0}}}
        facts = {f['metric']: f for f in CT.capital_totals(
            positions, currency=None, currency_basis=None, now=NOW)}
        dep = facts['deployed_usd']
        self.assertEqual(dep['value'], 95.0)
        self.assertEqual(dep['verification_state'], 'CONFLICT')
        self.assertEqual(dep['conflicts'][0]['other_value'], 70.0)


class MissingBooleanIsNotFalse(unittest.TestCase):
    def test_policy_compliant_null_is_not_non_compliance(self):
        positions = {'policy_compliant': None, 'capital_usd': 100.0,
                     'generated_at': '2026-09-21T11:00:00+00:00', 'positions': {}}
        pol = CT.policy_compliance(positions, {}, now=NOW)
        self.assertIsNone(pol['declared_compliant'])

    def test_null_policy_raises_no_owner_alarm(self):
        positions = {'policy_compliant': None, 'capital_usd': 100.0,
                     'generated_at': '2026-09-21T11:00:00+00:00', 'positions': {}}
        pol = CT.policy_compliance(positions, {}, now=NOW)
        att = CT.attention_items(red_flags=None, positions=positions, alloc=None,
                                 policy=pol, now=NOW)
        self.assertEqual(att['portfolio_attention_count'], 0)

    def test_false_policy_does_raise_the_alarm(self):
        positions = {'policy_compliant': False, 'capital_usd': 100.0,
                     'generated_at': '2026-09-21T11:00:00+00:00', 'positions': {}}
        pol = CT.policy_compliance(positions, {}, now=NOW)
        att = CT.attention_items(red_flags=None, positions=positions, alloc=None,
                                 policy=pol, now=NOW)
        self.assertEqual(att['portfolio_attention_count'], 1)
        self.assertEqual(att['portfolio_attention'][0]['owner_relevance'],
                         'DECISION_REQUIRED')


class UnknownModeIsNotPaper(unittest.TestCase):
    def test_unrecognised_execution_mode_is_unknown(self):
        self.assertEqual(CT._mode_of({'execution_mode': 'что-то новое'}), 'UNKNOWN')

    def test_is_demo_false_does_not_make_it_real(self):
        self.assertEqual(CT._mode_of({'is_demo': False}), 'UNKNOWN')

    def test_declared_simulation_is_paper(self):
        self.assertEqual(CT._mode_of({'execution_mode': 'read_only_simulation'}), 'PAPER')


class TargetIsNotObserved(unittest.TestCase):
    def test_shadow_allocation_is_marked_as_proposal(self):
        alloc = {'mode': 'SHADOW', 'generated_at': '2026-09-21T11:00:00+00:00',
                 'decision_shadow': {'decision': 'HOLD', 'legs': [
                     {'protocol': 'a', 'delta_usd': 10.0, 'direction': 'increase'}]}}
        t = CT.target_allocation(alloc, now=NOW)
        self.assertEqual(t['observation_kind'], 'SHADOW_PROPOSED')
        self.assertTrue(t['is_advisory'])

    def test_unrecognised_mode_is_not_silently_called_shadow(self):
        alloc = {'mode': 'СОВСЕМ_ДРУГОЕ', 'decision_shadow': {}}
        self.assertEqual(CT.target_allocation(alloc, now=NOW)['mode'], 'UNKNOWN')


class UnrelatedAlertIsNotPortfolioAlert(unittest.TestCase):
    def _flags(self, protocol):
        return {'generated_at': '2026-09-21T11:30:00+00:00', 'monitor_version': '1.0',
                'red_flags': [{'protocol': protocol, 'severity': 'CRITICAL',
                               'category': 'apy_spike', 'message': 'всплеск',
                               'source': 'historical_apy', 'evidence': {'grade': '?'}}]}

    def test_held_protocol_reaches_portfolio_attention(self):
        positions = {'positions_detail': {'aave_v3': {'usd': 1.0}}}
        att = CT.attention_items(red_flags=self._flags('aave_v3'), positions=positions,
                                 alloc=None, policy=None, now=NOW)
        self.assertEqual(att['portfolio_attention_count'], 1)

    def test_unheld_protocol_does_not(self):
        positions = {'positions_detail': {'aave_v3': {'usd': 1.0}}}
        att = CT.attention_items(red_flags=self._flags('чужой-протокол'),
                                 positions=positions, alloc=None, policy=None, now=NOW)
        self.assertEqual(att['portfolio_attention_count'], 0)
        self.assertEqual(len(att['not_relevant']), 1)

    def test_blocked_candidate_goes_to_the_watchlist(self):
        positions = {'positions_detail': {'aave_v3': {'usd': 1.0}},
                     'feed_coverage': {'blocked': {'susde': 'advisory'}}}
        att = CT.attention_items(red_flags=self._flags('ethena-susde'),
                                 positions=positions, alloc=None, policy=None, now=NOW)
        self.assertEqual(att['portfolio_attention_count'], 0)
        self.assertEqual(len(att['watchlist_rnd']), 1)
        self.assertEqual(att['watchlist_rnd'][0]['portfolio_link'], 'BLOCKED_CANDIDATE')

    def test_short_names_do_not_match_everything(self):
        positions = {'positions_detail': {'a': {'usd': 1.0}}}
        att = CT.attention_items(red_flags=self._flags('совершенно-другое'),
                                 positions=positions, alloc=None, policy=None, now=NOW)
        self.assertEqual(len(att['not_relevant']), 1)


class ScheduledNotRunningIsNotBroken(unittest.TestCase):
    def _manifest(self, label, **kw):
        return {'agents': [{'label': label, **kw}]}

    def test_scheduled_job_without_a_process_is_not_applicable(self):
        m = SH.build_service_health(
            manifest=self._manifest('com.spa.x'), registry={'agents': []},
            launchctl={'com.spa.x': {'pid': None, 'has_pid': False, 'last_exit': 0}},
            plists={'com.spa.x': {'schedule_class': 'SCHEDULED'}}, now=NOW)
        self.assertEqual(m['entities'][0]['stages']['RUNNING'], SH.NOT_APPLICABLE)
        self.assertEqual(m['counts']['running_false'], 0)

    def test_daemon_without_a_process_is_a_problem(self):
        m = SH.build_service_health(
            manifest=self._manifest('com.spa.x'), registry={'agents': []},
            launchctl={'com.spa.x': {'pid': None, 'has_pid': False, 'last_exit': 0}},
            plists={'com.spa.x': {'schedule_class': 'DAEMON'}}, now=NOW)
        self.assertIs(m['entities'][0]['stages']['RUNNING'], False)
        self.assertEqual(m['problems'][0]['problem'], 'DAEMON_NOT_RUNNING')

    def test_label_absent_from_the_listing_is_not_measured(self):
        m = SH.build_service_health(
            manifest=self._manifest('com.spa.x'), registry={'agents': []},
            launchctl={}, plists={'com.spa.x': {'schedule_class': 'DAEMON'}}, now=NOW)
        self.assertIsNone(m['entities'][0]['stages']['RUNNING'])

    def test_unknown_schedule_is_not_judged_as_a_daemon(self):
        m = SH.build_service_health(
            manifest=self._manifest('com.spa.x'), registry={'agents': []},
            launchctl={'com.spa.x': {'pid': None, 'has_pid': False, 'last_exit': 0}},
            plists={}, now=NOW)
        self.assertIsNone(m['entities'][0]['stages']['RUNNING'])

    def test_registry_not_supplied_is_not_unregistered(self):
        m = SH.build_service_health(manifest=self._manifest('com.spa.x'), registry=None,
                                    launchctl={}, plists={}, now=NOW)
        self.assertIsNone(m['entities'][0]['stages']['REGISTERED'])


class LiveIsNotHealthy(unittest.TestCase):
    def test_health_is_never_inferred_from_a_fresh_file(self):
        m = SH.build_service_health(
            manifest={'agents': [{'label': 'com.spa.x', 'produces': [
                {'artifact': 'data/x.json', 'slo_hours': 24}]}]},
            registry={'agents': []},
            launchctl={'com.spa.x': {'pid': 1, 'has_pid': True, 'last_exit': 0}},
            plists={'com.spa.x': {'schedule_class': 'DAEMON'}},
            production_root='.', now=NOW,
            stat_fn=lambda p: type('S', (), {'st_mtime': NOW.timestamp()})())
        ent = m['entities'][0]
        self.assertIs(ent['stages']['PRODUCING_OUTPUT'], True)
        self.assertIsNone(ent['stages']['HEALTHY'])
        self.assertFalse(m['health_contract_exists'])

    def test_artifact_without_a_declared_slo_gives_no_answer(self):
        m = SH.build_service_health(
            manifest={'agents': [{'label': 'com.spa.x',
                                  'produces': [{'artifact': 'data/x.json'}]}]},
            registry={'agents': []}, launchctl={}, plists={}, production_root='.',
            now=NOW, stat_fn=lambda p: type('S', (), {'st_mtime': NOW.timestamp()})())
        self.assertIsNone(m['entities'][0]['stages']['PRODUCING_OUTPUT'])


class KindIsNeverGuessed(unittest.TestCase):
    def test_agent_is_never_produced_without_a_declaration(self):
        for schedule in SH.SCHEDULE_CLASSES:
            kind, basis, _ = SH.entity_kind(role=None, schedule_class=schedule)
            self.assertNotEqual(kind, 'AGENT',
                                'ни одно поле не объявляет сущность агентом')

    def test_declared_kind_wins_and_is_marked_proven(self):
        kind, basis, _ = SH.entity_kind(role=None, schedule_class='UNKNOWN',
                                        declared_kind='CONNECTOR')
        self.assertEqual((kind, basis), ('CONNECTOR', 'PROVEN'))

    def test_no_evidence_gives_unknown_not_a_guess(self):
        kind, basis, _ = SH.entity_kind(role=None, schedule_class='UNKNOWN')
        self.assertEqual((kind, basis), ('UNKNOWN', 'NOT_DERIVABLE'))


class UnreadCarrierIsNotEmpty(unittest.TestCase):
    def test_unread_cards_give_unknown_not_not_found(self):
        p = BS.build_pipeline(cards=None, bridge=None, now=NOW)
        stages = {s['stage']: s for s in p['stages']}
        self.assertEqual(stages['INTAKE']['status'], 'UNKNOWN')
        self.assertIsNone(stages['INTAKE']['evidence_count'])

    def test_empty_cards_give_not_found(self):
        p = BS.build_pipeline(cards=[], bridge={}, now=NOW)
        stages = {s['stage']: s for s in p['stages']}
        self.assertEqual(stages['INTAKE']['status'], 'NOT_FOUND')


class CommitVerificationHonesty(unittest.TestCase):
    def test_no_repositories_is_not_measured_not_not_found(self):
        r = BE.verify_commit('deadbeef', [])
        self.assertEqual(r['state'], 'NOT_MEASURED')

    def test_missing_commit_names_where_it_looked(self):
        r = BE.verify_commit('0' * 40, [str(ROOT)])
        self.assertEqual(r['state'], 'NOT_FOUND')
        self.assertIn('repositories_checked', r)


class DocumentedIsNotLive(unittest.TestCase):
    def test_documents_alone_never_make_a_stage_live(self):
        p = BS.build_pipeline(cards=[], bridge={}, service_health={'entities': []},
                              now=NOW, production_root=str(ROOT))
        arch = next(s for s in p['stages'] if s['stage'] == 'ARCHITECT_REVIEW')
        self.assertIn(arch['status'], ('DOCUMENTED_ONLY', 'NOT_FOUND'))
        self.assertNotEqual(arch['status'], 'LIVE')

    def test_name_match_alone_is_rejected_and_recorded(self):
        health = {'entities': [{'label': 'com.spa.architecture_conformance',
                                'role_declared': 'monitoring',
                                'declared_output_count': 1,
                                'stages': {'PRODUCING_OUTPUT': True},
                                'declared_outputs': [{'artifact': 'x', 'age_hours': 1.0}]}]}
        p = BS.build_pipeline(cards=[], bridge={}, service_health=health, now=NOW,
                              production_root=str(ROOT))
        arch = next(s for s in p['stages'] if s['stage'] == 'ARCHITECT_REVIEW')
        self.assertNotEqual(arch['status'], 'LIVE')
        self.assertEqual(len(arch['detail']['rejected_name_matches']), 1)


class ProvenOnceIsNotLiveNow(unittest.TestCase):
    def test_old_evidence_downgrades_live_to_partial(self):
        old = NOW.timestamp() - 60 * 86400
        bridge = {'tasks': [{'created_at': old, 'turns_by_kind': {
            'implement': {'total': 1, 'done': 1}}, 'apply_manifests': 0}]}
        p = BS.build_pipeline(cards=[], bridge=bridge, now=NOW)
        stage = next(s for s in p['stages'] if s['stage'] == 'CLAUDE_EXECUTION')
        self.assertEqual(stage['status'], 'PARTIAL')
        self.assertIn('старше', stage['verdict_reason'])


if __name__ == '__main__':
    unittest.main()
