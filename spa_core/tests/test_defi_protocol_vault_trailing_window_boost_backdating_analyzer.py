"""
Tests for MP-1184: DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_trailing_window_boost_backdating_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_trailing_window_boost_backdating_analyzer import (  # noqa: E501
    DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_WINDOW_DAYS,
    FULLY_CURRENT_COVERAGE,
    MOSTLY_CURRENT_COVERAGE,
    PARTIALLY_BACKDATED_COVERAGE,
    HIGH_BOOST_SHARE_PCT,
    LARGE_OVERSTATEMENT_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=15.0,
    boost_apr_pct=6.0,
    window_days=30.0,
    boost_active_days=30.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "boost_apr_pct": boost_apr_pct,
        "window_days": window_days,
        "boost_active_days": boost_active_days,
    }


def A():
    return DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer()


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
        self.assertGreater(FULLY_CURRENT_COVERAGE, MOSTLY_CURRENT_COVERAGE)
        self.assertGreater(MOSTLY_CURRENT_COVERAGE,
                           PARTIALLY_BACKDATED_COVERAGE)
        self.assertGreater(DEFAULT_WINDOW_DAYS, 0)
        self.assertGreater(HIGH_BOOST_SHARE_PCT, 0)
        self.assertGreater(LARGE_OVERSTATEMENT_PCT, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "boost_apr_pct", "base_apr_pct",
            "window_days", "boost_active_days", "boost_share_pct",
            "coverage_frac", "expired_frac", "forward_run_rate_apr_pct",
            "apr_overstatement_pct", "overstatement_share_pct",
            "boost_expired", "high_boost_share", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 15.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "headline_apr_pct": 15.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 15.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "MINOR_BOOST_DISCOUNT", "DISCOUNT_TO_RUN_RATE",
            "USE_FORWARD_RUN_RATE", "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NO_BOOST", "FULLY_CURRENT", "MOSTLY_CURRENT",
            "PARTIALLY_BACKDATED", "HEAVILY_BACKDATED", "INSUFFICIENT_DATA",
        })

    def test_boost_expired_is_bool(self):
        self.assertIsInstance(self.r["boost_expired"], bool)

    def test_high_boost_share_is_bool(self):
        self.assertIsInstance(self.r["high_boost_share"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=15.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 15.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_base_apr(self):
        # 15 - 6 = 9
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0))
        self.assertAlmostEqual(r["base_apr_pct"], 9.0, places=4)

    def test_boost_clamped_to_headline(self):
        # boost 20 > headline 15 → clamped to 15, base 0
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=20.0))
        self.assertAlmostEqual(r["boost_apr_pct"], 15.0, places=4)
        self.assertAlmostEqual(r["base_apr_pct"], 0.0, places=4)

    def test_boost_share_pct(self):
        # boost 6 / headline 15 = 40%
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0))
        self.assertAlmostEqual(r["boost_share_pct"], 40.0, places=4)

    def test_boost_share_full(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, boost_apr_pct=10.0))
        self.assertAlmostEqual(r["boost_share_pct"], 100.0, places=4)

    def test_coverage_frac(self):
        # 15 / 30 = 0.5
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["coverage_frac"], 0.5, places=4)

    def test_coverage_full(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertAlmostEqual(r["coverage_frac"], 1.0, places=4)

    def test_coverage_clamped_when_active_exceeds_window(self):
        # active 40 > window 30 → clamp to 30 → coverage 1.0
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=40.0))
        self.assertAlmostEqual(r["coverage_frac"], 1.0, places=4)
        self.assertAlmostEqual(r["boost_active_days"], 30.0, places=4)

    def test_expired_frac(self):
        # coverage 0.5 → expired 0.5
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["expired_frac"], 0.5, places=4)

    def test_expired_frac_zero_when_full_coverage(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertAlmostEqual(r["expired_frac"], 0.0, places=4)

    def test_forward_run_rate(self):
        # base = 15-6 = 9; boost 6; coverage 0.5 → 9 + 6*0.5 = 12
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["forward_run_rate_apr_pct"], 12.0, places=4)

    def test_forward_run_rate_full_coverage_equals_headline(self):
        # coverage 1.0 → run-rate = base + boost = headline
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=30.0))
        self.assertAlmostEqual(r["forward_run_rate_apr_pct"], 15.0, places=4)

    def test_forward_run_rate_zero_coverage_equals_base(self):
        # coverage 0 → run-rate = base
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=0.0))
        self.assertAlmostEqual(r["forward_run_rate_apr_pct"], 9.0, places=4)

    def test_apr_overstatement(self):
        # headline 15 - run-rate 12 = 3 (= boost*expired = 6*0.5)
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["apr_overstatement_pct"], 3.0, places=4)

    def test_apr_overstatement_equals_boost_times_expired(self):
        # boost 8, expired 0.7 → overstatement 5.6
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=8.0,
                                 window_days=30.0, boost_active_days=9.0))
        # coverage 9/30=0.3, expired 0.7 → 8*0.7=5.6
        self.assertAlmostEqual(r["apr_overstatement_pct"], 5.6, places=4)

    def test_apr_overstatement_zero_full_coverage(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertAlmostEqual(r["apr_overstatement_pct"], 0.0, places=4)

    def test_overstatement_share_pct(self):
        # overstatement 3 / headline 15 = 20%
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["overstatement_share_pct"], 20.0, places=4)

    def test_boost_expired_true(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertTrue(r["boost_expired"])

    def test_boost_expired_false_full_coverage(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertFalse(r["boost_expired"])

    def test_window_default_when_zero(self):
        r = A().analyze(make_pos(window_days=0.0, boost_active_days=0.0))
        self.assertAlmostEqual(r["window_days"], DEFAULT_WINDOW_DAYS)

    def test_window_default_when_negative(self):
        r = A().analyze(make_pos(window_days=-5.0, boost_active_days=0.0))
        self.assertAlmostEqual(r["window_days"], DEFAULT_WINDOW_DAYS)

    def test_window_default_when_missing(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 15.0,
                         "boost_apr_pct": 6.0, "boost_active_days": 30.0})
        self.assertAlmostEqual(r["window_days"], DEFAULT_WINDOW_DAYS)

    def test_boost_negative_clamped(self):
        r = A().analyze(make_pos(boost_apr_pct=-3.0))
        self.assertAlmostEqual(r["boost_apr_pct"], 0.0)

    def test_boost_active_days_negative_clamped(self):
        r = A().analyze(make_pos(boost_active_days=-10.0))
        self.assertAlmostEqual(r["boost_active_days"], 0.0)

    def test_high_boost_share_true(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0))
        self.assertTrue(r["high_boost_share"])

    def test_high_boost_share_boundary(self):
        # boost share exactly 50% → flagged
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=10.0))
        self.assertTrue(r["high_boost_share"])

    def test_high_boost_share_false(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=4.0))
        self.assertFalse(r["high_boost_share"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=15.3333,
                                 boost_apr_pct=6.1111,
                                 window_days=30.0, boost_active_days=13.3333))
        for k in ("headline_apr_pct", "boost_apr_pct", "base_apr_pct",
                  "window_days", "boost_active_days", "boost_share_pct",
                  "coverage_frac", "expired_frac", "forward_run_rate_apr_pct",
                  "apr_overstatement_pct", "overstatement_share_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_no_boost(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertEqual(r["classification"], "NO_BOOST")

    def test_fully_current(self):
        # coverage 1.0
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertEqual(r["classification"], "FULLY_CURRENT")

    def test_fully_current_boundary(self):
        # coverage exactly 0.95
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=95.0))
        self.assertEqual(r["classification"], "FULLY_CURRENT")

    def test_mostly_current(self):
        # coverage 0.8
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=24.0))
        self.assertEqual(r["classification"], "MOSTLY_CURRENT")

    def test_mostly_current_boundary(self):
        # coverage exactly 0.75
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=75.0))
        self.assertEqual(r["classification"], "MOSTLY_CURRENT")

    def test_partially_backdated(self):
        # coverage 0.5
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertEqual(r["classification"], "PARTIALLY_BACKDATED")

    def test_partially_backdated_boundary(self):
        # coverage exactly 0.40
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=40.0))
        self.assertEqual(r["classification"], "PARTIALLY_BACKDATED")

    def test_heavily_backdated(self):
        # coverage 0.1
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=3.0))
        self.assertEqual(r["classification"], "HEAVILY_BACKDATED")

    def test_just_below_partially(self):
        # coverage 0.39 → HEAVILY_BACKDATED
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=39.0))
        self.assertEqual(r["classification"], "HEAVILY_BACKDATED")

    def test_just_below_mostly(self):
        # coverage 0.74 → PARTIALLY_BACKDATED
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=74.0))
        self.assertEqual(r["classification"], "PARTIALLY_BACKDATED")

    def test_just_below_fully(self):
        # coverage 0.94 → MOSTLY_CURRENT
        r = A().analyze(make_pos(window_days=100.0, boost_active_days=94.0))
        self.assertEqual(r["classification"], "MOSTLY_CURRENT")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(boost_apr_pct=0.0),
                    make_pos(boost_active_days=30.0),
                    make_pos(boost_active_days=24.0),
                    make_pos(boost_active_days=15.0),
                    make_pos(boost_active_days=3.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NO_BOOST", "FULLY_CURRENT", "MOSTLY_CURRENT",
                "PARTIALLY_BACKDATED", "HEAVILY_BACKDATED",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_no_boost(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_fully_current(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_minor_discount_mostly_current(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=24.0))
        self.assertEqual(r["recommendation"], "MINOR_BOOST_DISCOUNT")

    def test_discount_partially_backdated(self):
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=4.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_TO_RUN_RATE")

    def test_use_forward_heavily_backdated(self):
        # heavily backdated but low boost share → USE_FORWARD_RUN_RATE
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=4.0,
                                 window_days=30.0, boost_active_days=3.0))
        self.assertEqual(r["recommendation"], "USE_FORWARD_RUN_RATE")

    def test_avoid_heavily_backdated_high_share_override(self):
        # heavily backdated + high boost share → AVOID override
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=3.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_high_share_partially_no_override(self):
        # high boost share but only PARTIALLY_BACKDATED → no override
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_TO_RUN_RATE")

    def test_high_share_fully_current_no_override(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=30.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_no_boost_flag(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertIn("NO_BOOST", r["flags"])

    def test_fully_current_flag(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertIn("FULLY_CURRENT", r["flags"])

    def test_mostly_current_flag(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=24.0))
        self.assertIn("MOSTLY_CURRENT", r["flags"])

    def test_partially_backdated_flag(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertIn("PARTIALLY_BACKDATED", r["flags"])

    def test_heavily_backdated_flag(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=3.0))
        self.assertIn("HEAVILY_BACKDATED", r["flags"])

    def test_boost_expired_flag(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=15.0))
        self.assertIn("BOOST_EXPIRED", r["flags"])

    def test_boost_expired_flag_absent_full_coverage(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertNotIn("BOOST_EXPIRED", r["flags"])

    def test_boost_expired_flag_absent_no_boost(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertNotIn("BOOST_EXPIRED", r["flags"])

    def test_high_boost_share_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0))
        self.assertIn("HIGH_BOOST_SHARE", r["flags"])

    def test_high_boost_share_flag_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=10.0))
        self.assertIn("HIGH_BOOST_SHARE", r["flags"])

    def test_high_boost_share_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=4.0))
        self.assertNotIn("HIGH_BOOST_SHARE", r["flags"])

    def test_large_overstatement_flag(self):
        # overstatement share >= 25%
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=3.0))
        self.assertIn("LARGE_OVERSTATEMENT", r["flags"])

    def test_large_overstatement_flag_absent(self):
        # full coverage → 0 overstatement
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertNotIn("LARGE_OVERSTATEMENT", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertIn("FULLY_CURRENT", r["flags"])
        self.assertNotIn("HEAVILY_BACKDATED", r["flags"])

    def test_heavily_and_high_share_flags_together(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=3.0))
        self.assertIn("HEAVILY_BACKDATED", r["flags"])
        self.assertIn("HIGH_BOOST_SHARE", r["flags"])
        self.assertIn("BOOST_EXPIRED", r["flags"])
        self.assertIn("LARGE_OVERSTATEMENT", r["flags"])


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
        self.assertIsNone(r["coverage_frac"])
        self.assertIsNone(r["expired_frac"])
        self.assertIsNone(r["forward_run_rate_apr_pct"])
        self.assertIsNone(r["apr_overstatement_pct"])
        self.assertIsNone(r["overstatement_share_pct"])

    def test_insufficient_bools_false(self):
        r = A().analyze({})
        self.assertFalse(r["boost_expired"])
        self.assertFalse(r["high_boost_share"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "boost_apr_pct", "base_apr_pct",
                  "boost_active_days", "boost_share_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=15.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_no_boost_full_score(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_full_coverage_full_score(self):
        # coverage 1.0 → 60 + 40 = 100
        r = A().analyze(make_pos(window_days=30.0, boost_active_days=30.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_more_current_scores_higher(self):
        current = A().analyze(make_pos(window_days=30.0,
                                       boost_active_days=27.0))
        backdated = A().analyze(make_pos(window_days=30.0,
                                         boost_active_days=3.0))
        self.assertGreater(current["score"], backdated["score"])

    def test_known_score(self):
        # headline 15, boost 6, coverage 0.5:
        # persistence 60*0.5=30; overstatement 3/15=20% →
        # magnitude 40*(1-0.2)=32 → total 62
        r = A().analyze(make_pos(headline_apr_pct=15.0, boost_apr_pct=6.0,
                                 window_days=30.0, boost_active_days=15.0))
        self.assertAlmostEqual(r["score"], 62.0, places=2)

    def test_known_score_heavy(self):
        # headline 20, boost 12, coverage 0.1:
        # persistence 60*0.1=6; overstatement = 12*0.9=10.8; share 10.8/20=54%
        # magnitude 40*(1-0.54)=18.4 → total 24.4
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=12.0,
                                 window_days=30.0, boost_active_days=3.0))
        self.assertAlmostEqual(r["score"], 24.4, places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=20.0,
                                 window_days=30.0, boost_active_days=0.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, boost_apr_pct=1e9,
                                 window_days=1e9, boost_active_days=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(boost_apr_pct=0.0),
                    make_pos(boost_active_days=30.0),
                    make_pos(boost_active_days=3.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(boost_active_days=30.0),
                    make_pos(headline_apr_pct=20.0, boost_apr_pct=18.0,
                             window_days=30.0, boost_active_days=1.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_larger_boost_share_lower_score_when_backdated(self):
        low = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=4.0,
                                   window_days=30.0, boost_active_days=6.0))
        high = A().analyze(make_pos(headline_apr_pct=20.0, boost_apr_pct=16.0,
                                    window_days=30.0, boost_active_days=6.0))
        self.assertGreater(low["score"], high["score"])

    def test_confidence_not_present(self):
        # this module does not expose confidence_pct
        r = A().analyze(make_pos())
        self.assertNotIn("confidence_pct", r)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Current", window_days=30.0, boost_active_days=30.0),
            make_pos(vault="Backdated", headline_apr_pct=20.0,
                     boost_apr_pct=16.0, window_days=30.0,
                     boost_active_days=2.0),
            make_pos(vault="Mid", window_days=30.0, boost_active_days=18.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_current_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_current_vault"]],
                         max(scores.values()))

    def test_most_backdated_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_backdated_vault"]],
                         min(scores.values()))

    def test_most_current_token(self):
        self.assertEqual(self.res["aggregate"]["most_current_vault"],
                         "Current")

    def test_most_backdated_token(self):
        self.assertEqual(self.res["aggregate"]["most_backdated_vault"],
                         "Backdated")

    def test_heavily_backdated_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["heavily_backdated_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_heavily_backdated_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", window_days=30.0, boost_active_days=3.0),
            make_pos(vault="B", window_days=30.0, boost_active_days=2.0),
            make_pos(vault="C", window_days=30.0, boost_active_days=30.0),
        ])
        self.assertEqual(res["aggregate"]["heavily_backdated_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_current_vault"])
        self.assertIsNone(res["aggregate"]["most_backdated_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_current_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["heavily_backdated_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_current_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_backdated_vault"], "Solo")

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
                         boost_apr_pct=1e9, window_days=1e9,
                         boost_active_days=1e9),
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
            "headline_apr_pct": "15",
            "boost_apr_pct": "6",
            "window_days": "30",
            "boost_active_days": "15",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 15.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(window_days=30.0, boost_active_days=3.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(window_days=30.0, boost_active_days=3.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(boost_apr_pct=0.0),
                    make_pos(window_days=0.0),
                    make_pos(headline_apr_pct=1e9, boost_apr_pct=1e9,
                             window_days=1e9, boost_active_days=1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(boost_apr_pct=-1e9, boost_active_days=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, boost_apr_pct=1e9,
                                 window_days=1e9, boost_active_days=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(boost_apr_pct=-10.0,
                                 boost_active_days=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_boost_no_boost(self):
        r = A().analyze(make_pos(boost_apr_pct=0.0, boost_active_days=0.0))
        self.assertEqual(r["classification"], "NO_BOOST")

    def test_none_inputs_no_crash(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 15.0,
                         "boost_apr_pct": None,
                         "window_days": None,
                         "boost_active_days": None})
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

    def test_demo_includes_no_boost_and_heavily(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NO_BOOST", classes)
        self.assertIn("HEAVILY_BACKDATED", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NO_BOOST", "FULLY_CURRENT", "MOSTLY_CURRENT",
                  "PARTIALLY_BACKDATED", "HEAVILY_BACKDATED",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_HEADLINE", recs)

    def test_demo_includes_boost_expired(self):
        res = A().analyze_portfolio(_demo_positions())
        be = any("BOOST_EXPIRED" in p["flags"] for p in res["positions"])
        self.assertTrue(be)

    def test_demo_includes_high_boost_share(self):
        res = A().analyze_portfolio(_demo_positions())
        hv = any("HIGH_BOOST_SHARE" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(hv)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
