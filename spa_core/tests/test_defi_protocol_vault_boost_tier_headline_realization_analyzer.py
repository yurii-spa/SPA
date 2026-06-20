"""
Tests for MP-1192: DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_boost_tier_headline_realization_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_boost_tier_headline_realization_analyzer import (
    DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _is_number,
    _valid_max_boost,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    EPS,
    MAX_BOOST_REQUIRED_MULTIPLIER,
    FULLY_REALIZED_HAIRCUT_PCT,
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
    vault="CRV-Vault",
    headline_apr_pct=20.0,
    max_boost_multiplier=2.5,
    depositor_boost_multiplier=2.5,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "max_boost_multiplier": max_boost_multiplier,
        "depositor_boost_multiplier": depositor_boost_multiplier,
    }


def A():
    return DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer()


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

    def test_clamp_boost_range(self):
        self.assertEqual(_clamp(0.5, 1.0, 2.5), 1.0)
        self.assertEqual(_clamp(3.0, 1.0, 2.5), 2.5)
        self.assertEqual(_clamp(1.8, 1.0, 2.5), 1.8)

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


# ── _valid_max_boost tests ──────────────────────────────────────────────────

class TestValidMaxBoost(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_valid_max_boost(2.5), 2.5)

    def test_int(self):
        self.assertEqual(_valid_max_boost(2), 2.0)

    def test_exactly_one(self):
        self.assertEqual(_valid_max_boost(1.0), 1.0)

    def test_large(self):
        self.assertEqual(_valid_max_boost(10.0), 10.0)

    def test_below_one_rejected(self):
        self.assertIsNone(_valid_max_boost(0.9))

    def test_zero_rejected(self):
        self.assertIsNone(_valid_max_boost(0.0))

    def test_negative_rejected(self):
        self.assertIsNone(_valid_max_boost(-2.0))

    def test_none_rejected(self):
        self.assertIsNone(_valid_max_boost(None))

    def test_nan_rejected(self):
        self.assertIsNone(_valid_max_boost(float("nan")))

    def test_inf_rejected(self):
        self.assertIsNone(_valid_max_boost(float("inf")))

    def test_string_numeric_coerced(self):
        self.assertEqual(_valid_max_boost("2.5"), 2.5)

    def test_string_int_coerced(self):
        self.assertEqual(_valid_max_boost("3"), 3.0)

    def test_string_non_numeric_rejected(self):
        self.assertIsNone(_valid_max_boost("abc"))

    def test_string_below_one_rejected(self):
        self.assertIsNone(_valid_max_boost("0.5"))

    def test_bool_true_coerced(self):
        # bool fails _is_number; _f(True)->1.0 which is valid (>=1.0).
        self.assertEqual(_valid_max_boost(True), 1.0)

    def test_bool_false_rejected(self):
        # _f(False) -> 0.0 → below 1.0.
        self.assertIsNone(_valid_max_boost(False))

    def test_list_rejected(self):
        self.assertIsNone(_valid_max_boost([1]))


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_eps_small_positive(self):
        self.assertGreater(EPS, 0.0)
        self.assertLess(EPS, 1e-3)

    def test_max_boost_required_value(self):
        self.assertEqual(MAX_BOOST_REQUIRED_MULTIPLIER, 2.0)

    def test_fully_realized_value(self):
        self.assertEqual(FULLY_REALIZED_HAIRCUT_PCT, 2.0)

    def test_mild_value(self):
        self.assertEqual(MILD_HAIRCUT_PCT, 15.0)

    def test_moderate_value(self):
        self.assertEqual(MODERATE_HAIRCUT_PCT, 40.0)

    def test_haircut_ordering(self):
        self.assertLess(FULLY_REALIZED_HAIRCUT_PCT, MILD_HAIRCUT_PCT)
        self.assertLess(MILD_HAIRCUT_PCT, MODERATE_HAIRCUT_PCT)

    def test_haircut_thresholds_positive(self):
        for v in (FULLY_REALIZED_HAIRCUT_PCT, MILD_HAIRCUT_PCT,
                  MODERATE_HAIRCUT_PCT):
            self.assertGreater(v, 0.0)

    def test_large_haircut_equals_moderate(self):
        self.assertEqual(LARGE_HAIRCUT_PCT, MODERATE_HAIRCUT_PCT)

    def test_penalty_k_positive(self):
        self.assertGreater(HAIRCUT_PENALTY_K, 0.0)

    def test_penalty_k_value(self):
        self.assertAlmostEqual(HAIRCUT_PENALTY_K, 1.6, places=6)

    def test_penalty_k_maps_fully_realized_to_a(self):
        # haircut at FULLY_REALIZED boundary must score grade A (>=85).
        score = 100.0 - FULLY_REALIZED_HAIRCUT_PCT * HAIRCUT_PENALTY_K
        self.assertGreaterEqual(score, 85.0)

    def test_penalty_k_maps_mild_to_b(self):
        # haircut at MILD boundary scores grade B (>=70, <85).
        score = 100.0 - MILD_HAIRCUT_PCT * HAIRCUT_PENALTY_K
        self.assertGreaterEqual(score, 70.0)
        self.assertLess(score, 85.0)

    def test_penalty_k_maps_moderate_boundary_to_f(self):
        # haircut at MODERATE boundary (top) scores < 40.
        score = 100.0 - MODERATE_HAIRCUT_PCT * HAIRCUT_PENALTY_K
        self.assertLess(score, 40.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_boost_tier_headline_realization_log.json",
                      LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_max_boost(self):
        self.assertIn("max_boost_multiplier", self.r)

    def test_has_depositor_boost(self):
        self.assertIn("depositor_boost_multiplier", self.r)

    def test_has_base_apr(self):
        self.assertIn("base_apr_pct", self.r)

    def test_has_realized_apr(self):
        self.assertIn("realized_apr_pct", self.r)

    def test_has_realization_ratio(self):
        self.assertIn("realization_ratio", self.r)

    def test_has_boost_gap_multiplier(self):
        self.assertIn("boost_gap_multiplier", self.r)

    def test_has_boost_haircut(self):
        self.assertIn("boost_haircut_pct", self.r)

    def test_has_boost_premium(self):
        self.assertIn("boost_premium_pct", self.r)

    def test_has_unboosted(self):
        self.assertIn("unboosted", self.r)

    def test_has_max_boost_required(self):
        self.assertIn("max_boost_required", self.r)

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
        self.assertEqual(self.r["token"], "CRV-Vault")

    def test_token_fallback(self):
        r = A().analyze({"token": "TKN", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": 2.5})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": 2.5})
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
    def test_base_apr_value(self):
        # base = headline / max_boost = 20 / 2.5 = 8.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["base_apr_pct"], 8.0, places=4)

    def test_base_apr_max_one(self):
        # max_boost = 1.0 → base = headline.
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 max_boost_multiplier=1.0,
                                 depositor_boost_multiplier=1.0))
        self.assertAlmostEqual(r["base_apr_pct"], 12.0, places=4)

    def test_realized_apr_at_max(self):
        # depositor at max → realized = headline.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["realized_apr_pct"], 20.0, places=4)

    def test_realized_apr_unboosted(self):
        # depositor 1.0 at max 2.5 → realized = headline * 1/2.5 = 8.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 8.0, places=4)

    def test_realized_apr_partial(self):
        # depositor 1.6 at max 2.5 → realized = 16 * 1.6/2.5 = 10.24.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["realized_apr_pct"], 10.24, places=4)

    def test_realized_equals_base_times_boost(self):
        # realized = base_apr * dep_boost.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["realized_apr_pct"],
                               r["base_apr_pct"] * 1.6, places=4)

    def test_realization_ratio_value(self):
        # ratio = dep/max = 1.6/2.5 = 0.64.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["realization_ratio"], 0.64, places=4)

    def test_realization_ratio_at_max_is_one(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=4)

    def test_realization_ratio_unboosted(self):
        # 1/2.5 = 0.4.
        r = A().analyze(make_pos(depositor_boost_multiplier=1.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.4, places=4)

    def test_boost_gap_multiplier(self):
        # max - dep = 2.5 - 1.6 = 0.9.
        r = A().analyze(make_pos(max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["boost_gap_multiplier"], 0.9, places=4)

    def test_boost_gap_zero_at_max(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["boost_gap_multiplier"], 0.0, places=4)

    def test_boost_haircut_value(self):
        # (1 - 0.64)*100 = 36.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["boost_haircut_pct"], 36.0, places=4)

    def test_boost_haircut_zero_at_max(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["boost_haircut_pct"], 0.0, places=4)

    def test_boost_haircut_unboosted(self):
        # (1 - 0.4)*100 = 60.
        r = A().analyze(make_pos(depositor_boost_multiplier=1.0))
        self.assertAlmostEqual(r["boost_haircut_pct"], 60.0, places=4)

    def test_boost_haircut_in_range(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=10.0,
                                 depositor_boost_multiplier=1.0))
        self.assertGreaterEqual(r["boost_haircut_pct"], 0.0)
        self.assertLessEqual(r["boost_haircut_pct"], 100.0)

    def test_boost_premium_value(self):
        # headline 20, realized 8 → premium = (20-8)/8*100 = 150.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertAlmostEqual(r["boost_premium_pct"], 150.0, places=4)

    def test_boost_premium_partial(self):
        # headline 16, realized 10.24 → (16-10.24)/10.24*100 = 56.25.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertAlmostEqual(r["boost_premium_pct"], 56.25, places=4)

    def test_boost_premium_zero_at_max(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertAlmostEqual(r["boost_premium_pct"], 0.0, places=4)

    def test_unboosted_true(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=1.0))
        self.assertTrue(r["unboosted"])

    def test_unboosted_false_partial(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=1.6))
        self.assertFalse(r["unboosted"])

    def test_unboosted_false_when_max_one(self):
        # max_boost = 1.0 → no boost program → not "unboosted".
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 max_boost_multiplier=1.0,
                                 depositor_boost_multiplier=1.0))
        self.assertFalse(r["unboosted"])

    def test_max_boost_required_true(self):
        r = A().analyze(make_pos(max_boost_multiplier=2.5))
        self.assertTrue(r["max_boost_required"])

    def test_max_boost_required_boundary(self):
        r = A().analyze(make_pos(max_boost_multiplier=2.0,
                                 depositor_boost_multiplier=2.0))
        self.assertTrue(r["max_boost_required"])

    def test_max_boost_required_false(self):
        r = A().analyze(make_pos(max_boost_multiplier=1.5,
                                 depositor_boost_multiplier=1.0))
        self.assertFalse(r["max_boost_required"])

    def test_finite_all_metrics(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=20.0, max_boost_multiplier=2.5,
            depositor_boost_multiplier=1.0)))


# ── clamping of depositor_boost ────────────────────────────────────────────────

class TestDepositorBoostClamp(unittest.TestCase):
    def test_above_max_clamped(self):
        # dep 3.0 > max 2.5 → clamped to 2.5 → realization 1.0 → FULLY_REALIZED.
        r = A().analyze(make_pos(depositor_boost_multiplier=3.0))
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 2.5, places=4)
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=4)
        self.assertEqual(r["classification"], "FULLY_REALIZED")

    def test_below_one_clamped(self):
        # dep 0.5 < 1.0 → clamped to 1.0.
        r = A().analyze(make_pos(depositor_boost_multiplier=0.5))
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_missing_defaults_to_one(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_none_defaults_to_one(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": None})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_nan_defaults_to_one(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": float("nan")})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_inf_defaults_to_max(self):
        # inf is not finite → defaults to 1.0 before clamp.
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": float("inf")})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_string_defaults_to_value(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": "garbage"})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.0, places=4)

    def test_string_numeric_coerced(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 16.0,
                         "max_boost_multiplier": 2.5,
                         "depositor_boost_multiplier": "1.6"})
        self.assertAlmostEqual(r["depositor_boost_multiplier"], 1.6, places=4)

    def test_above_max_realized_capped(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 depositor_boost_multiplier=99.0))
        self.assertLessEqual(r["realized_apr_pct"], r["headline_apr_pct"] + 1e-6)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_fully_realized_at_max(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertEqual(r["classification"], "FULLY_REALIZED")

    def test_mild(self):
        # dep 2.2/2.5 → ratio 0.88 → haircut 12 → MILD.
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.2))
        self.assertEqual(r["classification"], "MILD_BOOST_GAP")

    def test_moderate(self):
        # dep 1.6/2.5 → haircut 36 → MODERATE.
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertEqual(r["classification"], "MODERATE_BOOST_GAP")

    def test_severe(self):
        # unboosted at max 2.5 → haircut 60 → SEVERE.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertEqual(r["classification"], "SEVERE_BOOST_GAP")

    def test_classify_boundary_fully_realized(self):
        self.assertEqual(A()._classify(FULLY_REALIZED_HAIRCUT_PCT),
                         "FULLY_REALIZED")

    def test_classify_boundary_mild(self):
        self.assertEqual(A()._classify(MILD_HAIRCUT_PCT), "MILD_BOOST_GAP")

    def test_classify_boundary_moderate(self):
        self.assertEqual(A()._classify(MODERATE_HAIRCUT_PCT),
                         "MODERATE_BOOST_GAP")

    def test_classify_above_moderate(self):
        self.assertEqual(A()._classify(MODERATE_HAIRCUT_PCT + 0.01),
                         "SEVERE_BOOST_GAP")

    def test_classify_just_above_fully_realized(self):
        self.assertEqual(A()._classify(FULLY_REALIZED_HAIRCUT_PCT + 0.01),
                         "MILD_BOOST_GAP")

    def test_classify_just_above_mild(self):
        self.assertEqual(A()._classify(MILD_HAIRCUT_PCT + 0.01),
                         "MODERATE_BOOST_GAP")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "FULLY_REALIZED")

    def test_classify_huge(self):
        self.assertEqual(A()._classify(100.0), "SEVERE_BOOST_GAP")

    def test_classify_negative_clamped(self):
        self.assertEqual(A()._classify(-5.0), "FULLY_REALIZED")

    def test_classify_at_two(self):
        # exactly at 2.0 → FULLY_REALIZED.
        self.assertEqual(A()._classify(2.0), "FULLY_REALIZED")

    def test_classify_at_fifteen(self):
        self.assertEqual(A()._classify(15.0), "MILD_BOOST_GAP")

    def test_classify_at_forty(self):
        self.assertEqual(A()._classify(40.0), "MODERATE_BOOST_GAP")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_fully_realized(self):
        self.assertEqual(A()._recommend("FULLY_REALIZED"), "TRUST_HEADLINE")

    def test_mild(self):
        self.assertEqual(A()._recommend("MILD_BOOST_GAP"), "MINOR_DISCOUNT")

    def test_moderate(self):
        self.assertEqual(A()._recommend("MODERATE_BOOST_GAP"),
                         "USE_BASE_OR_BOOST_TIER")

    def test_severe(self):
        self.assertEqual(A()._recommend("SEVERE_BOOST_GAP"),
                         "AVOID_OR_LOCK_FOR_BOOST")

    def test_fully_realized_via_analyze(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_severe_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_LOCK_FOR_BOOST")

    def test_moderate_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertEqual(r["recommendation"], "USE_BASE_OR_BOOST_TIER")

    def test_mild_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.2))
        self.assertEqual(r["recommendation"], "MINOR_DISCOUNT")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fully_realized_flag(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertIn("FULLY_REALIZED", r["flags"])

    def test_mild_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.2))
        self.assertIn("MILD_BOOST_GAP", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertIn("MODERATE_BOOST_GAP", r["flags"])

    def test_severe_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertIn("SEVERE_BOOST_GAP", r["flags"])

    def test_unboosted_flag(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=1.0))
        self.assertIn("UNBOOSTED", r["flags"])

    def test_no_unboosted_flag_partial(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=1.6))
        self.assertNotIn("UNBOOSTED", r["flags"])

    def test_no_unboosted_flag_when_max_one(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 max_boost_multiplier=1.0,
                                 depositor_boost_multiplier=1.0))
        self.assertNotIn("UNBOOSTED", r["flags"])

    def test_max_boost_required_flag(self):
        r = A().analyze(make_pos(max_boost_multiplier=2.5))
        self.assertIn("MAX_BOOST_REQUIRED", r["flags"])

    def test_no_max_boost_required_flag(self):
        r = A().analyze(make_pos(max_boost_multiplier=1.5,
                                 depositor_boost_multiplier=1.0))
        self.assertNotIn("MAX_BOOST_REQUIRED", r["flags"])

    def test_large_haircut_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertIn("LARGE_BOOST_HAIRCUT", r["flags"])

    def test_no_large_haircut_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.2))
        self.assertNotIn("LARGE_BOOST_HAIRCUT", r["flags"])

    def test_unboosted_and_max_boost_combo(self):
        # unboosted at max 2.5 → both UNBOOSTED and MAX_BOOST_REQUIRED.
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertIn("UNBOOSTED", r["flags"])
        self.assertIn("MAX_BOOST_REQUIRED", r["flags"])

    def test_insufficient_data_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))

    def test_flags_direct(self):
        flags = A()._flags("SEVERE_BOOST_GAP", True, True, 60.0)
        self.assertIn("SEVERE_BOOST_GAP", flags)
        self.assertIn("UNBOOSTED", flags)
        self.assertIn("MAX_BOOST_REQUIRED", flags)
        self.assertIn("LARGE_BOOST_HAIRCUT", flags)

    def test_flags_direct_fully_realized(self):
        flags = A()._flags("FULLY_REALIZED", False, True, 0.0)
        self.assertIn("FULLY_REALIZED", flags)
        self.assertIn("MAX_BOOST_REQUIRED", flags)
        self.assertNotIn("UNBOOSTED", flags)
        self.assertNotIn("LARGE_BOOST_HAIRCUT", flags)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": -3.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X", "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf"),
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_max_boost(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_below_one(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 0.8})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": 0.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_negative(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": -2.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_nan(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_inf(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_max_boost_none(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "max_boost_multiplier": None})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertIsNone(r["max_boost_multiplier"])
        self.assertIsNone(r["depositor_boost_multiplier"])
        self.assertIsNone(r["base_apr_pct"])
        self.assertIsNone(r["realized_apr_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["boost_gap_multiplier"])
        self.assertIsNone(r["boost_haircut_pct"])
        self.assertIsNone(r["boost_premium_pct"])

    def test_recommendation(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze({"vault": "ZZZ", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0})
        json.dumps(r)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_nan_in_insufficient(self):
        finite_check(self, A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                                        "max_boost_multiplier": 0.5}))

    def test_unboosted_false(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertFalse(r["unboosted"])

    def test_max_boost_required_false(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "max_boost_multiplier": 2.5})
        self.assertFalse(r["max_boost_required"])


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_at_zero_haircut(self):
        self.assertAlmostEqual(A()._score(0.0), 100.0, places=4)

    def test_score_at_fully_realized_boundary(self):
        # haircut 2 → 100 - 3.2 = 96.8.
        self.assertAlmostEqual(A()._score(2.0), 96.8, places=4)

    def test_score_at_mild_boundary(self):
        # haircut 15 → 100 - 24 = 76.
        self.assertAlmostEqual(A()._score(15.0), 76.0, places=4)

    def test_score_at_moderate_boundary(self):
        # haircut 40 → 100 - 64 = 36.
        self.assertAlmostEqual(A()._score(40.0), 36.0, places=4)

    def test_score_clamps_at_zero(self):
        # haircut 62.5 → 100 - 100 = 0.
        self.assertAlmostEqual(A()._score(62.5), 0.0, places=4)

    def test_score_clamps_above(self):
        self.assertAlmostEqual(A()._score(100.0), 0.0, places=4)

    def test_score_clamps_negative_haircut(self):
        self.assertAlmostEqual(A()._score(-5.0), 100.0, places=4)

    def test_score_monotonic(self):
        prev = 101.0
        for h in (0.0, 2.0, 5.0, 15.0, 30.0, 40.0, 60.0):
            s = A()._score(h)
            self.assertLessEqual(s, prev)
            prev = s

    def test_score_in_range(self):
        for h in (0.0, 1.0, 15.0, 40.0, 62.5, 100.0):
            s = A()._score(h)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_score_finite(self):
        for h in (0.0, 40.0, 100.0):
            self.assertTrue(math.isfinite(A()._score(h)))

    def test_fully_realized_grade_a(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertEqual(r["grade"], "A")

    def test_mild_grade_b(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=2.2))
        self.assertEqual(r["grade"], "B")

    def test_severe_grade_f(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.0))
        self.assertEqual(r["grade"], "F")

    def test_realized_higher_than_severe(self):
        realized = A().analyze(make_pos(
            depositor_boost_multiplier=2.5))["score"]
        severe = A().analyze(make_pos(
            headline_apr_pct=20.0, max_boost_multiplier=2.5,
            depositor_boost_multiplier=1.0))["score"]
        self.assertGreater(realized, severe)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0,
                                 max_boost_multiplier=2.5,
                                 depositor_boost_multiplier=1.6))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_fully_realized_scores_high(self):
        r = A().analyze(make_pos(depositor_boost_multiplier=2.5))
        self.assertGreaterEqual(r["score"], 85.0)

    def test_score_idempotent(self):
        p = make_pos(headline_apr_pct=16.0, max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.6)
        self.assertEqual(A().analyze(p)["score"], A().analyze(p)["score"])

    def test_more_boost_higher_score(self):
        low = A().analyze(make_pos(depositor_boost_multiplier=1.2))["score"]
        high = A().analyze(make_pos(depositor_boost_multiplier=2.2))["score"]
        self.assertGreater(high, low)


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
        self.assertIsNone(res["aggregate"]["least_boost_gap_vault"])
        self.assertIsNone(res["aggregate"]["most_boost_gap_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["severe_count"], 0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([
            {"vault": "X", "headline_apr_pct": 0.0,
             "max_boost_multiplier": 2.5}])
        self.assertIsNone(res["aggregate"]["least_boost_gap_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_least_boost_gap_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="REALIZED", depositor_boost_multiplier=2.5),
            make_pos(vault="GAPPED", headline_apr_pct=20.0,
                     max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.0),
        ])
        self.assertEqual(res["aggregate"]["least_boost_gap_vault"], "REALIZED")

    def test_most_boost_gap_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="REALIZED", depositor_boost_multiplier=2.5),
            make_pos(vault="GAPPED", headline_apr_pct=20.0,
                     max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.0),
        ])
        self.assertEqual(res["aggregate"]["most_boost_gap_vault"], "GAPPED")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(depositor_boost_multiplier=2.5),
            make_pos(depositor_boost_multiplier=2.5),
        ])
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 99.0)

    def test_severe_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=20.0, max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.0),
            make_pos(headline_apr_pct=20.0, max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.0),
            make_pos(depositor_boost_multiplier=2.5),
        ])
        self.assertEqual(res["aggregate"]["severe_count"], 2)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        finite_check(self, res["aggregate"])

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", depositor_boost_multiplier=2.5),
            {"vault": "BAD", "headline_apr_pct": 0.0},
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["least_boost_gap_vault"], "GOOD")

    def test_insufficient_excluded_from_scored(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", depositor_boost_multiplier=2.5),
            {"vault": "BAD", "headline_apr_pct": 0.0},
        ])
        self.assertNotEqual(res["aggregate"]["most_boost_gap_vault"], "BAD")

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

    def test_log_floats_finite(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio(_demo_positions(), cfg=self._cfg(p),
                                  write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            finite_check(self, data)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_no_nan_in_output(self):
        for p in _demo_positions():
            finite_check(self, A().analyze(p))

    def test_string_inputs(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": "16",
                         "max_boost_multiplier": "2.5",
                         "depositor_boost_multiplier": "1.6"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_headline(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=1e9, max_boost_multiplier=2.5,
            depositor_boost_multiplier=1.0)))

    def test_large_max_boost(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=20.0, max_boost_multiplier=100.0,
            depositor_boost_multiplier=1.0)))

    def test_max_boost_one_no_gap(self):
        # max=1.0 → realization ratio 1.0 → FULLY_REALIZED.
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 max_boost_multiplier=1.0,
                                 depositor_boost_multiplier=1.0))
        finite_check(self, r)
        self.assertEqual(r["classification"], "FULLY_REALIZED")

    def test_idempotent_full(self):
        p = make_pos(headline_apr_pct=16.0, max_boost_multiplier=2.5,
                     depositor_boost_multiplier=1.6)
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_haircut_non_negative_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["boost_haircut_pct"] is not None:
                self.assertGreaterEqual(r["boost_haircut_pct"], 0.0)
                self.assertLessEqual(r["boost_haircut_pct"], 100.0)

    def test_realized_not_exceeding_headline_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["realized_apr_pct"] is not None:
                self.assertLessEqual(r["realized_apr_pct"],
                                     r["headline_apr_pct"] + 1e-6)

    def test_base_not_exceeding_headline_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["base_apr_pct"] is not None:
                self.assertLessEqual(r["base_apr_pct"],
                                     r["headline_apr_pct"] + 1e-6)

    def test_score_in_unit_range_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_realization_ratio_in_range_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["realization_ratio"] is not None:
                self.assertGreater(r["realization_ratio"], 0.0)
                self.assertLessEqual(r["realization_ratio"], 1.0)


# ── registry ──────────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    MOD = "defi_protocol_vault_boost_tier_headline_realization_analyzer"
    CLS = "DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer"

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
        for c in ("FULLY_REALIZED", "MILD_BOOST_GAP", "MODERATE_BOOST_GAP",
                  "SEVERE_BOOST_GAP", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_trust_and_avoid(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("TRUST_HEADLINE", recs)
        self.assertIn("AVOID_OR_LOCK_FOR_BOOST", recs)

    def test_demo_includes_use_base(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("USE_BASE_OR_BOOST_TIER", recs)

    def test_demo_includes_minor_discount(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("MINOR_DISCOUNT", recs)

    def test_demo_includes_unboosted(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("UNBOOSTED" in p["flags"] for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_includes_max_boost_required(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("MAX_BOOST_REQUIRED" in p["flags"]
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
        self.assertGreaterEqual(res["aggregate"]["severe_count"], 1)

    def test_demo_partial_boost_present(self):
        # CVX position uses a partial boost (2.2 < 2.5) → MILD.
        res = A().analyze_portfolio(_demo_positions())
        hit = any(p["classification"] == "MILD_BOOST_GAP"
                  for p in res["positions"])
        self.assertTrue(hit)


# ── forbidden imports ───────────────────────────────────────────────────────

class TestNoForbiddenImports(unittest.TestCase):
    def _source(self):
        path = os.path.join(
            ROOT, "spa_core", "analytics",
            "defi_protocol_vault_boost_tier_headline_realization_analyzer.py")
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
