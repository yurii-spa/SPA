"""
Tests for MP-1185: DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_apr_annualization_basis_risk_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_apr_annualization_basis_risk_analyzer import (  # noqa: E501
    DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_EXPECTED_BASIS_DAYS,
    ROBUST_RATIO,
    ADEQUATE_RATIO,
    SHORT_RATIO,
    PERIOD_VOLATILITY_CEILING,
    HIGH_PERIOD_VOLATILITY_PCT,
    HIGH_ANNUALIZATION_FACTOR,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=12.0,
    measurement_window_days=30.0,
    expected_basis_days=30.0,
    period_volatility_pct=0.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "measurement_window_days": measurement_window_days,
        "expected_basis_days": expected_basis_days,
        "period_volatility_pct": period_volatility_pct,
    }


def A():
    return DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer()


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

    def test_f_default_used_for_none(self):
        self.assertEqual(_f(None, 3.0), 3.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

    def test_f_string_number(self):
        self.assertEqual(_f("30"), 30.0)

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
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

    def test_safe_div_none_sentinel(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_zero_sentinel(self):
        self.assertEqual(_safe_div(5, 0, 0.0), 0.0)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertIn("log_path", cfg)

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"extra": 1})
        self.assertEqual(cfg["extra"], 1)

    def test_grade_from_score_bands(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(72), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundaries(self):
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(70), "B")
        self.assertEqual(_grade_from_score(55), "C")
        self.assertEqual(_grade_from_score(40), "D")
        self.assertEqual(_grade_from_score(39.9), "F")

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100.0), "A")

    def test_constants_sane(self):
        self.assertGreater(ROBUST_RATIO, ADEQUATE_RATIO)
        self.assertGreater(ADEQUATE_RATIO, SHORT_RATIO)
        self.assertGreater(DEFAULT_EXPECTED_BASIS_DAYS, 0)
        self.assertGreater(PERIOD_VOLATILITY_CEILING, 0)
        self.assertGreater(HIGH_PERIOD_VOLATILITY_PCT, 0)
        self.assertGreater(HIGH_ANNUALIZATION_FACTOR, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "measurement_window_days",
            "expected_basis_days", "period_volatility_pct", "basis_ratio",
            "annualization_factor", "is_sufficient_basis", "short_basis_frac",
            "volatility_adjusted_basis_risk", "confidence_pct",
            "high_annualization_factor", "high_period_volatility", "score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "MINOR_CONFIDENCE_DISCOUNT",
            "DISCOUNT_FOR_BASIS_RISK", "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "ROBUST_BASIS", "ADEQUATE_BASIS", "SHORT_BASIS",
            "VERY_SHORT_BASIS", "INSUFFICIENT_DATA",
        })

    def test_is_sufficient_basis_is_bool(self):
        self.assertIsInstance(self.r["is_sufficient_basis"], bool)

    def test_high_annualization_factor_is_bool(self):
        self.assertIsInstance(self.r["high_annualization_factor"], bool)

    def test_high_period_volatility_is_bool(self):
        self.assertIsInstance(self.r["high_period_volatility"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_window_zero_insufficient(self):
        r = A().analyze(make_pos(measurement_window_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_window_negative_insufficient(self):
        r = A().analyze(make_pos(measurement_window_days=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_basis_ratio(self):
        # 18 / 30 = 0.6
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["basis_ratio"], 0.6, places=4)

    def test_basis_ratio_robust(self):
        # 30 / 30 = 1.0
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["basis_ratio"], 1.0, places=4)

    def test_basis_ratio_above_one(self):
        # 90 / 30 = 3.0
        r = A().analyze(make_pos(measurement_window_days=90.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["basis_ratio"], 3.0, places=4)

    def test_annualization_factor(self):
        # 365 / 30 ≈ 12.1667
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertAlmostEqual(r["annualization_factor"],
                               round(365.0 / 30.0, 4), places=4)

    def test_annualization_factor_one_day(self):
        # 365 / 1 = 365
        r = A().analyze(make_pos(measurement_window_days=1.0))
        self.assertAlmostEqual(r["annualization_factor"], 365.0, places=4)

    def test_annualization_factor_ninety_days(self):
        # 365 / 90 ≈ 4.0556
        r = A().analyze(make_pos(measurement_window_days=90.0))
        self.assertAlmostEqual(r["annualization_factor"],
                               round(365.0 / 90.0, 4), places=4)

    def test_is_sufficient_basis_true(self):
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertTrue(r["is_sufficient_basis"])

    def test_is_sufficient_basis_boundary(self):
        # ratio exactly 1.0 → sufficient
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertTrue(r["is_sufficient_basis"])

    def test_is_sufficient_basis_false(self):
        r = A().analyze(make_pos(measurement_window_days=10.0,
                                 expected_basis_days=30.0))
        self.assertFalse(r["is_sufficient_basis"])

    def test_short_basis_frac(self):
        # ratio 0.6 → short_frac 0.4
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["short_basis_frac"], 0.4, places=4)

    def test_short_basis_frac_zero_when_robust(self):
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["short_basis_frac"], 0.0, places=4)

    def test_short_basis_frac_clamped_when_above_one(self):
        # ratio 3.0 → short_frac clamped to 0
        r = A().analyze(make_pos(measurement_window_days=90.0,
                                 expected_basis_days=30.0))
        self.assertAlmostEqual(r["short_basis_frac"], 0.0, places=4)

    def test_volatility_adjusted_basis_risk_no_vol(self):
        # short_frac 0.4, no vol → 0.4 * 1 = 0.4
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=0.0))
        self.assertAlmostEqual(r["volatility_adjusted_basis_risk"], 0.4,
                               places=4)

    def test_volatility_adjusted_basis_risk_full_vol(self):
        # short_frac 0.4, vol 20 (full) → 0.4 * 2 = 0.8
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=PERIOD_VOLATILITY_CEILING))
        self.assertAlmostEqual(r["volatility_adjusted_basis_risk"], 0.8,
                               places=4)

    def test_volatility_adjusted_basis_risk_half_vol(self):
        # short_frac 0.4, vol 10 → factor 0.5 → 0.4 * 1.5 = 0.6
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=10.0))
        self.assertAlmostEqual(r["volatility_adjusted_basis_risk"], 0.6,
                               places=4)

    def test_expected_basis_default_when_zero(self):
        r = A().analyze(make_pos(expected_basis_days=0.0))
        self.assertAlmostEqual(r["expected_basis_days"],
                               DEFAULT_EXPECTED_BASIS_DAYS)

    def test_expected_basis_default_when_negative(self):
        r = A().analyze(make_pos(expected_basis_days=-12.0))
        self.assertAlmostEqual(r["expected_basis_days"],
                               DEFAULT_EXPECTED_BASIS_DAYS)

    def test_expected_basis_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0})
        self.assertAlmostEqual(r["expected_basis_days"],
                               DEFAULT_EXPECTED_BASIS_DAYS)

    def test_period_vol_negative_clamped(self):
        r = A().analyze(make_pos(period_volatility_pct=-8.0))
        self.assertAlmostEqual(r["period_volatility_pct"], 0.0)

    def test_high_annualization_factor_true(self):
        # window 1 → factor 365 >= 52
        r = A().analyze(make_pos(measurement_window_days=1.0))
        self.assertTrue(r["high_annualization_factor"])

    def test_high_annualization_factor_boundary(self):
        # 365/7 ≈ 52.14 >= 52
        r = A().analyze(make_pos(measurement_window_days=7.0))
        self.assertTrue(r["high_annualization_factor"])

    def test_high_annualization_factor_false(self):
        # window 30 → factor ~12 < 52
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertFalse(r["high_annualization_factor"])

    def test_high_period_volatility_true(self):
        r = A().analyze(make_pos(period_volatility_pct=18.0))
        self.assertTrue(r["high_period_volatility"])

    def test_high_period_volatility_boundary(self):
        r = A().analyze(make_pos(
            period_volatility_pct=HIGH_PERIOD_VOLATILITY_PCT))
        self.assertTrue(r["high_period_volatility"])

    def test_high_period_volatility_false(self):
        r = A().analyze(make_pos(period_volatility_pct=2.0))
        self.assertFalse(r["high_period_volatility"])

    def test_confidence_mirrors_score(self):
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 period_volatility_pct=5.0))
        self.assertAlmostEqual(r["confidence_pct"], r["score"], places=1)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=12.3333,
                                 measurement_window_days=17.3333,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=3.5555))
        for k in ("headline_apr_pct", "measurement_window_days",
                  "expected_basis_days", "period_volatility_pct",
                  "basis_ratio", "annualization_factor", "short_basis_frac",
                  "volatility_adjusted_basis_risk"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_robust(self):
        # ratio 1.0
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "ROBUST_BASIS")

    def test_robust_above_one(self):
        # ratio 3.0
        r = A().analyze(make_pos(measurement_window_days=90.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "ROBUST_BASIS")

    def test_adequate(self):
        # ratio 0.6
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "ADEQUATE_BASIS")

    def test_adequate_boundary(self):
        # ratio exactly 0.5
        r = A().analyze(make_pos(measurement_window_days=15.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "ADEQUATE_BASIS")

    def test_short(self):
        # ratio 0.3
        r = A().analyze(make_pos(measurement_window_days=9.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "SHORT_BASIS")

    def test_short_boundary(self):
        # ratio exactly 0.2
        r = A().analyze(make_pos(measurement_window_days=6.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "SHORT_BASIS")

    def test_very_short(self):
        # ratio 0.1
        r = A().analyze(make_pos(measurement_window_days=3.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "VERY_SHORT_BASIS")

    def test_robust_boundary_exactly_one(self):
        # ratio exactly 1.0 → ROBUST
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["classification"], "ROBUST_BASIS")

    def test_just_below_robust(self):
        # ratio 0.99 → ADEQUATE
        r = A().analyze(make_pos(measurement_window_days=99.0,
                                 expected_basis_days=100.0))
        self.assertEqual(r["classification"], "ADEQUATE_BASIS")

    def test_just_below_adequate(self):
        # ratio 0.49 → SHORT
        r = A().analyze(make_pos(measurement_window_days=49.0,
                                 expected_basis_days=100.0))
        self.assertEqual(r["classification"], "SHORT_BASIS")

    def test_just_below_short(self):
        # ratio 0.19 → VERY_SHORT
        r = A().analyze(make_pos(measurement_window_days=19.0,
                                 expected_basis_days=100.0))
        self.assertEqual(r["classification"], "VERY_SHORT_BASIS")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_window(self):
        r = A().analyze(make_pos(measurement_window_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(measurement_window_days=30.0),
                    make_pos(measurement_window_days=18.0),
                    make_pos(measurement_window_days=9.0),
                    make_pos(measurement_window_days=3.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(measurement_window_days=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "ROBUST_BASIS", "ADEQUATE_BASIS", "SHORT_BASIS",
                "VERY_SHORT_BASIS", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_robust(self):
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_minor_discount_adequate(self):
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0))
        self.assertEqual(r["recommendation"], "MINOR_CONFIDENCE_DISCOUNT")

    def test_discount_short(self):
        r = A().analyze(make_pos(measurement_window_days=9.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=1.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_FOR_BASIS_RISK")

    def test_avoid_very_short(self):
        r = A().analyze(make_pos(measurement_window_days=3.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_short_high_vol_override(self):
        # SHORT basis but high vol → AVOID override
        r = A().analyze(make_pos(measurement_window_days=9.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_very_short_high_vol_override(self):
        r = A().analyze(make_pos(measurement_window_days=3.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_high_vol_robust_no_override(self):
        # high vol but ROBUST → no override, trust headline
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_high_vol_adequate_no_override(self):
        # high vol but only ADEQUATE → no override
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "MINOR_CONFIDENCE_DISCOUNT")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_robust_flag(self):
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertIn("ROBUST_BASIS", r["flags"])

    def test_adequate_flag(self):
        r = A().analyze(make_pos(measurement_window_days=18.0))
        self.assertIn("ADEQUATE_BASIS", r["flags"])

    def test_short_class_flag(self):
        r = A().analyze(make_pos(measurement_window_days=9.0))
        self.assertIn("SHORT_BASIS", r["flags"])

    def test_very_short_flag(self):
        r = A().analyze(make_pos(measurement_window_days=3.0))
        self.assertIn("VERY_SHORT_BASIS", r["flags"])

    def test_short_basis_flag_on_very_short(self):
        # VERY_SHORT class also raises the SHORT_BASIS flag
        r = A().analyze(make_pos(measurement_window_days=3.0))
        self.assertIn("SHORT_BASIS", r["flags"])

    def test_short_basis_flag_absent_robust(self):
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertNotIn("SHORT_BASIS", r["flags"])

    def test_short_basis_flag_absent_adequate(self):
        r = A().analyze(make_pos(measurement_window_days=18.0))
        self.assertNotIn("SHORT_BASIS", r["flags"])

    def test_high_annualization_factor_flag(self):
        r = A().analyze(make_pos(measurement_window_days=1.0))
        self.assertIn("HIGH_ANNUALIZATION_FACTOR", r["flags"])

    def test_high_annualization_factor_flag_absent(self):
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertNotIn("HIGH_ANNUALIZATION_FACTOR", r["flags"])

    def test_high_period_volatility_flag(self):
        r = A().analyze(make_pos(period_volatility_pct=18.0))
        self.assertIn("HIGH_PERIOD_VOLATILITY", r["flags"])

    def test_high_period_volatility_flag_boundary(self):
        r = A().analyze(make_pos(
            period_volatility_pct=HIGH_PERIOD_VOLATILITY_PCT))
        self.assertIn("HIGH_PERIOD_VOLATILITY", r["flags"])

    def test_high_period_volatility_flag_absent(self):
        r = A().analyze(make_pos(period_volatility_pct=2.0))
        self.assertNotIn("HIGH_PERIOD_VOLATILITY", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(measurement_window_days=30.0))
        self.assertIn("ROBUST_BASIS", r["flags"])
        self.assertNotIn("VERY_SHORT_BASIS", r["flags"])

    def test_very_short_and_high_factor_flags_together(self):
        r = A().analyze(make_pos(measurement_window_days=1.0,
                                 period_volatility_pct=18.0))
        self.assertIn("VERY_SHORT_BASIS", r["flags"])
        self.assertIn("SHORT_BASIS", r["flags"])
        self.assertIn("HIGH_ANNUALIZATION_FACTOR", r["flags"])
        self.assertIn("HIGH_PERIOD_VOLATILITY", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_no_window(self):
        r = A().analyze(make_pos(measurement_window_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_metrics_none(self):
        r = A().analyze({})
        self.assertIsNone(r["basis_ratio"])
        self.assertIsNone(r["annualization_factor"])
        self.assertIsNone(r["short_basis_frac"])
        self.assertIsNone(r["volatility_adjusted_basis_risk"])
        self.assertIsNone(r["confidence_pct"])

    def test_insufficient_bools_false(self):
        r = A().analyze({})
        self.assertFalse(r["is_sufficient_basis"])
        self.assertFalse(r["high_annualization_factor"])
        self.assertFalse(r["high_period_volatility"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "measurement_window_days",
                  "period_volatility_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_headline_and_window(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 measurement_window_days=30.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_robust_no_vol_full_score(self):
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_robust_no_vol_full_score_above_one(self):
        r = A().analyze(make_pos(measurement_window_days=90.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_longer_basis_scores_higher(self):
        long_b = A().analyze(make_pos(measurement_window_days=27.0))
        short_b = A().analyze(make_pos(measurement_window_days=3.0))
        self.assertGreater(long_b["score"], short_b["score"])

    def test_known_score_no_vol(self):
        # ratio 0.6, no vol:
        # basis 70*0.6=42; vol_comp 30*(1-0)=30 → total 72
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 72.0, places=2)

    def test_known_score_with_vol(self):
        # ratio 0.6, vol 20 (full): short_frac 0.4
        # basis 42; vol_comp 30*(1 - 1.0*0.4)=30*0.6=18 → total 60
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=PERIOD_VOLATILITY_CEILING))
        self.assertAlmostEqual(r["score"], 60.0, places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(measurement_window_days=0.001,
                                 expected_basis_days=1e6,
                                 period_volatility_pct=1e6))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9,
                                 measurement_window_days=1e9,
                                 expected_basis_days=1.0,
                                 period_volatility_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(measurement_window_days=30.0),
                    make_pos(measurement_window_days=9.0),
                    make_pos(measurement_window_days=1.0,
                             period_volatility_pct=18.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(measurement_window_days=30.0),
                    make_pos(measurement_window_days=1.0,
                             period_volatility_pct=18.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_vol_lower_score_when_short(self):
        low_vol = A().analyze(make_pos(measurement_window_days=9.0,
                                       period_volatility_pct=1.0))
        high_vol = A().analyze(make_pos(measurement_window_days=9.0,
                                        period_volatility_pct=18.0))
        self.assertGreater(low_vol["score"], high_vol["score"])

    def test_robust_vol_does_not_reduce_below_basis(self):
        # ratio >= 1 → short_frac 0 → vol penalty 0 → still 100
        r = A().analyze(make_pos(measurement_window_days=30.0,
                                 expected_basis_days=30.0,
                                 period_volatility_pct=18.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_confidence_matches_score_value(self):
        r = A().analyze(make_pos(measurement_window_days=18.0,
                                 period_volatility_pct=5.0))
        self.assertAlmostEqual(r["confidence_pct"], r["score"], places=1)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Robust", measurement_window_days=30.0),
            make_pos(vault="VeryShort", measurement_window_days=1.0,
                     period_volatility_pct=18.0),
            make_pos(vault="Mid", measurement_window_days=18.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_robust_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_robust_vault"]],
                         max(scores.values()))

    def test_least_robust_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_robust_vault"]],
                         min(scores.values()))

    def test_most_robust_token(self):
        self.assertEqual(self.res["aggregate"]["most_robust_vault"], "Robust")

    def test_least_robust_token(self):
        self.assertEqual(self.res["aggregate"]["least_robust_vault"],
                         "VeryShort")

    def test_very_short_basis_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["very_short_basis_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_very_short_basis_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", measurement_window_days=3.0),
            make_pos(vault="B", measurement_window_days=2.0),
            make_pos(vault="C", measurement_window_days=30.0),
        ])
        self.assertEqual(res["aggregate"]["very_short_basis_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_robust_vault"])
        self.assertIsNone(res["aggregate"]["least_robust_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(measurement_window_days=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_robust_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["very_short_basis_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_robust_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_robust_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))


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
                         measurement_window_days=1e9, expected_basis_days=1.0,
                         period_volatility_pct=1e9),
                make_pos(vault="ins", headline_apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_has_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos()],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("aggregate", data[0])

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)

    def test_no_write_analyze_does_not_create_production_log(self):
        before = os.path.exists(LOG_PATH)
        A().analyze_portfolio(_demo_positions())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": "12",
            "measurement_window_days": "18",
            "expected_basis_days": "30",
            "period_volatility_pct": "3.0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(measurement_window_days=1.0, period_volatility_pct=18.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(measurement_window_days=1.0,
                             period_volatility_pct=18.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(measurement_window_days=0.0),
                    make_pos(expected_basis_days=0.0),
                    make_pos(headline_apr_pct=1e9,
                             measurement_window_days=1e9,
                             expected_basis_days=1.0,
                             period_volatility_pct=1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(measurement_window_days=-1e9,
                             period_volatility_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12,
                                 measurement_window_days=1e9,
                                 expected_basis_days=1.0,
                                 period_volatility_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(measurement_window_days=10.0,
                                 period_volatility_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_tiny_window_high_factor(self):
        r = A().analyze(make_pos(measurement_window_days=0.5))
        self.assertTrue(r["high_annualization_factor"])
        finite_check(self, r)

    def test_none_inputs_no_crash(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0,
                         "measurement_window_days": 30.0,
                         "expected_basis_days": None,
                         "period_volatility_pct": None})
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_window_insufficient(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0,
                         "measurement_window_days": None})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 6)

    def test_demo_runs_through_portfolio(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        self.assertIn("aggregate", res)

    def test_demo_json_serializable(self):
        res = A().analyze_portfolio(_demo_positions())
        json.dumps(res)

    def test_demo_no_inf_nan(self):
        res = A().analyze_portfolio(_demo_positions())
        raw = json.dumps(res)
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)

    def test_demo_has_varied_classifications(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertGreater(len(classes), 1)

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_robust_and_very_short(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("ROBUST_BASIS", classes)
        self.assertIn("VERY_SHORT_BASIS", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("ROBUST_BASIS", "ADEQUATE_BASIS", "SHORT_BASIS",
                  "VERY_SHORT_BASIS", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_HEADLINE", recs)

    def test_demo_includes_high_annualization_factor(self):
        res = A().analyze_portfolio(_demo_positions())
        haf = any("HIGH_ANNUALIZATION_FACTOR" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(haf)

    def test_demo_includes_high_period_volatility(self):
        res = A().analyze_portfolio(_demo_positions())
        hv = any("HIGH_PERIOD_VOLATILITY" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(hv)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
