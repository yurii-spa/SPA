"""Tests for spa_core/analytics/slippage_simulator.py — MP-629.

≥ 40 tests covering:
  * SlippageEstimate dataclass
  * _base_bps_for_tvl helper
  * SlippageSimulator.estimate_slippage (all liquidity tiers, edge cases)
  * SlippageSimulator.estimate_portfolio_slippage
  * SlippageSimulator.compute_effective_apy
  * SlippageSimulator.generate_report
  * Constants
"""
from __future__ import annotations

import math
import unittest

from spa_core.analytics.slippage_simulator import (
    ACCEPTABLE_SLIPPAGE_BPS,
    SLIPPAGE_MODEL,
    SlippageEstimate,
    SlippageSimulator,
    _base_bps_for_tvl,
)


# ---------------------------------------------------------------------------
# 1. SlippageEstimate dataclass
# ---------------------------------------------------------------------------


class TestSlippageEstimateDataclass(unittest.TestCase):
    """Tests for the SlippageEstimate dataclass (5 tests)."""

    def test_fields_exist(self):
        e = SlippageEstimate(
            adapter_id="test",
            trade_size_usd=1000.0,
            pool_tvl_usd=1_000_000.0,
            slippage_bps=5.0,
            price_impact_pct=0.05,
            is_acceptable=True,
            max_safe_trade_usd=60_000.0,
        )
        self.assertEqual(e.adapter_id, "test")
        self.assertEqual(e.trade_size_usd, 1000.0)
        self.assertEqual(e.pool_tvl_usd, 1_000_000.0)
        self.assertEqual(e.slippage_bps, 5.0)
        self.assertEqual(e.price_impact_pct, 0.05)
        self.assertTrue(e.is_acceptable)
        self.assertEqual(e.max_safe_trade_usd, 60_000.0)

    def test_is_acceptable_false(self):
        e = SlippageEstimate("x", 0, 0, 100.0, 1.0, False, 0.0)
        self.assertFalse(e.is_acceptable)

    def test_slippage_bps_float(self):
        e = SlippageEstimate("x", 0, 0, 12.345, 0.12345, True, 500.0)
        self.assertIsInstance(e.slippage_bps, float)

    def test_adapter_id_string(self):
        e = SlippageEstimate("aave_v3", 0, 0, 0, 0, True, 0)
        self.assertEqual(e.adapter_id, "aave_v3")

    def test_zero_values(self):
        e = SlippageEstimate("", 0.0, 0.0, 0.0, 0.0, True, 0.0)
        self.assertEqual(e.slippage_bps, 0.0)
        self.assertEqual(e.price_impact_pct, 0.0)


# ---------------------------------------------------------------------------
# 2. Constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Tests for module-level constants (6 tests)."""

    def test_acceptable_slippage_bps_value(self):
        self.assertEqual(ACCEPTABLE_SLIPPAGE_BPS, 30.0)

    def test_slippage_model_keys(self):
        self.assertIn("low_liquidity", SLIPPAGE_MODEL)
        self.assertIn("medium_liquidity", SLIPPAGE_MODEL)
        self.assertIn("high_liquidity", SLIPPAGE_MODEL)
        self.assertIn("deep_liquidity", SLIPPAGE_MODEL)

    def test_low_liquidity_bps(self):
        self.assertEqual(SLIPPAGE_MODEL["low_liquidity"]["base_bps"], 50)

    def test_medium_liquidity_bps(self):
        self.assertEqual(SLIPPAGE_MODEL["medium_liquidity"]["base_bps"], 20)

    def test_high_liquidity_bps(self):
        self.assertEqual(SLIPPAGE_MODEL["high_liquidity"]["base_bps"], 5)

    def test_deep_liquidity_bps(self):
        self.assertEqual(SLIPPAGE_MODEL["deep_liquidity"]["base_bps"], 1)


# ---------------------------------------------------------------------------
# 3. _base_bps_for_tvl helper
# ---------------------------------------------------------------------------


class TestBaseBpsForTvl(unittest.TestCase):
    """Tests for the internal _base_bps_for_tvl helper (8 tests)."""

    def test_low_liquidity_tvl(self):
        # TVL < $1M → 50 bps
        self.assertEqual(_base_bps_for_tvl(500_000), 50)

    def test_low_liquidity_boundary_just_below(self):
        self.assertEqual(_base_bps_for_tvl(999_999), 50)

    def test_medium_liquidity_tvl(self):
        # $1M ≤ TVL < $10M → 20 bps
        self.assertEqual(_base_bps_for_tvl(5_000_000), 20)

    def test_medium_liquidity_boundary_at_one_million(self):
        self.assertEqual(_base_bps_for_tvl(1_000_000), 20)

    def test_high_liquidity_tvl(self):
        # $10M ≤ TVL < $100M → 5 bps
        self.assertEqual(_base_bps_for_tvl(50_000_000), 5)

    def test_high_liquidity_boundary_at_ten_million(self):
        self.assertEqual(_base_bps_for_tvl(10_000_000), 5)

    def test_deep_liquidity_tvl(self):
        # TVL ≥ $100M → 1 bps
        self.assertEqual(_base_bps_for_tvl(100_000_000), 1)

    def test_deep_liquidity_very_large_tvl(self):
        self.assertEqual(_base_bps_for_tvl(2_000_000_000), 1)


# ---------------------------------------------------------------------------
# 4. SlippageSimulator.estimate_slippage
# ---------------------------------------------------------------------------


class TestEstimateSlippage(unittest.TestCase):
    """Core estimate_slippage tests (12 tests)."""

    def setUp(self):
        self.sim = SlippageSimulator()

    def test_deep_liquidity_small_trade_acceptable(self):
        # $100K trade in $2B pool → deep_liquidity (base_bps=1)
        # slippage_bps = 1 * (100_000 / 2_000_000_000) * 10_000 = 0.5
        est = self.sim.estimate_slippage("aave_v3", 100_000, 2_000_000_000)
        self.assertAlmostEqual(est.slippage_bps, 0.5, places=6)
        self.assertTrue(est.is_acceptable)

    def test_low_liquidity_large_trade_unacceptable(self):
        # $100K trade in $500K pool → low_liquidity (50 bps)
        # slippage_bps = 50 * (100_000 / 500_000) * 10_000 = 10_000_000  → huge
        est = self.sim.estimate_slippage("tiny_pool", 100_000, 500_000)
        self.assertGreater(est.slippage_bps, 30.0)
        self.assertFalse(est.is_acceptable)

    def test_price_impact_pct_equals_bps_div_100(self):
        est = self.sim.estimate_slippage("aave_v3", 50_000, 100_000_000)
        self.assertAlmostEqual(est.price_impact_pct, est.slippage_bps / 100.0, places=8)

    def test_zero_trade_size(self):
        est = self.sim.estimate_slippage("aave_v3", 0.0, 100_000_000)
        self.assertEqual(est.slippage_bps, 0.0)
        self.assertTrue(est.is_acceptable)

    def test_zero_tvl_uses_guard(self):
        # TVL = 0 → treated as 1.0 to avoid ZeroDivisionError
        est = self.sim.estimate_slippage("bad_pool", 1000.0, 0.0)
        self.assertIsInstance(est.slippage_bps, float)
        self.assertFalse(math.isnan(est.slippage_bps))

    def test_max_safe_trade_formula(self):
        # Verify max_safe_trade_usd matches spec formula:
        # max_safe = (ACCEPTABLE_SLIPPAGE_BPS / 10000) * tvl / (base_bps / 10000)
        tvl = 500_000_000.0
        est = self.sim.estimate_slippage("compound_v3", 50_000, tvl)
        base_bps = _base_bps_for_tvl(tvl)
        expected = (ACCEPTABLE_SLIPPAGE_BPS / 10_000.0) * tvl / (base_bps / 10_000.0)
        self.assertAlmostEqual(est.max_safe_trade_usd, round(expected, 2), places=1)

    def test_adapter_id_preserved(self):
        est = self.sim.estimate_slippage("morpho_steakhouse", 10_000, 50_000_000)
        self.assertEqual(est.adapter_id, "morpho_steakhouse")

    def test_high_liquidity_tier(self):
        # TVL = $50M → high_liquidity (5 bps base)
        est = self.sim.estimate_slippage("protocol_x", 10_000, 50_000_000)
        expected_bps = 5.0 * (10_000 / 50_000_000) * 10_000
        self.assertAlmostEqual(est.slippage_bps, expected_bps, places=8)

    def test_medium_liquidity_tier(self):
        # TVL = $5M → medium_liquidity (20 bps base)
        est = self.sim.estimate_slippage("protocol_y", 1_000, 5_000_000)
        expected_bps = 20.0 * (1_000 / 5_000_000) * 10_000
        self.assertAlmostEqual(est.slippage_bps, expected_bps, places=8)

    def test_low_liquidity_tier(self):
        # TVL = $200K → low_liquidity (50 bps base)
        est = self.sim.estimate_slippage("protocol_z", 500, 200_000)
        expected_bps = 50.0 * (500 / 200_000) * 10_000
        self.assertAlmostEqual(est.slippage_bps, expected_bps, places=6)

    def test_is_acceptable_boundary_exactly_30(self):
        # Craft a trade that produces exactly 30 bps
        # For deep_liquidity: 1 * (trade/tvl) * 10_000 = 30 → trade = 30 * tvl / 10_000
        tvl = 2_000_000_000.0
        trade = 30.0 * tvl / 10_000.0
        est = self.sim.estimate_slippage("aave_v3", trade, tvl)
        self.assertTrue(est.is_acceptable)

    def test_slippage_above_30_is_unacceptable(self):
        # For deep_liquidity: 1 * (trade/tvl) * 10_000 > 30
        tvl = 2_000_000_000.0
        trade = 31.0 * tvl / 10_000.0  # → 31 bps
        est = self.sim.estimate_slippage("aave_v3", trade, tvl)
        self.assertFalse(est.is_acceptable)


# ---------------------------------------------------------------------------
# 5. SlippageSimulator.estimate_portfolio_slippage
# ---------------------------------------------------------------------------


class TestEstimatePortfolioSlippage(unittest.TestCase):
    """Tests for estimate_portfolio_slippage (6 tests)."""

    def setUp(self):
        self.sim = SlippageSimulator()
        self.trades = {
            "aave_v3": 50_000.0,
            "compound_v3": 30_000.0,
            "morpho_steakhouse": 20_000.0,
        }
        self.tvl_map = {
            "aave_v3": 2_000_000_000.0,
            "compound_v3": 500_000_000.0,
            "morpho_steakhouse": 80_000_000.0,
        }

    def test_returns_list(self):
        result = self.sim.estimate_portfolio_slippage(self.trades, self.tvl_map)
        self.assertIsInstance(result, list)

    def test_length_matches_trades(self):
        result = self.sim.estimate_portfolio_slippage(self.trades, self.tvl_map)
        self.assertEqual(len(result), 3)

    def test_all_estimates_are_slippage_estimate(self):
        result = self.sim.estimate_portfolio_slippage(self.trades, self.tvl_map)
        for est in result:
            self.assertIsInstance(est, SlippageEstimate)

    def test_missing_tvl_defaults_to_zero(self):
        trades = {"unknown_pool": 10_000.0}
        result = self.sim.estimate_portfolio_slippage(trades, {})
        self.assertEqual(len(result), 1)
        # Should not raise; TVL guard handles 0 → 1
        self.assertIsInstance(result[0].slippage_bps, float)

    def test_empty_trades(self):
        result = self.sim.estimate_portfolio_slippage({}, self.tvl_map)
        self.assertEqual(result, [])

    def test_adapter_ids_match_trades_keys(self):
        result = self.sim.estimate_portfolio_slippage(self.trades, self.tvl_map)
        returned_ids = {e.adapter_id for e in result}
        self.assertEqual(returned_ids, set(self.trades.keys()))


# ---------------------------------------------------------------------------
# 6. SlippageSimulator.compute_effective_apy
# ---------------------------------------------------------------------------


class TestComputeEffectiveApy(unittest.TestCase):
    """Tests for compute_effective_apy (7 tests)."""

    def test_basic_calculation(self):
        # gross_apy=0.06, slippage_bps=20, freq=30
        # annual_slippage = (20/10000) * (365/30) ≈ 0.002433
        # effective = 0.06 - 0.002433 ≈ 0.057567
        result = SlippageSimulator.compute_effective_apy(0.06, 20, 30)
        expected = 0.06 - (20 / 10_000) * (365 / 30)
        self.assertAlmostEqual(result, expected, places=10)

    def test_zero_slippage(self):
        result = SlippageSimulator.compute_effective_apy(0.05, 0.0, 30)
        self.assertAlmostEqual(result, 0.05, places=10)

    def test_high_slippage_may_be_negative(self):
        # Very high slippage eats into APY
        result = SlippageSimulator.compute_effective_apy(0.05, 5000, 1)
        self.assertLess(result, 0.0)

    def test_default_rebalance_frequency(self):
        r1 = SlippageSimulator.compute_effective_apy(0.07, 10)
        r2 = SlippageSimulator.compute_effective_apy(0.07, 10, 30)
        self.assertAlmostEqual(r1, r2, places=10)

    def test_annual_rebalance(self):
        # freq=365 → annual_slippage = bps/10000 * 1
        result = SlippageSimulator.compute_effective_apy(0.08, 50, 365)
        expected = 0.08 - (50 / 10_000) * 1.0
        self.assertAlmostEqual(result, expected, places=10)

    def test_weekly_rebalance(self):
        result = SlippageSimulator.compute_effective_apy(0.065, 15, 7)
        expected = 0.065 - (15 / 10_000) * (365 / 7)
        self.assertAlmostEqual(result, expected, places=10)

    def test_freq_zero_guard_prevents_zero_division(self):
        # rebalance_frequency_days is guarded to min 1
        result = SlippageSimulator.compute_effective_apy(0.05, 10, 0)
        self.assertIsInstance(result, float)
        self.assertFalse(math.isnan(result))


# ---------------------------------------------------------------------------
# 7. SlippageSimulator.generate_report
# ---------------------------------------------------------------------------


class TestGenerateReport(unittest.TestCase):
    """Tests for generate_report (9 tests)."""

    def setUp(self):
        self.sim = SlippageSimulator()
        self.trades = {
            "aave_v3": 50_000.0,
            "compound_v3": 30_000.0,
        }
        self.tvl_map = {
            "aave_v3": 2_000_000_000.0,
            "compound_v3": 500_000_000.0,
        }

    def test_returns_dict(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        self.assertIsInstance(report, dict)

    def test_required_keys(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        for key in ("estimates", "total_slippage_bps", "worst_adapter", "best_adapter", "advisory"):
            self.assertIn(key, report)

    def test_estimates_is_list_of_dicts(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        self.assertIsInstance(report["estimates"], list)
        for item in report["estimates"]:
            self.assertIsInstance(item, dict)

    def test_total_slippage_bps_is_sum(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        calc_total = sum(e["slippage_bps"] for e in report["estimates"])
        self.assertAlmostEqual(report["total_slippage_bps"], calc_total, places=4)

    def test_worst_adapter_has_highest_slippage(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        worst_id = report["worst_adapter"]
        all_bps = {e["adapter_id"]: e["slippage_bps"] for e in report["estimates"]}
        max_bps = max(all_bps.values())
        self.assertEqual(all_bps[worst_id], max_bps)

    def test_best_adapter_has_lowest_slippage(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        best_id = report["best_adapter"]
        all_bps = {e["adapter_id"]: e["slippage_bps"] for e in report["estimates"]}
        min_bps = min(all_bps.values())
        self.assertEqual(all_bps[best_id], min_bps)

    def test_advisory_is_string(self):
        report = self.sim.generate_report(self.trades, self.tvl_map)
        self.assertIsInstance(report["advisory"], str)

    def test_empty_trades_report(self):
        report = self.sim.generate_report({}, {})
        self.assertEqual(report["estimates"], [])
        self.assertEqual(report["total_slippage_bps"], 0.0)
        self.assertIsNone(report["worst_adapter"])
        self.assertIsNone(report["best_adapter"])

    def test_advisory_mentions_unacceptable_when_present(self):
        # Tiny TVL to force unacceptable slippage
        trades = {"bad": 100_000.0}
        tvl_map = {"bad": 10_000.0}
        report = self.sim.generate_report(trades, tvl_map)
        self.assertIn("exceed", report["advisory"])


# ---------------------------------------------------------------------------
# 8. Class-level constant exposure
# ---------------------------------------------------------------------------


class TestClassConstants(unittest.TestCase):
    """Tests that class attributes mirror module constants (3 tests)."""

    def test_class_acceptable_slippage_bps(self):
        sim = SlippageSimulator()
        self.assertEqual(sim.ACCEPTABLE_SLIPPAGE_BPS, ACCEPTABLE_SLIPPAGE_BPS)

    def test_class_slippage_model(self):
        sim = SlippageSimulator()
        self.assertIs(sim.SLIPPAGE_MODEL, SLIPPAGE_MODEL)

    def test_static_compute_effective_apy(self):
        # Ensure it works as static method (no self required)
        result = SlippageSimulator.compute_effective_apy(0.05, 10, 30)
        self.assertIsInstance(result, float)


if __name__ == "__main__":
    unittest.main()
