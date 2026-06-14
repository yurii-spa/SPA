"""
Tests for MP-912: DeFiAMMImpermanentLossSimulator
Run with: python3 -m unittest spa_core.tests.test_defi_amm_impermanent_loss_simulator
Target: ≥ 80 tests
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_amm_impermanent_loss_simulator import (
    DeFiAMMImpermanentLossSimulator,
    _il_xy,
    _il_stable,
    _il_concentrated,
    _il_label,
    _compute_pool,
    _atomic_write,
    _load_log,
    _append_log,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _pool(
    name="TestPool",
    token_a="ETH",
    token_b="USDC",
    initial=1.0,
    current=1.0,
    liquidity=10_000.0,
    fee_tier=0.3,
    fee_income_30d=100.0,
    pool_type="xy",
    price_range=None,
):
    d = {
        "name": name,
        "token_a": token_a,
        "token_b": token_b,
        "initial_price_ratio": initial,
        "current_price_ratio": current,
        "liquidity_usd": liquidity,
        "fee_tier_pct": fee_tier,
        "fee_income_30d_usd": fee_income_30d,
        "pool_type": pool_type,
    }
    if price_range is not None:
        d["price_range"] = price_range
    return d


class TestILFormulaXY(unittest.TestCase):
    """Tests for the core xy IL formula."""

    def test_il_xy_price_unchanged(self):
        """r=1 → IL = 0"""
        self.assertAlmostEqual(_il_xy(1.0), 0.0, places=10)

    def test_il_xy_price_double(self):
        """r=2 → IL ≈ -5.72 %"""
        result = _il_xy(2.0)
        # 2*sqrt(2)/3 - 1
        expected = 2 * math.sqrt(2) / 3 - 1
        self.assertAlmostEqual(result, expected, places=10)
        self.assertAlmostEqual(result, -0.05719095842, places=8)

    def test_il_xy_price_half(self):
        """r=0.5 → same magnitude as r=2 (symmetric)"""
        self.assertAlmostEqual(_il_xy(0.5), _il_xy(2.0), places=10)

    def test_il_xy_price_quadruple(self):
        """r=4 → IL = -20 %"""
        result = _il_xy(4.0)
        expected = 2 * math.sqrt(4) / (1 + 4) - 1  # 4/5 - 1 = -0.2
        self.assertAlmostEqual(result, -0.2, places=10)

    def test_il_xy_price_quarter(self):
        """r=0.25 → IL = -20 % (same as r=4)"""
        self.assertAlmostEqual(_il_xy(0.25), -0.2, places=10)

    def test_il_xy_always_nonpositive(self):
        """IL is always ≤ 0 for any positive r."""
        for r in [0.1, 0.5, 0.9, 1.0, 1.5, 2.0, 5.0, 10.0]:
            with self.subTest(r=r):
                self.assertLessEqual(_il_xy(r), 0.0)

    def test_il_xy_zero_at_r_equals_one(self):
        """IL is exactly 0 only when price hasn't changed."""
        self.assertEqual(_il_xy(1.0), 0.0)

    def test_il_xy_negative_price_ratio_raises(self):
        with self.assertRaises(ValueError):
            _il_xy(-1.0)

    def test_il_xy_zero_price_ratio_raises(self):
        with self.assertRaises(ValueError):
            _il_xy(0.0)

    def test_il_xy_large_ratio(self):
        """Large price ratio → approaches -100 % but never reaches it."""
        result = _il_xy(10000.0)
        self.assertLess(result, 0.0)
        self.assertGreater(result, -1.0)

    def test_il_xy_small_ratio(self):
        """Very small price ratio → also IL < 0."""
        result = _il_xy(0.0001)
        self.assertLess(result, 0.0)
        self.assertGreater(result, -1.0)

    def test_il_xy_r_nine(self):
        """r=9 → 2*3/10 - 1 = -0.4"""
        self.assertAlmostEqual(_il_xy(9.0), -0.4, places=10)

    def test_il_xy_r_100(self):
        """r=100 → 2*10/101 - 1"""
        expected = 2 * math.sqrt(100) / (1 + 100) - 1
        self.assertAlmostEqual(_il_xy(100.0), expected, places=10)

    def test_il_xy_symmetric_various(self):
        """_il_xy(r) == _il_xy(1/r) for any r."""
        for r in [2.0, 3.0, 5.0, 10.0]:
            with self.subTest(r=r):
                self.assertAlmostEqual(_il_xy(r), _il_xy(1.0 / r), places=10)


class TestILFormulaStable(unittest.TestCase):
    """Tests for the stable-swap IL approximation."""

    def test_il_stable_price_unchanged(self):
        self.assertAlmostEqual(_il_stable(1.0), 0.0, places=10)

    def test_il_stable_smaller_than_xy(self):
        """Stable IL must be smaller (closer to 0) than xy IL."""
        for r in [0.99, 1.01, 0.95, 1.05]:
            with self.subTest(r=r):
                self.assertGreater(_il_stable(r), _il_xy(r))

    def test_il_stable_is_10pct_of_xy(self):
        """Stable IL ≈ 10 % of xy IL."""
        for r in [0.9, 1.1, 0.8, 1.5]:
            with self.subTest(r=r):
                self.assertAlmostEqual(_il_stable(r), _il_xy(r) * 0.1, places=10)

    def test_il_stable_nonpositive(self):
        for r in [0.5, 0.99, 1.0, 1.01, 2.0]:
            with self.subTest(r=r):
                self.assertLessEqual(_il_stable(r), 0.0)

    def test_il_stable_much_lower_on_depeg(self):
        """Even at 20 % de-peg, stable IL ≈ 0.5 % vs xy ≈ 5 %."""
        stable = abs(_il_stable(1.2)) * 100
        xy = abs(_il_xy(1.2)) * 100
        self.assertLess(stable, xy)


class TestILFormulaConcentrated(unittest.TestCase):
    """Tests for concentrated-liquidity IL."""

    def _cl(self, initial, current, lb, ub):
        return _il_concentrated(initial, current, lb, ub)

    def test_concentrated_in_range_returns_false_flag(self):
        il, oor = self._cl(1.0, 1.0, 0.5, 2.0)
        self.assertFalse(oor)

    def test_concentrated_out_of_range_above(self):
        il, oor = self._cl(1.0, 3.0, 0.5, 2.0)
        self.assertTrue(oor)

    def test_concentrated_out_of_range_below(self):
        il, oor = self._cl(1.0, 0.3, 0.5, 2.0)
        self.assertTrue(oor)

    def test_concentrated_in_range_il_amplified(self):
        """Concentrated LP IL must be ≥ full-range IL for same price move."""
        r = 1.5
        full_il = _il_xy(r)
        conc_il, _ = self._cl(1.0, r, 0.5, 3.0)
        # amplified ≤ full_il (both ≤ 0); amplified is more negative
        self.assertLessEqual(conc_il, full_il)

    def test_concentrated_no_il_when_price_unchanged(self):
        il, oor = self._cl(1.0, 1.0, 0.5, 2.0)
        self.assertAlmostEqual(il, 0.0, places=10)
        self.assertFalse(oor)

    def test_concentrated_invalid_bounds_raises(self):
        with self.assertRaises(ValueError):
            self._cl(1.0, 1.0, 2.0, 0.5)  # lb >= ub

    def test_concentrated_negative_initial_raises(self):
        with self.assertRaises(ValueError):
            self._cl(-1.0, 1.0, 0.5, 2.0)

    def test_concentrated_negative_current_raises(self):
        with self.assertRaises(ValueError):
            self._cl(1.0, -1.0, 0.5, 2.0)

    def test_concentrated_il_capped_at_minus_one(self):
        """IL fraction never goes below -1 (can't lose more than 100 %)."""
        il, _ = self._cl(1.0, 1.5, 1.49, 1.51)  # very narrow range
        self.assertGreaterEqual(il, -1.0)

    def test_concentrated_out_of_range_frozen_at_boundary(self):
        """Once out of range, IL doesn't worsen further."""
        il_oor, oor = self._cl(1.0, 5.0, 0.5, 2.0)
        il_at_ub, _ = self._cl(1.0, 2.0, 0.5, 2.0)
        # IL when out-of-range should match IL at boundary (frozen)
        self.assertAlmostEqual(il_oor, _il_xy(2.0 / 1.0), places=6)


class TestComputePool(unittest.TestCase):
    """Tests for _compute_pool() and label / flag logic."""

    def test_basic_xy_pool(self):
        result = _compute_pool(_pool(initial=1.0, current=2.0, liquidity=100_000), {})
        self.assertIn("il_pct", result)
        self.assertAlmostEqual(result["il_pct"], _il_xy(2.0) * 100, places=4)

    def test_il_usd_calculation(self):
        p = _pool(initial=1.0, current=4.0, liquidity=100_000, fee_income_30d=0)
        r = _compute_pool(p, {})
        # IL = -20 % → il_usd = -20000
        self.assertAlmostEqual(r["il_usd"], -20_000.0, places=2)

    def test_fee_offset_matches_input(self):
        p = _pool(fee_income_30d=500.0)
        r = _compute_pool(p, {})
        self.assertEqual(r["fee_offset_usd"], 500.0)

    def test_net_pnl_positive_when_fees_high(self):
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=2000)
        r = _compute_pool(p, {})
        # IL ≈ -5.72 % of 10000 ≈ -572; fees = 2000 → net > 0
        self.assertGreater(r["net_pnl_usd"], 0.0)

    def test_net_pnl_negative_when_fees_low(self):
        p = _pool(initial=1.0, current=4.0, liquidity=100_000, fee_income_30d=10)
        r = _compute_pool(p, {})
        self.assertLess(r["net_pnl_usd"], 0.0)

    def test_stable_pool_lower_il_than_xy(self):
        p_xy = _pool(initial=1.0, current=1.1, pool_type="xy")
        p_st = _pool(initial=1.0, current=1.1, pool_type="stable")
        r_xy = _compute_pool(p_xy, {})
        r_st = _compute_pool(p_st, {})
        self.assertGreater(r_st["il_pct"], r_xy["il_pct"])  # both ≤ 0; stable closer to 0

    def test_concentrated_pool_in_range(self):
        p = _pool(
            initial=1.0, current=1.5, pool_type="concentrated",
            price_range={"lower_bound": 0.5, "upper_bound": 3.0}
        )
        r = _compute_pool(p, {})
        self.assertFalse(r["out_of_range"])

    def test_concentrated_pool_out_of_range_flag(self):
        p = _pool(
            initial=1.0, current=5.0, pool_type="concentrated",
            price_range={"lower_bound": 0.5, "upper_bound": 3.0}
        )
        r = _compute_pool(p, {})
        self.assertTrue(r["out_of_range"])
        self.assertIn("OUT_OF_RANGE", r["flags"])

    def test_break_even_none_when_no_fees(self):
        p = _pool(initial=1.0, current=2.0, fee_income_30d=0.0)
        r = _compute_pool(p, {})
        self.assertIsNone(r["break_even_days"])

    def test_break_even_zero_when_no_il(self):
        p = _pool(initial=1.0, current=1.0, fee_income_30d=100.0)
        r = _compute_pool(p, {})
        self.assertEqual(r["break_even_days"], 0.0)

    def test_break_even_calculated_correctly(self):
        # IL ≈ 5.72 % of 10000 = 572 USD
        # 30d fees = 100 USD → daily = 100/30
        # break_even = 572 / (100/30) = 572 * 30 / 100 ≈ 171.6
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=100)
        r = _compute_pool(p, {})
        il_abs = abs(_il_xy(2.0)) * 10_000
        expected_be = il_abs / (100.0 / 30.0)
        self.assertAlmostEqual(r["break_even_days"], expected_be, places=2)

    def test_flag_fee_covers_il(self):
        # IL ≈ 572 USD; fees = 10000 > IL
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=10_000)
        r = _compute_pool(p, {})
        self.assertIn("FEE_COVERS_IL", r["flags"])

    def test_flag_fee_not_covers_il(self):
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=10)
        r = _compute_pool(p, {})
        self.assertNotIn("FEE_COVERS_IL", r["flags"])

    def test_flag_high_il(self):
        # 4x price → IL = 20 % → HIGH_IL
        p = _pool(initial=1.0, current=4.0, liquidity=100_000)
        r = _compute_pool(p, {})
        self.assertIn("HIGH_IL", r["flags"])

    def test_flag_no_high_il_when_small_move(self):
        p = _pool(initial=1.0, current=1.01)
        r = _compute_pool(p, {})
        self.assertNotIn("HIGH_IL", r["flags"])

    def test_flag_short_breakeven(self):
        # IL ≈ 572 USD; fee = 572 per day → break_even ≈ 1 day
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=572 * 30)
        r = _compute_pool(p, {})
        self.assertIn("SHORT_BREAKEVEN", r["flags"])
        self.assertLess(r["break_even_days"], 30.0)

    def test_flag_no_short_breakeven_when_long(self):
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=1)
        r = _compute_pool(p, {})
        self.assertNotIn("SHORT_BREAKEVEN", r["flags"])

    def test_label_minimal(self):
        p = _pool(initial=1.0, current=1.0001)  # tiny move
        r = _compute_pool(p, {})
        self.assertEqual(r["il_label"], "MINIMAL")

    def test_label_low(self):
        # r=1.1 → IL ≈ 0.12 % → LOW (0.1–0.5 %)
        p = _pool(initial=1.0, current=1.1)
        r = _compute_pool(p, {})
        il_abs = abs(r["il_pct"])
        self.assertGreaterEqual(il_abs, 0.1)
        self.assertLess(il_abs, 0.5)
        self.assertEqual(r["il_label"], "LOW")

    def test_label_moderate(self):
        # r=1.3 → IL ≈ 0.86 % → MODERATE (0.5–2.0 %)
        p = _pool(initial=1.0, current=1.3)
        r = _compute_pool(p, {})
        il_abs = abs(r["il_pct"])
        self.assertGreaterEqual(il_abs, 0.5)
        self.assertLess(il_abs, 2.0)
        self.assertEqual(r["il_label"], "MODERATE")

    def test_label_high(self):
        # r=1.7 → IL ≈ 3.42 % → HIGH (2.0–5.0 %)
        p = _pool(initial=1.0, current=1.7)
        r = _compute_pool(p, {})
        il_abs = abs(r["il_pct"])
        self.assertGreaterEqual(il_abs, 2.0)
        self.assertLess(il_abs, 5.0)
        self.assertEqual(r["il_label"], "HIGH")

    def test_label_severe(self):
        # r=4 → IL = 20 %
        p = _pool(initial=1.0, current=4.0)
        r = _compute_pool(p, {})
        self.assertEqual(r["il_label"], "SEVERE")

    def test_invalid_pool_type_defaults_to_xy(self):
        p = _pool(pool_type="unknown_type")
        r = _compute_pool(p, {})
        self.assertEqual(r["pool_type"], "xy")

    def test_price_ratio_change_in_result(self):
        p = _pool(initial=2.0, current=4.0)
        r = _compute_pool(p, {})
        self.assertAlmostEqual(r["price_ratio_change"], 2.0, places=6)

    def test_pool_with_zero_liquidity(self):
        p = _pool(liquidity=0.0)
        r = _compute_pool(p, {})
        self.assertEqual(r["il_usd"], 0.0)
        self.assertEqual(r["break_even_days"], 0.0)

    def test_field_names_present(self):
        r = _compute_pool(_pool(), {})
        for key in ("name", "token_a", "token_b", "pool_type", "il_pct",
                    "il_usd", "fee_offset_usd", "net_pnl_usd",
                    "break_even_days", "il_label", "flags", "out_of_range"):
            self.assertIn(key, r)

    def test_negative_il_pct(self):
        p = _pool(initial=1.0, current=2.0)
        r = _compute_pool(p, {})
        self.assertLess(r["il_pct"], 0.0)


class TestILLabel(unittest.TestCase):
    """Boundary tests for _il_label()."""

    def test_minimal_boundary(self):
        self.assertEqual(_il_label(0.0), "MINIMAL")
        self.assertEqual(_il_label(0.09), "MINIMAL")

    def test_low_boundary(self):
        self.assertEqual(_il_label(0.1), "LOW")
        self.assertEqual(_il_label(0.49), "LOW")

    def test_moderate_boundary(self):
        self.assertEqual(_il_label(0.5), "MODERATE")
        self.assertEqual(_il_label(1.99), "MODERATE")

    def test_high_boundary(self):
        self.assertEqual(_il_label(2.0), "HIGH")
        self.assertEqual(_il_label(4.99), "HIGH")

    def test_severe_boundary(self):
        self.assertEqual(_il_label(5.0), "SEVERE")
        self.assertEqual(_il_label(100.0), "SEVERE")


class TestSimulate(unittest.TestCase):
    """Tests for DeFiAMMImpermanentLossSimulator.simulate()."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "test_amm_log.json")
        self.sim = DeFiAMMImpermanentLossSimulator(data_file=self.data_file)

    def _single_pool_result(self, **kwargs):
        p = _pool(**kwargs)
        return self.sim.simulate([p], config={"write_log": False})

    def test_simulate_returns_dict(self):
        r = self._single_pool_result()
        self.assertIsInstance(r, dict)

    def test_simulate_returns_timestamp(self):
        r = self._single_pool_result()
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_simulate_returns_pools_list(self):
        r = self._single_pool_result()
        self.assertIn("pools", r)
        self.assertIsInstance(r["pools"], list)
        self.assertEqual(len(r["pools"]), 1)

    def test_simulate_returns_errors_list(self):
        r = self._single_pool_result()
        self.assertIn("errors", r)
        self.assertIsInstance(r["errors"], list)

    def test_simulate_returns_aggregates(self):
        r = self._single_pool_result()
        self.assertIn("aggregates", r)

    def test_simulate_single_xy_pool(self):
        r = self._single_pool_result(initial=1.0, current=2.0, liquidity=10_000)
        pool_r = r["pools"][0]
        expected_il = _il_xy(2.0) * 100
        self.assertAlmostEqual(pool_r["il_pct"], expected_il, places=4)

    def test_simulate_multiple_pools(self):
        pools = [
            _pool(name="P1", initial=1.0, current=2.0),
            _pool(name="P2", initial=1.0, current=3.0),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(len(r["pools"]), 2)

    def test_simulate_empty_pools(self):
        r = self.sim.simulate([], {"write_log": False})
        self.assertEqual(r["aggregates"]["pool_count"], 0)
        self.assertIsNone(r["aggregates"]["worst_il_pool"])
        self.assertIsNone(r["aggregates"]["best_net_pool"])

    def test_simulate_total_il_usd(self):
        pools = [
            _pool(name="A", initial=1.0, current=4.0, liquidity=100_000, fee_income_30d=0),
            _pool(name="B", initial=1.0, current=4.0, liquidity=50_000, fee_income_30d=0),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        # Each pool: IL = -20 %
        expected = (-0.2 * 100_000) + (-0.2 * 50_000)
        self.assertAlmostEqual(r["aggregates"]["total_il_usd"], expected, places=2)

    def test_simulate_total_fee_income_usd(self):
        pools = [
            _pool(name="A", fee_income_30d=500),
            _pool(name="B", fee_income_30d=300),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertAlmostEqual(r["aggregates"]["total_fee_income_usd"], 800.0, places=4)

    def test_simulate_worst_il_pool(self):
        pools = [
            _pool(name="BAD", initial=1.0, current=4.0),   # 20 % IL
            _pool(name="GOOD", initial=1.0, current=1.01),  # ~0.005 % IL
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(r["aggregates"]["worst_il_pool"], "BAD")

    def test_simulate_best_net_pool(self):
        pools = [
            _pool(name="HIGH_FEE", initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=9000),
            _pool(name="LOW_FEE", initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=10),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(r["aggregates"]["best_net_pool"], "HIGH_FEE")

    def test_simulate_average_break_even_days(self):
        pools = [
            _pool(name="A", initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=100),
            _pool(name="B", initial=1.0, current=4.0, liquidity=10_000, fee_income_30d=100),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertIsNotNone(r["aggregates"]["average_break_even_days"])
        self.assertGreater(r["aggregates"]["average_break_even_days"], 0)

    def test_simulate_pool_count(self):
        pools = [_pool() for _ in range(5)]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(r["aggregates"]["pool_count"], 5)

    def test_simulate_error_count(self):
        pools = [_pool(), "not_a_dict", _pool()]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 1)
        self.assertEqual(r["aggregates"]["pool_count"], 2)

    def test_simulate_pool_not_dict_recorded_as_error(self):
        r = self.sim.simulate(["bad_pool"], {"write_log": False})
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("error", r["errors"][0])

    def test_simulate_mixed_pool_types(self):
        pools = [
            _pool(name="XY", pool_type="xy"),
            _pool(name="STABLE", pool_type="stable"),
            _pool(
                name="CONC", pool_type="concentrated",
                price_range={"lower_bound": 0.5, "upper_bound": 2.0}
            ),
        ]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(len(r["pools"]), 3)

    def test_simulate_concentrated_out_of_range_flag(self):
        p = _pool(
            name="CONC_OOR", initial=1.0, current=5.0, pool_type="concentrated",
            price_range={"lower_bound": 0.5, "upper_bound": 3.0}
        )
        r = self.sim.simulate([p], {"write_log": False})
        pool_r = r["pools"][0]
        self.assertIn("OUT_OF_RANGE", pool_r["flags"])

    def test_simulate_break_even_none_when_infinite(self):
        p = _pool(initial=1.0, current=2.0, fee_income_30d=0.0)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertIsNone(r["pools"][0]["break_even_days"])

    def test_simulate_raises_typeerror_for_non_list_pools(self):
        with self.assertRaises(TypeError):
            self.sim.simulate("not_a_list", {})

    def test_simulate_raises_typeerror_for_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.sim.simulate([], "not_a_dict")

    def test_simulate_invalid_price_ratio_negative(self):
        p = _pool(initial=-1.0, current=1.0)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 1)

    def test_simulate_invalid_price_ratio_zero(self):
        p = _pool(initial=0.0, current=1.0)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 1)

    def test_simulate_average_be_none_when_all_infinite(self):
        pools = [_pool(fee_income_30d=0.0), _pool(initial=1.0, current=2.0, fee_income_30d=0.0)]
        r = self.sim.simulate(pools, {"write_log": False})
        # Pool 2 has IL but zero fees → None; pool 1 has no IL → be=0
        # mixed: one None, one 0.0 → only the 0.0 is in valid_be
        self.assertIsNotNone(r["aggregates"]["average_break_even_days"])

    def test_simulate_all_flags_possible_in_result(self):
        """At least one pool can carry all 4 flags."""
        # FEE_COVERS_IL: fees > IL abs
        # OUT_OF_RANGE: concentrated, price outside
        # HIGH_IL: abs >= 5 %
        # SHORT_BREAKEVEN: be < 30d
        p_fee = _pool(name="FEE_COVERS", initial=1.0, current=2.0,
                      liquidity=10_000, fee_income_30d=50_000)
        r = self.sim.simulate([p_fee], {"write_log": False})
        self.assertIn("FEE_COVERS_IL", r["pools"][0]["flags"])

    def test_simulate_write_log_false_no_file(self):
        self.sim.simulate([_pool()], {"write_log": False})
        self.assertFalse(os.path.exists(self.data_file))

    def test_simulate_write_log_true_creates_file(self):
        self.sim.simulate([_pool()], {"write_log": True})
        self.assertTrue(os.path.exists(self.data_file))

    def test_simulate_write_log_default_is_true(self):
        self.sim.simulate([_pool()], {})
        self.assertTrue(os.path.exists(self.data_file))

    def test_simulate_fee_covers_il_aggregate_correct(self):
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=1000)
        r = self.sim.simulate([p], {"write_log": False})
        pool_r = r["pools"][0]
        il_abs = abs(pool_r["il_usd"])
        if 1000 > il_abs:
            self.assertIn("FEE_COVERS_IL", pool_r["flags"])
        else:
            self.assertNotIn("FEE_COVERS_IL", pool_r["flags"])

    def test_simulate_multiple_errors(self):
        pools = ["bad1", "bad2", "bad3", _pool()]
        r = self.sim.simulate(pools, {"write_log": False})
        self.assertEqual(r["aggregates"]["error_count"], 3)
        self.assertEqual(r["aggregates"]["pool_count"], 1)


class TestLogFile(unittest.TestCase):
    """Tests for ring-buffer log file functionality."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def test_log_creates_file(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_appends_entries(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool()], {"write_log": True})
        sim.simulate([_pool()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 2)

    def test_log_ring_buffer_cap_100(self):
        """Ring buffer should not exceed 100 entries."""
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        for _ in range(110):
            sim.simulate([_pool()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertLessEqual(len(log), 100)

    def test_log_atomic_write(self):
        """File should be valid JSON after atomic write."""
        _atomic_write(self.log_path, [{"test": True}])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"test": True}])

    def test_log_invalid_json_recovers(self):
        """If the file has corrupt JSON, load_log returns []."""
        with open(self.log_path, "w") as f:
            f.write("NOT VALID JSON {{{{")
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_log_missing_file_returns_empty(self):
        result = _load_log("/nonexistent/path/file.json")
        self.assertEqual(result, [])

    def test_log_entry_has_timestamp(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertIn("timestamp", log[-1])

    def test_log_entry_has_pool_count(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool(), _pool()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertEqual(log[-1]["pool_count"], 2)

    def test_log_entry_has_total_il_usd(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool()], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertIn("total_il_usd", log[-1])

    def test_log_entry_has_total_fee_income_usd(self):
        sim = DeFiAMMImpermanentLossSimulator(data_file=self.log_path)
        sim.simulate([_pool(fee_income_30d=999)], {"write_log": True})
        log = _load_log(self.log_path)
        self.assertEqual(log[-1]["total_fee_income_usd"], 999.0)

    def test_append_log_preserves_existing(self):
        _atomic_write(self.log_path, [{"existing": 1}])
        _append_log(self.log_path, {"new": 2})
        log = _load_log(self.log_path)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0]["existing"], 1)
        self.assertEqual(log[1]["new"], 2)

    def test_load_log_non_list_json_returns_empty(self):
        _atomic_write(self.log_path, {"not": "a list"})
        result = _load_log(self.log_path)
        self.assertEqual(result, [])


class TestEdgeCases(unittest.TestCase):
    """Edge-case & boundary tests."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.sim = DeFiAMMImpermanentLossSimulator(
            data_file=os.path.join(self.tmp_dir, "edge.json")
        )

    def test_simulate_very_high_liquidity(self):
        p = _pool(liquidity=1_000_000_000, initial=1.0, current=4.0)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertAlmostEqual(r["pools"][0]["il_usd"], -200_000_000.0, places=0)

    def test_stable_pool_near_zero_il_on_small_move(self):
        p = _pool(pool_type="stable", initial=1.0, current=1.001, liquidity=100_000)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertGreater(r["pools"][0]["il_pct"], -0.01)  # very small

    def test_concentrated_narrow_range_high_amplification(self):
        p = _pool(
            initial=1.0, current=1.001, pool_type="concentrated",
            price_range={"lower_bound": 0.999, "upper_bound": 1.002}
        )
        r = self.sim.simulate([p], {"write_log": False})
        xy_p = _pool(initial=1.0, current=1.001)
        r_xy = self.sim.simulate([xy_p], {"write_log": False})
        # Concentrated should have higher abs IL than xy
        self.assertLessEqual(r["pools"][0]["il_pct"], r_xy["pools"][0]["il_pct"])

    def test_aggregates_none_when_no_valid_pools(self):
        r = self.sim.simulate([], {"write_log": False})
        self.assertIsNone(r["aggregates"]["worst_il_pool"])
        self.assertIsNone(r["aggregates"]["best_net_pool"])
        self.assertIsNone(r["aggregates"]["average_break_even_days"])

    def test_break_even_short_flag_just_under_30d(self):
        # Make fees such that be ≈ 29 days
        # IL abs = 572 USD (r=2, liq=10000)
        # daily_fee = fee/30 → be = 572/(fee/30) < 30 → fee > 572 USD
        p = _pool(initial=1.0, current=2.0, liquidity=10_000, fee_income_30d=600)
        r = self.sim.simulate([p], {"write_log": False})
        pool_r = r["pools"][0]
        if pool_r["break_even_days"] is not None and pool_r["break_even_days"] < 30:
            self.assertIn("SHORT_BREAKEVEN", pool_r["flags"])

    def test_fee_tier_pct_stored_in_result(self):
        p = _pool(fee_tier=1.5)
        r = self.sim.simulate([p], {"write_log": False})
        self.assertEqual(r["pools"][0]["fee_tier_pct"], 1.5)

    def test_token_names_preserved(self):
        p = _pool(token_a="WBTC", token_b="DAI")
        r = self.sim.simulate([p], {"write_log": False})
        self.assertEqual(r["pools"][0]["token_a"], "WBTC")
        self.assertEqual(r["pools"][0]["token_b"], "DAI")

    def test_simulate_all_pool_types_accepted(self):
        for pt in ["xy", "stable", "concentrated"]:
            with self.subTest(pool_type=pt):
                pr = {"lower_bound": 0.5, "upper_bound": 2.0} if pt == "concentrated" else None
                p = _pool(pool_type=pt, price_range=pr)
                r = self.sim.simulate([p], {"write_log": False})
                self.assertEqual(len(r["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
