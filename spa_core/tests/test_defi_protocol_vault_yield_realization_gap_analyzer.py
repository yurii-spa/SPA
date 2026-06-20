"""
Tests for MP-1169: DeFiProtocolVaultYieldRealizationGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_yield_realization_gap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_yield_realization_gap_analyzer import (
    DeFiProtocolVaultYieldRealizationGapAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    GAP_TOLERANCE_PCT,
    GAP_SCORE_CEILING_PCT,
    OUTPERFORM_GAP_PCT,
    MEETS_GAP_PCT,
    MINOR_GAP_PCT,
    MODERATE_GAP_PCT,
    MEETS_HEADLINE_FRACTION,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=10.0,
    share_price_start_usd=0.0,
    share_price_end_usd=0.0,
    window_days=30.0,
    realized_apr_pct=9.5,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "share_price_start_usd": share_price_start_usd,
        "share_price_end_usd": share_price_end_usd,
        "window_days": window_days,
    }
    if realized_apr_pct is not None:
        pos["realized_apr_pct"] = realized_apr_pct
    return pos


def A():
    return DeFiProtocolVaultYieldRealizationGapAnalyzer()


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
        self.assertGreater(GAP_TOLERANCE_PCT, 0)
        self.assertGreater(GAP_SCORE_CEILING_PCT, 0)
        self.assertGreater(OUTPERFORM_GAP_PCT, 0)
        self.assertLess(MEETS_GAP_PCT, MINOR_GAP_PCT)
        self.assertLess(MINOR_GAP_PCT, MODERATE_GAP_PCT)
        self.assertGreater(MEETS_HEADLINE_FRACTION, 0.0)
        self.assertLessEqual(MEETS_HEADLINE_FRACTION, 1.0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "realized_apr_pct",
            "share_price_start_usd", "share_price_end_usd", "window_days",
            "period_return_pct", "gap_pct", "realization_ratio",
            "realization_pct", "overstated", "meets_headline", "score",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 10.0,
                         "realized_apr_pct": 9.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 10.0, "realized_apr_pct": 9.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0, "realized_apr_pct": 9.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "DISCOUNT_HEADLINE_SLIGHTLY",
            "DISCOUNT_HEADLINE", "AVOID_OR_VERIFY",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "OUTPERFORMS", "MEETS_HEADLINE", "MINOR_GAP", "MODERATE_GAP",
            "SEVERE_GAP", "INSUFFICIENT_DATA",
        })

    def test_overstated_is_bool(self):
        self.assertIsInstance(self.r["overstated"], bool)

    def test_meets_headline_is_bool(self):
        self.assertIsInstance(self.r["meets_headline"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_realized_override_used(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 8.0)

    def test_period_return_none_with_override(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertIsNone(r["period_return_pct"])

    def test_realized_derived_from_prices(self):
        # end/start-1 = 0.01; *365/30*100 = 12.1667
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 window_days=30.0,
                                 realized_apr_pct=None))
        self.assertAlmostEqual(r["realized_apr_pct"],
                               0.01 * (365.0 / 30.0) * 100.0, places=2)

    def test_period_return_set_when_derived(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 window_days=30.0,
                                 realized_apr_pct=None))
        self.assertAlmostEqual(r["period_return_pct"], 1.0, places=4)

    def test_override_preferred_over_prices(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 window_days=30.0,
                                 realized_apr_pct=5.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 5.0)
        self.assertIsNone(r["period_return_pct"])

    def test_gap_pct(self):
        # headline 10 - realized 8 = 2
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertAlmostEqual(r["gap_pct"], 2.0)

    def test_gap_pct_negative_outperform(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=14.0))
        self.assertAlmostEqual(r["gap_pct"], -4.0)

    def test_realization_ratio(self):
        # 8/10 = 0.8
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.8)

    def test_realization_pct(self):
        # 0.8*100 = 80
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertAlmostEqual(r["realization_pct"], 80.0)

    def test_realization_pct_clamped_nonnegative(self):
        # negative realized → ratio negative → clamped to 0
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=-5.0))
        self.assertAlmostEqual(r["realization_pct"], 0.0)

    def test_overstated_true(self):
        # gap 2 > 1.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.0))
        self.assertTrue(r["overstated"])

    def test_overstated_false(self):
        # gap 0.5 <= 1.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.5))
        self.assertFalse(r["overstated"])

    def test_meets_headline_true(self):
        # realized 9.5 >= 10*0.9 = 9.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.5))
        self.assertTrue(r["meets_headline"])

    def test_meets_headline_false(self):
        # realized 5 < 9.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=5.0))
        self.assertFalse(r["meets_headline"])

    def test_passthrough_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, realized_apr_pct=10.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_window_days_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 window_days=45.0,
                                 realized_apr_pct=None))
        self.assertAlmostEqual(r["window_days"], 45.0)

    def test_window_days_negative_clamped(self):
        # negative window → cannot derive; with headline only → insufficient
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 window_days=-30.0,
                                 realized_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=8.3333))
        for k in ("headline_apr_pct", "realized_apr_pct", "gap_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_outperforms(self):
        # realized 14 > headline 10 + 1
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=14.0))
        self.assertEqual(r["classification"], "OUTPERFORMS")

    def test_meets_headline(self):
        # gap 0.5, |gap| <= 1
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.5))
        self.assertEqual(r["classification"], "MEETS_HEADLINE")

    def test_meets_headline_boundary(self):
        # gap exactly 1
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.0))
        self.assertEqual(r["classification"], "MEETS_HEADLINE")

    def test_minor_gap(self):
        # gap 2.5, <= 3
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=7.5))
        self.assertEqual(r["classification"], "MINOR_GAP")

    def test_minor_gap_boundary(self):
        # gap exactly 3
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=7.0))
        self.assertEqual(r["classification"], "MINOR_GAP")

    def test_moderate_gap(self):
        # gap 5, <= 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=5.0))
        self.assertEqual(r["classification"], "MODERATE_GAP")

    def test_moderate_gap_boundary(self):
        # gap exactly 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=2.0))
        self.assertEqual(r["classification"], "MODERATE_GAP")

    def test_severe_gap(self):
        # gap 9 > 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=1.0))
        self.assertEqual(r["classification"], "SEVERE_GAP")

    def test_insufficient_no_headline_no_prices(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0,
                                 share_price_start_usd=0.0,
                                 share_price_end_usd=0.0,
                                 realized_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_headline_only_no_realized(self):
        # headline > 0 but realized cannot be derived → INSUFFICIENT
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=0.0,
                                 share_price_end_usd=0.0,
                                 realized_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_headline_with_realized(self):
        # headline 0 → defensive insufficient
        r = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(realized_apr_pct=14.0),
                    make_pos(realized_apr_pct=9.5),
                    make_pos(realized_apr_pct=7.5),
                    make_pos(realized_apr_pct=5.0),
                    make_pos(realized_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, realized_apr_pct=None)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "OUTPERFORMS", "MEETS_HEADLINE", "MINOR_GAP", "MODERATE_GAP",
                "SEVERE_GAP", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_outperforms(self):
        r = A().analyze(make_pos(realized_apr_pct=14.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_meets(self):
        r = A().analyze(make_pos(realized_apr_pct=9.5))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_slightly_minor(self):
        r = A().analyze(make_pos(realized_apr_pct=7.5))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(realized_apr_pct=5.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_severe(self):
        r = A().analyze(make_pos(realized_apr_pct=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=None))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_meets_headline_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=9.5))
        self.assertIn("MEETS_HEADLINE", r["flags"])

    def test_outperforms_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=14.0))
        self.assertIn("OUTPERFORMS", r["flags"])

    def test_minor_gap_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=7.5))
        self.assertIn("MINOR_GAP", r["flags"])

    def test_moderate_gap_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=5.0))
        self.assertIn("MODERATE_GAP", r["flags"])

    def test_severe_gap_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=1.0))
        self.assertIn("SEVERE_GAP", r["flags"])

    def test_headline_overstated_flag(self):
        # gap 2 > 1.0
        r = A().analyze(make_pos(realized_apr_pct=8.0))
        self.assertIn("HEADLINE_OVERSTATED", r["flags"])

    def test_headline_overstated_flag_absent(self):
        r = A().analyze(make_pos(realized_apr_pct=9.5))
        self.assertNotIn("HEADLINE_OVERSTATED", r["flags"])

    def test_negative_realized_flag(self):
        r = A().analyze(make_pos(realized_apr_pct=-3.0))
        self.assertIn("NEGATIVE_REALIZED", r["flags"])

    def test_negative_realized_flag_absent(self):
        r = A().analyze(make_pos(realized_apr_pct=8.0))
        self.assertNotIn("NEGATIVE_REALIZED", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=None))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_headline_no_realized(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0,
                                 share_price_start_usd=0.0,
                                 share_price_end_usd=0.0,
                                 realized_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_headline_only(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=0.0,
                                 share_price_end_usd=0.0,
                                 realized_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=None))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=None))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["realized_apr_pct"])
        self.assertIsNone(r["period_return_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["realization_pct"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "share_price_start_usd",
                  "share_price_end_usd", "window_days", "gap_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["overstated"])
        self.assertFalse(r["meets_headline"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_non_finite_override_falls_back(self):
        # inf override is not finite → ignored; no prices → insufficient
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0,
                         "realized_apr_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_override(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_prices(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1.0,
                                 share_price_end_usd=1.01,
                                 realized_apr_pct=None))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_smaller_gap_scores_higher(self):
        small = A().analyze(make_pos(headline_apr_pct=10.0,
                                     realized_apr_pct=9.5))
        big = A().analyze(make_pos(headline_apr_pct=10.0,
                                   realized_apr_pct=2.0))
        self.assertGreater(small["score"], big["score"])

    def test_outperform_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=14.0))
        self.assertGreater(r["score"], 85.0)

    def test_meets_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=9.8))
        self.assertGreater(r["score"], 85.0)

    def test_severe_gap_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=1.0))
        self.assertLess(r["score"], 55.0)

    def test_negative_realized_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, realized_apr_pct=-5.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e-9, realized_apr_pct=1e12))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, realized_apr_pct=-1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(realized_apr_pct=14.0),
                    make_pos(realized_apr_pct=9.5),
                    make_pos(realized_apr_pct=7.5),
                    make_pos(realized_apr_pct=5.0),
                    make_pos(realized_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, realized_apr_pct=None)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(realized_apr_pct=14.0),
                    make_pos(realized_apr_pct=1.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Honest", headline_apr_pct=10.0,
                     realized_apr_pct=9.8),
            make_pos(vault="Severe", headline_apr_pct=10.0,
                     realized_apr_pct=1.0),
            make_pos(vault="Mid", headline_apr_pct=10.0, realized_apr_pct=5.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_honest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_honest_vault"]], max(scores.values()))

    def test_least_honest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_honest_vault"]], min(scores.values()))

    def test_most_honest_is_honest(self):
        self.assertEqual(self.res["aggregate"]["most_honest_vault"], "Honest")

    def test_least_honest_is_severe(self):
        self.assertEqual(self.res["aggregate"]["least_honest_vault"], "Severe")

    def test_severe_gap_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["severe_gap_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertIsNone(res["aggregate"]["least_honest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0, realized_apr_pct=None),
            make_pos(headline_apr_pct=0.0, realized_apr_pct=None),
        ])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_gap_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0, realized_apr_pct=9.8),
            make_pos(vault="Ins", headline_apr_pct=0.0, realized_apr_pct=None),
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
                make_pos(vault="big", headline_apr_pct=1e-9,
                         realized_apr_pct=1e12),
                make_pos(vault="ins", headline_apr_pct=0.0,
                         realized_apr_pct=None),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0, realized_apr_pct=None))
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
            "headline_apr_pct": "10",
            "realized_apr_pct": "8",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_string_prices_coerced(self):
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": "10",
            "share_price_start_usd": "1.0",
            "share_price_end_usd": "1.01",
            "window_days": "30",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "realized_apr_pct": 8.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0, realized_apr_pct=None),
            make_pos(realized_apr_pct=1.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(realized_apr_pct=14.0),
                    make_pos(realized_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, realized_apr_pct=None),
                    make_pos(headline_apr_pct=1e-9, realized_apr_pct=1e12),
                    make_pos(headline_apr_pct=1e12, realized_apr_pct=-1e12),
                    make_pos(headline_apr_pct=10.0,
                             share_price_start_usd=1e-12,
                             share_price_end_usd=1e12,
                             realized_apr_pct=None),
                    make_pos(realized_apr_pct=-50.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, realized_apr_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_start_price_no_inf(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 share_price_start_usd=1e-12,
                                 share_price_end_usd=1.0,
                                 window_days=30.0,
                                 realized_apr_pct=None))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=-10.0, realized_apr_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(), make_pos(headline_apr_pct=0.0,
                                         realized_apr_pct=None),
                    make_pos(headline_apr_pct=10.0,
                             share_price_start_usd=1.0,
                             share_price_end_usd=1.01,
                             realized_apr_pct=None)]:
            r = A().analyze(pos)
            for k in ("realized_apr_pct", "period_return_pct",
                      "realization_ratio", "realization_pct"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 3)

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

    def test_demo_includes_honest_and_gap(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "MEETS_HEADLINE" in classes or "OUTPERFORMS" in classes)
        self.assertTrue(
            "SEVERE_GAP" in classes or "MODERATE_GAP" in classes
            or "MINOR_GAP" in classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
