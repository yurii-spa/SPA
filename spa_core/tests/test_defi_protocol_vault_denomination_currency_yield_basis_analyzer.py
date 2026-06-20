"""
Tests for MP-1187: DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_denomination_currency_yield_basis_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_denomination_currency_yield_basis_analyzer import (
    DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HOLDING_HORIZON_DAYS,
    DAYS_PER_YEAR,
    WORST_CASE_SIGMA,
    TIGHT_BASIS_PCT,
    MILD_BASIS_PCT,
    WIDE_BASIS_PCT,
    LOOSE_BASIS_PCT,
    BASIS_GAP_CEILING_PCT,
    HIGH_VOL_PCT,
    MATERIAL_DRIFT_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=5.0,
    denomination_token="ETH",
    expected_annual_drift_pct=0.0,
    drift_volatility_pct=0.0,
    holding_horizon_days=30.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "denomination_token": denomination_token,
        "expected_annual_drift_pct": expected_annual_drift_pct,
        "drift_volatility_pct": drift_volatility_pct,
        "holding_horizon_days": holding_horizon_days,
    }


def A():
    return DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


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


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_default_horizon(self):
        self.assertEqual(DEFAULT_HOLDING_HORIZON_DAYS, 30.0)

    def test_days_per_year(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)

    def test_worst_case_sigma(self):
        self.assertGreater(WORST_CASE_SIGMA, 0.0)

    def test_basis_ordering(self):
        self.assertLess(TIGHT_BASIS_PCT, MILD_BASIS_PCT)
        self.assertLess(MILD_BASIS_PCT, WIDE_BASIS_PCT)
        self.assertLess(WIDE_BASIS_PCT, LOOSE_BASIS_PCT)

    def test_basis_thresholds_positive(self):
        for v in (TIGHT_BASIS_PCT, MILD_BASIS_PCT, WIDE_BASIS_PCT,
                  LOOSE_BASIS_PCT):
            self.assertGreater(v, 0.0)

    def test_ceiling_above_loose(self):
        self.assertGreaterEqual(BASIS_GAP_CEILING_PCT, LOOSE_BASIS_PCT)

    def test_high_vol(self):
        self.assertGreater(HIGH_VOL_PCT, 0.0)

    def test_material_drift(self):
        self.assertGreater(MATERIAL_DRIFT_PCT, 0.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_denomination_currency_yield_basis_log.json",
                      LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_denomination(self):
        self.assertIn("denomination_token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_expected_drift(self):
        self.assertIn("expected_annual_drift_pct", self.r)

    def test_has_volatility(self):
        self.assertIn("drift_volatility_pct", self.r)

    def test_has_horizon(self):
        self.assertIn("holding_horizon_days", self.r)

    def test_has_numeraire_apr(self):
        self.assertIn("numeraire_apr_pct", self.r)

    def test_has_numeraire_low(self):
        self.assertIn("numeraire_apr_low_pct", self.r)

    def test_has_numeraire_high(self):
        self.assertIn("numeraire_apr_high_pct", self.r)

    def test_has_horizon_drift(self):
        self.assertIn("horizon_expected_drift_pct", self.r)

    def test_has_horizon_swing(self):
        self.assertIn("horizon_swing_pct", self.r)

    def test_has_basis_gap(self):
        self.assertIn("horizon_basis_gap_pct", self.r)

    def test_has_high_volatility(self):
        self.assertIn("high_volatility", self.r)

    def test_has_material_drift(self):
        self.assertIn("material_drift", self.r)

    def test_has_adverse_drift(self):
        self.assertIn("adverse_drift", self.r)

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
        r = A().analyze({"token": "TKN", "headline_apr_pct": 5.0})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 5.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_denomination_value(self):
        self.assertEqual(self.r["denomination_token"], "ETH")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_numeraire_apr_adds_drift(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0,
                                 expected_annual_drift_pct=3.0))
        self.assertAlmostEqual(r["numeraire_apr_pct"], 8.0, places=4)

    def test_numeraire_apr_negative_drift(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0,
                                 expected_annual_drift_pct=-10.0))
        self.assertAlmostEqual(r["numeraire_apr_pct"], -5.0, places=4)

    def test_numeraire_band_symmetric(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=0.0,
                                 drift_volatility_pct=20.0))
        mid = r["numeraire_apr_pct"]
        self.assertAlmostEqual(r["numeraire_apr_high_pct"] - mid,
                               mid - r["numeraire_apr_low_pct"], places=4)

    def test_band_collapses_when_no_vol(self):
        r = A().analyze(make_pos(drift_volatility_pct=0.0))
        self.assertAlmostEqual(r["numeraire_apr_low_pct"],
                               r["numeraire_apr_pct"], places=4)
        self.assertAlmostEqual(r["numeraire_apr_high_pct"],
                               r["numeraire_apr_pct"], places=4)

    def test_basis_gap_zero_stable(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=0.0,
                                 drift_volatility_pct=0.0))
        self.assertAlmostEqual(r["horizon_basis_gap_pct"], 0.0, places=4)

    def test_basis_gap_grows_with_vol(self):
        low = A().analyze(make_pos(drift_volatility_pct=10.0))
        high = A().analyze(make_pos(drift_volatility_pct=50.0))
        self.assertGreater(high["horizon_basis_gap_pct"],
                           low["horizon_basis_gap_pct"])

    def test_basis_gap_grows_with_drift(self):
        low = A().analyze(make_pos(expected_annual_drift_pct=-2.0))
        high = A().analyze(make_pos(expected_annual_drift_pct=-30.0))
        self.assertGreater(high["horizon_basis_gap_pct"],
                           low["horizon_basis_gap_pct"])

    def test_horizon_swing_scales_sqrt_time(self):
        short = A().analyze(make_pos(drift_volatility_pct=40.0,
                                     holding_horizon_days=30.0))
        long = A().analyze(make_pos(drift_volatility_pct=40.0,
                                    holding_horizon_days=120.0))
        self.assertGreater(long["horizon_swing_pct"],
                           short["horizon_swing_pct"])

    def test_horizon_expected_drift_scaled(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=12.0,
                                 holding_horizon_days=DAYS_PER_YEAR))
        self.assertAlmostEqual(r["horizon_expected_drift_pct"], 12.0, places=2)

    def test_horizon_expected_drift_half_year(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=10.0,
                                 holding_horizon_days=182.5))
        self.assertAlmostEqual(r["horizon_expected_drift_pct"], 5.0, places=2)

    def test_vol_max0(self):
        r = A().analyze(make_pos(drift_volatility_pct=-30.0))
        self.assertEqual(r["drift_volatility_pct"], 0.0)

    def test_horizon_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 5.0})
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_zero(self):
        r = A().analyze(make_pos(holding_horizon_days=0.0))
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_negative(self):
        r = A().analyze(make_pos(holding_horizon_days=-5.0))
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_years_capped_at_one(self):
        # 5-year horizon → horizon_years capped at 1.0 → swing == annual.
        r = A().analyze(make_pos(drift_volatility_pct=20.0,
                                 holding_horizon_days=5 * 365.0))
        self.assertAlmostEqual(r["horizon_swing_pct"], 20.0, places=4)

    def test_high_volatility_flag_value(self):
        r = A().analyze(make_pos(drift_volatility_pct=60.0))
        self.assertTrue(r["high_volatility"])

    def test_high_volatility_false(self):
        r = A().analyze(make_pos(drift_volatility_pct=10.0))
        self.assertFalse(r["high_volatility"])

    def test_material_drift_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-40.0,
                                 holding_horizon_days=DAYS_PER_YEAR))
        self.assertTrue(r["material_drift"])

    def test_material_drift_false(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=0.5,
                                 holding_horizon_days=30.0))
        self.assertFalse(r["material_drift"])

    def test_adverse_drift_true(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-5.0))
        self.assertTrue(r["adverse_drift"])

    def test_adverse_drift_false(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=5.0))
        self.assertFalse(r["adverse_drift"])

    def test_denomination_default_unknown(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 5.0})
        self.assertEqual(r["denomination_token"], "UNKNOWN")

    def test_denomination_empty_unknown(self):
        r = A().analyze(make_pos(denomination_token=""))
        self.assertEqual(r["denomination_token"], "UNKNOWN")

    def test_finite_all_metrics(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-12.0,
                                 drift_volatility_pct=80.0))
        finite_check(self, r)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_tight(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=0.0,
                                 drift_volatility_pct=0.0))
        self.assertEqual(r["classification"], "TIGHT_BASIS")

    def test_mild(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=2.0,
                                 drift_volatility_pct=15.0,
                                 holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "MILD_BASIS")

    def test_wide(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-5.0,
                                 drift_volatility_pct=40.0,
                                 holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "WIDE_BASIS")

    def test_loose(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-8.0,
                                 drift_volatility_pct=45.0,
                                 holding_horizon_days=90.0))
        self.assertEqual(r["classification"], "LOOSE_BASIS")

    def test_decoupled(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-30.0,
                                 drift_volatility_pct=130.0,
                                 holding_horizon_days=365.0))
        self.assertEqual(r["classification"], "DECOUPLED_BASIS")

    def test_classify_boundary_tight(self):
        self.assertEqual(A()._classify(TIGHT_BASIS_PCT), "TIGHT_BASIS")

    def test_classify_boundary_mild(self):
        self.assertEqual(A()._classify(MILD_BASIS_PCT), "MILD_BASIS")

    def test_classify_boundary_wide(self):
        self.assertEqual(A()._classify(WIDE_BASIS_PCT), "WIDE_BASIS")

    def test_classify_boundary_loose(self):
        self.assertEqual(A()._classify(LOOSE_BASIS_PCT), "LOOSE_BASIS")

    def test_classify_above_loose(self):
        self.assertEqual(A()._classify(LOOSE_BASIS_PCT + 0.01),
                         "DECOUPLED_BASIS")

    def test_classify_just_above_tight(self):
        self.assertEqual(A()._classify(TIGHT_BASIS_PCT + 0.01), "MILD_BASIS")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "TIGHT_BASIS")

    def test_classify_huge(self):
        self.assertEqual(A()._classify(1000.0), "DECOUPLED_BASIS")

    def test_classify_negative_clamped(self):
        self.assertEqual(A()._classify(-5.0), "TIGHT_BASIS")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_tight(self):
        self.assertEqual(A()._recommend("TIGHT_BASIS"), "NO_ACTION")

    def test_mild(self):
        self.assertEqual(A()._recommend("MILD_BASIS"), "MONITOR")

    def test_wide(self):
        self.assertEqual(A()._recommend("WIDE_BASIS"), "ADJUST_FOR_DRIFT")

    def test_loose(self):
        self.assertEqual(A()._recommend("LOOSE_BASIS"), "HEDGE_DENOMINATION")

    def test_decoupled(self):
        self.assertEqual(A()._recommend("DECOUPLED_BASIS"),
                         "TREAT_AS_DIRECTIONAL")

    def test_tight_via_analyze(self):
        r = A().analyze(make_pos(drift_volatility_pct=0.0))
        self.assertEqual(r["recommendation"], "NO_ACTION")

    def test_decoupled_via_analyze(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-30.0,
                                 drift_volatility_pct=130.0,
                                 holding_horizon_days=365.0))
        self.assertEqual(r["recommendation"], "TREAT_AS_DIRECTIONAL")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_tight_flag(self):
        r = A().analyze(make_pos(drift_volatility_pct=0.0))
        self.assertIn("TIGHT_BASIS", r["flags"])

    def test_decoupled_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-30.0,
                                 drift_volatility_pct=130.0,
                                 holding_horizon_days=365.0))
        self.assertIn("DECOUPLED_BASIS", r["flags"])

    def test_high_vol_flag(self):
        r = A().analyze(make_pos(drift_volatility_pct=60.0))
        self.assertIn("HIGH_DENOMINATION_VOLATILITY", r["flags"])

    def test_material_drift_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-40.0,
                                 holding_horizon_days=DAYS_PER_YEAR))
        self.assertIn("MATERIAL_EXPECTED_DRIFT", r["flags"])

    def test_adverse_drift_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-5.0))
        self.assertIn("ADVERSE_EXPECTED_DRIFT", r["flags"])

    def test_no_adverse_when_positive(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=5.0))
        self.assertNotIn("ADVERSE_EXPECTED_DRIFT", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-40.0,
                                 drift_volatility_pct=80.0,
                                 holding_horizon_days=365.0))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))

    def test_insufficient_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_mild_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=2.0,
                                 drift_volatility_pct=15.0,
                                 holding_horizon_days=30.0))
        self.assertIn("MILD_BASIS", r["flags"])

    def test_wide_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-5.0,
                                 drift_volatility_pct=40.0,
                                 holding_horizon_days=30.0))
        self.assertIn("WIDE_BASIS", r["flags"])

    def test_loose_flag(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-8.0,
                                 drift_volatility_pct=45.0,
                                 holding_horizon_days=90.0))
        self.assertIn("LOOSE_BASIS", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_headline_is_valid(self):
        # A 0% token-APR is still a quotable basis (not insufficient).
        r = A().analyze(make_pos(headline_apr_pct=0.0, drift_volatility_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline_is_valid(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0,
                                 drift_volatility_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertIsNone(r["numeraire_apr_pct"])
        self.assertIsNone(r["numeraire_apr_low_pct"])
        self.assertIsNone(r["numeraire_apr_high_pct"])
        self.assertIsNone(r["horizon_expected_drift_pct"])
        self.assertIsNone(r["horizon_swing_pct"])
        self.assertIsNone(r["horizon_basis_gap_pct"])

    def test_recommendation(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze({"vault": "ZZZ", "headline_apr_pct": None})
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        json.dumps(r)


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_when_no_gap(self):
        self.assertAlmostEqual(A()._score(0.0), 100.0, places=4)

    def test_score_zero_at_ceiling(self):
        self.assertAlmostEqual(A()._score(BASIS_GAP_CEILING_PCT), 0.0, places=4)

    def test_score_half(self):
        self.assertAlmostEqual(A()._score(BASIS_GAP_CEILING_PCT / 2.0),
                               50.0, places=4)

    def test_score_monotonic_decreasing(self):
        prev = 101.0
        for g in (0.0, 5.0, 10.0, 25.0, 50.0):
            s = A()._score(g)
            self.assertLessEqual(s, prev)
            prev = s

    def test_score_clamps_above_ceiling(self):
        self.assertEqual(A()._score(BASIS_GAP_CEILING_PCT * 2), 0.0)

    def test_score_clamps_negative_gap(self):
        self.assertEqual(A()._score(-5.0), 100.0)

    def test_score_in_range(self):
        for g in (1.0, 7.0, 22.0, 49.0):
            s = A()._score(g)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_score_idempotent(self):
        p = make_pos(drift_volatility_pct=30.0)
        self.assertEqual(A().analyze(p)["score"], A().analyze(p)["score"])

    def test_score_finite(self):
        for g in (0.0, 25.0, 50.0):
            self.assertTrue(math.isfinite(A()._score(g)))

    def test_tight_higher_than_decoupled(self):
        tight = A().analyze(make_pos(drift_volatility_pct=0.0))["score"]
        dec = A().analyze(make_pos(expected_annual_drift_pct=-30.0,
                                   drift_volatility_pct=130.0,
                                   holding_horizon_days=365.0))["score"]
        self.assertGreater(tight, dec)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(drift_volatility_pct=0.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_stablecoin_scores_high(self):
        r = A().analyze(make_pos(denomination_token="USDC",
                                 expected_annual_drift_pct=0.0,
                                 drift_volatility_pct=0.5))
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
        self.assertIsNone(res["aggregate"]["tightest_basis_vault"])

    def test_all_insufficient(self):
        res = A().analyze_portfolio([{"vault": "X", "headline_apr_pct": None}])
        self.assertIsNone(res["aggregate"]["tightest_basis_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_tightest_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="STABLE", drift_volatility_pct=0.0),
            make_pos(vault="VOLATILE", expected_annual_drift_pct=-30.0,
                     drift_volatility_pct=130.0, holding_horizon_days=365.0),
        ])
        self.assertEqual(res["aggregate"]["tightest_basis_vault"], "STABLE")

    def test_loosest_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="STABLE", drift_volatility_pct=0.0),
            make_pos(vault="VOLATILE", expected_annual_drift_pct=-30.0,
                     drift_volatility_pct=130.0, holding_horizon_days=365.0),
        ])
        self.assertEqual(res["aggregate"]["loosest_basis_vault"], "VOLATILE")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(drift_volatility_pct=0.0),
            make_pos(drift_volatility_pct=0.0),
        ])
        self.assertAlmostEqual(res["aggregate"]["avg_score"], 100.0, places=2)

    def test_decoupled_count(self):
        res = A().analyze_portfolio([
            make_pos(expected_annual_drift_pct=-30.0, drift_volatility_pct=130.0,
                     holding_horizon_days=365.0),
            make_pos(expected_annual_drift_pct=-30.0, drift_volatility_pct=130.0,
                     holding_horizon_days=365.0),
            make_pos(drift_volatility_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["decoupled_count"], 2)

    def test_avg_basis_gap(self):
        res = A().analyze_portfolio([make_pos(drift_volatility_pct=0.0)])
        self.assertEqual(res["aggregate"]["avg_basis_gap_pct"], 0.0)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for v in res["aggregate"].values():
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v))

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", drift_volatility_pct=0.0),
            {"vault": "BAD", "headline_apr_pct": None},
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["tightest_basis_vault"], "GOOD")


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
            r = A().analyze(p)
            finite_check(self, r)

    def test_string_inputs(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": "5",
                         "denomination_token": "ETH",
                         "expected_annual_drift_pct": "-3",
                         "drift_volatility_pct": "20",
                         "holding_horizon_days": "30"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_drift(self):
        r = A().analyze(make_pos(expected_annual_drift_pct=-1e9,
                                 drift_volatility_pct=1e9))
        finite_check(self, r)

    def test_huge_horizon(self):
        r = A().analyze(make_pos(drift_volatility_pct=40.0,
                                 holding_horizon_days=1e9))
        finite_check(self, r)

    def test_nan_drift(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 5.0,
                         "expected_annual_drift_pct": float("nan"),
                         "drift_volatility_pct": 10.0})
        finite_check(self, r)

    def test_inf_vol(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 5.0,
                         "drift_volatility_pct": float("inf")})
        finite_check(self, r)

    def test_nan_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 5.0,
                         "drift_volatility_pct": 10.0,
                         "holding_horizon_days": float("nan")})
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_idempotent_full(self):
        p = make_pos(drift_volatility_pct=33.0)
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_basis_gap_non_negative(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["horizon_basis_gap_pct"] is not None:
                self.assertGreaterEqual(r["horizon_basis_gap_pct"], 0.0)

    def test_positive_drift_still_has_gap(self):
        # Even a favourable expected drift still widens the basis (uncertainty).
        r = A().analyze(make_pos(expected_annual_drift_pct=20.0,
                                 drift_volatility_pct=0.0,
                                 holding_horizon_days=DAYS_PER_YEAR))
        self.assertGreater(r["horizon_basis_gap_pct"], 0.0)


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
        for c in ("TIGHT_BASIS", "MILD_BASIS", "WIDE_BASIS", "LOOSE_BASIS",
                  "DECOUPLED_BASIS", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_no_action_and_directional(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("NO_ACTION", recs)
        self.assertIn("TREAT_AS_DIRECTIONAL", recs)

    def test_demo_includes_high_vol(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("HIGH_DENOMINATION_VOLATILITY" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_includes_adverse_drift(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("ADVERSE_EXPECTED_DRIFT" in p["flags"]
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


if __name__ == "__main__":
    unittest.main()
