"""
Tests for MP-1180: DeFiProtocolVaultAPRQuoteStalenessAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_apr_quote_staleness_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_apr_quote_staleness_analyzer import (
    DeFiProtocolVaultAPRQuoteStalenessAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_EXPECTED_REFRESH_HOURS,
    FRESH_RATIO,
    SLIGHTLY_STALE_RATIO,
    STALE_RATIO,
    STALENESS_CEILING,
    APR_VOLATILITY_CEILING,
    HIGH_APR_VOLATILITY_PCT,
    STALENESS_RATIO_CAP,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=12.0,
    quote_age_hours=6.0,
    expected_refresh_hours=24.0,
    apr_volatility_pct=1.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "quote_age_hours": quote_age_hours,
        "expected_refresh_hours": expected_refresh_hours,
        "apr_volatility_pct": apr_volatility_pct,
    }


def A():
    return DeFiProtocolVaultAPRQuoteStalenessAnalyzer()


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
        self.assertEqual(_f("24"), 24.0)

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
        self.assertLess(FRESH_RATIO, SLIGHTLY_STALE_RATIO)
        self.assertLess(SLIGHTLY_STALE_RATIO, STALE_RATIO)
        self.assertGreater(DEFAULT_EXPECTED_REFRESH_HOURS, 0)
        self.assertGreater(STALENESS_CEILING, 0)
        self.assertGreater(APR_VOLATILITY_CEILING, 0)
        self.assertGreater(HIGH_APR_VOLATILITY_PCT, 0)
        self.assertGreater(STALENESS_RATIO_CAP, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "quote_age_hours",
            "expected_refresh_hours", "apr_volatility_pct", "staleness_ratio",
            "is_fresh", "hours_overdue", "volatility_adjusted_staleness",
            "confidence_pct", "high_apr_volatility", "score", "classification",
            "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_QUOTE", "MINOR_STALENESS_DISCOUNT", "REFRESH_BEFORE_USE",
            "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
            "INSUFFICIENT_DATA",
        })

    def test_is_fresh_is_bool(self):
        self.assertIsInstance(self.r["is_fresh"], bool)

    def test_high_apr_volatility_is_bool(self):
        self.assertIsInstance(self.r["high_apr_volatility"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_staleness_ratio(self):
        # 12 / 24 = 0.5
        r = A().analyze(make_pos(quote_age_hours=12.0,
                                 expected_refresh_hours=24.0))
        self.assertAlmostEqual(r["staleness_ratio"], 0.5, places=4)

    def test_staleness_ratio_overdue(self):
        # 72 / 24 = 3.0
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 expected_refresh_hours=24.0))
        self.assertAlmostEqual(r["staleness_ratio"], 3.0, places=4)

    def test_staleness_ratio_capped(self):
        r = A().analyze(make_pos(quote_age_hours=1e9,
                                 expected_refresh_hours=1.0))
        self.assertAlmostEqual(r["staleness_ratio"], STALENESS_RATIO_CAP,
                               places=4)

    def test_quote_age_negative_clamped(self):
        r = A().analyze(make_pos(quote_age_hours=-5.0))
        self.assertAlmostEqual(r["quote_age_hours"], 0.0)

    def test_expected_refresh_default_when_zero(self):
        r = A().analyze(make_pos(expected_refresh_hours=0.0))
        self.assertAlmostEqual(r["expected_refresh_hours"],
                               DEFAULT_EXPECTED_REFRESH_HOURS)

    def test_expected_refresh_default_when_negative(self):
        r = A().analyze(make_pos(expected_refresh_hours=-12.0))
        self.assertAlmostEqual(r["expected_refresh_hours"],
                               DEFAULT_EXPECTED_REFRESH_HOURS)

    def test_expected_refresh_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0,
                         "quote_age_hours": 6.0})
        self.assertAlmostEqual(r["expected_refresh_hours"],
                               DEFAULT_EXPECTED_REFRESH_HOURS)

    def test_is_fresh_true(self):
        r = A().analyze(make_pos(quote_age_hours=12.0,
                                 expected_refresh_hours=24.0))
        self.assertTrue(r["is_fresh"])

    def test_is_fresh_boundary(self):
        # ratio exactly 1.0 → fresh
        r = A().analyze(make_pos(quote_age_hours=24.0,
                                 expected_refresh_hours=24.0))
        self.assertTrue(r["is_fresh"])

    def test_is_fresh_false(self):
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0))
        self.assertFalse(r["is_fresh"])

    def test_hours_overdue_positive(self):
        # 72 - 24 = 48
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 expected_refresh_hours=24.0))
        self.assertAlmostEqual(r["hours_overdue"], 48.0, places=4)

    def test_hours_overdue_zero_when_fresh(self):
        r = A().analyze(make_pos(quote_age_hours=6.0,
                                 expected_refresh_hours=24.0))
        self.assertAlmostEqual(r["hours_overdue"], 0.0, places=4)

    def test_hours_overdue_boundary(self):
        # exactly at refresh → 0 overdue
        r = A().analyze(make_pos(quote_age_hours=24.0,
                                 expected_refresh_hours=24.0))
        self.assertAlmostEqual(r["hours_overdue"], 0.0, places=4)

    def test_volatility_adjusted_staleness_no_vol(self):
        # ratio 2.0, no vol → 2.0 * 1.0 = 2.0
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=0.0))
        self.assertAlmostEqual(r["volatility_adjusted_staleness"], 2.0,
                               places=4)

    def test_volatility_adjusted_staleness_with_vol(self):
        # ratio 2.0, vol 20 (full ceiling) → factor 1.0 → 2.0*(1+1)=4.0
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=APR_VOLATILITY_CEILING))
        self.assertAlmostEqual(r["volatility_adjusted_staleness"], 4.0,
                               places=4)

    def test_volatility_adjusted_staleness_half_vol(self):
        # ratio 2.0, vol 10 → factor 0.5 → 2.0*1.5 = 3.0
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=10.0))
        self.assertAlmostEqual(r["volatility_adjusted_staleness"], 3.0,
                               places=4)

    def test_apr_volatility_negative_clamped(self):
        r = A().analyze(make_pos(apr_volatility_pct=-8.0))
        self.assertAlmostEqual(r["apr_volatility_pct"], 0.0)

    def test_confidence_equals_score_scale(self):
        r = A().analyze(make_pos())
        self.assertGreaterEqual(r["confidence_pct"], 0.0)
        self.assertLessEqual(r["confidence_pct"], 100.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=12.3333,
                                 quote_age_hours=33.3333,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=3.5555))
        for k in ("headline_apr_pct", "quote_age_hours",
                  "expected_refresh_hours", "apr_volatility_pct",
                  "staleness_ratio", "hours_overdue",
                  "volatility_adjusted_staleness"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_fresh(self):
        # ratio 0.25
        r = A().analyze(make_pos(quote_age_hours=6.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "FRESH")

    def test_slightly_stale(self):
        # ratio 1.5
        r = A().analyze(make_pos(quote_age_hours=36.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "SLIGHTLY_STALE")

    def test_stale(self):
        # ratio 3.0
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "STALE")

    def test_severely_stale(self):
        # ratio 5.0
        r = A().analyze(make_pos(quote_age_hours=120.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "SEVERELY_STALE")

    def test_fresh_boundary(self):
        # ratio exactly 1.0 → FRESH
        r = A().analyze(make_pos(quote_age_hours=24.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "FRESH")

    def test_slightly_stale_boundary(self):
        # ratio exactly 2.0 → SLIGHTLY_STALE
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "SLIGHTLY_STALE")

    def test_stale_boundary(self):
        # ratio exactly 4.0 → STALE
        r = A().analyze(make_pos(quote_age_hours=96.0,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "STALE")

    def test_above_stale_severely(self):
        # ratio 4.01 → SEVERELY_STALE
        r = A().analyze(make_pos(quote_age_hours=96.24,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "SEVERELY_STALE")

    def test_just_above_fresh(self):
        # ratio 1.01 → SLIGHTLY_STALE
        r = A().analyze(make_pos(quote_age_hours=24.24,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "SLIGHTLY_STALE")

    def test_just_above_slightly(self):
        # ratio 2.01 → STALE
        r = A().analyze(make_pos(quote_age_hours=48.24,
                                 expected_refresh_hours=24.0))
        self.assertEqual(r["classification"], "STALE")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(quote_age_hours=6.0),
                    make_pos(quote_age_hours=36.0),
                    make_pos(quote_age_hours=72.0),
                    make_pos(quote_age_hours=200.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_quote_fresh(self):
        r = A().analyze(make_pos(quote_age_hours=6.0))
        self.assertEqual(r["recommendation"], "TRUST_QUOTE")

    def test_minor_discount_slightly_stale(self):
        r = A().analyze(make_pos(quote_age_hours=36.0))
        self.assertEqual(r["recommendation"], "MINOR_STALENESS_DISCOUNT")

    def test_refresh_stale(self):
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 apr_volatility_pct=1.0))
        self.assertEqual(r["recommendation"], "REFRESH_BEFORE_USE")

    def test_avoid_severely_stale(self):
        r = A().analyze(make_pos(quote_age_hours=200.0,
                                 apr_volatility_pct=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_high_vol_stale_override(self):
        # STALE class but high APR volatility → AVOID override
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 apr_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_high_vol_severely_stale_override(self):
        r = A().analyze(make_pos(quote_age_hours=200.0,
                                 apr_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_high_vol_fresh_no_override(self):
        # high vol but FRESH → no override, trust quote
        r = A().analyze(make_pos(quote_age_hours=6.0,
                                 apr_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "TRUST_QUOTE")

    def test_high_vol_slightly_stale_no_override(self):
        # high vol but only SLIGHTLY_STALE → no override
        r = A().analyze(make_pos(quote_age_hours=36.0,
                                 apr_volatility_pct=18.0))
        self.assertEqual(r["recommendation"], "MINOR_STALENESS_DISCOUNT")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fresh_flag(self):
        r = A().analyze(make_pos(quote_age_hours=6.0))
        self.assertIn("FRESH", r["flags"])

    def test_slightly_stale_flag(self):
        r = A().analyze(make_pos(quote_age_hours=36.0))
        self.assertIn("SLIGHTLY_STALE", r["flags"])

    def test_stale_flag(self):
        r = A().analyze(make_pos(quote_age_hours=72.0))
        self.assertIn("STALE", r["flags"])

    def test_severely_stale_flag(self):
        r = A().analyze(make_pos(quote_age_hours=200.0))
        self.assertIn("SEVERELY_STALE", r["flags"])

    def test_overdue_flag(self):
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0))
        self.assertIn("OVERDUE", r["flags"])

    def test_overdue_flag_absent(self):
        r = A().analyze(make_pos(quote_age_hours=6.0,
                                 expected_refresh_hours=24.0))
        self.assertNotIn("OVERDUE", r["flags"])

    def test_overdue_flag_absent_at_boundary(self):
        r = A().analyze(make_pos(quote_age_hours=24.0,
                                 expected_refresh_hours=24.0))
        self.assertNotIn("OVERDUE", r["flags"])

    def test_high_apr_volatility_flag(self):
        r = A().analyze(make_pos(apr_volatility_pct=18.0))
        self.assertIn("HIGH_APR_VOLATILITY", r["flags"])

    def test_high_apr_volatility_flag_boundary(self):
        # exactly at threshold → flagged
        r = A().analyze(make_pos(apr_volatility_pct=HIGH_APR_VOLATILITY_PCT))
        self.assertIn("HIGH_APR_VOLATILITY", r["flags"])

    def test_high_apr_volatility_flag_absent(self):
        r = A().analyze(make_pos(apr_volatility_pct=2.0))
        self.assertNotIn("HIGH_APR_VOLATILITY", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(quote_age_hours=6.0))
        self.assertIn("FRESH", r["flags"])
        self.assertNotIn("SEVERELY_STALE", r["flags"])

    def test_stale_and_high_vol_flags_together(self):
        r = A().analyze(make_pos(quote_age_hours=72.0,
                                 apr_volatility_pct=18.0))
        self.assertIn("STALE", r["flags"])
        self.assertIn("HIGH_APR_VOLATILITY", r["flags"])
        self.assertIn("OVERDUE", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
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
        self.assertIsNone(r["staleness_ratio"])
        self.assertIsNone(r["hours_overdue"])
        self.assertIsNone(r["volatility_adjusted_staleness"])
        self.assertIsNone(r["confidence_pct"])

    def test_insufficient_is_fresh_false(self):
        r = A().analyze({})
        self.assertFalse(r["is_fresh"])
        self.assertFalse(r["high_apr_volatility"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "quote_age_hours",
                  "apr_volatility_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_fresher_scores_higher(self):
        fresh = A().analyze(make_pos(quote_age_hours=6.0))
        stale = A().analyze(make_pos(quote_age_hours=200.0))
        self.assertGreater(fresh["score"], stale["score"])

    def test_zero_age_full_score(self):
        r = A().analyze(make_pos(quote_age_hours=0.0,
                                 apr_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_zero_age_full_score_even_with_vol(self):
        # fresh & zero age short-circuits to 100 regardless of volatility
        r = A().analyze(make_pos(quote_age_hours=0.0,
                                 apr_volatility_pct=18.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_tiny_age_near_full(self):
        r = A().analyze(make_pos(quote_age_hours=0.5,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=0.0))
        self.assertGreater(r["score"], 95.0)

    def test_severely_stale_low_score(self):
        r = A().analyze(make_pos(quote_age_hours=1e6,
                                 expected_refresh_hours=1.0,
                                 apr_volatility_pct=18.0))
        self.assertLess(r["score"], 5.0)

    def test_known_score_no_vol(self):
        # ratio 2.0, no vol:
        # stale_frac = clamp(2/4)=0.5; freshness 70*0.5=35
        # vol_penalty 0 → vol_comp 30 → total 65
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=0.0))
        stale_frac = min(2.0 / STALENESS_CEILING, 1.0)
        expected = 70.0 * (1.0 - stale_frac) + 30.0
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_known_score_with_vol(self):
        # ratio 2.0, vol 20 (full):
        # stale_frac 0.5; freshness 35
        # vol_penalty 1.0*0.5=0.5; vol_comp 30-30*0.5=15 → total 50
        r = A().analyze(make_pos(quote_age_hours=48.0,
                                 expected_refresh_hours=24.0,
                                 apr_volatility_pct=APR_VOLATILITY_CEILING))
        stale_frac = min(2.0 / STALENESS_CEILING, 1.0)
        vol_penalty = 1.0 * stale_frac
        expected = 70.0 * (1.0 - stale_frac) + (30.0 - 30.0 * vol_penalty)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(quote_age_hours=1e9,
                                 expected_refresh_hours=1.0,
                                 apr_volatility_pct=1e6))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9,
                                 quote_age_hours=1e9,
                                 expected_refresh_hours=1.0,
                                 apr_volatility_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(quote_age_hours=6.0),
                    make_pos(quote_age_hours=72.0),
                    make_pos(quote_age_hours=200.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(quote_age_hours=6.0),
                    make_pos(quote_age_hours=1e6,
                             expected_refresh_hours=1.0,
                             apr_volatility_pct=18.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_vol_lower_score_when_stale(self):
        low_vol = A().analyze(make_pos(quote_age_hours=72.0,
                                       apr_volatility_pct=1.0))
        high_vol = A().analyze(make_pos(quote_age_hours=72.0,
                                        apr_volatility_pct=18.0))
        self.assertGreater(low_vol["score"], high_vol["score"])

    def test_confidence_matches_score_value(self):
        r = A().analyze(make_pos(quote_age_hours=48.0))
        # confidence_pct is the unrounded score; score is 2-dp rounded.
        self.assertAlmostEqual(r["confidence_pct"], r["score"], places=1)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Fresh", quote_age_hours=6.0),
            make_pos(vault="VeryStale", quote_age_hours=300.0,
                     apr_volatility_pct=18.0),
            make_pos(vault="Mid", quote_age_hours=48.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_freshest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["freshest_vault"]], max(scores.values()))

    def test_stalest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["stalest_vault"]], min(scores.values()))

    def test_freshest_is_fresh(self):
        self.assertEqual(self.res["aggregate"]["freshest_vault"], "Fresh")

    def test_stalest_is_stale(self):
        self.assertEqual(self.res["aggregate"]["stalest_vault"], "VeryStale")

    def test_severely_stale_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["severely_stale_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_severely_stale_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", quote_age_hours=200.0),
            make_pos(vault="B", quote_age_hours=300.0),
            make_pos(vault="C", quote_age_hours=6.0),
        ])
        self.assertEqual(res["aggregate"]["severely_stale_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["freshest_vault"])
        self.assertIsNone(res["aggregate"]["stalest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["freshest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severely_stale_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["freshest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["stalest_vault"], "Solo")

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
                         quote_age_hours=1e9, expected_refresh_hours=1.0,
                         apr_volatility_pct=1e9),
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
            "quote_age_hours": "48",
            "expected_refresh_hours": "24",
            "apr_volatility_pct": "3.0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 12.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(quote_age_hours=200.0, apr_volatility_pct=18.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(quote_age_hours=200.0, apr_volatility_pct=18.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(quote_age_hours=0.0),
                    make_pos(expected_refresh_hours=0.0),
                    make_pos(headline_apr_pct=1e9, quote_age_hours=1e9,
                             expected_refresh_hours=1.0,
                             apr_volatility_pct=1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(quote_age_hours=-1e9,
                             apr_volatility_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12,
                                 quote_age_hours=1e9,
                                 expected_refresh_hours=1.0,
                                 apr_volatility_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(quote_age_hours=-10.0,
                                 apr_volatility_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_age_fresh(self):
        r = A().analyze(make_pos(quote_age_hours=0.0))
        self.assertEqual(r["classification"], "FRESH")

    def test_none_inputs_no_crash(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0,
                         "quote_age_hours": None,
                         "expected_refresh_hours": None,
                         "apr_volatility_pct": None})
        self.assertIn("classification", r)
        finite_check(self, r)


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

    def test_demo_includes_fresh_and_severely_stale(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("FRESH", classes)
        self.assertIn("SEVERELY_STALE", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_QUOTE", recs)

    def test_demo_includes_overdue(self):
        res = A().analyze_portfolio(_demo_positions())
        overdue = any("OVERDUE" in p["flags"] for p in res["positions"])
        self.assertTrue(overdue)

    def test_demo_includes_high_apr_volatility(self):
        res = A().analyze_portfolio(_demo_positions())
        hv = any("HIGH_APR_VOLATILITY" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(hv)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
