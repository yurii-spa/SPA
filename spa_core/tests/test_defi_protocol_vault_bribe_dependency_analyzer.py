"""
Tests for MP-1175: DeFiProtocolVaultBribeDependencyAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_bribe_dependency_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_bribe_dependency_analyzer import (
    DeFiProtocolVaultBribeDependencyAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    BRIBE_HEAVY_PCT,
    LOW_DEP_PCT,
    MODERATE_DEP_PCT,
    NO_DEP_PCT,
    CHANGE_FLOOR_PCT,
    VOL_CEILING_PCT,
    SEVERE_DECLINE_PCT,
    DECLINE_PCT,
    RISE_PCT,
    HIGH_VOL_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=16.0,
    bribe_apr_pct=6.0,
    bribe_apr_change_pct=0.0,
    bribe_volatility_pct=20.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "bribe_apr_pct": bribe_apr_pct,
        "bribe_apr_change_pct": bribe_apr_change_pct,
        "bribe_volatility_pct": bribe_volatility_pct,
    }


def A():
    return DeFiProtocolVaultBribeDependencyAnalyzer()


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
        self.assertLess(NO_DEP_PCT, LOW_DEP_PCT)
        self.assertLess(LOW_DEP_PCT, MODERATE_DEP_PCT)
        self.assertEqual(BRIBE_HEAVY_PCT, 50.0)
        self.assertGreater(CHANGE_FLOOR_PCT, 0)
        self.assertGreater(VOL_CEILING_PCT, 0)
        self.assertLess(SEVERE_DECLINE_PCT, 0)
        self.assertLess(DECLINE_PCT, 0)
        self.assertGreater(RISE_PCT, 0)
        self.assertGreater(HIGH_VOL_PCT, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "base_apr_pct", "bribe_apr_pct",
            "bribe_share_pct", "bribe_apr_change_pct", "bribe_volatility_pct",
            "apr_if_bribes_halve_pct", "apr_if_bribes_vanish_pct",
            "durable_apr_pct", "bribe_heavy", "bribes_declining",
            "bribes_rising", "high_bribe_volatility", "score",
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
            "TRUST_HEADLINE", "DISCOUNT_FOR_BRIBE_RISK", "DISCOUNT_HEAVILY",
            "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NO_BRIBE_DEPENDENCY", "LOW_BRIBE_DEPENDENCY",
            "MODERATE_BRIBE_DEPENDENCY", "HIGH_BRIBE_DEPENDENCY",
            "INSUFFICIENT_DATA",
        })

    def test_bribe_heavy_is_bool(self):
        self.assertIsInstance(self.r["bribe_heavy"], bool)

    def test_bribes_declining_is_bool(self):
        self.assertIsInstance(self.r["bribes_declining"], bool)

    def test_bribes_rising_is_bool(self):
        self.assertIsInstance(self.r["bribes_rising"], bool)

    def test_high_bribe_volatility_is_bool(self):
        self.assertIsInstance(self.r["high_bribe_volatility"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 16.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bribe_negative_clamped(self):
        r = A().analyze(make_pos(bribe_apr_pct=-2.0))
        self.assertAlmostEqual(r["bribe_apr_pct"], 0.0)

    def test_bribe_clamped_to_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, bribe_apr_pct=15.0))
        self.assertAlmostEqual(r["bribe_apr_pct"], 10.0)

    def test_base_apr(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertAlmostEqual(r["base_apr_pct"], 10.0, places=4)

    def test_base_apr_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, bribe_apr_pct=15.0))
        self.assertAlmostEqual(r["base_apr_pct"], 0.0, places=4)

    def test_bribe_share(self):
        # 6 / 16 * 100 = 37.5
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertAlmostEqual(r["bribe_share_pct"], 37.5, places=4)

    def test_bribe_share_zero_no_bribe(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0))
        self.assertAlmostEqual(r["bribe_share_pct"], 0.0, places=4)

    def test_bribe_share_full(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=16.0))
        self.assertAlmostEqual(r["bribe_share_pct"], 100.0, places=4)

    def test_apr_if_bribes_halve(self):
        # base 10 + bribe 6*0.5 = 13
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertAlmostEqual(r["apr_if_bribes_halve_pct"], 13.0, places=4)

    def test_apr_if_bribes_vanish(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertAlmostEqual(r["apr_if_bribes_vanish_pct"], 10.0, places=4)

    def test_durable_apr_equals_base(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertAlmostEqual(r["durable_apr_pct"], r["base_apr_pct"],
                               places=4)

    def test_bribe_change_signed_preserved(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=-40.0))
        self.assertAlmostEqual(r["bribe_apr_change_pct"], -40.0, places=4)

    def test_bribe_vol_negative_clamped(self):
        r = A().analyze(make_pos(bribe_volatility_pct=-10.0))
        self.assertAlmostEqual(r["bribe_volatility_pct"], 0.0, places=4)

    def test_bribe_heavy_true(self):
        # share 8/12 = 66.7 >= 50
        r = A().analyze(make_pos(headline_apr_pct=12.0, bribe_apr_pct=8.0))
        self.assertTrue(r["bribe_heavy"])

    def test_bribe_heavy_boundary(self):
        # share exactly 50
        r = A().analyze(make_pos(headline_apr_pct=12.0, bribe_apr_pct=6.0))
        self.assertTrue(r["bribe_heavy"])

    def test_bribe_heavy_false(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0))
        self.assertFalse(r["bribe_heavy"])

    def test_bribes_declining_true(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=-10.0))
        self.assertTrue(r["bribes_declining"])

    def test_bribes_declining_boundary_excluded(self):
        # exactly DECLINE_PCT=-1.0, strict < → not declining
        r = A().analyze(make_pos(bribe_apr_change_pct=DECLINE_PCT))
        self.assertFalse(r["bribes_declining"])

    def test_bribes_rising_true(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=10.0))
        self.assertTrue(r["bribes_rising"])

    def test_bribes_rising_boundary_excluded(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=RISE_PCT))
        self.assertFalse(r["bribes_rising"])

    def test_high_bribe_volatility_true(self):
        r = A().analyze(make_pos(bribe_volatility_pct=90.0))
        self.assertTrue(r["high_bribe_volatility"])

    def test_high_bribe_volatility_boundary(self):
        r = A().analyze(make_pos(bribe_volatility_pct=HIGH_VOL_PCT))
        self.assertTrue(r["high_bribe_volatility"])

    def test_high_bribe_volatility_false(self):
        r = A().analyze(make_pos(bribe_volatility_pct=30.0))
        self.assertFalse(r["high_bribe_volatility"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=16.3333,
                                 bribe_apr_pct=6.1111,
                                 bribe_apr_change_pct=-7.7777,
                                 bribe_volatility_pct=33.3333))
        for k in ("headline_apr_pct", "base_apr_pct", "bribe_apr_pct",
                  "bribe_share_pct", "bribe_apr_change_pct",
                  "bribe_volatility_pct", "apr_if_bribes_halve_pct",
                  "apr_if_bribes_vanish_pct", "durable_apr_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_no_dependency(self):
        # share 0
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_BRIBE_DEPENDENCY")

    def test_low_dependency(self):
        # 2/16 = 12.5%
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0))
        self.assertEqual(r["classification"], "LOW_BRIBE_DEPENDENCY")

    def test_moderate_dependency(self):
        # 6/16 = 37.5%
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertEqual(r["classification"], "MODERATE_BRIBE_DEPENDENCY")

    def test_high_dependency(self):
        # 12/16 = 75%
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=12.0))
        self.assertEqual(r["classification"], "HIGH_BRIBE_DEPENDENCY")

    def test_no_dep_boundary(self):
        # share exactly NO_DEP_PCT=2.0 → NO_BRIBE_DEPENDENCY (<=)
        r = A().analyze(make_pos(headline_apr_pct=100.0, bribe_apr_pct=2.0))
        self.assertEqual(r["classification"], "NO_BRIBE_DEPENDENCY")

    def test_low_dep_boundary(self):
        # share exactly LOW_DEP_PCT=25.0 → LOW (<=)
        r = A().analyze(make_pos(headline_apr_pct=100.0, bribe_apr_pct=25.0))
        self.assertEqual(r["classification"], "LOW_BRIBE_DEPENDENCY")

    def test_moderate_dep_boundary(self):
        # share exactly MODERATE_DEP_PCT=50.0 → MODERATE (<=)
        r = A().analyze(make_pos(headline_apr_pct=100.0, bribe_apr_pct=50.0))
        self.assertEqual(r["classification"], "MODERATE_BRIBE_DEPENDENCY")

    def test_above_moderate_high(self):
        # share 50.1 → HIGH
        r = A().analyze(make_pos(headline_apr_pct=1000.0, bribe_apr_pct=501.0))
        self.assertEqual(r["classification"], "HIGH_BRIBE_DEPENDENCY")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(bribe_apr_pct=0.0),
                    make_pos(bribe_apr_pct=2.0),
                    make_pos(bribe_apr_pct=6.0),
                    make_pos(bribe_apr_pct=12.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NO_BRIBE_DEPENDENCY", "LOW_BRIBE_DEPENDENCY",
                "MODERATE_BRIBE_DEPENDENCY", "HIGH_BRIBE_DEPENDENCY",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_headline_no_dep(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0,
                                 bribe_apr_change_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_headline_low_dep(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0,
                                 bribe_apr_change_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_for_bribe_risk_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0,
                                 bribe_apr_change_pct=0.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_FOR_BRIBE_RISK")

    def test_discount_heavily_high_no_severe(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=12.0,
                                 bribe_apr_change_pct=0.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEAVILY")

    def test_avoid_high_and_severe_decline(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=12.0,
                                 bribe_apr_change_pct=-40.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_severe_decline_moderate_discount_heavily(self):
        # MODERATE classification but severe decline and share > NO_DEP
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0,
                                 bribe_apr_change_pct=-30.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEAVILY")

    def test_severe_decline_low_discount_heavily(self):
        # LOW classification, severe decline, share > NO_DEP → DISCOUNT_HEAVILY
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0,
                                 bribe_apr_change_pct=-30.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEAVILY")

    def test_severe_decline_no_dep_still_trust(self):
        # severe decline but no bribe share → TRUST_HEADLINE
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0,
                                 bribe_apr_change_pct=-50.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_severe_decline_boundary(self):
        # change exactly SEVERE_DECLINE_PCT=-25, MODERATE share
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0,
                                 bribe_apr_change_pct=SEVERE_DECLINE_PCT))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEAVILY")

    def test_high_dep_priority_over_severe(self):
        # high dep + severe → AVOID (high+severe branch first)
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=12.0,
                                 bribe_apr_change_pct=-50.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_no_dep_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0))
        self.assertIn("NO_BRIBE_DEPENDENCY", r["flags"])

    def test_low_dep_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0))
        self.assertIn("LOW_BRIBE_DEPENDENCY", r["flags"])

    def test_moderate_dep_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=6.0))
        self.assertIn("MODERATE_BRIBE_DEPENDENCY", r["flags"])

    def test_high_dep_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=12.0))
        self.assertIn("HIGH_BRIBE_DEPENDENCY", r["flags"])

    def test_bribe_heavy_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, bribe_apr_pct=8.0))
        self.assertIn("BRIBE_HEAVY", r["flags"])

    def test_bribe_heavy_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=2.0))
        self.assertNotIn("BRIBE_HEAVY", r["flags"])

    def test_bribes_declining_flag(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=-10.0))
        self.assertIn("BRIBES_DECLINING", r["flags"])

    def test_bribes_declining_flag_absent(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=0.0))
        self.assertNotIn("BRIBES_DECLINING", r["flags"])

    def test_bribes_rising_flag(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=10.0))
        self.assertIn("BRIBES_RISING", r["flags"])

    def test_bribes_rising_flag_absent(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=0.0))
        self.assertNotIn("BRIBES_RISING", r["flags"])

    def test_high_bribe_volatility_flag(self):
        r = A().analyze(make_pos(bribe_volatility_pct=90.0))
        self.assertIn("HIGH_BRIBE_VOLATILITY", r["flags"])

    def test_high_bribe_volatility_flag_absent(self):
        r = A().analyze(make_pos(bribe_volatility_pct=30.0))
        self.assertNotIn("HIGH_BRIBE_VOLATILITY", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_declining_and_rising_mutually_exclusive(self):
        r = A().analyze(make_pos(bribe_apr_change_pct=-10.0))
        self.assertIn("BRIBES_DECLINING", r["flags"])
        self.assertNotIn("BRIBES_RISING", r["flags"])


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

    def test_insufficient_share_none(self):
        r = A().analyze({})
        self.assertIsNone(r["bribe_share_pct"])

    def test_insufficient_projection_none(self):
        r = A().analyze({})
        self.assertIsNone(r["apr_if_bribes_halve_pct"])
        self.assertIsNone(r["apr_if_bribes_vanish_pct"])
        self.assertIsNone(r["durable_apr_pct"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["bribe_heavy"])
        self.assertFalse(r["bribes_declining"])
        self.assertFalse(r["bribes_rising"])
        self.assertFalse(r["high_bribe_volatility"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "base_apr_pct", "bribe_apr_pct",
                  "bribe_apr_change_pct", "bribe_volatility_pct", "score"):
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
    def test_less_dependent_scores_higher(self):
        low = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=1.0,
                                   bribe_apr_change_pct=0.0,
                                   bribe_volatility_pct=0.0))
        high = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=14.0,
                                    bribe_apr_change_pct=0.0,
                                    bribe_volatility_pct=0.0))
        self.assertGreater(low["score"], high["score"])

    def test_zero_bribe_full_score(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0,
                                 bribe_apr_change_pct=0.0,
                                 bribe_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_zero_bribe_full_score_despite_decline(self):
        # no bribe share → trend/vol penalties scale to zero → 100
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=0.0,
                                 bribe_apr_change_pct=-50.0,
                                 bribe_volatility_pct=100.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_declining_bribes_lower_score(self):
        stable = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                      bribe_apr_change_pct=0.0,
                                      bribe_volatility_pct=0.0))
        declining = A().analyze(make_pos(headline_apr_pct=16.0,
                                         bribe_apr_pct=8.0,
                                         bribe_apr_change_pct=-50.0,
                                         bribe_volatility_pct=0.0))
        self.assertGreater(stable["score"], declining["score"])

    def test_rising_bribes_no_penalty(self):
        # a rise (positive change) gives min(0,change)=0 → no trend penalty
        stable = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                      bribe_apr_change_pct=0.0,
                                      bribe_volatility_pct=0.0))
        rising = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                      bribe_apr_change_pct=40.0,
                                      bribe_volatility_pct=0.0))
        self.assertAlmostEqual(stable["score"], rising["score"], places=4)

    def test_high_volatility_lower_score(self):
        calm = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                    bribe_apr_change_pct=0.0,
                                    bribe_volatility_pct=0.0))
        wild = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                    bribe_apr_change_pct=0.0,
                                    bribe_volatility_pct=100.0))
        self.assertGreater(calm["score"], wild["score"])

    def test_worst_case_low_score(self):
        # full bribe share, severe decline, max vol
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=16.0,
                                 bribe_apr_change_pct=-50.0,
                                 bribe_volatility_pct=100.0))
        self.assertLess(r["score"], 5.0)

    def test_half_share_durable_component(self):
        # share 50%, no decline, no vol → durable 25 + trend 30 + vol 20 = 75
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=8.0,
                                 bribe_apr_change_pct=0.0,
                                 bribe_volatility_pct=0.0))
        self.assertAlmostEqual(r["score"], 75.0, places=4)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, bribe_apr_pct=16.0,
                                 bribe_apr_change_pct=-1e9,
                                 bribe_volatility_pct=1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, bribe_apr_pct=1e9,
                                 bribe_apr_change_pct=1e9,
                                 bribe_volatility_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(bribe_apr_pct=0.0),
                    make_pos(bribe_apr_pct=6.0),
                    make_pos(bribe_apr_pct=12.0,
                             bribe_apr_change_pct=-40.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(bribe_apr_pct=0.0),
                    make_pos(bribe_apr_pct=16.0,
                             bribe_apr_change_pct=-50.0,
                             bribe_volatility_pct=100.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Durable", headline_apr_pct=16.0, bribe_apr_pct=0.0,
                     bribe_apr_change_pct=0.0, bribe_volatility_pct=0.0),
            make_pos(vault="Dependent", headline_apr_pct=16.0,
                     bribe_apr_pct=15.0, bribe_apr_change_pct=-50.0,
                     bribe_volatility_pct=100.0),
            make_pos(vault="Mid", headline_apr_pct=16.0, bribe_apr_pct=6.0,
                     bribe_apr_change_pct=-5.0, bribe_volatility_pct=40.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_durable_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_durable_vault"]],
                         max(scores.values()))

    def test_most_dependent_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_bribe_dependent_vault"]],
                         min(scores.values()))

    def test_most_durable_is_durable(self):
        self.assertEqual(self.res["aggregate"]["most_durable_vault"],
                         "Durable")

    def test_most_dependent_is_dependent(self):
        self.assertEqual(self.res["aggregate"]["most_bribe_dependent_vault"],
                         "Dependent")

    def test_high_dependency_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["high_dependency_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_high_dependency_count_only_high(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=16.0, bribe_apr_pct=12.0),
            make_pos(vault="B", headline_apr_pct=16.0, bribe_apr_pct=14.0),
            make_pos(vault="C", headline_apr_pct=16.0, bribe_apr_pct=2.0),
        ])
        self.assertEqual(res["aggregate"]["high_dependency_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_durable_vault"])
        self.assertIsNone(res["aggregate"]["most_bribe_dependent_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_durable_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["high_dependency_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_durable_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_bribe_dependent_vault"],
                         "Solo")

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
                         bribe_apr_pct=1e9, bribe_apr_change_pct=-1e9,
                         bribe_volatility_pct=1e9),
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
            "headline_apr_pct": "16",
            "bribe_apr_pct": "6",
            "bribe_apr_change_pct": "-5",
            "bribe_volatility_pct": "40",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 16.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(bribe_apr_pct=14.0, bribe_apr_change_pct=-40.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(bribe_apr_pct=14.0, bribe_apr_change_pct=-40.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(headline_apr_pct=1e9, bribe_apr_pct=1e9,
                             bribe_apr_change_pct=1e9,
                             bribe_volatility_pct=1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(bribe_apr_pct=-1e9, bribe_volatility_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, bribe_apr_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(bribe_apr_pct=-10.0,
                                 bribe_volatility_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_bribe_no_dependency(self):
        r = A().analyze(make_pos(bribe_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_BRIBE_DEPENDENCY")


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

    def test_demo_includes_no_dep_and_high(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NO_BRIBE_DEPENDENCY", classes)
        self.assertIn("HIGH_BRIBE_DEPENDENCY", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NO_BRIBE_DEPENDENCY", "LOW_BRIBE_DEPENDENCY",
                  "MODERATE_BRIBE_DEPENDENCY", "HIGH_BRIBE_DEPENDENCY",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_severe_decline_and_stable_high(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("DISCOUNT_HEAVILY", recs)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
