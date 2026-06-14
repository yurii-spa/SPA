#!/usr/bin/env python3
"""Unit tests for MP-1034 DeFiProtocolInterestRateModelAnalyzer (SPA-V755).

Run:
    python3 -m unittest spa_core/tests/test_defi_protocol_interest_rate_model_analyzer.py -v

stdlib unittest only — no pytest, no numpy.
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_protocol_interest_rate_model_analyzer import (
    DeFiProtocolInterestRateModelAnalyzer,
    _clamp,
    _compute_borrow_rate,
    _compute_supply_rate,
    _compute_utilization_efficiency,
    _compute_rate_volatility_risk,
    _compute_label,
    _load_json_list,
    _atomic_write,
    analyze_rate_model,
    write_log,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    CRISIS_BORROW_RATE_THRESHOLD,
    CRISIS_UTILIZATION_THRESHOLD,
    OPTIMAL_BAND_PCT,
    VALID_MODEL_TYPES,
)


# ===========================================================================
# 1. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below_low(self):
        self.assertAlmostEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above_high(self):
        self.assertAlmostEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_clamp_at_low_boundary(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 10.0), 0.0)

    def test_clamp_at_high_boundary(self):
        self.assertAlmostEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_clamp_negative_range(self):
        self.assertAlmostEqual(_clamp(-5.0, -10.0, -1.0), -5.0)


# ===========================================================================
# 2. _compute_borrow_rate — KINK model
# ===========================================================================

class TestComputeBorrowRateKink(unittest.TestCase):

    # kink=80, base=0, slope1=4, slope2=75
    # Below kink: rate = 0 + 4 * (u/80)
    # Above kink: rate = 0 + 4 + 75 * ((u-80)/20)

    def test_kink_zero_utilization(self):
        rate, warnings = _compute_borrow_rate("kink", 0.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 0.0, places=6)
        self.assertEqual(warnings, [])

    def test_kink_at_kink_point(self):
        rate, _ = _compute_borrow_rate("kink", 80.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 4.0, places=6)

    def test_kink_below_kink(self):
        # u=40: rate = 0 + 4*(40/80) = 2.0
        rate, _ = _compute_borrow_rate("kink", 40.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 2.0, places=6)

    def test_kink_above_kink(self):
        # u=90: rate = 0 + 4 + 75*((90-80)/20) = 4 + 37.5 = 41.5
        rate, _ = _compute_borrow_rate("kink", 90.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 41.5, places=6)

    def test_kink_100_utilization(self):
        # u=100: rate = 0 + 4 + 75*((100-80)/20) = 4 + 75 = 79.0
        rate, _ = _compute_borrow_rate("kink", 100.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 79.0, places=6)

    def test_kink_with_base_rate(self):
        # u=80, base=2: rate = 2 + 4*(80/80) = 6.0
        rate, _ = _compute_borrow_rate("kink", 80.0, 80.0, 2.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 6.0, places=6)

    def test_kink_50_utilization(self):
        # u=50: rate = 0 + 4*(50/80) = 2.5
        rate, _ = _compute_borrow_rate("kink", 50.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 2.5, places=6)

    def test_kink_clamps_negative_utilization(self):
        rate, _ = _compute_borrow_rate("kink", -10.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 0.0, places=6)  # utilization clamped to 0

    def test_kink_clamps_over_100_utilization(self):
        # u clamped to 100: rate = 0 + 4 + 75*1 = 79
        rate, _ = _compute_borrow_rate("kink", 110.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 79.0, places=6)

    def test_kink_zero_slope1(self):
        # u=40: rate = 0 + 0*(40/80) = 0.0
        rate, _ = _compute_borrow_rate("kink", 40.0, 80.0, 0.0, 0.0, 75.0)
        self.assertAlmostEqual(rate, 0.0, places=6)

    def test_kink_zero_slope2(self):
        # u=90: rate = 0 + 4 + 0*((90-80)/20) = 4.0
        rate, _ = _compute_borrow_rate("kink", 90.0, 80.0, 0.0, 4.0, 0.0)
        self.assertAlmostEqual(rate, 4.0, places=6)

    def test_kink_invalid_kink_point_zero_warns(self):
        # kink=0 is clamped to 0.1
        rate, warnings = _compute_borrow_rate("kink", 50.0, 0.0, 0.0, 4.0, 75.0)
        self.assertGreater(len(warnings), 0)

    def test_kink_invalid_kink_point_100_warns(self):
        rate, warnings = _compute_borrow_rate("kink", 90.0, 100.0, 0.0, 4.0, 75.0)
        self.assertGreater(len(warnings), 0)

    def test_kink_rate_never_negative(self):
        # Even with negative base rate, clamped to 0
        rate, _ = _compute_borrow_rate("kink", 0.0, 80.0, -5.0, 4.0, 75.0)
        self.assertGreaterEqual(rate, 0.0)

    def test_kink_different_kink_point(self):
        # kink=60: u=30: rate = 0 + 4*(30/60) = 2.0
        rate, _ = _compute_borrow_rate("kink", 30.0, 60.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 2.0, places=6)


# ===========================================================================
# 3. _compute_borrow_rate — LINEAR model
# ===========================================================================

class TestComputeBorrowRateLinear(unittest.TestCase):

    def test_linear_zero_utilization(self):
        rate, _ = _compute_borrow_rate("linear", 0.0, 80.0, 1.0, 10.0, 0.0)
        self.assertAlmostEqual(rate, 1.0, places=6)

    def test_linear_full_utilization(self):
        # rate = 1 + 10*(100/100) = 11.0
        rate, _ = _compute_borrow_rate("linear", 100.0, 80.0, 1.0, 10.0, 0.0)
        self.assertAlmostEqual(rate, 11.0, places=6)

    def test_linear_half_utilization(self):
        # rate = 1 + 10*(50/100) = 6.0
        rate, _ = _compute_borrow_rate("linear", 50.0, 80.0, 1.0, 10.0, 0.0)
        self.assertAlmostEqual(rate, 6.0, places=6)

    def test_linear_zero_base_rate(self):
        # rate = 0 + 8*(75/100) = 6.0
        rate, _ = _compute_borrow_rate("linear", 75.0, 80.0, 0.0, 8.0, 0.0)
        self.assertAlmostEqual(rate, 6.0, places=6)

    def test_linear_no_slope(self):
        # rate = 5 + 0*(50/100) = 5.0
        rate, _ = _compute_borrow_rate("linear", 50.0, 80.0, 5.0, 0.0, 0.0)
        self.assertAlmostEqual(rate, 5.0, places=6)

    def test_linear_ignores_slope2(self):
        # slope2 should be ignored
        rate1, _ = _compute_borrow_rate("linear", 50.0, 80.0, 0.0, 4.0, 0.0)
        rate2, _ = _compute_borrow_rate("linear", 50.0, 80.0, 0.0, 4.0, 100.0)
        self.assertAlmostEqual(rate1, rate2, places=6)

    def test_linear_kink_point_ignored(self):
        # kink_point should not affect linear model result
        rate1, _ = _compute_borrow_rate("linear", 50.0, 60.0, 0.0, 4.0, 0.0)
        rate2, _ = _compute_borrow_rate("linear", 50.0, 90.0, 0.0, 4.0, 0.0)
        self.assertAlmostEqual(rate1, rate2, places=6)

    def test_linear_no_warnings_for_valid_inputs(self):
        _, warnings = _compute_borrow_rate("linear", 50.0, 80.0, 1.0, 10.0, 0.0)
        self.assertEqual(warnings, [])


# ===========================================================================
# 4. _compute_borrow_rate — JUMP and CUSTOM models
# ===========================================================================

class TestComputeBorrowRateJumpCustom(unittest.TestCase):

    def test_jump_same_formula_as_kink(self):
        rate_kink, _ = _compute_borrow_rate("kink", 85.0, 80.0, 0.0, 4.0, 150.0)
        rate_jump, _ = _compute_borrow_rate("jump", 85.0, 80.0, 0.0, 4.0, 150.0)
        self.assertAlmostEqual(rate_kink, rate_jump, places=6)

    def test_jump_large_slope2(self):
        # u=82: rate = 0 + 4 + 150*((82-80)/20) = 4 + 15 = 19
        rate, _ = _compute_borrow_rate("jump", 82.0, 80.0, 0.0, 4.0, 150.0)
        self.assertAlmostEqual(rate, 19.0, places=6)

    def test_custom_same_formula_as_kink(self):
        rate_kink, _ = _compute_borrow_rate("kink", 50.0, 80.0, 1.0, 5.0, 60.0)
        rate_custom, _ = _compute_borrow_rate("custom", 50.0, 80.0, 1.0, 5.0, 60.0)
        self.assertAlmostEqual(rate_kink, rate_custom, places=6)

    def test_unknown_model_falls_back_to_kink_with_warning(self):
        rate_kink, _ = _compute_borrow_rate("kink", 50.0, 80.0, 0.0, 4.0, 75.0)
        rate_unknown, warnings = _compute_borrow_rate("foobar", 50.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate_kink, rate_unknown, places=6)
        self.assertGreater(len(warnings), 0)


# ===========================================================================
# 5. _compute_supply_rate
# ===========================================================================

class TestComputeSupplyRate(unittest.TestCase):

    def test_supply_zero_utilization(self):
        self.assertAlmostEqual(_compute_supply_rate(10.0, 0.0), 0.0, places=9)

    def test_supply_full_utilization(self):
        self.assertAlmostEqual(_compute_supply_rate(10.0, 100.0), 10.0, places=9)

    def test_supply_half_utilization(self):
        self.assertAlmostEqual(_compute_supply_rate(10.0, 50.0), 5.0, places=9)

    def test_supply_80_utilization(self):
        # borrow_rate=4, utilization=80: supply = 4*0.8 = 3.2
        self.assertAlmostEqual(_compute_supply_rate(4.0, 80.0), 3.2, places=9)

    def test_supply_always_leq_borrow(self):
        for u in [0, 25, 50, 75, 100]:
            s = _compute_supply_rate(10.0, float(u))
            self.assertLessEqual(s, 10.0)

    def test_supply_zero_borrow_rate(self):
        self.assertAlmostEqual(_compute_supply_rate(0.0, 80.0), 0.0, places=9)

    def test_supply_proportional_to_utilization(self):
        s1 = _compute_supply_rate(8.0, 25.0)
        s2 = _compute_supply_rate(8.0, 50.0)
        self.assertAlmostEqual(s2, 2 * s1, places=9)


# ===========================================================================
# 6. _compute_utilization_efficiency
# ===========================================================================

class TestComputeUtilizationEfficiency(unittest.TestCase):

    def test_efficiency_at_optimal(self):
        self.assertAlmostEqual(_compute_utilization_efficiency(80.0, 80.0), 100.0, places=6)

    def test_efficiency_10_below_optimal(self):
        # deviation=10 → score = 100 - 20 = 80
        self.assertAlmostEqual(_compute_utilization_efficiency(70.0, 80.0), 80.0, places=6)

    def test_efficiency_10_above_optimal(self):
        # deviation=10 → score = 80
        self.assertAlmostEqual(_compute_utilization_efficiency(90.0, 80.0), 80.0, places=6)

    def test_efficiency_50_below_clamps_to_zero(self):
        # deviation=50 → 100 - 100 = 0
        self.assertAlmostEqual(_compute_utilization_efficiency(30.0, 80.0), 0.0, places=6)

    def test_efficiency_1_deviation(self):
        # deviation=1 → 100 - 2 = 98
        self.assertAlmostEqual(_compute_utilization_efficiency(79.0, 80.0), 98.0, places=6)

    def test_efficiency_clamps_to_zero_large_deviation(self):
        score = _compute_utilization_efficiency(0.0, 80.0)
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_efficiency_never_negative(self):
        score = _compute_utilization_efficiency(0.0, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_efficiency_never_exceeds_100(self):
        score = _compute_utilization_efficiency(80.0, 80.0)
        self.assertLessEqual(score, 100.0)

    def test_efficiency_symmetric(self):
        below = _compute_utilization_efficiency(70.0, 80.0)
        above = _compute_utilization_efficiency(90.0, 80.0)
        self.assertAlmostEqual(below, above, places=6)


# ===========================================================================
# 7. _compute_rate_volatility_risk
# ===========================================================================

class TestComputeRateVolatilityRisk(unittest.TestCase):

    def test_volatility_low_far_below_kink(self):
        # u=30 < 80*0.75=60 → LOW
        self.assertEqual(_compute_rate_volatility_risk(30.0, 80.0), "LOW")

    def test_volatility_medium_approaching_kink(self):
        # u=65 in [60, 84) → MEDIUM
        self.assertEqual(_compute_rate_volatility_risk(65.0, 80.0), "MEDIUM")

    def test_volatility_high_above_kink(self):
        # u=85 >= 80*1.05=84 → HIGH
        self.assertEqual(_compute_rate_volatility_risk(85.0, 80.0), "HIGH")

    def test_volatility_high_well_above_kink(self):
        self.assertEqual(_compute_rate_volatility_risk(95.0, 80.0), "HIGH")

    def test_volatility_at_kink_is_medium_or_high(self):
        risk = _compute_rate_volatility_risk(80.0, 80.0)
        self.assertIn(risk, ("MEDIUM", "HIGH"))

    def test_volatility_zero_utilization(self):
        self.assertEqual(_compute_rate_volatility_risk(0.0, 80.0), "LOW")


# ===========================================================================
# 8. _compute_label
# ===========================================================================

class TestComputeLabel(unittest.TestCase):

    def test_label_crisis_high_borrow_rate(self):
        # borrow_rate=30 >= CRISIS_BORROW_RATE_THRESHOLD
        self.assertEqual(_compute_label(50.0, 30.0, 80.0, 80.0), "CRISIS_RATES")

    def test_label_crisis_high_utilization(self):
        # utilization=96 >= CRISIS_UTILIZATION_THRESHOLD
        self.assertEqual(_compute_label(96.0, 10.0, 80.0, 80.0), "CRISIS_RATES")

    def test_label_crisis_at_threshold(self):
        self.assertEqual(_compute_label(95.0, 25.0, 80.0, 80.0), "CRISIS_RATES")

    def test_label_optimal_utilization(self):
        # util=80, optimal=80, borrow_rate=4 → OPTIMAL_UTILIZATION
        self.assertEqual(_compute_label(80.0, 4.0, 80.0, 80.0), "OPTIMAL_UTILIZATION")

    def test_label_optimal_band_left(self):
        # util=77.5 within 3% of optimal=80 → OPTIMAL_UTILIZATION
        self.assertEqual(_compute_label(77.5, 3.0, 80.0, 80.0), "OPTIMAL_UTILIZATION")

    def test_label_optimal_band_right(self):
        # util=82.5 within 3% of optimal=80 → OPTIMAL_UTILIZATION
        self.assertEqual(_compute_label(82.5, 3.0, 80.0, 80.0), "OPTIMAL_UTILIZATION")

    def test_label_above_kink(self):
        # util=85 >= kink=80, not optimal → ABOVE_KINK
        self.assertEqual(_compute_label(85.0, 5.0, 80.0, 70.0), "ABOVE_KINK")

    def test_label_approaching_kink(self):
        # util=70 >= 80*0.85=68, < 80 → APPROACHING_KINK
        self.assertEqual(_compute_label(70.0, 3.5, 80.0, 60.0), "APPROACHING_KINK")

    def test_label_healthy_zone(self):
        # util=20 < 80*0.85=68 → HEALTHY_ZONE
        self.assertEqual(_compute_label(20.0, 1.0, 80.0, 80.0), "HEALTHY_ZONE")

    def test_label_crisis_trumps_optimal(self):
        # util=80=optimal but borrow_rate=26 → CRISIS_RATES
        self.assertEqual(_compute_label(80.0, 26.0, 80.0, 80.0), "CRISIS_RATES")

    def test_label_just_below_kink_is_approaching(self):
        # util=79, kink=80 → 79 >= 80*0.85=68, < 80 → APPROACHING_KINK
        self.assertEqual(_compute_label(79.0, 3.0, 80.0, 60.0), "APPROACHING_KINK")

    def test_label_exactly_at_kink(self):
        # util=80=kink, optimal=70 → ABOVE_KINK (util >= kink, not in optimal zone)
        self.assertEqual(_compute_label(80.0, 4.0, 80.0, 70.0), "ABOVE_KINK")


# ===========================================================================
# 9. DeFiProtocolInterestRateModelAnalyzer.analyze() — structure
# ===========================================================================

class TestAnalyzerStructure(unittest.TestCase):

    def _make_default(self, **kwargs):
        params = dict(
            model_type="kink",
            utilization_rate_pct=50.0,
            kink_point_pct=80.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        )
        params.update(kwargs)
        return DeFiProtocolInterestRateModelAnalyzer(**params).analyze()

    def test_result_has_all_keys(self):
        result = self._make_default()
        for key in [
            "model_type", "utilization_rate_pct", "borrow_rate_pct",
            "supply_rate_pct", "spread_pct", "utilization_efficiency_score",
            "rate_volatility_risk", "label", "warnings",
        ]:
            self.assertIn(key, result)

    def test_result_schema_version(self):
        result = self._make_default()
        self.assertEqual(result["schema_version"], 1)

    def test_result_mp_tag(self):
        result = self._make_default()
        self.assertEqual(result["mp_tag"], "MP-1034")

    def test_result_source(self):
        result = self._make_default()
        self.assertIn("defi_protocol_interest_rate_model_analyzer", result["source"])

    def test_borrow_gt_supply(self):
        result = self._make_default(utilization_rate_pct=50.0)
        self.assertGreater(result["borrow_rate_pct"], result["supply_rate_pct"])

    def test_spread_is_borrow_minus_supply(self):
        result = self._make_default(utilization_rate_pct=50.0)
        self.assertAlmostEqual(
            result["spread_pct"],
            result["borrow_rate_pct"] - result["supply_rate_pct"],
            places=5,
        )

    def test_efficiency_score_in_range(self):
        result = self._make_default()
        self.assertGreaterEqual(result["utilization_efficiency_score"], 0.0)
        self.assertLessEqual(result["utilization_efficiency_score"], 100.0)

    def test_volatility_risk_valid_value(self):
        result = self._make_default()
        self.assertIn(result["rate_volatility_risk"], {"LOW", "MEDIUM", "HIGH"})

    def test_label_valid_value(self):
        result = self._make_default()
        valid = {"OPTIMAL_UTILIZATION", "HEALTHY_ZONE", "APPROACHING_KINK", "ABOVE_KINK", "CRISIS_RATES"}
        self.assertIn(result["label"], valid)

    def test_warnings_is_list(self):
        result = self._make_default()
        self.assertIsInstance(result["warnings"], list)

    def test_no_warnings_for_valid_inputs(self):
        result = self._make_default()
        self.assertEqual(len(result["warnings"]), 0)


# ===========================================================================
# 10. Analyzer — specific value checks
# ===========================================================================

class TestAnalyzerValues(unittest.TestCase):

    def test_kink_50pct_borrow_rate(self):
        # kink=80, slope1=4, u=50: rate = 4*(50/80) = 2.5
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=50.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertAlmostEqual(result["borrow_rate_pct"], 2.5, places=4)

    def test_kink_90pct_borrow_rate(self):
        # u=90: rate = 4 + 75*((90-80)/20) = 4+37.5 = 41.5
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=90.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertAlmostEqual(result["borrow_rate_pct"], 41.5, places=4)

    def test_linear_50pct_borrow_rate(self):
        # linear, u=50, base=1, slope1=10: rate = 1 + 10*(50/100) = 6.0
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="linear", utilization_rate_pct=50.0,
            kink_point_pct=80.0, base_rate_pct=1.0,
            slope1_pct=10.0, slope2_pct=0.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertAlmostEqual(result["borrow_rate_pct"], 6.0, places=4)

    def test_crisis_label_at_95_utilization(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=95.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertEqual(result["label"], "CRISIS_RATES")

    def test_optimal_label_at_optimal_utilization(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=80.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=1.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertEqual(result["label"], "OPTIMAL_UTILIZATION")

    def test_healthy_zone_label_low_utilization(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=10.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertEqual(result["label"], "HEALTHY_ZONE")

    def test_efficiency_score_100_at_optimal(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=80.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertAlmostEqual(result["utilization_efficiency_score"], 100.0, places=4)

    def test_supply_rate_zero_at_zero_utilization(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=0.0,
            kink_point_pct=80.0, base_rate_pct=2.0,
            slope1_pct=4.0, slope2_pct=75.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertAlmostEqual(result["supply_rate_pct"], 0.0, places=6)

    def test_model_type_preserved_in_result(self):
        for mt in ("kink", "linear", "jump", "custom"):
            result = DeFiProtocolInterestRateModelAnalyzer(
                model_type=mt, utilization_rate_pct=50.0,
            ).analyze()
            self.assertEqual(result["model_type"], mt)

    def test_above_kink_label(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=85.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=1.0,
            optimal_utilization_pct=50.0,
        ).analyze()
        self.assertEqual(result["label"], "ABOVE_KINK")


# ===========================================================================
# 11. analyze_rate_model convenience wrapper
# ===========================================================================

class TestAnalyzeRateModelWrapper(unittest.TestCase):

    def test_returns_dict(self):
        result = analyze_rate_model()
        self.assertIsInstance(result, dict)

    def test_default_label_not_crisis(self):
        result = analyze_rate_model(utilization_rate_pct=50.0)
        self.assertNotEqual(result["label"], "CRISIS_RATES")

    def test_matches_class_output(self):
        class_result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=60.0,
        ).analyze()
        fn_result = analyze_rate_model(
            model_type="kink", utilization_rate_pct=60.0,
        )
        self.assertAlmostEqual(
            class_result["borrow_rate_pct"], fn_result["borrow_rate_pct"], places=4
        )

    def test_all_model_types_run(self):
        for mt in VALID_MODEL_TYPES:
            result = analyze_rate_model(model_type=mt)
            self.assertIn("label", result)


# ===========================================================================
# 12. Ring-buffer and persistence
# ===========================================================================

class TestRingBufferAndPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def test_write_log_creates_file(self):
        result = analyze_rate_model()
        log_path = write_log(result, self.data_dir)
        self.assertTrue(log_path.exists())

    def test_write_log_is_valid_json_list(self):
        result = analyze_rate_model()
        log_path = write_log(result, self.data_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_write_log_appends(self):
        for _ in range(3):
            write_log(analyze_rate_model(), self.data_dir)
        log_path = self.data_dir / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap(self):
        for _ in range(RING_BUFFER_CAP + 5):
            write_log(analyze_rate_model(), self.data_dir)
        log_path = self.data_dir / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_atomic_write_produces_valid_json(self):
        path = self.data_dir / "test.json"
        _atomic_write(path, [{"x": 1}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["x"], 1)

    def test_load_json_list_missing_file_returns_empty(self):
        result = _load_json_list(self.data_dir / "nonexistent.json")
        self.assertEqual(result, [])

    def test_load_json_list_invalid_json_returns_empty(self):
        bad = self.data_dir / "bad.json"
        bad.write_text("NOT JSON")
        result = _load_json_list(bad)
        self.assertEqual(result, [])

    def test_log_filename_constant(self):
        self.assertEqual(LOG_FILENAME, "interest_rate_model_log.json")

    def test_ring_buffer_cap_constant(self):
        self.assertEqual(RING_BUFFER_CAP, 100)


# ===========================================================================
# 13. Constants and module-level checks
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_crisis_borrow_rate_threshold(self):
        self.assertEqual(CRISIS_BORROW_RATE_THRESHOLD, 25.0)

    def test_crisis_utilization_threshold(self):
        self.assertEqual(CRISIS_UTILIZATION_THRESHOLD, 95.0)

    def test_optimal_band_pct(self):
        self.assertEqual(OPTIMAL_BAND_PCT, 3.0)

    def test_valid_model_types_contains_kink(self):
        self.assertIn("kink", VALID_MODEL_TYPES)

    def test_valid_model_types_contains_linear(self):
        self.assertIn("linear", VALID_MODEL_TYPES)

    def test_valid_model_types_contains_jump(self):
        self.assertIn("jump", VALID_MODEL_TYPES)

    def test_valid_model_types_contains_custom(self):
        self.assertIn("custom", VALID_MODEL_TYPES)


# ===========================================================================
# 14. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_100_utilization_does_not_crash(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            utilization_rate_pct=100.0
        ).analyze()
        self.assertIn("label", result)

    def test_0_utilization_does_not_crash(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            utilization_rate_pct=0.0
        ).analyze()
        self.assertIn("label", result)

    def test_negative_utilization_clamped(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            utilization_rate_pct=-5.0
        ).analyze()
        self.assertAlmostEqual(result["utilization_rate_pct"], 0.0, places=4)

    def test_over_100_utilization_clamped(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            utilization_rate_pct=150.0
        ).analyze()
        self.assertAlmostEqual(result["utilization_rate_pct"], 100.0, places=4)

    def test_zero_slopes_no_crash(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            slope1_pct=0.0, slope2_pct=0.0
        ).analyze()
        self.assertGreaterEqual(result["borrow_rate_pct"], 0.0)

    def test_extreme_slope2_causes_crisis(self):
        result = DeFiProtocolInterestRateModelAnalyzer(
            model_type="kink", utilization_rate_pct=90.0,
            kink_point_pct=80.0, base_rate_pct=0.0,
            slope1_pct=4.0, slope2_pct=500.0,
            optimal_utilization_pct=80.0,
        ).analyze()
        self.assertEqual(result["label"], "CRISIS_RATES")

    def test_result_is_json_serializable(self):
        result = DeFiProtocolInterestRateModelAnalyzer().analyze()
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)

    def test_timestamp_present(self):
        result = DeFiProtocolInterestRateModelAnalyzer().analyze()
        self.assertIn("timestamp_utc", result)
        self.assertIsNotNone(result["timestamp_utc"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
