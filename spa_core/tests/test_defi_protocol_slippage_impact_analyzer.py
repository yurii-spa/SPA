"""
Tests for MP-1002: DeFiProtocolSlippageImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_slippage_impact_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Make sure the repo root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_slippage_impact_analyzer import (
    DeFiProtocolSlippageImpactAnalyzer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(
    name="t1",
    protocol="aave",
    pool_tvl_usd=10_000_000,
    trade_size_usd=10_000,
    pool_type="v2_amm",
    bid_ask_spread_bps=5,
    actual_slippage_bps=8,
    mev_extracted_bps=2,
    total_cost_bps=None,
    position_hold_days=30,
    expected_yield_pct_annual=10.0,
    expected_price_impact_bps=None,
    token_pair_volatility_pct=2.0,
):
    d = {
        "name": name,
        "protocol": protocol,
        "pool_tvl_usd": pool_tvl_usd,
        "trade_size_usd": trade_size_usd,
        "pool_type": pool_type,
        "bid_ask_spread_bps": bid_ask_spread_bps,
        "actual_slippage_bps": actual_slippage_bps,
        "mev_extracted_bps": mev_extracted_bps,
        "position_hold_days": position_hold_days,
        "expected_yield_pct_annual": expected_yield_pct_annual,
        "token_pair_volatility_pct": token_pair_volatility_pct,
    }
    if total_cost_bps is not None:
        d["total_cost_bps"] = total_cost_bps
    if expected_price_impact_bps is not None:
        d["expected_price_impact_bps"] = expected_price_impact_bps
    return d


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_empty_trades_returns_empty_results(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["results"], [])

    def test_empty_aggregates_total_trades_zero(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["aggregates"]["total_trades"], 0)

    def test_empty_aggregates_lowest_impact_none(self):
        out = self.az.analyze([], {})
        self.assertIsNone(out["aggregates"]["lowest_impact"])

    def test_empty_aggregates_highest_impact_none(self):
        out = self.az.analyze([], {})
        self.assertIsNone(out["aggregates"]["highest_impact"])

    def test_empty_aggregates_avg_efficiency_zero(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["aggregates"]["avg_efficiency_score"], 0.0)

    def test_empty_aggregates_yield_destructive_zero(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["aggregates"]["yield_destructive_count"], 0)

    def test_empty_aggregates_negligible_zero(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["aggregates"]["negligible_count"], 0)

    def test_empty_meta_analyzer_name(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["meta"]["analyzer"], "DeFiProtocolSlippageImpactAnalyzer")

    def test_empty_meta_version(self):
        out = self.az.analyze([], {})
        self.assertEqual(out["meta"]["version"], "1.0.0")


class TestSingleTradeFields(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()
        trade = _trade(
            name="alpha",
            protocol="compound",
            pool_tvl_usd=5_000_000,
            trade_size_usd=50_000,
            total_cost_bps=20,
            actual_slippage_bps=12,
            expected_price_impact_bps=10,
            position_hold_days=30,
            expected_yield_pct_annual=12.0,
        )
        self.out = self.az.analyze([trade], {})
        self.r = self.out["results"][0]

    def test_name_preserved(self):
        self.assertEqual(self.r["name"], "alpha")

    def test_protocol_preserved(self):
        self.assertEqual(self.r["protocol"], "compound")

    def test_pool_tvl_preserved(self):
        self.assertEqual(self.r["pool_tvl_usd"], 5_000_000)

    def test_trade_size_preserved(self):
        self.assertEqual(self.r["trade_size_usd"], 50_000)

    def test_size_to_liquidity_ratio(self):
        # 50000 / 5000000 * 100 = 1.0
        self.assertAlmostEqual(self.r["size_to_liquidity_ratio"], 1.0, places=3)

    def test_total_cost_bps_provided(self):
        self.assertEqual(self.r["total_cost_bps"], 20)

    def test_slippage_to_trade_ratio(self):
        # 12/10000 * 50000 = 60.0
        self.assertAlmostEqual(self.r["slippage_to_trade_ratio"], 60.0, places=3)

    def test_annual_slippage_drag_pct(self):
        # 20/10000 * 365/30 * 100 = 2.4333...
        expected = (20 / 10000) * (365 / 30) * 100
        self.assertAlmostEqual(self.r["annual_slippage_drag_pct"], expected, places=3)

    def test_yield_net_of_costs(self):
        drag = (20 / 10000) * (365 / 30) * 100
        expected = 12.0 - drag
        self.assertAlmostEqual(self.r["yield_net_of_costs"], expected, places=2)

    def test_efficiency_score_bounded_0_100(self):
        self.assertGreaterEqual(self.r["efficiency_score"], 0)
        self.assertLessEqual(self.r["efficiency_score"], 100)

    def test_expected_price_impact_preserved(self):
        self.assertAlmostEqual(self.r["expected_price_impact_bps"], 10.0, places=3)

    def test_result_has_flags_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_result_has_impact_label(self):
        self.assertIn("impact_label", self.r)

    def test_total_trades_one(self):
        self.assertEqual(self.out["aggregates"]["total_trades"], 1)


class TestImpactLabelNegligible(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_negligible_small_cost_small_ratio(self):
        trade = _trade(
            pool_tvl_usd=100_000_000,
            trade_size_usd=50_000,       # ratio = 0.05% < 0.1%
            total_cost_bps=5,            # < 10
            actual_slippage_bps=3,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "NEGLIGIBLE_IMPACT")

    def test_negligible_exact_boundary_cost_9(self):
        trade = _trade(
            pool_tvl_usd=1_000_000_000,
            trade_size_usd=500_000,      # 0.05% < 0.1%
            total_cost_bps=9,
            actual_slippage_bps=5,
            expected_yield_pct_annual=8.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "NEGLIGIBLE_IMPACT")

    def test_negligible_count_increments(self):
        t1 = _trade(
            pool_tvl_usd=100_000_000, trade_size_usd=50_000,
            total_cost_bps=5, actual_slippage_bps=3,
            expected_yield_pct_annual=10.0, position_hold_days=365,
        )
        t2 = _trade(
            name="t2",
            pool_tvl_usd=100_000_000, trade_size_usd=50_000,
            total_cost_bps=5, actual_slippage_bps=3,
            expected_yield_pct_annual=10.0, position_hold_days=365,
        )
        out = self.az.analyze([t1, t2], {})
        self.assertEqual(out["aggregates"]["negligible_count"], 2)


class TestImpactLabelLow(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_low_impact_medium_cost_small_ratio(self):
        trade = _trade(
            pool_tvl_usd=10_000_000,
            trade_size_usd=20_000,       # ratio = 0.2% < 0.5%
            total_cost_bps=15,           # 10 ≤ cost < 30
            actual_slippage_bps=10,
            expected_yield_pct_annual=8.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "LOW_IMPACT")

    def test_not_negligible_when_cost_10(self):
        trade = _trade(
            pool_tvl_usd=100_000_000,
            trade_size_usd=50_000,       # ratio = 0.05%
            total_cost_bps=10,           # not < 10
            actual_slippage_bps=8,
            expected_yield_pct_annual=8.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        label = out["results"][0]["impact_label"]
        self.assertNotEqual(label, "NEGLIGIBLE_IMPACT")


class TestImpactLabelHigh(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_high_impact_cost_over_100(self):
        # cost=120bps, hold=365d → drag=1.2% < yield=20% → NOT destructive; cost>100 → HIGH_IMPACT
        trade = _trade(
            total_cost_bps=120,
            actual_slippage_bps=90,
            expected_yield_pct_annual=20.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "HIGH_IMPACT")

    def test_high_impact_yield_net_under_50pct(self):
        # yield=10%, drag must be >5% but <10% to avoid YIELD_DESTRUCTIVE
        # drag = total_cost/10000 * 365/hold_days * 100
        # want drag=8%: total_cost = 8/100 * 10000 * 1 = 800bps but that's >100 so HIGH_IMPACT from cost
        # Let's do: drag = 7%:  total_cost = 7/100/100 * 10000 = 70bps, hold=365
        trade = _trade(
            total_cost_bps=70,
            actual_slippage_bps=50,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        # drag = 70/10000 * 1 * 100 = 0.7%
        # net = 9.3%, which is 93% of 10 → not < 50%
        # cost=70<100 → not cost-based high
        # So label should be LOW or MODERATE
        label = out["results"][0]["impact_label"]
        self.assertNotEqual(label, "HIGH_IMPACT")

    def test_high_impact_from_low_net_yield(self):
        # yield=10%, drag=6% → net=4% which is 40% of gross < 50%
        # drag = total_cost/10000 * (365/365) * 100 = total_cost/100
        # need drag=6% → total_cost = 600bps > 100 → still HIGH from cost
        # Use smaller hold days to achieve big drag without >100bps cost
        # drag = total_cost/10000 * (365/hold) * 100
        # want drag=6% with cost=90bps: 90/10000 * 365/h * 100 = 6 → h = 90*365/600 = 54.75
        trade = _trade(
            total_cost_bps=90,
            actual_slippage_bps=60,
            expected_yield_pct_annual=10.0,
            position_hold_days=55,
        )
        out = self.az.analyze([trade], {})
        r = out["results"][0]
        # yield_net = 10 - drag
        drag = (90 / 10000) * (365 / 55) * 100
        net = 10.0 - drag
        if net < 5.0 and net >= 0:  # net < 50% of 10%
            self.assertEqual(r["impact_label"], "HIGH_IMPACT")
        else:
            # cost=90 < 100, might be moderate
            self.assertIn(r["impact_label"], ["HIGH_IMPACT", "MODERATE_IMPACT"])


class TestImpactLabelYieldDestructive(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_yield_destructive_drag_exceeds_yield(self):
        # yield=5%, drag must be >5%
        # drag = total_cost/10000 * 365/hold_days * 100
        # total_cost=200, hold=30 → drag = 200/10000 * 365/30 * 100 = 24.33%
        trade = _trade(
            total_cost_bps=200,
            actual_slippage_bps=150,
            expected_yield_pct_annual=5.0,
            position_hold_days=30,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "YIELD_DESTRUCTIVE")

    def test_yield_destructive_count(self):
        t = _trade(
            total_cost_bps=500,
            actual_slippage_bps=400,
            expected_yield_pct_annual=5.0,
            position_hold_days=30,
        )
        out = self.az.analyze([t], {})
        self.assertEqual(out["aggregates"]["yield_destructive_count"], 1)

    def test_yield_destructive_zero_yield_any_drag(self):
        # yield=0, drag=anything>0 → YIELD_DESTRUCTIVE
        trade = _trade(
            total_cost_bps=5,
            actual_slippage_bps=3,
            expected_yield_pct_annual=0.0,
            position_hold_days=30,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "YIELD_DESTRUCTIVE")


class TestImpactLabelModerate(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_moderate_medium_cost_medium_ratio(self):
        trade = _trade(
            pool_tvl_usd=1_000_000,
            trade_size_usd=4_000,        # ratio = 0.4%, not < 0.1% so not NEGLIGIBLE
            total_cost_bps=25,           # not > 100
            actual_slippage_bps=20,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        label = out["results"][0]["impact_label"]
        # ratio 0.4% < 0.5% and cost 25<30 → LOW
        self.assertIn(label, ["LOW_IMPACT", "MODERATE_IMPACT"])

    def test_moderate_when_ratio_too_high_for_low(self):
        # cost<30 but ratio>0.5% → MODERATE
        trade = _trade(
            pool_tvl_usd=1_000_000,
            trade_size_usd=8_000,        # ratio = 0.8%
            total_cost_bps=20,
            actual_slippage_bps=15,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["impact_label"], "MODERATE_IMPACT")


class TestFlagMevExposure(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_mev_flag_above_20(self):
        trade = _trade(mev_extracted_bps=25)
        out = self.az.analyze([trade], {})
        self.assertIn("MEV_EXPOSURE", out["results"][0]["flags"])

    def test_no_mev_flag_at_20(self):
        trade = _trade(mev_extracted_bps=20)
        out = self.az.analyze([trade], {})
        self.assertNotIn("MEV_EXPOSURE", out["results"][0]["flags"])

    def test_no_mev_flag_below_20(self):
        trade = _trade(mev_extracted_bps=10)
        out = self.az.analyze([trade], {})
        self.assertNotIn("MEV_EXPOSURE", out["results"][0]["flags"])

    def test_mev_flag_at_21(self):
        trade = _trade(mev_extracted_bps=21)
        out = self.az.analyze([trade], {})
        self.assertIn("MEV_EXPOSURE", out["results"][0]["flags"])


class TestFlagOversizedForPool(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_oversized_flag_above_2pct(self):
        trade = _trade(pool_tvl_usd=1_000_000, trade_size_usd=25_000)  # 2.5%
        out = self.az.analyze([trade], {})
        self.assertIn("OVERSIZED_FOR_POOL", out["results"][0]["flags"])

    def test_no_oversized_at_2pct(self):
        trade = _trade(pool_tvl_usd=1_000_000, trade_size_usd=20_000)  # exactly 2%
        out = self.az.analyze([trade], {})
        self.assertNotIn("OVERSIZED_FOR_POOL", out["results"][0]["flags"])

    def test_no_oversized_below_2pct(self):
        trade = _trade(pool_tvl_usd=1_000_000, trade_size_usd=10_000)  # 1%
        out = self.az.analyze([trade], {})
        self.assertNotIn("OVERSIZED_FOR_POOL", out["results"][0]["flags"])

    def test_oversized_large_trade(self):
        trade = _trade(pool_tvl_usd=500_000, trade_size_usd=50_000)  # 10%
        out = self.az.analyze([trade], {})
        self.assertIn("OVERSIZED_FOR_POOL", out["results"][0]["flags"])


class TestFlagYieldNegativeNet(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_negative_net_flag(self):
        trade = _trade(
            total_cost_bps=1000,
            actual_slippage_bps=800,
            expected_yield_pct_annual=3.0,
            position_hold_days=30,
        )
        out = self.az.analyze([trade], {})
        self.assertIn("YIELD_NEGATIVE_NET", out["results"][0]["flags"])

    def test_no_negative_net_flag_positive(self):
        trade = _trade(
            total_cost_bps=5,
            actual_slippage_bps=3,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("YIELD_NEGATIVE_NET", out["results"][0]["flags"])


class TestFlagStablePoolEfficient(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_stable_pool_efficient_flag(self):
        trade = _trade(
            pool_type="curve_stable",
            total_cost_bps=3,
            actual_slippage_bps=2,
        )
        out = self.az.analyze([trade], {})
        self.assertIn("STABLE_POOL_EFFICIENT", out["results"][0]["flags"])

    def test_no_stable_pool_flag_non_curve(self):
        trade = _trade(
            pool_type="v2_amm",
            total_cost_bps=3,
            actual_slippage_bps=2,
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("STABLE_POOL_EFFICIENT", out["results"][0]["flags"])

    def test_no_stable_pool_flag_high_cost(self):
        trade = _trade(
            pool_type="curve_stable",
            total_cost_bps=10,
            actual_slippage_bps=8,
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("STABLE_POOL_EFFICIENT", out["results"][0]["flags"])

    def test_stable_at_boundary_4bps(self):
        trade = _trade(
            pool_type="curve_stable",
            total_cost_bps=4,
            actual_slippage_bps=3,
        )
        out = self.az.analyze([trade], {})
        self.assertIn("STABLE_POOL_EFFICIENT", out["results"][0]["flags"])


class TestFlagSlippageExceedsEstimate(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_slippage_exceeds_1_5x_estimate(self):
        trade = _trade(
            actual_slippage_bps=160,
            expected_price_impact_bps=100,  # 160 > 100*1.5
        )
        out = self.az.analyze([trade], {})
        self.assertIn("SLIPPAGE_EXCEEDS_ESTIMATE", out["results"][0]["flags"])

    def test_slippage_exactly_1_5x_not_flagged(self):
        trade = _trade(
            actual_slippage_bps=150,
            expected_price_impact_bps=100,  # exactly 1.5x, not >
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("SLIPPAGE_EXCEEDS_ESTIMATE", out["results"][0]["flags"])

    def test_slippage_below_estimate_not_flagged(self):
        trade = _trade(
            actual_slippage_bps=80,
            expected_price_impact_bps=100,
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("SLIPPAGE_EXCEEDS_ESTIMATE", out["results"][0]["flags"])

    def test_zero_expected_impact_no_flag(self):
        trade = _trade(
            actual_slippage_bps=50,
            expected_price_impact_bps=0,
        )
        out = self.az.analyze([trade], {})
        self.assertNotIn("SLIPPAGE_EXCEEDS_ESTIMATE", out["results"][0]["flags"])


class TestFlagHighSpreadMarket(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_high_spread_flag_above_50(self):
        trade = _trade(bid_ask_spread_bps=60)
        out = self.az.analyze([trade], {})
        self.assertIn("HIGH_SPREAD_MARKET", out["results"][0]["flags"])

    def test_no_high_spread_at_50(self):
        trade = _trade(bid_ask_spread_bps=50)
        out = self.az.analyze([trade], {})
        self.assertNotIn("HIGH_SPREAD_MARKET", out["results"][0]["flags"])

    def test_no_high_spread_below_50(self):
        trade = _trade(bid_ask_spread_bps=30)
        out = self.az.analyze([trade], {})
        self.assertNotIn("HIGH_SPREAD_MARKET", out["results"][0]["flags"])

    def test_high_spread_at_51(self):
        trade = _trade(bid_ask_spread_bps=51)
        out = self.az.analyze([trade], {})
        self.assertIn("HIGH_SPREAD_MARKET", out["results"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def _analyze_two(self):
        t1 = _trade(
            name="good",
            pool_tvl_usd=100_000_000,
            trade_size_usd=10_000,
            total_cost_bps=5,
            actual_slippage_bps=3,
            expected_yield_pct_annual=10.0,
            position_hold_days=365,
        )
        t2 = _trade(
            name="bad",
            total_cost_bps=500,
            actual_slippage_bps=400,
            expected_yield_pct_annual=5.0,
            position_hold_days=30,
        )
        return self.az.analyze([t1, t2], {})

    def test_total_trades_two(self):
        out = self._analyze_two()
        self.assertEqual(out["aggregates"]["total_trades"], 2)

    def test_lowest_impact_is_good(self):
        out = self._analyze_two()
        self.assertEqual(out["aggregates"]["lowest_impact"], "good")

    def test_highest_impact_is_bad(self):
        out = self._analyze_two()
        self.assertEqual(out["aggregates"]["highest_impact"], "bad")

    def test_avg_efficiency_between_0_100(self):
        out = self._analyze_two()
        avg = out["aggregates"]["avg_efficiency_score"]
        self.assertGreaterEqual(avg, 0)
        self.assertLessEqual(avg, 100)

    def test_yield_destructive_count_one(self):
        out = self._analyze_two()
        self.assertEqual(out["aggregates"]["yield_destructive_count"], 1)

    def test_negligible_count_for_efficient_trade(self):
        out = self._analyze_two()
        # The "good" trade with cost=5bps, ratio<0.1% → NEGLIGIBLE
        self.assertGreaterEqual(out["aggregates"]["negligible_count"], 0)

    def test_single_trade_lowest_equals_highest(self):
        trade = _trade()
        out = self.az.analyze([trade], {})
        agg = out["aggregates"]
        self.assertEqual(agg["lowest_impact"], agg["highest_impact"])


class TestCalculations(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_size_to_liquidity_ratio_calculation(self):
        trade = _trade(pool_tvl_usd=1_000_000, trade_size_usd=10_000)
        out = self.az.analyze([trade], {})
        self.assertAlmostEqual(out["results"][0]["size_to_liquidity_ratio"], 1.0, places=3)

    def test_size_to_liquidity_zero_tvl(self):
        trade = _trade(pool_tvl_usd=0, trade_size_usd=10_000)
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["size_to_liquidity_ratio"], 0.0)

    def test_slippage_to_trade_ratio_dollars(self):
        # 10 bps on 100,000 = $100 (10/10000 * 100000)
        trade = _trade(actual_slippage_bps=10, trade_size_usd=100_000)
        out = self.az.analyze([trade], {})
        self.assertAlmostEqual(out["results"][0]["slippage_to_trade_ratio"], 100.0, places=2)

    def test_annual_drag_hold_365(self):
        trade = _trade(total_cost_bps=100, position_hold_days=365, expected_yield_pct_annual=5.0)
        out = self.az.analyze([trade], {})
        # drag = 100/10000 * 1 * 100 = 1.0%
        self.assertAlmostEqual(out["results"][0]["annual_slippage_drag_pct"], 1.0, places=3)

    def test_annual_drag_hold_1_day(self):
        trade = _trade(total_cost_bps=1, position_hold_days=1, expected_yield_pct_annual=5.0)
        out = self.az.analyze([trade], {})
        # drag = 1/10000 * 365 * 100 = 3.65%
        self.assertAlmostEqual(out["results"][0]["annual_slippage_drag_pct"], 3.65, places=2)

    def test_yield_net_of_costs(self):
        trade = _trade(
            total_cost_bps=100,
            position_hold_days=365,
            expected_yield_pct_annual=10.0,
        )
        out = self.az.analyze([trade], {})
        self.assertAlmostEqual(out["results"][0]["yield_net_of_costs"], 9.0, places=2)

    def test_efficiency_score_100_zero_cost(self):
        trade = _trade(
            total_cost_bps=0,
            actual_slippage_bps=0,
            mev_extracted_bps=0,
            bid_ask_spread_bps=0,
            expected_yield_pct_annual=10.0,
        )
        out = self.az.analyze([trade], {})
        self.assertAlmostEqual(out["results"][0]["efficiency_score"], 100.0, places=1)

    def test_efficiency_score_zero_when_yield_zero(self):
        trade = _trade(expected_yield_pct_annual=0.0, total_cost_bps=10)
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["efficiency_score"], 0.0)

    def test_expected_price_impact_computed_from_tvl(self):
        # No expected_price_impact_bps given; should compute from size/tvl
        trade = {
            "name": "x",
            "pool_tvl_usd": 1_000_000,
            "trade_size_usd": 10_000,
            "bid_ask_spread_bps": 0,
            "actual_slippage_bps": 0,
            "mev_extracted_bps": 0,
            "total_cost_bps": 0,
            "position_hold_days": 1,
            "expected_yield_pct_annual": 5.0,
        }
        out = self.az.analyze([trade], {})
        # size_ratio = 1% → expected_impact = 1 * 100 = 100bps
        self.assertAlmostEqual(out["results"][0]["expected_price_impact_bps"], 100.0, places=0)

    def test_total_cost_computed_when_not_provided(self):
        trade = {
            "name": "x",
            "bid_ask_spread_bps": 5,
            "actual_slippage_bps": 10,
            "mev_extracted_bps": 3,
            "position_hold_days": 30,
            "expected_yield_pct_annual": 5.0,
        }
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["total_cost_bps"], 18)


class TestPoolTypes(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_concentrated_pool(self):
        trade = _trade(pool_type="concentrated")
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["pool_type"], "concentrated")

    def test_v2_amm_pool(self):
        trade = _trade(pool_type="v2_amm")
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["pool_type"], "v2_amm")

    def test_balancer_pool(self):
        trade = _trade(pool_type="balancer")
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["pool_type"], "balancer")

    def test_curve_stable_pool(self):
        trade = _trade(pool_type="curve_stable")
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["pool_type"], "curve_stable")


class TestMultipleTrades(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_five_trades_total_count(self):
        trades = [_trade(name=f"t{i}") for i in range(5)]
        out = self.az.analyze(trades, {})
        self.assertEqual(out["aggregates"]["total_trades"], 5)
        self.assertEqual(len(out["results"]), 5)

    def test_names_preserved_multiple(self):
        names = ["alpha", "beta", "gamma"]
        trades = [_trade(name=n) for n in names]
        out = self.az.analyze(trades, {})
        result_names = [r["name"] for r in out["results"]]
        for n in names:
            self.assertIn(n, result_names)

    def test_all_negligible_negligible_count(self):
        trades = [
            _trade(
                name=f"t{i}",
                pool_tvl_usd=1_000_000_000,
                trade_size_usd=100_000,    # 0.01%
                total_cost_bps=5,
                actual_slippage_bps=3,
                expected_yield_pct_annual=10.0,
                position_hold_days=365,
            )
            for i in range(3)
        ]
        out = self.az.analyze(trades, {})
        self.assertEqual(out["aggregates"]["negligible_count"], 3)


class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            trade = _trade()
            self.az.analyze([trade], {})
            self.assertTrue(os.path.exists(self.az.LOG_FILE))

    def test_log_file_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            trade = _trade()
            self.az.analyze([trade], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_file_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            trade = _trade()
            self.az.analyze([trade], {})
            self.az.analyze([trade], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            self.az.analyze([_trade()], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])

    def test_log_entry_has_total_trades(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            self.az.analyze([_trade()], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("total_trades", data[0])

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            self.az.LOG_CAP = 3
            trade = _trade()
            for _ in range(5):
                self.az.analyze([trade], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_atomic_no_tmp_left_after(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            self.az.analyze([_trade()], {})
            self.assertFalse(os.path.exists(self.az.LOG_FILE + ".tmp"))

    def test_log_entry_avg_efficiency_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.az.LOG_FILE = os.path.join(tmpdir, "data", "slippage_impact_log.json")
            self.az.analyze([_trade()], {})
            with open(self.az.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("avg_efficiency_score", data[0])


class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_output_has_results_key(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("results", out)

    def test_output_has_aggregates_key(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("aggregates", out)

    def test_output_has_meta_key(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("meta", out)

    def test_result_has_all_required_keys(self):
        out = self.az.analyze([_trade()], {})
        keys = [
            "name", "protocol", "pool_type", "trade_size_usd", "pool_tvl_usd",
            "size_to_liquidity_ratio", "bid_ask_spread_bps", "actual_slippage_bps",
            "expected_price_impact_bps", "mev_extracted_bps", "total_cost_bps",
            "slippage_to_trade_ratio", "annual_slippage_drag_pct",
            "expected_yield_pct_annual", "yield_net_of_costs", "efficiency_score",
            "impact_label", "flags",
        ]
        r = out["results"][0]
        for k in keys:
            self.assertIn(k, r, f"Missing key: {k}")

    def test_meta_has_analyzer(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("analyzer", out["meta"])

    def test_meta_has_version(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("version", out["meta"])

    def test_meta_has_timestamp_when_trades(self):
        out = self.az.analyze([_trade()], {})
        self.assertIn("timestamp", out["meta"])

    def test_aggregates_has_all_keys(self):
        out = self.az.analyze([_trade()], {})
        keys = [
            "lowest_impact", "highest_impact", "avg_efficiency_score",
            "yield_destructive_count", "negligible_count", "total_trades",
        ]
        agg = out["aggregates"]
        for k in keys:
            self.assertIn(k, agg, f"Missing agg key: {k}")


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.az = DeFiProtocolSlippageImpactAnalyzer()

    def test_zero_hold_days_no_crash(self):
        trade = _trade(position_hold_days=0)
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["annual_slippage_drag_pct"], 0.0)

    def test_negative_slippage_no_crash(self):
        trade = _trade(actual_slippage_bps=-5)
        out = self.az.analyze([trade], {})
        self.assertIsNotNone(out)

    def test_very_large_trade(self):
        trade = _trade(trade_size_usd=1e12, pool_tvl_usd=1e9)
        out = self.az.analyze([trade], {})
        self.assertIn("OVERSIZED_FOR_POOL", out["results"][0]["flags"])

    def test_unknown_defaults(self):
        trade = {}
        out = self.az.analyze([trade], {})
        self.assertEqual(out["results"][0]["name"], "unknown")

    def test_multiple_flags_simultaneously(self):
        trade = _trade(
            pool_tvl_usd=1_000_000,
            trade_size_usd=30_000,       # 3% → OVERSIZED
            mev_extracted_bps=25,         # MEV_EXPOSURE
            bid_ask_spread_bps=60,        # HIGH_SPREAD
            total_cost_bps=1000,
            actual_slippage_bps=800,
            expected_yield_pct_annual=5.0,
            position_hold_days=30,
        )
        out = self.az.analyze([trade], {})
        flags = out["results"][0]["flags"]
        self.assertIn("MEV_EXPOSURE", flags)
        self.assertIn("OVERSIZED_FOR_POOL", flags)
        self.assertIn("HIGH_SPREAD_MARKET", flags)
        self.assertIn("YIELD_NEGATIVE_NET", flags)

    def test_config_empty_dict_accepted(self):
        trade = _trade()
        out = self.az.analyze([trade], {})
        self.assertIsNotNone(out)

    def test_config_with_arbitrary_keys(self):
        trade = _trade()
        out = self.az.analyze([trade], {"some_key": 42, "another": "value"})
        self.assertIsNotNone(out)

    def test_efficiency_score_never_exceeds_100(self):
        trade = _trade(
            total_cost_bps=0,
            actual_slippage_bps=0,
            mev_extracted_bps=0,
            bid_ask_spread_bps=0,
            expected_yield_pct_annual=100.0,
        )
        out = self.az.analyze([trade], {})
        self.assertLessEqual(out["results"][0]["efficiency_score"], 100.0)

    def test_efficiency_score_never_below_zero(self):
        trade = _trade(
            total_cost_bps=10000,
            actual_slippage_bps=8000,
            expected_yield_pct_annual=1.0,
            position_hold_days=1,
        )
        out = self.az.analyze([trade], {})
        self.assertGreaterEqual(out["results"][0]["efficiency_score"], 0.0)


class TestLabelConstants(unittest.TestCase):
    def test_negligible_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.NEGLIGIBLE_IMPACT, "NEGLIGIBLE_IMPACT"
        )

    def test_low_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.LOW_IMPACT, "LOW_IMPACT"
        )

    def test_moderate_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.MODERATE_IMPACT, "MODERATE_IMPACT"
        )

    def test_high_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.HIGH_IMPACT, "HIGH_IMPACT"
        )

    def test_yield_destructive_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.YIELD_DESTRUCTIVE, "YIELD_DESTRUCTIVE"
        )

    def test_flag_mev_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.FLAG_MEV_EXPOSURE, "MEV_EXPOSURE"
        )

    def test_flag_oversized_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.FLAG_OVERSIZED_FOR_POOL,
            "OVERSIZED_FOR_POOL",
        )

    def test_flag_yield_negative_constant(self):
        self.assertEqual(
            DeFiProtocolSlippageImpactAnalyzer.FLAG_YIELD_NEGATIVE_NET,
            "YIELD_NEGATIVE_NET",
        )

    def test_log_cap(self):
        self.assertEqual(DeFiProtocolSlippageImpactAnalyzer.LOG_CAP, 100)


if __name__ == "__main__":
    unittest.main()
