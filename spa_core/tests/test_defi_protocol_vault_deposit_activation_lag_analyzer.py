"""
Tests for MP-1176: DeFiProtocolVaultDepositActivationLagAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_deposit_activation_lag_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_deposit_activation_lag_analyzer import (
    DeFiProtocolVaultDepositActivationLagAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    INSTANT_RATIO,
    MINOR_RATIO,
    MATERIAL_RATIO,
    LAG_CEILING_DAYS,
    INSTANT_HOURS,
    LONG_HORIZON_DAYS,
    SHORT_HORIZON_DAYS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=10.0,
    activation_lag_hours=24.0,
    intended_hold_days=30.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "activation_lag_hours": activation_lag_hours,
        "intended_hold_days": intended_hold_days,
    }


def A():
    return DeFiProtocolVaultDepositActivationLagAnalyzer()


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
        self.assertEqual(_f(None, 30.0), 30.0)

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
        self.assertLess(INSTANT_RATIO, MINOR_RATIO)
        self.assertLess(MINOR_RATIO, MATERIAL_RATIO)
        self.assertGreater(LAG_CEILING_DAYS, 0)
        self.assertEqual(INSTANT_HOURS, 1.0)
        self.assertGreater(LONG_HORIZON_DAYS, SHORT_HORIZON_DAYS)
        self.assertGreater(SHORT_HORIZON_DAYS, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "activation_lag_hours", "lag_days",
            "intended_hold_days", "earning_days", "effective_apr_pct",
            "yield_drag_pct", "drag_ratio", "lag_exceeds_hold", "is_instant",
            "long_horizon", "short_horizon", "score", "classification",
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
            "DEPLOY_NOW", "ACCEPTABLE_FOR_HORIZON",
            "LENGTHEN_HORIZON_OR_VERIFY", "AVOID_FOR_SHORT_HOLD",
            "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "INSTANT_DEPLOYMENT", "MINOR_LAG", "MATERIAL_LAG", "SEVERE_LAG",
            "INSUFFICIENT_DATA",
        })

    def test_lag_exceeds_hold_is_bool(self):
        self.assertIsInstance(self.r["lag_exceeds_hold"], bool)

    def test_is_instant_is_bool(self):
        self.assertIsInstance(self.r["is_instant"], bool)

    def test_long_horizon_is_bool(self):
        self.assertIsInstance(self.r["long_horizon"], bool)

    def test_short_horizon_is_bool(self):
        self.assertIsInstance(self.r["short_horizon"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 10.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_lag_negative_clamped(self):
        r = A().analyze(make_pos(activation_lag_hours=-10.0))
        self.assertAlmostEqual(r["activation_lag_hours"], 0.0)

    def test_lag_days_conversion(self):
        # 72 hours = 3 days
        r = A().analyze(make_pos(activation_lag_hours=72.0))
        self.assertAlmostEqual(r["lag_days"], 3.0, places=4)

    def test_earning_days(self):
        # hold 30, lag 3 → earning 27
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=30.0))
        self.assertAlmostEqual(r["earning_days"], 27.0, places=4)

    def test_earning_days_floor_zero(self):
        # lag 10 days > hold 5 → earning 0
        r = A().analyze(make_pos(activation_lag_hours=240.0,
                                 intended_hold_days=5.0))
        self.assertAlmostEqual(r["earning_days"], 0.0, places=4)

    def test_effective_apr(self):
        # headline 10, earning 27/30 → 9.0
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 activation_lag_hours=72.0,
                                 intended_hold_days=30.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 9.0, places=4)

    def test_effective_apr_short_hold(self):
        # headline 10, lag 3 days, hold 5 → earning 2/5 → 4.0
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 activation_lag_hours=72.0,
                                 intended_hold_days=5.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 4.0, places=4)

    def test_effective_apr_instant_equals_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 activation_lag_hours=0.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 10.0, places=4)

    def test_yield_drag(self):
        # headline 10, effective 9 → drag 1
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 activation_lag_hours=72.0,
                                 intended_hold_days=30.0))
        self.assertAlmostEqual(r["yield_drag_pct"], 1.0, places=4)

    def test_drag_ratio(self):
        # lag 3 / hold 30 = 0.1
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=30.0))
        self.assertAlmostEqual(r["drag_ratio"], 0.1, places=4)

    def test_drag_ratio_clamped_one(self):
        # lag exceeds hold → drag ratio clamps to 1
        r = A().analyze(make_pos(activation_lag_hours=240.0,
                                 intended_hold_days=5.0))
        self.assertAlmostEqual(r["drag_ratio"], 1.0, places=4)

    def test_lag_exceeds_hold_true(self):
        r = A().analyze(make_pos(activation_lag_hours=240.0,
                                 intended_hold_days=5.0))
        self.assertTrue(r["lag_exceeds_hold"])

    def test_lag_exceeds_hold_boundary(self):
        # lag exactly equals hold (5 days = 120 hours)
        r = A().analyze(make_pos(activation_lag_hours=120.0,
                                 intended_hold_days=5.0))
        self.assertTrue(r["lag_exceeds_hold"])

    def test_lag_exceeds_hold_false(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertFalse(r["lag_exceeds_hold"])

    def test_is_instant_true(self):
        r = A().analyze(make_pos(activation_lag_hours=0.5))
        self.assertTrue(r["is_instant"])

    def test_is_instant_boundary(self):
        r = A().analyze(make_pos(activation_lag_hours=INSTANT_HOURS))
        self.assertTrue(r["is_instant"])

    def test_is_instant_false(self):
        r = A().analyze(make_pos(activation_lag_hours=2.0))
        self.assertFalse(r["is_instant"])

    def test_long_horizon_true(self):
        r = A().analyze(make_pos(intended_hold_days=180.0))
        self.assertTrue(r["long_horizon"])

    def test_long_horizon_boundary(self):
        r = A().analyze(make_pos(intended_hold_days=LONG_HORIZON_DAYS))
        self.assertTrue(r["long_horizon"])

    def test_short_horizon_true(self):
        r = A().analyze(make_pos(intended_hold_days=5.0))
        self.assertTrue(r["short_horizon"])

    def test_short_horizon_boundary(self):
        r = A().analyze(make_pos(intended_hold_days=SHORT_HORIZON_DAYS))
        self.assertTrue(r["short_horizon"])

    def test_short_horizon_false(self):
        r = A().analyze(make_pos(intended_hold_days=30.0))
        self.assertFalse(r["short_horizon"])

    def test_hold_days_default_30(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0})
        self.assertAlmostEqual(r["intended_hold_days"], 30.0, places=4)

    def test_hold_days_zero_insufficient(self):
        r = A().analyze(make_pos(intended_hold_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_hold_days_negative_insufficient(self):
        r = A().analyze(make_pos(intended_hold_days=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=10.3333,
                                 activation_lag_hours=33.3333,
                                 intended_hold_days=27.7777))
        for k in ("headline_apr_pct", "activation_lag_hours", "lag_days",
                  "intended_hold_days", "earning_days", "effective_apr_pct",
                  "yield_drag_pct", "drag_ratio"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_instant_deployment(self):
        # lag 0 → ratio 0
        r = A().analyze(make_pos(activation_lag_hours=0.0,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "INSTANT_DEPLOYMENT")

    def test_minor_lag(self):
        # lag 1 day / hold 30 = 0.033 → MINOR
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "MINOR_LAG")

    def test_material_lag(self):
        # lag 3 days / hold 14 = 0.214 → MATERIAL
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=14.0))
        self.assertEqual(r["classification"], "MATERIAL_LAG")

    def test_severe_lag(self):
        # lag 3 days / hold 5 = 0.6 → SEVERE
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=5.0))
        self.assertEqual(r["classification"], "SEVERE_LAG")

    def test_instant_ratio_boundary(self):
        # ratio exactly INSTANT_RATIO=0.02: lag 0.6 days / hold 30
        r = A().analyze(make_pos(activation_lag_hours=0.02 * 30 * 24,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "INSTANT_DEPLOYMENT")

    def test_minor_ratio_boundary(self):
        # ratio exactly MINOR_RATIO=0.10: lag 3 days / hold 30
        r = A().analyze(make_pos(activation_lag_hours=0.10 * 30 * 24,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "MINOR_LAG")

    def test_material_ratio_boundary(self):
        # ratio exactly MATERIAL_RATIO=0.30: lag 9 days / hold 30
        r = A().analyze(make_pos(activation_lag_hours=0.30 * 30 * 24,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "MATERIAL_LAG")

    def test_above_material_severe(self):
        # ratio 0.31 → SEVERE
        r = A().analyze(make_pos(activation_lag_hours=0.31 * 30 * 24,
                                 intended_hold_days=30.0))
        self.assertEqual(r["classification"], "SEVERE_LAG")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(activation_lag_hours=0.0),
                    make_pos(activation_lag_hours=24.0),
                    make_pos(activation_lag_hours=72.0,
                             intended_hold_days=14.0),
                    make_pos(activation_lag_hours=72.0,
                             intended_hold_days=5.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "INSTANT_DEPLOYMENT", "MINOR_LAG", "MATERIAL_LAG",
                "SEVERE_LAG", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_now_instant(self):
        r = A().analyze(make_pos(activation_lag_hours=0.0,
                                 intended_hold_days=30.0))
        self.assertEqual(r["recommendation"], "DEPLOY_NOW")

    def test_deploy_now_minor(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertEqual(r["recommendation"], "DEPLOY_NOW")

    def test_acceptable_material(self):
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=14.0))
        self.assertEqual(r["recommendation"], "ACCEPTABLE_FOR_HORIZON")

    def test_lengthen_severe(self):
        # SEVERE but lag does not exceed hold: lag 3 days / hold 7 = 0.43
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=7.0))
        self.assertEqual(r["recommendation"], "LENGTHEN_HORIZON_OR_VERIFY")

    def test_avoid_lag_exceeds_hold(self):
        r = A().analyze(make_pos(activation_lag_hours=240.0,
                                 intended_hold_days=5.0))
        self.assertEqual(r["recommendation"], "AVOID_FOR_SHORT_HOLD")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_lag_exceeds_priority_over_severe(self):
        # lag exceeds hold → AVOID even though it's SEVERE
        r = A().analyze(make_pos(activation_lag_hours=200.0,
                                 intended_hold_days=5.0))
        self.assertEqual(r["recommendation"], "AVOID_FOR_SHORT_HOLD")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_instant_deployment_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=0.0))
        self.assertIn("INSTANT_DEPLOYMENT", r["flags"])

    def test_minor_lag_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertIn("MINOR_LAG", r["flags"])

    def test_material_lag_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=14.0))
        self.assertIn("MATERIAL_LAG", r["flags"])

    def test_severe_lag_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=5.0))
        self.assertIn("SEVERE_LAG", r["flags"])

    def test_lag_exceeds_hold_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=240.0,
                                 intended_hold_days=5.0))
        self.assertIn("LAG_EXCEEDS_HOLD", r["flags"])

    def test_lag_exceeds_hold_flag_absent(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertNotIn("LAG_EXCEEDS_HOLD", r["flags"])

    def test_instant_activation_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=0.5))
        self.assertIn("INSTANT_ACTIVATION", r["flags"])

    def test_instant_activation_flag_absent(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0))
        self.assertNotIn("INSTANT_ACTIVATION", r["flags"])

    def test_long_horizon_ok_flag(self):
        r = A().analyze(make_pos(intended_hold_days=180.0))
        self.assertIn("LONG_HORIZON_OK", r["flags"])

    def test_long_horizon_ok_flag_absent(self):
        r = A().analyze(make_pos(intended_hold_days=30.0))
        self.assertNotIn("LONG_HORIZON_OK", r["flags"])

    def test_short_horizon_flag(self):
        r = A().analyze(make_pos(activation_lag_hours=2.0,
                                 intended_hold_days=5.0))
        self.assertIn("SHORT_HORIZON", r["flags"])

    def test_short_horizon_flag_absent(self):
        r = A().analyze(make_pos(intended_hold_days=30.0))
        self.assertNotIn("SHORT_HORIZON", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(activation_lag_hours=24.0,
                                 intended_hold_days=30.0))
        self.assertIn("MINOR_LAG", r["flags"])
        self.assertNotIn("SEVERE_LAG", r["flags"])


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

    def test_insufficient_ratio_none(self):
        r = A().analyze({})
        self.assertIsNone(r["drag_ratio"])

    def test_insufficient_projection_none(self):
        r = A().analyze({})
        self.assertIsNone(r["earning_days"])
        self.assertIsNone(r["effective_apr_pct"])
        self.assertIsNone(r["yield_drag_pct"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["lag_exceeds_hold"])
        self.assertFalse(r["is_instant"])
        self.assertFalse(r["long_horizon"])
        self.assertFalse(r["short_horizon"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "activation_lag_hours", "lag_days",
                  "intended_hold_days", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_hold_zero(self):
        r = A().analyze(make_pos(intended_hold_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["effective_apr_pct"])

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_faster_scores_higher(self):
        fast = A().analyze(make_pos(activation_lag_hours=6.0,
                                    intended_hold_days=30.0))
        slow = A().analyze(make_pos(activation_lag_hours=120.0,
                                    intended_hold_days=30.0))
        self.assertGreater(fast["score"], slow["score"])

    def test_zero_lag_full_score(self):
        r = A().analyze(make_pos(activation_lag_hours=0.0,
                                 intended_hold_days=30.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_zero_lag_full_score_short_hold(self):
        r = A().analyze(make_pos(activation_lag_hours=0.0,
                                 intended_hold_days=3.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_longer_horizon_higher_score(self):
        # same lag, longer horizon → lower drag ratio → higher score
        short = A().analyze(make_pos(activation_lag_hours=48.0,
                                     intended_hold_days=10.0))
        long = A().analyze(make_pos(activation_lag_hours=48.0,
                                    intended_hold_days=100.0))
        self.assertGreater(long["score"], short["score"])

    def test_worst_case_low_score(self):
        # lag far exceeds hold, large absolute lag
        r = A().analyze(make_pos(activation_lag_hours=720.0,
                                 intended_hold_days=1.0))
        self.assertLess(r["score"], 5.0)

    def test_lag_exceeds_hold_zero_efficiency(self):
        # drag ratio = 1 → efficiency comp = 0; large lag → absolute comp 0
        r = A().analyze(make_pos(activation_lag_hours=24.0 * 7,
                                 intended_hold_days=1.0))
        self.assertAlmostEqual(r["score"], 0.0, places=4)

    def test_known_score_minor(self):
        # ratio 0.1 → efficiency 70*0.9=63; lag 3 days → abs 30*(1-3/7)=17.142...
        r = A().analyze(make_pos(activation_lag_hours=72.0,
                                 intended_hold_days=30.0))
        expected = 70.0 * 0.9 + 30.0 * (1.0 - 3.0 / 7.0)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(activation_lag_hours=1e9,
                                 intended_hold_days=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9,
                                 activation_lag_hours=1e9,
                                 intended_hold_days=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(activation_lag_hours=0.0),
                    make_pos(activation_lag_hours=72.0),
                    make_pos(activation_lag_hours=72.0,
                             intended_hold_days=5.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(activation_lag_hours=0.0),
                    make_pos(activation_lag_hours=240.0,
                             intended_hold_days=5.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Fast", activation_lag_hours=0.0,
                     intended_hold_days=30.0),
            make_pos(vault="Slow", activation_lag_hours=120.0,
                     intended_hold_days=6.0),
            make_pos(vault="Mid", activation_lag_hours=48.0,
                     intended_hold_days=30.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_fastest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["fastest_vault"]], max(scores.values()))

    def test_slowest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["slowest_vault"]], min(scores.values()))

    def test_fastest_is_fast(self):
        self.assertEqual(self.res["aggregate"]["fastest_vault"], "Fast")

    def test_slowest_is_slow(self):
        self.assertEqual(self.res["aggregate"]["slowest_vault"], "Slow")

    def test_severe_lag_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["severe_lag_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_severe_lag_count_only_severe(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", activation_lag_hours=72.0,
                     intended_hold_days=5.0),
            make_pos(vault="B", activation_lag_hours=120.0,
                     intended_hold_days=6.0),
            make_pos(vault="C", activation_lag_hours=0.0,
                     intended_hold_days=30.0),
        ])
        self.assertEqual(res["aggregate"]["severe_lag_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["fastest_vault"])
        self.assertIsNone(res["aggregate"]["slowest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["fastest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_lag_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["fastest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["slowest_vault"], "Solo")

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
                         activation_lag_hours=1e9, intended_hold_days=1e9),
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
            "headline_apr_pct": "10",
            "activation_lag_hours": "24",
            "intended_hold_days": "30",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(activation_lag_hours=240.0, intended_hold_days=5.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(activation_lag_hours=240.0,
                             intended_hold_days=5.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(headline_apr_pct=1e9, activation_lag_hours=1e9,
                             intended_hold_days=1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(activation_lag_hours=-1e9,
                             intended_hold_days=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12,
                                 activation_lag_hours=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(activation_lag_hours=-10.0,
                                 intended_hold_days=30.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_lag_instant(self):
        r = A().analyze(make_pos(activation_lag_hours=0.0))
        self.assertEqual(r["classification"], "INSTANT_DEPLOYMENT")


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

    def test_demo_includes_instant_and_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSTANT_DEPLOYMENT", classes)
        self.assertIn("SEVERE_LAG", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("INSTANT_DEPLOYMENT", "MINOR_LAG", "MATERIAL_LAG",
                  "SEVERE_LAG", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_deploy(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_FOR_SHORT_HOLD", recs)
        self.assertIn("DEPLOY_NOW", recs)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
