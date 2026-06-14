"""
Tests for MP-941: ProtocolTotalValueSecuredAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_total_value_secured_analyzer -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))

from spa_core.analytics.protocol_total_value_secured_analyzer import (
    ProtocolTotalValueSecuredAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(**kwargs):
    """Return a well-funded, secure protocol dict."""
    base = {
        "name":                         "SafeProtocol",
        "tvl_usd":                      500_000_000.0,
        "bridged_assets_usd":           50_000_000.0,
        "insured_assets_usd":           20_000_000.0,
        "staked_for_security_usd":      100_000_000.0,
        "oracle_secured_usd":           200_000_000.0,
        "validator_set_value_usd":      80_000_000.0,
        "protocol_revenue_monthly_usd": 5_000_000.0,
        "security_budget_monthly_usd":  3_000_000.0,
    }
    base.update(kwargs)
    return base


def _make_weak_protocol(**kwargs):
    """Return an underfunded, risky protocol dict."""
    base = {
        "name":                         "WeakProtocol",
        "tvl_usd":                      10_000_000.0,
        "bridged_assets_usd":           0.0,
        "insured_assets_usd":           0.0,
        "staked_for_security_usd":      0.0,
        "oracle_secured_usd":           0.0,
        "validator_set_value_usd":      0.0,
        "protocol_revenue_monthly_usd": 100.0,
        "security_budget_monthly_usd":  50.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Instantiation & constants
# ---------------------------------------------------------------------------

class TestInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        a = ProtocolTotalValueSecuredAnalyzer()
        self.assertIsNotNone(a)

    def test_log_cap_is_100(self):
        self.assertEqual(ProtocolTotalValueSecuredAnalyzer.LOG_CAP, 100)

    def test_default_log_path_contains_tvs(self):
        self.assertIn("value_secured", ProtocolTotalValueSecuredAnalyzer.DEFAULT_LOG_PATH)

    def test_low_security_budget_ratio(self):
        self.assertAlmostEqual(
            ProtocolTotalValueSecuredAnalyzer.LOW_SECURITY_BUDGET_RATIO, 0.001
        )

    def test_oracle_systemic_multiplier(self):
        self.assertAlmostEqual(
            ProtocolTotalValueSecuredAnalyzer.ORACLE_SYSTEMIC_MULTIPLIER, 10.0
        )

    def test_high_tvs_ratio_threshold(self):
        self.assertAlmostEqual(
            ProtocolTotalValueSecuredAnalyzer.HIGH_TVS_RATIO_THRESHOLD, 5.0
        )

    def test_restaking_dependent_ratio(self):
        self.assertAlmostEqual(
            ProtocolTotalValueSecuredAnalyzer.RESTAKING_DEPENDENT_RATIO, 0.50
        )


# ---------------------------------------------------------------------------
# 2. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()
        self.result = self.analyzer.analyze([], {})

    def test_status_ok(self):
        self.assertEqual(self.result["status"], "ok")

    def test_protocols_empty_list(self):
        self.assertEqual(self.result["protocols"], [])

    def test_aggregates_most_secure_none(self):
        self.assertIsNone(self.result["aggregates"]["most_secure"])

    def test_aggregates_least_secure_none(self):
        self.assertIsNone(self.result["aggregates"]["least_secure"])

    def test_aggregates_total_ecosystem_tvs_zero(self):
        self.assertEqual(self.result["aggregates"]["total_ecosystem_tvs"], 0.0)

    def test_aggregates_average_security_ratio_zero(self):
        self.assertEqual(self.result["aggregates"]["average_security_ratio"], 0.0)

    def test_aggregates_fortress_count_zero(self):
        self.assertEqual(self.result["aggregates"]["fortress_count"], 0)

    def test_aggregates_total_protocols_zero(self):
        self.assertEqual(self.result["aggregates"]["total_protocols"], 0)


# ---------------------------------------------------------------------------
# 3. Single protocol — output structure
# ---------------------------------------------------------------------------

class TestSingleProtocolStructure(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()
        self.result = self.analyzer.analyze([_make_protocol()], {})
        self.p = self.result["protocols"][0]

    def test_has_protocols_key(self):
        self.assertIn("protocols", self.result)

    def test_has_aggregates_key(self):
        self.assertIn("aggregates", self.result)

    def test_has_status_key(self):
        self.assertIn("status", self.result)

    def test_protocol_has_name(self):
        self.assertIn("name", self.p)

    def test_protocol_has_total_value_secured_usd(self):
        self.assertIn("total_value_secured_usd", self.p)

    def test_protocol_has_tvs_to_tvl_ratio(self):
        self.assertIn("tvs_to_tvl_ratio", self.p)

    def test_protocol_has_security_ratio(self):
        self.assertIn("security_ratio", self.p)

    def test_protocol_has_security_adequacy_score(self):
        self.assertIn("security_adequacy_score", self.p)

    def test_protocol_has_attack_cost_estimate_usd(self):
        self.assertIn("attack_cost_estimate_usd", self.p)

    def test_protocol_has_security_label(self):
        self.assertIn("security_label", self.p)

    def test_protocol_has_flags(self):
        self.assertIn("flags", self.p)

    def test_flags_is_list(self):
        self.assertIsInstance(self.p["flags"], list)

    def test_security_label_is_string(self):
        self.assertIsInstance(self.p["security_label"], str)

    def test_adequacy_score_in_range(self):
        self.assertGreaterEqual(self.p["security_adequacy_score"], 0.0)
        self.assertLessEqual(self.p["security_adequacy_score"], 100.0)

    def test_total_tvs_positive_for_funded_protocol(self):
        self.assertGreater(self.p["total_value_secured_usd"], 0.0)

    def test_attack_cost_positive(self):
        self.assertGreater(self.p["attack_cost_estimate_usd"], 0.0)


# ---------------------------------------------------------------------------
# 4. TVS calculation
# ---------------------------------------------------------------------------

class TestTVSCalculation(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def test_tvs_sum_all_components(self):
        p = _make_protocol(
            tvl_usd=100.0,
            bridged_assets_usd=200.0,
            insured_assets_usd=300.0,
            staked_for_security_usd=400.0,
            oracle_secured_usd=500.0,
            validator_set_value_usd=600.0,
        )
        result = self.analyzer.analyze([p], {})
        expected = 100 + 200 + 300 + 400 + 500 + 600
        self.assertAlmostEqual(result["protocols"][0]["total_value_secured_usd"], expected, places=1)

    def test_tvs_equals_tvl_when_all_others_zero(self):
        p = _make_protocol(
            tvl_usd=1_000_000.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=0.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["total_value_secured_usd"], 1_000_000.0, places=1)

    def test_tvs_to_tvl_ratio_equals_one_when_tvs_equals_tvl(self):
        p = _make_protocol(
            tvl_usd=1_000_000.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=0.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["tvs_to_tvl_ratio"], 1.0, places=3)

    def test_tvs_to_tvl_ratio_above_one_when_tvs_greater(self):
        p = _make_protocol(tvl_usd=100.0, bridged_assets_usd=400.0,
                           insured_assets_usd=0.0, staked_for_security_usd=0.0,
                           oracle_secured_usd=0.0, validator_set_value_usd=0.0)
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["tvs_to_tvl_ratio"], 5.0, places=3)

    def test_tvs_to_tvl_ratio_zero_when_tvl_zero(self):
        p = _make_protocol(tvl_usd=0.0)
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["tvs_to_tvl_ratio"], 0.0, places=3)

    def test_tvs_non_negative_with_zero_inputs(self):
        p = {k: 0.0 if k != "name" else "Empty" for k in [
            "name", "tvl_usd", "bridged_assets_usd", "insured_assets_usd",
            "staked_for_security_usd", "oracle_secured_usd", "validator_set_value_usd",
            "protocol_revenue_monthly_usd", "security_budget_monthly_usd"
        ]}
        result = self.analyzer.analyze([p], {})
        self.assertGreaterEqual(result["protocols"][0]["total_value_secured_usd"], 0.0)


# ---------------------------------------------------------------------------
# 5. Security ratio
# ---------------------------------------------------------------------------

class TestSecurityRatio(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def test_security_ratio_formula(self):
        # TVS = tvl only = 1_200_000; security_monthly = 1000; annual = 12000; ratio = 12000/1_200_000 = 0.01
        p = _make_protocol(
            tvl_usd=1_200_000.0,
            bridged_assets_usd=0.0, insured_assets_usd=0.0,
            staked_for_security_usd=0.0, oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
            security_budget_monthly_usd=1_000.0,
        )
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["security_ratio"], 0.01, places=5)

    def test_security_ratio_zero_when_tvs_zero(self):
        p = {k: 0.0 if k != "name" else "Z" for k in [
            "name", "tvl_usd", "bridged_assets_usd", "insured_assets_usd",
            "staked_for_security_usd", "oracle_secured_usd", "validator_set_value_usd",
            "protocol_revenue_monthly_usd", "security_budget_monthly_usd"
        ]}
        result = self.analyzer.analyze([p], {})
        self.assertAlmostEqual(result["protocols"][0]["security_ratio"], 0.0, places=6)

    def test_security_ratio_increases_with_budget(self):
        p_low  = _make_protocol(security_budget_monthly_usd=100.0)
        p_high = _make_protocol(security_budget_monthly_usd=10_000_000.0)
        r_low  = self.analyzer.analyze([p_low],  {})["protocols"][0]["security_ratio"]
        r_high = self.analyzer.analyze([p_high], {})["protocols"][0]["security_ratio"]
        self.assertGreater(r_high, r_low)


# ---------------------------------------------------------------------------
# 6. Security labels
# ---------------------------------------------------------------------------

class TestSecurityLabels(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def _get_label(self, **kwargs):
        result = self.analyzer.analyze([_make_protocol(**kwargs)], {})
        return result["protocols"][0]["security_label"]

    def test_label_valid_values(self):
        valid = {"FORTRESS", "SECURE", "ADEQUATE", "UNDERFUNDED", "CRITICAL"}
        lbl = self._get_label()
        self.assertIn(lbl, valid)

    def test_fortress_label_for_very_secure_protocol(self):
        # High security budget relative to TVS, revenue covers it
        lbl = self._get_label(
            security_budget_monthly_usd=5_000_000.0,
            protocol_revenue_monthly_usd=10_000_000.0,
            staked_for_security_usd=10_000_000.0,  # low restaking share
            tvl_usd=500_000_000.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertIn(lbl, {"FORTRESS", "SECURE"})

    def test_critical_label_for_zero_budget(self):
        lbl = self._get_label(
            security_budget_monthly_usd=0.0,
            protocol_revenue_monthly_usd=0.0,
            staked_for_security_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertIn(lbl, {"CRITICAL", "UNDERFUNDED"})

    def test_weak_protocol_not_fortress(self):
        result = self.analyzer.analyze([_make_weak_protocol()], {})
        lbl = result["protocols"][0]["security_label"]
        self.assertNotEqual(lbl, "FORTRESS")

    def test_all_label_values_covered_in_thresholds(self):
        valid = {"FORTRESS", "SECURE", "ADEQUATE", "UNDERFUNDED", "CRITICAL"}
        labels_in_thresholds = {lbl for _, lbl in ProtocolTotalValueSecuredAnalyzer._LABEL_THRESHOLDS}
        labels_in_thresholds.add("CRITICAL")  # default fallback
        self.assertEqual(labels_in_thresholds, valid)


# ---------------------------------------------------------------------------
# 7. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def _get_flags(self, **kwargs):
        result = self.analyzer.analyze([_make_protocol(**kwargs)], {})
        return result["protocols"][0]["flags"]

    def test_low_security_budget_flag_triggered(self):
        # security_ratio < 0.001: annual_budget / TVS < 0.001
        # TVS ≈ 500M+50M+20M+100M+200M+80M = 950M; budget need < 950M*0.001/12 ≈ 79167/month
        # Use 1000/month on 950M TVS → ratio = 12000/950M ≈ 0.0000126 < 0.001
        flags = self._get_flags(security_budget_monthly_usd=1_000.0)
        self.assertIn("LOW_SECURITY_BUDGET", flags)

    def test_low_security_budget_flag_not_triggered(self):
        # budget 10M/month on ~950M TVS → ratio = 120M/950M ≈ 0.126 > 0.001
        flags = self._get_flags(security_budget_monthly_usd=10_000_000.0)
        self.assertNotIn("LOW_SECURITY_BUDGET", flags)

    def test_oracle_systemic_flag_triggered(self):
        # oracle_secured > 10x TVL: tvl=1M, oracle_secured=11M
        flags = self._get_flags(
            tvl_usd=1_000_000.0,
            oracle_secured_usd=11_000_000.0,
        )
        self.assertIn("ORACLE_SYSTEMIC", flags)

    def test_oracle_systemic_flag_not_triggered(self):
        # oracle_secured = 5x TVL: tvl=1M, oracle=5M < 10M
        flags = self._get_flags(
            tvl_usd=1_000_000.0,
            oracle_secured_usd=5_000_000.0,
        )
        self.assertNotIn("ORACLE_SYSTEMIC", flags)

    def test_oracle_systemic_no_crash_zero_tvl(self):
        flags = self._get_flags(tvl_usd=0.0, oracle_secured_usd=1_000_000.0)
        # Should not crash; oracle_systemic not triggered when tvl=0
        self.assertNotIn("ORACLE_SYSTEMIC", flags)

    def test_high_tvs_ratio_flag_triggered(self):
        # tvs_to_tvl_ratio > 5: tvl=100, all others = 600 → total=700, ratio=7
        flags = self._get_flags(
            tvl_usd=100.0,
            bridged_assets_usd=600.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=0.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertIn("HIGH_TVS_RATIO", flags)

    def test_high_tvs_ratio_flag_not_triggered(self):
        # tvs_to_tvl_ratio = 1: only tvl, others=0
        flags = self._get_flags(
            tvl_usd=1_000_000.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=0.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertNotIn("HIGH_TVS_RATIO", flags)

    def test_revenue_covers_security_flag_triggered(self):
        flags = self._get_flags(
            protocol_revenue_monthly_usd=5_000_000.0,
            security_budget_monthly_usd=3_000_000.0,
        )
        self.assertIn("REVENUE_COVERS_SECURITY", flags)

    def test_revenue_covers_security_flag_not_triggered_when_equal(self):
        # equal — flag requires revenue > budget (strict)
        flags = self._get_flags(
            protocol_revenue_monthly_usd=3_000_000.0,
            security_budget_monthly_usd=3_000_000.0,
        )
        self.assertNotIn("REVENUE_COVERS_SECURITY", flags)

    def test_revenue_covers_security_flag_not_triggered_less(self):
        flags = self._get_flags(
            protocol_revenue_monthly_usd=1_000_000.0,
            security_budget_monthly_usd=3_000_000.0,
        )
        self.assertNotIn("REVENUE_COVERS_SECURITY", flags)

    def test_restaking_dependent_flag_triggered(self):
        # staked > 50% of TVS
        # TVS = tvl(100) + staked(600) + others(0) = 700; staked/tvs = 600/700 > 0.5
        flags = self._get_flags(
            tvl_usd=100.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=600.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertIn("RESTAKING_DEPENDENT", flags)

    def test_restaking_dependent_flag_not_triggered(self):
        # staked = 10% of TVS
        flags = self._get_flags(
            tvl_usd=900.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=100.0,
            oracle_secured_usd=0.0,
            validator_set_value_usd=0.0,
        )
        self.assertNotIn("RESTAKING_DEPENDENT", flags)

    def test_multiple_flags_can_fire(self):
        # Low budget + oracle systemic
        flags = self._get_flags(
            security_budget_monthly_usd=1.0,
            tvl_usd=1_000_000.0,
            oracle_secured_usd=20_000_000.0,
        )
        self.assertIn("LOW_SECURITY_BUDGET", flags)
        self.assertIn("ORACLE_SYSTEMIC", flags)

    def test_flags_is_always_list(self):
        result = self.analyzer.analyze([_make_protocol()], {})
        self.assertIsInstance(result["protocols"][0]["flags"], list)


# ---------------------------------------------------------------------------
# 8. Attack cost estimate
# ---------------------------------------------------------------------------

class TestAttackCostEstimate(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def test_attack_cost_positive(self):
        result = self.analyzer.analyze([_make_protocol()], {})
        self.assertGreater(result["protocols"][0]["attack_cost_estimate_usd"], 0.0)

    def test_attack_cost_increases_with_staking(self):
        p_low  = _make_protocol(staked_for_security_usd=0.0, validator_set_value_usd=0.0)
        p_high = _make_protocol(staked_for_security_usd=1_000_000_000.0)
        c_low  = self.analyzer.analyze([p_low],  {})["protocols"][0]["attack_cost_estimate_usd"]
        c_high = self.analyzer.analyze([p_high], {})["protocols"][0]["attack_cost_estimate_usd"]
        self.assertGreater(c_high, c_low)

    def test_attack_cost_minimum_is_tvl_floor(self):
        # With zero staking and zero budget, floor = 1% of TVL
        p = _make_protocol(
            tvl_usd=10_000_000.0,
            staked_for_security_usd=0.0,
            validator_set_value_usd=0.0,
            security_budget_monthly_usd=0.0,
        )
        result = self.analyzer.analyze([p], {})
        attack_cost = result["protocols"][0]["attack_cost_estimate_usd"]
        self.assertGreaterEqual(attack_cost, 10_000_000.0 * 0.01)

    def test_attack_cost_zero_tvl_no_crash(self):
        p = _make_protocol(tvl_usd=0.0, staked_for_security_usd=0.0,
                           validator_set_value_usd=0.0, security_budget_monthly_usd=0.0)
        result = self.analyzer.analyze([p], {})
        self.assertGreaterEqual(result["protocols"][0]["attack_cost_estimate_usd"], 0.0)


# ---------------------------------------------------------------------------
# 9. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def test_most_secure_is_string(self):
        result = self.analyzer.analyze([_make_protocol(), _make_weak_protocol()], {})
        self.assertIsInstance(result["aggregates"]["most_secure"], str)

    def test_least_secure_is_string(self):
        result = self.analyzer.analyze([_make_protocol(), _make_weak_protocol()], {})
        self.assertIsInstance(result["aggregates"]["least_secure"], str)

    def test_most_secure_in_protocol_names(self):
        allocs = [_make_protocol(name="Alpha"), _make_weak_protocol(name="Beta")]
        result = self.analyzer.analyze(allocs, {})
        self.assertIn(result["aggregates"]["most_secure"], {"Alpha", "Beta"})

    def test_total_ecosystem_tvs_sums_all(self):
        p1 = _make_protocol(name="P1", tvl_usd=100.0, bridged_assets_usd=0.0,
                            insured_assets_usd=0.0, staked_for_security_usd=0.0,
                            oracle_secured_usd=0.0, validator_set_value_usd=0.0)
        p2 = _make_protocol(name="P2", tvl_usd=200.0, bridged_assets_usd=0.0,
                            insured_assets_usd=0.0, staked_for_security_usd=0.0,
                            oracle_secured_usd=0.0, validator_set_value_usd=0.0)
        result = self.analyzer.analyze([p1, p2], {})
        self.assertAlmostEqual(result["aggregates"]["total_ecosystem_tvs"], 300.0, places=1)

    def test_total_protocols_count(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(6)]
        result = self.analyzer.analyze(protocols, {})
        self.assertEqual(result["aggregates"]["total_protocols"], 6)

    def test_fortress_count_accurate(self):
        # Ensure at least the counting works
        result = self.analyzer.analyze([_make_protocol(), _make_weak_protocol()], {})
        fc = result["aggregates"]["fortress_count"]
        self.assertGreaterEqual(fc, 0)
        self.assertLessEqual(fc, 2)

    def test_average_security_ratio_positive_for_funded(self):
        result = self.analyzer.analyze([_make_protocol()], {})
        self.assertGreater(result["aggregates"]["average_security_ratio"], 0.0)

    def test_average_security_ratio_is_mean(self):
        # Two identical protocols: average should equal individual ratio
        p1 = _make_protocol(name="P1")
        p2 = _make_protocol(name="P2")
        result = self.analyzer.analyze([p1, p2], {})
        ratio_1 = result["protocols"][0]["security_ratio"]
        ratio_2 = result["protocols"][1]["security_ratio"]
        expected_avg = (ratio_1 + ratio_2) / 2.0
        self.assertAlmostEqual(result["aggregates"]["average_security_ratio"], expected_avg, places=6)

    def test_single_protocol_aggregates(self):
        result = self.analyzer.analyze([_make_protocol(name="Solo")], {})
        agg = result["aggregates"]
        self.assertEqual(agg["most_secure"], "Solo")
        self.assertEqual(agg["least_secure"], "Solo")
        self.assertEqual(agg["total_protocols"], 1)


# ---------------------------------------------------------------------------
# 10. Log persistence
# ---------------------------------------------------------------------------

class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_tvs_log.json")

    def test_no_log_when_persist_false(self):
        cfg = {"log_path": self.log_path, "persist": False}
        self.analyzer.analyze([_make_protocol()], cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_written_when_persist_true(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([_make_protocol()], cfg)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([_make_protocol()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_one_entry_after_one_call(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([_make_protocol()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        cfg = {"log_path": self.log_path, "persist": True}
        for _ in range(5):
            self.analyzer.analyze([_make_protocol()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_caps_at_100(self):
        cfg = {"log_path": self.log_path, "persist": True}
        for _ in range(115):
            self.analyzer.analyze([_make_protocol()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_contains_status(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([_make_protocol()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("status", data[0])

    def test_atomic_write_no_temp_files_remaining(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([_make_protocol()], cfg)
        tmp_files = [f for f in os.listdir(self.tmpdir)
                     if f.startswith(".tvs_analyzer_tmp_")]
        self.assertEqual(len(tmp_files), 0)

    def test_empty_input_persisted_when_persist(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.analyzer.analyze([], cfg)
        self.assertTrue(os.path.exists(self.log_path))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def test_all_zero_inputs_no_crash(self):
        p = {"name": "Zero"}
        result = self.analyzer.analyze([p], {})
        self.assertEqual(result["status"], "ok")

    def test_large_values_no_crash(self):
        p = _make_protocol(
            tvl_usd=1e15,
            oracle_secured_usd=1e15,
            security_budget_monthly_usd=1e12,
        )
        result = self.analyzer.analyze([p], {})
        self.assertEqual(result["status"], "ok")

    def test_name_preserved(self):
        result = self.analyzer.analyze([_make_protocol(name="Wonderland")], {})
        self.assertEqual(result["protocols"][0]["name"], "Wonderland")

    def test_50_protocols_no_crash(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(50)]
        result = self.analyzer.analyze(protocols, {})
        self.assertEqual(len(result["protocols"]), 50)

    def test_adequacy_score_always_in_range(self):
        test_cases = [
            _make_protocol(),
            _make_weak_protocol(),
            {"name": "Bare"},
        ]
        for p in test_cases:
            result = self.analyzer.analyze([p], {})
            score = result["protocols"][0]["security_adequacy_score"]
            self.assertGreaterEqual(score, 0.0, f"Score below 0 for {p.get('name')}")
            self.assertLessEqual(score, 100.0, f"Score above 100 for {p.get('name')}")

    def test_protocol_with_all_fields_none_like_missing_uses_defaults(self):
        p = {"name": "Minimal", "tvl_usd": 1_000_000.0}
        result = self.analyzer.analyze([p], {})
        self.assertEqual(result["status"], "ok")

    def test_tvs_ratio_high_with_oracle_heavy(self):
        p = _make_protocol(
            tvl_usd=1_000_000.0,
            bridged_assets_usd=0.0,
            insured_assets_usd=0.0,
            staked_for_security_usd=0.0,
            oracle_secured_usd=100_000_000.0,
            validator_set_value_usd=0.0,
        )
        result = self.analyzer.analyze([p], {})
        self.assertGreater(result["protocols"][0]["tvs_to_tvl_ratio"], 5.0)
        self.assertIn("HIGH_TVS_RATIO", result["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# 12. Score monotonicity
# ---------------------------------------------------------------------------

class TestScoreMonotonicity(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolTotalValueSecuredAnalyzer()

    def _score(self, **kwargs):
        result = self.analyzer.analyze([_make_protocol(**kwargs)], {})
        return result["protocols"][0]["security_adequacy_score"]

    def test_higher_security_budget_higher_score(self):
        s_low  = self._score(security_budget_monthly_usd=100.0)
        s_high = self._score(security_budget_monthly_usd=50_000_000.0)
        self.assertGreater(s_high, s_low)

    def test_higher_revenue_coverage_higher_score(self):
        s_low  = self._score(protocol_revenue_monthly_usd=100.0,
                              security_budget_monthly_usd=3_000_000.0)
        s_high = self._score(protocol_revenue_monthly_usd=100_000_000.0,
                              security_budget_monthly_usd=3_000_000.0)
        self.assertGreater(s_high, s_low)


if __name__ == "__main__":
    unittest.main()
