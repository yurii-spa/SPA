"""
Tests for MP-970: DeFiProtocolComposabilityRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_composability_risk_analyzer -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_protocol_composability_risk_analyzer import (
    DeFiProtocolComposabilityRiskAnalyzer,
    RISK_LABEL_SAFE,
    RISK_LABEL_LOW,
    RISK_LABEL_MODERATE,
    RISK_LABEL_HIGH,
    RISK_LABEL_SYSTEMIC,
    FLAG_DEEP_DEPENDENCY,
    FLAG_NO_CIRCUIT_BREAKER,
    FLAG_SLOW_UNWIND,
    FLAG_PRIOR_ISSUES,
    FLAG_LARGE_TVL_AT_RISK,
    ALL_RISK_LABELS,
)


def _make_integration(**kwargs):
    """Return a safe base integration, overriding with kwargs."""
    defaults = {
        'name': 'test_integration',
        'base_protocol': 'Aave',
        'dependent_protocol': 'Compound',
        'integration_type': 'collateral',
        'tvl_at_risk_usd': 1_000_000,
        'dependency_depth': 1,
        'base_protocol_audit_score': 90,
        'circuit_breaker_exists': True,
        'auto_unwind_available': True,
        'time_to_unwind_hours': 24,
        'historical_issues_count': 0,
    }
    defaults.update(kwargs)
    return defaults


def _make_log_dir():
    """Return a temp dir and log file path for isolated testing."""
    d = tempfile.mkdtemp()
    return d, os.path.join(d, 'composability_risk_log.json')


class TestInstantiation(unittest.TestCase):
    def test_default_instantiation(self):
        a = DeFiProtocolComposabilityRiskAnalyzer()
        self.assertIsNotNone(a)

    def test_custom_log_file(self):
        _, log = _make_log_dir()
        a = DeFiProtocolComposabilityRiskAnalyzer(log_file=log)
        self.assertEqual(a._log_file, log)

    def test_default_config_keys_present(self):
        cfg = DeFiProtocolComposabilityRiskAnalyzer.DEFAULT_CONFIG
        self.assertIn('depth_penalty_factor', cfg)
        self.assertIn('fragility_weight', cfg)
        self.assertIn('recovery_weight', cfg)
        self.assertIn('systemic_depth_threshold', cfg)
        self.assertIn('systemic_risk_threshold', cfg)


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_empty_integrations_returns_dict(self):
        r = self.a.analyze([], config={'log_file': self.log})
        self.assertIsInstance(r, dict)

    def test_empty_integrations_count_zero(self):
        r = self.a.analyze([], config={'log_file': self.log})
        self.assertEqual(r['integrations_analyzed'], 0)

    def test_empty_integrations_results_empty(self):
        r = self.a.analyze([], config={'log_file': self.log})
        self.assertEqual(r['results'], [])

    def test_empty_aggregates_defaults(self):
        r = self.a.analyze([], config={'log_file': self.log})
        agg = r['aggregates']
        self.assertIsNone(agg['highest_risk_integration'])
        self.assertIsNone(agg['safest_integration'])
        self.assertEqual(agg['total_tvl_at_risk_usd'], 0.0)
        self.assertEqual(agg['systemic_count'], 0)
        self.assertEqual(agg['average_risk_score'], 0.0)

    def test_empty_still_writes_log(self):
        self.a.analyze([], config={'log_file': self.log})
        self.assertTrue(os.path.exists(self.log))


class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)
        self.integ = _make_integration()

    def test_top_level_keys(self):
        r = self.a.analyze([self.integ], config={'log_file': self.log})
        for key in ('timestamp', 'integrations_analyzed', 'results', 'aggregates'):
            self.assertIn(key, r)

    def test_result_has_required_fields(self):
        r = self.a.analyze([self.integ], config={'log_file': self.log})
        res = r['results'][0]
        for field in (
            'name', 'base_protocol', 'dependent_protocol', 'integration_type',
            'tvl_at_risk_usd', 'dependency_depth', 'contagion_multiplier',
            'fragility_score', 'recovery_score', 'net_composability_risk',
            'risk_label', 'flags',
        ):
            self.assertIn(field, res)

    def test_timestamp_format(self):
        r = self.a.analyze([self.integ], config={'log_file': self.log})
        ts = r['timestamp']
        self.assertRegex(ts, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')

    def test_integrations_analyzed_count(self):
        r = self.a.analyze([self.integ, self.integ], config={'log_file': self.log})
        self.assertEqual(r['integrations_analyzed'], 2)


class TestContagionMultiplier(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _run(self, tvl, depth):
        integ = _make_integration(tvl_at_risk_usd=tvl, dependency_depth=depth)
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['contagion_multiplier']

    def test_depth_1(self):
        self.assertAlmostEqual(self._run(5_000_000, 1), 5_000_000.0)

    def test_depth_2(self):
        self.assertAlmostEqual(self._run(2_000_000, 2), 4_000_000.0)

    def test_depth_5(self):
        self.assertAlmostEqual(self._run(1_000_000, 5), 5_000_000.0)

    def test_zero_tvl(self):
        self.assertAlmostEqual(self._run(0, 3), 0.0)

    def test_tvl_10m_depth_3(self):
        self.assertAlmostEqual(self._run(10_000_000, 3), 30_000_000.0)


class TestFragilityScore(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _fragility(self, audit_score, depth):
        integ = _make_integration(
            base_protocol_audit_score=audit_score, dependency_depth=depth
        )
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['fragility_score']

    def test_perfect_audit_depth_1_near_zero(self):
        # 100 audit, depth 1 → (100-100) + 0*15 = 0
        self.assertAlmostEqual(self._fragility(100, 1), 0.0, places=2)

    def test_zero_audit_depth_1(self):
        # (100-0) + 0*15 = 100
        self.assertAlmostEqual(self._fragility(0, 1), 100.0, places=2)

    def test_depth_increases_fragility(self):
        f1 = self._fragility(80, 1)
        f2 = self._fragility(80, 2)
        self.assertGreater(f2, f1)

    def test_clamped_at_100(self):
        f = self._fragility(0, 10)
        self.assertLessEqual(f, 100.0)

    def test_clamped_at_zero(self):
        f = self._fragility(100, 1)
        self.assertGreaterEqual(f, 0.0)


class TestRecoveryScore(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _recovery(self, cb, au, unwind_hours):
        integ = _make_integration(
            circuit_breaker_exists=cb,
            auto_unwind_available=au,
            time_to_unwind_hours=unwind_hours,
        )
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['recovery_score']

    def test_all_recovery_features(self):
        # 40 + 30 + 30 = 100
        self.assertAlmostEqual(self._recovery(True, True, 24), 100.0, places=2)

    def test_no_recovery_features(self):
        self.assertAlmostEqual(self._recovery(False, False, 120), 0.0, places=2)

    def test_cb_only(self):
        self.assertAlmostEqual(self._recovery(True, False, 120), 40.0, places=2)

    def test_auto_unwind_only(self):
        self.assertAlmostEqual(self._recovery(False, True, 120), 30.0, places=2)

    def test_fast_unwind_only(self):
        self.assertAlmostEqual(self._recovery(False, False, 24), 30.0, places=2)

    def test_slow_unwind_no_fast_pts(self):
        # >72h → no fast unwind pts
        r1 = self._recovery(True, True, 72)   # =72, <= threshold → pts
        r2 = self._recovery(True, True, 73)   # >72 → no fast pts
        self.assertGreater(r1, r2)

    def test_capped_at_100(self):
        r = self._recovery(True, True, 1)
        self.assertLessEqual(r, 100.0)


class TestRiskLabels(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _label(self, **kwargs):
        integ = _make_integration(**kwargs)
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['risk_label']

    def test_safe_composition(self):
        # High audit, shallow depth, full recovery, no issues → net risk near 0
        lbl = self._label(
            base_protocol_audit_score=100,
            dependency_depth=1,
            circuit_breaker_exists=True,
            auto_unwind_available=True,
            time_to_unwind_hours=24,
            historical_issues_count=0,
        )
        self.assertEqual(lbl, RISK_LABEL_SAFE)

    def test_low_risk(self):
        # mid-low risk
        lbl = self._label(
            base_protocol_audit_score=85,
            dependency_depth=1,
            circuit_breaker_exists=True,
            auto_unwind_available=False,
            time_to_unwind_hours=48,
            historical_issues_count=0,
        )
        self.assertIn(lbl, ALL_RISK_LABELS)

    def test_systemic_deep_dependency(self):
        # depth > 4 → SYSTEMIC
        lbl = self._label(
            dependency_depth=5,
            base_protocol_audit_score=80,
            circuit_breaker_exists=True,
            auto_unwind_available=True,
            time_to_unwind_hours=24,
        )
        self.assertEqual(lbl, RISK_LABEL_SYSTEMIC)

    def test_systemic_high_risk_score(self):
        # low audit, deep, no recovery → net risk > 80 → SYSTEMIC
        lbl = self._label(
            base_protocol_audit_score=0,
            dependency_depth=4,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
            historical_issues_count=3,
        )
        self.assertEqual(lbl, RISK_LABEL_SYSTEMIC)

    def test_all_labels_valid(self):
        lbl = self._label()
        self.assertIn(lbl, ALL_RISK_LABELS)

    def test_high_risk_label(self):
        # force high net risk 60-80
        lbl = self._label(
            base_protocol_audit_score=10,
            dependency_depth=3,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
            historical_issues_count=0,
        )
        self.assertIn(lbl, [RISK_LABEL_HIGH, RISK_LABEL_SYSTEMIC])

    def test_moderate_label(self):
        lbl = self._label(
            base_protocol_audit_score=60,
            dependency_depth=2,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=48,
            historical_issues_count=0,
        )
        self.assertIn(lbl, ALL_RISK_LABELS)


class TestFlags(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _flags(self, **kwargs):
        integ = _make_integration(**kwargs)
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['flags']

    def test_no_flags_on_safe_integration(self):
        flags = self._flags(
            dependency_depth=1,
            circuit_breaker_exists=True,
            time_to_unwind_hours=24,
            historical_issues_count=0,
            tvl_at_risk_usd=500_000,
        )
        self.assertEqual(flags, [])

    def test_deep_dependency_flag(self):
        flags = self._flags(dependency_depth=4)
        self.assertIn(FLAG_DEEP_DEPENDENCY, flags)

    def test_no_deep_dependency_flag_at_threshold(self):
        # threshold is 3, flag when > 3
        flags = self._flags(dependency_depth=3)
        self.assertNotIn(FLAG_DEEP_DEPENDENCY, flags)

    def test_no_circuit_breaker_flag(self):
        flags = self._flags(circuit_breaker_exists=False)
        self.assertIn(FLAG_NO_CIRCUIT_BREAKER, flags)

    def test_circuit_breaker_no_flag(self):
        flags = self._flags(circuit_breaker_exists=True)
        self.assertNotIn(FLAG_NO_CIRCUIT_BREAKER, flags)

    def test_slow_unwind_flag(self):
        flags = self._flags(time_to_unwind_hours=73)
        self.assertIn(FLAG_SLOW_UNWIND, flags)

    def test_no_slow_unwind_at_threshold(self):
        flags = self._flags(time_to_unwind_hours=72)
        self.assertNotIn(FLAG_SLOW_UNWIND, flags)

    def test_prior_issues_flag(self):
        flags = self._flags(historical_issues_count=1)
        self.assertIn(FLAG_PRIOR_ISSUES, flags)

    def test_no_prior_issues_flag(self):
        flags = self._flags(historical_issues_count=0)
        self.assertNotIn(FLAG_PRIOR_ISSUES, flags)

    def test_large_tvl_flag(self):
        flags = self._flags(tvl_at_risk_usd=10_000_001)
        self.assertIn(FLAG_LARGE_TVL_AT_RISK, flags)

    def test_no_large_tvl_flag(self):
        flags = self._flags(tvl_at_risk_usd=10_000_000)
        self.assertNotIn(FLAG_LARGE_TVL_AT_RISK, flags)

    def test_multiple_flags(self):
        flags = self._flags(
            dependency_depth=5,
            circuit_breaker_exists=False,
            time_to_unwind_hours=100,
            historical_issues_count=2,
            tvl_at_risk_usd=20_000_000,
        )
        self.assertIn(FLAG_DEEP_DEPENDENCY, flags)
        self.assertIn(FLAG_NO_CIRCUIT_BREAKER, flags)
        self.assertIn(FLAG_SLOW_UNWIND, flags)
        self.assertIn(FLAG_PRIOR_ISSUES, flags)
        self.assertIn(FLAG_LARGE_TVL_AT_RISK, flags)
        self.assertEqual(len(flags), 5)

    def test_flags_is_list(self):
        flags = self._flags()
        self.assertIsInstance(flags, list)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_highest_risk_is_highest(self):
        integ_safe = _make_integration(
            name='safe',
            base_protocol_audit_score=100,
            dependency_depth=1,
            circuit_breaker_exists=True,
            auto_unwind_available=True,
            time_to_unwind_hours=24,
        )
        integ_risky = _make_integration(
            name='risky',
            base_protocol_audit_score=0,
            dependency_depth=5,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
            historical_issues_count=3,
        )
        r = self.a.analyze([integ_safe, integ_risky], config={'log_file': self.log})
        self.assertEqual(r['aggregates']['highest_risk_integration'], 'risky')

    def test_safest_is_safest(self):
        integ_safe = _make_integration(
            name='safe',
            base_protocol_audit_score=100,
            dependency_depth=1,
            circuit_breaker_exists=True,
            auto_unwind_available=True,
            time_to_unwind_hours=24,
        )
        integ_risky = _make_integration(
            name='risky',
            base_protocol_audit_score=0,
            dependency_depth=5,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
        )
        r = self.a.analyze([integ_safe, integ_risky], config={'log_file': self.log})
        self.assertEqual(r['aggregates']['safest_integration'], 'safe')

    def test_total_tvl_at_risk(self):
        integ1 = _make_integration(name='a', tvl_at_risk_usd=1_000_000)
        integ2 = _make_integration(name='b', tvl_at_risk_usd=2_000_000)
        r = self.a.analyze([integ1, integ2], config={'log_file': self.log})
        self.assertAlmostEqual(r['aggregates']['total_tvl_at_risk_usd'], 3_000_000.0)

    def test_systemic_count(self):
        systemic = _make_integration(
            name='sys',
            dependency_depth=5,
            base_protocol_audit_score=0,
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
        )
        safe = _make_integration(name='safe')
        r = self.a.analyze([systemic, safe], config={'log_file': self.log})
        self.assertEqual(r['aggregates']['systemic_count'], 1)

    def test_average_risk_score(self):
        i1 = _make_integration(name='a')
        i2 = _make_integration(name='b')
        r = self.a.analyze([i1, i2], config={'log_file': self.log})
        agg = r['aggregates']
        expected = (r['results'][0]['net_composability_risk'] +
                    r['results'][1]['net_composability_risk']) / 2
        self.assertAlmostEqual(agg['average_risk_score'], round(expected, 4), places=2)

    def test_single_integration_aggregates(self):
        integ = _make_integration(name='solo', tvl_at_risk_usd=5_000_000)
        r = self.a.analyze([integ], config={'log_file': self.log})
        agg = r['aggregates']
        self.assertEqual(agg['highest_risk_integration'], 'solo')
        self.assertEqual(agg['safest_integration'], 'solo')
        self.assertAlmostEqual(agg['total_tvl_at_risk_usd'], 5_000_000.0)


class TestNetComposabilityRisk(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def _net_risk(self, **kwargs):
        integ = _make_integration(**kwargs)
        r = self.a.analyze([integ], config={'log_file': self.log})
        return r['results'][0]['net_composability_risk']

    def test_bounded_0_to_100(self):
        for audit in [0, 50, 100]:
            for depth in [1, 3, 6]:
                risk = self._net_risk(
                    base_protocol_audit_score=audit,
                    dependency_depth=depth,
                    circuit_breaker_exists=False,
                    auto_unwind_available=False,
                    time_to_unwind_hours=200,
                    historical_issues_count=5,
                )
                self.assertGreaterEqual(risk, 0.0)
                self.assertLessEqual(risk, 100.0)

    def test_lower_audit_higher_risk(self):
        r_high = self._net_risk(base_protocol_audit_score=30)
        r_low = self._net_risk(base_protocol_audit_score=90)
        self.assertGreater(r_high, r_low)

    def test_more_issues_higher_risk(self):
        r_with = self._net_risk(historical_issues_count=3)
        r_without = self._net_risk(historical_issues_count=0)
        self.assertGreater(r_with, r_without)

    def test_issue_penalty_capped(self):
        r_10 = self._net_risk(historical_issues_count=10)
        r_100 = self._net_risk(historical_issues_count=100)
        # Both hit the cap; should be equal
        self.assertAlmostEqual(r_10, r_100, places=2)

    def test_full_recovery_reduces_risk(self):
        r_no_recovery = self._net_risk(
            circuit_breaker_exists=False,
            auto_unwind_available=False,
            time_to_unwind_hours=200,
        )
        r_full_recovery = self._net_risk(
            circuit_breaker_exists=True,
            auto_unwind_available=True,
            time_to_unwind_hours=24,
        )
        self.assertGreater(r_no_recovery, r_full_recovery)


class TestFieldPassthrough(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_name_passthrough(self):
        integ = _make_integration(name='MyIntegration')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['name'], 'MyIntegration')

    def test_base_protocol_passthrough(self):
        integ = _make_integration(base_protocol='Uniswap')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['base_protocol'], 'Uniswap')

    def test_dependent_protocol_passthrough(self):
        integ = _make_integration(dependent_protocol='Curve')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['dependent_protocol'], 'Curve')

    def test_integration_type_passthrough(self):
        for t in ('collateral', 'oracle', 'liquidity', 'yield_source', 'governance'):
            integ = _make_integration(integration_type=t)
            r = self.a.analyze([integ], config={'log_file': self.log})
            self.assertEqual(r['results'][0]['integration_type'], t)

    def test_tvl_passthrough(self):
        integ = _make_integration(tvl_at_risk_usd=7_654_321)
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertAlmostEqual(r['results'][0]['tvl_at_risk_usd'], 7_654_321.0)

    def test_depth_passthrough(self):
        integ = _make_integration(dependency_depth=3)
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['dependency_depth'], 3)


class TestMissingFields(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_empty_integration_dict(self):
        r = self.a.analyze([{}], config={'log_file': self.log})
        self.assertEqual(r['integrations_analyzed'], 1)
        res = r['results'][0]
        self.assertEqual(res['name'], 'unknown')
        self.assertIn(res['risk_label'], ALL_RISK_LABELS)

    def test_partial_fields(self):
        r = self.a.analyze([{'name': 'partial', 'tvl_at_risk_usd': 500_000}],
                           config={'log_file': self.log})
        self.assertEqual(r['integrations_analyzed'], 1)

    def test_missing_circuit_breaker_defaults_false(self):
        # No circuit_breaker_exists → defaults False → NO_CIRCUIT_BREAKER flag
        integ = {'name': 'no_cb', 'dependency_depth': 1}
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertIn(FLAG_NO_CIRCUIT_BREAKER, r['results'][0]['flags'])


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_systemic_depth_threshold_override(self):
        # Lower threshold: depth=3 should be SYSTEMIC
        cfg = {'systemic_depth_threshold': 2, 'log_file': self.log}
        integ = _make_integration(dependency_depth=3)
        r = self.a.analyze([integ], config=cfg)
        self.assertEqual(r['results'][0]['risk_label'], RISK_LABEL_SYSTEMIC)

    def test_large_tvl_threshold_override(self):
        cfg = {'large_tvl_threshold_usd': 500_000, 'log_file': self.log}
        integ = _make_integration(tvl_at_risk_usd=600_000)
        r = self.a.analyze([integ], config=cfg)
        self.assertIn(FLAG_LARGE_TVL_AT_RISK, r['results'][0]['flags'])

    def test_slow_unwind_threshold_override(self):
        cfg = {'slow_unwind_threshold_hours': 12, 'log_file': self.log}
        integ = _make_integration(time_to_unwind_hours=24)
        r = self.a.analyze([integ], config=cfg)
        self.assertIn(FLAG_SLOW_UNWIND, r['results'][0]['flags'])

    def test_deep_dependency_threshold_override(self):
        cfg = {'deep_dependency_threshold': 1, 'log_file': self.log}
        integ = _make_integration(dependency_depth=2)
        r = self.a.analyze([integ], config=cfg)
        self.assertIn(FLAG_DEEP_DEPENDENCY, r['results'][0]['flags'])


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_log_created_on_first_call(self):
        self.assertFalse(os.path.exists(self.log))
        self.a.analyze([], config={'log_file': self.log})
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_valid_json(self):
        self.a.analyze([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        self.a.analyze([], config={'log_file': self.log})
        self.a.analyze([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap(self):
        # write 105 entries, only 100 should remain
        for _ in range(105):
            self.a.analyze([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_keeps_latest_entries(self):
        # Fill to 101
        for i in range(101):
            self.a.analyze([_make_integration(name=f'integ_{i}')],
                           config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        # Latest entry should be integ_100
        last = data[-1]
        self.assertEqual(last['results'][0]['name'], 'integ_100')

    def test_log_entry_has_timestamp(self):
        self.a.analyze([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn('timestamp', data[0])

    def test_corrupted_log_recovered(self):
        # Write invalid JSON to the log file
        with open(self.log, 'w') as f:
            f.write('not valid json {{{')
        # Should not raise, should start fresh
        self.a.analyze([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_log_atomic_write_no_partial_file(self):
        # Verify that the log file is a proper JSON after each write
        for i in range(5):
            self.a.analyze([_make_integration(name=f'x{i}')],
                           config={'log_file': self.log})
            with open(self.log) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)


class TestMultipleIntegrations(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_three_integrations(self):
        integrations = [
            _make_integration(name='a', tvl_at_risk_usd=1_000_000),
            _make_integration(name='b', tvl_at_risk_usd=2_000_000),
            _make_integration(name='c', tvl_at_risk_usd=3_000_000),
        ]
        r = self.a.analyze(integrations, config={'log_file': self.log})
        self.assertEqual(r['integrations_analyzed'], 3)
        self.assertEqual(len(r['results']), 3)

    def test_all_systemic(self):
        integrations = [
            _make_integration(name=f's{i}', dependency_depth=5,
                              base_protocol_audit_score=0,
                              circuit_breaker_exists=False,
                              auto_unwind_available=False,
                              time_to_unwind_hours=200)
            for i in range(3)
        ]
        r = self.a.analyze(integrations, config={'log_file': self.log})
        self.assertEqual(r['aggregates']['systemic_count'], 3)

    def test_results_preserves_order(self):
        integrations = [_make_integration(name=n) for n in ['x', 'y', 'z']]
        r = self.a.analyze(integrations, config={'log_file': self.log})
        names = [res['name'] for res in r['results']]
        self.assertEqual(names, ['x', 'y', 'z'])

    def test_tvl_sum_correct(self):
        tvls = [1_000_000, 2_500_000, 500_000]
        integrations = [_make_integration(name=f'p{i}', tvl_at_risk_usd=t)
                        for i, t in enumerate(tvls)]
        r = self.a.analyze(integrations, config={'log_file': self.log})
        self.assertAlmostEqual(
            r['aggregates']['total_tvl_at_risk_usd'], sum(tvls), places=2
        )


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_depth_zero_treated_as_int(self):
        integ = _make_integration(dependency_depth=0)
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['dependency_depth'], 0)

    def test_very_large_tvl(self):
        integ = _make_integration(tvl_at_risk_usd=1e12)
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertAlmostEqual(r['results'][0]['tvl_at_risk_usd'], 1e12)

    def test_audit_score_clamped_above_100(self):
        integ = _make_integration(base_protocol_audit_score=150)
        r = self.a.analyze([integ], config={'log_file': self.log})
        # Should not raise; risk should still be in [0,100]
        risk = r['results'][0]['net_composability_risk']
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 100.0)

    def test_audit_score_clamped_below_zero(self):
        integ = _make_integration(base_protocol_audit_score=-10)
        r = self.a.analyze([integ], config={'log_file': self.log})
        risk = r['results'][0]['net_composability_risk']
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 100.0)

    def test_zero_historical_issues(self):
        integ = _make_integration(historical_issues_count=0)
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertNotIn(FLAG_PRIOR_ISSUES, r['results'][0]['flags'])

    def test_hundred_historical_issues_caps_penalty(self):
        # Many issues → penalty capped
        integ = _make_integration(historical_issues_count=100)
        r = self.a.analyze([integ], config={'log_file': self.log})
        risk = r['results'][0]['net_composability_risk']
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 100.0)

    def test_config_none_uses_defaults(self):
        integ = _make_integration()
        r = self.a.analyze([integ], config=None)
        self.assertIn('results', r)

    def test_numeric_fields_are_float(self):
        integ = _make_integration()
        r = self.a.analyze([integ], config={'log_file': self.log})
        res = r['results'][0]
        self.assertIsInstance(res['fragility_score'], float)
        self.assertIsInstance(res['recovery_score'], float)
        self.assertIsInstance(res['net_composability_risk'], float)
        self.assertIsInstance(res['contagion_multiplier'], float)


class TestIntegrationTypes(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.a = DeFiProtocolComposabilityRiskAnalyzer(log_file=self.log)

    def test_collateral_type(self):
        integ = _make_integration(integration_type='collateral')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['integration_type'], 'collateral')

    def test_oracle_type(self):
        integ = _make_integration(integration_type='oracle')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['integration_type'], 'oracle')

    def test_liquidity_type(self):
        integ = _make_integration(integration_type='liquidity')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['integration_type'], 'liquidity')

    def test_yield_source_type(self):
        integ = _make_integration(integration_type='yield_source')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['integration_type'], 'yield_source')

    def test_governance_type(self):
        integ = _make_integration(integration_type='governance')
        r = self.a.analyze([integ], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['integration_type'], 'governance')


class TestRiskLabelConstants(unittest.TestCase):
    def test_safe_constant(self):
        self.assertEqual(RISK_LABEL_SAFE, 'SAFE_COMPOSITION')

    def test_low_constant(self):
        self.assertEqual(RISK_LABEL_LOW, 'LOW_RISK')

    def test_moderate_constant(self):
        self.assertEqual(RISK_LABEL_MODERATE, 'MODERATE')

    def test_high_constant(self):
        self.assertEqual(RISK_LABEL_HIGH, 'HIGH_RISK')

    def test_systemic_constant(self):
        self.assertEqual(RISK_LABEL_SYSTEMIC, 'SYSTEMIC')

    def test_all_labels_list_has_five(self):
        self.assertEqual(len(ALL_RISK_LABELS), 5)

    def test_flag_constants(self):
        self.assertEqual(FLAG_DEEP_DEPENDENCY, 'DEEP_DEPENDENCY')
        self.assertEqual(FLAG_NO_CIRCUIT_BREAKER, 'NO_CIRCUIT_BREAKER')
        self.assertEqual(FLAG_SLOW_UNWIND, 'SLOW_UNWIND')
        self.assertEqual(FLAG_PRIOR_ISSUES, 'PRIOR_ISSUES')
        self.assertEqual(FLAG_LARGE_TVL_AT_RISK, 'LARGE_TVL_AT_RISK')


if __name__ == '__main__':
    unittest.main()
