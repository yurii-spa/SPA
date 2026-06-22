#!/usr/bin/env python3
"""Tests for defi_slippage_impact_estimator (MP-868 / SPA-V672).

Run with:
    python3 -m unittest spa_core.tests.test_defi_slippage_impact_estimator -v
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.defi_slippage_impact_estimator import (
    _compute_price_impact_pct,
    _effective_liquidity,
    _load_log,
    _recommendation,
    _save_log,
    _slippage_label,
    analyze,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(
    protocol="TestDEX",
    token_pair="USDC/ETH",
    pool_liquidity_usd=1_000_000.0,
    trade_size_usd=10_000.0,
    pool_fee_pct=0.3,
    pool_type="CONSTANT_PRODUCT",
    concentration_factor=1.0,
    price_impact_observed_pct=None,
):
    return {
        "protocol": protocol,
        "token_pair": token_pair,
        "pool_liquidity_usd": pool_liquidity_usd,
        "trade_size_usd": trade_size_usd,
        "pool_fee_pct": pool_fee_pct,
        "pool_type": pool_type,
        "concentration_factor": concentration_factor,
        "price_impact_observed_pct": price_impact_observed_pct,
    }


# ===========================================================================
# _effective_liquidity tests
# ===========================================================================
class TestEffectiveLiquidity(unittest.TestCase):

    def test_concentration_1_returns_pool_liquidity(self):
        self.assertAlmostEqual(_effective_liquidity(1_000_000, 1.0), 1_000_000.0)

    def test_concentration_0_5_halves_liquidity(self):
        self.assertAlmostEqual(_effective_liquidity(1_000_000, 0.5), 500_000.0)

    def test_concentration_zero_returns_pool_liquidity(self):
        # concentration=0 → fall back to pool_liquidity
        self.assertAlmostEqual(_effective_liquidity(500_000, 0.0), 500_000.0)

    def test_concentration_negative_returns_pool_liquidity(self):
        self.assertAlmostEqual(_effective_liquidity(300_000, -0.5), 300_000.0)

    def test_concentration_0_4(self):
        self.assertAlmostEqual(_effective_liquidity(10_000_000, 0.4), 4_000_000.0)

    def test_concentration_1_0_edge(self):
        self.assertAlmostEqual(_effective_liquidity(0.0, 1.0), 0.0)


# ===========================================================================
# _compute_price_impact_pct tests
# ===========================================================================
class TestComputePriceImpactPct(unittest.TestCase):

    def test_constant_product_small_trade(self):
        # 1000 / (100000 + 1000) * 100 = ~0.99%
        impact = _compute_price_impact_pct(1000.0, 100_000.0, "CONSTANT_PRODUCT")
        expected = 1000 / (100_000 + 1000) * 100
        self.assertAlmostEqual(impact, expected, places=8)

    def test_constant_product_large_trade(self):
        # 50000 / (100000 + 50000) * 100 = 33.33%
        impact = _compute_price_impact_pct(50_000.0, 100_000.0, "CONSTANT_PRODUCT")
        self.assertAlmostEqual(impact, 33.333333, places=4)

    def test_stable_swap_is_10x_less_than_constant_product(self):
        cp_impact = _compute_price_impact_pct(5000.0, 200_000.0, "CONSTANT_PRODUCT")
        ss_impact = _compute_price_impact_pct(5000.0, 200_000.0, "STABLE_SWAP")
        self.assertAlmostEqual(ss_impact, cp_impact * 0.1, places=8)

    def test_stable_swap_small_value(self):
        # Large pool, small trade → tiny impact * 0.1
        impact = _compute_price_impact_pct(1000.0, 100_000_000.0, "STABLE_SWAP")
        self.assertLess(impact, 0.01)

    def test_concentrated_same_as_constant_product(self):
        # CONCENTRATED uses same formula as CONSTANT_PRODUCT
        cp = _compute_price_impact_pct(10_000.0, 500_000.0, "CONSTANT_PRODUCT")
        conc = _compute_price_impact_pct(10_000.0, 500_000.0, "CONCENTRATED")
        self.assertAlmostEqual(cp, conc, places=8)

    def test_zero_effective_liquidity_returns_100(self):
        impact = _compute_price_impact_pct(10_000.0, 0.0, "CONSTANT_PRODUCT")
        self.assertAlmostEqual(impact, 100.0, places=4)

    def test_zero_effective_liquidity_stable_returns_10(self):
        impact = _compute_price_impact_pct(10_000.0, 0.0, "STABLE_SWAP")
        self.assertAlmostEqual(impact, 10.0, places=4)

    def test_trade_equals_liquidity(self):
        # 100000 / (100000 + 100000) * 100 = 50%
        impact = _compute_price_impact_pct(100_000.0, 100_000.0, "CONSTANT_PRODUCT")
        self.assertAlmostEqual(impact, 50.0, places=4)

    def test_very_small_trade_near_zero_impact(self):
        impact = _compute_price_impact_pct(1.0, 1_000_000_000.0, "CONSTANT_PRODUCT")
        self.assertLess(impact, 0.001)


# ===========================================================================
# _slippage_label tests
# ===========================================================================
class TestSlippageLabel(unittest.TestCase):

    def test_minimal_zero(self):
        self.assertEqual(_slippage_label(0.0), "MINIMAL")

    def test_minimal_at_boundary(self):
        self.assertEqual(_slippage_label(0.1), "MINIMAL")

    def test_acceptable_just_above_minimal(self):
        self.assertEqual(_slippage_label(0.11), "ACCEPTABLE")

    def test_acceptable_at_boundary(self):
        self.assertEqual(_slippage_label(0.5), "ACCEPTABLE")

    def test_notable_just_above_acceptable(self):
        self.assertEqual(_slippage_label(0.51), "NOTABLE")

    def test_notable_at_boundary(self):
        self.assertEqual(_slippage_label(1.0), "NOTABLE")

    def test_high_just_above_notable(self):
        self.assertEqual(_slippage_label(1.01), "HIGH")

    def test_high_at_boundary(self):
        self.assertEqual(_slippage_label(3.0), "HIGH")

    def test_severe_just_above_high(self):
        self.assertEqual(_slippage_label(3.01), "SEVERE")

    def test_severe_large_value(self):
        self.assertEqual(_slippage_label(50.0), "SEVERE")


# ===========================================================================
# _recommendation tests
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_minimal_contains_excellent(self):
        rec = _recommendation("MINIMAL", 0.05, "USDC/ETH")
        self.assertIn("Excellent", rec)
        self.assertIn("USDC/ETH", rec)
        self.assertIn("0.050%", rec)

    def test_acceptable_contains_proceed(self):
        rec = _recommendation("ACCEPTABLE", 0.35, "DAI/USDT")
        self.assertIn("Proceed with trade", rec)
        self.assertIn("0.35%", rec)

    def test_notable_contains_split(self):
        rec = _recommendation("NOTABLE", 0.75, "WBTC/ETH")
        self.assertIn("splitting trade", rec)
        self.assertIn("0.75%", rec)

    def test_high_contains_limit_orders(self):
        rec = _recommendation("HIGH", 2.5, "USDC/WETH")
        self.assertIn("limit orders", rec)
        self.assertIn("2.50%", rec)

    def test_severe_contains_too_large(self):
        rec = _recommendation("SEVERE", 8.0, "ETH/BTC")
        self.assertIn("SEVERE", rec)
        self.assertIn("too large", rec)
        self.assertIn("8.00%", rec)


# ===========================================================================
# analyze() integration tests
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_trades(self):
        result = analyze([])
        self.assertEqual(result["trades"], [])
        self.assertIsNone(result["worst_slippage_trade"])
        self.assertIsNone(result["best_execution_trade"])
        self.assertEqual(result["trades_above_threshold"], 0)
        self.assertEqual(result["average_total_cost_pct"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_trade_constant_product(self):
        t = _trade(
            protocol="UniswapV2",
            token_pair="USDC/ETH",
            pool_liquidity_usd=1_000_000,
            trade_size_usd=10_000,
            pool_fee_pct=0.3,
            pool_type="CONSTANT_PRODUCT",
            concentration_factor=1.0,
        )
        result = analyze([t])
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        # expected_impact = 10000/(1000000+10000)*100 ≈ 0.99%
        expected_impact = 10000 / (1_000_000 + 10_000) * 100
        self.assertAlmostEqual(trade["estimated_price_impact_pct"], expected_impact, places=3)
        expected_cost = expected_impact + 0.3
        self.assertAlmostEqual(trade["total_cost_pct"], expected_cost, places=3)

    def test_stable_swap_lower_impact(self):
        t = _trade(
            pool_type="STABLE_SWAP",
            pool_liquidity_usd=10_000_000,
            trade_size_usd=100_000,
            pool_fee_pct=0.04,
            concentration_factor=1.0,
        )
        result = analyze([t])
        trade = result["trades"][0]
        # price_impact = (100000/(10100000))*100*0.1 ≈ 0.099%, total = 0.099+0.04 = 0.139%
        # 0.139 > 0.1 → ACCEPTABLE (not MINIMAL)
        self.assertLess(trade["estimated_price_impact_pct"], 0.2)
        self.assertIn(trade["slippage_label"], ("MINIMAL", "ACCEPTABLE"))

    def test_concentrated_pool_with_concentration_factor(self):
        t = _trade(
            pool_type="CONCENTRATED",
            pool_liquidity_usd=10_000_000,
            trade_size_usd=100_000,
            pool_fee_pct=0.05,
            concentration_factor=0.3,
        )
        result = analyze([t])
        trade = result["trades"][0]
        # effective_liq = 10_000_000 * 0.3 = 3_000_000
        # impact = 100000/(3000000+100000)*100 ≈ 3.125%
        expected_eff_liq = 3_000_000.0
        self.assertAlmostEqual(trade["effective_liquidity_usd"], expected_eff_liq, places=0)
        expected_impact = 100_000 / (3_000_000 + 100_000) * 100
        self.assertAlmostEqual(trade["estimated_price_impact_pct"], expected_impact, places=3)

    def test_observed_impact_overrides_computed(self):
        t = _trade(
            pool_liquidity_usd=1_000_000,
            trade_size_usd=10_000,
            pool_fee_pct=0.3,
            pool_type="CONSTANT_PRODUCT",
            price_impact_observed_pct=2.5,
        )
        result = analyze([t])
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["estimated_price_impact_pct"], 2.5, places=6)

    def test_net_received_pct_correct(self):
        t = _trade(pool_fee_pct=0.3, pool_type="CONSTANT_PRODUCT",
                   pool_liquidity_usd=1_000_000, trade_size_usd=10_000)
        result = analyze([t])
        trade = result["trades"][0]
        expected_net = max(0.0, 100.0 - trade["total_cost_pct"])
        self.assertAlmostEqual(trade["net_received_pct"], expected_net, places=4)

    def test_net_received_pct_never_negative(self):
        # Extreme case: enormous trade, tiny pool
        t = _trade(pool_liquidity_usd=1000, trade_size_usd=1_000_000_000, pool_fee_pct=50.0)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertGreaterEqual(trade["net_received_pct"], 0.0)

    def test_is_above_threshold_true(self):
        # With default acceptable_slippage=0.5, total_cost > 0.5 → True
        t = _trade(pool_liquidity_usd=10_000, trade_size_usd=5_000, pool_fee_pct=0.5)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertTrue(trade["is_above_threshold"])

    def test_is_above_threshold_false(self):
        # Tiny trade in huge pool, fee=0.1 → total cost minimal
        t = _trade(pool_liquidity_usd=100_000_000, trade_size_usd=100, pool_fee_pct=0.1)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertFalse(trade["is_above_threshold"])

    def test_custom_acceptable_slippage_threshold(self):
        t = _trade(pool_liquidity_usd=100_000_000, trade_size_usd=100, pool_fee_pct=0.1)
        result = analyze([t], config={"acceptable_slippage_pct": 0.0})
        trade = result["trades"][0]
        # total_cost > 0.0 → above threshold
        self.assertTrue(trade["is_above_threshold"])

    def test_trades_above_threshold_count(self):
        t1 = _trade(pool_liquidity_usd=100_000_000, trade_size_usd=100, pool_fee_pct=0.1)
        t2 = _trade(pool_liquidity_usd=10_000, trade_size_usd=5_000, pool_fee_pct=1.0)
        result = analyze([t1, t2])
        self.assertEqual(result["trades_above_threshold"], 1)

    def test_worst_slippage_trade_format(self):
        t1 = _trade(protocol="Aave", token_pair="USDC/ETH",
                    pool_liquidity_usd=100_000_000, trade_size_usd=100)
        t2 = _trade(protocol="UniV2", token_pair="DAI/WETH",
                    pool_liquidity_usd=10_000, trade_size_usd=5_000)
        result = analyze([t1, t2])
        self.assertEqual(result["worst_slippage_trade"], "UniV2 DAI/WETH")

    def test_best_execution_trade_format(self):
        t1 = _trade(protocol="Aave", token_pair="USDC/ETH",
                    pool_liquidity_usd=100_000_000, trade_size_usd=100, pool_fee_pct=0.01)
        t2 = _trade(protocol="UniV2", token_pair="DAI/WETH",
                    pool_liquidity_usd=10_000, trade_size_usd=5_000)
        result = analyze([t1, t2])
        self.assertEqual(result["best_execution_trade"], "Aave USDC/ETH")

    def test_average_total_cost_computed(self):
        t1 = _trade(pool_liquidity_usd=100_000_000, trade_size_usd=100, pool_fee_pct=0.1)
        t2 = _trade(pool_liquidity_usd=100_000, trade_size_usd=10_000, pool_fee_pct=0.3)
        result = analyze([t1, t2])
        costs = [r["total_cost_pct"] for r in result["trades"]]
        expected_avg = sum(costs) / len(costs)
        self.assertAlmostEqual(result["average_total_cost_pct"], expected_avg, places=4)

    def test_output_keys_complete(self):
        result = analyze([_trade()])
        for key in [
            "trades", "worst_slippage_trade", "best_execution_trade",
            "trades_above_threshold", "average_total_cost_pct", "timestamp",
        ]:
            self.assertIn(key, result)

    def test_trade_output_keys_complete(self):
        result = analyze([_trade()])
        trade = result["trades"][0]
        for key in [
            "protocol", "token_pair", "trade_size_usd", "pool_liquidity_usd",
            "estimated_price_impact_pct", "total_cost_pct", "net_received_pct",
            "slippage_label", "is_above_threshold", "effective_liquidity_usd",
            "trade_size_ratio", "recommendation",
        ]:
            self.assertIn(key, trade)

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([_trade()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_trade_size_ratio_computed(self):
        t = _trade(pool_liquidity_usd=1_000_000, trade_size_usd=10_000, concentration_factor=0.5)
        result = analyze([t])
        trade = result["trades"][0]
        # effective_liq = 500_000, ratio = 10_000 / 500_000 = 0.02
        self.assertAlmostEqual(trade["trade_size_ratio"], 0.02, places=6)

    def test_trade_size_ratio_zero_liq(self):
        t = _trade(pool_liquidity_usd=0.0, trade_size_usd=1000.0, concentration_factor=1.0)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["trade_size_ratio"], 1.0, places=6)

    def test_effective_liquidity_in_output(self):
        t = _trade(pool_liquidity_usd=2_000_000, concentration_factor=0.5)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["effective_liquidity_usd"], 1_000_000.0, places=0)

    def test_protocol_and_pair_preserved(self):
        t = _trade(protocol="MorphoBlue", token_pair="wstETH/USDC")
        result = analyze([t])
        trade = result["trades"][0]
        self.assertEqual(trade["protocol"], "MorphoBlue")
        self.assertEqual(trade["token_pair"], "wstETH/USDC")

    def test_pool_fee_included_in_total_cost(self):
        t = _trade(
            pool_liquidity_usd=1_000_000_000,  # huge pool → near-zero impact
            trade_size_usd=1.0,
            pool_fee_pct=0.3,
            pool_type="CONSTANT_PRODUCT",
        )
        result = analyze([t])
        trade = result["trades"][0]
        # total_cost ≈ 0 + 0.3 = 0.3
        self.assertAlmostEqual(trade["total_cost_pct"], 0.3, delta=0.001)

    def test_severe_slippage_label(self):
        t = _trade(pool_liquidity_usd=1000, trade_size_usd=1_000_000, pool_fee_pct=1.0)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertEqual(trade["slippage_label"], "SEVERE")

    def test_minimal_slippage_label(self):
        t = _trade(pool_liquidity_usd=1_000_000_000, trade_size_usd=100, pool_fee_pct=0.05)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertEqual(trade["slippage_label"], "MINIMAL")

    def test_concentration_zero_falls_back_to_pool_liquidity(self):
        t = _trade(pool_liquidity_usd=1_000_000, concentration_factor=0.0, trade_size_usd=10_000)
        result = analyze([t])
        trade = result["trades"][0]
        # effective_liq = pool_liquidity = 1_000_000
        self.assertAlmostEqual(trade["effective_liquidity_usd"], 1_000_000.0, places=0)

    def test_none_config_accepted(self):
        result = analyze([_trade()], config=None)
        self.assertIn("trades", result)

    def test_empty_config_accepted(self):
        result = analyze([_trade()], config={})
        self.assertIn("trades", result)

    def test_three_trades_worst_and_best(self):
        t1 = _trade(protocol="A", token_pair="X/Y",
                    pool_liquidity_usd=1_000_000_000, trade_size_usd=10, pool_fee_pct=0.01)
        t2 = _trade(protocol="B", token_pair="Y/Z",
                    pool_liquidity_usd=100_000, trade_size_usd=50_000, pool_fee_pct=0.3)
        t3 = _trade(protocol="C", token_pair="A/B",
                    pool_liquidity_usd=50_000, trade_size_usd=25_000, pool_fee_pct=0.5)
        result = analyze([t1, t2, t3])
        self.assertEqual(result["best_execution_trade"], "A X/Y")
        # B and C need to check which has higher cost
        costs = {r["protocol"]: r["total_cost_pct"] for r in result["trades"]}
        worst_proto = max(costs, key=lambda k: costs[k])
        self.assertIn(worst_proto, result["worst_slippage_trade"])

    def test_single_trade_worst_equals_best(self):
        result = analyze([_trade(protocol="Solo", token_pair="A/B")])
        self.assertEqual(result["worst_slippage_trade"], "Solo A/B")
        self.assertEqual(result["best_execution_trade"], "Solo A/B")

    def test_all_trades_above_threshold(self):
        trades = [
            _trade(pool_liquidity_usd=1000, trade_size_usd=10_000, pool_fee_pct=5.0),
            _trade(pool_liquidity_usd=500, trade_size_usd=5_000, pool_fee_pct=3.0),
        ]
        result = analyze(trades, config={"acceptable_slippage_pct": 0.0})
        self.assertEqual(result["trades_above_threshold"], 2)

    def test_no_trades_above_threshold(self):
        trades = [
            _trade(pool_liquidity_usd=1_000_000_000, trade_size_usd=1, pool_fee_pct=0.01),
        ]
        result = analyze(trades, config={"acceptable_slippage_pct": 100.0})
        self.assertEqual(result["trades_above_threshold"], 0)

    def test_recommendation_string_type(self):
        result = analyze([_trade()])
        self.assertIsInstance(result["trades"][0]["recommendation"], str)

    def test_price_impact_non_negative(self):
        t = _trade()
        result = analyze([t])
        self.assertGreaterEqual(result["trades"][0]["estimated_price_impact_pct"], 0.0)

    def test_total_cost_at_least_fee(self):
        t = _trade(pool_fee_pct=0.3)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertGreaterEqual(trade["total_cost_pct"], 0.3)

    def test_stable_swap_impact_much_less_than_cp(self):
        kwargs = dict(
            pool_liquidity_usd=1_000_000,
            trade_size_usd=50_000,
            pool_fee_pct=0.0,
            concentration_factor=1.0,
        )
        cp_result = analyze([_trade(pool_type="CONSTANT_PRODUCT", **kwargs)])
        ss_result = analyze([_trade(pool_type="STABLE_SWAP", **kwargs)])
        cp_impact = cp_result["trades"][0]["estimated_price_impact_pct"]
        ss_impact = ss_result["trades"][0]["estimated_price_impact_pct"]
        self.assertLess(ss_impact, cp_impact)

    def test_observed_impact_none_uses_model(self):
        t = _trade(price_impact_observed_pct=None, pool_liquidity_usd=1_000_000,
                   trade_size_usd=10_000, pool_fee_pct=0.0, pool_type="CONSTANT_PRODUCT")
        result = analyze([t])
        expected = 10_000 / (1_000_000 + 10_000) * 100
        self.assertAlmostEqual(result["trades"][0]["estimated_price_impact_pct"], expected, places=4)


# ===========================================================================
# Ring-buffer log tests
# ===========================================================================
class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.tmp_dir) / "data" / "slippage_impact_log.json"

    def test_save_and_load(self):
        entries = [{"x": 1}, {"y": 2}]
        _save_log(self.log_path, entries)
        loaded = _load_log(self.log_path)
        self.assertEqual(loaded, entries)

    def test_ring_buffer_cap_at_100(self):
        entries = [{"i": i} for i in range(110)]
        _save_log(self.log_path, entries)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 100)
        self.assertEqual(loaded[0]["i"], 10)
        self.assertEqual(loaded[-1]["i"], 109)

    def test_load_nonexistent_returns_empty(self):
        path = Path(self.tmp_dir) / "no_file.json"
        self.assertEqual(_load_log(path), [])

    def test_load_corrupt_returns_empty(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("{bad json")
        self.assertEqual(_load_log(self.log_path), [])

    def test_run_creates_log_file(self):
        run([_trade()], data_dir=self.tmp_dir)
        self.assertTrue(self.log_path.exists())

    def test_run_appends_to_log(self):
        run([_trade()], data_dir=self.tmp_dir)
        run([_trade()], data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 2)

    def test_run_overflow_stays_at_100(self):
        for _ in range(105):
            run([_trade()], data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 100)

    def test_run_returns_result(self):
        result = run([_trade()], data_dir=self.tmp_dir)
        self.assertIn("trades", result)

    def test_run_empty_trades_logged(self):
        result = run([], data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["trades"], [])

    def test_atomic_write_via_replace(self):
        # Multiple rapid saves shouldn't corrupt
        for i in range(10):
            _save_log(self.log_path, [{"n": i}])
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["n"], 9)


# ===========================================================================
# Edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_trade_size_zero(self):
        t = _trade(trade_size_usd=0.0)
        result = analyze([t])
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["estimated_price_impact_pct"], 0.0, places=6)

    def test_both_pool_and_trade_zero(self):
        t = _trade(pool_liquidity_usd=0.0, trade_size_usd=0.0)
        result = analyze([t])
        trade = result["trades"][0]
        # 0/(0+0) → effective_liq=0 → impact=100? No: trade_size=0 → 0/(0+0) but handled
        # Actually: eff_liq=0, trade_size=0 → denominator=0+0=0 → division by zero
        # Our model: if eff_liq <= 0 → base=100%; trade_size=0 → 0/(0+0)*100=0 but eff_liq≤0
        # Check: trade_size_ratio = 0/0 → should be 1.0 (fallback), impact=100 for 0 liq
        self.assertGreaterEqual(trade["estimated_price_impact_pct"], 0.0)

    def test_observation_overrides_even_if_zero(self):
        t = _trade(price_impact_observed_pct=0.0, pool_liquidity_usd=1000,
                   trade_size_usd=500, pool_type="CONSTANT_PRODUCT")
        result = analyze([t])
        self.assertAlmostEqual(result["trades"][0]["estimated_price_impact_pct"], 0.0, places=6)

    def test_high_fee_pushes_to_severe(self):
        t = _trade(pool_liquidity_usd=1_000_000_000, trade_size_usd=1, pool_fee_pct=5.0)
        result = analyze([t])
        self.assertEqual(result["trades"][0]["slippage_label"], "SEVERE")

    def test_concentrated_with_low_concentration_increases_impact(self):
        t_high = _trade(pool_type="CONCENTRATED", pool_liquidity_usd=10_000_000,
                        trade_size_usd=100_000, concentration_factor=1.0)
        t_low = _trade(pool_type="CONCENTRATED", pool_liquidity_usd=10_000_000,
                       trade_size_usd=100_000, concentration_factor=0.1)
        r_high = analyze([t_high])
        r_low = analyze([t_low])
        self.assertLess(
            r_high["trades"][0]["estimated_price_impact_pct"],
            r_low["trades"][0]["estimated_price_impact_pct"],
        )

    def test_recommendation_contains_cost(self):
        t = _trade(pool_liquidity_usd=1_000_000_000, trade_size_usd=10, pool_fee_pct=0.05)
        result = analyze([t])
        rec = result["trades"][0]["recommendation"]
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_output_is_json_serializable(self):
        result = analyze([_trade()])
        # Should not raise
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)

    def test_multiple_pool_types_all_process(self):
        trades = [
            _trade(pool_type="CONSTANT_PRODUCT"),
            _trade(pool_type="STABLE_SWAP"),
            _trade(pool_type="CONCENTRATED"),
        ]
        result = analyze(trades)
        self.assertEqual(len(result["trades"]), 3)

    def test_trade_size_ratio_with_full_concentration(self):
        t = _trade(pool_liquidity_usd=1_000_000, trade_size_usd=50_000, concentration_factor=1.0)
        result = analyze([t])
        self.assertAlmostEqual(result["trades"][0]["trade_size_ratio"], 0.05, places=4)

    def test_average_cost_single_trade(self):
        result = analyze([_trade()])
        self.assertAlmostEqual(
            result["average_total_cost_pct"],
            result["trades"][0]["total_cost_pct"],
            places=4,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
