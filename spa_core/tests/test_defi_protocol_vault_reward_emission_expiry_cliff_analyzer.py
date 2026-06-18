"""
Tests for MP-1186: DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_reward_emission_expiry_cliff_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_reward_emission_expiry_cliff_analyzer import (
    DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HOLDING_HORIZON_DAYS,
    DURABLE_FRACTION,
    MOSTLY_DURABLE_FRACTION,
    SOFT_CLIFF_FRACTION,
    HARD_CLIFF_FRACTION,
    HIGH_EMISSION_SHARE,
    IMMINENT_CLIFF_DAYS,
    THIN_BASE_FRACTION,
    RATIO_CAP,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=20.0,
    base_apr_pct=10.0,
    days_to_cliff=60.0,
    holding_horizon_days=30.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "base_apr_pct": base_apr_pct,
        "days_to_cliff": days_to_cliff,
        "holding_horizon_days": holding_horizon_days,
    }


def A():
    return DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer()


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

    def test_fraction_ordering(self):
        self.assertGreater(DURABLE_FRACTION, MOSTLY_DURABLE_FRACTION)
        self.assertGreater(MOSTLY_DURABLE_FRACTION, SOFT_CLIFF_FRACTION)
        self.assertGreater(SOFT_CLIFF_FRACTION, HARD_CLIFF_FRACTION)

    def test_fractions_in_unit(self):
        for v in (DURABLE_FRACTION, MOSTLY_DURABLE_FRACTION,
                  SOFT_CLIFF_FRACTION, HARD_CLIFF_FRACTION):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_high_emission_share(self):
        self.assertEqual(HIGH_EMISSION_SHARE, 0.5)

    def test_imminent_cliff_days(self):
        self.assertGreater(IMMINENT_CLIFF_DAYS, 0.0)

    def test_thin_base_fraction(self):
        self.assertGreater(THIN_BASE_FRACTION, 0.0)
        self.assertLess(THIN_BASE_FRACTION, 1.0)

    def test_ratio_cap(self):
        self.assertEqual(RATIO_CAP, 1.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_reward_emission_expiry_cliff_log.json", LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_base(self):
        self.assertIn("base_apr_pct", self.r)

    def test_has_emission_apr(self):
        self.assertIn("emission_apr_pct", self.r)

    def test_has_emission_share(self):
        self.assertIn("emission_share", self.r)

    def test_has_days_to_cliff(self):
        self.assertIn("days_to_cliff", self.r)

    def test_has_horizon(self):
        self.assertIn("holding_horizon_days", self.r)

    def test_has_live_fraction(self):
        self.assertIn("live_fraction", self.r)

    def test_has_cliff_reached(self):
        self.assertIn("cliff_reached", self.r)

    def test_has_cliff_within_horizon(self):
        self.assertIn("cliff_within_horizon", self.r)

    def test_has_forward_apr(self):
        self.assertIn("forward_apr_pct", self.r)

    def test_has_forward_drop(self):
        self.assertIn("forward_drop_pct", self.r)

    def test_has_durable_fraction(self):
        self.assertIn("durable_fraction", self.r)

    def test_has_base_fraction(self):
        self.assertIn("base_fraction", self.r)

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
        r = A().analyze({"token": "TKN", "headline_apr_pct": 10.0})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_emission_apr_computed(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=12.0))
        self.assertAlmostEqual(r["emission_apr_pct"], 8.0, places=4)

    def test_emission_share(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=10.0))
        self.assertAlmostEqual(r["emission_share"], 0.5, places=4)

    def test_base_clamped_to_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, base_apr_pct=50.0))
        self.assertEqual(r["base_apr_pct"], 10.0)

    def test_base_clamped_low(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, base_apr_pct=-5.0))
        self.assertEqual(r["base_apr_pct"], 0.0)

    def test_emission_zero_when_base_eq_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, base_apr_pct=10.0))
        self.assertEqual(r["emission_apr_pct"], 0.0)
        self.assertEqual(r["emission_share"], 0.0)

    def test_live_fraction_cliff_beyond_horizon(self):
        r = A().analyze(make_pos(days_to_cliff=100.0, holding_horizon_days=30.0))
        self.assertEqual(r["live_fraction"], 1.0)

    def test_live_fraction_half(self):
        r = A().analyze(make_pos(days_to_cliff=15.0, holding_horizon_days=30.0))
        self.assertAlmostEqual(r["live_fraction"], 0.5, places=4)

    def test_live_fraction_zero_when_cliff_reached(self):
        r = A().analyze(make_pos(days_to_cliff=0.0))
        self.assertEqual(r["live_fraction"], 0.0)

    def test_cliff_reached_true(self):
        r = A().analyze(make_pos(days_to_cliff=0.0))
        self.assertTrue(r["cliff_reached"])

    def test_cliff_reached_false(self):
        r = A().analyze(make_pos(days_to_cliff=10.0))
        self.assertFalse(r["cliff_reached"])

    def test_cliff_within_horizon_true(self):
        r = A().analyze(make_pos(days_to_cliff=10.0, holding_horizon_days=30.0))
        self.assertTrue(r["cliff_within_horizon"])

    def test_cliff_within_horizon_false(self):
        r = A().analyze(make_pos(days_to_cliff=40.0, holding_horizon_days=30.0))
        self.assertFalse(r["cliff_within_horizon"])

    def test_forward_apr_full_when_cliff_far(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=10.0,
                                 days_to_cliff=100.0, holding_horizon_days=30.0))
        self.assertAlmostEqual(r["forward_apr_pct"], 20.0, places=4)

    def test_forward_apr_base_when_cliff_reached(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=10.0,
                                 days_to_cliff=0.0))
        self.assertAlmostEqual(r["forward_apr_pct"], 10.0, places=4)

    def test_forward_apr_blend(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=10.0,
                                 days_to_cliff=15.0, holding_horizon_days=30.0))
        # 0.5*20 + 0.5*10 = 15
        self.assertAlmostEqual(r["forward_apr_pct"], 15.0, places=4)

    def test_forward_drop(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=10.0,
                                 days_to_cliff=0.0))
        self.assertAlmostEqual(r["forward_drop_pct"], 10.0, places=4)

    def test_forward_drop_zero_when_durable(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertAlmostEqual(r["forward_drop_pct"], 0.0, places=4)

    def test_durable_fraction_one_when_far(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertEqual(r["durable_fraction"], 1.0)

    def test_durable_fraction_base_when_collapsed(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=4.0,
                                 days_to_cliff=0.0))
        self.assertAlmostEqual(r["durable_fraction"], 0.2, places=4)

    def test_base_fraction(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=5.0))
        self.assertAlmostEqual(r["base_fraction"], 0.25, places=4)

    def test_horizon_default_applied(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "base_apr_pct": 10.0, "days_to_cliff": 10.0})
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_zero(self):
        r = A().analyze(make_pos(holding_horizon_days=0.0))
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_negative(self):
        r = A().analyze(make_pos(holding_horizon_days=-5.0))
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_days_to_cliff_max0(self):
        r = A().analyze(make_pos(days_to_cliff=-10.0))
        self.assertEqual(r["days_to_cliff"], 0.0)
        self.assertTrue(r["cliff_reached"])

    def test_high_emission_share_flag_value(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=8.0))
        self.assertTrue(r["high_emission_share"])

    def test_low_emission_share(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=18.0))
        self.assertFalse(r["high_emission_share"])

    def test_imminent_cliff_true(self):
        r = A().analyze(make_pos(days_to_cliff=5.0, holding_horizon_days=30.0))
        self.assertTrue(r["imminent_cliff"])

    def test_imminent_cliff_false_far(self):
        r = A().analyze(make_pos(days_to_cliff=20.0, holding_horizon_days=30.0))
        self.assertFalse(r["imminent_cliff"])

    def test_thin_base_true(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=2.0))
        self.assertTrue(r["thin_base"])

    def test_thin_base_false(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=18.0))
        self.assertFalse(r["thin_base"])

    def test_finite_all_metrics(self):
        r = A().analyze(make_pos())
        finite_check(self, r)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_durable(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertEqual(r["classification"], "DURABLE")

    def test_mostly_durable(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=12.0,
                                 days_to_cliff=17.0, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "MOSTLY_DURABLE")

    def test_soft_cliff(self):
        r = A().analyze(make_pos(headline_apr_pct=30.0, base_apr_pct=10.0,
                                 days_to_cliff=12.0, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "SOFT_CLIFF")

    def test_hard_cliff(self):
        r = A().analyze(make_pos(headline_apr_pct=40.0, base_apr_pct=8.0,
                                 days_to_cliff=20.0, holding_horizon_days=60.0))
        self.assertEqual(r["classification"], "HARD_CLIFF")

    def test_cliff_collapse(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, base_apr_pct=2.0,
                                 days_to_cliff=0.0, holding_horizon_days=90.0))
        self.assertEqual(r["classification"], "CLIFF_COLLAPSE")

    def test_classify_boundary_durable(self):
        c = A()._classify(DURABLE_FRACTION)
        self.assertEqual(c, "DURABLE")

    def test_classify_boundary_mostly(self):
        c = A()._classify(MOSTLY_DURABLE_FRACTION)
        self.assertEqual(c, "MOSTLY_DURABLE")

    def test_classify_boundary_soft(self):
        c = A()._classify(SOFT_CLIFF_FRACTION)
        self.assertEqual(c, "SOFT_CLIFF")

    def test_classify_boundary_hard(self):
        c = A()._classify(HARD_CLIFF_FRACTION)
        self.assertEqual(c, "HARD_CLIFF")

    def test_classify_below_hard(self):
        c = A()._classify(HARD_CLIFF_FRACTION - 0.01)
        self.assertEqual(c, "CLIFF_COLLAPSE")

    def test_classify_just_below_durable(self):
        c = A()._classify(DURABLE_FRACTION - 0.001)
        self.assertEqual(c, "MOSTLY_DURABLE")

    def test_classify_zero(self):
        self.assertEqual(A()._classify(0.0), "CLIFF_COLLAPSE")

    def test_classify_one(self):
        self.assertEqual(A()._classify(1.0), "DURABLE")

    def test_classify_clamps_above_one(self):
        self.assertEqual(A()._classify(5.0), "DURABLE")

    def test_classify_clamps_below_zero(self):
        self.assertEqual(A()._classify(-2.0), "CLIFF_COLLAPSE")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_durable(self):
        self.assertEqual(A()._recommend("DURABLE"), "NO_ACTION")

    def test_mostly_durable(self):
        self.assertEqual(A()._recommend("MOSTLY_DURABLE"), "MONITOR")

    def test_soft_cliff(self):
        self.assertEqual(A()._recommend("SOFT_CLIFF"), "DISCOUNT_HEADLINE")

    def test_hard_cliff(self):
        self.assertEqual(A()._recommend("HARD_CLIFF"), "PLAN_EXIT_AT_CLIFF")

    def test_collapse(self):
        self.assertEqual(A()._recommend("CLIFF_COLLAPSE"), "USE_BASE_APR")

    def test_durable_via_analyze(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertEqual(r["recommendation"], "NO_ACTION")

    def test_collapse_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, base_apr_pct=2.0,
                                 days_to_cliff=0.0, holding_horizon_days=90.0))
        self.assertEqual(r["recommendation"], "USE_BASE_APR")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_durable_flag(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertIn("DURABLE", r["flags"])

    def test_collapse_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, base_apr_pct=2.0,
                                 days_to_cliff=0.0, holding_horizon_days=90.0))
        self.assertIn("CLIFF_COLLAPSE", r["flags"])

    def test_cliff_reached_flag(self):
        r = A().analyze(make_pos(days_to_cliff=0.0))
        self.assertIn("CLIFF_REACHED", r["flags"])

    def test_cliff_within_horizon_flag(self):
        r = A().analyze(make_pos(days_to_cliff=10.0, holding_horizon_days=30.0))
        self.assertIn("CLIFF_WITHIN_HORIZON", r["flags"])

    def test_no_cliff_within_when_far(self):
        r = A().analyze(make_pos(days_to_cliff=100.0, holding_horizon_days=30.0))
        self.assertNotIn("CLIFF_WITHIN_HORIZON", r["flags"])
        self.assertNotIn("CLIFF_REACHED", r["flags"])

    def test_high_emission_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=5.0,
                                 days_to_cliff=10.0))
        self.assertIn("HIGH_EMISSION_SHARE", r["flags"])

    def test_imminent_cliff_flag(self):
        r = A().analyze(make_pos(days_to_cliff=3.0, holding_horizon_days=30.0))
        self.assertIn("IMMINENT_CLIFF", r["flags"])

    def test_thin_base_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, base_apr_pct=2.0,
                                 days_to_cliff=10.0))
        self.assertIn("THIN_BASE_RUN_RATE", r["flags"])

    def test_cliff_reached_excludes_within(self):
        r = A().analyze(make_pos(days_to_cliff=0.0))
        self.assertIn("CLIFF_REACHED", r["flags"])
        self.assertNotIn("CLIFF_WITHIN_HORIZON", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos())
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))

    def test_insufficient_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertIsNone(r["emission_share"])
        self.assertIsNone(r["live_fraction"])
        self.assertIsNone(r["forward_apr_pct"])
        self.assertIsNone(r["durable_fraction"])
        self.assertIsNone(r["base_fraction"])

    def test_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze(make_pos(vault="ZZZ", headline_apr_pct=0.0))
        self.assertEqual(r["token"], "ZZZ")

    def test_json_serializable(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        json.dumps(r)


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_durable(self):
        self.assertAlmostEqual(A()._score(1.0), 100.0, places=4)

    def test_score_zero_collapse(self):
        self.assertAlmostEqual(A()._score(0.0), 0.0, places=4)

    def test_score_half(self):
        self.assertAlmostEqual(A()._score(0.5), 50.0, places=4)

    def test_score_monotonic(self):
        prev = -1.0
        for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            s = A()._score(f)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_score_clamps_above(self):
        self.assertLessEqual(A()._score(2.0), 100.0)

    def test_score_clamps_below(self):
        self.assertGreaterEqual(A()._score(-1.0), 0.0)

    def test_score_in_range_random(self):
        for f in (0.05, 0.33, 0.71, 0.99):
            s = A()._score(f)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_score_idempotent(self):
        p = make_pos()
        s1 = A().analyze(p)["score"]
        s2 = A().analyze(p)["score"]
        self.assertEqual(s1, s2)

    def test_score_finite(self):
        for f in (0.0, 0.5, 1.0):
            self.assertTrue(math.isfinite(A()._score(f)))

    def test_durable_higher_than_collapse(self):
        durable = A().analyze(make_pos(days_to_cliff=1000.0))["score"]
        collapse = A().analyze(make_pos(headline_apr_pct=50.0, base_apr_pct=1.0,
                                        days_to_cliff=0.0))["score"]
        self.assertGreater(durable, collapse)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(days_to_cliff=1000.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))


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
        self.assertIsNone(res["aggregate"]["most_durable_vault"])

    def test_all_insufficient(self):
        res = A().analyze_portfolio([make_pos(headline_apr_pct=0.0)])
        self.assertIsNone(res["aggregate"]["most_durable_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_most_durable_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", days_to_cliff=1000.0),
            make_pos(vault="BAD", headline_apr_pct=50.0, base_apr_pct=1.0,
                     days_to_cliff=0.0),
        ])
        self.assertEqual(res["aggregate"]["most_durable_vault"], "GOOD")

    def test_least_durable_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", days_to_cliff=1000.0),
            make_pos(vault="BAD", headline_apr_pct=50.0, base_apr_pct=1.0,
                     days_to_cliff=0.0),
        ])
        self.assertEqual(res["aggregate"]["least_durable_vault"], "BAD")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(days_to_cliff=1000.0),
            make_pos(days_to_cliff=1000.0),
        ])
        self.assertAlmostEqual(res["aggregate"]["avg_score"], 100.0, places=2)

    def test_collapse_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=50.0, base_apr_pct=1.0, days_to_cliff=0.0),
            make_pos(headline_apr_pct=50.0, base_apr_pct=1.0, days_to_cliff=0.0),
            make_pos(days_to_cliff=1000.0),
        ])
        self.assertEqual(res["aggregate"]["cliff_collapse_count"], 2)

    def test_avg_forward_drop(self):
        res = A().analyze_portfolio([make_pos(days_to_cliff=1000.0)])
        self.assertEqual(res["aggregate"]["avg_forward_drop_pct"], 0.0)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for v in res["aggregate"].values():
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v))

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(days_to_cliff=1000.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["most_durable_vault"],
                         make_pos()["vault"])


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
        r = A().analyze({"vault": "X", "headline_apr_pct": "20",
                         "base_apr_pct": "10", "days_to_cliff": "10",
                         "holding_horizon_days": "30"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, base_apr_pct=1.0,
                                 days_to_cliff=0.0))
        finite_check(self, r)

    def test_huge_horizon(self):
        r = A().analyze(make_pos(holding_horizon_days=1e9, days_to_cliff=10.0))
        finite_check(self, r)
        self.assertLessEqual(r["live_fraction"], 1.0)

    def test_huge_days_to_cliff(self):
        r = A().analyze(make_pos(days_to_cliff=1e12))
        self.assertEqual(r["live_fraction"], 1.0)

    def test_nan_base(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "base_apr_pct": float("nan"), "days_to_cliff": 10.0})
        finite_check(self, r)

    def test_inf_days_to_cliff(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "base_apr_pct": 10.0,
                         "days_to_cliff": float("inf")})
        finite_check(self, r)

    def test_nan_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "base_apr_pct": 10.0, "days_to_cliff": 10.0,
                         "holding_horizon_days": float("nan")})
        self.assertEqual(r["holding_horizon_days"], DEFAULT_HOLDING_HORIZON_DAYS)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_idempotent_full(self):
        p = make_pos()
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_durable_fraction_bounded(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["durable_fraction"] is not None:
                self.assertGreaterEqual(r["durable_fraction"], 0.0)
                self.assertLessEqual(r["durable_fraction"], 1.0)


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
        for c in ("DURABLE", "MOSTLY_DURABLE", "SOFT_CLIFF", "HARD_CLIFF",
                  "CLIFF_COLLAPSE", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_no_action_and_base(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("NO_ACTION", recs)
        self.assertIn("USE_BASE_APR", recs)

    def test_demo_includes_high_emission(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("HIGH_EMISSION_SHARE" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_includes_cliff_reached(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("CLIFF_REACHED" in p["flags"] for p in res["positions"])
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
