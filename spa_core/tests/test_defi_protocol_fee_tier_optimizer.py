"""
Tests for MP-1000: DeFiProtocolFeeTierOptimizer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_fee_tier_optimizer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_fee_tier_optimizer import (
    DeFiProtocolFeeTierOptimizer,
    LOG_CAP,
    VALID_FEE_TIERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pool(**overrides) -> dict:
    """Return a minimal valid pool dict, with optional overrides."""
    base = {
        "name": "TestPool",
        "token_pair": "USDC/USDT",
        "current_fee_tier_bps": 5,
        "volume_24h_usd": 1_000_000,
        "tvl_usd": 10_000_000,
        "price_volatility_30d_pct": 0.5,
        "correlation_with_eth": 0.99,
        "arbitrage_volume_pct": 10.0,
        "tick_range_tightness_pct": 60.0,
        "competing_pools_same_pair": 2,
        "swap_count_24h": 500,
        "avg_swap_size_usd": 2_000,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Optimal fee determination
# ---------------------------------------------------------------------------

class TestDetermineOptimalFee(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def test_stable_high_correlation(self):
        self.assertEqual(self.opt._determine_optimal_fee(2.0, 0.97), 5)

    def test_stable_exactly_at_correlation_boundary(self):
        # 0.96 > 0.95 → stable
        self.assertEqual(self.opt._determine_optimal_fee(50.0, 0.96), 5)

    def test_not_stable_at_boundary_correlation(self):
        # 0.95 is NOT > 0.95, but vol=50 → high_vol
        self.assertEqual(self.opt._determine_optimal_fee(50.0, 0.95), 100)

    def test_stable_low_volatility(self):
        self.assertEqual(self.opt._determine_optimal_fee(1.0, 0.0), 5)

    def test_stable_volatility_boundary(self):
        # vol < 5 → stable
        self.assertEqual(self.opt._determine_optimal_fee(4.99, 0.0), 5)

    def test_medium_vol_low_end(self):
        self.assertEqual(self.opt._determine_optimal_fee(5.0, 0.3), 30)

    def test_medium_vol_mid_range(self):
        self.assertEqual(self.opt._determine_optimal_fee(15.0, 0.5), 30)

    def test_medium_vol_high_end(self):
        self.assertEqual(self.opt._determine_optimal_fee(29.99, 0.0), 30)

    def test_high_vol_low_end(self):
        self.assertEqual(self.opt._determine_optimal_fee(30.0, 0.0), 100)

    def test_high_vol_mid_range(self):
        self.assertEqual(self.opt._determine_optimal_fee(55.0, 0.2), 100)

    def test_high_vol_upper_boundary(self):
        self.assertEqual(self.opt._determine_optimal_fee(79.99, 0.0), 100)

    def test_exotic_vol(self):
        self.assertEqual(self.opt._determine_optimal_fee(80.0, 0.0), 500)

    def test_exotic_extreme_vol(self):
        self.assertEqual(self.opt._determine_optimal_fee(200.0, 0.1), 500)

    def test_zero_volatility_zero_correlation(self):
        # vol=0 < 5 → stable → 5
        self.assertEqual(self.opt._determine_optimal_fee(0.0, 0.0), 5)


# ---------------------------------------------------------------------------
# 2. Label determination
# ---------------------------------------------------------------------------

class TestDetermineLabel(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def test_optimal_tier_exact_match(self):
        self.assertEqual(self.opt._determine_label(5, 5, 0.0), "OPTIMAL_TIER")

    def test_optimal_tier_mismatch_zero(self):
        self.assertEqual(self.opt._determine_label(30, 30, 0.0), "OPTIMAL_TIER")

    def test_extreme_mismatch_over_100(self):
        # current=500, optimal=30 → mismatch=1566%
        mismatch = abs(500 - 30) / 30 * 100
        self.assertEqual(
            self.opt._determine_label(500, 30, mismatch), "EXTREME_MISMATCH"
        )

    def test_extreme_mismatch_exactly_101(self):
        self.assertEqual(self.opt._determine_label(100, 5, 101.0), "EXTREME_MISMATCH")

    def test_significantly_misaligned_over_50(self):
        self.assertEqual(
            self.opt._determine_label(100, 30, 66.67), "SIGNIFICANTLY_MISALIGNED"
        )

    def test_significantly_misaligned_at_boundary(self):
        self.assertEqual(
            self.opt._determine_label(50, 30, 51.0), "SIGNIFICANTLY_MISALIGNED"
        )

    def test_slightly_overpriced(self):
        # current=100, optimal=30, mismatch=233% → EXTREME
        # Let's use current=40, optimal=30 → mismatch=33%
        self.assertEqual(
            self.opt._determine_label(100, 30, 33.3), "SLIGHTLY_OVERPRICED"
        )

    def test_slightly_overpriced_small_mismatch(self):
        # current > optimal but mismatch small
        self.assertEqual(
            self.opt._determine_label(30, 5, 20.0), "SLIGHTLY_OVERPRICED"
        )

    def test_slightly_underpriced(self):
        self.assertEqual(
            self.opt._determine_label(5, 30, 83.33), "SIGNIFICANTLY_MISALIGNED"
        )

    def test_slightly_underpriced_small(self):
        # current=5, optimal=30 → mismatch=500% → EXTREME. Use 30 vs 100 at 30%
        self.assertEqual(
            self.opt._determine_label(30, 100, 30.0), "SLIGHTLY_UNDERPRICED"
        )

    def test_label_overpriced_not_extreme(self):
        # current=100, optimal=30, 33% → SLIGHTLY_OVERPRICED... but 100>30 mismatch=233%→EXTREME
        # Let's construct a case: mismatch=40%, current>optimal
        self.assertEqual(
            self.opt._determine_label(100, 5, 40.0), "SLIGHTLY_OVERPRICED"
        )

    def test_slightly_underpriced_low_mismatch(self):
        self.assertEqual(
            self.opt._determine_label(5, 30, 10.0), "SLIGHTLY_UNDERPRICED"
        )


# ---------------------------------------------------------------------------
# 3. Flag computation
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def _flags(self, **kw):
        defaults = dict(
            correlation=0.0,
            current_fee=30,
            volatility=15.0,
            arb_pct=10.0,
            tick_tightness=20.0,
            label="OPTIMAL_TIER",
            mismatch_score=0.0,
        )
        defaults.update(kw)
        return self.opt._compute_flags(**defaults)

    def test_no_flags_baseline(self):
        self.assertEqual(self._flags(), [])

    def test_fee_too_high_for_stable(self):
        f = self._flags(correlation=0.97, current_fee=100)
        self.assertIn("FEE_TOO_HIGH_FOR_STABLE", f)

    def test_fee_too_high_for_stable_boundary_fee(self):
        # fee must be > 30 (not >=)
        f = self._flags(correlation=0.96, current_fee=31)
        self.assertIn("FEE_TOO_HIGH_FOR_STABLE", f)

    def test_no_fee_too_high_for_stable_when_fee_30(self):
        f = self._flags(correlation=0.97, current_fee=30)
        self.assertNotIn("FEE_TOO_HIGH_FOR_STABLE", f)

    def test_fee_too_low_for_volatile(self):
        f = self._flags(volatility=60.0, current_fee=30)
        self.assertIn("FEE_TOO_LOW_FOR_VOLATILE", f)

    def test_fee_too_low_for_volatile_at_boundary(self):
        # volatility must be > 50 AND fee < 100
        f = self._flags(volatility=50.01, current_fee=99)
        self.assertIn("FEE_TOO_LOW_FOR_VOLATILE", f)

    def test_no_fee_too_low_when_fee_100(self):
        f = self._flags(volatility=60.0, current_fee=100)
        self.assertNotIn("FEE_TOO_LOW_FOR_VOLATILE", f)

    def test_arbitrage_dominated(self):
        f = self._flags(arb_pct=65.0)
        self.assertIn("ARBITRAGE_DOMINATED", f)

    def test_no_arbitrage_dominated_at_60(self):
        f = self._flags(arb_pct=60.0)
        self.assertNotIn("ARBITRAGE_DOMINATED", f)

    def test_concentrated_liquidity_efficient(self):
        f = self._flags(tick_tightness=55.0, label="OPTIMAL_TIER")
        self.assertIn("CONCENTRATED_LIQUIDITY_EFFICIENT", f)

    def test_no_cl_efficient_if_not_optimal(self):
        f = self._flags(tick_tightness=55.0, label="SLIGHTLY_OVERPRICED")
        self.assertNotIn("CONCENTRATED_LIQUIDITY_EFFICIENT", f)

    def test_switch_recommended_mismatch_over_40(self):
        f = self._flags(mismatch_score=41.0)
        self.assertIn("SWITCH_RECOMMENDED", f)

    def test_no_switch_recommended_at_40(self):
        f = self._flags(mismatch_score=40.0)
        self.assertNotIn("SWITCH_RECOMMENDED", f)

    def test_multiple_flags(self):
        f = self._flags(
            correlation=0.97, current_fee=500,
            volatility=10.0, arb_pct=70.0,
            mismatch_score=200.0,
        )
        self.assertIn("FEE_TOO_HIGH_FOR_STABLE", f)
        self.assertIn("ARBITRAGE_DOMINATED", f)
        self.assertIn("SWITCH_RECOMMENDED", f)

    def test_flags_are_list(self):
        self.assertIsInstance(self._flags(), list)


# ---------------------------------------------------------------------------
# 4. Fee revenue calculation
# ---------------------------------------------------------------------------

class TestFeeRevenueCalculation(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def _run(self, pool):
        return self.opt._analyze_pool(pool)

    def test_basic_fee_revenue(self):
        pool = make_pool(volume_24h_usd=1_000_000, current_fee_tier_bps=30)
        result = self._run(pool)
        # 1_000_000 * 30 / 10_000 = 3_000
        self.assertAlmostEqual(result["fee_revenue_daily_usd"], 3000.0, places=2)

    def test_fee_revenue_5bps(self):
        pool = make_pool(volume_24h_usd=10_000_000, current_fee_tier_bps=5)
        result = self._run(pool)
        # 10_000_000 * 5 / 10_000 = 5_000
        self.assertAlmostEqual(result["fee_revenue_daily_usd"], 5000.0, places=2)

    def test_fee_revenue_500bps(self):
        pool = make_pool(volume_24h_usd=500_000, current_fee_tier_bps=500)
        result = self._run(pool)
        # 500_000 * 500 / 10_000 = 25_000
        self.assertAlmostEqual(result["fee_revenue_daily_usd"], 25000.0, places=2)

    def test_fee_revenue_zero_volume(self):
        pool = make_pool(volume_24h_usd=0, current_fee_tier_bps=100)
        result = self._run(pool)
        self.assertEqual(result["fee_revenue_daily_usd"], 0.0)

    def test_fee_revenue_100bps(self):
        pool = make_pool(volume_24h_usd=2_000_000, current_fee_tier_bps=100)
        result = self._run(pool)
        # 2_000_000 * 100 / 10_000 = 20_000
        self.assertAlmostEqual(result["fee_revenue_daily_usd"], 20000.0, places=2)

    def test_fee_revenue_stored_in_result(self):
        pool = make_pool()
        result = self._run(pool)
        self.assertIn("fee_revenue_daily_usd", result)


# ---------------------------------------------------------------------------
# 5. Fee APY calculation
# ---------------------------------------------------------------------------

class TestFeeAPYCalculation(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def _run(self, pool):
        return self.opt._analyze_pool(pool)

    def test_basic_apy(self):
        pool = make_pool(
            volume_24h_usd=1_000_000, tvl_usd=10_000_000,
            current_fee_tier_bps=30,
        )
        result = self._run(pool)
        # revenue=3000, apy = 3000*365/10_000_000*100 = 10.95%
        self.assertAlmostEqual(result["fee_apy_pct"], 10.95, places=2)

    def test_high_volume_high_apy(self):
        pool = make_pool(
            volume_24h_usd=10_000_000, tvl_usd=1_000_000,
            current_fee_tier_bps=100,
        )
        result = self._run(pool)
        # revenue=100_000, apy = 100_000*365/1_000_000*100 = 3650%
        self.assertAlmostEqual(result["fee_apy_pct"], 3650.0, places=0)

    def test_zero_volume_zero_apy(self):
        pool = make_pool(volume_24h_usd=0, tvl_usd=1_000_000)
        result = self._run(pool)
        self.assertEqual(result["fee_apy_pct"], 0.0)

    def test_apy_scales_with_fee_tier(self):
        pool5 = make_pool(current_fee_tier_bps=5, volume_24h_usd=1_000_000, tvl_usd=5_000_000)
        pool30 = make_pool(current_fee_tier_bps=30, volume_24h_usd=1_000_000, tvl_usd=5_000_000)
        r5 = self._run(pool5)
        r30 = self._run(pool30)
        self.assertLess(r5["fee_apy_pct"], r30["fee_apy_pct"])

    def test_apy_field_present(self):
        pool = make_pool()
        result = self._run(pool)
        self.assertIn("fee_apy_pct", result)

    def test_apy_non_negative(self):
        pool = make_pool(volume_24h_usd=500_000, tvl_usd=5_000_000)
        result = self._run(pool)
        self.assertGreaterEqual(result["fee_apy_pct"], 0.0)


# ---------------------------------------------------------------------------
# 6. Arbitrage drag calculation
# ---------------------------------------------------------------------------

class TestArbitrageDragCalculation(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def _run(self, pool):
        return self.opt._analyze_pool(pool)

    def test_basic_arb_drag(self):
        pool = make_pool(
            volume_24h_usd=1_000_000, tvl_usd=10_000_000,
            current_fee_tier_bps=30, arbitrage_volume_pct=50.0,
        )
        result = self._run(pool)
        # drag = (50/100)*1_000_000*30/10_000 / 10_000_000 * 365 * 100
        # = 0.5 * 3000 / 10_000_000 * 365 * 100
        # = 1500 / 10_000_000 * 36500 = 5.475%
        self.assertAlmostEqual(result["arbitrage_drag_pct"], 5.475, places=3)

    def test_zero_arb_drag(self):
        pool = make_pool(arbitrage_volume_pct=0.0)
        result = self._run(pool)
        self.assertEqual(result["arbitrage_drag_pct"], 0.0)

    def test_100pct_arb_drag(self):
        pool = make_pool(arbitrage_volume_pct=100.0, volume_24h_usd=1_000_000,
                         tvl_usd=10_000_000, current_fee_tier_bps=30)
        result = self._run(pool)
        self.assertGreater(result["arbitrage_drag_pct"], 0.0)

    def test_arb_drag_stored(self):
        pool = make_pool()
        result = self._run(pool)
        self.assertIn("arbitrage_drag_pct", result)

    def test_arb_drag_scales_with_arb_pct(self):
        pool_low = make_pool(arbitrage_volume_pct=10.0)
        pool_high = make_pool(arbitrage_volume_pct=80.0)
        r_low = self._run(pool_low)
        r_high = self._run(pool_high)
        self.assertLess(r_low["arbitrage_drag_pct"], r_high["arbitrage_drag_pct"])

    def test_arb_drag_non_negative(self):
        pool = make_pool(arbitrage_volume_pct=30.0)
        result = self._run(pool)
        self.assertGreaterEqual(result["arbitrage_drag_pct"], 0.0)


# ---------------------------------------------------------------------------
# 7. Mismatch score
# ---------------------------------------------------------------------------

class TestMismatchScore(unittest.TestCase):

    def setUp(self):
        self.opt = DeFiProtocolFeeTierOptimizer()

    def _run(self, pool):
        return self.opt._analyze_pool(pool)

    def test_zero_mismatch_optimal(self):
        # stable pair, fee=5
        pool = make_pool(
            current_fee_tier_bps=5, correlation_with_eth=0.99,
            price_volatility_30d_pct=0.5,
        )
        result = self._run(pool)
        self.assertEqual(result["fee_tier_mismatch_score"], 0.0)

    def test_mismatch_30_vs_5(self):
        # current=30, optimal=5 → |30-5|/5*100 = 500%
        pool = make_pool(
            current_fee_tier_bps=30, correlation_with_eth=0.99,
            price_volatility_30d_pct=0.5,
        )
        result = self._run(pool)
        self.assertAlmostEqual(result["fee_tier_mismatch_score"], 500.0, places=1)

    def test_mismatch_5_vs_30(self):
        # medium vol, current=5, optimal=30 → |5-30|/30*100 = 83.33%
        pool = make_pool(
            current_fee_tier_bps=5, correlation_with_eth=0.0,
            price_volatility_30d_pct=15.0,
        )
        result = self._run(pool)
        self.assertAlmostEqual(result["fee_tier_mismatch_score"], 83.33, places=1)

    def test_mismatch_100_vs_30(self):
        # high vol pair but fee=30, optimal=100 → |30-100|/100*100=70%
        pool = make_pool(
            current_fee_tier_bps=30, correlation_with_eth=0.0,
            price_volatility_30d_pct=50.0,
        )
        result = self._run(pool)
        self.assertAlmostEqual(result["fee_tier_mismatch_score"], 70.0, places=1)

    def test_mismatch_field_present(self):
        pool = make_pool()
        result = self._run(pool)
        self.assertIn("fee_tier_mismatch_score", result)

    def test_mismatch_non_negative(self):
        pool = make_pool(current_fee_tier_bps=100, price_volatility_30d_pct=20.0)
        result = self._run(pool)
        self.assertGreaterEqual(result["fee_tier_mismatch_score"], 0.0)

    def test_mismatch_100_vs_500(self):
        # exotic pool, current=100, optimal=500 → |100-500|/500*100=80%
        pool = make_pool(
            current_fee_tier_bps=100, correlation_with_eth=0.0,
            price_volatility_30d_pct=90.0,
        )
        result = self._run(pool)
        self.assertAlmostEqual(result["fee_tier_mismatch_score"], 80.0, places=1)

    def test_mismatch_500_vs_5(self):
        # stable pair with 500bps fee → extreme
        pool = make_pool(
            current_fee_tier_bps=500, correlation_with_eth=0.99,
            price_volatility_30d_pct=0.5,
        )
        result = self._run(pool)
        self.assertAlmostEqual(result["fee_tier_mismatch_score"], 9900.0, places=0)


# ---------------------------------------------------------------------------
# 8. Optimize — basic API
# ---------------------------------------------------------------------------

class TestOptimizeBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def test_returns_dict(self):
        result = self.opt.optimize([make_pool()], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_required_top_level_keys(self):
        result = self.opt.optimize([make_pool()], {"log_enabled": False})
        for key in ("timestamp", "module", "mp", "pool_count", "pools", "aggregates"):
            self.assertIn(key, result)

    def test_module_name(self):
        result = self.opt.optimize([make_pool()], {"log_enabled": False})
        self.assertEqual(result["module"], "DeFiProtocolFeeTierOptimizer")

    def test_mp_number(self):
        result = self.opt.optimize([make_pool()], {"log_enabled": False})
        self.assertEqual(result["mp"], "MP-1000")

    def test_pool_count(self):
        result = self.opt.optimize([make_pool(), make_pool(name="P2")], {"log_enabled": False})
        self.assertEqual(result["pool_count"], 2)

    def test_empty_pools(self):
        result = self.opt.optimize([], {"log_enabled": False})
        self.assertEqual(result["pool_count"], 0)
        self.assertEqual(result["pools"], [])

    def test_raises_on_non_list_pools(self):
        with self.assertRaises(TypeError):
            self.opt.optimize("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.opt.optimize([], "not_a_dict")

    def test_pool_result_fields(self):
        result = self.opt.optimize([make_pool()], {"log_enabled": False})
        pool_res = result["pools"][0]
        for field in (
            "name", "token_pair", "current_fee_tier_bps",
            "fee_revenue_daily_usd", "fee_apy_pct", "arbitrage_drag_pct",
            "optimal_fee_bps", "fee_tier_mismatch_score", "label", "flags",
        ):
            self.assertIn(field, pool_res)


# ---------------------------------------------------------------------------
# 9. Multiple pools
# ---------------------------------------------------------------------------

class TestMultiplePools(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def _run(self, pools):
        return self.opt.optimize(pools, {"log_enabled": False})

    def test_three_pools(self):
        pools = [
            make_pool(name="A"),
            make_pool(name="B", price_volatility_30d_pct=20.0, current_fee_tier_bps=30),
            make_pool(name="C", price_volatility_30d_pct=60.0, current_fee_tier_bps=100),
        ]
        result = self._run(pools)
        self.assertEqual(result["pool_count"], 3)

    def test_pools_list_length(self):
        pools = [make_pool(name=f"P{i}") for i in range(5)]
        result = self._run(pools)
        self.assertEqual(len(result["pools"]), 5)

    def test_each_pool_has_label(self):
        pools = [make_pool(name=f"P{i}") for i in range(3)]
        result = self._run(pools)
        for p in result["pools"]:
            self.assertIn(p["label"], {
                "OPTIMAL_TIER", "SLIGHTLY_OVERPRICED", "SLIGHTLY_UNDERPRICED",
                "SIGNIFICANTLY_MISALIGNED", "EXTREME_MISMATCH",
            })

    def test_each_pool_has_flags_list(self):
        pools = [make_pool(name=f"P{i}") for i in range(3)]
        result = self._run(pools)
        for p in result["pools"]:
            self.assertIsInstance(p["flags"], list)

    def test_mixed_labels(self):
        pools = [
            make_pool(name="Stable", current_fee_tier_bps=5,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
            make_pool(name="Overpriced", current_fee_tier_bps=500,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
        ]
        result = self._run(pools)
        labels = {p["name"]: p["label"] for p in result["pools"]}
        self.assertEqual(labels["Stable"], "OPTIMAL_TIER")
        self.assertNotEqual(labels["Overpriced"], "OPTIMAL_TIER")

    def test_optimal_count_in_aggregates(self):
        pools = [
            make_pool(name="A", current_fee_tier_bps=5,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
            make_pool(name="B", current_fee_tier_bps=5,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
            make_pool(name="C", current_fee_tier_bps=500,
                      correlation_with_eth=0.0, price_volatility_30d_pct=20.0),
        ]
        result = self._run(pools)
        self.assertEqual(result["aggregates"]["optimal_count"], 2)


# ---------------------------------------------------------------------------
# 10. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def _run(self, pools):
        return self.opt.optimize(pools, {"log_enabled": False})["aggregates"]

    def test_empty_aggregates(self):
        agg = self._run([])
        self.assertIsNone(agg["most_optimized"])
        self.assertIsNone(agg["worst_mismatch"])
        self.assertEqual(agg["avg_fee_apy"], 0.0)
        self.assertEqual(agg["optimal_count"], 0)
        self.assertEqual(agg["extreme_mismatch_count"], 0)

    def test_most_optimized_single(self):
        agg = self._run([make_pool(name="Solo")])
        self.assertEqual(agg["most_optimized"], "Solo")

    def test_worst_mismatch_single(self):
        agg = self._run([make_pool(name="Solo")])
        self.assertEqual(agg["worst_mismatch"], "Solo")

    def test_most_optimized_picks_lowest_mismatch(self):
        pools = [
            make_pool(name="Good", current_fee_tier_bps=5,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
            make_pool(name="Bad", current_fee_tier_bps=500,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
        ]
        agg = self._run(pools)
        self.assertEqual(agg["most_optimized"], "Good")

    def test_worst_mismatch_picks_highest_mismatch(self):
        pools = [
            make_pool(name="Good", current_fee_tier_bps=5,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
            make_pool(name="Bad", current_fee_tier_bps=500,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
        ]
        agg = self._run(pools)
        self.assertEqual(agg["worst_mismatch"], "Bad")

    def test_avg_fee_apy_single_pool(self):
        pool = make_pool(
            volume_24h_usd=1_000_000, tvl_usd=10_000_000,
            current_fee_tier_bps=30,
        )
        agg = self._run([pool])
        # 3000 * 365 / 10_000_000 * 100 = 10.95
        self.assertAlmostEqual(agg["avg_fee_apy"], 10.95, places=2)

    def test_avg_fee_apy_two_pools(self):
        pool1 = make_pool(name="P1",
                          volume_24h_usd=1_000_000, tvl_usd=10_000_000,
                          current_fee_tier_bps=30)
        pool2 = make_pool(name="P2",
                          volume_24h_usd=2_000_000, tvl_usd=10_000_000,
                          current_fee_tier_bps=30)
        agg = self._run([pool1, pool2])
        # apy1=10.95, apy2=21.9 → avg=16.425
        self.assertAlmostEqual(agg["avg_fee_apy"], 16.425, places=2)

    def test_optimal_count_zero(self):
        pools = [
            make_pool(name="A", current_fee_tier_bps=500,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
        ]
        agg = self._run(pools)
        self.assertEqual(agg["optimal_count"], 0)

    def test_extreme_mismatch_count(self):
        pools = [
            # stable pair but 500bps → extreme
            make_pool(name="X", current_fee_tier_bps=500,
                      correlation_with_eth=0.99, price_volatility_30d_pct=1.0),
        ]
        agg = self._run(pools)
        self.assertEqual(agg["extreme_mismatch_count"], 1)

    def test_aggregate_keys(self):
        agg = self._run([make_pool()])
        for k in ("most_optimized", "worst_mismatch", "avg_fee_apy",
                  "optimal_count", "extreme_mismatch_count"):
            self.assertIn(k, agg)


# ---------------------------------------------------------------------------
# 11. Ring-buffer log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)
        self.log_path = os.path.join(self.tmp, "fee_tier_optimization_log.json")

    def _run(self, pools=None, enabled=True):
        pools = pools or [make_pool()]
        return self.opt.optimize(pools, {"log_enabled": enabled})

    def test_log_created_when_enabled(self):
        self._run()
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_grows_with_each_call(self):
        self._run()
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_log_entry_has_timestamp(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("timestamp", log[0])

    def test_log_entry_has_pool_count(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("pool_count", log[0])

    def test_log_entry_has_aggregates(self):
        self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("aggregates", log[0])

    def test_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 5):
            self._run()
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), LOG_CAP)

    def test_no_log_when_disabled(self):
        self._run(enabled=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_atomic_write_no_tmp_remaining(self):
        self._run()
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_log_pool_count_correct(self):
        pools = [make_pool(name=f"P{i}") for i in range(3)]
        self._run(pools)
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(log[0]["pool_count"], 3)


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def _run(self, pool):
        return self.opt.optimize([pool], {"log_enabled": False})["pools"][0]

    def test_zero_tvl_uses_default(self):
        pool = make_pool(tvl_usd=0)
        result = self._run(pool)
        # Should not raise; TVL clamped to 1
        self.assertGreaterEqual(result["fee_apy_pct"], 0.0)

    def test_negative_tvl_treated_as_one(self):
        pool = make_pool(tvl_usd=-100_000)
        result = self._run(pool)
        self.assertGreaterEqual(result["fee_apy_pct"], 0.0)

    def test_missing_optional_fields_defaults(self):
        pool = {"name": "Minimal"}
        result = self._run(pool)
        self.assertIn("label", result)
        self.assertIn("flags", result)

    def test_extra_fields_ignored(self):
        pool = make_pool(extra_field="ignored")
        result = self._run(pool)
        self.assertIn("label", result)

    def test_large_volume(self):
        pool = make_pool(volume_24h_usd=1e12, tvl_usd=1e10)
        result = self._run(pool)
        self.assertGreater(result["fee_revenue_daily_usd"], 0)

    def test_100pct_arbitrage(self):
        pool = make_pool(arbitrage_volume_pct=100.0)
        result = self._run(pool)
        self.assertIn("ARBITRAGE_DOMINATED", result["flags"])

    def test_names_preserved(self):
        pool = make_pool(name="MySpecialPool", token_pair="WBTC/ETH")
        result = self._run(pool)
        self.assertEqual(result["name"], "MySpecialPool")
        self.assertEqual(result["token_pair"], "WBTC/ETH")

    def test_optimal_fee_in_result(self):
        pool = make_pool(price_volatility_30d_pct=60.0, correlation_with_eth=0.0)
        result = self._run(pool)
        self.assertEqual(result["optimal_fee_bps"], 100)


# ---------------------------------------------------------------------------
# 13. Config handling
# ---------------------------------------------------------------------------

class TestConfigHandling(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def test_log_enabled_default_true(self):
        log_path = os.path.join(self.tmp, "fee_tier_optimization_log.json")
        self.opt.optimize([make_pool()], {})
        self.assertTrue(os.path.exists(log_path))

    def test_log_enabled_false_no_file(self):
        log_path = os.path.join(self.tmp, "fee_tier_optimization_log.json")
        self.opt.optimize([make_pool()], {"log_enabled": False})
        self.assertFalse(os.path.exists(log_path))

    def test_custom_data_dir_in_config(self):
        tmp2 = tempfile.mkdtemp()
        self.opt.optimize([make_pool()], {"data_dir": tmp2})
        log_path = os.path.join(tmp2, "fee_tier_optimization_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_empty_config_ok(self):
        result = self.opt.optimize([make_pool()], {})
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# 14. Label integration tests
# ---------------------------------------------------------------------------

class TestLabelIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = DeFiProtocolFeeTierOptimizer(data_dir=self.tmp)

    def _label(self, pool):
        return self.opt.optimize([pool], {"log_enabled": False})["pools"][0]["label"]

    def test_optimal_tier_stable_5bps(self):
        pool = make_pool(
            current_fee_tier_bps=5, correlation_with_eth=0.99,
            price_volatility_30d_pct=1.0,
        )
        self.assertEqual(self._label(pool), "OPTIMAL_TIER")

    def test_optimal_tier_medium_30bps(self):
        pool = make_pool(
            current_fee_tier_bps=30, correlation_with_eth=0.0,
            price_volatility_30d_pct=15.0,
        )
        self.assertEqual(self._label(pool), "OPTIMAL_TIER")

    def test_optimal_tier_high_100bps(self):
        pool = make_pool(
            current_fee_tier_bps=100, correlation_with_eth=0.0,
            price_volatility_30d_pct=50.0,
        )
        self.assertEqual(self._label(pool), "OPTIMAL_TIER")

    def test_optimal_tier_exotic_500bps(self):
        pool = make_pool(
            current_fee_tier_bps=500, correlation_with_eth=0.0,
            price_volatility_30d_pct=90.0,
        )
        self.assertEqual(self._label(pool), "OPTIMAL_TIER")

    def test_slightly_overpriced(self):
        # medium vol pair (optimal=30), fee=100 → mismatch=233% → EXTREME
        # Use optimal=5 stable, fee=30 → mismatch=500% → EXTREME
        # Use optimal=100 high, fee=30 is underpriced
        # Let me use a case where mismatch ≤ 50: need |c-o|/o ≤ 50 AND c>o
        # optimal=100, current=130 → not a valid tier but let's test the label method directly
        label = self.opt._determine_label(current=100, optimal=30, mismatch=33.3)
        self.assertEqual(label, "SLIGHTLY_OVERPRICED")

    def test_slightly_underpriced(self):
        label = self.opt._determine_label(current=30, optimal=100, mismatch=30.0)
        self.assertEqual(label, "SLIGHTLY_UNDERPRICED")

    def test_significantly_misaligned(self):
        label = self.opt._determine_label(current=100, optimal=30, mismatch=66.0)
        self.assertEqual(label, "SIGNIFICANTLY_MISALIGNED")

    def test_extreme_mismatch(self):
        # stable pair with 500bps → mismatch=9900%
        pool = make_pool(
            current_fee_tier_bps=500, correlation_with_eth=0.99,
            price_volatility_30d_pct=1.0,
        )
        self.assertEqual(self._label(pool), "EXTREME_MISMATCH")


# ---------------------------------------------------------------------------
# 15. Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_valid_fee_tiers(self):
        self.assertIn(5, VALID_FEE_TIERS)
        self.assertIn(30, VALID_FEE_TIERS)
        self.assertIn(100, VALID_FEE_TIERS)
        self.assertIn(500, VALID_FEE_TIERS)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


if __name__ == "__main__":
    unittest.main()
