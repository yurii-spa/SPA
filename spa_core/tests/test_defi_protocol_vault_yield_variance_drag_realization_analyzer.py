"""
Tests for MP-1197: DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_yield_variance_drag_realization_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_yield_variance_drag_realization_analyzer import (  # noqa: E501
    DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _pstdev,
    _safe_div,
    _geometric_mean_pct,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    DEFAULT_PERIODS_PER_YEAR,
    NEGLIGIBLE_DRAG_FRAC,
    MINOR_DRAG_FRAC,
    MODERATE_DRAG_FRAC,
    HIGH_CV,
    HEADLINE_OPTIMISTIC_RATIO,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_apr_pct=40.0,
    period_yield_samples=None,
    periods_per_year=None,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
    }
    if period_yield_samples is not None:
        pos["period_yield_samples"] = period_yield_samples
    else:
        pos["period_yield_samples"] = [3.0, 3.0, 3.0, 3.0]
    if periods_per_year is not None:
        pos["periods_per_year"] = periods_per_year
    return pos


def A():
    return DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid_str(self):
        self.assertEqual(_f("3.5"), 3.5)

    def test_f_valid_int(self):
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_none_custom_default(self):
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_str(self):
        self.assertEqual(_f("abc"), 0.0)

    def test_f_bad_list_default(self):
        self.assertEqual(_f([], 1.0), 1.0)

    def test_f_negative(self):
        self.assertEqual(_f("-5"), -5.0)

    def test_f_int_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_f_dict_default(self):
        self.assertEqual(_f({}, 2.0), 2.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

    def test_f_negative_float(self):
        self.assertEqual(_f(-3.7), -3.7)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_low(self):
        self.assertEqual(_clamp(0, 0, 10), 0)

    def test_clamp_exact_high(self):
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_clamp_unit_high(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)

    def test_clamp_unit_low(self):
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

    def test_pstdev_empty(self):
        self.assertEqual(_pstdev([]), 0.0)

    def test_pstdev_constant(self):
        self.assertEqual(_pstdev([5.0, 5.0, 5.0]), 0.0)

    def test_pstdev_single(self):
        self.assertEqual(_pstdev([9.0]), 0.0)

    def test_pstdev_known(self):
        # population stdev of [2,4,4,4,5,5,7,9] is 2.0
        self.assertAlmostEqual(_pstdev([2, 4, 4, 4, 5, 5, 7, 9]), 2.0)

    def test_pstdev_positive(self):
        self.assertGreater(_pstdev([1.0, 5.0]), 0.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 4.0, None), 2.5)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(1.0, 0.0, None))

    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(1.0, -2.0, None))

    def test_safe_div_sentinel_zero(self):
        self.assertEqual(_safe_div(1.0, 0.0, 0.0), 0.0)

    def test_build_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_build_cfg_override_path(self):
        cfg = _build_default_cfg({"log_path": "/x/y.json"})
        self.assertEqual(cfg["log_path"], "/x/y.json")

    def test_build_cfg_no_mutate(self):
        _build_default_cfg({"extra": 1})
        cfg2 = _build_default_cfg()
        self.assertNotIn("extra", cfg2)

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(75), "B")

    def test_grade_c(self):
        self.assertEqual(_grade_from_score(60), "C")

    def test_grade_d(self):
        self.assertEqual(_grade_from_score(45), "D")

    def test_grade_f(self):
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundary_85(self):
        self.assertEqual(_grade_from_score(85), "A")

    def test_grade_boundary_70(self):
        self.assertEqual(_grade_from_score(70), "B")

    def test_grade_boundary_55(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_boundary_40(self):
        self.assertEqual(_grade_from_score(40), "D")


# ── geometric-mean helper tests ────────────────────────────────────────────────

class TestGeometricMean(unittest.TestCase):
    def test_constant_equals_value(self):
        g, w = _geometric_mean_pct([5.0, 5.0, 5.0])
        self.assertFalse(w)
        self.assertAlmostEqual(g, 5.0, places=6)

    def test_constant_zero(self):
        g, w = _geometric_mean_pct([0.0, 0.0])
        self.assertFalse(w)
        self.assertAlmostEqual(g, 0.0, places=9)

    def test_geom_below_arithmetic_when_volatile(self):
        samples = [40.0, -20.0, 45.0, -25.0]
        g, w = _geometric_mean_pct(samples)
        self.assertFalse(w)
        self.assertLess(g, _mean(samples))

    def test_geom_equals_arith_when_constant(self):
        samples = [3.0, 3.0, 3.0]
        g, w = _geometric_mean_pct(samples)
        self.assertAlmostEqual(g, _mean(samples), places=6)

    def test_wipeout_exact_minus_100(self):
        g, w = _geometric_mean_pct([10.0, -100.0])
        self.assertTrue(w)
        self.assertIsNone(g)

    def test_wipeout_below_minus_100(self):
        g, w = _geometric_mean_pct([10.0, -150.0])
        self.assertTrue(w)
        self.assertIsNone(g)

    def test_no_wipeout_at_minus_99(self):
        g, w = _geometric_mean_pct([-99.0, 10.0])
        self.assertFalse(w)
        self.assertIsNotNone(g)

    def test_known_two_point(self):
        # growths 2.0 and 0.5 → geometric growth 1.0 → 0%
        g, w = _geometric_mean_pct([100.0, -50.0])
        self.assertFalse(w)
        self.assertAlmostEqual(g, 0.0, places=6)

    def test_all_positive_geom_positive(self):
        g, w = _geometric_mean_pct([10.0, 20.0, 30.0])
        self.assertFalse(w)
        self.assertGreater(g, 0.0)

    def test_finite_result(self):
        g, w = _geometric_mean_pct([5.0, 7.0, 3.0])
        self.assertTrue(math.isfinite(g))


# ── classification tests ────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_constant_negligible(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0, 3.0]))
        self.assertEqual(r["classification"], "NEGLIGIBLE_DRAG")

    def test_zero_drag_fraction_on_constant(self):
        r = A().analyze(make_pos(period_yield_samples=[2.0, 2.0, 2.0]))
        self.assertAlmostEqual(r["drag_fraction"], 0.0, places=6)

    def test_moderate_drag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=40.0, periods_per_year=12,
            period_yield_samples=[12.0, -6.0, 10.0, -4.0, 11.0, -3.0]))
        self.assertEqual(r["classification"], "MODERATE_DRAG")

    def test_severe_drag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=120.0, periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0, -30.0]))
        self.assertEqual(r["classification"], "SEVERE_DRAG")

    def test_wipeout_is_severe(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertEqual(r["classification"], "SEVERE_DRAG")

    def test_minor_drag(self):
        # small spread producing drag fraction between 0.02 and 0.08
        r = A().analyze(make_pos(
            headline_apr_pct=36.0, periods_per_year=12,
            period_yield_samples=[8.0, -2.0, 7.0, -1.0, 6.0, 0.0]))
        self.assertIn(r["classification"], ("MINOR_DRAG", "MODERATE_DRAG"))

    def test_insufficient_no_samples(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_one_sample(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_zero_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_min_samples_constant(self):
        self.assertEqual(MIN_SAMPLES, 2)

    def test_exactly_min_samples_ok(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0]))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negligible_at_threshold(self):
        # constant → drag fraction 0 ≤ threshold
        r = A().analyze(make_pos(period_yield_samples=[5.0, 5.0, 5.0]))
        self.assertEqual(r["classification"], "NEGLIGIBLE_DRAG")

    def test_classification_in_valid_set(self):
        valid = {"NEGLIGIBLE_DRAG", "MINOR_DRAG", "MODERATE_DRAG",
                 "SEVERE_DRAG", "INSUFFICIENT_DATA"}
        for samples in ([3, 3, 3], [12, -6, 10, -4], [40, -20, 45, -25],
                        [30, 30, -100, 30], [1]):
            r = A().analyze(make_pos(period_yield_samples=samples))
            self.assertIn(r["classification"], valid)


# ── metric / math tests ─────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_arithmetic_apr_linear(self):
        r = A().analyze(make_pos(
            periods_per_year=12, period_yield_samples=[2.0, 4.0]))
        self.assertAlmostEqual(r["arithmetic_apr_pct"], 3.0 * 12)

    def test_geom_le_arith(self):
        r = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[20.0, -10.0, 25.0, -15.0]))
        self.assertLessEqual(r["geometric_apr_pct"], r["arithmetic_apr_pct"])

    def test_variance_drag_nonneg_when_arith_positive(self):
        r = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[20.0, -10.0, 25.0, -15.0]))
        self.assertGreaterEqual(r["variance_drag_pct"], 0.0)

    def test_variance_drag_zero_on_constant(self):
        r = A().analyze(make_pos(period_yield_samples=[4.0, 4.0, 4.0]))
        self.assertAlmostEqual(r["variance_drag_pct"], 0.0, places=6)

    def test_drag_fraction_clamped_unit(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertLessEqual(r["drag_fraction"], 1.0)
        self.assertGreaterEqual(r["drag_fraction"], 0.0)

    def test_realization_ratio_unit_on_constant(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=6)

    def test_realization_ratio_below_one_volatile(self):
        r = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0]))
        self.assertLess(r["realization_ratio"], 1.0)

    def test_geometric_total_loss_on_wipeout(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertEqual(r["geometric_apr_pct"], -100.0)

    def test_wipeout_flag_set(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertTrue(r["capital_wipeout_period"])

    def test_period_mean_value(self):
        r = A().analyze(make_pos(period_yield_samples=[2.0, 4.0, 6.0]))
        self.assertAlmostEqual(r["period_mean_pct"], 4.0)

    def test_period_volatility_zero_on_constant(self):
        r = A().analyze(make_pos(period_yield_samples=[5.0, 5.0]))
        self.assertAlmostEqual(r["period_volatility_pct"], 0.0)

    def test_period_volatility_positive(self):
        r = A().analyze(make_pos(period_yield_samples=[2.0, 8.0]))
        self.assertGreater(r["period_volatility_pct"], 0.0)

    def test_cv_zero_on_constant(self):
        r = A().analyze(make_pos(period_yield_samples=[5.0, 5.0, 5.0]))
        self.assertAlmostEqual(r["coefficient_of_variation"], 0.0, places=9)

    def test_cv_none_when_mean_zero(self):
        # symmetric samples mean to 0 → CV undefined
        r = A().analyze(make_pos(period_yield_samples=[5.0, -5.0]))
        self.assertIsNone(r["coefficient_of_variation"])

    def test_headline_vs_arith_gap(self):
        r = A().analyze(make_pos(
            headline_apr_pct=50.0, periods_per_year=12,
            period_yield_samples=[2.0, 2.0]))
        self.assertAlmostEqual(r["headline_vs_arith_gap_pct"], 50.0 - 24.0)

    def test_periods_per_year_default(self):
        r = A().analyze(make_pos(period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_periods_per_year_custom(self):
        r = A().analyze(make_pos(
            periods_per_year=52, period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], 52.0)

    def test_periods_per_year_invalid_falls_back(self):
        r = A().analyze(make_pos(
            periods_per_year=0, period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_periods_per_year_negative_falls_back(self):
        r = A().analyze(make_pos(
            periods_per_year=-5, period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_sample_count(self):
        r = A().analyze(make_pos(period_yield_samples=[1.0, 2.0, 3.0, 4.0]))
        self.assertEqual(r["sample_count"], 4)

    def test_drag_fraction_scale_free_in_ppy(self):
        s = [12.0, -6.0, 10.0, -4.0, 11.0, -3.0]
        r1 = A().analyze(make_pos(periods_per_year=12, period_yield_samples=s))
        r2 = A().analyze(make_pos(periods_per_year=52, period_yield_samples=s))
        self.assertAlmostEqual(r1["drag_fraction"], r2["drag_fraction"],
                               places=6)


# ── flag tests ──────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_smooth_yield_flag(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertIn("SMOOTH_YIELD", r["flags"])

    def test_high_volatility_flag(self):
        r = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0]))
        self.assertIn("HIGH_VOLATILITY", r["flags"])

    def test_wipeout_flag(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertIn("CAPITAL_WIPEOUT_PERIOD", r["flags"])

    def test_headline_above_arithmetic_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=120.0, periods_per_year=12,
            period_yield_samples=[2.0, 2.0]))
        self.assertIn("HEADLINE_ABOVE_ARITHMETIC", r["flags"])

    def test_no_headline_above_when_matched(self):
        r = A().analyze(make_pos(
            headline_apr_pct=24.0, periods_per_year=12,
            period_yield_samples=[2.0, 2.0]))
        self.assertNotIn("HEADLINE_ABOVE_ARITHMETIC", r["flags"])

    def test_severe_flag_present(self):
        r = A().analyze(make_pos(
            headline_apr_pct=120.0, periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0, -30.0]))
        self.assertIn("SEVERE_DRAG", r["flags"])

    def test_negligible_flag_present(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertIn("NEGLIGIBLE_DRAG", r["flags"])

    def test_moderate_flag_present(self):
        r = A().analyze(make_pos(
            headline_apr_pct=40.0, periods_per_year=12,
            period_yield_samples=[12.0, -6.0, 10.0, -4.0, 11.0, -3.0]))
        self.assertIn("MODERATE_DRAG", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_flags_is_list(self):
        r = A().analyze(make_pos())
        self.assertIsInstance(r["flags"], list)

    def test_smooth_not_on_volatile(self):
        r = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0, -30.0]))
        self.assertNotIn("SMOOTH_YIELD", r["flags"])


# ── scoring tests ────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_range(self):
        for samples in ([3, 3, 3], [12, -6, 10, -4], [40, -20, 45, -25],
                        [30, 30, -100, 30]):
            r = A().analyze(make_pos(period_yield_samples=samples))
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_smooth_high_score(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertGreater(r["score"], 90.0)

    def test_wipeout_zero_score(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertEqual(r["score"], 0.0)

    def test_severe_lower_than_negligible(self):
        smooth = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        severe = A().analyze(make_pos(
            headline_apr_pct=120.0, periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0, -30.0]))
        self.assertLess(severe["score"], smooth["score"])

    def test_insufficient_zero_score(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)

    def test_grade_matches_score_a(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertEqual(r["grade"], "A")

    def test_monotone_in_volatility(self):
        low = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[6.0, 4.0, 6.0, 4.0]))
        high = A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[20.0, -10.0, 20.0, -10.0]))
        self.assertGreater(low["score"], high["score"])


# ── recommendation tests ─────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_negligible_trust(self):
        r = A().analyze(make_pos(period_yield_samples=[3.0, 3.0, 3.0]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_severe_avoid(self):
        r = A().analyze(make_pos(
            headline_apr_pct=120.0, periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0, -30.0]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_moderate_discount(self):
        r = A().analyze(make_pos(
            headline_apr_pct=40.0, periods_per_year=12,
            period_yield_samples=[12.0, -6.0, 10.0, -4.0, 11.0, -3.0]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_insufficient_avoid(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_recommendation_nonempty(self):
        r = A().analyze(make_pos())
        self.assertTrue(r["recommendation"])


# ── input-robustness tests ───────────────────────────────────────────────────────

class TestInputRobustness(unittest.TestCase):
    def test_non_numeric_samples_filtered(self):
        r = A().analyze(make_pos(
            period_yield_samples=[3.0, "x", None, 3.0, 3.0]))
        self.assertEqual(r["sample_count"], 3)

    def test_nan_sample_filtered(self):
        r = A().analyze(make_pos(
            period_yield_samples=[3.0, float("nan"), 3.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_inf_sample_filtered(self):
        r = A().analyze(make_pos(
            period_yield_samples=[3.0, float("inf"), 3.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_neg_inf_sample_filtered(self):
        r = A().analyze(make_pos(
            period_yield_samples=[3.0, float("-inf"), 3.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_all_invalid_insufficient(self):
        r = A().analyze(make_pos(
            period_yield_samples=["a", None, float("nan")]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_string_numeric_samples_ok(self):
        r = A().analyze(make_pos(period_yield_samples=["3.0", "3.0", "3.0"]))
        self.assertEqual(r["sample_count"], 3)

    def test_nan_headline_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=float("inf")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_token_key_fallback(self):
        r = A().analyze({"token": "TKN", "headline_apr_pct": 10.0,
                         "period_yield_samples": [3.0, 3.0]})
        self.assertEqual(r["token"], "TKN")

    def test_unknown_token(self):
        r = A().analyze({"headline_apr_pct": 10.0,
                         "period_yield_samples": [3.0, 3.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_empty_samples_list(self):
        r = A().analyze(make_pos(period_yield_samples=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_samples_key(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_string_ppy_coerced(self):
        r = A().analyze(make_pos(
            periods_per_year="12", period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], 12.0)

    def test_bad_ppy_falls_back(self):
        r = A().analyze(make_pos(
            periods_per_year="abc", period_yield_samples=[2.0, 2.0]))
        self.assertEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)


# ── finiteness tests ─────────────────────────────────────────────────────────────

class TestFiniteness(unittest.TestCase):
    def test_finite_smooth(self):
        finite_check(self, A().analyze(make_pos(
            period_yield_samples=[3.0, 3.0, 3.0])))

    def test_finite_volatile(self):
        finite_check(self, A().analyze(make_pos(
            periods_per_year=12,
            period_yield_samples=[40.0, -20.0, 45.0, -25.0])))

    def test_finite_wipeout(self):
        finite_check(self, A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0])))

    def test_finite_insufficient(self):
        finite_check(self, A().analyze(make_pos(headline_apr_pct=0.0)))

    def test_finite_large_values(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=1e6, periods_per_year=365,
            period_yield_samples=[1e3, -5e2, 1e3])))

    def test_no_inf_nan_in_json(self):
        r = A().analyze(make_pos(
            period_yield_samples=[1e6, -1e5, 1e6]))
        raw = json.dumps(r)
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)

    def test_realization_ratio_finite_or_none(self):
        r = A().analyze(make_pos(
            period_yield_samples=[40.0, -20.0, 45.0, -25.0]))
        rr = r["realization_ratio"]
        self.assertTrue(rr is None or math.isfinite(rr))


# ── result-shape tests ───────────────────────────────────────────────────────────

class TestResultShape(unittest.TestCase):
    EXPECTED = {
        "token", "headline_apr_pct", "arithmetic_apr_pct",
        "geometric_apr_pct", "variance_drag_pct", "drag_fraction",
        "realization_ratio", "headline_vs_arith_gap_pct", "period_mean_pct",
        "period_volatility_pct", "coefficient_of_variation", "periods_per_year",
        "sample_count", "capital_wipeout_period", "high_volatility",
        "headline_above_arithmetic", "smooth_yield", "score", "classification",
        "recommendation", "grade", "flags",
    }

    def test_keys_present_normal(self):
        r = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), self.EXPECTED)

    def test_keys_present_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(set(r.keys()), self.EXPECTED)

    def test_keys_present_wipeout(self):
        r = A().analyze(make_pos(
            period_yield_samples=[30.0, 30.0, -100.0, 30.0]))
        self.assertEqual(set(r.keys()), self.EXPECTED)

    def test_token_is_str(self):
        self.assertIsInstance(A().analyze(make_pos())["token"], str)

    def test_flags_list_type(self):
        self.assertIsInstance(A().analyze(make_pos())["flags"], list)

    def test_sample_count_int(self):
        self.assertIsInstance(A().analyze(make_pos())["sample_count"], int)

    def test_booleans_are_bool(self):
        r = A().analyze(make_pos())
        for k in ("capital_wipeout_period", "high_volatility",
                  "headline_above_arithmetic", "smooth_yield"):
            self.assertIsInstance(r[k], bool)


# ── portfolio tests ──────────────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="A", period_yield_samples=[3.0, 3.0, 3.0]),
            make_pos(vault="B", headline_apr_pct=120.0, periods_per_year=12,
                     period_yield_samples=[40.0, -20.0, 45.0, -25.0]),
            make_pos(vault="C", headline_apr_pct=0.0),
        ])

    def test_positions_count(self):
        self.assertEqual(len(self.res["positions"]), 3)

    def test_aggregate_present(self):
        self.assertIn("aggregate", self.res)

    def test_most_honest_is_smooth(self):
        self.assertEqual(self.res["aggregate"]["most_honest_vault"], "A")

    def test_least_honest_is_volatile(self):
        self.assertEqual(self.res["aggregate"]["least_honest_vault"], "B")

    def test_position_count_field(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_avg_score_excludes_insufficient(self):
        scored = [p["score"] for p in self.res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(
            self.res["aggregate"]["avg_score"],
            round(sum(scored) / len(scored), 2))

    def test_severe_count(self):
        agg = A().analyze_portfolio([
            make_pos(vault="X", headline_apr_pct=120.0, periods_per_year=12,
                     period_yield_samples=[40.0, -20.0, 45.0, -25.0, 50.0,
                                           -30.0]),
            make_pos(vault="Y", period_yield_samples=[30.0, 30.0, -100.0]),
        ])["aggregate"]
        self.assertEqual(agg["severe_count"], 2)

    def test_all_insufficient_aggregate(self):
        agg = A().analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=0.0),
            make_pos(vault="B", headline_apr_pct=-1.0),
        ])["aggregate"]
        self.assertIsNone(agg["most_honest_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    def test_empty_portfolio(self):
        agg = A().analyze_portfolio([])["aggregate"]
        self.assertEqual(agg["position_count"], 0)
        self.assertIsNone(agg["least_honest_vault"])

    def test_portfolio_all_finite(self):
        for p in self.res["positions"]:
            finite_check(self, p)

    def test_single_position_portfolio(self):
        res = A().analyze_portfolio([make_pos(vault="solo")])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "solo")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "solo")


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_cap_3(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio([make_pos()], cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_100_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": LOG_CAP}
            for _ in range(105):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_corrupt_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_non_list_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                json.dump({"not": "a list"}, fh)
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(), make_pos(vault="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="big", headline_apr_pct=1e9,
                         period_yield_samples=[1e6, -1e5]),
                make_pos(vault="ins", headline_apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0))
        raw = json.dumps(res)
        self.assertIn("null", raw)
        json.loads(raw)

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "score", "recommendation",
                      "flags"):
                self.assertIn(k, snap)

    def test_log_aggregate_present(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("aggregate", data[0])
            self.assertIn("ts", data[0])


# ── demo / CLI ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_portfolio_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        json.dumps(res)

    def test_demo_has_negligible(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NEGLIGIBLE_DRAG", classes)

    def test_demo_has_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("SEVERE_DRAG", classes)

    def test_demo_has_moderate(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("MODERATE_DRAG", classes)

    def test_demo_has_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_smooth_negligible(self):
        res = A().analyze_portfolio(_demo_positions())
        by = {p["token"]: p for p in res["positions"]}
        self.assertEqual(by["USDC-Lend-Smooth"]["classification"],
                         "NEGLIGIBLE_DRAG")

    def test_demo_volatile_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        by = {p["token"]: p for p in res["positions"]}
        self.assertEqual(by["DEGEN-Options-Volatile"]["classification"],
                         "SEVERE_DRAG")

    def test_demo_wipeout_flagged(self):
        res = A().analyze_portfolio(_demo_positions())
        by = {p["token"]: p for p in res["positions"]}
        self.assertTrue(by["RUG-Risk-Vault"]["capital_wipeout_period"])


# ── constants ────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_threshold_ordering(self):
        self.assertLess(NEGLIGIBLE_DRAG_FRAC, MINOR_DRAG_FRAC)
        self.assertLess(MINOR_DRAG_FRAC, MODERATE_DRAG_FRAC)

    def test_high_cv_positive(self):
        self.assertGreater(HIGH_CV, 0.0)

    def test_headline_ratio_above_one(self):
        self.assertGreater(HEADLINE_OPTIMISTIC_RATIO, 1.0)

    def test_default_ppy(self):
        self.assertEqual(DEFAULT_PERIODS_PER_YEAR, 365.0)

    def test_log_cap_positive(self):
        self.assertGreater(LOG_CAP, 0)


if __name__ == "__main__":
    unittest.main()
