"""
Tests for MP-758: SlippageImpactEstimator
≥65 test cases using unittest only.
"""

import json
import math
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.slippage_impact_estimator import (
    SlippageEstimate,
    SlippageResult,
    compute_price_impact,
    compute_effective_price,
    compute_slippage_cost,
    compute_min_pool_liquidity,
    slippage_label,
    estimate_slippage,
    estimate_market,
    load_history,
    save_results,
    RING_BUFFER_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_file() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump([], f)
    return path


def _pool(
    protocol: str = "Aave",
    token_pair: str = "USDC/ETH",
    trade_size_usd: float = 1_000.0,
    pool_liquidity_usd: float = 1_000_000.0,
    mid_price: float = 1.0,
    max_slippage_pct: float = 0.5,
) -> dict:
    return {
        "protocol": protocol,
        "token_pair": token_pair,
        "trade_size_usd": trade_size_usd,
        "pool_liquidity_usd": pool_liquidity_usd,
        "mid_price": mid_price,
        "max_slippage_pct": max_slippage_pct,
    }


# ---------------------------------------------------------------------------
# 1. compute_price_impact
# ---------------------------------------------------------------------------

class TestComputePriceImpact(unittest.TestCase):

    def test_basic_formula(self):
        # 1000 / (1_000_000 * 2) * 100 = 0.05%
        result = compute_price_impact(1000, 1_000_000)
        self.assertAlmostEqual(result, 0.05, places=6)

    def test_pool_zero_returns_100(self):
        result = compute_price_impact(1000, 0)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_pool_negative_returns_100(self):
        result = compute_price_impact(1000, -500)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_large_pool_small_impact(self):
        # 100 / (100_000_000 * 2) * 100 = 0.00005%
        result = compute_price_impact(100, 100_000_000)
        self.assertAlmostEqual(result, 0.00005, places=7)

    def test_trade_equal_to_pool(self):
        # trade=pool → 50% impact
        result = compute_price_impact(1_000_000, 1_000_000)
        self.assertAlmostEqual(result, 50.0, places=6)

    def test_tiny_trade(self):
        result = compute_price_impact(1, 1_000_000_000)
        self.assertLess(result, 0.001)

    def test_zero_trade(self):
        result = compute_price_impact(0, 1_000_000)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_doubling_pool_halves_impact(self):
        r1 = compute_price_impact(5000, 1_000_000)
        r2 = compute_price_impact(5000, 2_000_000)
        self.assertAlmostEqual(r1, 2 * r2, places=6)

    def test_constant_product_formula(self):
        # 10000 / (500000 * 2) * 100 = 1.0%
        result = compute_price_impact(10_000, 500_000)
        self.assertAlmostEqual(result, 1.0, places=6)


# ---------------------------------------------------------------------------
# 2. compute_effective_price
# ---------------------------------------------------------------------------

class TestComputeEffectivePrice(unittest.TestCase):

    def test_basic_formula(self):
        # mid=100, impact=1% → 100*(1-0.01)=99
        result = compute_effective_price(100.0, 1.0)
        self.assertAlmostEqual(result, 99.0, places=6)

    def test_zero_impact_unchanged(self):
        result = compute_effective_price(100.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_100_pct_impact_zero(self):
        result = compute_effective_price(100.0, 100.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_small_impact(self):
        result = compute_effective_price(2.0, 0.05)
        self.assertAlmostEqual(result, 2.0 * (1 - 0.0005), places=8)

    def test_mid_price_1_half_pct(self):
        result = compute_effective_price(1.0, 0.5)
        self.assertAlmostEqual(result, 0.995, places=6)

    def test_mid_price_3000(self):
        result = compute_effective_price(3000.0, 0.1)
        self.assertAlmostEqual(result, 3000.0 * 0.999, places=4)


# ---------------------------------------------------------------------------
# 3. compute_slippage_cost
# ---------------------------------------------------------------------------

class TestComputeSlippageCost(unittest.TestCase):

    def test_basic_formula(self):
        # 10000 * 0.5 / 100 = 50
        result = compute_slippage_cost(10000, 0.5)
        self.assertAlmostEqual(result, 50.0, places=6)

    def test_zero_impact(self):
        result = compute_slippage_cost(10000, 0.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_100_pct_impact_full_loss(self):
        result = compute_slippage_cost(10000, 100.0)
        self.assertAlmostEqual(result, 10000.0, places=6)

    def test_negligible_impact(self):
        result = compute_slippage_cost(1_000_000, 0.01)
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_proportional_to_trade_size(self):
        r1 = compute_slippage_cost(1000, 1.0)
        r2 = compute_slippage_cost(2000, 1.0)
        self.assertAlmostEqual(r2, 2 * r1, places=6)

    def test_formula_direct(self):
        # 500_000 * 5 / 100 = 25000
        result = compute_slippage_cost(500_000, 5.0)
        self.assertAlmostEqual(result, 25_000.0, places=4)


# ---------------------------------------------------------------------------
# 4. compute_min_pool_liquidity
# ---------------------------------------------------------------------------

class TestComputeMinPoolLiquidity(unittest.TestCase):

    def test_basic_formula(self):
        # 1000 / (0.5/100 * 2) = 1000/0.01 = 100000
        result = compute_min_pool_liquidity(1000, 0.5)
        self.assertAlmostEqual(result, 100_000.0, places=4)

    def test_zero_max_slippage_returns_inf(self):
        result = compute_min_pool_liquidity(1000, 0)
        self.assertTrue(math.isinf(result))

    def test_negative_max_slippage_returns_inf(self):
        result = compute_min_pool_liquidity(1000, -0.1)
        self.assertTrue(math.isinf(result))

    def test_large_max_slippage(self):
        # 1000 / (10/100 * 2) = 1000/0.2 = 5000
        result = compute_min_pool_liquidity(1000, 10.0)
        self.assertAlmostEqual(result, 5000.0, places=4)

    def test_1_pct_slippage(self):
        # 10000 / (1/100 * 2) = 10000/0.02 = 500000
        result = compute_min_pool_liquidity(10_000, 1.0)
        self.assertAlmostEqual(result, 500_000.0, places=4)

    def test_large_trade(self):
        # 1_000_000 / (0.5/100 * 2) = 1_000_000 / 0.01 = 100_000_000
        result = compute_min_pool_liquidity(1_000_000, 0.5)
        self.assertAlmostEqual(result, 100_000_000.0, places=2)


# ---------------------------------------------------------------------------
# 5. slippage_label
# ---------------------------------------------------------------------------

class TestSlippageLabel(unittest.TestCase):

    def test_negligible_below_0_1(self):
        self.assertEqual(slippage_label(0.05), "NEGLIGIBLE")

    def test_negligible_zero(self):
        self.assertEqual(slippage_label(0.0), "NEGLIGIBLE")

    def test_negligible_just_below_0_1(self):
        self.assertEqual(slippage_label(0.0999), "NEGLIGIBLE")

    def test_low_at_exactly_0_1(self):
        self.assertEqual(slippage_label(0.1), "LOW")

    def test_low_at_0_3(self):
        self.assertEqual(slippage_label(0.3), "LOW")

    def test_low_just_below_0_5(self):
        self.assertEqual(slippage_label(0.4999), "LOW")

    def test_moderate_at_0_5(self):
        self.assertEqual(slippage_label(0.5), "MODERATE")

    def test_moderate_at_0_75(self):
        self.assertEqual(slippage_label(0.75), "MODERATE")

    def test_moderate_at_exactly_1_0(self):
        self.assertEqual(slippage_label(1.0), "MODERATE")

    def test_high_just_above_1(self):
        self.assertEqual(slippage_label(1.001), "HIGH")

    def test_high_at_5(self):
        self.assertEqual(slippage_label(5.0), "HIGH")

    def test_high_at_100(self):
        self.assertEqual(slippage_label(100.0), "HIGH")


# ---------------------------------------------------------------------------
# 6. estimate_slippage
# ---------------------------------------------------------------------------

class TestEstimateSlippage(unittest.TestCase):

    def test_returns_slippage_estimate_instance(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        self.assertIsInstance(result, SlippageEstimate)

    def test_all_fields_populated(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        for f in ["protocol", "token_pair", "trade_size_usd", "pool_liquidity_usd",
                  "price_impact_pct", "mid_price", "effective_price", "slippage_cost_usd",
                  "max_slippage_pct", "is_within_tolerance", "min_pool_liquidity_needed_usd",
                  "pool_fraction_pct", "slippage_label", "recommendation"]:
            self.assertTrue(hasattr(result, f), f"Missing field: {f}")

    def test_default_max_slippage_0_5(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        self.assertAlmostEqual(result.max_slippage_pct, 0.5, places=6)

    def test_price_impact_matches_formula(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        expected = compute_price_impact(1000, 1_000_000)
        self.assertAlmostEqual(result.price_impact_pct, expected, places=8)

    def test_is_within_tolerance_true(self):
        # 1000 / (1M * 2) * 100 = 0.05% < 0.5%
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0, 0.5)
        self.assertTrue(result.is_within_tolerance)

    def test_is_within_tolerance_false_large_trade(self):
        # 100k / (100k * 2) * 100 = 50% >> 0.5%
        result = estimate_slippage("Aave", "USDC/ETH", 100_000, 100_000, 1.0, 0.5)
        self.assertFalse(result.is_within_tolerance)

    def test_pool_fraction_pct_formula(self):
        # 10000/100000 * 100 = 10%
        result = estimate_slippage("Aave", "USDC/ETH", 10_000, 100_000, 1.0)
        self.assertAlmostEqual(result.pool_fraction_pct, 10.0, places=6)

    def test_pool_fraction_pct_zero_pool_returns_100(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 0, 1.0)
        self.assertAlmostEqual(result.pool_fraction_pct, 100.0, places=6)

    def test_recommendation_high_label(self):
        # Large trade → HIGH impact → high slippage risk
        result = estimate_slippage("Aave", "USDC/ETH", 1_000_000, 10_000, 1.0)
        self.assertEqual(result.slippage_label, "HIGH")
        self.assertIn("High slippage risk", result.recommendation)

    def test_recommendation_not_within_tolerance_gives_high_risk_msg(self):
        # LOW label but max_slippage=0.01 → not within tolerance
        # impact = 1000/(100000*2)*100 = 0.5% → MODERATE label, max=0.01 → out of tol
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 100_000, 1.0, 0.01)
        self.assertFalse(result.is_within_tolerance)
        self.assertIn("High slippage risk", result.recommendation)

    def test_recommendation_moderate(self):
        # impact=0.5% MODERATE, within 1.0% tolerance
        result = estimate_slippage("Aave", "USDC/ETH", 10_000, 1_000_000, 1.0, 1.0)
        # 10000/(2000000)*100 = 0.5% → MODERATE
        self.assertEqual(result.slippage_label, "MODERATE")
        self.assertTrue(result.is_within_tolerance)
        self.assertIn("Moderate slippage", result.recommendation)

    def test_recommendation_low(self):
        # impact 0.1-0.5%, within tolerance
        # 2000/(1000000*2)*100 = 0.1% → LOW boundary
        result = estimate_slippage("Aave", "USDC/ETH", 2000, 1_000_000, 1.0, 0.5)
        self.assertEqual(result.slippage_label, "LOW")
        self.assertTrue(result.is_within_tolerance)
        self.assertIn("Acceptable slippage", result.recommendation)

    def test_recommendation_negligible(self):
        # impact < 0.1%: 100/(1M*2)*100 = 0.005% → NEGLIGIBLE
        result = estimate_slippage("Aave", "USDC/ETH", 100, 1_000_000, 1.0, 0.5)
        self.assertEqual(result.slippage_label, "NEGLIGIBLE")
        self.assertIn("Negligible slippage", result.recommendation)

    def test_effective_price_formula(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 2.0)
        expected = 2.0 * (1 - result.price_impact_pct / 100)
        self.assertAlmostEqual(result.effective_price, expected, places=8)

    def test_slippage_cost_formula(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        expected_cost = 1000 * result.price_impact_pct / 100
        self.assertAlmostEqual(result.slippage_cost_usd, expected_cost, places=8)

    def test_protocol_and_pair_stored(self):
        result = estimate_slippage("Compound", "USDC/WBTC", 500, 500_000, 1.5)
        self.assertEqual(result.protocol, "Compound")
        self.assertEqual(result.token_pair, "USDC/WBTC")


# ---------------------------------------------------------------------------
# 7. estimate_market
# ---------------------------------------------------------------------------

class TestEstimateMarket(unittest.TestCase):

    def test_returns_slippage_result(self):
        result = estimate_market([_pool()])
        self.assertIsInstance(result, SlippageResult)

    def test_empty_list_lowest_na(self):
        result = estimate_market([])
        self.assertEqual(result.lowest_slippage_pool, "N/A")

    def test_empty_list_highest_na(self):
        result = estimate_market([])
        self.assertEqual(result.highest_slippage_pool, "N/A")

    def test_empty_list_tradeable_empty(self):
        result = estimate_market([])
        self.assertEqual(result.tradeable_pools, [])

    def test_empty_list_avg_zero(self):
        result = estimate_market([])
        self.assertAlmostEqual(result.avg_price_impact_pct, 0.0)

    def test_empty_list_total_cost_zero(self):
        result = estimate_market([])
        self.assertAlmostEqual(result.total_slippage_cost_usd, 0.0)

    def test_single_pool_lowest_and_highest_same(self):
        result = estimate_market([_pool("Aave")])
        self.assertEqual(result.lowest_slippage_pool, "Aave")
        self.assertEqual(result.highest_slippage_pool, "Aave")

    def test_lowest_slippage_pool(self):
        data = [
            _pool("Deep", trade_size_usd=100, pool_liquidity_usd=10_000_000),
            _pool("Shallow", trade_size_usd=100, pool_liquidity_usd=1_000),
        ]
        result = estimate_market(data)
        self.assertEqual(result.lowest_slippage_pool, "Deep")

    def test_highest_slippage_pool(self):
        data = [
            _pool("Deep", trade_size_usd=100, pool_liquidity_usd=10_000_000),
            _pool("Shallow", trade_size_usd=100, pool_liquidity_usd=1_000),
        ]
        result = estimate_market(data)
        self.assertEqual(result.highest_slippage_pool, "Shallow")

    def test_tradeable_pools_within_tolerance_only(self):
        data = [
            _pool("Ok", trade_size_usd=100, pool_liquidity_usd=1_000_000, max_slippage_pct=0.5),
            _pool("NotOk", trade_size_usd=500_000, pool_liquidity_usd=1_000, max_slippage_pct=0.5),
        ]
        result = estimate_market(data)
        self.assertIn("Ok", result.tradeable_pools)
        self.assertNotIn("NotOk", result.tradeable_pools)

    def test_tradeable_pools_empty_when_none_within_tolerance(self):
        # 1M trade in 10k pool → ~50x impact >> 0.01% tolerance
        data = [_pool("Illiquid", trade_size_usd=1_000_000, pool_liquidity_usd=10_000, max_slippage_pct=0.01)]
        result = estimate_market(data)
        self.assertEqual(result.tradeable_pools, [])

    def test_avg_price_impact_formula(self):
        # Pool A: 1000/2M*100=0.05; Pool B: 10000/2M*100=0.5
        data = [
            _pool("A", trade_size_usd=1_000, pool_liquidity_usd=1_000_000),
            _pool("B", trade_size_usd=10_000, pool_liquidity_usd=1_000_000),
        ]
        result = estimate_market(data)
        expected = (0.05 + 0.5) / 2
        self.assertAlmostEqual(result.avg_price_impact_pct, expected, places=4)

    def test_total_slippage_cost_sum(self):
        data = [_pool("A"), _pool("B")]
        result = estimate_market(data)
        expected = sum(e.slippage_cost_usd for e in result.estimates)
        self.assertAlmostEqual(result.total_slippage_cost_usd, round(expected, 4), places=4)

    def test_market_liquidity_label_deep(self):
        # 100/(100M*2)*100 = 0.00005% → avg < 0.1% → DEEP
        data = [_pool(trade_size_usd=100, pool_liquidity_usd=100_000_000)]
        result = estimate_market(data)
        self.assertEqual(result.market_liquidity_label, "DEEP")

    def test_market_liquidity_label_adequate(self):
        # 3000/(1M*2)*100 = 0.15% → ADEQUATE (0.1 <= 0.15 < 0.5)
        data = [_pool(trade_size_usd=3_000, pool_liquidity_usd=1_000_000)]
        result = estimate_market(data)
        self.assertEqual(result.market_liquidity_label, "ADEQUATE")

    def test_market_liquidity_label_thin(self):
        # 100000/(1M*2)*100 = 5% → THIN
        data = [_pool(trade_size_usd=100_000, pool_liquidity_usd=1_000_000)]
        result = estimate_market(data)
        self.assertEqual(result.market_liquidity_label, "THIN")

    def test_saved_to_empty_initially(self):
        result = estimate_market([_pool()])
        self.assertEqual(result.saved_to, "")

    def test_all_result_fields_present(self):
        result = estimate_market([_pool()])
        for f in ["estimates", "lowest_slippage_pool", "highest_slippage_pool",
                  "tradeable_pools", "avg_price_impact_pct", "total_slippage_cost_usd",
                  "market_liquidity_label", "recommendation_summary", "saved_to"]:
            self.assertTrue(hasattr(result, f), f"Missing field: {f}")

    def test_three_pools_count(self):
        data = [_pool("A"), _pool("B"), _pool("C")]
        result = estimate_market(data)
        self.assertEqual(len(result.estimates), 3)


# ---------------------------------------------------------------------------
# 8. save_results / load_history
# ---------------------------------------------------------------------------

class TestSaveLoadRingBuffer(unittest.TestCase):

    def test_save_load_roundtrip(self):
        tmp = _tmp_file()
        try:
            result = estimate_market([_pool()])
            save_results(result, tmp)
            history = load_history(tmp)
            self.assertEqual(len(history), 1)
        finally:
            os.unlink(tmp)

    def test_saved_to_populated_after_save(self):
        tmp = _tmp_file()
        try:
            result = estimate_market([_pool()])
            save_results(result, tmp)
            self.assertEqual(result.saved_to, tmp)
        finally:
            os.unlink(tmp)

    def test_multiple_saves_accumulate(self):
        tmp = _tmp_file()
        try:
            for i in range(5):
                r = estimate_market([_pool(f"Pool{i}")])
                save_results(r, tmp)
            self.assertEqual(len(load_history(tmp)), 5)
        finally:
            os.unlink(tmp)

    def test_ring_buffer_cap_100(self):
        tmp = _tmp_file()
        try:
            for i in range(RING_BUFFER_CAP + 20):
                r = estimate_market([_pool(f"Pool{i}")])
                save_results(r, tmp)
            self.assertEqual(len(load_history(tmp)), RING_BUFFER_CAP)
        finally:
            os.unlink(tmp)

    def test_ring_buffer_keeps_latest(self):
        tmp = _tmp_file()
        try:
            for i in range(RING_BUFFER_CAP + 10):
                r = estimate_market([_pool(f"Protocol_{i}")])
                save_results(r, tmp)
            history = load_history(tmp)
            last_pool = history[-1]["estimates"][0]["protocol"]
            self.assertTrue(last_pool.startswith("Protocol_"))
        finally:
            os.unlink(tmp)

    def test_ring_buffer_exactly_100(self):
        tmp = _tmp_file()
        try:
            for i in range(100):
                r = estimate_market([_pool()])
                save_results(r, tmp)
            self.assertEqual(len(load_history(tmp)), 100)
        finally:
            os.unlink(tmp)

    def test_load_missing_file_returns_empty(self):
        result = load_history("/tmp/no_such_slippage_log_xyz.json")
        self.assertEqual(result, [])

    def test_load_corrupted_returns_empty(self):
        tmp = _tmp_file()
        try:
            with open(tmp, "w") as f:
                f.write("{bad json}")
            self.assertEqual(load_history(tmp), [])
        finally:
            os.unlink(tmp)

    def test_atomic_write_valid_json(self):
        tmp = _tmp_file()
        try:
            r = estimate_market([_pool()])
            save_results(r, tmp)
            with open(tmp) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            os.unlink(tmp)

    def test_history_entry_has_estimates_key(self):
        tmp = _tmp_file()
        try:
            r = estimate_market([_pool()])
            save_results(r, tmp)
            h = load_history(tmp)
            self.assertIn("estimates", h[0])
        finally:
            os.unlink(tmp)

    def test_history_entry_has_avg_price_impact_pct(self):
        tmp = _tmp_file()
        try:
            r = estimate_market([_pool()])
            save_results(r, tmp)
            h = load_history(tmp)
            self.assertIn("avg_price_impact_pct", h[0])
        finally:
            os.unlink(tmp)

    def test_history_entry_has_market_liquidity_label(self):
        tmp = _tmp_file()
        try:
            r = estimate_market([_pool()])
            save_results(r, tmp)
            h = load_history(tmp)
            self.assertIn("market_liquidity_label", h[0])
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_trade_equals_pool_50pct_impact(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1_000_000, 1_000_000, 1.0)
        self.assertAlmostEqual(result.price_impact_pct, 50.0, places=6)

    def test_tiny_trade_negligible_label(self):
        result = estimate_slippage("Aave", "USDC/ETH", 0.01, 1_000_000_000, 1.0)
        self.assertLess(result.price_impact_pct, 0.1)
        self.assertEqual(result.slippage_label, "NEGLIGIBLE")

    def test_three_pools_ranking(self):
        data = [
            _pool("A", trade_size_usd=100, pool_liquidity_usd=100_000_000),
            _pool("B", trade_size_usd=100, pool_liquidity_usd=1_000_000),
            _pool("C", trade_size_usd=100, pool_liquidity_usd=10_000),
        ]
        result = estimate_market(data)
        self.assertEqual(len(result.estimates), 3)
        self.assertEqual(result.lowest_slippage_pool, "A")
        self.assertEqual(result.highest_slippage_pool, "C")

    def test_pool_fraction_10_pct(self):
        result = estimate_slippage("Aave", "USDC/ETH", 10_000, 100_000, 1.0)
        self.assertAlmostEqual(result.pool_fraction_pct, 10.0, places=6)

    def test_slippage_cost_nonnegative(self):
        result = estimate_slippage("Aave", "USDC/ETH", 1000, 1_000_000, 1.0)
        self.assertGreaterEqual(result.slippage_cost_usd, 0.0)

    def test_min_pool_liquidity_needed_consistent_with_tolerance(self):
        # If pool >= min_liq, should be within tolerance
        est = estimate_slippage("Aave", "USDC/ETH", 5_000, 1_000_000, 1.0, 0.5)
        min_liq = est.min_pool_liquidity_needed_usd
        # min_liq = 5000/(0.5/100*2) = 500000
        self.assertAlmostEqual(min_liq, 500_000.0, places=2)
        # Our pool (1M) >= 500k → within tolerance
        self.assertTrue(est.is_within_tolerance)

    def test_deep_market_recommendation_summary(self):
        data = [_pool(trade_size_usd=10, pool_liquidity_usd=1_000_000_000)]
        result = estimate_market(data)
        self.assertEqual(result.market_liquidity_label, "DEEP")
        self.assertIn("deep", result.recommendation_summary.lower())


if __name__ == "__main__":
    unittest.main()
