"""
Tests for MP-1182: DeFiProtocolVaultSharePricePremiumAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_share_price_premium_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_share_price_premium_analyzer import (
    DeFiProtocolVaultSharePricePremiumAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_CONVERGENCE_HORIZON_DAYS,
    SLIGHT_PREMIUM_PCT,
    MODERATE_PREMIUM_PCT,
    HIGH_PREMIUM_PCT,
    PREMIUM_SCORE_CEILING,
    DRAG_SCORE_CEILING,
    HIGH_DRAG_PCT,
    PREMIUM_PCT_FLOOR,
    PREMIUM_PCT_CAP,
    DRAG_PCT_CAP,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    nav_per_share=1.0,
    market_price_per_share=1.02,
    expected_apr_pct=10.0,
    convergence_horizon_days=30.0,
):
    return {
        "vault": vault,
        "nav_per_share": nav_per_share,
        "market_price_per_share": market_price_per_share,
        "expected_apr_pct": expected_apr_pct,
        "convergence_horizon_days": convergence_horizon_days,
    }


def A():
    return DeFiProtocolVaultSharePricePremiumAnalyzer()


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
        self.assertLess(SLIGHT_PREMIUM_PCT, MODERATE_PREMIUM_PCT)
        self.assertLess(MODERATE_PREMIUM_PCT, HIGH_PREMIUM_PCT)
        self.assertGreater(DEFAULT_CONVERGENCE_HORIZON_DAYS, 0)
        self.assertGreater(PREMIUM_SCORE_CEILING, 0)
        self.assertGreater(DRAG_SCORE_CEILING, 0)
        self.assertGreater(HIGH_DRAG_PCT, 0)
        self.assertLess(PREMIUM_PCT_FLOOR, 0)
        self.assertGreater(PREMIUM_PCT_CAP, 0)
        self.assertGreater(DRAG_PCT_CAP, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "nav_per_share", "market_price_per_share",
            "expected_apr_pct", "convergence_horizon_days", "premium_pct",
            "is_premium", "annualized_drag_pct", "payback_days", "high_drag",
            "score", "classification", "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "nav_per_share": 1.0,
                         "market_price_per_share": 1.02})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "nav_per_share": 1.0,
                         "market_price_per_share": 1.02})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"nav_per_share": 1.0,
                         "market_price_per_share": 1.02})
        self.assertEqual(r["token"], "USDC-Vault" if False else "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "ENTER_AT_FAIR_VALUE", "ENTER_MINOR_PREMIUM", "ENTER_WITH_CAUTION",
            "WAIT_FOR_CONVERGENCE", "AVOID_PREMIUM", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "AT_OR_BELOW_NAV", "SLIGHT_PREMIUM", "MODERATE_PREMIUM",
            "HIGH_PREMIUM", "EXTREME_PREMIUM", "INSUFFICIENT_DATA",
        })

    def test_is_premium_is_bool(self):
        self.assertIsInstance(self.r["is_premium"], bool)

    def test_high_drag_is_bool(self):
        self.assertIsInstance(self.r["high_drag"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_premium_pct_positive(self):
        # (1.02 - 1.00)/1.00 * 100 = 2.0
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.02))
        self.assertAlmostEqual(r["premium_pct"], 2.0, places=4)

    def test_premium_pct_discount(self):
        # (0.95 - 1.00)/1.00 * 100 = -5.0
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=0.95))
        self.assertAlmostEqual(r["premium_pct"], -5.0, places=4)

    def test_premium_pct_zero_at_nav(self):
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.0))
        self.assertAlmostEqual(r["premium_pct"], 0.0, places=4)

    def test_premium_pct_nonunit_nav(self):
        # (110 - 100)/100 * 100 = 10.0
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=110.0))
        self.assertAlmostEqual(r["premium_pct"], 10.0, places=4)

    def test_premium_pct_capped(self):
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1e9))
        self.assertAlmostEqual(r["premium_pct"], PREMIUM_PCT_CAP, places=4)

    def test_premium_pct_floored(self):
        # market far below nav cannot go below -100 (price>0 so practically not,
        # but verify clamp floor holds)
        r = A().analyze(make_pos(nav_per_share=1e9,
                                 market_price_per_share=1e-9))
        self.assertGreaterEqual(r["premium_pct"], PREMIUM_PCT_FLOOR)

    def test_is_premium_true(self):
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertTrue(r["is_premium"])

    def test_is_premium_false_at_nav(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertFalse(r["is_premium"])

    def test_is_premium_false_discount(self):
        r = A().analyze(make_pos(market_price_per_share=0.95))
        self.assertFalse(r["is_premium"])

    def test_annualized_drag(self):
        # premium 2.0 over 30 days → 2.0 * (365/30) = 24.3333
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.02,
                                 convergence_horizon_days=30.0))
        self.assertAlmostEqual(r["annualized_drag_pct"],
                               2.0 * (365.0 / 30.0), places=4)

    def test_annualized_drag_shorter_horizon(self):
        # premium 2.0 over 10 days → 2.0 * (365/10) = 73.0
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.02,
                                 convergence_horizon_days=10.0))
        self.assertAlmostEqual(r["annualized_drag_pct"], 73.0, places=4)

    def test_annualized_drag_zero_for_discount(self):
        r = A().analyze(make_pos(market_price_per_share=0.95))
        self.assertAlmostEqual(r["annualized_drag_pct"], 0.0, places=4)

    def test_annualized_drag_zero_at_nav(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertAlmostEqual(r["annualized_drag_pct"], 0.0, places=4)

    def test_payback_days(self):
        # premium 2.0, apr 10 → 2/10 * 365 = 73.0
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.02,
                                 expected_apr_pct=10.0))
        self.assertAlmostEqual(r["payback_days"], 73.0, places=4)

    def test_payback_days_zero_for_discount(self):
        r = A().analyze(make_pos(market_price_per_share=0.95))
        self.assertAlmostEqual(r["payback_days"], 0.0, places=4)

    def test_payback_days_zero_at_nav(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertAlmostEqual(r["payback_days"], 0.0, places=4)

    def test_payback_days_none_no_apr(self):
        r = A().analyze(make_pos(market_price_per_share=1.02,
                                 expected_apr_pct=0.0))
        self.assertIsNone(r["payback_days"])

    def test_horizon_default_when_zero(self):
        r = A().analyze(make_pos(convergence_horizon_days=0.0))
        self.assertAlmostEqual(r["convergence_horizon_days"],
                               DEFAULT_CONVERGENCE_HORIZON_DAYS)

    def test_horizon_default_when_negative(self):
        r = A().analyze(make_pos(convergence_horizon_days=-10.0))
        self.assertAlmostEqual(r["convergence_horizon_days"],
                               DEFAULT_CONVERGENCE_HORIZON_DAYS)

    def test_horizon_default_when_missing(self):
        r = A().analyze({"vault": "X", "nav_per_share": 1.0,
                         "market_price_per_share": 1.02})
        self.assertAlmostEqual(r["convergence_horizon_days"],
                               DEFAULT_CONVERGENCE_HORIZON_DAYS)

    def test_expected_apr_negative_clamped(self):
        r = A().analyze(make_pos(expected_apr_pct=-5.0))
        self.assertAlmostEqual(r["expected_apr_pct"], 0.0)

    def test_nav_passthrough(self):
        r = A().analyze(make_pos(nav_per_share=1.25))
        self.assertAlmostEqual(r["nav_per_share"], 1.25)

    def test_market_passthrough(self):
        r = A().analyze(make_pos(market_price_per_share=1.30,
                                 nav_per_share=1.25))
        self.assertAlmostEqual(r["market_price_per_share"], 1.30)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.023456789,
                                 expected_apr_pct=10.3333,
                                 convergence_horizon_days=33.3333))
        for k in ("expected_apr_pct", "convergence_horizon_days",
                  "premium_pct", "annualized_drag_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_at_or_below_nav_discount(self):
        r = A().analyze(make_pos(market_price_per_share=0.98))
        self.assertEqual(r["classification"], "AT_OR_BELOW_NAV")

    def test_at_or_below_nav_exact(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertEqual(r["classification"], "AT_OR_BELOW_NAV")

    def test_slight_premium(self):
        # premium 0.5
        r = A().analyze(make_pos(market_price_per_share=1.005))
        self.assertEqual(r["classification"], "SLIGHT_PREMIUM")

    def test_moderate_premium(self):
        # premium 2.0
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_high_premium(self):
        # premium 5.0
        r = A().analyze(make_pos(market_price_per_share=1.05))
        self.assertEqual(r["classification"], "HIGH_PREMIUM")

    def test_extreme_premium(self):
        # premium 15.0
        r = A().analyze(make_pos(market_price_per_share=1.15))
        self.assertEqual(r["classification"], "EXTREME_PREMIUM")

    def test_slight_boundary(self):
        # premium exactly 1.0 → SLIGHT (nav 100, market 101)
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=101.0))
        self.assertAlmostEqual(r["premium_pct"], 1.0, places=6)
        self.assertEqual(r["classification"], "SLIGHT_PREMIUM")

    def test_moderate_boundary(self):
        # premium exactly 3.0 → MODERATE (nav 100, market 103)
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=103.0))
        self.assertAlmostEqual(r["premium_pct"], 3.0, places=6)
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_high_boundary(self):
        # premium exactly 7.0 → HIGH (nav 100, market 107)
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=107.0))
        self.assertAlmostEqual(r["premium_pct"], 7.0, places=6)
        self.assertEqual(r["classification"], "HIGH_PREMIUM")

    def test_just_above_slight(self):
        # premium 1.5 → MODERATE
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=101.5))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_just_above_high(self):
        # premium 7.5 → EXTREME
        r = A().analyze(make_pos(nav_per_share=100.0,
                                 market_price_per_share=107.5))
        self.assertEqual(r["classification"], "EXTREME_PREMIUM")

    def test_insufficient_no_nav(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_market(self):
        r = A().analyze(make_pos(market_price_per_share=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(market_price_per_share=0.98),
                    make_pos(market_price_per_share=1.005),
                    make_pos(market_price_per_share=1.02),
                    make_pos(market_price_per_share=1.05),
                    make_pos(market_price_per_share=1.15),
                    make_pos(nav_per_share=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AT_OR_BELOW_NAV", "SLIGHT_PREMIUM", "MODERATE_PREMIUM",
                "HIGH_PREMIUM", "EXTREME_PREMIUM", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_enter_fair_value(self):
        r = A().analyze(make_pos(market_price_per_share=0.98))
        self.assertEqual(r["recommendation"], "ENTER_AT_FAIR_VALUE")

    def test_enter_minor_premium(self):
        r = A().analyze(make_pos(market_price_per_share=1.005))
        self.assertEqual(r["recommendation"], "ENTER_MINOR_PREMIUM")

    def test_enter_with_caution(self):
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertEqual(r["recommendation"], "ENTER_WITH_CAUTION")

    def test_wait_for_convergence(self):
        r = A().analyze(make_pos(market_price_per_share=1.05))
        self.assertEqual(r["recommendation"], "WAIT_FOR_CONVERGENCE")

    def test_avoid_premium(self):
        r = A().analyze(make_pos(market_price_per_share=1.15))
        self.assertEqual(r["recommendation"], "AVOID_PREMIUM")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_recommendation_matches_classification(self):
        mapping = {
            "AT_OR_BELOW_NAV": "ENTER_AT_FAIR_VALUE",
            "SLIGHT_PREMIUM": "ENTER_MINOR_PREMIUM",
            "MODERATE_PREMIUM": "ENTER_WITH_CAUTION",
            "HIGH_PREMIUM": "WAIT_FOR_CONVERGENCE",
            "EXTREME_PREMIUM": "AVOID_PREMIUM",
        }
        for price in (0.98, 1.005, 1.02, 1.05, 1.15):
            r = A().analyze(make_pos(market_price_per_share=price))
            self.assertEqual(r["recommendation"],
                             mapping[r["classification"]])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_at_or_below_nav_flag(self):
        r = A().analyze(make_pos(market_price_per_share=0.98))
        self.assertIn("AT_OR_BELOW_NAV", r["flags"])

    def test_slight_flag(self):
        r = A().analyze(make_pos(market_price_per_share=1.005))
        self.assertIn("SLIGHT_PREMIUM", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertIn("MODERATE_PREMIUM", r["flags"])

    def test_high_flag(self):
        r = A().analyze(make_pos(market_price_per_share=1.05))
        self.assertIn("HIGH_PREMIUM", r["flags"])

    def test_extreme_flag(self):
        r = A().analyze(make_pos(market_price_per_share=1.15))
        self.assertIn("EXTREME_PREMIUM", r["flags"])

    def test_premium_flag_present(self):
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertIn("PREMIUM", r["flags"])

    def test_premium_flag_absent_at_nav(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertNotIn("PREMIUM", r["flags"])

    def test_discount_flag(self):
        r = A().analyze(make_pos(market_price_per_share=0.98))
        self.assertIn("DISCOUNT", r["flags"])

    def test_discount_flag_absent_at_nav(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertNotIn("DISCOUNT", r["flags"])

    def test_discount_flag_absent_premium(self):
        r = A().analyze(make_pos(market_price_per_share=1.02))
        self.assertNotIn("DISCOUNT", r["flags"])

    def test_high_drag_flag(self):
        # premium 5.0 over 10 days → drag 182.5 → high
        r = A().analyze(make_pos(market_price_per_share=1.05,
                                 convergence_horizon_days=10.0))
        self.assertIn("HIGH_ANNUALIZED_DRAG", r["flags"])

    def test_high_drag_flag_boundary(self):
        # drag exactly at HIGH_DRAG_PCT → flagged. premium p over horizon h:
        # p*365/h = 50 → with h=365, p=50; use nav 1, market 1.5 → premium 50
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.5,
                                 convergence_horizon_days=365.0))
        self.assertAlmostEqual(r["annualized_drag_pct"], 50.0, places=4)
        self.assertIn("HIGH_ANNUALIZED_DRAG", r["flags"])

    def test_high_drag_flag_absent(self):
        # small premium long horizon → low drag
        r = A().analyze(make_pos(market_price_per_share=1.005,
                                 convergence_horizon_days=365.0))
        self.assertNotIn("HIGH_ANNUALIZED_DRAG", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(market_price_per_share=0.98))
        self.assertIn("AT_OR_BELOW_NAV", r["flags"])
        self.assertNotIn("EXTREME_PREMIUM", r["flags"])

    def test_extreme_and_drag_flags_together(self):
        r = A().analyze(make_pos(market_price_per_share=1.20,
                                 convergence_horizon_days=14.0))
        self.assertIn("EXTREME_PREMIUM", r["flags"])
        self.assertIn("PREMIUM", r["flags"])
        self.assertIn("HIGH_ANNUALIZED_DRAG", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_nav(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_no_market(self):
        r = A().analyze(make_pos(market_price_per_share=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_nav(self):
        r = A().analyze(make_pos(nav_per_share=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_market(self):
        r = A().analyze(make_pos(market_price_per_share=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(nav_per_share=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_metrics_none(self):
        r = A().analyze({})
        self.assertIsNone(r["premium_pct"])
        self.assertIsNone(r["annualized_drag_pct"])
        self.assertIsNone(r["payback_days"])

    def test_insufficient_is_premium_false(self):
        r = A().analyze({})
        self.assertFalse(r["is_premium"])
        self.assertFalse(r["high_drag"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("nav_per_share", "market_price_per_share",
                  "expected_apr_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_prices(self):
        r = A().analyze(make_pos())
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_cheaper_scores_higher(self):
        cheap = A().analyze(make_pos(market_price_per_share=1.005))
        pricey = A().analyze(make_pos(market_price_per_share=1.15))
        self.assertGreater(cheap["score"], pricey["score"])

    def test_at_nav_full_score(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_discount_full_score(self):
        r = A().analyze(make_pos(market_price_per_share=0.9))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_extreme_premium_low_score(self):
        r = A().analyze(make_pos(market_price_per_share=1.20,
                                 convergence_horizon_days=7.0))
        self.assertLess(r["score"], 5.0)

    def test_known_score_no_drag_component(self):
        # premium 5.0 over 365 days → drag = 5.0 (small), apr large
        # frac = clamp(5/10)=0.5; premium_comp = 70*0.5 = 35
        # drag_frac = clamp(5/100)=0.05; drag_comp = 30*0.95 = 28.5
        # total = 63.5
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.05,
                                 convergence_horizon_days=365.0))
        frac = min(5.0 / PREMIUM_SCORE_CEILING, 1.0)
        premium_comp = 70.0 * (1.0 - frac)
        drag = 5.0 * (365.0 / 365.0)
        drag_frac = min(drag / DRAG_SCORE_CEILING, 1.0)
        drag_comp = 30.0 * (1.0 - drag_frac)
        expected = premium_comp + drag_comp
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_known_score_at_ceiling(self):
        # premium exactly 10 (ceiling) → premium_comp 0; long horizon for drag
        # drag = 10 over 365 → 10 → drag_frac 0.1 → drag_comp 27
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1.10,
                                 convergence_horizon_days=365.0))
        frac = min(10.0 / PREMIUM_SCORE_CEILING, 1.0)
        premium_comp = 70.0 * (1.0 - frac)
        drag = 10.0
        drag_frac = min(drag / DRAG_SCORE_CEILING, 1.0)
        drag_comp = 30.0 * (1.0 - drag_frac)
        expected = premium_comp + drag_comp
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(market_price_per_share=1e9,
                                 convergence_horizon_days=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(nav_per_share=1e-9,
                                 market_price_per_share=1e9,
                                 expected_apr_pct=1e9,
                                 convergence_horizon_days=1.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(market_price_per_share=0.98),
                    make_pos(market_price_per_share=1.02),
                    make_pos(market_price_per_share=1.15),
                    make_pos(nav_per_share=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(market_price_per_share=1.005),
                    make_pos(market_price_per_share=1.20,
                             convergence_horizon_days=7.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_drag_lower_score_same_premium(self):
        low_drag = A().analyze(make_pos(market_price_per_share=1.05,
                                        convergence_horizon_days=365.0))
        high_drag = A().analyze(make_pos(market_price_per_share=1.05,
                                         convergence_horizon_days=7.0))
        self.assertGreater(low_drag["score"], high_drag["score"])

    def test_monotonic_in_premium(self):
        prev = None
        for price in (1.0, 1.01, 1.03, 1.05, 1.08, 1.15):
            r = A().analyze(make_pos(market_price_per_share=price,
                                     convergence_horizon_days=365.0))
            if prev is not None:
                self.assertLessEqual(r["score"], prev + 1e-6)
            prev = r["score"]


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Cheap", market_price_per_share=0.99),
            make_pos(vault="Pricey", market_price_per_share=1.20,
                     convergence_horizon_days=7.0),
            make_pos(vault="Mid", market_price_per_share=1.02),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_cheapest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["cheapest_entry_vault"]],
                         max(scores.values()))

    def test_most_premium_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_premium_vault"]],
                         min(scores.values()))

    def test_cheapest_is_cheap(self):
        self.assertEqual(self.res["aggregate"]["cheapest_entry_vault"], "Cheap")

    def test_most_premium_is_pricey(self):
        self.assertEqual(self.res["aggregate"]["most_premium_vault"], "Pricey")

    def test_extreme_premium_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["extreme_premium_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_extreme_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", market_price_per_share=1.15),
            make_pos(vault="B", market_price_per_share=1.20),
            make_pos(vault="C", market_price_per_share=1.0),
        ])
        self.assertEqual(res["aggregate"]["extreme_premium_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["cheapest_entry_vault"])
        self.assertIsNone(res["aggregate"]["most_premium_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(nav_per_share=0.0),
            make_pos(nav_per_share=0.0),
        ])
        self.assertIsNone(res["aggregate"]["cheapest_entry_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["extreme_premium_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["cheapest_entry_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_premium_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", nav_per_share=0.0),
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
                make_pos(vault="big", nav_per_share=1e-9,
                         market_price_per_share=1e9,
                         convergence_horizon_days=1.0),
                make_pos(vault="ins", nav_per_share=0.0),
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
            "nav_per_share": "1.0",
            "market_price_per_share": "1.02",
            "expected_apr_pct": "10",
            "convergence_horizon_days": "30",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "nav_per_share": 1.0,
                         "market_price_per_share": 1.02})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(nav_per_share=0.0),
            make_pos(market_price_per_share=1.20,
                     convergence_horizon_days=7.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(market_price_per_share=1.20,
                             convergence_horizon_days=7.0),
                    make_pos(nav_per_share=0.0),
                    make_pos(market_price_per_share=1.0),
                    make_pos(convergence_horizon_days=0.0),
                    make_pos(nav_per_share=1e-9, market_price_per_share=1e9,
                             expected_apr_pct=1e9,
                             convergence_horizon_days=1.0),
                    make_pos(nav_per_share=-1e9),
                    make_pos(market_price_per_share=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(nav_per_share=1.0,
                                 market_price_per_share=1e12,
                                 expected_apr_pct=1e9,
                                 convergence_horizon_days=1.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(nav_per_share=-10.0,
                                 market_price_per_share=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_at_nav_classification(self):
        r = A().analyze(make_pos(market_price_per_share=1.0))
        self.assertEqual(r["classification"], "AT_OR_BELOW_NAV")

    def test_none_inputs_no_crash(self):
        r = A().analyze({"vault": "X", "nav_per_share": 1.0,
                         "market_price_per_share": 1.02,
                         "expected_apr_pct": None,
                         "convergence_horizon_days": None})
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_prices_insufficient(self):
        r = A().analyze({"vault": "X", "nav_per_share": None,
                         "market_price_per_share": None})
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

    def test_demo_includes_at_nav_and_extreme(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("AT_OR_BELOW_NAV", classes)
        self.assertIn("EXTREME_PREMIUM", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("AT_OR_BELOW_NAV", "SLIGHT_PREMIUM", "MODERATE_PREMIUM",
                  "HIGH_PREMIUM", "EXTREME_PREMIUM", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_enter(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_PREMIUM", recs)
        self.assertIn("ENTER_AT_FAIR_VALUE", recs)

    def test_demo_includes_discount(self):
        res = A().analyze_portfolio(_demo_positions())
        disc = any("DISCOUNT" in p["flags"] for p in res["positions"])
        self.assertTrue(disc)

    def test_demo_includes_high_drag(self):
        res = A().analyze_portfolio(_demo_positions())
        hd = any("HIGH_ANNUALIZED_DRAG" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(hd)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
