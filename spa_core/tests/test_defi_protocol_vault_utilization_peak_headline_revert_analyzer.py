"""
Tests for MP-1191: DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_utilization_peak_headline_revert_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_utilization_peak_headline_revert_analyzer import (
    DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _is_number,
    _valid_utilization,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    EPS,
    NEAR_FULL_UTILIZATION_PCT,
    ANCHORED_HAIRCUT_PCT,
    MILD_HAIRCUT_PCT,
    MODERATE_HAIRCUT_PCT,
    LARGE_HAIRCUT_PCT,
    HAIRCUT_PENALTY_K,
    LOG_PATH,
    LOG_CAP,
)
from spa_core.analytics import _module_registry as REG


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=8.0,
    current_utilization_pct=70.0,
    equilibrium_utilization_pct=70.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "current_utilization_pct": current_utilization_pct,
        "equilibrium_utilization_pct": equilibrium_utilization_pct,
    }


def A():
    return DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer()


def finite_check(testcase, obj):
    """Recursively assert every float in a result structure is finite."""
    if isinstance(obj, float):
        testcase.assertTrue(math.isfinite(obj), f"non-finite: {obj}")
    elif isinstance(obj, dict):
        for v in obj.values():
            finite_check(testcase, v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            finite_check(testcase, v)


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid(self):
        self.assertEqual(_f("3.5"), 3.5)
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_value(self):
        self.assertEqual(_f("abc"), 0.0)
        self.assertEqual(_f([], 1.0), 1.0)

    def test_f_negative(self):
        self.assertEqual(_f("-5"), -5.0)

    def test_f_int_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_f_dict_default(self):
        self.assertEqual(_f({}, 2.0), 2.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

    def test_f_string_number(self):
        self.assertEqual(_f("30"), 30.0)

    def test_f_bool_true(self):
        self.assertEqual(_f(True), 1.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_clamp_unit_interval(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertEqual(_mean([2.0, 4.0]), 3.0)

    def test_mean_single(self):
        self.assertEqual(_mean([9.0]), 9.0)

    def test_mean_three(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0, places=6)

    def test_safe_div_normal(self):
        self.assertEqual(_safe_div(10.0, 2.0, None), 5.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertEqual(_safe_div(10.0, -1.0, 0.0), 0.0)

    def test_safe_div_sentinel_value(self):
        self.assertEqual(_safe_div(1.0, 0.0, -1.0), -1.0)

    def test_safe_div_sentinel_zero(self):
        self.assertEqual(_safe_div(1.0, 0.0, 0.0), 0.0)

    def test_build_default_cfg_keys(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_build_default_cfg_extra(self):
        cfg = _build_default_cfg({"x": 1})
        self.assertEqual(cfg["x"], 1)

    def test_build_default_cfg_default_cap(self):
        self.assertEqual(_build_default_cfg()["log_cap"], LOG_CAP)

    def test_build_default_cfg_default_path(self):
        self.assertEqual(_build_default_cfg()["log_path"], LOG_PATH)

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(72), "B")

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

    def test_grade_just_below_85(self):
        self.assertEqual(_grade_from_score(84.99), "B")

    def test_grade_just_below_40(self):
        self.assertEqual(_grade_from_score(39.99), "F")


# ── _is_number tests ────────────────────────────────────────────────────────

class TestIsNumber(unittest.TestCase):
    def test_int(self):
        self.assertTrue(_is_number(5))

    def test_float(self):
        self.assertTrue(_is_number(5.5))

    def test_zero(self):
        self.assertTrue(_is_number(0))

    def test_negative(self):
        self.assertTrue(_is_number(-3.0))

    def test_bool_rejected(self):
        self.assertFalse(_is_number(True))
        self.assertFalse(_is_number(False))

    def test_none_rejected(self):
        self.assertFalse(_is_number(None))

    def test_string_rejected(self):
        self.assertFalse(_is_number("5"))

    def test_nan_rejected(self):
        self.assertFalse(_is_number(float("nan")))

    def test_inf_rejected(self):
        self.assertFalse(_is_number(float("inf")))

    def test_neg_inf_rejected(self):
        self.assertFalse(_is_number(float("-inf")))

    def test_list_rejected(self):
        self.assertFalse(_is_number([1]))


# ── _valid_utilization tests ──────────────────────────────────────────────────

class TestValidUtilization(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_valid_utilization(70.0), 70.0)

    def test_int(self):
        self.assertEqual(_valid_utilization(50), 50.0)

    def test_upper_bound_100(self):
        self.assertEqual(_valid_utilization(100.0), 100.0)

    def test_just_above_zero(self):
        self.assertEqual(_valid_utilization(0.0001), 0.0001)

    def test_zero_rejected(self):
        self.assertIsNone(_valid_utilization(0.0))

    def test_negative_rejected(self):
        self.assertIsNone(_valid_utilization(-5.0))

    def test_above_100_rejected(self):
        self.assertIsNone(_valid_utilization(100.01))

    def test_far_above_rejected(self):
        self.assertIsNone(_valid_utilization(250.0))

    def test_none_rejected(self):
        self.assertIsNone(_valid_utilization(None))

    def test_nan_rejected(self):
        self.assertIsNone(_valid_utilization(float("nan")))

    def test_inf_rejected(self):
        self.assertIsNone(_valid_utilization(float("inf")))

    def test_string_numeric_coerced(self):
        self.assertEqual(_valid_utilization("70"), 70.0)

    def test_string_float_coerced(self):
        self.assertEqual(_valid_utilization("85.5"), 85.5)

    def test_string_non_numeric_rejected(self):
        self.assertIsNone(_valid_utilization("abc"))

    def test_string_above_100_rejected(self):
        self.assertIsNone(_valid_utilization("150"))

    def test_bool_true_coerced(self):
        # bool fails _is_number; _f(True)->1.0 which is valid (0,100].
        self.assertEqual(_valid_utilization(True), 1.0)

    def test_bool_false_rejected(self):
        # _f(False) -> 0.0 → out of (0,100].
        self.assertIsNone(_valid_utilization(False))

    def test_list_rejected(self):
        self.assertIsNone(_valid_utilization([1]))


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_eps_small_positive(self):
        self.assertGreater(EPS, 0.0)
        self.assertLess(EPS, 1e-3)

    def test_near_full_value(self):
        self.assertEqual(NEAR_FULL_UTILIZATION_PCT, 90.0)

    def test_haircut_ordering(self):
        self.assertLess(ANCHORED_HAIRCUT_PCT, MILD_HAIRCUT_PCT)
        self.assertLess(MILD_HAIRCUT_PCT, MODERATE_HAIRCUT_PCT)

    def test_haircut_thresholds_positive(self):
        for v in (ANCHORED_HAIRCUT_PCT, MILD_HAIRCUT_PCT, MODERATE_HAIRCUT_PCT):
            self.assertGreater(v, 0.0)

    def test_large_haircut_equals_moderate(self):
        self.assertEqual(LARGE_HAIRCUT_PCT, MODERATE_HAIRCUT_PCT)

    def test_penalty_k_positive(self):
        self.assertGreater(HAIRCUT_PENALTY_K, 0.0)

    def test_penalty_k_maps_anchored_to_a(self):
        # haircut at ANCHORED boundary must score grade A (>=85).
        score = 100.0 - ANCHORED_HAIRCUT_PCT * HAIRCUT_PENALTY_K
        self.assertGreaterEqual(score, 85.0)

    def test_penalty_k_maps_severe_to_f(self):
        # haircut at MODERATE boundary (top of SEVERE start) scores < 40.
        score = 100.0 - MODERATE_HAIRCUT_PCT * HAIRCUT_PENALTY_K
        self.assertLess(score, 40.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_utilization_peak_headline_revert_log.json",
                      LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_current_util(self):
        self.assertIn("current_utilization_pct", self.r)

    def test_has_equilibrium_util(self):
        self.assertIn("equilibrium_utilization_pct", self.r)

    def test_has_equilibrium_apr(self):
        self.assertIn("equilibrium_apr_pct", self.r)

    def test_has_util_excess(self):
        self.assertIn("utilization_excess_pct", self.r)

    def test_has_revert_haircut(self):
        self.assertIn("revert_haircut_pct", self.r)

    def test_has_headline_premium(self):
        self.assertIn("headline_premium_pct", self.r)

    def test_has_above_equilibrium(self):
        self.assertIn("above_equilibrium", self.r)

    def test_has_near_full(self):
        self.assertIn("near_full_utilization", self.r)

    def test_has_score(self):
        self.assertIn("score", self.r)

    def test_has_classification(self):
        self.assertIn("classification", self.r)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.r)

    def test_has_grade(self):
        self.assertIn("grade", self.r)

    def test_has_flags(self):
        self.assertIn("flags", self.r)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_value(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_fallback(self):
        r = A().analyze({"token": "TKN", "headline_apr_pct": 8.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 8.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)

    def test_json_serializable(self):
        json.dumps(self.r)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_anchored_at_equilibrium(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["equilibrium_apr_pct"], 8.0, places=4)
        self.assertAlmostEqual(r["revert_haircut_pct"], 0.0, places=4)

    def test_below_equilibrium_no_inflation(self):
        # current util below equilibrium → headline anchored, eq_apr=headline.
        r = A().analyze(make_pos(headline_apr_pct=7.0,
                                 current_utilization_pct=55.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["equilibrium_apr_pct"], 7.0, places=4)
        self.assertAlmostEqual(r["revert_haircut_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["utilization_excess_pct"], 0.0, places=4)

    def test_above_equilibrium_discount(self):
        # headline 12 @ util 95 vs eq 70 → eq_apr = 12*70/95 ≈ 8.8421.
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["equilibrium_apr_pct"], 12.0 * 70.0 / 95.0,
                               places=3)

    def test_equilibrium_apr_clamped_to_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=50.0,
                                 equilibrium_utilization_pct=80.0))
        self.assertLessEqual(r["equilibrium_apr_pct"], r["headline_apr_pct"])

    def test_utilization_excess(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["utilization_excess_pct"], 15.0, places=4)

    def test_utilization_excess_zero_below(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=60.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["utilization_excess_pct"], 0.0, places=4)

    def test_revert_haircut_value(self):
        # eq_apr = 10*70/90 = 7.7778; haircut = (10-7.7778)/10*100 = 22.222.
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=90.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["revert_haircut_pct"], 22.2222, places=3)

    def test_revert_haircut_in_range(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 current_utilization_pct=100.0,
                                 equilibrium_utilization_pct=1.0))
        self.assertGreaterEqual(r["revert_haircut_pct"], 0.0)
        self.assertLessEqual(r["revert_haircut_pct"], 100.0)

    def test_headline_premium(self):
        # eq_apr = 10*70/90 = 7.7778; premium = (10-7.7778)/7.7778*100 ≈ 28.57.
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=90.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["headline_premium_pct"], 28.5714, places=2)

    def test_headline_premium_zero_anchored(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertAlmostEqual(r["headline_premium_pct"], 0.0, places=4)

    def test_above_equilibrium_true(self):
        r = A().analyze(make_pos(current_utilization_pct=80.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertTrue(r["above_equilibrium"])

    def test_above_equilibrium_false_equal(self):
        r = A().analyze(make_pos(current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertFalse(r["above_equilibrium"])

    def test_above_equilibrium_false_below(self):
        r = A().analyze(make_pos(current_utilization_pct=60.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertFalse(r["above_equilibrium"])

    def test_near_full_true(self):
        r = A().analyze(make_pos(current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertTrue(r["near_full_utilization"])

    def test_near_full_boundary(self):
        r = A().analyze(make_pos(current_utilization_pct=90.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertTrue(r["near_full_utilization"])

    def test_near_full_false(self):
        r = A().analyze(make_pos(current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertFalse(r["near_full_utilization"])

    def test_finite_all_metrics(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=14.0, current_utilization_pct=95.0,
            equilibrium_utilization_pct=60.0)))


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_anchored_equal(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["classification"], "ANCHORED")

    def test_anchored_below(self):
        r = A().analyze(make_pos(headline_apr_pct=7.0,
                                 current_utilization_pct=55.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["classification"], "ANCHORED")

    def test_mild(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 current_utilization_pct=75.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["classification"], "MILD_PEAK")

    def test_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["classification"], "MODERATE_PEAK")

    def test_severe(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertEqual(r["classification"], "SEVERE_PEAK")

    def test_classify_boundary_anchored(self):
        self.assertEqual(A()._classify(ANCHORED_HAIRCUT_PCT), "ANCHORED")

    def test_classify_boundary_mild(self):
        self.assertEqual(A()._classify(MILD_HAIRCUT_PCT), "MILD_PEAK")

    def test_classify_boundary_moderate(self):
        self.assertEqual(A()._classify(MODERATE_HAIRCUT_PCT), "MODERATE_PEAK")

    def test_classify_above_moderate(self):
        self.assertEqual(A()._classify(MODERATE_HAIRCUT_PCT + 0.01),
                         "SEVERE_PEAK")

    def test_classify_just_above_anchored(self):
        self.assertEqual(A()._classify(ANCHORED_HAIRCUT_PCT + 0.01),
                         "MILD_PEAK")

    def test_classify_just_above_mild(self):
        self.assertEqual(A()._classify(MILD_HAIRCUT_PCT + 0.01),
                         "MODERATE_PEAK")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "ANCHORED")

    def test_classify_huge(self):
        self.assertEqual(A()._classify(100.0), "SEVERE_PEAK")

    def test_classify_negative_clamped(self):
        self.assertEqual(A()._classify(-5.0), "ANCHORED")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_anchored(self):
        self.assertEqual(A()._recommend("ANCHORED"), "TRUST_HEADLINE")

    def test_mild(self):
        self.assertEqual(A()._recommend("MILD_PEAK"), "MINOR_DISCOUNT")

    def test_moderate(self):
        self.assertEqual(A()._recommend("MODERATE_PEAK"),
                         "USE_EQUILIBRIUM_BASE")

    def test_severe(self):
        self.assertEqual(A()._recommend("SEVERE_PEAK"), "AVOID_OR_VERIFY")

    def test_anchored_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_severe_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_moderate_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["recommendation"], "USE_EQUILIBRIUM_BASE")

    def test_mild_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 current_utilization_pct=75.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["recommendation"], "MINOR_DISCOUNT")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_anchored_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertIn("ANCHORED", r["flags"])

    def test_mild_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 current_utilization_pct=75.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertIn("MILD_PEAK", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertIn("MODERATE_PEAK", r["flags"])

    def test_severe_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertIn("SEVERE_PEAK", r["flags"])

    def test_above_equilibrium_flag(self):
        r = A().analyze(make_pos(current_utilization_pct=80.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertIn("ABOVE_EQUILIBRIUM_UTIL", r["flags"])

    def test_no_above_equilibrium_flag(self):
        r = A().analyze(make_pos(current_utilization_pct=60.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertNotIn("ABOVE_EQUILIBRIUM_UTIL", r["flags"])

    def test_near_full_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertIn("NEAR_FULL_UTILIZATION", r["flags"])

    def test_no_near_full_flag(self):
        r = A().analyze(make_pos(current_utilization_pct=80.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertNotIn("NEAR_FULL_UTILIZATION", r["flags"])

    def test_large_haircut_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertIn("LARGE_REVERT_HAIRCUT", r["flags"])

    def test_no_large_haircut_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 current_utilization_pct=75.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertNotIn("LARGE_REVERT_HAIRCUT", r["flags"])

    def test_insufficient_data_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))

    def test_flags_direct(self):
        flags = A()._flags("SEVERE_PEAK", True, True, 40.0)
        self.assertIn("SEVERE_PEAK", flags)
        self.assertIn("ABOVE_EQUILIBRIUM_UTIL", flags)
        self.assertIn("NEAR_FULL_UTILIZATION", flags)
        self.assertIn("LARGE_REVERT_HAIRCUT", flags)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": -3.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X", "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf"),
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_current_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_current_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 0.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_current_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": -5.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_above_100_current_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 120.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_current_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": float("nan"),
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_equilibrium_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 70.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_equilibrium_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 0.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_above_100_equilibrium_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 110.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_equilibrium_util(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertIsNone(r["current_utilization_pct"])
        self.assertIsNone(r["equilibrium_utilization_pct"])
        self.assertIsNone(r["equilibrium_apr_pct"])
        self.assertIsNone(r["utilization_excess_pct"])
        self.assertIsNone(r["revert_haircut_pct"])
        self.assertIsNone(r["headline_premium_pct"])

    def test_recommendation(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze({"vault": "ZZZ", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0})
        json.dumps(r)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_nan_in_insufficient(self):
        finite_check(self, A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                                        "current_utilization_pct": 0.0,
                                        "equilibrium_utilization_pct": 70.0}))

    def test_above_equilibrium_false(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertFalse(r["above_equilibrium"])

    def test_near_full_false(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "current_utilization_pct": 70.0,
                         "equilibrium_utilization_pct": 70.0})
        self.assertFalse(r["near_full_utilization"])


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_at_zero_haircut(self):
        self.assertAlmostEqual(A()._score(0.0), 100.0, places=4)

    def test_score_at_anchored_boundary(self):
        # haircut 2 → 100 - 6 = 94.
        self.assertAlmostEqual(A()._score(2.0), 94.0, places=4)

    def test_score_at_mild_boundary(self):
        # haircut 10 → 100 - 30 = 70.
        self.assertAlmostEqual(A()._score(10.0), 70.0, places=4)

    def test_score_at_moderate_boundary(self):
        # haircut 25 → 100 - 75 = 25.
        self.assertAlmostEqual(A()._score(25.0), 25.0, places=4)

    def test_score_clamps_at_zero(self):
        self.assertAlmostEqual(A()._score(50.0), 0.0, places=4)

    def test_score_clamps_above_100_haircut(self):
        self.assertAlmostEqual(A()._score(500.0), 0.0, places=4)

    def test_score_clamps_negative_haircut(self):
        self.assertAlmostEqual(A()._score(-5.0), 100.0, places=4)

    def test_score_monotonic(self):
        prev = 101.0
        for h in (0.0, 2.0, 5.0, 10.0, 20.0, 33.4):
            s = A()._score(h)
            self.assertLessEqual(s, prev)
            prev = s

    def test_score_in_range(self):
        for h in (0.0, 1.0, 10.0, 33.0, 50.0, 100.0):
            s = A()._score(h)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_score_finite(self):
        for h in (0.0, 25.0, 100.0):
            self.assertTrue(math.isfinite(A()._score(h)))

    def test_anchored_grade_a(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["grade"], "A")

    def test_severe_grade_f(self):
        r = A().analyze(make_pos(headline_apr_pct=14.0,
                                 current_utilization_pct=95.0,
                                 equilibrium_utilization_pct=60.0))
        self.assertEqual(r["grade"], "F")

    def test_anchored_higher_than_severe(self):
        anchored = A().analyze(make_pos(
            headline_apr_pct=8.0, current_utilization_pct=70.0,
            equilibrium_utilization_pct=70.0))["score"]
        severe = A().analyze(make_pos(
            headline_apr_pct=14.0, current_utilization_pct=95.0,
            equilibrium_utilization_pct=60.0))["score"]
        self.assertGreater(anchored, severe)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 current_utilization_pct=85.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_anchored_scores_high(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 current_utilization_pct=70.0,
                                 equilibrium_utilization_pct=70.0))
        self.assertGreaterEqual(r["score"], 85.0)

    def test_score_idempotent(self):
        p = make_pos(headline_apr_pct=11.0, current_utilization_pct=85.0,
                     equilibrium_utilization_pct=70.0)
        self.assertEqual(A().analyze(p)["score"], A().analyze(p)["score"])


# ── portfolio / aggregate ─────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_positions_key(self):
        res = A().analyze_portfolio([make_pos()])
        self.assertIn("positions", res)

    def test_aggregate_key(self):
        res = A().analyze_portfolio([make_pos()])
        self.assertIn("aggregate", res)

    def test_position_count(self):
        res = A().analyze_portfolio([make_pos(), make_pos()])
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)
        self.assertIsNone(res["aggregate"]["least_revert_vault"])
        self.assertIsNone(res["aggregate"]["most_revert_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["severe_peak_count"], 0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([
            {"vault": "X", "headline_apr_pct": 0.0,
             "current_utilization_pct": 70.0,
             "equilibrium_utilization_pct": 70.0}])
        self.assertIsNone(res["aggregate"]["least_revert_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_least_revert_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="CLEAN", headline_apr_pct=8.0,
                     current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
            make_pos(vault="PEAKED", headline_apr_pct=14.0,
                     current_utilization_pct=95.0,
                     equilibrium_utilization_pct=60.0),
        ])
        self.assertEqual(res["aggregate"]["least_revert_vault"], "CLEAN")

    def test_most_revert_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="CLEAN", headline_apr_pct=8.0,
                     current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
            make_pos(vault="PEAKED", headline_apr_pct=14.0,
                     current_utilization_pct=95.0,
                     equilibrium_utilization_pct=60.0),
        ])
        self.assertEqual(res["aggregate"]["most_revert_vault"], "PEAKED")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=8.0, current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
            make_pos(headline_apr_pct=8.0, current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
        ])
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 99.0)

    def test_severe_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=14.0, current_utilization_pct=95.0,
                     equilibrium_utilization_pct=60.0),
            make_pos(headline_apr_pct=14.0, current_utilization_pct=95.0,
                     equilibrium_utilization_pct=60.0),
            make_pos(headline_apr_pct=8.0, current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
        ])
        self.assertEqual(res["aggregate"]["severe_peak_count"], 2)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        finite_check(self, res["aggregate"])

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", headline_apr_pct=8.0,
                     current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
            {"vault": "BAD", "headline_apr_pct": 0.0},
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["least_revert_vault"], "GOOD")

    def test_insufficient_excluded_from_scored(self):
        # insufficient must not be the most_revert (avg unaffected by it).
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", headline_apr_pct=8.0,
                     current_utilization_pct=70.0,
                     equilibrium_utilization_pct=70.0),
            {"vault": "BAD", "headline_apr_pct": 0.0},
        ])
        self.assertNotEqual(res["aggregate"]["most_revert_vault"], "BAD")

    def test_aggregate_json(self):
        res = A().analyze_portfolio(_demo_positions())
        json.dumps(res)


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def _cfg(self, path):
        return {"log_path": path, "log_cap": LOG_CAP}

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            self.assertTrue(os.path.exists(p))

    def test_write_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_no_write_when_flag_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=False)
            self.assertFalse(os.path.exists(p))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            cfg = {"log_path": p, "log_cap": 3}
            for _ in range(10):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            cfg = {"log_path": p, "log_cap": 100}
            for _ in range(130):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_ring_buffer_no_tmp_after_overflow(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            cfg = {"log_path": p, "log_cap": 100}
            for _ in range(105):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(p + ".tmp"))

    def test_log_entry_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos()], cfg=self._cfg(p),
                                  write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            entry = data[0]
            self.assertIn("ts", entry)
            self.assertIn("position_count", entry)
            self.assertIn("aggregate", entry)
            self.assertIn("snapshots", entry)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            self.assertFalse(os.path.exists(p + ".tmp"))

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            with open(p, "w") as fh:
                fh.write("not json{{")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_non_list_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            with open(p, "w") as fh:
                json.dump({"x": 1}, fh)
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_snapshot_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(vault="SNAP")],
                                  cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            self.assertEqual(snap["token"], "SNAP")
            self.assertIn("classification", snap)
            self.assertIn("score", snap)
            self.assertIn("flags", snap)

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio(_demo_positions(), cfg=self._cfg(p),
                                  write_log=True)
            with open(p) as fh:
                s = fh.read()
            self.assertNotIn("Infinity", s)
            self.assertNotIn("NaN", s)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_no_nan_in_output(self):
        for p in _demo_positions():
            finite_check(self, A().analyze(p))

    def test_string_inputs(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": "11",
                         "current_utilization_pct": "85",
                         "equilibrium_utilization_pct": "70"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_headline(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=1e9, current_utilization_pct=99.0,
            equilibrium_utilization_pct=50.0)))

    def test_tiny_equilibrium_util(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=10.0, current_utilization_pct=99.0,
            equilibrium_utilization_pct=0.001)))

    def test_full_utilization_100(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_utilization_pct=100.0,
                                 equilibrium_utilization_pct=50.0))
        finite_check(self, r)
        self.assertTrue(r["near_full_utilization"])

    def test_idempotent_full(self):
        p = make_pos(headline_apr_pct=11.0, current_utilization_pct=85.0,
                     equilibrium_utilization_pct=70.0)
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_haircut_non_negative_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["revert_haircut_pct"] is not None:
                self.assertGreaterEqual(r["revert_haircut_pct"], 0.0)
                self.assertLessEqual(r["revert_haircut_pct"], 100.0)

    def test_equilibrium_apr_not_exceeding_headline_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["equilibrium_apr_pct"] is not None:
                self.assertLessEqual(r["equilibrium_apr_pct"],
                                     r["headline_apr_pct"] + 1e-6)

    def test_score_in_unit_range_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)


# ── registry ──────────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    MOD = "defi_protocol_vault_utilization_peak_headline_revert_analyzer"
    CLS = "DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer"

    def test_module_present(self):
        info = REG.get_module_info(self.MOD)
        self.assertIsNotNone(info)

    def test_class_name(self):
        info = REG.get_module_info(self.MOD)
        self.assertEqual(info["class"], self.CLS)

    def test_tier_b(self):
        info = REG.get_module_info(self.MOD)
        self.assertEqual(info["tier"], "B")

    def test_category_yield_quality(self):
        info = REG.get_module_info(self.MOD)
        self.assertEqual(info["category"], "yield_quality")

    def test_weight(self):
        info = REG.get_module_info(self.MOD)
        self.assertEqual(info["weight"], 0.5)

    def test_protocols_all(self):
        info = REG.get_module_info(self.MOD)
        self.assertEqual(info["protocols"], ["all"])

    def test_in_tier_b_list(self):
        mods = [m["module"] for m in REG.TIER_B_MODULES]
        self.assertIn(self.MOD, mods)


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_count(self):
        self.assertEqual(len(_demo_positions()), 6)

    def test_demo_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), 6)

    def test_demo_has_insufficient_data(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("ANCHORED", "MILD_PEAK", "MODERATE_PEAK", "SEVERE_PEAK",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_trust_and_avoid(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("TRUST_HEADLINE", recs)
        self.assertIn("AVOID_OR_VERIFY", recs)

    def test_demo_includes_use_equilibrium(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("USE_EQUILIBRIUM_BASE", recs)

    def test_demo_includes_minor_discount(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("MINOR_DISCOUNT", recs)

    def test_demo_includes_near_full(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("NEAR_FULL_UTILIZATION" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_includes_above_equilibrium(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("ABOVE_EQUILIBRIUM_UTIL" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_avg_score_in_range(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertLessEqual(res["aggregate"]["avg_score"], 100.0)

    def test_demo_json_no_inf_nan_tokens(self):
        s = json.dumps(A().analyze_portfolio(_demo_positions()))
        self.assertNotIn("Infinity", s)
        self.assertNotIn("NaN", s)

    def test_demo_severe_count(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(res["aggregate"]["severe_peak_count"], 1)


# ── forbidden imports ───────────────────────────────────────────────────────

class TestNoForbiddenImports(unittest.TestCase):
    def _source(self):
        path = os.path.join(
            ROOT, "spa_core", "analytics",
            "defi_protocol_vault_utilization_peak_headline_revert_analyzer.py")
        with open(path) as fh:
            return fh.read()

    def test_no_numpy(self):
        self.assertNotIn("import numpy", self._source())

    def test_no_pandas(self):
        self.assertNotIn("import pandas", self._source())

    def test_no_requests(self):
        self.assertNotIn("import requests", self._source())

    def test_no_web3(self):
        self.assertNotIn("web3", self._source())

    def test_no_scipy(self):
        self.assertNotIn("scipy", self._source())

    def test_no_openai(self):
        self.assertNotIn("openai", self._source())

    def test_no_anthropic(self):
        self.assertNotIn("anthropic", self._source())

    def test_no_subprocess(self):
        self.assertNotIn("subprocess", self._source())

    def test_no_os_system(self):
        self.assertNotIn("os.system", self._source())

    def test_no_eval(self):
        self.assertNotIn("eval(", self._source())

    def test_no_exec(self):
        self.assertNotIn("exec(", self._source())

    def test_no_risk_import(self):
        self.assertNotIn("spa_core.risk", self._source())

    def test_no_execution_import(self):
        self.assertNotIn("spa_core.execution", self._source())

    def test_no_monitoring_import(self):
        self.assertNotIn("spa_core.monitoring", self._source())

    def test_no_allocator_import(self):
        self.assertNotIn("spa_core.allocator", self._source())


if __name__ == "__main__":
    unittest.main()
