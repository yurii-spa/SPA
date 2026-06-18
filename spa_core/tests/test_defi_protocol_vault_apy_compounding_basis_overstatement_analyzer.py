"""
Tests for MP-1188: DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_apy_compounding_basis_overstatement_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_apy_compounding_basis_overstatement_analyzer import (
    DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _eff_apy,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_ADVERTISED_COMPOUNDS,
    DEFAULT_ACTUAL_COMPOUNDS,
    MAX_COMPOUNDS,
    HONEST_GAP_RATIO,
    MINOR_GAP_RATIO,
    MODERATE_GAP_RATIO,
    GAP_CEILING_RATIO,
    SHORTFALL_WEIGHT,
    GAP_WEIGHT,
    SHORTFALL_RATIO_FLOOR,
    LARGE_HEADLINE_GAP_PCT,
    LOG_PATH,
    LOG_CAP,
)
from spa_core.analytics import _module_registry as REG


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apy_pct=5.1267,
    base_apr_pct=5.0,
    advertised_compounds_per_year=365.0,
    actual_compounds_per_year=365.0,
):
    return {
        "vault": vault,
        "headline_apy_pct": headline_apy_pct,
        "base_apr_pct": base_apr_pct,
        "advertised_compounds_per_year": advertised_compounds_per_year,
        "actual_compounds_per_year": actual_compounds_per_year,
    }


def A():
    return DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer()


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

    def test_safe_div_normal(self):
        self.assertEqual(_safe_div(10.0, 2.0, None), 5.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertEqual(_safe_div(10.0, -1.0, 0.0), 0.0)

    def test_safe_div_sentinel_value(self):
        self.assertEqual(_safe_div(1.0, 0.0, -1.0), -1.0)

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


# ── _eff_apy tests ────────────────────────────────────────────────────────────

class TestEffApy(unittest.TestCase):
    def test_n_one_equals_apr(self):
        self.assertAlmostEqual(_eff_apy(10.0, 1.0), 10.0, places=6)

    def test_daily_above_simple(self):
        self.assertGreater(_eff_apy(10.0, 365.0), 10.0)

    def test_more_compounds_more_apy(self):
        self.assertGreater(_eff_apy(20.0, 365.0), _eff_apy(20.0, 52.0))
        self.assertGreater(_eff_apy(20.0, 52.0), _eff_apy(20.0, 12.0))

    def test_known_value_5pct_daily(self):
        self.assertAlmostEqual(_eff_apy(5.0, 365.0), 5.1267, places=3)

    def test_zero_apr(self):
        self.assertAlmostEqual(_eff_apy(0.0, 365.0), 0.0, places=6)

    def test_n_clamped_to_one(self):
        # n < 1 → treated as 1 → equals simple APR.
        self.assertAlmostEqual(_eff_apy(10.0, 0.5), 10.0, places=6)

    def test_n_zero_treated_as_one(self):
        self.assertAlmostEqual(_eff_apy(10.0, 0.0), 10.0, places=6)

    def test_finite_large_apr(self):
        self.assertTrue(math.isfinite(_eff_apy(1000.0, 365.0)))

    def test_finite_huge_compounds(self):
        self.assertTrue(math.isfinite(_eff_apy(10.0, 1e6)))

    def test_negative_apr_handled(self):
        self.assertTrue(math.isfinite(_eff_apy(-50.0, 365.0)))

    def test_result_finite_extreme(self):
        self.assertTrue(math.isfinite(_eff_apy(1e9, 1e9)))


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_default_advertised(self):
        self.assertEqual(DEFAULT_ADVERTISED_COMPOUNDS, 365.0)

    def test_default_actual(self):
        self.assertEqual(DEFAULT_ACTUAL_COMPOUNDS, 52.0)

    def test_max_compounds(self):
        self.assertGreater(MAX_COMPOUNDS, 365.0)

    def test_gap_ordering(self):
        self.assertLess(HONEST_GAP_RATIO, MINOR_GAP_RATIO)
        self.assertLess(MINOR_GAP_RATIO, MODERATE_GAP_RATIO)

    def test_gap_thresholds_positive(self):
        for v in (HONEST_GAP_RATIO, MINOR_GAP_RATIO, MODERATE_GAP_RATIO):
            self.assertGreater(v, 0.0)

    def test_ceiling_above_moderate(self):
        self.assertGreaterEqual(GAP_CEILING_RATIO, MODERATE_GAP_RATIO)

    def test_weights_sum_100(self):
        self.assertAlmostEqual(SHORTFALL_WEIGHT + GAP_WEIGHT, 100.0, places=6)

    def test_shortfall_floor(self):
        self.assertEqual(SHORTFALL_RATIO_FLOOR, 1.0)

    def test_large_gap_positive(self):
        self.assertGreater(LARGE_HEADLINE_GAP_PCT, 0.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_apy_compounding_basis_overstatement_log.json",
                      LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apy_pct", self.r)

    def test_has_base_apr(self):
        self.assertIn("base_apr_pct", self.r)

    def test_has_advertised_compounds(self):
        self.assertIn("advertised_compounds_per_year", self.r)

    def test_has_actual_compounds(self):
        self.assertIn("actual_compounds_per_year", self.r)

    def test_has_advertised_eff(self):
        self.assertIn("advertised_effective_apy_pct", self.r)

    def test_has_achievable_eff(self):
        self.assertIn("achievable_effective_apy_pct", self.r)

    def test_has_overstatement(self):
        self.assertIn("overstatement_pct", self.r)

    def test_has_headline_gap(self):
        self.assertIn("headline_gap_pct", self.r)

    def test_has_relative_gap(self):
        self.assertIn("relative_headline_gap", self.r)

    def test_has_shortfall_ratio(self):
        self.assertIn("compounding_shortfall_ratio", self.r)

    def test_has_shortfall_flag(self):
        self.assertIn("compounding_shortfall", self.r)

    def test_has_large_gap_flag(self):
        self.assertIn("large_headline_gap", self.r)

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
        r = A().analyze({"token": "TKN", "headline_apy_pct": 5.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apy_pct": 5.0, "base_apr_pct": 5.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_advertised_eff_matches_eff_apy(self):
        r = A().analyze(make_pos(base_apr_pct=10.0,
                                 advertised_compounds_per_year=365.0))
        self.assertAlmostEqual(r["advertised_effective_apy_pct"],
                               _eff_apy(10.0, 365.0), places=3)

    def test_achievable_eff_matches_eff_apy(self):
        r = A().analyze(make_pos(base_apr_pct=10.0,
                                 actual_compounds_per_year=12.0))
        self.assertAlmostEqual(r["achievable_effective_apy_pct"],
                               _eff_apy(10.0, 12.0), places=3)

    def test_overstatement_nonneg(self):
        r = A().analyze(make_pos(base_apr_pct=40.0,
                                 advertised_compounds_per_year=365.0,
                                 actual_compounds_per_year=1.0))
        self.assertGreaterEqual(r["overstatement_pct"], 0.0)

    def test_overstatement_positive_when_sparse(self):
        r = A().analyze(make_pos(base_apr_pct=40.0,
                                 advertised_compounds_per_year=365.0,
                                 actual_compounds_per_year=1.0))
        self.assertGreater(r["overstatement_pct"], 0.0)

    def test_overstatement_zero_when_equal(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=52.0,
                                 actual_compounds_per_year=52.0))
        self.assertAlmostEqual(r["overstatement_pct"], 0.0, places=4)

    def test_headline_gap_nonneg(self):
        r = A().analyze(make_pos(headline_apy_pct=5.1267, base_apr_pct=5.0,
                                 actual_compounds_per_year=1.0))
        self.assertGreaterEqual(r["headline_gap_pct"], 0.0)

    def test_headline_gap_zero_when_headline_below_achievable(self):
        r = A().analyze(make_pos(headline_apy_pct=4.0, base_apr_pct=5.0,
                                 actual_compounds_per_year=365.0))
        self.assertAlmostEqual(r["headline_gap_pct"], 0.0, places=4)

    def test_shortfall_ratio_one_when_equal(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=100.0,
                                 actual_compounds_per_year=100.0))
        self.assertAlmostEqual(r["compounding_shortfall_ratio"], 1.0, places=4)

    def test_shortfall_ratio_half(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=100.0,
                                 actual_compounds_per_year=50.0))
        self.assertAlmostEqual(r["compounding_shortfall_ratio"], 0.5, places=4)

    def test_shortfall_ratio_clamped_to_one(self):
        # actual richer than advertised → still clamped at 1.0.
        r = A().analyze(make_pos(advertised_compounds_per_year=52.0,
                                 actual_compounds_per_year=365.0))
        self.assertLessEqual(r["compounding_shortfall_ratio"], 1.0)

    def test_relative_gap_nonneg(self):
        r = A().analyze(make_pos(base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertGreaterEqual(r["relative_headline_gap"], 0.0)

    def test_advertised_default_when_zero(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=0.0))
        self.assertEqual(r["advertised_compounds_per_year"],
                         DEFAULT_ADVERTISED_COMPOUNDS)

    def test_advertised_default_when_negative(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=-5.0))
        self.assertEqual(r["advertised_compounds_per_year"],
                         DEFAULT_ADVERTISED_COMPOUNDS)

    def test_actual_default_when_zero(self):
        r = A().analyze(make_pos(actual_compounds_per_year=0.0))
        self.assertEqual(r["actual_compounds_per_year"],
                         DEFAULT_ACTUAL_COMPOUNDS)

    def test_actual_default_when_negative(self):
        r = A().analyze(make_pos(actual_compounds_per_year=-3.0))
        self.assertEqual(r["actual_compounds_per_year"],
                         DEFAULT_ACTUAL_COMPOUNDS)

    def test_advertised_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["advertised_compounds_per_year"],
                         DEFAULT_ADVERTISED_COMPOUNDS)

    def test_actual_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["actual_compounds_per_year"],
                         DEFAULT_ACTUAL_COMPOUNDS)

    def test_compounds_clamped_to_max(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=1e9,
                                 actual_compounds_per_year=1e9))
        self.assertLessEqual(r["advertised_compounds_per_year"], MAX_COMPOUNDS)
        self.assertLessEqual(r["actual_compounds_per_year"], MAX_COMPOUNDS)

    def test_compounding_shortfall_true(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=365.0,
                                 actual_compounds_per_year=52.0))
        self.assertTrue(r["compounding_shortfall"])

    def test_compounding_shortfall_false(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=52.0,
                                 actual_compounds_per_year=52.0))
        self.assertFalse(r["compounding_shortfall"])

    def test_large_headline_gap_true(self):
        r = A().analyze(make_pos(headline_apy_pct=34.97, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertTrue(r["large_headline_gap"])

    def test_large_headline_gap_false(self):
        r = A().analyze(make_pos(headline_apy_pct=5.1267, base_apr_pct=5.0,
                                 actual_compounds_per_year=365.0))
        self.assertFalse(r["large_headline_gap"])

    def test_finite_all_metrics(self):
        r = A().analyze(make_pos(base_apr_pct=80.0,
                                 actual_compounds_per_year=1.0))
        finite_check(self, r)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_honest(self):
        r = A().analyze(make_pos(headline_apy_pct=5.1267, base_apr_pct=5.0,
                                 actual_compounds_per_year=365.0))
        self.assertEqual(r["classification"], "HONEST_BASIS")

    def test_minor(self):
        r = A().analyze(make_pos(headline_apy_pct=5.1267, base_apr_pct=5.0,
                                 actual_compounds_per_year=1.0))
        self.assertEqual(r["classification"], "MINOR_OVERSTATEMENT")

    def test_moderate(self):
        r = A().analyze(make_pos(headline_apy_pct=16.1798, base_apr_pct=15.0,
                                 actual_compounds_per_year=1.0))
        self.assertEqual(r["classification"], "MODERATE_OVERSTATEMENT")

    def test_severe(self):
        r = A().analyze(make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertEqual(r["classification"], "SEVERE_OVERSTATEMENT")

    def test_classify_boundary_honest(self):
        self.assertEqual(A()._classify(HONEST_GAP_RATIO), "HONEST_BASIS")

    def test_classify_boundary_minor(self):
        self.assertEqual(A()._classify(MINOR_GAP_RATIO), "MINOR_OVERSTATEMENT")

    def test_classify_boundary_moderate(self):
        self.assertEqual(A()._classify(MODERATE_GAP_RATIO),
                         "MODERATE_OVERSTATEMENT")

    def test_classify_above_moderate(self):
        self.assertEqual(A()._classify(MODERATE_GAP_RATIO + 0.01),
                         "SEVERE_OVERSTATEMENT")

    def test_classify_just_above_honest(self):
        self.assertEqual(A()._classify(HONEST_GAP_RATIO + 0.001),
                         "MINOR_OVERSTATEMENT")

    def test_classify_just_above_minor(self):
        self.assertEqual(A()._classify(MINOR_GAP_RATIO + 0.001),
                         "MODERATE_OVERSTATEMENT")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "HONEST_BASIS")

    def test_classify_huge(self):
        self.assertEqual(A()._classify(10.0), "SEVERE_OVERSTATEMENT")

    def test_classify_negative_clamped(self):
        self.assertEqual(A()._classify(-1.0), "HONEST_BASIS")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_honest(self):
        self.assertEqual(A()._recommend("HONEST_BASIS"), "TRUST_HEADLINE")

    def test_minor(self):
        self.assertEqual(A()._recommend("MINOR_OVERSTATEMENT"),
                         "MINOR_DISCOUNT")

    def test_moderate(self):
        self.assertEqual(A()._recommend("MODERATE_OVERSTATEMENT"),
                         "DISCOUNT_TO_ACHIEVABLE")

    def test_severe(self):
        self.assertEqual(A()._recommend("SEVERE_OVERSTATEMENT"),
                         "USE_ACHIEVABLE_BASIS")

    def test_honest_via_analyze(self):
        r = A().analyze(make_pos(actual_compounds_per_year=365.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_severe_via_analyze(self):
        r = A().analyze(make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertEqual(r["recommendation"], "USE_ACHIEVABLE_BASIS")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_honest_flag(self):
        r = A().analyze(make_pos(actual_compounds_per_year=365.0))
        self.assertIn("HONEST_BASIS", r["flags"])

    def test_minor_flag(self):
        r = A().analyze(make_pos(headline_apy_pct=5.1267, base_apr_pct=5.0,
                                 actual_compounds_per_year=1.0))
        self.assertIn("MINOR_OVERSTATEMENT", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apy_pct=16.1798, base_apr_pct=15.0,
                                 actual_compounds_per_year=1.0))
        self.assertIn("MODERATE_OVERSTATEMENT", r["flags"])

    def test_severe_flag(self):
        r = A().analyze(make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertIn("SEVERE_OVERSTATEMENT", r["flags"])

    def test_compounding_shortfall_flag(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=365.0,
                                 actual_compounds_per_year=52.0))
        self.assertIn("COMPOUNDING_SHORTFALL", r["flags"])

    def test_no_shortfall_flag_when_equal(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=52.0,
                                 actual_compounds_per_year=52.0))
        self.assertNotIn("COMPOUNDING_SHORTFALL", r["flags"])

    def test_large_gap_flag(self):
        r = A().analyze(make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertIn("LARGE_HEADLINE_GAP", r["flags"])

    def test_no_large_gap_flag_when_small(self):
        r = A().analyze(make_pos(actual_compounds_per_year=365.0))
        self.assertNotIn("LARGE_HEADLINE_GAP", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                                 actual_compounds_per_year=1.0))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": -5.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X", "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": None,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": float("nan"),
                         "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": float("inf"),
                         "base_apr_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_base_apr(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0,
                         "base_apr_pct": 0.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_base_apr(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0,
                         "base_apr_pct": -3.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_base_apr(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_base_apr(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 5.0,
                         "base_apr_pct": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertIsNone(r["advertised_effective_apy_pct"])
        self.assertIsNone(r["achievable_effective_apy_pct"])
        self.assertIsNone(r["overstatement_pct"])
        self.assertIsNone(r["headline_gap_pct"])
        self.assertIsNone(r["relative_headline_gap"])
        self.assertIsNone(r["compounding_shortfall_ratio"])

    def test_recommendation(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze({"vault": "ZZZ", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                         "base_apr_pct": 5.0})
        json.dumps(r)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_nan_in_insufficient(self):
        finite_check(self, A().analyze({"vault": "X", "headline_apy_pct": 0.0,
                                        "base_apr_pct": 5.0}))


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_when_honest(self):
        # ratio 1.0 (honest cadence) + zero gap → 100.
        self.assertAlmostEqual(A()._score(1.0, 0.0), 100.0, places=4)

    def test_score_zero_when_worst(self):
        # ratio 0 + gap at/above ceiling → 0.
        self.assertAlmostEqual(A()._score(0.0, GAP_CEILING_RATIO), 0.0,
                               places=4)

    def test_score_shortfall_component(self):
        # ratio 0.5, zero gap → 30 (half of 60) + 40 = 70.
        self.assertAlmostEqual(A()._score(0.5, 0.0), 70.0, places=4)

    def test_score_gap_component(self):
        # ratio 1.0, gap at half ceiling → 60 + 20 = 80.
        self.assertAlmostEqual(A()._score(1.0, GAP_CEILING_RATIO / 2.0), 80.0,
                               places=4)

    def test_score_monotonic_in_ratio(self):
        prev = -1.0
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            s = A()._score(ratio, 0.1)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_score_monotonic_in_gap(self):
        prev = 101.0
        for gap in (0.0, 0.05, 0.1, 0.2, 0.4):
            s = A()._score(1.0, gap)
            self.assertLessEqual(s, prev)
            prev = s

    def test_score_clamps_above_ceiling_gap(self):
        self.assertAlmostEqual(A()._score(1.0, GAP_CEILING_RATIO * 5), 60.0,
                               places=4)

    def test_score_clamps_negative_gap(self):
        self.assertAlmostEqual(A()._score(1.0, -1.0), 100.0, places=4)

    def test_score_in_range(self):
        for ratio in (0.0, 0.3, 0.7, 1.0):
            for gap in (0.0, 0.1, 0.3, 0.5):
                s = A()._score(ratio, gap)
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)

    def test_score_idempotent(self):
        p = make_pos(actual_compounds_per_year=12.0)
        self.assertEqual(A().analyze(p)["score"], A().analyze(p)["score"])

    def test_score_finite(self):
        for ratio in (0.0, 0.5, 1.0):
            for gap in (0.0, 0.25, 0.5):
                self.assertTrue(math.isfinite(A()._score(ratio, gap)))

    def test_honest_higher_than_severe(self):
        honest = A().analyze(make_pos(actual_compounds_per_year=365.0))["score"]
        severe = A().analyze(make_pos(headline_apy_pct=34.9692,
                                      base_apr_pct=30.0,
                                      actual_compounds_per_year=1.0))["score"]
        self.assertGreater(honest, severe)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(actual_compounds_per_year=365.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_honest_scores_high(self):
        r = A().analyze(make_pos(actual_compounds_per_year=365.0))
        self.assertGreaterEqual(r["score"], 85.0)


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
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertIsNone(res["aggregate"]["most_overstated_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["severe_overstatement_count"], 0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([
            {"vault": "X", "headline_apy_pct": 0.0, "base_apr_pct": 5.0}])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_most_honest_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="HONEST", actual_compounds_per_year=365.0),
            make_pos(vault="OVER", headline_apy_pct=34.9692, base_apr_pct=30.0,
                     actual_compounds_per_year=1.0),
        ])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "HONEST")

    def test_most_overstated_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="HONEST", actual_compounds_per_year=365.0),
            make_pos(vault="OVER", headline_apy_pct=34.9692, base_apr_pct=30.0,
                     actual_compounds_per_year=1.0),
        ])
        self.assertEqual(res["aggregate"]["most_overstated_vault"], "OVER")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(actual_compounds_per_year=365.0),
            make_pos(actual_compounds_per_year=365.0),
        ])
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 99.0)

    def test_severe_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                     actual_compounds_per_year=1.0),
            make_pos(headline_apy_pct=34.9692, base_apr_pct=30.0,
                     actual_compounds_per_year=1.0),
            make_pos(actual_compounds_per_year=365.0),
        ])
        self.assertEqual(res["aggregate"]["severe_overstatement_count"], 2)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        finite_check(self, res["aggregate"])

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", actual_compounds_per_year=365.0),
            {"vault": "BAD", "headline_apy_pct": 0.0, "base_apr_pct": 5.0},
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["most_honest_vault"], "GOOD")

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


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_no_nan_in_output(self):
        for p in _demo_positions():
            finite_check(self, A().analyze(p))

    def test_string_inputs(self):
        r = A().analyze({"vault": "X", "headline_apy_pct": "5.1267",
                         "base_apr_pct": "5",
                         "advertised_compounds_per_year": "365",
                         "actual_compounds_per_year": "365"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_base_apr(self):
        finite_check(self, A().analyze(make_pos(base_apr_pct=1e9,
                                                actual_compounds_per_year=1.0)))

    def test_extreme_compounds(self):
        finite_check(self, A().analyze(make_pos(
            advertised_compounds_per_year=1e12,
            actual_compounds_per_year=1e12)))

    def test_nan_compounds_defaults(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=float("nan"),
                                 actual_compounds_per_year=float("nan")))
        self.assertEqual(r["advertised_compounds_per_year"],
                         DEFAULT_ADVERTISED_COMPOUNDS)
        self.assertEqual(r["actual_compounds_per_year"],
                         DEFAULT_ACTUAL_COMPOUNDS)

    def test_inf_compounds_defaults(self):
        r = A().analyze(make_pos(advertised_compounds_per_year=float("inf"),
                                 actual_compounds_per_year=float("inf")))
        finite_check(self, r)

    def test_idempotent_full(self):
        p = make_pos(headline_apy_pct=16.1798, base_apr_pct=15.0,
                     actual_compounds_per_year=1.0)
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_overstatement_non_negative_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["overstatement_pct"] is not None:
                self.assertGreaterEqual(r["overstatement_pct"], 0.0)

    def test_bool_compounds_treated_as_number(self):
        # _f(True) → 1.0; should not raise and stays finite.
        finite_check(self, A().analyze(make_pos(
            actual_compounds_per_year=True)))


# ── registry ──────────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    MOD = "defi_protocol_vault_apy_compounding_basis_overstatement_analyzer"
    CLS = "DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer"

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

    def test_demo_has_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("HONEST_BASIS", "MINOR_OVERSTATEMENT",
                  "MODERATE_OVERSTATEMENT", "SEVERE_OVERSTATEMENT",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_trust_and_use_achievable(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("TRUST_HEADLINE", recs)
        self.assertIn("USE_ACHIEVABLE_BASIS", recs)

    def test_demo_includes_shortfall(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("COMPOUNDING_SHORTFALL" in p["flags"]
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


if __name__ == "__main__":
    unittest.main()
