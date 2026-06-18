"""
Tests for MP-1195: DeFiProtocolVaultDeploymentRampDragAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_deployment_ramp_drag_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_deployment_ramp_drag_analyzer import (  # noqa: E501
    DeFiProtocolVaultDeploymentRampDragAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HORIZON_DAYS,
    NEGLIGIBLE_RAMP_FRACTION,
    MINOR_RAMP_FRACTION,
    MODERATE_RAMP_FRACTION,
    SHORT_HORIZON_DAYS,
    LONG_RAMP_DAYS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=12.0,
    ramp_days=0.0,
    holding_horizon_days=365.0,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
    }
    if ramp_days is not None:
        pos["ramp_days"] = ramp_days
    if holding_horizon_days is not None:
        pos["holding_horizon_days"] = holding_horizon_days
    return pos


def A():
    return DeFiProtocolVaultDeploymentRampDragAnalyzer()


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

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

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
        self.assertGreater(NEGLIGIBLE_RAMP_FRACTION, 0)
        self.assertLess(NEGLIGIBLE_RAMP_FRACTION, MINOR_RAMP_FRACTION)
        self.assertLess(MINOR_RAMP_FRACTION, MODERATE_RAMP_FRACTION)
        self.assertGreater(DEFAULT_HORIZON_DAYS, 0)
        self.assertGreater(SHORT_HORIZON_DAYS, 0)
        self.assertGreater(LONG_RAMP_DAYS, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "realized_apr_pct", "drag_pct",
            "realization_ratio", "productive_fraction", "ramp_fraction",
            "ramp_days", "holding_horizon_days", "productive_days",
            "full_horizon_lost", "short_horizon", "long_ramp", "score",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 12.0})
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
            "TRUST_HEADLINE", "DISCOUNT_HEADLINE_SLIGHTLY",
            "DISCOUNT_HEADLINE", "AVOID_OR_VERIFY",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NEGLIGIBLE_RAMP", "MINOR_RAMP", "MODERATE_RAMP",
            "SEVERE_RAMP", "INSUFFICIENT_DATA",
        })

    def test_full_horizon_lost_is_bool(self):
        self.assertIsInstance(self.r["full_horizon_lost"], bool)

    def test_short_horizon_is_bool(self):
        self.assertIsInstance(self.r["short_horizon"], bool)

    def test_long_ramp_is_bool(self):
        self.assertIsInstance(self.r["long_ramp"], bool)


# ── realized APR / drag correctness ───────────────────────────────────────────

class TestRealizedAndDrag(unittest.TestCase):
    def test_no_ramp_full_realization(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=0.0,
                                 holding_horizon_days=365.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 12.0)
        self.assertAlmostEqual(r["drag_pct"], 0.0)
        self.assertAlmostEqual(r["productive_fraction"], 1.0)

    def test_half_horizon_ramp(self):
        # ramp 15 of 30 days → productive 0.5 → realized 6.0, drag 6.0
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=15.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 6.0)
        self.assertAlmostEqual(r["drag_pct"], 6.0)
        self.assertAlmostEqual(r["productive_fraction"], 0.5)

    def test_known_ten_of_thirty(self):
        # ramp 10 of 30 → productive 20/30 = 0.6667 → realized 8.0
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=10.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 8.0, places=3)
        self.assertAlmostEqual(r["drag_pct"], 4.0, places=3)

    def test_ramp_exceeds_horizon_zero_realized(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=40.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 0.0)
        self.assertAlmostEqual(r["drag_pct"], 12.0)
        self.assertAlmostEqual(r["productive_fraction"], 0.0)

    def test_ramp_equals_horizon_zero_realized(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=30.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 0.0)
        self.assertTrue(r["full_horizon_lost"])

    def test_productive_days(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=12.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["productive_days"], 88.0)

    def test_productive_days_floored_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=200.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["productive_days"], 0.0)

    def test_ramp_fraction(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["ramp_fraction"], 0.1)

    def test_ramp_fraction_capped_one(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=500.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["ramp_fraction"], 1.0)

    def test_realization_ratio(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=15.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.5)

    def test_realization_ratio_one_no_ramp(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=0.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0)

    def test_drag_equals_headline_minus_realized(self):
        r = A().analyze(make_pos(headline_apr_pct=9.0, ramp_days=20.0,
                                 holding_horizon_days=80.0))
        self.assertAlmostEqual(
            r["drag_pct"], r["headline_apr_pct"] - r["realized_apr_pct"])

    def test_passthrough_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 13.0)

    def test_ramp_days_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=5.0))
        self.assertAlmostEqual(r["ramp_days"], 5.0)

    def test_horizon_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 holding_horizon_days=90.0))
        self.assertAlmostEqual(r["holding_horizon_days"], 90.0)

    def test_default_horizon_used(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0,
                         "ramp_days": 7.0})
        self.assertAlmostEqual(r["holding_horizon_days"], DEFAULT_HORIZON_DAYS)

    def test_default_ramp_zero(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0,
                         "holding_horizon_days": 100.0})
        self.assertAlmostEqual(r["ramp_days"], 0.0)
        self.assertAlmostEqual(r["realized_apr_pct"], 10.0)

    def test_negative_ramp_clamped(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=-5.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["ramp_days"], 0.0)
        self.assertAlmostEqual(r["realized_apr_pct"], 10.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=13.3333, ramp_days=7.0,
                                 holding_horizon_days=111.0))
        for k in ("headline_apr_pct", "realized_apr_pct", "drag_pct",
                  "productive_fraction", "ramp_fraction"):
            self.assertEqual(r[k], round(r[k], 4))

    def test_realized_never_exceeds_headline(self):
        for ramp in (0.0, 1.0, 10.0, 100.0, 400.0):
            r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=ramp,
                                     holding_horizon_days=100.0))
            self.assertLessEqual(r["realized_apr_pct"], 10.0 + 1e-9)
            self.assertGreaterEqual(r["realized_apr_pct"], 0.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_negligible_no_ramp(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0,
                                 holding_horizon_days=365.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE_RAMP")

    def test_negligible_boundary(self):
        # ramp_fraction exactly 0.01: 3.65 / 365
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=3.65,
                                 holding_horizon_days=365.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE_RAMP")

    def test_minor_ramp(self):
        # ramp_fraction 0.03 (3 of 100) → minor
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=3.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "MINOR_RAMP")

    def test_minor_boundary(self):
        # ramp_fraction exactly 0.05 (5 of 100)
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=5.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "MINOR_RAMP")

    def test_moderate_ramp(self):
        # ramp_fraction 0.10 (10 of 100) → moderate
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "MODERATE_RAMP")

    def test_moderate_boundary(self):
        # ramp_fraction exactly 0.15 (15 of 100)
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=15.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "MODERATE_RAMP")

    def test_severe_ramp(self):
        # ramp_fraction 0.20 (20 of 100) → severe
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=20.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "SEVERE_RAMP")

    def test_severe_just_above_moderate(self):
        # ramp_fraction 0.1501
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=15.01,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "SEVERE_RAMP")

    def test_severe_full_loss(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=100.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["classification"], "SEVERE_RAMP")

    def test_short_horizon_amplifies(self):
        # 10-day ramp over 30-day horizon → fraction 0.333 → severe
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=10.0,
                                 holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "SEVERE_RAMP")

    def test_same_ramp_long_horizon_negligible(self):
        # same 10-day ramp over 1y horizon → fraction 0.027 → minor
        r = A().analyze(make_pos(headline_apr_pct=12.0, ramp_days=10.0,
                                 holding_horizon_days=365.0))
        self.assertEqual(r["classification"], "MINOR_RAMP")

    def test_classification_known_values(self):
        for pos in [
            make_pos(ramp_days=0.0),
            make_pos(ramp_days=3.0, holding_horizon_days=100.0),
            make_pos(ramp_days=10.0, holding_horizon_days=100.0),
            make_pos(ramp_days=30.0, holding_horizon_days=100.0),
            make_pos(headline_apr_pct=0.0),
        ]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NEGLIGIBLE_RAMP", "MINOR_RAMP", "MODERATE_RAMP",
                "SEVERE_RAMP", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_negligible(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_slightly_minor(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=3.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_severe(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=20.0,
                                 holding_horizon_days=100.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_negligible_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0))
        self.assertIn("NEGLIGIBLE_RAMP", r["flags"])

    def test_minor_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=3.0,
                                 holding_horizon_days=100.0))
        self.assertIn("MINOR_RAMP", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertIn("MODERATE_RAMP", r["flags"])

    def test_severe_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=20.0,
                                 holding_horizon_days=100.0))
        self.assertIn("SEVERE_RAMP", r["flags"])

    def test_full_horizon_lost_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=100.0,
                                 holding_horizon_days=100.0))
        self.assertIn("FULL_HORIZON_LOST", r["flags"])

    def test_full_horizon_lost_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertNotIn("FULL_HORIZON_LOST", r["flags"])

    def test_short_horizon_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=2.0,
                                 holding_horizon_days=20.0))
        self.assertIn("SHORT_HORIZON", r["flags"])

    def test_short_horizon_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0,
                                 holding_horizon_days=SHORT_HORIZON_DAYS))
        self.assertIn("SHORT_HORIZON", r["flags"])

    def test_short_horizon_absent_long(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0,
                                 holding_horizon_days=365.0))
        self.assertNotIn("SHORT_HORIZON", r["flags"])

    def test_long_ramp_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=365.0))
        self.assertIn("LONG_RAMP", r["flags"])

    def test_long_ramp_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 ramp_days=LONG_RAMP_DAYS,
                                 holding_horizon_days=365.0))
        self.assertIn("LONG_RAMP", r["flags"])

    def test_long_ramp_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=2.0,
                                 holding_horizon_days=365.0))
        self.assertNotIn("LONG_RAMP", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_one_classification_flag_only(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        class_flags = {"NEGLIGIBLE_RAMP", "MINOR_RAMP", "MODERATE_RAMP",
                       "SEVERE_RAMP"}
        present = [f for f in r["flags"] if f in class_flags]
        self.assertEqual(len(present), 1)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_headline_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_headline_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_headline_missing(self):
        r = A().analyze({"vault": "V"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_horizon_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 holding_horizon_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_horizon_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 holding_horizon_days=-30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_non_finite_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_ramp(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0,
                         "ramp_days": float("nan")})
        # nan ramp → max(0, nan) is nan → not finite → insufficient
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0,
                         "holding_horizon_days": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["realized_apr_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["productive_fraction"])
        self.assertIsNone(r["ramp_fraction"])
        self.assertIsNone(r["ramp_days"])
        self.assertIsNone(r["holding_horizon_days"])
        self.assertIsNone(r["productive_days"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "drag_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["full_horizon_lost"])
        self.assertFalse(r["short_horizon"])
        self.assertFalse(r["long_ramp"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_insufficient_has_all_keys(self):
        r = A().analyze({})
        valid = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), set(valid.keys()))

    def test_valid_not_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity & bounds ─────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_no_ramp_full_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0))
        self.assertAlmostEqual(r["score"], 100.0)

    def test_no_ramp_grade_a(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=0.0))
        self.assertEqual(r["grade"], "A")

    def test_half_horizon_score_50(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=15.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["score"], 50.0)

    def test_full_loss_zero_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=100.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(r["score"], 0.0)

    def test_smaller_ramp_scores_higher(self):
        small = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=2.0,
                                     holding_horizon_days=100.0))
        big = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=40.0,
                                   holding_horizon_days=100.0))
        self.assertGreater(small["score"], big["score"])

    def test_severe_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=50.0,
                                 holding_horizon_days=100.0))
        self.assertLess(r["score"], 55.0)

    def test_score_independent_of_headline_magnitude(self):
        # score depends only on productive fraction, not headline level
        a = A().analyze(make_pos(headline_apr_pct=5.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        b = A().analyze(make_pos(headline_apr_pct=50.0, ramp_days=10.0,
                                 holding_horizon_days=100.0))
        self.assertAlmostEqual(a["score"], b["score"])

    def test_score_in_range_many(self):
        for pos in [
            make_pos(ramp_days=0.0),
            make_pos(ramp_days=3.0, holding_horizon_days=100.0),
            make_pos(ramp_days=10.0, holding_horizon_days=100.0),
            make_pos(ramp_days=50.0, holding_horizon_days=100.0),
            make_pos(ramp_days=200.0, holding_horizon_days=100.0),
            make_pos(headline_apr_pct=0.0),
        ]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [
            make_pos(ramp_days=0.0),
            make_pos(ramp_days=50.0, holding_horizon_days=100.0),
        ]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_monotonic_decreasing_with_ramp(self):
        scores = []
        for ramp in (0.0, 5.0, 15.0, 30.0, 60.0, 100.0):
            r = A().analyze(make_pos(headline_apr_pct=10.0, ramp_days=ramp,
                                     holding_horizon_days=100.0))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_score_floor_zero_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, ramp_days=1e9,
                                 holding_horizon_days=1.0))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Honest", headline_apr_pct=10.0, ramp_days=0.0),
            make_pos(vault="Severe", headline_apr_pct=10.0, ramp_days=60.0,
                     holding_horizon_days=100.0),
            make_pos(vault="Mid", headline_apr_pct=10.0, ramp_days=10.0,
                     holding_horizon_days=100.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_honest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_honest_vault"]],
                         max(scores.values()))

    def test_least_honest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_honest_vault"]],
                         min(scores.values()))

    def test_most_honest_is_honest(self):
        self.assertEqual(self.res["aggregate"]["most_honest_vault"], "Honest")

    def test_least_honest_is_severe(self):
        self.assertEqual(self.res["aggregate"]["least_honest_vault"], "Severe")

    def test_severe_ramp_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["severe_ramp_count"], 1)

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

    def test_empty_severe_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["severe_ramp_count"], 0)

    def test_empty_avg_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_ramp_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0, ramp_days=0.0),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))

    def test_severe_count_multiple(self):
        res = A().analyze_portfolio([
            make_pos(vault="S1", headline_apr_pct=10.0, ramp_days=40.0,
                     holding_horizon_days=100.0),
            make_pos(vault="S2", headline_apr_pct=10.0, ramp_days=80.0,
                     holding_horizon_days=100.0),
            make_pos(vault="Honest", headline_apr_pct=10.0, ramp_days=0.0),
        ])
        self.assertEqual(res["aggregate"]["severe_ramp_count"], 2)

    def test_aggregate_ignores_insufficient_for_ranking(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0, ramp_days=0.0),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "Good")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "Good")


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
                make_pos(vault="big", headline_apr_pct=1e9, ramp_days=1e9,
                         holding_horizon_days=1.0),
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


# ── demo / CLI ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_portfolio_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]),
                         len(_demo_positions()))
        json.dumps(res)

    def test_demo_has_full_spectrum(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NEGLIGIBLE_RAMP", classes)
        self.assertIn("SEVERE_RAMP", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
