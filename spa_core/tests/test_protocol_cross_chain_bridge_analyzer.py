"""
Tests for MP-904: ProtocolCrossChainBridgeAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_cross_chain_bridge_analyzer -v
"""
import json
import os
import sys
import tempfile
import unittest

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))

from spa_core.analytics.protocol_cross_chain_bridge_analyzer import (
    ProtocolCrossChainBridgeAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bridge(**kwargs):
    """Return a pristine safe bridge dict, overriding with kwargs."""
    base = {
        "name":                  "SafeBridge",
        "tvl_locked_usd":        500_000_000.0,
        "hack_history":          [],
        "validator_count":       100,
        "finality_time_seconds": 60.0,
        "fee_pct":               0.05,
        "supported_chains":      ["Ethereum", "Arbitrum", "Optimism", "Polygon",
                                  "BNB", "Avalanche", "Fantom", "Base"],
        "audit_count":           4,
        "age_days":              900,
        "daily_volume_usd":      50_000_000.0,
    }
    base.update(kwargs)
    return base


def _make_risky_bridge(**kwargs):
    """Return a high-risk bridge dict, overriding with kwargs."""
    base = {
        "name":                  "RiskyBridge",
        "tvl_locked_usd":        1_000_000.0,
        "hack_history":          [{"amount": 1e8, "date": "2023-01-01"},
                                  {"amount": 2e7, "date": "2023-06-01"}],
        "validator_count":       2,
        "finality_time_seconds": 7200.0,
        "fee_pct":               2.5,
        "supported_chains":      ["Ethereum"],
        "audit_count":           0,
        "age_days":              20,
        "daily_volume_usd":      5_000.0,
    }
    base.update(kwargs)
    return base


class TestProtocolCrossChainBridgeAnalyzerInit(unittest.TestCase):
    def test_instantiation(self):
        analyzer = ProtocolCrossChainBridgeAnalyzer()
        self.assertIsNotNone(analyzer)

    def test_log_cap_constant(self):
        self.assertEqual(ProtocolCrossChainBridgeAnalyzer.LOG_CAP, 100)

    def test_few_validators_threshold(self):
        self.assertEqual(ProtocolCrossChainBridgeAnalyzer.FEW_VALIDATORS_THRESHOLD, 5)

    def test_slow_finality_threshold(self):
        self.assertEqual(ProtocolCrossChainBridgeAnalyzer.SLOW_FINALITY_THRESHOLD, 3600)

    def test_high_fee_threshold(self):
        self.assertEqual(ProtocolCrossChainBridgeAnalyzer.HIGH_FEE_THRESHOLD, 1.0)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyBridges(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()
        self.result = self.analyzer.analyze([], {})

    def test_status_ok(self):
        self.assertEqual(self.result["status"], "ok")

    def test_bridges_empty(self):
        self.assertEqual(self.result["bridges"], [])

    def test_safest_bridge_none(self):
        self.assertIsNone(self.result["aggregates"]["safest_bridge"])

    def test_riskiest_bridge_none(self):
        self.assertIsNone(self.result["aggregates"]["riskiest_bridge"])

    def test_total_tvl_at_risk_zero(self):
        self.assertEqual(self.result["aggregates"]["total_tvl_at_risk_usd"], 0.0)

    def test_hack_count_total_zero(self):
        self.assertEqual(self.result["aggregates"]["hack_count_total"], 0)

    def test_average_efficiency_zero(self):
        self.assertEqual(self.result["aggregates"]["average_efficiency"], 0.0)

    def test_total_bridges_zero(self):
        self.assertEqual(self.result["aggregates"]["total_bridges"], 0)


# ---------------------------------------------------------------------------
# Single bridge output structure
# ---------------------------------------------------------------------------

class TestSingleBridgeOutputStructure(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()
        self.result   = self.analyzer.analyze([_make_bridge()], {})
        self.bridge   = self.result["bridges"][0]

    def test_has_name(self):
        self.assertIn("name", self.bridge)

    def test_has_tvl_locked_usd(self):
        self.assertIn("tvl_locked_usd", self.bridge)

    def test_has_hack_count(self):
        self.assertIn("hack_count", self.bridge)

    def test_has_security_score(self):
        self.assertIn("security_score", self.bridge)

    def test_has_efficiency_score(self):
        self.assertIn("efficiency_score", self.bridge)

    def test_has_trust_score(self):
        self.assertIn("trust_score", self.bridge)

    def test_has_safety_label(self):
        self.assertIn("safety_label", self.bridge)

    def test_has_flags(self):
        self.assertIn("flags", self.bridge)

    def test_name_preserved(self):
        self.assertEqual(self.bridge["name"], "SafeBridge")

    def test_tvl_preserved(self):
        self.assertAlmostEqual(self.bridge["tvl_locked_usd"], 500_000_000.0)

    def test_hack_count_zero_for_safe_bridge(self):
        self.assertEqual(self.bridge["hack_count"], 0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.bridge["flags"], list)

    def test_safety_label_is_string(self):
        self.assertIsInstance(self.bridge["safety_label"], str)

    def test_result_status_ok(self):
        self.assertEqual(self.result["status"], "ok")


# ---------------------------------------------------------------------------
# Score ranges (all 0-100)
# ---------------------------------------------------------------------------

class TestScoreRanges(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _analyze(self, **kwargs):
        return self.analyzer.analyze([_make_bridge(**kwargs)], {})["bridges"][0]

    def test_security_score_range_safe(self):
        s = self._analyze()["security_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_efficiency_score_range_safe(self):
        s = self._analyze()["efficiency_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_trust_score_range_safe(self):
        s = self._analyze()["trust_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_security_score_range_risky(self):
        s = self.analyzer.analyze([_make_risky_bridge()], {})["bridges"][0]["security_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_trust_score_range_risky(self):
        s = self.analyzer.analyze([_make_risky_bridge()], {})["bridges"][0]["trust_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_scores_are_floats(self):
        b = self._analyze()
        for key in ("security_score", "efficiency_score", "trust_score"):
            self.assertIsInstance(b[key], float)


# ---------------------------------------------------------------------------
# Security score
# ---------------------------------------------------------------------------

class TestSecurityScore(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _sec(self, **kwargs):
        return self.analyzer.analyze([_make_bridge(**kwargs)], {})["bridges"][0]["security_score"]

    def test_no_hacks_higher_security(self):
        no_hack  = self._sec(hack_history=[])
        one_hack = self._sec(hack_history=[{"amount": 1e8}])
        self.assertGreater(no_hack, one_hack)

    def test_one_hack_penalty(self):
        none = self._sec(hack_history=[])
        one  = self._sec(hack_history=[{"amount": 1e8}])
        self.assertGreater(none, one)

    def test_two_hacks_lower_than_one_hack(self):
        one = self._sec(hack_history=[{"amount": 1e8}])
        two = self._sec(hack_history=[{"amount": 1e8}, {"amount": 2e7}])
        self.assertGreater(one, two)

    def test_three_plus_hacks_max_penalty(self):
        three = self._sec(hack_history=[{}, {}, {}])
        two   = self._sec(hack_history=[{}, {}])
        self.assertLessEqual(three, two)

    def test_many_validators_higher_security(self):
        many = self._sec(validator_count=100)
        few  = self._sec(validator_count=2)
        self.assertGreater(many, few)

    def test_few_validators_penalty(self):
        s = self._sec(validator_count=3)
        self.assertLess(s, self._sec(validator_count=20))

    def test_many_audits_higher_security(self):
        many = self._sec(audit_count=5)
        none = self._sec(audit_count=0)
        self.assertGreater(many, none)

    def test_no_audits_penalty(self):
        s = self._sec(audit_count=0)
        self.assertLess(s, self._sec(audit_count=3))

    def test_old_bridge_higher_security(self):
        old = self._sec(age_days=1000)
        new = self._sec(age_days=10)
        self.assertGreater(old, new)

    def test_very_new_bridge_penalty(self):
        s = self._sec(age_days=5)
        self.assertLess(s, self._sec(age_days=500))


# ---------------------------------------------------------------------------
# Efficiency score
# ---------------------------------------------------------------------------

class TestEfficiencyScore(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _eff(self, **kwargs):
        return self.analyzer.analyze([_make_bridge(**kwargs)], {})["bridges"][0]["efficiency_score"]

    def test_fast_finality_higher_efficiency(self):
        fast = self._eff(finality_time_seconds=30)
        slow = self._eff(finality_time_seconds=7200)
        self.assertGreater(fast, slow)

    def test_slow_finality_penalty(self):
        s = self._eff(finality_time_seconds=7200)
        self.assertLess(s, self._eff(finality_time_seconds=60))

    def test_finality_at_300s(self):
        s = self._eff(finality_time_seconds=300)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_low_fee_higher_efficiency(self):
        low  = self._eff(fee_pct=0.01)
        high = self._eff(fee_pct=3.0)
        self.assertGreater(low, high)

    def test_high_fee_penalty(self):
        s = self._eff(fee_pct=2.0)
        self.assertLess(s, self._eff(fee_pct=0.05))

    def test_many_chains_higher_efficiency(self):
        many = self._eff(supported_chains=list(range(25)))
        few  = self._eff(supported_chains=["Ethereum"])
        self.assertGreater(many, few)

    def test_no_chains_penalty(self):
        s = self._eff(supported_chains=[])
        self.assertLess(s, self._eff(supported_chains=list(range(15))))

    def test_high_volume_ratio_bonus(self):
        # TVL = 1M, daily volume = 500k → ratio 0.5 → bonus
        high = self._eff(tvl_locked_usd=1_000_000, daily_volume_usd=500_000)
        low  = self._eff(tvl_locked_usd=1_000_000, daily_volume_usd=100)
        self.assertGreater(high, low)

    def test_zero_daily_volume_no_crash(self):
        s = self._eff(daily_volume_usd=0.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_zero_tvl_no_crash(self):
        s = self._eff(tvl_locked_usd=0.0)
        self.assertGreaterEqual(s, 0.0)


# ---------------------------------------------------------------------------
# Trust score
# ---------------------------------------------------------------------------

class TestTrustScore(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _trust(self, **kwargs):
        return self.analyzer.analyze([_make_bridge(**kwargs)], {})["bridges"][0]["trust_score"]

    def test_trust_in_range(self):
        s = self._trust()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_two_hacks_reduce_trust_more_than_one(self):
        one = self._trust(hack_history=[{}])
        two = self._trust(hack_history=[{}, {}])
        self.assertGreater(one, two)

    def test_no_audit_reduces_trust(self):
        no_audit  = self._trust(audit_count=0)
        has_audit = self._trust(audit_count=3)
        self.assertLess(no_audit, has_audit)

    def test_safe_bridge_higher_trust(self):
        safe  = self._trust()
        risky = self.analyzer.analyze([_make_risky_bridge()], {})["bridges"][0]["trust_score"]
        self.assertGreater(safe, risky)

    def test_two_hacks_apply_0_70_multiplier_effect(self):
        # Direct unit test of _compute_trust_score
        a = self.analyzer
        base = a._compute_trust_score(80, 80, 0, 3)
        hacked = a._compute_trust_score(80, 80, 2, 3)
        self.assertAlmostEqual(hacked, base * 0.70, places=5)


# ---------------------------------------------------------------------------
# Safety labels
# ---------------------------------------------------------------------------

class TestSafetyLabels(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _label(self, trust_score):
        return self.analyzer._get_safety_label(trust_score)

    def test_score_0_is_critical(self):
        self.assertEqual(self._label(0.0), "CRITICAL")

    def test_score_19_is_critical(self):
        self.assertEqual(self._label(19.9), "CRITICAL")

    def test_score_20_is_very_risky(self):
        self.assertEqual(self._label(20.0), "VERY_RISKY")

    def test_score_39_is_very_risky(self):
        self.assertEqual(self._label(39.9), "VERY_RISKY")

    def test_score_40_is_risky(self):
        self.assertEqual(self._label(40.0), "RISKY")

    def test_score_54_is_risky(self):
        self.assertEqual(self._label(54.9), "RISKY")

    def test_score_55_is_moderate(self):
        self.assertEqual(self._label(55.0), "MODERATE")

    def test_score_69_is_moderate(self):
        self.assertEqual(self._label(69.9), "MODERATE")

    def test_score_70_is_safe(self):
        self.assertEqual(self._label(70.0), "SAFE")

    def test_score_84_is_safe(self):
        self.assertEqual(self._label(84.9), "SAFE")

    def test_score_85_is_very_safe(self):
        self.assertEqual(self._label(85.0), "VERY_SAFE")

    def test_score_100_is_very_safe(self):
        self.assertEqual(self._label(100.0), "VERY_SAFE")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def _flags(self, **kwargs):
        return self.analyzer.analyze([_make_bridge(**kwargs)], {})["bridges"][0]["flags"]

    def test_hack_history_flag_triggered(self):
        self.assertIn("HACK_HISTORY", self._flags(hack_history=[{"amount": 1e8}]))

    def test_hack_history_flag_not_triggered_empty(self):
        self.assertNotIn("HACK_HISTORY", self._flags(hack_history=[]))

    def test_few_validators_flag_triggered(self):
        self.assertIn("FEW_VALIDATORS", self._flags(validator_count=3))

    def test_few_validators_flag_at_threshold(self):
        # count = 4 < 5 → should trigger
        self.assertIn("FEW_VALIDATORS", self._flags(validator_count=4))

    def test_few_validators_not_triggered_at_5(self):
        self.assertNotIn("FEW_VALIDATORS", self._flags(validator_count=5))

    def test_slow_finality_flag_triggered(self):
        self.assertIn("SLOW_FINALITY", self._flags(finality_time_seconds=3601))

    def test_slow_finality_flag_not_triggered_at_threshold(self):
        self.assertNotIn("SLOW_FINALITY", self._flags(finality_time_seconds=3600.0))

    def test_high_fee_flag_triggered(self):
        self.assertIn("HIGH_FEE", self._flags(fee_pct=1.5))

    def test_high_fee_flag_not_triggered_at_threshold(self):
        self.assertNotIn("HIGH_FEE", self._flags(fee_pct=1.0))

    def test_low_audit_flag_triggered(self):
        self.assertIn("LOW_AUDIT", self._flags(audit_count=0))

    def test_low_audit_flag_not_triggered_with_one_audit(self):
        self.assertNotIn("LOW_AUDIT", self._flags(audit_count=1))

    def test_all_flags_on_worst_bridge(self):
        flags = self._flags(
            hack_history=[{}, {}],
            validator_count=1,
            finality_time_seconds=10_000,
            fee_pct=5.0,
            audit_count=0,
        )
        self.assertIn("HACK_HISTORY",    flags)
        self.assertIn("FEW_VALIDATORS",  flags)
        self.assertIn("SLOW_FINALITY",   flags)
        self.assertIn("HIGH_FEE",        flags)
        self.assertIn("LOW_AUDIT",       flags)

    def test_no_flags_pristine_bridge(self):
        flags = self._flags(
            hack_history=[],
            validator_count=50,
            finality_time_seconds=30,
            fee_pct=0.05,
            audit_count=5,
        )
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()
        self.safe  = _make_bridge(name="Safe",  tvl_locked_usd=1_000_000_000)
        self.risky = _make_risky_bridge(name="Risky", tvl_locked_usd=500_000)
        self.result = self.analyzer.analyze([self.safe, self.risky], {})
        self.agg = self.result["aggregates"]

    def test_safest_bridge_is_safe(self):
        self.assertEqual(self.agg["safest_bridge"], "Safe")

    def test_riskiest_bridge_is_risky(self):
        self.assertEqual(self.agg["riskiest_bridge"], "Risky")

    def test_total_tvl_at_risk_is_sum(self):
        expected = 1_000_000_000 + 500_000
        self.assertAlmostEqual(self.agg["total_tvl_at_risk_usd"], expected)

    def test_hack_count_total(self):
        expected = 0 + len(_make_risky_bridge()["hack_history"])
        self.assertEqual(self.agg["hack_count_total"], expected)

    def test_average_efficiency_is_mean(self):
        bridges = self.result["bridges"]
        expected = (bridges[0]["efficiency_score"] + bridges[1]["efficiency_score"]) / 2
        self.assertAlmostEqual(self.agg["average_efficiency"], expected, places=1)

    def test_total_bridges_correct(self):
        self.assertEqual(self.agg["total_bridges"], 2)

    def test_single_bridge_safest_equals_riskiest(self):
        result = self.analyzer.analyze([_make_bridge(name="Only")], {})
        agg = result["aggregates"]
        self.assertEqual(agg["safest_bridge"], "Only")
        self.assertEqual(agg["riskiest_bridge"], "Only")

    def test_three_bridges_total_tvl(self):
        b1 = _make_bridge(name="A", tvl_locked_usd=1_000_000)
        b2 = _make_bridge(name="B", tvl_locked_usd=2_000_000)
        b3 = _make_bridge(name="C", tvl_locked_usd=3_000_000)
        agg = self.analyzer.analyze([b1, b2, b3], {})["aggregates"]
        self.assertAlmostEqual(agg["total_tvl_at_risk_usd"], 6_000_000)


# ---------------------------------------------------------------------------
# Log / persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()
        self.tmp_dir  = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_bridge_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_persist_false_no_file(self):
        self.analyzer.analyze([_make_bridge()], {"persist": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_persist_true_creates_file(self):
        self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_correctly(self):
        self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_at_100(self):
        for _ in range(105):
            self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_written_atomically(self):
        self.analyzer.analyze([_make_bridge()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            content = f.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolCrossChainBridgeAnalyzer()

    def test_missing_all_fields_uses_defaults(self):
        result = self.analyzer.analyze([{}], {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["bridges"]), 1)

    def test_tvl_zero(self):
        result = self.analyzer.analyze([_make_bridge(tvl_locked_usd=0.0)], {})
        self.assertIn("trust_score", result["bridges"][0])

    def test_validator_count_zero(self):
        result = self.analyzer.analyze([_make_bridge(validator_count=0)], {})
        b = result["bridges"][0]
        self.assertIn("FEW_VALIDATORS", b["flags"])

    def test_validator_count_exactly_5(self):
        b = self.analyzer.analyze([_make_bridge(validator_count=5)], {})["bridges"][0]
        self.assertNotIn("FEW_VALIDATORS", b["flags"])

    def test_finality_exactly_3600(self):
        b = self.analyzer.analyze([_make_bridge(finality_time_seconds=3600.0)], {})["bridges"][0]
        self.assertNotIn("SLOW_FINALITY", b["flags"])

    def test_finality_just_above_3600(self):
        b = self.analyzer.analyze([_make_bridge(finality_time_seconds=3601.0)], {})["bridges"][0]
        self.assertIn("SLOW_FINALITY", b["flags"])

    def test_fee_exactly_1_pct(self):
        b = self.analyzer.analyze([_make_bridge(fee_pct=1.0)], {})["bridges"][0]
        self.assertNotIn("HIGH_FEE", b["flags"])

    def test_fee_above_1_pct(self):
        b = self.analyzer.analyze([_make_bridge(fee_pct=1.01)], {})["bridges"][0]
        self.assertIn("HIGH_FEE", b["flags"])

    def test_hack_history_empty_list(self):
        b = self.analyzer.analyze([_make_bridge(hack_history=[])], {})["bridges"][0]
        self.assertEqual(b["hack_count"], 0)
        self.assertNotIn("HACK_HISTORY", b["flags"])

    def test_hack_history_one_item(self):
        b = self.analyzer.analyze([_make_bridge(hack_history=[{"amount": 1e6}])], {})["bridges"][0]
        self.assertEqual(b["hack_count"], 1)
        self.assertIn("HACK_HISTORY", b["flags"])

    def test_hack_history_with_string_items(self):
        b = self.analyzer.analyze([_make_bridge(hack_history=["hack1", "hack2"])], {})["bridges"][0]
        self.assertEqual(b["hack_count"], 2)

    def test_supported_chains_empty(self):
        b = self.analyzer.analyze([_make_bridge(supported_chains=[])], {})["bridges"][0]
        self.assertGreaterEqual(b["efficiency_score"], 0.0)

    def test_supported_chains_many(self):
        b = self.analyzer.analyze([_make_bridge(supported_chains=list(range(25)))], {})["bridges"][0]
        self.assertLessEqual(b["efficiency_score"], 100.0)

    def test_age_days_zero(self):
        b = self.analyzer.analyze([_make_bridge(age_days=0)], {})["bridges"][0]
        self.assertGreaterEqual(b["security_score"], 0.0)

    def test_empty_config_uses_defaults(self):
        result = self.analyzer.analyze([_make_bridge()], {})
        self.assertEqual(result["status"], "ok")

    def test_ideal_bridge_label_very_safe(self):
        result = self.analyzer.analyze([_make_bridge()], {})
        label = result["bridges"][0]["safety_label"]
        self.assertIn(label, ("VERY_SAFE", "SAFE"))

    def test_worst_bridge_label(self):
        result = self.analyzer.analyze([_make_risky_bridge()], {})
        label = result["bridges"][0]["safety_label"]
        self.assertIn(label, ("CRITICAL", "VERY_RISKY", "RISKY"))

    def test_five_bridges_total_count(self):
        bridges = [_make_bridge(name=f"B{i}") for i in range(5)]
        result = self.analyzer.analyze(bridges, {})
        self.assertEqual(result["aggregates"]["total_bridges"], 5)

    def test_aggregates_tvl_includes_all_bridges(self):
        bridges = [_make_bridge(name=f"B{i}", tvl_locked_usd=1_000_000) for i in range(3)]
        agg = self.analyzer.analyze(bridges, {})["aggregates"]
        self.assertAlmostEqual(agg["total_tvl_at_risk_usd"], 3_000_000)

    def test_hack_count_in_output(self):
        b = self.analyzer.analyze([_make_bridge(hack_history=[{}, {}, {}])], {})["bridges"][0]
        self.assertEqual(b["hack_count"], 3)

    def test_high_validator_count_max_benefit(self):
        b = self.analyzer.analyze([_make_bridge(validator_count=200)], {})["bridges"][0]
        self.assertLessEqual(b["security_score"], 100.0)

    def test_efficiency_score_no_chains_no_crash(self):
        b = self.analyzer.analyze([_make_bridge(supported_chains=None)], {})["bridges"][0]
        self.assertGreaterEqual(b["efficiency_score"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
