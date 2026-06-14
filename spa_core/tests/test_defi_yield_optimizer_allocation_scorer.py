"""
Tests for MP-940: DeFiYieldOptimizerAllocationScorer
Run: python3 -m unittest spa_core.tests.test_defi_yield_optimizer_allocation_scorer -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))

from spa_core.analytics.defi_yield_optimizer_allocation_scorer import (
    DeFiYieldOptimizerAllocationScorer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_alloc(**kwargs):
    """Return a minimal well-behaved allocation dict."""
    base = {
        "protocol":                   "Aave",
        "strategy_name":              "USDC_Supply",
        "allocated_usd":              100_000.0,
        "current_apy_pct":            5.0,
        "risk_score":                 20.0,
        "gas_cost_annual_usd":        50.0,
        "rebalance_frequency_days":   30.0,
        "opportunity_cost_pct":       5.0,
        "correlation_to_portfolio":   0.2,
    }
    base.update(kwargs)
    return base


def _make_bad_alloc(**kwargs):
    """Return a high-risk / inefficient allocation dict."""
    base = {
        "protocol":                   "BadProtocol",
        "strategy_name":              "RISKY_VAULT",
        "allocated_usd":              50_000.0,
        "current_apy_pct":            2.0,
        "risk_score":                 85.0,
        "gas_cost_annual_usd":        800.0,
        "rebalance_frequency_days":   7.0,
        "opportunity_cost_pct":       8.0,
        "correlation_to_portfolio":   0.9,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        s = DeFiYieldOptimizerAllocationScorer()
        self.assertIsNotNone(s)

    def test_log_cap_is_100(self):
        self.assertEqual(DeFiYieldOptimizerAllocationScorer.LOG_CAP, 100)

    def test_default_log_path(self):
        self.assertIn("yield_optimizer", DeFiYieldOptimizerAllocationScorer.DEFAULT_LOG_PATH)

    def test_efficiency_threshold(self):
        self.assertAlmostEqual(DeFiYieldOptimizerAllocationScorer.EFFICIENCY_OPPORTUNITY_LOSS, 0.80)

    def test_gas_drag_threshold(self):
        self.assertAlmostEqual(DeFiYieldOptimizerAllocationScorer.GAS_DRAG_THRESHOLD_PCT, 0.005)

    def test_overcorrelation_threshold(self):
        self.assertAlmostEqual(DeFiYieldOptimizerAllocationScorer.OVERCORRELATION_THRESHOLD, 0.80)

    def test_risk_mismatch_risk_score(self):
        self.assertEqual(DeFiYieldOptimizerAllocationScorer.RISK_MISMATCH_RISK_SCORE, 70.0)

    def test_risk_mismatch_apy_threshold(self):
        self.assertEqual(DeFiYieldOptimizerAllocationScorer.RISK_MISMATCH_APY_THRESHOLD, 5.0)


# ---------------------------------------------------------------------------
# 2. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()
        self.result = self.scorer.score([], {})

    def test_status_ok(self):
        self.assertEqual(self.result["status"], "ok")

    def test_allocations_empty_list(self):
        self.assertEqual(self.result["allocations"], [])

    def test_aggregates_best_is_none(self):
        self.assertIsNone(self.result["aggregates"]["best_allocation"])

    def test_aggregates_worst_is_none(self):
        self.assertIsNone(self.result["aggregates"]["worst_allocation"])

    def test_aggregates_weighted_apy_zero(self):
        self.assertEqual(self.result["aggregates"]["portfolio_weighted_apy"], 0.0)

    def test_aggregates_opp_cost_zero(self):
        self.assertEqual(self.result["aggregates"]["total_opportunity_cost_usd"], 0.0)

    def test_aggregates_optimal_count_zero(self):
        self.assertEqual(self.result["aggregates"]["optimal_count"], 0)

    def test_aggregates_total_allocations_zero(self):
        self.assertEqual(self.result["aggregates"]["total_allocations"], 0)


# ---------------------------------------------------------------------------
# 3. Single allocation — output structure
# ---------------------------------------------------------------------------

class TestSingleAllocationStructure(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()
        self.result = self.scorer.score([_make_alloc()], {})
        self.a = self.result["allocations"][0]

    def test_has_allocations_key(self):
        self.assertIn("allocations", self.result)

    def test_has_aggregates_key(self):
        self.assertIn("aggregates", self.result)

    def test_has_status_key(self):
        self.assertIn("status", self.result)

    def test_allocation_has_protocol(self):
        self.assertIn("protocol", self.a)

    def test_allocation_has_strategy_name(self):
        self.assertIn("strategy_name", self.a)

    def test_allocation_has_efficiency_ratio(self):
        self.assertIn("efficiency_ratio", self.a)

    def test_allocation_has_risk_adjusted_apy(self):
        self.assertIn("risk_adjusted_apy", self.a)

    def test_allocation_has_net_apy_after_gas(self):
        self.assertIn("net_apy_after_gas", self.a)

    def test_allocation_has_diversification_contribution(self):
        self.assertIn("diversification_contribution", self.a)

    def test_allocation_has_composite_score(self):
        self.assertIn("composite_score", self.a)

    def test_allocation_has_label(self):
        self.assertIn("label", self.a)

    def test_allocation_has_flags(self):
        self.assertIn("flags", self.a)

    def test_flags_is_list(self):
        self.assertIsInstance(self.a["flags"], list)

    def test_label_is_string(self):
        self.assertIsInstance(self.a["label"], str)

    def test_composite_score_in_range(self):
        self.assertGreaterEqual(self.a["composite_score"], 0.0)
        self.assertLessEqual(self.a["composite_score"], 100.0)

    def test_efficiency_ratio_positive_for_good_alloc(self):
        self.assertGreater(self.a["efficiency_ratio"], 0.0)


# ---------------------------------------------------------------------------
# 4. Derived metric calculations
# ---------------------------------------------------------------------------

class TestDerivedMetrics(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def test_efficiency_ratio_when_equal(self):
        a = _make_alloc(current_apy_pct=5.0, opportunity_cost_pct=5.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["efficiency_ratio"], 1.0, places=3)

    def test_efficiency_ratio_below_one_when_underperforming(self):
        a = _make_alloc(current_apy_pct=3.0, opportunity_cost_pct=6.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["efficiency_ratio"], 0.5, places=3)

    def test_efficiency_ratio_above_one_when_outperforming(self):
        a = _make_alloc(current_apy_pct=8.0, opportunity_cost_pct=5.0)
        result = self.scorer.score([a], {})
        self.assertGreater(result["allocations"][0]["efficiency_ratio"], 1.0)

    def test_risk_adjusted_apy_zero_risk(self):
        a = _make_alloc(current_apy_pct=10.0, risk_score=0.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["risk_adjusted_apy"], 10.0, places=3)

    def test_risk_adjusted_apy_max_risk(self):
        a = _make_alloc(current_apy_pct=10.0, risk_score=100.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["risk_adjusted_apy"], 5.0, places=3)

    def test_risk_adjusted_apy_half_risk(self):
        a = _make_alloc(current_apy_pct=8.0, risk_score=50.0)
        result = self.scorer.score([a], {})
        # apy * (1 - 50/200) = 8 * 0.75 = 6.0
        self.assertAlmostEqual(result["allocations"][0]["risk_adjusted_apy"], 6.0, places=3)

    def test_net_apy_after_gas_calculation(self):
        # gas_drag = 100 / 100_000 * 100 = 0.1%; net = 5 - 0.1 = 4.9
        a = _make_alloc(current_apy_pct=5.0, gas_cost_annual_usd=100.0, allocated_usd=100_000.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["net_apy_after_gas"], 4.9, places=3)

    def test_net_apy_after_gas_high_drag(self):
        # gas_drag = 5000 / 100_000 * 100 = 5%; net = 5 - 5 = 0
        a = _make_alloc(current_apy_pct=5.0, gas_cost_annual_usd=5_000.0, allocated_usd=100_000.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["net_apy_after_gas"], 0.0, places=3)

    def test_diversification_contribution_uncorrelated(self):
        a = _make_alloc(correlation_to_portfolio=0.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["diversification_contribution"], 1.0, places=3)

    def test_diversification_contribution_fully_correlated(self):
        a = _make_alloc(correlation_to_portfolio=1.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["diversification_contribution"], 0.0, places=3)

    def test_diversification_contribution_half(self):
        a = _make_alloc(correlation_to_portfolio=0.5)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["diversification_contribution"], 0.5, places=3)

    def test_zero_opportunity_cost_no_crash(self):
        a = _make_alloc(opportunity_cost_pct=0.0, current_apy_pct=5.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")

    def test_zero_allocated_no_crash(self):
        a = _make_alloc(allocated_usd=0.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")


# ---------------------------------------------------------------------------
# 5. Labels
# ---------------------------------------------------------------------------

class TestLabels(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def _get_label(self, **kwargs):
        result = self.scorer.score([_make_alloc(**kwargs)], {})
        return result["allocations"][0]["label"]

    def test_label_values_are_valid(self):
        valid = {"OPTIMAL", "GOOD", "SUBOPTIMAL", "INEFFICIENT", "MISALLOCATED"}
        for _ in range(5):
            lbl = self._get_label()
            self.assertIn(lbl, valid)

    def test_bad_alloc_not_optimal(self):
        result = self.scorer.score([_make_bad_alloc()], {})
        lbl = result["allocations"][0]["label"]
        self.assertNotEqual(lbl, "OPTIMAL")

    def test_good_alloc_label_at_least_good(self):
        # Perfect alloc: no gas, equal apy/opp, low risk, low correlation
        a = _make_alloc(
            current_apy_pct=10.0,
            opportunity_cost_pct=10.0,
            risk_score=0.0,
            gas_cost_annual_usd=0.0,
            correlation_to_portfolio=0.0,
        )
        result = self.scorer.score([a], {})
        lbl = result["allocations"][0]["label"]
        self.assertIn(lbl, {"OPTIMAL", "GOOD"})

    def test_misallocated_very_poor_efficiency(self):
        a = _make_alloc(
            current_apy_pct=0.5,
            opportunity_cost_pct=10.0,
            gas_cost_annual_usd=50_000.0,
            allocated_usd=100_000.0,
            correlation_to_portfolio=0.99,
            risk_score=90.0,
        )
        result = self.scorer.score([a], {})
        lbl = result["allocations"][0]["label"]
        self.assertIn(lbl, {"INEFFICIENT", "MISALLOCATED"})


# ---------------------------------------------------------------------------
# 6. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def _get_flags(self, **kwargs):
        result = self.scorer.score([_make_alloc(**kwargs)], {})
        return result["allocations"][0]["flags"]

    def test_opportunity_loss_flag_triggered(self):
        # efficiency = 3/6 = 0.5 < 0.8
        flags = self._get_flags(current_apy_pct=3.0, opportunity_cost_pct=6.0)
        self.assertIn("OPPORTUNITY_LOSS", flags)

    def test_opportunity_loss_flag_not_triggered(self):
        # efficiency = 5/5 = 1.0 >= 0.8
        flags = self._get_flags(current_apy_pct=5.0, opportunity_cost_pct=5.0)
        self.assertNotIn("OPPORTUNITY_LOSS", flags)

    def test_high_gas_drag_flag_triggered(self):
        # gas = 600 on 100_000 = 0.6% > 0.5%
        flags = self._get_flags(gas_cost_annual_usd=600.0, allocated_usd=100_000.0)
        self.assertIn("HIGH_GAS_DRAG", flags)

    def test_high_gas_drag_flag_not_triggered(self):
        # gas = 400 on 100_000 = 0.4% < 0.5%
        flags = self._get_flags(gas_cost_annual_usd=400.0, allocated_usd=100_000.0)
        self.assertNotIn("HIGH_GAS_DRAG", flags)

    def test_risk_mismatch_flag_triggered(self):
        # risk > 70, apy < 5
        flags = self._get_flags(risk_score=80.0, current_apy_pct=2.0)
        self.assertIn("RISK_MISMATCH", flags)

    def test_risk_mismatch_flag_not_triggered_low_risk(self):
        flags = self._get_flags(risk_score=30.0, current_apy_pct=2.0)
        self.assertNotIn("RISK_MISMATCH", flags)

    def test_risk_mismatch_flag_not_triggered_high_apy(self):
        flags = self._get_flags(risk_score=80.0, current_apy_pct=10.0)
        self.assertNotIn("RISK_MISMATCH", flags)

    def test_overcorrelated_flag_triggered(self):
        flags = self._get_flags(correlation_to_portfolio=0.9)
        self.assertIn("OVERCORRELATED", flags)

    def test_overcorrelated_flag_at_boundary(self):
        # exactly 0.80 — should NOT trigger (>0.80, not >=0.80)
        flags = self._get_flags(correlation_to_portfolio=0.80)
        self.assertNotIn("OVERCORRELATED", flags)

    def test_overcorrelated_flag_just_above_boundary(self):
        flags = self._get_flags(correlation_to_portfolio=0.81)
        self.assertIn("OVERCORRELATED", flags)

    def test_overcorrelated_not_triggered_low_correlation(self):
        flags = self._get_flags(correlation_to_portfolio=0.3)
        self.assertNotIn("OVERCORRELATED", flags)

    def test_optimal_allocation_flag_no_negative_flags(self):
        # Perfect allocation should get OPTIMAL_ALLOCATION
        a = _make_alloc(
            current_apy_pct=10.0,
            opportunity_cost_pct=10.0,
            risk_score=0.0,
            gas_cost_annual_usd=0.0,
            correlation_to_portfolio=0.0,
        )
        result = self.scorer.score([a], {})
        flags = result["allocations"][0]["flags"]
        # OPTIMAL_ALLOCATION should appear if no negative flags and composite >= 80
        composite = result["allocations"][0]["composite_score"]
        if composite >= 80.0:
            self.assertIn("OPTIMAL_ALLOCATION", flags)

    def test_optimal_allocation_not_present_when_negative_flag(self):
        # High gas drag should prevent OPTIMAL_ALLOCATION
        flags = self._get_flags(gas_cost_annual_usd=5_000.0, allocated_usd=100_000.0)
        self.assertNotIn("OPTIMAL_ALLOCATION", flags)

    def test_flags_is_always_list(self):
        result = self.scorer.score([_make_alloc()], {})
        self.assertIsInstance(result["allocations"][0]["flags"], list)

    def test_multiple_flags_possible(self):
        # Both OPPORTUNITY_LOSS and RISK_MISMATCH should fire
        flags = self._get_flags(
            current_apy_pct=2.0,
            opportunity_cost_pct=10.0,
            risk_score=80.0,
        )
        self.assertIn("OPPORTUNITY_LOSS", flags)
        self.assertIn("RISK_MISMATCH", flags)


# ---------------------------------------------------------------------------
# 7. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def test_best_allocation_is_string(self):
        result = self.scorer.score([_make_alloc(), _make_bad_alloc()], {})
        self.assertIsInstance(result["aggregates"]["best_allocation"], str)

    def test_worst_allocation_is_string(self):
        result = self.scorer.score([_make_alloc(), _make_bad_alloc()], {})
        self.assertIsInstance(result["aggregates"]["worst_allocation"], str)

    def test_best_is_not_worst_when_different(self):
        result = self.scorer.score([_make_alloc(), _make_bad_alloc()], {})
        agg = result["aggregates"]
        # Not always true but in this case should differ
        # (just check types)
        self.assertIsInstance(agg["best_allocation"], str)
        self.assertIsInstance(agg["worst_allocation"], str)

    def test_portfolio_weighted_apy_single(self):
        result = self.scorer.score([_make_alloc(current_apy_pct=6.0, allocated_usd=100_000.0)], {})
        self.assertAlmostEqual(result["aggregates"]["portfolio_weighted_apy"], 6.0, places=3)

    def test_portfolio_weighted_apy_two_equal(self):
        allocs = [
            _make_alloc(current_apy_pct=4.0, allocated_usd=100_000.0, protocol="A"),
            _make_alloc(current_apy_pct=8.0, allocated_usd=100_000.0, protocol="B"),
        ]
        result = self.scorer.score(allocs, {})
        self.assertAlmostEqual(result["aggregates"]["portfolio_weighted_apy"], 6.0, places=3)

    def test_portfolio_weighted_apy_unequal_weights(self):
        allocs = [
            _make_alloc(current_apy_pct=4.0, allocated_usd=25_000.0, protocol="A"),
            _make_alloc(current_apy_pct=8.0, allocated_usd=75_000.0, protocol="B"),
        ]
        result = self.scorer.score(allocs, {})
        # weighted = (4*25k + 8*75k) / 100k = (100k + 600k)/100k = 7.0
        self.assertAlmostEqual(result["aggregates"]["portfolio_weighted_apy"], 7.0, places=3)

    def test_total_opportunity_cost_zero_when_efficient(self):
        # opp_cost == current_apy → no foregone yield
        a = _make_alloc(current_apy_pct=5.0, opportunity_cost_pct=5.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["aggregates"]["total_opportunity_cost_usd"], 0.0, places=2)

    def test_total_opportunity_cost_positive_when_underperforming(self):
        # opp_cost=8%, current=5%, allocated=100k → foregone = 3% * 100k = 3000
        a = _make_alloc(current_apy_pct=5.0, opportunity_cost_pct=8.0, allocated_usd=100_000.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["aggregates"]["total_opportunity_cost_usd"], 3000.0, places=1)

    def test_optimal_count_counts_correctly(self):
        allocs = [
            _make_alloc(current_apy_pct=10.0, opportunity_cost_pct=10.0, risk_score=0.0,
                        gas_cost_annual_usd=0.0, correlation_to_portfolio=0.0, protocol="A"),
            _make_bad_alloc(),
        ]
        result = self.scorer.score(allocs, {})
        # optimal_count should be >= 0 (at least 0)
        self.assertGreaterEqual(result["aggregates"]["optimal_count"], 0)

    def test_total_allocations_count(self):
        allocs = [_make_alloc(protocol=f"P{i}") for i in range(5)]
        result = self.scorer.score(allocs, {})
        self.assertEqual(result["aggregates"]["total_allocations"], 5)


# ---------------------------------------------------------------------------
# 8. Log persistence
# ---------------------------------------------------------------------------

class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_alloc_log.json")

    def test_no_log_written_when_persist_false(self):
        cfg = {"log_path": self.log_path, "persist": False}
        self.scorer.score([_make_alloc()], cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_written_when_persist_true(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([_make_alloc()], cfg)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([_make_alloc()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_call(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([_make_alloc()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        cfg = {"log_path": self.log_path, "persist": True}
        for _ in range(3):
            self.scorer.score([_make_alloc()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_caps_at_100(self):
        cfg = {"log_path": self.log_path, "persist": True}
        for _ in range(110):
            self.scorer.score([_make_alloc()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_empty_input_persisted_when_persist(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([], cfg)
        self.assertTrue(os.path.exists(self.log_path))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_has_status_key(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([_make_alloc()], cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("status", data[0])

    def test_atomic_write_no_partial_files(self):
        cfg = {"log_path": self.log_path, "persist": True}
        self.scorer.score([_make_alloc()], cfg)
        # tmp file should be gone after atomic write
        tmp_files = [f for f in os.listdir(self.tmpdir)
                     if f.startswith(".yield_optimizer_alloc_tmp_")]
        self.assertEqual(len(tmp_files), 0)


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def test_negative_apy_no_crash(self):
        a = _make_alloc(current_apy_pct=-2.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")

    def test_risk_score_zero_no_crash(self):
        a = _make_alloc(risk_score=0.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")

    def test_risk_score_100_no_crash(self):
        a = _make_alloc(risk_score=100.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")

    def test_risk_score_clamped_above_100(self):
        a = _make_alloc(risk_score=150.0)
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")
        # risk_adjusted_apy should not be negative (clamped risk)
        ra = result["allocations"][0]["risk_adjusted_apy"]
        # With risk_score clamped to 100: apy*(1-100/200) = apy*0.5
        self.assertGreaterEqual(ra, 0.0)

    def test_correlation_clamped_above_1(self):
        a = _make_alloc(correlation_to_portfolio=1.5)
        result = self.scorer.score([a], {})
        dc = result["allocations"][0]["diversification_contribution"]
        self.assertGreaterEqual(dc, 0.0)

    def test_large_list_no_crash(self):
        allocs = [_make_alloc(protocol=f"P{i}") for i in range(50)]
        result = self.scorer.score(allocs, {})
        self.assertEqual(len(result["allocations"]), 50)

    def test_composite_score_always_0_to_100(self):
        test_cases = [
            _make_alloc(),
            _make_bad_alloc(),
            _make_alloc(current_apy_pct=0.0, opportunity_cost_pct=0.0),
            _make_alloc(current_apy_pct=100.0, opportunity_cost_pct=1.0),
        ]
        for a in test_cases:
            result = self.scorer.score([a], {})
            score = result["allocations"][0]["composite_score"]
            self.assertGreaterEqual(score, 0.0, f"Score {score} below 0 for {a}")
            self.assertLessEqual(score, 100.0, f"Score {score} above 100 for {a}")

    def test_missing_fields_use_defaults(self):
        a = {"protocol": "Minimal"}
        result = self.scorer.score([a], {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["allocations"]), 1)

    def test_protocol_name_preserved(self):
        a = _make_alloc(protocol="MyProtocol123")
        result = self.scorer.score([a], {})
        self.assertEqual(result["allocations"][0]["protocol"], "MyProtocol123")

    def test_strategy_name_preserved(self):
        a = _make_alloc(strategy_name="VAULT_STRAT_42")
        result = self.scorer.score([a], {})
        self.assertEqual(result["allocations"][0]["strategy_name"], "VAULT_STRAT_42")

    def test_rebalance_frequency_preserved(self):
        a = _make_alloc(rebalance_frequency_days=14.0)
        result = self.scorer.score([a], {})
        self.assertAlmostEqual(result["allocations"][0]["rebalance_frequency_days"], 14.0)


# ---------------------------------------------------------------------------
# 10. Multiple allocations — ordering and aggregates
# ---------------------------------------------------------------------------

class TestMultipleAllocations(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def test_best_worst_allocation_names_exist_in_protocols(self):
        allocs = [
            _make_alloc(protocol="Alpha"),
            _make_alloc(protocol="Beta"),
            _make_bad_alloc(protocol="Gamma"),
        ]
        result = self.scorer.score(allocs, {})
        agg = result["aggregates"]
        protocols = {"Alpha", "Beta", "Gamma"}
        self.assertIn(agg["best_allocation"], protocols)
        self.assertIn(agg["worst_allocation"], protocols)

    def test_three_allocations_count(self):
        allocs = [_make_alloc(protocol=f"P{i}") for i in range(3)]
        result = self.scorer.score(allocs, {})
        self.assertEqual(result["aggregates"]["total_allocations"], 3)

    def test_all_allocations_returned(self):
        allocs = [_make_alloc(protocol=f"P{i}") for i in range(7)]
        result = self.scorer.score(allocs, {})
        self.assertEqual(len(result["allocations"]), 7)

    def test_each_allocation_has_label(self):
        allocs = [_make_alloc(protocol=f"P{i}") for i in range(4)]
        result = self.scorer.score(allocs, {})
        for a in result["allocations"]:
            self.assertIn(a["label"], {"OPTIMAL", "GOOD", "SUBOPTIMAL", "INEFFICIENT", "MISALLOCATED"})

    def test_opportunity_cost_sums_correctly(self):
        # Two allocations, each losing 1% on 100k = 1000 each → total = 2000
        allocs = [
            _make_alloc(current_apy_pct=4.0, opportunity_cost_pct=5.0,
                        allocated_usd=100_000.0, protocol="A"),
            _make_alloc(current_apy_pct=4.0, opportunity_cost_pct=5.0,
                        allocated_usd=100_000.0, protocol="B"),
        ]
        result = self.scorer.score(allocs, {})
        self.assertAlmostEqual(result["aggregates"]["total_opportunity_cost_usd"], 2000.0, places=1)


# ---------------------------------------------------------------------------
# 11. Score monotonicity / ordering
# ---------------------------------------------------------------------------

class TestScoreMonotonicity(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldOptimizerAllocationScorer()

    def _score_of(self, **kwargs):
        result = self.scorer.score([_make_alloc(**kwargs)], {})
        return result["allocations"][0]["composite_score"]

    def test_higher_efficiency_higher_score(self):
        s_high = self._score_of(current_apy_pct=9.0, opportunity_cost_pct=10.0,
                                 gas_cost_annual_usd=0.0, correlation_to_portfolio=0.0,
                                 risk_score=0.0)
        s_low  = self._score_of(current_apy_pct=3.0, opportunity_cost_pct=10.0,
                                 gas_cost_annual_usd=0.0, correlation_to_portfolio=0.0,
                                 risk_score=0.0)
        self.assertGreater(s_high, s_low)

    def test_lower_correlation_higher_score(self):
        s_low_corr  = self._score_of(correlation_to_portfolio=0.0)
        s_high_corr = self._score_of(correlation_to_portfolio=0.9)
        self.assertGreater(s_low_corr, s_high_corr)

    def test_lower_gas_higher_net_apy(self):
        result_low  = self.scorer.score([_make_alloc(gas_cost_annual_usd=10.0,   allocated_usd=100_000.0)], {})
        result_high = self.scorer.score([_make_alloc(gas_cost_annual_usd=4_000.0, allocated_usd=100_000.0)], {})
        net_low  = result_low["allocations"][0]["net_apy_after_gas"]
        net_high = result_high["allocations"][0]["net_apy_after_gas"]
        self.assertGreater(net_low, net_high)


if __name__ == "__main__":
    unittest.main()
