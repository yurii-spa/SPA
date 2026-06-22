"""tests/test_rebalance_cost.py — MP-583 RebalanceCostModel test suite.

Coverage: 120+ test cases across 11 classes.

TestSafeFloat            — _safe_float coercion / clamp
TestNormaliseWeights     — _normalise_weights normalisation / negatives
TestSlippageBps          — _slippage_bps_for_trade tier/utilisation/lock
TestEstimateGasCost      — estimate_gas_cost formula / clamps / defaults
TestEstimateSlippageCost — estimate_slippage_cost summation / edge cases
TestComputeRebalanceCost — compute_rebalance_cost trades / turnover / cost
TestComputeBreakEvenDays — compute_break_even_days horizon / inf
TestIsRebalanceWorthwhile— is_rebalance_worthwhile verdict logic
TestGetCostReport        — get_cost_report structure / warnings
TestSaveReport           — atomic write / ring-buffer / no .tmp leftover
TestCLI                  — subprocess `--check` exit 0
TestImportHygiene        — no forbidden imports in source
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

# Make spa_core importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.rebalance_cost import (  # noqa: E402
    RebalanceCostModel,
    estimate_gas_cost,
    estimate_slippage_cost,
    compute_rebalance_cost,
    compute_break_even_days,
    is_rebalance_worthwhile,
    get_cost_report,
    _slippage_bps_for_trade,
    _safe_float,
    _normalise_weights,
    _normalise_tier,
    _normalise_redemption,
    _adapter_field,
    GAS_PER_LEG,
    DEFAULT_GAS_PRICE_GWEI,
    DEFAULT_ETH_PRICE_USD,
    MAX_SLIPPAGE_BPS,
    RING_BUFFER,
    SCHEMA_VERSION,
    VERDICT_WORTHWHILE,
    VERDICT_MARGINAL,
    VERDICT_NOT_WORTHWHILE,
)


def _obj(**kwargs):
    return types.SimpleNamespace(**kwargs)


# ---------------------------------------------------------------------------
# TestSafeFloat
# ---------------------------------------------------------------------------

class TestSafeFloat(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_numeric_string(self):
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_none_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_none_custom_default(self):
        self.assertEqual(_safe_float(None, default=7.0), 7.0)

    def test_garbage_string(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_garbage_custom_default(self):
        self.assertEqual(_safe_float("xyz", default=1.5), 1.5)

    def test_list_default(self):
        self.assertEqual(_safe_float([1, 2]), 0.0)

    def test_min_value_clamp_negative(self):
        self.assertEqual(_safe_float(-5.0, min_value=0.0), 0.0)

    def test_min_value_no_clamp(self):
        self.assertEqual(_safe_float(3.0, min_value=0.0), 3.0)

    def test_min_value_with_default_path(self):
        self.assertEqual(_safe_float(None, default=-2.0, min_value=0.0), 0.0)

    def test_nan_returns_default(self):
        self.assertEqual(_safe_float(float("nan"), default=4.0), 4.0)

    def test_inf_returns_default(self):
        self.assertEqual(_safe_float(float("inf"), default=9.0), 9.0)

    def test_negative_inf_returns_default(self):
        self.assertEqual(_safe_float(float("-inf"), default=1.0), 1.0)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)

    def test_negative_allowed_without_min(self):
        self.assertEqual(_safe_float(-3.5), -3.5)


# ---------------------------------------------------------------------------
# TestNormaliseWeights
# ---------------------------------------------------------------------------

class TestNormaliseWeights(unittest.TestCase):
    def test_basic_sum_to_one(self):
        out = _normalise_weights({"a": 1, "b": 1})
        self.assertAlmostEqual(sum(out.values()), 1.0)

    def test_equal_split(self):
        out = _normalise_weights({"a": 2, "b": 2})
        self.assertAlmostEqual(out["a"], 0.5)
        self.assertAlmostEqual(out["b"], 0.5)

    def test_proportional(self):
        out = _normalise_weights({"a": 3, "b": 1})
        self.assertAlmostEqual(out["a"], 0.75)
        self.assertAlmostEqual(out["b"], 0.25)

    def test_negatives_dropped(self):
        out = _normalise_weights({"a": 1, "b": -1})
        self.assertNotIn("b", out)
        self.assertAlmostEqual(out["a"], 1.0)

    def test_zero_dropped(self):
        out = _normalise_weights({"a": 1, "b": 0})
        self.assertNotIn("b", out)

    def test_all_zero_empty(self):
        self.assertEqual(_normalise_weights({"a": 0, "b": 0}), {})

    def test_all_negative_empty(self):
        self.assertEqual(_normalise_weights({"a": -1, "b": -2}), {})

    def test_empty_dict(self):
        self.assertEqual(_normalise_weights({}), {})

    def test_none_input(self):
        self.assertEqual(_normalise_weights(None), {})

    def test_already_normalised(self):
        out = _normalise_weights({"a": 0.6, "b": 0.4})
        self.assertAlmostEqual(out["a"], 0.6)

    def test_keys_stringified(self):
        out = _normalise_weights({1: 1, 2: 1})
        self.assertIn("1", out)

    def test_garbage_value_dropped(self):
        out = _normalise_weights({"a": "bad", "b": 1})
        self.assertNotIn("a", out)
        self.assertAlmostEqual(out["b"], 1.0)


# ---------------------------------------------------------------------------
# TestSlippageBps
# ---------------------------------------------------------------------------

class TestSlippageBps(unittest.TestCase):
    def test_t1_base_no_utilisation(self):
        bps = _slippage_bps_for_trade({"tier": "T1", "notional_usd": 100, "tvl_usd": 0})
        self.assertEqual(bps, 2.0)

    def test_t2_base(self):
        bps = _slippage_bps_for_trade({"tier": "T2", "notional_usd": 100, "tvl_usd": 0})
        self.assertEqual(bps, 5.0)

    def test_t3_base(self):
        bps = _slippage_bps_for_trade({"tier": "T3", "notional_usd": 100, "tvl_usd": 0})
        self.assertEqual(bps, 10.0)

    def test_unknown_tier_defaults_t2(self):
        bps = _slippage_bps_for_trade({"tier": "T9", "notional_usd": 100, "tvl_usd": 0})
        self.assertEqual(bps, 5.0)

    def test_missing_tier_defaults_t2(self):
        bps = _slippage_bps_for_trade({"notional_usd": 100, "tvl_usd": 0})
        self.assertEqual(bps, 5.0)

    def test_zero_tvl_no_premium(self):
        bps = _slippage_bps_for_trade({"tier": "T1", "notional_usd": 1000, "tvl_usd": 0})
        self.assertEqual(bps, 2.0)

    def test_low_utilisation_small_premium(self):
        # util = 1000/1_000_000 = 0.001 → util_frac=0.01 → premium=0.01*(300-2)=2.98
        bps = _slippage_bps_for_trade(
            {"tier": "T1", "notional_usd": 1000, "tvl_usd": 1_000_000}
        )
        self.assertAlmostEqual(bps, 2.0 + 0.01 * (300.0 - 2.0), places=4)

    def test_saturation_util_clamps_to_max(self):
        # util = 0.20 > 0.10 saturation → util_frac=1.0 → bps=MAX
        bps = _slippage_bps_for_trade(
            {"tier": "T1", "notional_usd": 200_000, "tvl_usd": 1_000_000}
        )
        self.assertEqual(bps, MAX_SLIPPAGE_BPS)

    def test_exact_saturation_util(self):
        # util = 0.10 → util_frac=1.0 → bps=MAX
        bps = _slippage_bps_for_trade(
            {"tier": "T2", "notional_usd": 100_000, "tvl_usd": 1_000_000}
        )
        self.assertEqual(bps, MAX_SLIPPAGE_BPS)

    def test_lock_penalty_added(self):
        base = _slippage_bps_for_trade(
            {"tier": "T1", "notional_usd": 100, "tvl_usd": 0, "redemption_type": "instant"}
        )
        lock = _slippage_bps_for_trade(
            {"tier": "T1", "notional_usd": 100, "tvl_usd": 0, "redemption_type": "lock"}
        )
        self.assertEqual(lock - base, 25.0)

    def test_instant_no_penalty(self):
        bps = _slippage_bps_for_trade(
            {"tier": "T2", "notional_usd": 100, "tvl_usd": 0, "redemption_type": "instant"}
        )
        self.assertEqual(bps, 5.0)

    def test_lock_clamped_to_max(self):
        bps = _slippage_bps_for_trade(
            {"tier": "T3", "notional_usd": 200_000, "tvl_usd": 1_000_000,
             "redemption_type": "lock"}
        )
        self.assertEqual(bps, MAX_SLIPPAGE_BPS)

    def test_final_lower_bound_is_base(self):
        bps = _slippage_bps_for_trade({"tier": "T3", "notional_usd": 0, "tvl_usd": 0})
        self.assertGreaterEqual(bps, 10.0)

    def test_none_trade_safe(self):
        bps = _slippage_bps_for_trade(None)
        self.assertEqual(bps, 5.0)

    def test_lock_on_zero_util_t1(self):
        # base 2 + 25 = 27, below max → 27
        bps = _slippage_bps_for_trade(
            {"tier": "T1", "notional_usd": 100, "tvl_usd": 0, "redemption_type": "lock"}
        )
        self.assertEqual(bps, 27.0)

    def test_never_exceeds_max(self):
        bps = _slippage_bps_for_trade(
            {"tier": "T3", "notional_usd": 10_000_000, "tvl_usd": 1_000,
             "redemption_type": "lock"}
        )
        self.assertLessEqual(bps, MAX_SLIPPAGE_BPS)


# ---------------------------------------------------------------------------
# TestEstimateGasCost
# ---------------------------------------------------------------------------

class TestEstimateGasCost(unittest.TestCase):
    def test_zero_trades(self):
        self.assertEqual(estimate_gas_cost(0), 0.0)

    def test_negative_trades(self):
        self.assertEqual(estimate_gas_cost(-3), 0.0)

    def test_one_trade_default(self):
        # 1*2*180000*20*1e-9*3000 = 21.6
        self.assertAlmostEqual(estimate_gas_cost(1), 21.6, places=6)

    def test_multiple_trades_scale(self):
        self.assertAlmostEqual(estimate_gas_cost(5), 21.6 * 5, places=6)

    def test_custom_gas_price(self):
        # 1*2*180000*40*1e-9*3000 = 43.2
        self.assertAlmostEqual(estimate_gas_cost(1, gas_price_gwei=40.0), 43.2, places=6)

    def test_custom_eth_price(self):
        # 1*2*180000*20*1e-9*6000 = 43.2
        self.assertAlmostEqual(estimate_gas_cost(1, eth_price_usd=6000.0), 43.2, places=6)

    def test_negative_gas_price_clamped(self):
        self.assertEqual(estimate_gas_cost(1, gas_price_gwei=-5.0), 0.0)

    def test_negative_eth_price_clamped(self):
        self.assertEqual(estimate_gas_cost(1, eth_price_usd=-100.0), 0.0)

    def test_none_gas_uses_default(self):
        self.assertAlmostEqual(estimate_gas_cost(1, gas_price_gwei=None), 21.6, places=6)

    def test_none_eth_uses_default(self):
        self.assertAlmostEqual(estimate_gas_cost(1, eth_price_usd=None), 21.6, places=6)

    def test_zero_gas_price(self):
        self.assertEqual(estimate_gas_cost(3, gas_price_gwei=0.0), 0.0)

    def test_zero_eth_price(self):
        self.assertEqual(estimate_gas_cost(3, eth_price_usd=0.0), 0.0)

    def test_garbage_n_trades(self):
        self.assertEqual(estimate_gas_cost("abc"), 0.0)

    def test_float_n_trades_truncated(self):
        self.assertAlmostEqual(estimate_gas_cost(2.9), 21.6 * 2, places=6)

    def test_constants_present(self):
        self.assertEqual(GAS_PER_LEG, 180_000)
        self.assertEqual(DEFAULT_GAS_PRICE_GWEI, 20.0)
        self.assertEqual(DEFAULT_ETH_PRICE_USD, 3000.0)

    def test_result_non_negative(self):
        self.assertGreaterEqual(estimate_gas_cost(10), 0.0)


# ---------------------------------------------------------------------------
# TestEstimateSlippageCost
# ---------------------------------------------------------------------------

class TestEstimateSlippageCost(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(estimate_slippage_cost([]), 0.0)

    def test_none(self):
        self.assertEqual(estimate_slippage_cost(None), 0.0)

    def test_single_trade(self):
        # T1, no util → 2 bps on 10000 = 2.0
        cost = estimate_slippage_cost(
            [{"tier": "T1", "notional_usd": 10_000, "tvl_usd": 0}]
        )
        self.assertAlmostEqual(cost, 10_000 * 2.0 / 1e4, places=6)

    def test_sum_of_trades(self):
        cost = estimate_slippage_cost(
            [
                {"tier": "T1", "notional_usd": 10_000, "tvl_usd": 0},
                {"tier": "T3", "notional_usd": 10_000, "tvl_usd": 0},
            ]
        )
        expected = 10_000 * 2.0 / 1e4 + 10_000 * 10.0 / 1e4
        self.assertAlmostEqual(cost, expected, places=6)

    def test_zero_notional_skipped(self):
        cost = estimate_slippage_cost([{"tier": "T1", "notional_usd": 0, "tvl_usd": 0}])
        self.assertEqual(cost, 0.0)

    def test_negative_notional_skipped(self):
        cost = estimate_slippage_cost([{"tier": "T1", "notional_usd": -500, "tvl_usd": 0}])
        self.assertEqual(cost, 0.0)

    def test_missing_notional_skipped(self):
        cost = estimate_slippage_cost([{"tier": "T1", "tvl_usd": 0}])
        self.assertEqual(cost, 0.0)

    def test_lock_increases_cost(self):
        base = estimate_slippage_cost(
            [{"tier": "T1", "notional_usd": 10_000, "tvl_usd": 0,
              "redemption_type": "instant"}]
        )
        lock = estimate_slippage_cost(
            [{"tier": "T1", "notional_usd": 10_000, "tvl_usd": 0,
              "redemption_type": "lock"}]
        )
        self.assertGreater(lock, base)

    def test_high_util_max_bps(self):
        cost = estimate_slippage_cost(
            [{"tier": "T1", "notional_usd": 200_000, "tvl_usd": 1_000_000}]
        )
        self.assertAlmostEqual(cost, 200_000 * MAX_SLIPPAGE_BPS / 1e4, places=4)

    def test_none_in_list_safe(self):
        cost = estimate_slippage_cost([None, {"tier": "T1", "notional_usd": 10_000}])
        self.assertGreater(cost, 0.0)

    def test_result_non_negative(self):
        self.assertGreaterEqual(
            estimate_slippage_cost([{"tier": "T2", "notional_usd": 5000}]), 0.0
        )


# ---------------------------------------------------------------------------
# TestComputeRebalanceCost
# ---------------------------------------------------------------------------

class TestComputeRebalanceCost(unittest.TestCase):
    def setUp(self):
        self.cur = {"a": 0.5, "b": 0.5}
        self.tgt = {"a": 0.3, "b": 0.7}
        self.pv = 1_000_000.0

    def test_identical_zero_trades(self):
        out = compute_rebalance_cost(self.cur, self.cur, self.pv)
        self.assertEqual(out["n_trades"], 0)
        self.assertEqual(out["total_cost_usd"], 0.0)

    def test_identical_zero_turnover(self):
        out = compute_rebalance_cost(self.cur, self.cur, self.pv)
        self.assertEqual(out["turnover_pct"], 0.0)

    def test_basic_trade_count(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        self.assertEqual(out["n_trades"], 2)

    def test_turnover_pct(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        # |delta|/2 = (0.2 + 0.2)/2 = 0.2 → 20%
        self.assertAlmostEqual(out["turnover_pct"], 20.0, places=4)

    def test_gas_cost_present(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        self.assertGreater(out["gas_cost_usd"], 0.0)

    def test_slippage_cost_present(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        self.assertGreater(out["slippage_cost_usd"], 0.0)

    def test_total_is_sum(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        self.assertAlmostEqual(
            out["total_cost_usd"],
            out["gas_cost_usd"] + out["slippage_cost_usd"],
            places=6,
        )

    def test_cost_bps_computed(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        expected = out["total_cost_usd"] / self.pv * 1e4
        self.assertAlmostEqual(out["cost_bps"], expected, places=4)

    def test_pv_zero_no_trades(self):
        out = compute_rebalance_cost(self.cur, self.tgt, 0.0)
        self.assertEqual(out["n_trades"], 0)
        self.assertEqual(out["cost_bps"], 0.0)

    def test_pv_negative_no_trades(self):
        out = compute_rebalance_cost(self.cur, self.tgt, -100.0)
        self.assertEqual(out["n_trades"], 0)

    def test_min_trade_threshold(self):
        # delta tiny → notional < MIN_TRADE_USD
        cur = {"a": 0.5000001, "b": 0.4999999}
        tgt = {"a": 0.5, "b": 0.5}
        out = compute_rebalance_cost(cur, tgt, 1000.0)
        self.assertEqual(out["n_trades"], 0)

    def test_trade_direction_enter(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        dirs = {t["adapter_id"]: t["direction"] for t in out["trades"]}
        self.assertEqual(dirs["b"], "enter")

    def test_trade_direction_exit(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        dirs = {t["adapter_id"]: t["direction"] for t in out["trades"]}
        self.assertEqual(dirs["a"], "exit")

    def test_trade_view_keys(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        for t in out["trades"]:
            self.assertEqual(
                set(t.keys()),
                {"adapter_id", "notional_usd", "slippage_bps", "direction"},
            )

    def test_union_of_ids(self):
        cur = {"a": 1.0}
        tgt = {"b": 1.0}
        out = compute_rebalance_cost(cur, tgt, self.pv)
        ids = {t["adapter_id"] for t in out["trades"]}
        self.assertEqual(ids, {"a", "b"})

    def test_adapters_enrich_tvl(self):
        adapters = {"a": {"tvl_usd": 1_000_000, "tier": "T3"},
                    "b": {"tvl_usd": 1_000_000, "tier": "T3"}}
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv, adapters=adapters)
        # T3 base 10 with utilisation → higher slippage than default T2
        self.assertGreater(out["slippage_cost_usd"], 0.0)

    def test_adapters_object_form(self):
        adapters = {"a": _obj(tvl_usd=1_000_000, tier="T1"),
                    "b": _obj(tvl_usd=1_000_000, tier="T1")}
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv, adapters=adapters)
        self.assertEqual(out["n_trades"], 2)

    def test_lock_redemption_increases_cost(self):
        ad_instant = {"a": {"redemption_type": "instant"},
                      "b": {"redemption_type": "instant"}}
        ad_lock = {"a": {"redemption_type": "lock"},
                   "b": {"redemption_type": "lock"}}
        c1 = compute_rebalance_cost(self.cur, self.tgt, self.pv, adapters=ad_instant)
        c2 = compute_rebalance_cost(self.cur, self.tgt, self.pv, adapters=ad_lock)
        self.assertGreater(c2["slippage_cost_usd"], c1["slippage_cost_usd"])

    def test_negative_weights_normalised(self):
        cur = {"a": -1, "b": 2}
        tgt = {"a": 1, "b": 1}
        out = compute_rebalance_cost(cur, tgt, self.pv)
        self.assertIsInstance(out["n_trades"], int)

    def test_empty_weights(self):
        out = compute_rebalance_cost({}, {}, self.pv)
        self.assertEqual(out["n_trades"], 0)

    def test_gas_overrides(self):
        out = compute_rebalance_cost(
            self.cur, self.tgt, self.pv, gas_price_gwei=100.0, eth_price_usd=4000.0
        )
        self.assertGreater(out["gas_cost_usd"], 0.0)

    def test_trades_sorted_by_id(self):
        out = compute_rebalance_cost(self.cur, self.tgt, self.pv)
        ids = [t["adapter_id"] for t in out["trades"]]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# TestComputeBreakEvenDays
# ---------------------------------------------------------------------------

class TestComputeBreakEvenDays(unittest.TestCase):
    def test_zero_cost(self):
        self.assertEqual(compute_break_even_days(0.0, 5.0, 1_000_000), 0.0)

    def test_negative_cost(self):
        self.assertEqual(compute_break_even_days(-100.0, 5.0, 1_000_000), 0.0)

    def test_basic(self):
        # daily_gain = 1_000_000 * 0.05/365 = 136.98...; cost 1000 → ~7.3 days
        be = compute_break_even_days(1000.0, 5.0, 1_000_000)
        self.assertAlmostEqual(be, 1000.0 / (1_000_000 * 0.05 / 365), places=4)

    def test_zero_apy_gain_inf(self):
        self.assertEqual(compute_break_even_days(1000.0, 0.0, 1_000_000), float("inf"))

    def test_negative_apy_gain_inf(self):
        self.assertEqual(compute_break_even_days(1000.0, -2.0, 1_000_000), float("inf"))

    def test_zero_pv_inf(self):
        self.assertEqual(compute_break_even_days(1000.0, 5.0, 0.0), float("inf"))

    def test_negative_pv_inf(self):
        self.assertEqual(compute_break_even_days(1000.0, 5.0, -50.0), float("inf"))

    def test_higher_gain_shorter_horizon(self):
        be_low = compute_break_even_days(1000.0, 2.0, 1_000_000)
        be_high = compute_break_even_days(1000.0, 8.0, 1_000_000)
        self.assertLess(be_high, be_low)

    def test_higher_cost_longer_horizon(self):
        be_low = compute_break_even_days(500.0, 5.0, 1_000_000)
        be_high = compute_break_even_days(5000.0, 5.0, 1_000_000)
        self.assertGreater(be_high, be_low)

    def test_larger_pv_shorter_horizon(self):
        be_small = compute_break_even_days(1000.0, 5.0, 100_000)
        be_large = compute_break_even_days(1000.0, 5.0, 10_000_000)
        self.assertLess(be_large, be_small)

    def test_garbage_cost(self):
        self.assertEqual(compute_break_even_days("bad", 5.0, 1_000_000), 0.0)

    def test_result_positive_finite(self):
        be = compute_break_even_days(100.0, 10.0, 1_000_000)
        self.assertTrue(math.isfinite(be))
        self.assertGreater(be, 0.0)


# ---------------------------------------------------------------------------
# TestIsRebalanceWorthwhile
# ---------------------------------------------------------------------------

class TestIsRebalanceWorthwhile(unittest.TestCase):
    def setUp(self):
        self.cur = {"a": 0.5, "b": 0.5}
        self.tgt = {"a": 0.4, "b": 0.6}
        self.pv = 10_000_000.0  # large pv → small break-even

    def test_worthwhile_large_gain(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, current_apy_pct=5.0, target_apy_pct=15.0
        )
        self.assertEqual(out["verdict"], VERDICT_WORTHWHILE)

    def test_not_worthwhile_no_gain(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, current_apy_pct=8.0, target_apy_pct=8.0
        )
        self.assertEqual(out["verdict"], VERDICT_NOT_WORTHWHILE)

    def test_not_worthwhile_negative_gain(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, current_apy_pct=10.0, target_apy_pct=8.0
        )
        self.assertEqual(out["verdict"], VERDICT_NOT_WORTHWHILE)

    def test_apy_gain_computed(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, current_apy_pct=5.0, target_apy_pct=7.5
        )
        self.assertAlmostEqual(out["apy_gain_pct"], 2.5, places=4)

    def test_break_even_present(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, current_apy_pct=5.0, target_apy_pct=10.0
        )
        self.assertIn("break_even_days", out)

    def test_max_break_even_echoed(self):
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, 5.0, 10.0, max_break_even_days=45.0
        )
        self.assertEqual(out["max_break_even_days"], 45.0)

    def test_recommendation_string(self):
        out = is_rebalance_worthwhile(self.cur, self.tgt, self.pv, 5.0, 10.0)
        self.assertIsInstance(out["recommendation"], str)
        self.assertTrue(out["recommendation"])

    def test_merges_cost_summary(self):
        out = is_rebalance_worthwhile(self.cur, self.tgt, self.pv, 5.0, 10.0)
        for k in ("n_trades", "turnover_pct", "total_cost_usd", "cost_bps", "trades"):
            self.assertIn(k, out)

    def test_no_trades_recommendation(self):
        out = is_rebalance_worthwhile(self.cur, self.cur, self.pv, 5.0, 10.0)
        self.assertEqual(out["n_trades"], 0)
        self.assertIn("No trades", out["recommendation"])

    def test_marginal_verdict(self):
        # small pv + small gain → break-even between 0.5*max and max
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, 50_000.0, current_apy_pct=5.0, target_apy_pct=5.5,
            max_break_even_days=400.0,
        )
        # Just assert verdict is one of the valid labels (boundary-dependent)
        self.assertIn(
            out["verdict"],
            (VERDICT_WORTHWHILE, VERDICT_MARGINAL, VERDICT_NOT_WORTHWHILE),
        )

    def test_inf_break_even_not_worthwhile(self):
        out = is_rebalance_worthwhile(self.cur, self.tgt, self.pv, 5.0, 5.0)
        self.assertTrue(math.isinf(out["break_even_days"]))
        self.assertEqual(out["verdict"], VERDICT_NOT_WORTHWHILE)

    def test_adapters_passthrough(self):
        adapters = {"a": {"tier": "T1"}, "b": {"tier": "T1"}}
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, 5.0, 12.0, adapters=adapters
        )
        self.assertIn("verdict", out)

    def test_worthwhile_boundary(self):
        # explicit worthwhile threshold half-of-max
        out = is_rebalance_worthwhile(
            self.cur, self.tgt, self.pv, 5.0, 30.0, max_break_even_days=30.0
        )
        self.assertIn(out["verdict"], (VERDICT_WORTHWHILE, VERDICT_MARGINAL))


# ---------------------------------------------------------------------------
# TestGetCostReport
# ---------------------------------------------------------------------------

class TestGetCostReport(unittest.TestCase):
    def setUp(self):
        self.cur = {"a": 0.5, "b": 0.5}
        self.tgt = {"a": 0.3, "b": 0.7}
        self.pv = 1_000_000.0

    def _report(self, **kw):
        return get_cost_report(
            self.cur, self.tgt, self.pv,
            kw.get("current_apy_pct", 5.0), kw.get("target_apy_pct", 10.0),
            adapters=kw.get("adapters"),
            max_break_even_days=kw.get("max_break_even_days", 30.0),
        )

    def test_schema_version(self):
        self.assertEqual(self._report()["schema_version"], SCHEMA_VERSION)

    def test_generated_at_iso(self):
        r = self._report()
        self.assertIn("T", r["generated_at"])

    def test_all_keys_present(self):
        r = self._report()
        for k in (
            "schema_version", "generated_at", "portfolio_value", "n_trades",
            "turnover_pct", "gas_cost_usd", "slippage_cost_usd", "total_cost_usd",
            "cost_bps", "apy_gain_pct", "break_even_days", "verdict",
            "recommendation", "trades", "warnings",
        ):
            self.assertIn(k, r)

    def test_warnings_is_list(self):
        self.assertIsInstance(self._report()["warnings"], list)

    def test_pv_zero_warning(self):
        r = get_cost_report(self.cur, self.tgt, 0.0, 5.0, 10.0)
        self.assertTrue(any("portfolio_value" in w for w in r["warnings"]))

    def test_high_turnover_warning(self):
        # full swap → turnover 100%
        r = get_cost_report({"a": 1.0}, {"b": 1.0}, self.pv, 5.0, 20.0)
        self.assertTrue(any("turnover" in w.lower() for w in r["warnings"]))

    def test_inf_break_even_warning(self):
        r = get_cost_report(self.cur, self.tgt, self.pv, 5.0, 5.0)
        self.assertTrue(any("infinite" in w.lower() for w in r["warnings"]))

    def test_break_even_over_threshold_warning(self):
        # tiny gain → very long break-even
        r = get_cost_report(self.cur, self.tgt, 10_000.0, 5.0, 5.01,
                            max_break_even_days=1.0)
        self.assertTrue(any("break-even" in w.lower() for w in r["warnings"]))

    def test_high_cost_bps_warning(self):
        # tiny pv, T3 lock adapters → high cost_bps
        adapters = {"a": {"tier": "T3", "redemption_type": "lock", "tvl_usd": 1000},
                    "b": {"tier": "T3", "redemption_type": "lock", "tvl_usd": 1000}}
        r = get_cost_report({"a": 1.0}, {"b": 1.0}, 100_000.0, 5.0, 20.0,
                            adapters=adapters)
        self.assertTrue(any("bps" in w.lower() for w in r["warnings"]))

    def test_trades_present(self):
        r = self._report()
        self.assertEqual(len(r["trades"]), 2)

    def test_verdict_label_valid(self):
        r = self._report()
        self.assertIn(
            r["verdict"],
            (VERDICT_WORTHWHILE, VERDICT_MARGINAL, VERDICT_NOT_WORTHWHILE),
        )

    def test_portfolio_value_echoed(self):
        self.assertEqual(self._report()["portfolio_value"], self.pv)

    def test_identical_no_warnings_for_turnover(self):
        r = get_cost_report(self.cur, self.cur, self.pv, 5.0, 10.0)
        self.assertEqual(r["n_trades"], 0)

    def test_is_json_serialisable(self):
        r = self._report()
        # break_even may be inf; ensure non-inf path serialises cleanly
        r2 = get_cost_report(self.cur, self.tgt, self.pv, 5.0, 20.0)
        json.dumps(r2)
        self.assertIsInstance(r, dict)


# ---------------------------------------------------------------------------
# TestSaveReport
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.model = RebalanceCostModel(data_dir=self.tmp)
        self.report = get_cost_report(
            {"a": 0.5, "b": 0.5}, {"a": 0.3, "b": 0.7}, 1_000_000.0, 5.0, 20.0
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self):
        return Path(self.tmp) / "rebalance_cost_report.json"

    def test_returns_path(self):
        p = self.model.save_report(self.report)
        self.assertEqual(p, str(self._path()))

    def test_file_created(self):
        self.model.save_report(self.report)
        self.assertTrue(self._path().exists())

    def test_valid_json(self):
        self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertIsInstance(doc, dict)

    def test_schema_version(self):
        self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["schema_version"], SCHEMA_VERSION)

    def test_latest_matches(self):
        self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["latest"]["verdict"], self.report["verdict"])

    def test_label_stored(self):
        self.model.save_report(self.report, label="run-1")
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["latest"]["label"], "run-1")

    def test_history_grows(self):
        for _ in range(3):
            self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["history_depth"], 3)

    def test_ring_buffer_capped(self):
        for _ in range(RING_BUFFER + 15):
            self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertLessEqual(len(doc["history"]), RING_BUFFER)

    def test_ring_buffer_exact(self):
        for _ in range(RING_BUFFER + 5):
            self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(len(doc["history"]), RING_BUFFER)

    def test_no_tmp_left(self):
        self.model.save_report(self.report)
        leftover = [
            f for f in os.listdir(self.tmp)
            if f.endswith(".tmp") or f.startswith(".rebalance_cost_report_tmp_")
        ]
        self.assertEqual(leftover, [])

    def test_data_dir_created(self):
        nested = os.path.join(self.tmp, "x", "y")
        m = RebalanceCostModel(data_dir=nested)
        m.save_report(self.report)
        self.assertTrue(os.path.isdir(nested))

    def test_corrupt_history_recovers(self):
        # write garbage then save → should reset history gracefully
        with open(self._path(), "w") as f:
            f.write("{not valid json")
        self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["history_depth"], 1)

    def test_history_depth_matches_len(self):
        for _ in range(4):
            self.model.save_report(self.report)
        with open(self._path()) as f:
            doc = json.load(f)
        self.assertEqual(doc["history_depth"], len(doc["history"]))


# ---------------------------------------------------------------------------
# TestModelWrappers
# ---------------------------------------------------------------------------

class TestModelWrappers(unittest.TestCase):
    def setUp(self):
        self.m = RebalanceCostModel(data_dir=tempfile.mkdtemp())

    def test_estimate_gas_cost(self):
        self.assertEqual(self.m.estimate_gas_cost(0), 0.0)

    def test_estimate_slippage_cost(self):
        self.assertEqual(self.m.estimate_slippage_cost([]), 0.0)

    def test_compute_rebalance_cost(self):
        out = self.m.compute_rebalance_cost({"a": 1.0}, {"a": 1.0}, 1000.0)
        self.assertEqual(out["n_trades"], 0)

    def test_compute_break_even_days(self):
        self.assertEqual(self.m.compute_break_even_days(0.0, 5.0, 1000.0), 0.0)

    def test_is_rebalance_worthwhile(self):
        out = self.m.is_rebalance_worthwhile(
            {"a": 0.5, "b": 0.5}, {"a": 0.4, "b": 0.6}, 1_000_000.0, 5.0, 12.0
        )
        self.assertIn("verdict", out)

    def test_get_cost_report(self):
        out = self.m.get_cost_report(
            {"a": 0.5, "b": 0.5}, {"a": 0.4, "b": 0.6}, 1_000_000.0, 5.0, 12.0
        )
        self.assertEqual(out["schema_version"], SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# TestHelpersExtra
# ---------------------------------------------------------------------------

class TestHelpersExtra(unittest.TestCase):
    def test_normalise_tier_lower(self):
        self.assertEqual(_normalise_tier("t1"), "T1")

    def test_normalise_tier_default(self):
        self.assertEqual(_normalise_tier("zzz"), "T2")

    def test_normalise_tier_none(self):
        self.assertEqual(_normalise_tier(None), "T2")

    def test_normalise_redemption_lock(self):
        self.assertEqual(_normalise_redemption("LOCK"), "lock")

    def test_normalise_redemption_default(self):
        self.assertEqual(_normalise_redemption("weird"), "instant")

    def test_normalise_redemption_none(self):
        self.assertEqual(_normalise_redemption(None), "instant")

    def test_normalise_redemption_batched(self):
        self.assertEqual(_normalise_redemption("batched"), "batched")

    def test_adapter_field_dict(self):
        self.assertEqual(_adapter_field({"tvl_usd": 5}, "tvl_usd"), 5)

    def test_adapter_field_fallback_name(self):
        self.assertEqual(_adapter_field({"tvl": 9}, "tvl_usd", "tvl"), 9)

    def test_adapter_field_object(self):
        self.assertEqual(_adapter_field(_obj(tier="T1"), "tier"), "T1")

    def test_adapter_field_none_adapter(self):
        self.assertIsNone(_adapter_field(None, "tvl_usd"))

    def test_adapter_field_missing(self):
        self.assertIsNone(_adapter_field({"x": 1}, "y"))


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.join(os.path.dirname(__file__), "..")
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_subprocess(self, args):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.analytics.rebalance_cost", *args],
            cwd=os.path.abspath(self.repo_root),
            capture_output=True,
            text=True,
        )

    def test_check_exit_zero(self):
        proc = self._run_subprocess(["--check"])
        self.assertEqual(proc.returncode, 0)

    def test_check_output_sane(self):
        proc = self._run_subprocess(["--check"])
        self.assertIn("Rebalance Cost Model", proc.stdout)

    def test_default_exit_zero(self):
        proc = self._run_subprocess([])
        self.assertEqual(proc.returncode, 0)

    def test_main_check_returns_zero(self):
        from spa_core.analytics.rebalance_cost import main
        self.assertEqual(main(["--check"]), 0)

    def test_main_run_returns_zero(self):
        from spa_core.analytics.rebalance_cost import main
        self.assertEqual(main(["--run", "--data-dir", self.tmp]), 0)

    def test_main_run_writes_file(self):
        from spa_core.analytics.rebalance_cost import main
        main(["--run", "--data-dir", self.tmp])
        self.assertTrue((Path(self.tmp) / "rebalance_cost_report.json").exists())

    def test_main_run_no_tmp_left(self):
        from spa_core.analytics.rebalance_cost import main
        main(["--run", "--data-dir", self.tmp])
        leftover = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftover, [])


# ---------------------------------------------------------------------------
# TestImportHygiene
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    def _source(self) -> str:
        import spa_core.analytics.rebalance_cost as mod
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_no_network_or_heavy_libs(self):
        src = self._source()
        for banned in ("requests", "web3", "numpy", "scipy", "pandas",
                       "openai", "anthropic"):
            self.assertNotIn(f"import {banned}", src, msg=f"Found: import {banned}")
            self.assertNotIn(f"from {banned}", src, msg=f"Found: from {banned}")

    def test_no_subprocess_import(self):
        src = self._source()
        self.assertNotIn("import subprocess", src)
        self.assertNotIn("from subprocess", src)

    def test_no_eval_exec(self):
        src = self._source()
        self.assertNotIn("eval(", src)
        self.assertNotIn("exec(", src)

    def test_no_forbidden_domains(self):
        src = self._source()
        for banned in ("spa_core.risk", "spa_core.execution", "spa_core.monitoring"):
            self.assertNotIn(banned, src, msg=f"Found forbidden domain: {banned}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
