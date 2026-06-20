"""
Tests for MP-1112  DeFiProtocolLeverageAdjustedAPYCalculator
Run: python3 -m unittest spa_core.tests.test_defi_protocol_leverage_adjusted_apy_calculator -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

# Ensure repo root is on path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_leverage_adjusted_apy_calculator import (
    DeFiProtocolLeverageAdjustedAPYCalculator,
    _clamp,
    _compute_effective_leverage,
    _label_from_safety_margin,
    _atomic_log,
    _LOG_CAP,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helper: build a minimal valid data dict
# ---------------------------------------------------------------------------

def _data(
    base_supply_apy_pct=5.0,
    borrow_apy_pct=2.0,
    ltv_ratio=0.75,
    num_loops=3,
    liquidation_ltv_pct=80.0,
    initial_capital_usd=10_000.0,
    protocol_name="TestProto",
):
    return {
        "base_supply_apy_pct": base_supply_apy_pct,
        "borrow_apy_pct": borrow_apy_pct,
        "ltv_ratio": ltv_ratio,
        "num_loops": num_loops,
        "liquidation_ltv_pct": liquidation_ltv_pct,
        "initial_capital_usd": initial_capital_usd,
        "protocol_name": protocol_name,
    }


# ===========================================================================
# 1. Helpers — _clamp
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_below_low(self):
        self.assertEqual(_clamp(-5.0, 0.0, 10.0), 0.0)

    def test_above_high(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_at_low(self):
        self.assertEqual(_clamp(0.0, 0.0, 10.0), 0.0)

    def test_at_high(self):
        self.assertEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_negative_range(self):
        self.assertEqual(_clamp(-3.0, -5.0, -1.0), -3.0)

    def test_clamp_to_low_negative(self):
        self.assertEqual(_clamp(-10.0, -5.0, -1.0), -5.0)

    def test_clamp_to_high_negative(self):
        self.assertEqual(_clamp(0.0, -5.0, -1.0), -1.0)


# ===========================================================================
# 2. Helpers — _compute_effective_leverage
# ===========================================================================

class TestComputeEffectiveLeverage(unittest.TestCase):
    def test_one_loop_is_unity(self):
        self.assertAlmostEqual(_compute_effective_leverage(0.75, 1), 1.0, places=9)

    def test_zero_loops_clamped_to_one(self):
        self.assertAlmostEqual(_compute_effective_leverage(0.75, 0), 1.0, places=9)

    def test_negative_loops_clamped_to_one(self):
        self.assertAlmostEqual(_compute_effective_leverage(0.75, -5), 1.0, places=9)

    def test_two_loops_formula(self):
        # (1 - 0.75^2) / (1 - 0.75) = (1 - 0.5625)/0.25 = 0.4375/0.25 = 1.75
        result = _compute_effective_leverage(0.75, 2)
        self.assertAlmostEqual(result, 1.75, places=6)

    def test_three_loops_formula(self):
        # (1 - 0.75^3) / (1 - 0.75) = (1 - 0.421875)/0.25 = 2.3125
        result = _compute_effective_leverage(0.75, 3)
        self.assertAlmostEqual(result, 2.3125, places=6)

    def test_four_loops(self):
        ltv = 0.8
        n = 4
        expected = (1 - ltv**n) / (1 - ltv)
        self.assertAlmostEqual(_compute_effective_leverage(ltv, n), expected, places=6)

    def test_ten_loops(self):
        ltv = 0.5
        n = 10
        expected = (1 - ltv**n) / (1 - ltv)
        self.assertAlmostEqual(_compute_effective_leverage(ltv, n), expected, places=6)

    def test_ltv_one_gives_num_loops(self):
        # limit: when ltv=1, leverage = n
        self.assertAlmostEqual(_compute_effective_leverage(1.0, 5), 5.0, places=9)

    def test_ltv_one_single_loop(self):
        self.assertAlmostEqual(_compute_effective_leverage(1.0, 1), 1.0, places=9)

    def test_ltv_zero_gives_unity(self):
        self.assertAlmostEqual(_compute_effective_leverage(0.0, 10), 1.0, places=9)

    def test_leverage_increases_with_loops(self):
        lev2 = _compute_effective_leverage(0.75, 2)
        lev5 = _compute_effective_leverage(0.75, 5)
        lev10 = _compute_effective_leverage(0.75, 10)
        self.assertLess(lev2, lev5)
        self.assertLess(lev5, lev10)

    def test_leverage_increases_with_ltv(self):
        lev_low = _compute_effective_leverage(0.5, 5)
        lev_high = _compute_effective_leverage(0.9, 5)
        self.assertLess(lev_low, lev_high)

    def test_limit_approaches_1_over_1_minus_ltv(self):
        ltv = 0.75
        limit = 1.0 / (1.0 - ltv)  # = 4.0
        lev_big = _compute_effective_leverage(ltv, 100)
        self.assertAlmostEqual(lev_big, limit, places=4)


# ===========================================================================
# 3. Helpers — _label_from_safety_margin
# ===========================================================================

class TestLabelFromSafetyMargin(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(_label_from_safety_margin(25.0), "SAFE_LEVERAGE")

    def test_safe_boundary_above_20(self):
        self.assertEqual(_label_from_safety_margin(20.01), "SAFE_LEVERAGE")

    def test_moderate(self):
        self.assertEqual(_label_from_safety_margin(15.0), "MODERATE_LEVERAGE")

    def test_moderate_at_20(self):
        self.assertEqual(_label_from_safety_margin(20.0), "MODERATE_LEVERAGE")

    def test_moderate_just_above_10(self):
        self.assertEqual(_label_from_safety_margin(10.01), "MODERATE_LEVERAGE")

    def test_aggressive(self):
        self.assertEqual(_label_from_safety_margin(7.5), "AGGRESSIVE_LEVERAGE")

    def test_aggressive_at_10(self):
        self.assertEqual(_label_from_safety_margin(10.0), "AGGRESSIVE_LEVERAGE")

    def test_aggressive_just_above_5(self):
        self.assertEqual(_label_from_safety_margin(5.01), "AGGRESSIVE_LEVERAGE")

    def test_dangerous(self):
        self.assertEqual(_label_from_safety_margin(2.5), "DANGEROUS_LEVERAGE")

    def test_dangerous_at_5(self):
        self.assertEqual(_label_from_safety_margin(5.0), "DANGEROUS_LEVERAGE")

    def test_dangerous_just_above_zero(self):
        self.assertEqual(_label_from_safety_margin(0.001), "DANGEROUS_LEVERAGE")

    def test_liquidation_imminent_at_zero(self):
        self.assertEqual(_label_from_safety_margin(0.0), "LIQUIDATION_IMMINENT")

    def test_liquidation_imminent_negative(self):
        self.assertEqual(_label_from_safety_margin(-5.0), "LIQUIDATION_IMMINENT")

    def test_liquidation_imminent_very_negative(self):
        self.assertEqual(_label_from_safety_margin(-100.0), "LIQUIDATION_IMMINENT")


# ===========================================================================
# 4. Core calculator — instantiation
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        self.assertIsNotNone(calc)

    def test_calculate_returns_dict(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        result = calc.calculate(_data(), NO_LOG)
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        result = calc.calculate(_data(), NO_LOG)
        expected_keys = [
            "protocol_name",
            "base_supply_apy_pct",
            "borrow_apy_pct",
            "ltv_ratio",
            "num_loops",
            "liquidation_ltv_pct",
            "initial_capital_usd",
            "effective_leverage_x",
            "total_exposure_usd",
            "total_debt_usd",
            "current_composite_ltv_pct",
            "leveraged_supply_apy_pct",
            "leveraged_borrow_cost_pct",
            "net_leveraged_apy_pct",
            "safety_margin_pct",
            "leverage_label",
            "timestamp",
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_protocol_name_stored(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        result = calc.calculate(_data(protocol_name="Aave"), NO_LOG)
        self.assertEqual(result["protocol_name"], "Aave")

    def test_timestamp_is_float(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        result = calc.calculate(_data(), NO_LOG)
        self.assertIsInstance(result["timestamp"], float)
        self.assertGreater(result["timestamp"], 0.0)


# ===========================================================================
# 5. Core calculations — effective_leverage_x
# ===========================================================================

class TestEffectiveLeverageInResult(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_one_loop_leverage_is_one(self):
        r = self.calc.calculate(_data(ltv_ratio=0.75, num_loops=1), NO_LOG)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=5)

    def test_three_loops_leverage(self):
        r = self.calc.calculate(_data(ltv_ratio=0.75, num_loops=3), NO_LOG)
        expected = (1 - 0.75**3) / (1 - 0.75)
        self.assertAlmostEqual(r["effective_leverage_x"], expected, places=4)

    def test_leverage_gt_one_for_loops_gt_one(self):
        r = self.calc.calculate(_data(ltv_ratio=0.8, num_loops=5), NO_LOG)
        self.assertGreater(r["effective_leverage_x"], 1.0)

    def test_leverage_with_ltv_one(self):
        r = self.calc.calculate(_data(ltv_ratio=1.0, num_loops=7), NO_LOG)
        self.assertAlmostEqual(r["effective_leverage_x"], 7.0, places=5)


# ===========================================================================
# 6. Core calculations — exposure & debt
# ===========================================================================

class TestExposureAndDebt(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_total_exposure_equals_capital_times_leverage(self):
        capital = 10_000.0
        r = self.calc.calculate(_data(initial_capital_usd=capital, num_loops=3, ltv_ratio=0.75), NO_LOG)
        expected_lev = (1 - 0.75**3) / (1 - 0.75)
        self.assertAlmostEqual(r["total_exposure_usd"], capital * expected_lev, places=2)

    def test_total_debt_equals_exposure_minus_capital(self):
        r = self.calc.calculate(_data(initial_capital_usd=5000, num_loops=4, ltv_ratio=0.6), NO_LOG)
        self.assertAlmostEqual(
            r["total_debt_usd"],
            r["total_exposure_usd"] - 5000.0,
            places=4,
        )

    def test_no_leverage_debt_is_zero(self):
        r = self.calc.calculate(_data(num_loops=1, initial_capital_usd=10000), NO_LOG)
        self.assertAlmostEqual(r["total_debt_usd"], 0.0, places=6)

    def test_no_leverage_exposure_equals_capital(self):
        r = self.calc.calculate(_data(num_loops=1, initial_capital_usd=7500), NO_LOG)
        self.assertAlmostEqual(r["total_exposure_usd"], 7500.0, places=6)

    def test_debt_increases_with_loops(self):
        r2 = self.calc.calculate(_data(num_loops=2, ltv_ratio=0.7), NO_LOG)
        r5 = self.calc.calculate(_data(num_loops=5, ltv_ratio=0.7), NO_LOG)
        self.assertLess(r2["total_debt_usd"], r5["total_debt_usd"])

    def test_zero_capital_gives_zero_exposure(self):
        r = self.calc.calculate(_data(initial_capital_usd=0.0, num_loops=5), NO_LOG)
        self.assertAlmostEqual(r["total_exposure_usd"], 0.0, places=6)
        self.assertAlmostEqual(r["total_debt_usd"], 0.0, places=6)


# ===========================================================================
# 7. Core calculations — composite LTV
# ===========================================================================

class TestCompositeGTV(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_no_leverage_composite_ltv_is_zero(self):
        r = self.calc.calculate(_data(num_loops=1), NO_LOG)
        self.assertAlmostEqual(r["current_composite_ltv_pct"], 0.0, places=6)

    def test_composite_ltv_formula(self):
        r = self.calc.calculate(_data(ltv_ratio=0.75, num_loops=4), NO_LOG)
        lev = r["effective_leverage_x"]
        expected_ltv = (lev - 1.0) / lev * 100.0
        self.assertAlmostEqual(r["current_composite_ltv_pct"], expected_ltv, places=4)

    def test_composite_ltv_below_liquidation(self):
        r = self.calc.calculate(_data(ltv_ratio=0.7, num_loops=3, liquidation_ltv_pct=85.0), NO_LOG)
        self.assertLess(r["current_composite_ltv_pct"], 85.0)

    def test_composite_ltv_approaches_100_many_loops(self):
        r = self.calc.calculate(_data(ltv_ratio=0.99, num_loops=50, liquidation_ltv_pct=100.0), NO_LOG)
        # With very high ltv and many loops, composite LTV approaches 99%
        self.assertGreater(r["current_composite_ltv_pct"], 80.0)

    def test_zero_capital_composite_ltv_zero(self):
        r = self.calc.calculate(_data(initial_capital_usd=0.0, num_loops=3), NO_LOG)
        self.assertAlmostEqual(r["current_composite_ltv_pct"], 0.0, places=6)


# ===========================================================================
# 8. Core calculations — APY metrics
# ===========================================================================

class TestAPYMetrics(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_leveraged_supply_apy_equals_base_times_leverage(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=6.0, ltv_ratio=0.75, num_loops=3), NO_LOG)
        lev = r["effective_leverage_x"]
        self.assertAlmostEqual(r["leveraged_supply_apy_pct"], 6.0 * lev, places=4)

    def test_leveraged_borrow_cost_equals_borrow_times_debt_leverage(self):
        r = self.calc.calculate(_data(borrow_apy_pct=3.0, ltv_ratio=0.75, num_loops=3), NO_LOG)
        lev = r["effective_leverage_x"]
        self.assertAlmostEqual(r["leveraged_borrow_cost_pct"], 3.0 * (lev - 1.0), places=4)

    def test_net_apy_is_supply_minus_cost(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=8.0, borrow_apy_pct=3.5, ltv_ratio=0.8, num_loops=4), NO_LOG)
        expected = r["leveraged_supply_apy_pct"] - r["leveraged_borrow_cost_pct"]
        self.assertAlmostEqual(r["net_leveraged_apy_pct"], expected, places=4)

    def test_no_leverage_supply_apy_equals_base(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=5.0, num_loops=1), NO_LOG)
        self.assertAlmostEqual(r["leveraged_supply_apy_pct"], 5.0, places=5)

    def test_no_leverage_borrow_cost_is_zero(self):
        r = self.calc.calculate(_data(borrow_apy_pct=3.0, num_loops=1), NO_LOG)
        self.assertAlmostEqual(r["leveraged_borrow_cost_pct"], 0.0, places=5)

    def test_no_leverage_net_apy_equals_base(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=5.0, borrow_apy_pct=3.0, num_loops=1), NO_LOG)
        self.assertAlmostEqual(r["net_leveraged_apy_pct"], 5.0, places=5)

    def test_negative_net_apy_when_borrow_exceeds_supply(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=2.0, borrow_apy_pct=5.0, num_loops=3), NO_LOG)
        self.assertLess(r["net_leveraged_apy_pct"], 0.0)

    def test_zero_borrow_gives_pure_supply_amplification(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=5.0, borrow_apy_pct=0.0, ltv_ratio=0.75, num_loops=3), NO_LOG)
        lev = r["effective_leverage_x"]
        self.assertAlmostEqual(r["net_leveraged_apy_pct"], 5.0 * lev, places=4)

    def test_supply_apy_amplified_with_loops(self):
        r1 = self.calc.calculate(_data(base_supply_apy_pct=5.0, num_loops=1, ltv_ratio=0.75), NO_LOG)
        r3 = self.calc.calculate(_data(base_supply_apy_pct=5.0, num_loops=3, ltv_ratio=0.75), NO_LOG)
        self.assertLess(r1["leveraged_supply_apy_pct"], r3["leveraged_supply_apy_pct"])


# ===========================================================================
# 9. Safety margin and label
# ===========================================================================

class TestSafetyMarginAndLabel(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_safety_margin_formula(self):
        r = self.calc.calculate(_data(ltv_ratio=0.75, num_loops=3, liquidation_ltv_pct=80.0), NO_LOG)
        expected_safety = 80.0 - r["current_composite_ltv_pct"]
        self.assertAlmostEqual(r["safety_margin_pct"], expected_safety, places=4)

    def test_no_leverage_safety_equals_liq_ltv(self):
        r = self.calc.calculate(_data(num_loops=1, liquidation_ltv_pct=80.0), NO_LOG)
        self.assertAlmostEqual(r["safety_margin_pct"], 80.0, places=5)

    def test_safe_label_high_margin(self):
        r = self.calc.calculate(_data(num_loops=1, liquidation_ltv_pct=80.0), NO_LOG)
        self.assertEqual(r["leverage_label"], "SAFE_LEVERAGE")

    def test_moderate_label(self):
        # ltv=0.7, loops=5 → leverage ≈ 2.8 → comp_ltv ≈ 64.4% → margin vs 80 = 15.6 → MODERATE
        r = self.calc.calculate(_data(ltv_ratio=0.7, num_loops=5, liquidation_ltv_pct=80.0), NO_LOG)
        margin = r["safety_margin_pct"]
        if 10 < margin <= 20:
            self.assertEqual(r["leverage_label"], "MODERATE_LEVERAGE")
        # Accept any valid label—what matters is it matches the margin
        self.assertEqual(r["leverage_label"], _label_from_safety_margin(margin))

    def test_label_matches_safety_margin(self):
        for loops in [1, 2, 3, 5, 8, 10]:
            r = self.calc.calculate(_data(ltv_ratio=0.75, num_loops=loops, liquidation_ltv_pct=80.0), NO_LOG)
            self.assertEqual(r["leverage_label"], _label_from_safety_margin(r["safety_margin_pct"]))

    def test_liquidation_imminent_when_ltv_exceeds_liquidation(self):
        # ltv=0.95, many loops → composite LTV > liquidation_ltv
        r = self.calc.calculate(_data(ltv_ratio=0.95, num_loops=20, liquidation_ltv_pct=80.0), NO_LOG)
        self.assertLessEqual(r["safety_margin_pct"], 0.0)
        self.assertEqual(r["leverage_label"], "LIQUIDATION_IMMINENT")

    def test_high_liquidation_ltv_gives_safe_label(self):
        r = self.calc.calculate(_data(ltv_ratio=0.9, num_loops=3, liquidation_ltv_pct=99.0), NO_LOG)
        # comp_ltv for ltv=0.9, n=3: (1-0.9^3)/(1-0.9) = (1-0.729)/0.1 = 2.71 → debt/exposure = 1.71/2.71 ≈ 63.1%
        # safety = 99 - 63.1 = 35.9% → SAFE
        self.assertEqual(r["leverage_label"], "SAFE_LEVERAGE")


# ===========================================================================
# 10. Input guards / edge cases
# ===========================================================================

class TestInputGuards(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_num_loops_zero_clamped_to_one(self):
        r = self.calc.calculate(_data(num_loops=0), NO_LOG)
        self.assertEqual(r["num_loops"], 1)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=5)

    def test_num_loops_negative_clamped_to_one(self):
        r = self.calc.calculate(_data(num_loops=-10), NO_LOG)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=5)

    def test_ltv_ratio_above_one_clamped(self):
        r = self.calc.calculate(_data(ltv_ratio=1.5, num_loops=3), NO_LOG)
        self.assertLessEqual(r["ltv_ratio"], 1.0)

    def test_ltv_ratio_negative_clamped(self):
        r = self.calc.calculate(_data(ltv_ratio=-0.5, num_loops=3), NO_LOG)
        self.assertGreaterEqual(r["ltv_ratio"], 0.0)

    def test_negative_capital_clamped_to_zero(self):
        r = self.calc.calculate(_data(initial_capital_usd=-5000.0), NO_LOG)
        self.assertGreaterEqual(r["initial_capital_usd"], 0.0)
        self.assertAlmostEqual(r["total_exposure_usd"], 0.0, places=6)

    def test_float_coercion_num_loops(self):
        r = self.calc.calculate({"num_loops": "4", **{k: v for k, v in _data().items() if k != "num_loops"}}, NO_LOG)
        self.assertIsInstance(r["num_loops"], int)

    def test_missing_protocol_name_defaults_to_unknown(self):
        d = _data()
        del d["protocol_name"]
        r = self.calc.calculate(d, NO_LOG)
        self.assertEqual(r["protocol_name"], "unknown")

    def test_missing_liquidation_ltv_defaults(self):
        d = _data()
        del d["liquidation_ltv_pct"]
        r = self.calc.calculate(d, NO_LOG)
        self.assertIn("liquidation_ltv_pct", r)
        self.assertAlmostEqual(r["liquidation_ltv_pct"], 80.0, places=5)

    def test_zero_base_supply_apy(self):
        r = self.calc.calculate(_data(base_supply_apy_pct=0.0), NO_LOG)
        self.assertAlmostEqual(r["leveraged_supply_apy_pct"], 0.0, places=6)

    def test_zero_borrow_apy(self):
        r = self.calc.calculate(_data(borrow_apy_pct=0.0), NO_LOG)
        self.assertAlmostEqual(r["leveraged_borrow_cost_pct"], 0.0, places=6)

    def test_very_large_capital(self):
        r = self.calc.calculate(_data(initial_capital_usd=1e9, num_loops=2, ltv_ratio=0.8), NO_LOG)
        self.assertGreater(r["total_exposure_usd"], 1e9)

    def test_very_high_num_loops_hard_cap(self):
        r = self.calc.calculate(_data(num_loops=10_000, ltv_ratio=0.8), NO_LOG)
        # Must not raise; leverage capped at hard-cap scenario
        self.assertIsNotNone(r)

    def test_empty_dict_uses_defaults(self):
        r = self.calc.calculate({}, NO_LOG)
        self.assertIn("effective_leverage_x", r)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=5)  # num_loops defaults to 1


# ===========================================================================
# 11. Numeric precision
# ===========================================================================

class TestNumericPrecision(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_results_are_rounded_to_6_places(self):
        r = self.calc.calculate(_data(ltv_ratio=1/3, num_loops=5), NO_LOG)
        for key in ["effective_leverage_x", "total_exposure_usd", "total_debt_usd",
                    "leveraged_supply_apy_pct", "leveraged_borrow_cost_pct",
                    "net_leveraged_apy_pct", "safety_margin_pct"]:
            val = r[key]
            # Check it doesn't exceed 6 decimal places (within floating-point noise)
            self.assertAlmostEqual(val, round(val, 6), places=9, msg=f"{key} not rounded")

    def test_leverage_formula_exact_for_ltv_half(self):
        # ltv=0.5, n=4: (1 - 0.0625)/(0.5) = 0.9375/0.5 = 1.875
        r = self.calc.calculate(_data(ltv_ratio=0.5, num_loops=4), NO_LOG)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.875, places=6)


# ===========================================================================
# 12. Batch mode
# ===========================================================================

class TestBatchMode(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_batch_returns_dict(self):
        out = self.calc.calculate_batch([_data(), _data()], NO_LOG)
        self.assertIsInstance(out, dict)

    def test_batch_top_level_keys(self):
        out = self.calc.calculate_batch([_data()], NO_LOG)
        for k in ("results", "summary", "timestamp"):
            self.assertIn(k, out)

    def test_batch_results_length(self):
        out = self.calc.calculate_batch([_data(), _data(), _data()], NO_LOG)
        self.assertEqual(len(out["results"]), 3)

    def test_batch_empty_list(self):
        out = self.calc.calculate_batch([], NO_LOG)
        self.assertEqual(out["summary"]["count"], 0)

    def test_batch_raises_on_non_list(self):
        with self.assertRaises(TypeError):
            self.calc.calculate_batch("not a list", NO_LOG)

    def test_batch_summary_count(self):
        out = self.calc.calculate_batch([_data(), _data()], NO_LOG)
        self.assertEqual(out["summary"]["count"], 2)

    def test_batch_summary_avg_net_apy(self):
        d1 = _data(base_supply_apy_pct=5.0, borrow_apy_pct=2.0, num_loops=1)
        d2 = _data(base_supply_apy_pct=7.0, borrow_apy_pct=2.0, num_loops=1)
        out = self.calc.calculate_batch([d1, d2], NO_LOG)
        # no leverage → net_apy = base_supply - 0
        self.assertAlmostEqual(out["summary"]["avg_net_apy_pct"], 6.0, places=4)

    def test_batch_summary_keys_present(self):
        out = self.calc.calculate_batch([_data()], NO_LOG)
        summary_keys = [
            "count", "avg_net_apy_pct", "max_net_apy_pct", "min_net_apy_pct",
            "avg_leverage_x", "max_leverage_x", "min_safety_margin_pct",
            "liquidation_imminent_count", "dangerous_count", "safe_count",
        ]
        for k in summary_keys:
            self.assertIn(k, out["summary"])

    def test_batch_liquidation_imminent_counted(self):
        safe = _data(num_loops=1, liquidation_ltv_pct=80.0)
        danger = _data(ltv_ratio=0.95, num_loops=50, liquidation_ltv_pct=80.0)
        out = self.calc.calculate_batch([safe, danger], NO_LOG)
        self.assertGreaterEqual(out["summary"]["liquidation_imminent_count"], 1)

    def test_batch_timestamp_is_float(self):
        out = self.calc.calculate_batch([_data()], NO_LOG)
        self.assertIsInstance(out["timestamp"], float)


# ===========================================================================
# 13. Log file — _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test_log.json")
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends_entries(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test_log.json")
            _atomic_log(path, {"n": 1})
            _atomic_log(path, {"n": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[1]["n"], 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test_log.json")
            for i in range(_LOG_CAP + 10):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), _LOG_CAP)
            # Should keep the most recent entries
            self.assertEqual(data[-1]["i"], _LOG_CAP + 9)

    def test_log_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test_log.json")
            _atomic_log(path, {"key": "value"})
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_recovers_from_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test_log.json")
            with open(path, "w") as f:
                f.write("NOT JSON")
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["ok"])

    def test_log_written_by_calculate(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "lev_log.json")
            calc.calculate(_data(), {"write_log": True, "log_path": log_path})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertIn("protocol_name", data[0])

    def test_no_log_skips_write(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "nolog.json")
            calc.calculate(_data(), {"write_log": False, "log_path": log_path})
            self.assertFalse(os.path.exists(log_path))

    def test_log_entry_contains_expected_fields(self):
        calc = DeFiProtocolLeverageAdjustedAPYCalculator()
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "lev_log.json")
            calc.calculate(_data(protocol_name="Compound"), {"write_log": True, "log_path": log_path})
            with open(log_path) as f:
                entry = json.load(f)[0]
            for field in ["timestamp", "protocol_name", "effective_leverage_x", "leverage_label"]:
                self.assertIn(field, entry)


# ===========================================================================
# 14. Scenario tests
# ===========================================================================

class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_no_leverage_scenario(self):
        """1 loop = no leverage, APY unchanged, no debt, full safety."""
        r = self.calc.calculate(_data(
            base_supply_apy_pct=5.0,
            borrow_apy_pct=3.0,
            num_loops=1,
            liquidation_ltv_pct=80.0,
        ), NO_LOG)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=5)
        self.assertAlmostEqual(r["total_debt_usd"], 0.0, places=4)
        self.assertAlmostEqual(r["net_leveraged_apy_pct"], 5.0, places=5)
        self.assertEqual(r["leverage_label"], "SAFE_LEVERAGE")

    def test_e_mode_loop_aave_style(self):
        """E-mode: ltv=0.9, 5 loops → high leverage, check math consistency."""
        r = self.calc.calculate(_data(
            base_supply_apy_pct=4.0,
            borrow_apy_pct=2.5,
            ltv_ratio=0.9,
            num_loops=5,
            liquidation_ltv_pct=93.0,
            initial_capital_usd=50_000,
        ), NO_LOG)
        # leverage = (1 - 0.9^5)/(0.1) = (1 - 0.59049)/0.1 = 4.0951
        self.assertAlmostEqual(r["effective_leverage_x"], (1 - 0.9**5) / 0.1, places=4)
        # net_apy should be positive (supply > borrow)
        self.assertGreater(r["net_leveraged_apy_pct"], 0.0)

    def test_dangerous_loop(self):
        """Very high ltv=0.95, 15 loops → near-liquidation, safety < 5%."""
        r = self.calc.calculate(_data(
            ltv_ratio=0.95,
            num_loops=15,
            liquidation_ltv_pct=94.0,
        ), NO_LOG)
        # leverage ≈ (1-0.95^15)/0.05 ≈ 10.73 → composite LTV ≈ 90.7%
        # safety = 94 - 90.7 = 3.3% → DANGEROUS
        self.assertLess(r["safety_margin_pct"], 5.0)

    def test_carry_negative_borrow_dominant(self):
        """Borrow cost dominates → negative carry even with leverage."""
        r = self.calc.calculate(_data(
            base_supply_apy_pct=3.0,
            borrow_apy_pct=7.0,
            ltv_ratio=0.8,
            num_loops=5,
        ), NO_LOG)
        self.assertLess(r["net_leveraged_apy_pct"], 0.0)

    def test_arbitrage_near_zero_spread(self):
        """Supply ≈ borrow: net APY close to zero."""
        r = self.calc.calculate(_data(
            base_supply_apy_pct=4.0,
            borrow_apy_pct=4.0,
            num_loops=3,
        ), NO_LOG)
        # net = supply*lev - borrow*(lev-1) = lev*(supply-borrow) + borrow = borrow
        # = 4.0 → net_leveraged_apy ≈ supply_apy (4.0), because
        # leveraged_supply = 4*lev, leveraged_borrow = 4*(lev-1)
        # net = 4*lev - 4*(lev-1) = 4
        self.assertAlmostEqual(r["net_leveraged_apy_pct"], 4.0, places=4)

    def test_high_supply_low_borrow_positive_carry(self):
        """Strong carry: supply >> borrow → net APY significantly positive."""
        r = self.calc.calculate(_data(
            base_supply_apy_pct=10.0,
            borrow_apy_pct=2.0,
            ltv_ratio=0.75,
            num_loops=4,
        ), NO_LOG)
        self.assertGreater(r["net_leveraged_apy_pct"], 10.0)

    def test_two_positions_different_ltv(self):
        """Higher LTV = higher leverage = different APY and LTV."""
        r_low = self.calc.calculate(_data(ltv_ratio=0.5, num_loops=4), NO_LOG)
        r_high = self.calc.calculate(_data(ltv_ratio=0.8, num_loops=4), NO_LOG)
        self.assertLess(r_low["effective_leverage_x"], r_high["effective_leverage_x"])
        self.assertLess(r_low["current_composite_ltv_pct"], r_high["current_composite_ltv_pct"])


# ===========================================================================
# 15. Integration — calculate → values are internally consistent
# ===========================================================================

class TestInternalConsistency(unittest.TestCase):
    def setUp(self):
        self.calc = DeFiProtocolLeverageAdjustedAPYCalculator()

    def test_total_exposure_ge_initial_capital(self):
        r = self.calc.calculate(_data(num_loops=3), NO_LOG)
        self.assertGreaterEqual(r["total_exposure_usd"], r["initial_capital_usd"])

    def test_total_debt_ge_zero(self):
        r = self.calc.calculate(_data(num_loops=3), NO_LOG)
        self.assertGreaterEqual(r["total_debt_usd"], 0.0)

    def test_composite_ltv_in_0_100(self):
        r = self.calc.calculate(_data(ltv_ratio=0.8, num_loops=10), NO_LOG)
        self.assertGreaterEqual(r["current_composite_ltv_pct"], 0.0)
        self.assertLessEqual(r["current_composite_ltv_pct"], 100.0)

    def test_label_is_valid_string(self):
        valid_labels = {
            "SAFE_LEVERAGE", "MODERATE_LEVERAGE", "AGGRESSIVE_LEVERAGE",
            "DANGEROUS_LEVERAGE", "LIQUIDATION_IMMINENT",
        }
        for loops in range(1, 8):
            r = self.calc.calculate(_data(num_loops=loops, ltv_ratio=0.75), NO_LOG)
            self.assertIn(r["leverage_label"], valid_labels)

    def test_leverage_not_less_than_one(self):
        r = self.calc.calculate(_data(ltv_ratio=0.9, num_loops=5), NO_LOG)
        self.assertGreaterEqual(r["effective_leverage_x"], 1.0)

    def test_debt_plus_capital_equals_exposure(self):
        r = self.calc.calculate(_data(initial_capital_usd=20_000, num_loops=4, ltv_ratio=0.6), NO_LOG)
        self.assertAlmostEqual(
            r["total_debt_usd"] + r["initial_capital_usd"],
            r["total_exposure_usd"],
            places=3,
        )


if __name__ == "__main__":
    unittest.main()
