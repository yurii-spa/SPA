"""
Tests for MP-1189: DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_apr_lookback_window_selection_bias_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_apr_lookback_window_selection_bias_analyzer import (
    DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _is_number,
    _is_window_key,
    _clean_windows,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_WINDOWS,
    HOTTEST_MATCH_TOLERANCE_PCT,
    NEUTRAL_BIAS_PCT,
    MILD_BIAS_PCT,
    MODERATE_BIAS_PCT,
    BIAS_CEILING_PCT,
    AGREEMENT_WEIGHT,
    HOTTEST_WEIGHT,
    MATERIAL_BASELINE_GAP_PCT,
    WIDE_WINDOW_SPREAD_PCT,
    LOG_PATH,
    LOG_CAP,
)
from spa_core.analytics import _module_registry as REG


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=9.0,
    window_aprs=None,
):
    if window_aprs is None:
        window_aprs = {7: 9.0, 30: 9.0, 90: 9.0}
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "window_aprs": window_aprs,
    }


def A():
    return DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer()


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


# ── _is_number / _is_window_key tests ──────────────────────────────────────────

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

    def test_list_rejected(self):
        self.assertFalse(_is_number([1]))


class TestIsWindowKey(unittest.TestCase):
    def test_positive_int(self):
        self.assertTrue(_is_window_key(7))

    def test_zero_rejected(self):
        self.assertFalse(_is_window_key(0))

    def test_negative_rejected(self):
        self.assertFalse(_is_window_key(-7))

    def test_bool_rejected(self):
        self.assertFalse(_is_window_key(True))

    def test_positive_float(self):
        self.assertTrue(_is_window_key(30.0))

    def test_string_int(self):
        self.assertTrue(_is_window_key("90"))

    def test_string_non_int(self):
        self.assertFalse(_is_window_key("abc"))

    def test_none_rejected(self):
        self.assertFalse(_is_window_key(None))

    def test_nan_key_rejected(self):
        self.assertFalse(_is_window_key(float("nan")))


class TestCleanWindows(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_clean_windows({7: 9.0, 30: 10.0}),
                         {7: 9.0, 30: 10.0})

    def test_drops_none_value(self):
        self.assertEqual(_clean_windows({7: None, 30: 10.0}), {30: 10.0})

    def test_drops_bool_value(self):
        self.assertEqual(_clean_windows({7: True, 30: 10.0}), {30: 10.0})

    def test_drops_negative_value(self):
        self.assertEqual(_clean_windows({7: -5.0, 30: 10.0}), {30: 10.0})

    def test_drops_string_value(self):
        self.assertEqual(_clean_windows({7: "x", 30: 10.0}), {30: 10.0})

    def test_drops_nan_value(self):
        self.assertEqual(_clean_windows({7: float("nan"), 30: 10.0}),
                         {30: 10.0})

    def test_drops_inf_value(self):
        self.assertEqual(_clean_windows({7: float("inf"), 30: 10.0}),
                         {30: 10.0})

    def test_drops_non_positive_key(self):
        self.assertEqual(_clean_windows({0: 9.0, -3: 8.0, 30: 10.0}),
                         {30: 10.0})

    def test_drops_bool_key(self):
        out = _clean_windows({True: 9.0, 30: 10.0})
        self.assertNotIn(True, out)

    def test_string_key_coerced(self):
        self.assertEqual(_clean_windows({"7": 9.0}), {7: 9.0})

    def test_not_dict(self):
        self.assertEqual(_clean_windows(None), {})
        self.assertEqual(_clean_windows([1, 2]), {})

    def test_empty(self):
        self.assertEqual(_clean_windows({}), {})

    def test_zero_value_kept(self):
        # A 0% APR window is valid (non-negative).
        self.assertEqual(_clean_windows({7: 0.0, 30: 10.0}),
                         {7: 0.0, 30: 10.0})


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_min_windows(self):
        self.assertEqual(MIN_WINDOWS, 2)

    def test_tolerance_positive(self):
        self.assertGreater(HOTTEST_MATCH_TOLERANCE_PCT, 0.0)

    def test_bias_ordering(self):
        self.assertLess(NEUTRAL_BIAS_PCT, MILD_BIAS_PCT)
        self.assertLess(MILD_BIAS_PCT, MODERATE_BIAS_PCT)

    def test_bias_thresholds_positive(self):
        for v in (NEUTRAL_BIAS_PCT, MILD_BIAS_PCT, MODERATE_BIAS_PCT):
            self.assertGreater(v, 0.0)

    def test_ceiling_above_moderate(self):
        self.assertGreaterEqual(BIAS_CEILING_PCT, MODERATE_BIAS_PCT)

    def test_weights_sum_100(self):
        self.assertAlmostEqual(AGREEMENT_WEIGHT + HOTTEST_WEIGHT, 100.0,
                               places=6)

    def test_material_gap(self):
        self.assertGreater(MATERIAL_BASELINE_GAP_PCT, 0.0)

    def test_wide_spread(self):
        self.assertGreater(WIDE_WINDOW_SPREAD_PCT, 0.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_apr_lookback_window_selection_bias_log.json",
                      LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_window_count(self):
        self.assertIn("window_count", self.r)

    def test_has_baseline_days(self):
        self.assertIn("baseline_window_days", self.r)

    def test_has_shortest_days(self):
        self.assertIn("shortest_window_days", self.r)

    def test_has_baseline_apr(self):
        self.assertIn("baseline_apr_pct", self.r)

    def test_has_shortest_apr(self):
        self.assertIn("shortest_window_apr_pct", self.r)

    def test_has_max_apr(self):
        self.assertIn("max_window_apr_pct", self.r)

    def test_has_min_apr(self):
        self.assertIn("min_window_apr_pct", self.r)

    def test_has_spread(self):
        self.assertIn("window_spread_pct", self.r)

    def test_has_headline_vs_baseline(self):
        self.assertIn("headline_vs_baseline_pct", self.r)

    def test_has_selection_bias_ratio(self):
        self.assertIn("selection_bias_ratio", self.r)

    def test_has_matches_hottest(self):
        self.assertIn("headline_matches_hottest", self.r)

    def test_has_materially_lower(self):
        self.assertIn("baseline_materially_lower", self.r)

    def test_has_wide_spread_flag(self):
        self.assertIn("wide_window_spread", self.r)

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
        r = A().analyze({"token": "TKN", "headline_apr_pct": 9.0,
                         "window_aprs": {7: 9.0, 30: 9.0}})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 9.0,
                         "window_aprs": {7: 9.0, 30: 9.0}})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_baseline_is_longest_window(self):
        r = A().analyze(make_pos(window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertEqual(r["baseline_window_days"], 90)
        self.assertAlmostEqual(r["baseline_apr_pct"], 9.0, places=4)

    def test_shortest_is_smallest_window(self):
        r = A().analyze(make_pos(window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertEqual(r["shortest_window_days"], 7)
        self.assertAlmostEqual(r["shortest_window_apr_pct"], 13.0, places=4)

    def test_window_count(self):
        r = A().analyze(make_pos(window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertEqual(r["window_count"], 3)

    def test_max_min(self):
        r = A().analyze(make_pos(window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertAlmostEqual(r["max_window_apr_pct"], 13.0, places=4)
        self.assertAlmostEqual(r["min_window_apr_pct"], 9.0, places=4)

    def test_spread(self):
        r = A().analyze(make_pos(window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertAlmostEqual(r["window_spread_pct"], 4.0, places=4)

    def test_spread_zero_when_flat(self):
        r = A().analyze(make_pos(window_aprs={7: 9.0, 30: 9.0, 90: 9.0}))
        self.assertAlmostEqual(r["window_spread_pct"], 0.0, places=4)

    def test_headline_vs_baseline_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 30: 9.0, 90: 9.0}))
        self.assertAlmostEqual(r["headline_vs_baseline_pct"], 0.0, places=4)

    def test_headline_vs_baseline_positive(self):
        # headline 18 vs baseline(90d) 9 → 100% above.
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 window_aprs={7: 18.0, 90: 9.0}))
        self.assertAlmostEqual(r["headline_vs_baseline_pct"], 100.0, places=2)

    def test_headline_below_baseline_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0,
                                 window_aprs={7: 12.0, 90: 9.0}))
        self.assertAlmostEqual(r["headline_vs_baseline_pct"], 0.0, places=4)

    def test_matches_hottest_true(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0,
                                 window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertTrue(r["headline_matches_hottest"])

    def test_matches_hottest_false(self):
        r = A().analyze(make_pos(headline_apr_pct=9.5,
                                 window_aprs={7: 13.0, 30: 11.0, 90: 9.0}))
        self.assertFalse(r["headline_matches_hottest"])

    def test_matches_hottest_tolerance(self):
        # within tolerance of the hottest → counts as a match.
        r = A().analyze(make_pos(
            headline_apr_pct=13.0 - HOTTEST_MATCH_TOLERANCE_PCT / 2.0,
            window_aprs={7: 13.0, 90: 9.0}))
        self.assertTrue(r["headline_matches_hottest"])

    def test_selection_bias_ratio_one_at_hottest(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0,
                                 window_aprs={7: 13.0, 90: 9.0}))
        self.assertAlmostEqual(r["selection_bias_ratio"], 1.0, places=4)

    def test_selection_bias_ratio_zero_at_baseline(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 13.0, 90: 9.0}))
        self.assertAlmostEqual(r["selection_bias_ratio"], 0.0, places=4)

    def test_selection_bias_ratio_mid(self):
        # headline 11 between baseline 9 and hottest 13 → 0.5.
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 window_aprs={7: 13.0, 90: 9.0}))
        self.assertAlmostEqual(r["selection_bias_ratio"], 0.5, places=4)

    def test_selection_bias_ratio_zero_when_flat(self):
        # denom (max-baseline) == 0 → ratio 0.
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
        self.assertAlmostEqual(r["selection_bias_ratio"], 0.0, places=4)

    def test_materially_lower_true(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 90: 9.0}))
        self.assertTrue(r["baseline_materially_lower"])

    def test_materially_lower_false(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
        self.assertFalse(r["baseline_materially_lower"])

    def test_wide_spread_true(self):
        r = A().analyze(make_pos(window_aprs={7: 19.0, 90: 9.0}))
        self.assertTrue(r["wide_window_spread"])

    def test_wide_spread_false(self):
        r = A().analyze(make_pos(window_aprs={7: 9.2, 90: 9.0}))
        self.assertFalse(r["wide_window_spread"])

    def test_finite_all_metrics(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=19.0, window_aprs={7: 19.0, 30: 12.0, 90: 9.0})))

    def test_dirty_windows_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 window_aprs={7: 12.0, 30: None, 90: 9.0,
                                              -1: 5.0, 0: 4.0}))
        self.assertEqual(r["window_count"], 2)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_neutral(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.2, 30: 9.0, 90: 9.0}))
        self.assertEqual(r["classification"], "NEUTRAL_BASIS")

    def test_mild(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 window_aprs={7: 11.0, 30: 10.0, 90: 10.0}))
        self.assertEqual(r["classification"], "MILD_SELECTION")

    def test_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0,
                                 window_aprs={7: 13.0, 30: 11.0, 90: 10.0}))
        self.assertEqual(r["classification"], "MODERATE_SELECTION")

    def test_strong(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 30: 12.0, 90: 9.0}))
        self.assertEqual(r["classification"], "STRONG_SELECTION")

    def test_classify_boundary_neutral(self):
        self.assertEqual(A()._classify(NEUTRAL_BIAS_PCT), "NEUTRAL_BASIS")

    def test_classify_boundary_mild(self):
        self.assertEqual(A()._classify(MILD_BIAS_PCT), "MILD_SELECTION")

    def test_classify_boundary_moderate(self):
        self.assertEqual(A()._classify(MODERATE_BIAS_PCT), "MODERATE_SELECTION")

    def test_classify_above_moderate(self):
        self.assertEqual(A()._classify(MODERATE_BIAS_PCT + 0.01),
                         "STRONG_SELECTION")

    def test_classify_just_above_neutral(self):
        self.assertEqual(A()._classify(NEUTRAL_BIAS_PCT + 0.01),
                         "MILD_SELECTION")

    def test_classify_just_above_mild(self):
        self.assertEqual(A()._classify(MILD_BIAS_PCT + 0.01),
                         "MODERATE_SELECTION")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "NEUTRAL_BASIS")

    def test_classify_huge(self):
        self.assertEqual(A()._classify(1000.0), "STRONG_SELECTION")

    def test_classify_negative_clamped(self):
        self.assertEqual(A()._classify(-5.0), "NEUTRAL_BASIS")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA", False),
                         "VERIFY_DATA")

    def test_insufficient_windows(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_WINDOWS", False),
                         "VERIFY_DATA")

    def test_neutral(self):
        self.assertEqual(A()._recommend("NEUTRAL_BASIS", False),
                         "TRUST_HEADLINE")

    def test_mild(self):
        self.assertEqual(A()._recommend("MILD_SELECTION", False),
                         "MINOR_DISCOUNT")

    def test_moderate_not_hottest(self):
        self.assertEqual(A()._recommend("MODERATE_SELECTION", False),
                         "USE_LONGER_BASELINE")

    def test_strong_not_hottest(self):
        self.assertEqual(A()._recommend("STRONG_SELECTION", False),
                         "AVOID_OR_VERIFY")

    def test_moderate_hottest_override(self):
        self.assertEqual(A()._recommend("MODERATE_SELECTION", True),
                         "AVOID_OR_VERIFY")

    def test_strong_hottest_override(self):
        self.assertEqual(A()._recommend("STRONG_SELECTION", True),
                         "AVOID_OR_VERIFY")

    def test_neutral_hottest_no_override(self):
        # NEUTRAL at hottest (flat windows) should NOT be forced to AVOID.
        self.assertEqual(A()._recommend("NEUTRAL_BASIS", True),
                         "TRUST_HEADLINE")

    def test_mild_hottest_no_override(self):
        self.assertEqual(A()._recommend("MILD_SELECTION", True),
                         "MINOR_DISCOUNT")

    def test_neutral_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_strong_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 30: 12.0, 90: 9.0}))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_neutral_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
        self.assertIn("NEUTRAL_BASIS", r["flags"])

    def test_mild_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=11.0,
                                 window_aprs={7: 11.0, 30: 10.0, 90: 10.0}))
        self.assertIn("MILD_SELECTION", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0,
                                 window_aprs={7: 13.0, 30: 11.0, 90: 10.0}))
        self.assertIn("MODERATE_SELECTION", r["flags"])

    def test_strong_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 30: 12.0, 90: 9.0}))
        self.assertIn("STRONG_SELECTION", r["flags"])

    def test_hottest_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 90: 9.0}))
        self.assertIn("HEADLINE_AT_HOTTEST", r["flags"])

    def test_no_hottest_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=9.5,
                                 window_aprs={7: 13.0, 90: 9.0}))
        self.assertNotIn("HEADLINE_AT_HOTTEST", r["flags"])

    def test_wide_spread_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 90: 9.0}))
        self.assertIn("WIDE_WINDOW_SPREAD", r["flags"])

    def test_no_wide_spread_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.1, 90: 9.0}))
        self.assertNotIn("WIDE_WINDOW_SPREAD", r["flags"])

    def test_insufficient_data_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_windows_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {30: 9.0}})
        self.assertIn("INSUFFICIENT_WINDOWS", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos(headline_apr_pct=19.0,
                                 window_aprs={7: 19.0, 30: 12.0, 90: 9.0}))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))


# ── insufficient data / windows ───────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": -3.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X", "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf"),
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_one_window(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {30: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_zero_windows(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {}})
        self.assertEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_missing_windows(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_all_windows_dirty(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {7: None, 30: -5.0, -1: 9.0}})
        self.assertEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_one_valid_after_cleaning(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {7: 9.0, 30: None}})
        self.assertEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_insufficient_data_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["score"], 0.0)

    def test_insufficient_windows_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                         "window_aprs": {30: 9.0}})
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertIsNone(r["baseline_apr_pct"])
        self.assertIsNone(r["baseline_window_days"])
        self.assertIsNone(r["shortest_window_days"])
        self.assertIsNone(r["shortest_window_apr_pct"])
        self.assertIsNone(r["max_window_apr_pct"])
        self.assertIsNone(r["min_window_apr_pct"])
        self.assertIsNone(r["window_spread_pct"])
        self.assertIsNone(r["headline_vs_baseline_pct"])
        self.assertIsNone(r["selection_bias_ratio"])

    def test_recommendation(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze({"vault": "ZZZ", "headline_apr_pct": 0.0,
                         "window_aprs": {7: 9.0, 90: 9.0}})
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0})
        json.dumps(r)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_nan_in_insufficient(self):
        finite_check(self, A().analyze({"vault": "X", "headline_apr_pct": 9.0,
                                        "window_aprs": {30: 9.0}}))


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_when_aligned(self):
        # zero bias, not (hottest & materially-lower) → 100.
        self.assertAlmostEqual(A()._score(0.0, False, False), 100.0, places=4)

    def test_score_agreement_decays(self):
        # bias at half ceiling, no hottest penalty → 30 + 40 = 70.
        self.assertAlmostEqual(
            A()._score(BIAS_CEILING_PCT / 2.0, False, False), 70.0, places=4)

    def test_score_hottest_penalty(self):
        # zero bias but hottest & materially-lower → 60 + 0 = 60.
        self.assertAlmostEqual(A()._score(0.0, True, True), 60.0, places=4)

    def test_score_both_penalties(self):
        # bias at ceiling + hottest penalty → 0.
        self.assertAlmostEqual(
            A()._score(BIAS_CEILING_PCT, True, True), 0.0, places=4)

    def test_score_hottest_only_no_penalty_if_not_lower(self):
        # hottest but baseline NOT materially lower → full hottest weight.
        self.assertAlmostEqual(A()._score(0.0, True, False), 100.0, places=4)

    def test_score_monotonic_in_bias(self):
        prev = 101.0
        for b in (0.0, 10.0, 30.0, 60.0, 100.0):
            s = A()._score(b, False, False)
            self.assertLessEqual(s, prev)
            prev = s

    def test_score_clamps_above_ceiling(self):
        self.assertAlmostEqual(A()._score(BIAS_CEILING_PCT * 5, False, False),
                               40.0, places=4)

    def test_score_clamps_negative_bias(self):
        self.assertAlmostEqual(A()._score(-5.0, False, False), 100.0, places=4)

    def test_score_in_range(self):
        for b in (0.0, 20.0, 60.0, 200.0):
            for h in (True, False):
                for m in (True, False):
                    s = A()._score(b, h, m)
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_score_idempotent(self):
        p = make_pos(headline_apr_pct=13.0,
                     window_aprs={7: 13.0, 30: 11.0, 90: 10.0})
        self.assertEqual(A().analyze(p)["score"], A().analyze(p)["score"])

    def test_score_finite(self):
        for b in (0.0, 50.0, 100.0):
            self.assertTrue(math.isfinite(A()._score(b, True, True)))

    def test_neutral_higher_than_strong(self):
        neutral = A().analyze(make_pos(headline_apr_pct=9.0,
                                       window_aprs={7: 9.0, 90: 9.0}))["score"]
        strong = A().analyze(make_pos(
            headline_apr_pct=19.0,
            window_aprs={7: 19.0, 30: 12.0, 90: 9.0}))["score"]
        self.assertGreater(neutral, strong)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_neutral_scores_high(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0,
                                 window_aprs={7: 9.0, 90: 9.0}))
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
        self.assertIsNone(res["aggregate"]["least_biased_vault"])
        self.assertIsNone(res["aggregate"]["most_biased_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["strong_selection_count"], 0)

    def test_all_insufficient_data(self):
        res = A().analyze_portfolio([
            {"vault": "X", "headline_apr_pct": 0.0,
             "window_aprs": {7: 9.0, 90: 9.0}}])
        self.assertIsNone(res["aggregate"]["least_biased_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_all_insufficient_windows(self):
        res = A().analyze_portfolio([
            {"vault": "X", "headline_apr_pct": 9.0, "window_aprs": {30: 9.0}}])
        self.assertIsNone(res["aggregate"]["least_biased_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_least_biased_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="CLEAN", headline_apr_pct=9.0,
                     window_aprs={7: 9.0, 90: 9.0}),
            make_pos(vault="BIASED", headline_apr_pct=19.0,
                     window_aprs={7: 19.0, 30: 12.0, 90: 9.0}),
        ])
        self.assertEqual(res["aggregate"]["least_biased_vault"], "CLEAN")

    def test_most_biased_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="CLEAN", headline_apr_pct=9.0,
                     window_aprs={7: 9.0, 90: 9.0}),
            make_pos(vault="BIASED", headline_apr_pct=19.0,
                     window_aprs={7: 19.0, 30: 12.0, 90: 9.0}),
        ])
        self.assertEqual(res["aggregate"]["most_biased_vault"], "BIASED")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=9.0, window_aprs={7: 9.0, 90: 9.0}),
            make_pos(headline_apr_pct=9.0, window_aprs={7: 9.0, 90: 9.0}),
        ])
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 99.0)

    def test_strong_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=19.0,
                     window_aprs={7: 19.0, 30: 12.0, 90: 9.0}),
            make_pos(headline_apr_pct=19.0,
                     window_aprs={7: 19.0, 30: 12.0, 90: 9.0}),
            make_pos(headline_apr_pct=9.0, window_aprs={7: 9.0, 90: 9.0}),
        ])
        self.assertEqual(res["aggregate"]["strong_selection_count"], 2)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        finite_check(self, res["aggregate"])

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", headline_apr_pct=9.0,
                     window_aprs={7: 9.0, 90: 9.0}),
            {"vault": "BAD", "headline_apr_pct": 0.0},
            {"vault": "FEW", "headline_apr_pct": 9.0,
             "window_aprs": {30: 9.0}},
        ])
        self.assertEqual(res["aggregate"]["position_count"], 3)
        self.assertEqual(res["aggregate"]["least_biased_vault"], "GOOD")

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
        r = A().analyze({"vault": "X", "headline_apr_pct": "13",
                         "window_aprs": {"7": 13.0, "90": 9.0}})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertNotEqual(r["classification"], "INSUFFICIENT_WINDOWS")

    def test_extreme_headline(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=1e9, window_aprs={7: 1e9, 90: 9.0})))

    def test_tiny_baseline(self):
        finite_check(self, A().analyze(make_pos(
            headline_apr_pct=10.0, window_aprs={7: 10.0, 90: 0.0001})))

    def test_zero_baseline_safe(self):
        # baseline 0 → safe_div sentinel 0 → no crash.
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 window_aprs={7: 10.0, 90: 0.0}))
        finite_check(self, r)

    def test_idempotent_full(self):
        p = make_pos(headline_apr_pct=13.0,
                     window_aprs={7: 13.0, 30: 11.0, 90: 10.0})
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_spread_non_negative_demo(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["window_spread_pct"] is not None:
                self.assertGreaterEqual(r["window_spread_pct"], 0.0)

    def test_bias_ratio_in_unit_interval(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["selection_bias_ratio"] is not None:
                self.assertGreaterEqual(r["selection_bias_ratio"], 0.0)
                self.assertLessEqual(r["selection_bias_ratio"], 1.0)

    def test_unordered_window_keys(self):
        # keys provided out of order → baseline still the longest.
        r = A().analyze(make_pos(headline_apr_pct=13.0,
                                 window_aprs={90: 9.0, 7: 13.0, 30: 11.0}))
        self.assertEqual(r["baseline_window_days"], 90)


# ── registry ──────────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    MOD = "defi_protocol_vault_apr_lookback_window_selection_bias_analyzer"
    CLS = "DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer"

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

    def test_demo_has_insufficient_windows(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_WINDOWS", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NEUTRAL_BASIS", "MILD_SELECTION", "MODERATE_SELECTION",
                  "STRONG_SELECTION", "INSUFFICIENT_DATA",
                  "INSUFFICIENT_WINDOWS"):
            self.assertIn(c, classes)

    def test_demo_includes_trust_and_avoid(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("TRUST_HEADLINE", recs)
        self.assertIn("AVOID_OR_VERIFY", recs)

    def test_demo_includes_hottest(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("HEADLINE_AT_HOTTEST" in p["flags"]
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
