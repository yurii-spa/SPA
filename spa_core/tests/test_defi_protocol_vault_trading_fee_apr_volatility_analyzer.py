"""
Tests for MP-1179: DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_trading_fee_apr_volatility_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_trading_fee_apr_volatility_analyzer import (
    DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    STABLE_VOLATILITY,
    MODERATE_VOLATILITY,
    HIGH_VOLATILITY,
    FEE_APR_EPSILON,
    NORM_VOL_CAP,
    VOLUME_DECLINING_PCT,
    VOLUME_RISING_PCT,
    VOLUME_COLLAPSE_PCT,
    VOL_CEILING,
    VOLUME_DROP_CEILING,
    HIGH_FEE_SHARE_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=16.0,
    fee_apr_pct=8.0,
    fee_apr_volatility_pct=2.4,
    volume_change_pct=0.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "fee_apr_pct": fee_apr_pct,
        "fee_apr_volatility_pct": fee_apr_volatility_pct,
        "volume_change_pct": volume_change_pct,
    }


def A():
    return DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer()


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
        self.assertLess(STABLE_VOLATILITY, MODERATE_VOLATILITY)
        self.assertLess(MODERATE_VOLATILITY, HIGH_VOLATILITY)
        self.assertGreater(FEE_APR_EPSILON, 0)
        self.assertGreater(NORM_VOL_CAP, 0)
        self.assertLess(VOLUME_DECLINING_PCT, 0)
        self.assertGreater(VOLUME_RISING_PCT, 0)
        self.assertLess(VOLUME_COLLAPSE_PCT, 0)
        self.assertGreater(VOL_CEILING, 0)
        self.assertGreater(VOLUME_DROP_CEILING, 0)
        self.assertEqual(HIGH_FEE_SHARE_PCT, 50.0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "base_apr_pct", "fee_apr_pct",
            "fee_share_pct", "fee_apr_volatility_pct", "volume_change_pct",
            "normalized_volatility", "sustainable_fee_apr_pct",
            "fee_apr_at_risk_pct", "realized_headline_apr_pct",
            "volume_declining", "volume_rising", "high_fee_share",
            "volume_collapse", "score", "classification", "recommendation",
            "grade", "flags",
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
            "TRUST_HEADLINE", "MINOR_FEE_DISCOUNT",
            "DISCOUNT_FEE_LAYER", "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NO_FEE_YIELD", "STABLE_FEE_YIELD", "MODERATE_VOLATILITY",
            "HIGH_VOLATILITY", "UNSTABLE", "INSUFFICIENT_DATA",
        })

    def test_volume_declining_is_bool(self):
        self.assertIsInstance(self.r["volume_declining"], bool)

    def test_volume_rising_is_bool(self):
        self.assertIsInstance(self.r["volume_rising"], bool)

    def test_high_fee_share_is_bool(self):
        self.assertIsInstance(self.r["high_fee_share"], bool)

    def test_volume_collapse_is_bool(self):
        self.assertIsInstance(self.r["volume_collapse"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 16.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_fee_negative_clamped_no_fee_yield(self):
        r = A().analyze(make_pos(fee_apr_pct=-2.0))
        self.assertEqual(r["classification"], "NO_FEE_YIELD")

    def test_fee_clamped_to_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, fee_apr_pct=15.0))
        self.assertAlmostEqual(r["fee_apr_pct"], 10.0)

    def test_base_apr(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0))
        self.assertAlmostEqual(r["base_apr_pct"], 8.0, places=4)

    def test_fee_share(self):
        # 8 / 16 * 100 = 50
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0))
        self.assertAlmostEqual(r["fee_share_pct"], 50.0, places=4)

    def test_normalized_volatility(self):
        # 2.4 / 8 = 0.3
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=2.4))
        self.assertAlmostEqual(r["normalized_volatility"], 0.3, places=4)

    def test_normalized_volatility_capped(self):
        # huge vol vs small fee → caps at NORM_VOL_CAP
        r = A().analyze(make_pos(fee_apr_pct=0.5, fee_apr_volatility_pct=1e6))
        self.assertAlmostEqual(r["normalized_volatility"], NORM_VOL_CAP,
                               places=4)

    def test_sustainable_fee_apr_no_decline(self):
        # fee 8, norm_vol 0.3, no decline:
        # 8 * (1-0.3) * (1-0) = 5.6
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=2.4,
                                 volume_change_pct=0.0))
        self.assertAlmostEqual(r["sustainable_fee_apr_pct"], 5.6, places=4)

    def test_sustainable_fee_apr_with_decline(self):
        # fee 8, norm_vol 0.3, volume -20:
        # trend_haircut = clamp(20/100, 0, 0.5) = 0.2
        # 8 * 0.7 * 0.8 = 4.48
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=2.4,
                                 volume_change_pct=-20.0))
        self.assertAlmostEqual(r["sustainable_fee_apr_pct"], 4.48, places=4)

    def test_trend_haircut_capped(self):
        # volume -200 → drop 200, haircut clamps to 0.5
        # fee 8, norm_vol 0.3 → 8*0.7*0.5 = 2.8
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=2.4,
                                 volume_change_pct=-200.0))
        self.assertAlmostEqual(r["sustainable_fee_apr_pct"], 2.8, places=4)

    def test_fee_apr_at_risk(self):
        # 8 - 5.6 = 2.4
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=2.4,
                                 volume_change_pct=0.0))
        self.assertAlmostEqual(r["fee_apr_at_risk_pct"], 2.4, places=4)

    def test_realized_headline_apr(self):
        # base 8 + sustainable 5.6 = 13.6
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0,
                                 fee_apr_volatility_pct=2.4,
                                 volume_change_pct=0.0))
        self.assertAlmostEqual(r["realized_headline_apr_pct"], 13.6, places=4)

    def test_volume_declining_true(self):
        r = A().analyze(make_pos(volume_change_pct=-5.0))
        self.assertTrue(r["volume_declining"])

    def test_volume_declining_boundary(self):
        # exactly -1.0 is NOT below -1.0
        r = A().analyze(make_pos(volume_change_pct=-1.0))
        self.assertFalse(r["volume_declining"])

    def test_volume_declining_false(self):
        r = A().analyze(make_pos(volume_change_pct=5.0))
        self.assertFalse(r["volume_declining"])

    def test_volume_rising_true(self):
        r = A().analyze(make_pos(volume_change_pct=5.0))
        self.assertTrue(r["volume_rising"])

    def test_volume_rising_boundary(self):
        # exactly 1.0 is NOT above 1.0
        r = A().analyze(make_pos(volume_change_pct=1.0))
        self.assertFalse(r["volume_rising"])

    def test_volume_rising_false(self):
        r = A().analyze(make_pos(volume_change_pct=-5.0))
        self.assertFalse(r["volume_rising"])

    def test_volume_collapse_true(self):
        r = A().analyze(make_pos(volume_change_pct=-50.0))
        self.assertTrue(r["volume_collapse"])

    def test_volume_collapse_boundary(self):
        # exactly -40.0
        r = A().analyze(make_pos(volume_change_pct=-40.0))
        self.assertTrue(r["volume_collapse"])

    def test_volume_collapse_false(self):
        r = A().analyze(make_pos(volume_change_pct=-30.0))
        self.assertFalse(r["volume_collapse"])

    def test_high_fee_share_true(self):
        # fee 12 / headline 16 = 75% >= 50
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=12.0))
        self.assertTrue(r["high_fee_share"])

    def test_high_fee_share_boundary(self):
        # fee 8 / 16 = 50%
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0))
        self.assertTrue(r["high_fee_share"])

    def test_high_fee_share_false(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=2.0))
        self.assertFalse(r["high_fee_share"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=16.3333,
                                 fee_apr_pct=8.1111,
                                 fee_apr_volatility_pct=2.5555,
                                 volume_change_pct=-13.3333))
        for k in ("headline_apr_pct", "base_apr_pct", "fee_apr_pct",
                  "fee_share_pct", "fee_apr_volatility_pct",
                  "volume_change_pct", "normalized_volatility",
                  "sustainable_fee_apr_pct", "fee_apr_at_risk_pct",
                  "realized_headline_apr_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_no_fee_yield(self):
        r = A().analyze(make_pos(fee_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_FEE_YIELD")

    def test_stable(self):
        # norm_vol 0.8/8 = 0.1
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.8))
        self.assertEqual(r["classification"], "STABLE_FEE_YIELD")

    def test_moderate(self):
        # norm_vol 3.2/8 = 0.4
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=3.2))
        self.assertEqual(r["classification"], "MODERATE_VOLATILITY")

    def test_high(self):
        # norm_vol 5.6/8 = 0.7
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=5.6))
        self.assertEqual(r["classification"], "HIGH_VOLATILITY")

    def test_unstable(self):
        # norm_vol 12/8 = 1.5
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=12.0))
        self.assertEqual(r["classification"], "UNSTABLE")

    def test_stable_boundary(self):
        # norm_vol exactly STABLE_VOLATILITY=0.20: vol 1.6 / 8
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=1.6))
        self.assertEqual(r["classification"], "STABLE_FEE_YIELD")

    def test_moderate_boundary(self):
        # norm_vol exactly MODERATE_VOLATILITY=0.50: vol 4.0 / 8
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=4.0))
        self.assertEqual(r["classification"], "MODERATE_VOLATILITY")

    def test_high_boundary(self):
        # norm_vol exactly HIGH_VOLATILITY=1.0: vol 8.0 / 8
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=8.0))
        self.assertEqual(r["classification"], "HIGH_VOLATILITY")

    def test_above_high_unstable(self):
        # norm_vol 1.01: vol 8.08 / 8
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=8.08))
        self.assertEqual(r["classification"], "UNSTABLE")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(fee_apr_pct=0.0),
                    make_pos(fee_apr_volatility_pct=0.8),
                    make_pos(fee_apr_volatility_pct=3.2),
                    make_pos(fee_apr_volatility_pct=12.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NO_FEE_YIELD", "STABLE_FEE_YIELD", "MODERATE_VOLATILITY",
                "HIGH_VOLATILITY", "UNSTABLE", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_headline_no_fee_yield(self):
        r = A().analyze(make_pos(fee_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_headline_stable(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.8))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_minor_discount_moderate(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=3.2))
        self.assertEqual(r["recommendation"], "MINOR_FEE_DISCOUNT")

    def test_discount_high(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=5.6))
        self.assertEqual(r["recommendation"], "DISCOUNT_FEE_LAYER")

    def test_avoid_unstable(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=12.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_severe_collapse_override(self):
        # stable volatility but severe collapse with high fee share → AVOID
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=12.0,
                                 fee_apr_volatility_pct=0.8,
                                 volume_change_pct=-50.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_collapse_low_fee_share_no_override(self):
        # severe collapse but low fee share → no override (stable trusts)
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=2.0,
                                 fee_apr_volatility_pct=0.2,
                                 volume_change_pct=-50.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_no_fee_yield_flag(self):
        r = A().analyze(make_pos(fee_apr_pct=0.0))
        self.assertIn("NO_FEE_YIELD", r["flags"])

    def test_stable_flag(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.8))
        self.assertIn("STABLE_FEE_YIELD", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=3.2))
        self.assertIn("MODERATE_VOLATILITY", r["flags"])

    def test_high_flag(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=5.6))
        self.assertIn("HIGH_VOLATILITY", r["flags"])

    def test_unstable_flag(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=12.0))
        self.assertIn("UNSTABLE", r["flags"])

    def test_volume_declining_flag(self):
        r = A().analyze(make_pos(volume_change_pct=-10.0))
        self.assertIn("VOLUME_DECLINING", r["flags"])

    def test_volume_declining_flag_absent(self):
        r = A().analyze(make_pos(volume_change_pct=10.0))
        self.assertNotIn("VOLUME_DECLINING", r["flags"])

    def test_volume_rising_flag(self):
        r = A().analyze(make_pos(volume_change_pct=10.0))
        self.assertIn("VOLUME_RISING", r["flags"])

    def test_volume_rising_flag_absent(self):
        r = A().analyze(make_pos(volume_change_pct=-10.0))
        self.assertNotIn("VOLUME_RISING", r["flags"])

    def test_high_fee_share_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=12.0,
                                 fee_apr_volatility_pct=0.8))
        self.assertIn("HIGH_FEE_SHARE", r["flags"])

    def test_high_fee_share_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=2.0,
                                 fee_apr_volatility_pct=0.2))
        self.assertNotIn("HIGH_FEE_SHARE", r["flags"])

    def test_volume_collapse_flag(self):
        r = A().analyze(make_pos(volume_change_pct=-50.0))
        self.assertIn("VOLUME_COLLAPSE", r["flags"])

    def test_volume_collapse_flag_absent(self):
        r = A().analyze(make_pos(volume_change_pct=-30.0))
        self.assertNotIn("VOLUME_COLLAPSE", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.8))
        self.assertIn("STABLE_FEE_YIELD", r["flags"])
        self.assertNotIn("UNSTABLE", r["flags"])


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
        self.assertIsNone(r["fee_share_pct"])

    def test_insufficient_projection_none(self):
        r = A().analyze({})
        self.assertIsNone(r["normalized_volatility"])
        self.assertIsNone(r["sustainable_fee_apr_pct"])
        self.assertIsNone(r["fee_apr_at_risk_pct"])
        self.assertIsNone(r["realized_headline_apr_pct"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["volume_declining"])
        self.assertFalse(r["volume_rising"])
        self.assertFalse(r["high_fee_share"])
        self.assertFalse(r["volume_collapse"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "base_apr_pct", "fee_apr_pct",
                  "fee_apr_volatility_pct", "volume_change_pct", "score"):
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
    def test_more_stable_scores_higher(self):
        stable = A().analyze(make_pos(fee_apr_pct=8.0,
                                      fee_apr_volatility_pct=0.8))
        volatile = A().analyze(make_pos(fee_apr_pct=8.0,
                                        fee_apr_volatility_pct=12.0))
        self.assertGreater(stable["score"], volatile["score"])

    def test_no_fee_yield_full_score(self):
        r = A().analyze(make_pos(fee_apr_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_tiny_volatility_near_full_score(self):
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.0,
                                 volume_change_pct=0.0))
        self.assertGreater(r["score"], 99.0)

    def test_stable_volume_higher_than_declining(self):
        rising = A().analyze(make_pos(fee_apr_pct=8.0,
                                      fee_apr_volatility_pct=2.4,
                                      volume_change_pct=10.0))
        declining = A().analyze(make_pos(fee_apr_pct=8.0,
                                         fee_apr_volatility_pct=2.4,
                                         volume_change_pct=-40.0))
        self.assertGreater(rising["score"], declining["score"])

    def test_worst_case_low_score(self):
        # huge volatility + collapse + high fee share
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=16.0,
                                 fee_apr_volatility_pct=1e6,
                                 volume_change_pct=-100.0))
        self.assertLess(r["score"], 5.0)

    def test_known_score_no_decline(self):
        # norm_vol 0.3, no decline, fee_share 8/16=50%:
        # stability_comp 60*(1-0.3)=42; trend_comp 40-0 = 40 → 82
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0,
                                 fee_apr_volatility_pct=2.4,
                                 volume_change_pct=0.0))
        expected = 60.0 * (1.0 - 0.3) + 40.0
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_known_score_with_decline(self):
        # norm_vol 0.3, volume -25, fee_share 50%:
        # stability 60*0.7=42
        # trend_penalty = clamp(25/50,0,1)*0.5 = 0.25; trend_comp 40-40*0.25=30
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=8.0,
                                 fee_apr_volatility_pct=2.4,
                                 volume_change_pct=-25.0))
        expected = 60.0 * 0.7 + (40.0 - 40.0 * (25.0 / 50.0) * 0.5)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, fee_apr_pct=16.0,
                                 fee_apr_volatility_pct=1e6,
                                 volume_change_pct=-100.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, fee_apr_pct=1e9,
                                 fee_apr_volatility_pct=1e9,
                                 volume_change_pct=-1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(fee_apr_pct=0.0),
                    make_pos(fee_apr_volatility_pct=2.4),
                    make_pos(fee_apr_volatility_pct=12.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(fee_apr_pct=0.0),
                    make_pos(headline_apr_pct=16.0, fee_apr_pct=16.0,
                             fee_apr_volatility_pct=1e6,
                             volume_change_pct=-100.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_fee_share_lower_score_on_decline(self):
        # same vol+decline, but more headline on fee layer → lower score
        low_share = A().analyze(make_pos(headline_apr_pct=20.0, fee_apr_pct=2.0,
                                         fee_apr_volatility_pct=0.6,
                                         volume_change_pct=-50.0))
        high_share = A().analyze(make_pos(headline_apr_pct=20.0,
                                          fee_apr_pct=18.0,
                                          fee_apr_volatility_pct=5.4,
                                          volume_change_pct=-50.0))
        self.assertGreater(low_share["score"], high_share["score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Stable", fee_apr_pct=8.0,
                     fee_apr_volatility_pct=0.8),
            make_pos(vault="Volatile", fee_apr_pct=8.0,
                     fee_apr_volatility_pct=14.0),
            make_pos(vault="Mid", fee_apr_pct=8.0,
                     fee_apr_volatility_pct=3.2),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_stable_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_stable_vault"]],
                         max(scores.values()))

    def test_most_volatile_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_volatile_vault"]],
                         min(scores.values()))

    def test_most_stable_is_stable(self):
        self.assertEqual(self.res["aggregate"]["most_stable_vault"], "Stable")

    def test_most_volatile_is_volatile(self):
        self.assertEqual(self.res["aggregate"]["most_volatile_vault"],
                         "Volatile")

    def test_unstable_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["unstable_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_unstable_count_only_unstable(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", fee_apr_pct=8.0, fee_apr_volatility_pct=12.0),
            make_pos(vault="B", fee_apr_pct=8.0, fee_apr_volatility_pct=14.0),
            make_pos(vault="C", fee_apr_pct=8.0, fee_apr_volatility_pct=0.8),
        ])
        self.assertEqual(res["aggregate"]["unstable_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_stable_vault"])
        self.assertIsNone(res["aggregate"]["most_volatile_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_stable_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["unstable_count"], 0)

    def test_no_fee_yield_counts_as_scored(self):
        # NO_FEE_YIELD is not INSUFFICIENT → participates in aggregate
        res = A().analyze_portfolio([
            make_pos(vault="NoFee", fee_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["most_stable_vault"], "NoFee")

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_stable_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_volatile_vault"], "Solo")

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
                         fee_apr_pct=1e9, fee_apr_volatility_pct=1e9,
                         volume_change_pct=-1e9),
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
            "fee_apr_pct": "8",
            "fee_apr_volatility_pct": "2.4",
            "volume_change_pct": "-10",
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
            make_pos(fee_apr_volatility_pct=12.0, volume_change_pct=-50.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(fee_apr_volatility_pct=12.0,
                             volume_change_pct=-50.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(fee_apr_pct=0.0),
                    make_pos(fee_apr_pct=0.001, fee_apr_volatility_pct=1e6),
                    make_pos(headline_apr_pct=1e9, fee_apr_pct=1e9,
                             fee_apr_volatility_pct=1e9,
                             volume_change_pct=-1e9),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(fee_apr_pct=-1e9, fee_apr_volatility_pct=-1e9,
                             volume_change_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, fee_apr_pct=1e9,
                                 fee_apr_volatility_pct=1e9,
                                 volume_change_pct=-1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(fee_apr_pct=-10.0,
                                 fee_apr_volatility_pct=-8.0,
                                 volume_change_pct=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_fee_no_fee_yield(self):
        r = A().analyze(make_pos(fee_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_FEE_YIELD")

    def test_positive_volume_change_no_haircut(self):
        # rising volume → no trend haircut on sustainable fee
        r = A().analyze(make_pos(fee_apr_pct=8.0, fee_apr_volatility_pct=0.0,
                                 volume_change_pct=50.0))
        self.assertAlmostEqual(r["sustainable_fee_apr_pct"], 8.0, places=4)


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

    def test_demo_includes_no_fee_yield_and_unstable(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NO_FEE_YIELD", classes)
        self.assertIn("UNSTABLE", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NO_FEE_YIELD", "STABLE_FEE_YIELD", "MODERATE_VOLATILITY",
                  "HIGH_VOLATILITY", "UNSTABLE", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_HEADLINE", recs)

    def test_demo_includes_volume_collapse(self):
        res = A().analyze_portfolio(_demo_positions())
        collapse = any("VOLUME_COLLAPSE" in p["flags"]
                       for p in res["positions"])
        self.assertTrue(collapse)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
