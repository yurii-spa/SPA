"""
Tests for MP-1170: DeFiProtocolVaultRewardTokenPriceExposureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_reward_token_price_exposure_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_reward_token_price_exposure_analyzer import (
    DeFiProtocolVaultRewardTokenPriceExposureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    NO_EXPOSURE_SHARE_PCT,
    LOW_EXPOSURE_SHARE_PCT,
    MODERATE_EXPOSURE_SHARE_PCT,
    REWARD_HEAVY_SHARE_PCT,
    DEPRECIATED_CHANGE_PCT,
    APPRECIATED_CHANGE_PCT,
    HEAVY_DEPRECIATION_CHANGE_PCT,
    HIGH_VOLATILITY_PCT,
    VOLATILITY_SCORE_CEILING_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="CRV-Vault",
    headline_apr_pct=12.0,
    reward_apr_pct=3.0,
    reward_token_price_change_pct=0.0,
    reward_token_volatility_pct=40.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "reward_apr_pct": reward_apr_pct,
        "reward_token_price_change_pct": reward_token_price_change_pct,
        "reward_token_volatility_pct": reward_token_volatility_pct,
    }


def A():
    return DeFiProtocolVaultRewardTokenPriceExposureAnalyzer()


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
        self.assertGreater(NO_EXPOSURE_SHARE_PCT, 0)
        self.assertLess(NO_EXPOSURE_SHARE_PCT, LOW_EXPOSURE_SHARE_PCT)
        self.assertLess(LOW_EXPOSURE_SHARE_PCT, MODERATE_EXPOSURE_SHARE_PCT)
        self.assertEqual(REWARD_HEAVY_SHARE_PCT, MODERATE_EXPOSURE_SHARE_PCT)
        self.assertLess(DEPRECIATED_CHANGE_PCT, 0)
        self.assertGreater(APPRECIATED_CHANGE_PCT, 0)
        self.assertLess(HEAVY_DEPRECIATION_CHANGE_PCT, DEPRECIATED_CHANGE_PCT)
        self.assertGreater(HIGH_VOLATILITY_PCT, 0)
        self.assertGreater(VOLATILITY_SCORE_CEILING_PCT, HIGH_VOLATILITY_PCT)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "base_apr_pct", "reward_apr_pct",
            "reward_share_pct", "reward_token_price_change_pct",
            "reward_token_volatility_pct", "realized_reward_apr_pct",
            "realized_apr_pct", "realization_haircut_pct", "realization_ratio",
            "effective_loss_from_reward_pct", "reward_heavy",
            "reward_token_depreciated", "high_reward_volatility", "score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "CRV-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 10.0,
                         "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 10.0, "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0, "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "DISCOUNT_FOR_REWARD_RISK",
            "HEDGE_OR_SELL_REWARDS_FAST", "AVOID_OR_VERIFY",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NO_REWARD_EXPOSURE", "LOW_REWARD_EXPOSURE",
            "MODERATE_REWARD_EXPOSURE", "HIGH_REWARD_EXPOSURE",
            "INSUFFICIENT_DATA",
        })

    def test_reward_heavy_is_bool(self):
        self.assertIsInstance(self.r["reward_heavy"], bool)

    def test_reward_token_depreciated_is_bool(self):
        self.assertIsInstance(self.r["reward_token_depreciated"], bool)

    def test_high_reward_volatility_is_bool(self):
        self.assertIsInstance(self.r["high_reward_volatility"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_base_apr(self):
        # headline 12 - reward 3 = base 9
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertAlmostEqual(r["base_apr_pct"], 9.0)

    def test_reward_apr_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertAlmostEqual(r["reward_apr_pct"], 3.0)

    def test_reward_apr_clamped_to_headline(self):
        # reward 20 > headline 12 → clamped to 12; base 0
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=20.0))
        self.assertAlmostEqual(r["reward_apr_pct"], 12.0)
        self.assertAlmostEqual(r["base_apr_pct"], 0.0)

    def test_reward_apr_negative_clamped_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=-5.0))
        self.assertAlmostEqual(r["reward_apr_pct"], 0.0)
        self.assertAlmostEqual(r["base_apr_pct"], 12.0)

    def test_reward_share_pct(self):
        # 3/12*100 = 25
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertAlmostEqual(r["reward_share_pct"], 25.0)

    def test_reward_share_zero_when_no_reward(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0))
        self.assertAlmostEqual(r["reward_share_pct"], 0.0)

    def test_realized_reward_flat_price(self):
        # price change 0 → realized reward = reward apr
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=0.0))
        self.assertAlmostEqual(r["realized_reward_apr_pct"], 3.0)

    def test_realized_reward_depreciated(self):
        # reward 3, down 35% → 3*0.65 = 1.95
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-35.0))
        self.assertAlmostEqual(r["realized_reward_apr_pct"], 1.95)

    def test_realized_reward_appreciated(self):
        # reward 3, up 20% → 3*1.2 = 3.6
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=20.0))
        self.assertAlmostEqual(r["realized_reward_apr_pct"], 3.6)

    def test_realized_reward_wiped_at_minus_100(self):
        # down 100% → factor 0 → realized 0
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-100.0))
        self.assertAlmostEqual(r["realized_reward_apr_pct"], 0.0)

    def test_realized_reward_floored_below_minus_100(self):
        # down 150% → factor max(0,-0.5)=0 → realized 0 (never negative)
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-150.0))
        self.assertAlmostEqual(r["realized_reward_apr_pct"], 0.0)

    def test_realized_apr(self):
        # base 9 + realized reward 1.95 = 10.95
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-35.0))
        self.assertAlmostEqual(r["realized_apr_pct"], 10.95)

    def test_realization_haircut_positive_when_down(self):
        # headline 12 - realized 10.95 = 1.05
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-35.0))
        self.assertAlmostEqual(r["realization_haircut_pct"], 1.05)

    def test_realization_haircut_negative_when_up(self):
        # reward 3 up 20% → realized reward 3.6; realized apr 12.6; haircut -0.6
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=20.0))
        self.assertAlmostEqual(r["realization_haircut_pct"], -0.6)

    def test_realization_ratio(self):
        # realized 10.95 / 12 = 0.9125
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-35.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.9125)

    def test_effective_loss_from_reward(self):
        # reward 3 - realized reward 1.95 = 1.05
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=-35.0))
        self.assertAlmostEqual(r["effective_loss_from_reward_pct"], 1.05)

    def test_effective_loss_negative_when_appreciated(self):
        # reward 3 - realized 3.6 = -0.6 (a gain)
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=20.0))
        self.assertAlmostEqual(r["effective_loss_from_reward_pct"], -0.6)

    def test_reward_heavy_true(self):
        # reward 7 of headline 12 → 58.3% >= 50
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=7.0))
        self.assertTrue(r["reward_heavy"])

    def test_reward_heavy_false(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertFalse(r["reward_heavy"])

    def test_reward_token_depreciated_true(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=-10.0))
        self.assertTrue(r["reward_token_depreciated"])

    def test_reward_token_depreciated_false(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=0.0))
        self.assertFalse(r["reward_token_depreciated"])

    def test_high_reward_volatility_true(self):
        r = A().analyze(make_pos(reward_token_volatility_pct=90.0))
        self.assertTrue(r["high_reward_volatility"])

    def test_high_reward_volatility_false(self):
        r = A().analyze(make_pos(reward_token_volatility_pct=40.0))
        self.assertFalse(r["high_reward_volatility"])

    def test_high_reward_volatility_boundary(self):
        # exactly at threshold counts as high
        r = A().analyze(make_pos(reward_token_volatility_pct=HIGH_VOLATILITY_PCT))
        self.assertTrue(r["high_reward_volatility"])

    def test_volatility_negative_clamped(self):
        r = A().analyze(make_pos(reward_token_volatility_pct=-50.0))
        self.assertAlmostEqual(r["reward_token_volatility_pct"], 0.0)

    def test_passthrough_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0, reward_apr_pct=4.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 18.0)

    def test_price_change_passthrough(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=-22.0))
        self.assertAlmostEqual(r["reward_token_price_change_pct"], -22.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=12.3333, reward_apr_pct=3.1111))
        for k in ("headline_apr_pct", "base_apr_pct", "reward_apr_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_no_reward_exposure(self):
        # share 0 <= 2
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_REWARD_EXPOSURE")

    def test_no_reward_exposure_boundary(self):
        # reward 0.24 of 12 → 2.0% exactly
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.24))
        self.assertEqual(r["classification"], "NO_REWARD_EXPOSURE")

    def test_low_reward_exposure(self):
        # reward 2 of 12 → 16.7% <= 25
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=2.0))
        self.assertEqual(r["classification"], "LOW_REWARD_EXPOSURE")

    def test_low_reward_exposure_boundary(self):
        # reward 3 of 12 → 25% exactly
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertEqual(r["classification"], "LOW_REWARD_EXPOSURE")

    def test_moderate_reward_exposure(self):
        # reward 5 of 12 → 41.7% <= 50
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=5.0))
        self.assertEqual(r["classification"], "MODERATE_REWARD_EXPOSURE")

    def test_moderate_reward_exposure_boundary(self):
        # reward 6 of 12 → 50% exactly
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=6.0))
        self.assertEqual(r["classification"], "MODERATE_REWARD_EXPOSURE")

    def test_high_reward_exposure(self):
        # reward 10 of 12 → 83.3% > 50
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=10.0))
        self.assertEqual(r["classification"], "HIGH_REWARD_EXPOSURE")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0, reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0),
                    make_pos(headline_apr_pct=12.0, reward_apr_pct=2.0),
                    make_pos(headline_apr_pct=12.0, reward_apr_pct=5.0),
                    make_pos(headline_apr_pct=12.0, reward_apr_pct=10.0),
                    make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NO_REWARD_EXPOSURE", "LOW_REWARD_EXPOSURE",
                "MODERATE_REWARD_EXPOSURE", "HIGH_REWARD_EXPOSURE",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_no_exposure(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_low_exposure(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=2.0,
                                 reward_token_price_change_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=5.0,
                                 reward_token_price_change_pct=-5.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_FOR_REWARD_RISK")

    def test_hedge_high_exposure(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=10.0))
        self.assertEqual(r["recommendation"], "HEDGE_OR_SELL_REWARDS_FAST")

    def test_hedge_heavily_depreciated_even_if_low(self):
        # low exposure but reward token down 40% → fast hedge
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=2.0,
                                 reward_token_price_change_pct=-40.0))
        self.assertEqual(r["recommendation"], "HEDGE_OR_SELL_REWARDS_FAST")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_no_reward_exposure_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0))
        self.assertIn("NO_REWARD_EXPOSURE", r["flags"])

    def test_low_reward_exposure_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=2.0))
        self.assertIn("LOW_REWARD_EXPOSURE", r["flags"])

    def test_moderate_reward_exposure_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=5.0))
        self.assertIn("MODERATE_REWARD_EXPOSURE", r["flags"])

    def test_high_reward_exposure_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=10.0))
        self.assertIn("HIGH_REWARD_EXPOSURE", r["flags"])

    def test_reward_heavy_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=7.0))
        self.assertIn("REWARD_HEAVY", r["flags"])

    def test_reward_heavy_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertNotIn("REWARD_HEAVY", r["flags"])

    def test_reward_token_depreciated_flag(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=-10.0))
        self.assertIn("REWARD_TOKEN_DEPRECIATED", r["flags"])

    def test_reward_token_appreciated_flag(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=5.0))
        self.assertIn("REWARD_TOKEN_APPRECIATED", r["flags"])

    def test_no_price_flag_when_flat(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=0.0))
        self.assertNotIn("REWARD_TOKEN_DEPRECIATED", r["flags"])
        self.assertNotIn("REWARD_TOKEN_APPRECIATED", r["flags"])

    def test_high_reward_volatility_flag(self):
        r = A().analyze(make_pos(reward_token_volatility_pct=100.0))
        self.assertIn("HIGH_REWARD_VOLATILITY", r["flags"])

    def test_high_reward_volatility_flag_absent(self):
        r = A().analyze(make_pos(reward_token_volatility_pct=30.0))
        self.assertNotIn("HIGH_REWARD_VOLATILITY", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_depreciated_and_appreciated_mutually_exclusive(self):
        for pc in (-50.0, -5.0, 0.0, 5.0, 50.0):
            r = A().analyze(make_pos(reward_token_price_change_pct=pc))
            self.assertFalse(
                "REWARD_TOKEN_DEPRECIATED" in r["flags"]
                and "REWARD_TOKEN_APPRECIATED" in r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["reward_share_pct"])
        self.assertIsNone(r["realized_reward_apr_pct"])
        self.assertIsNone(r["realized_apr_pct"])
        self.assertIsNone(r["realization_haircut_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["effective_loss_from_reward_pct"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "base_apr_pct", "reward_apr_pct",
                  "reward_token_price_change_pct",
                  "reward_token_volatility_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["reward_heavy"])
        self.assertFalse(r["reward_token_depreciated"])
        self.assertFalse(r["high_reward_volatility"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_reward(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_only_base(self):
        # headline > 0, no reward → valid NO_REWARD_EXPOSURE
        r = A().analyze(make_pos(headline_apr_pct=8.0, reward_apr_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_reward_share_scores_lower(self):
        low = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=1.0,
                                   reward_token_volatility_pct=0.0))
        high = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=10.0,
                                    reward_token_volatility_pct=0.0))
        self.assertGreater(low["score"], high["score"])

    def test_depreciated_scores_lower_than_held(self):
        held = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=6.0,
                                    reward_token_price_change_pct=0.0))
        down = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=6.0,
                                    reward_token_price_change_pct=-50.0))
        self.assertGreater(held["score"], down["score"])

    def test_higher_volatility_scores_lower(self):
        calm = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                    reward_token_volatility_pct=0.0))
        wild = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                    reward_token_volatility_pct=120.0))
        self.assertGreater(calm["score"], wild["score"])

    def test_no_exposure_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=0.0,
                                 reward_token_volatility_pct=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_high_exposure_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=11.0,
                                 reward_token_price_change_pct=-50.0,
                                 reward_token_volatility_pct=120.0))
        self.assertLess(r["score"], 40.0)

    def test_appreciated_reward_full_held_value(self):
        # appreciated reward → held value component caps at full
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=3.0,
                                 reward_token_price_change_pct=50.0,
                                 reward_token_volatility_pct=0.0))
        # safe base (9/12=0.75)*45=33.75 + 35 + 20 = 88.75
        self.assertAlmostEqual(r["score"], 88.75, places=1)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e-9, reward_apr_pct=1e12,
                                 reward_token_price_change_pct=1e9,
                                 reward_token_volatility_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, reward_apr_pct=12.0,
                                 reward_token_price_change_pct=-100.0,
                                 reward_token_volatility_pct=1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(reward_apr_pct=0.0),
                    make_pos(reward_apr_pct=2.0),
                    make_pos(reward_apr_pct=5.0),
                    make_pos(reward_apr_pct=10.0),
                    make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(reward_apr_pct=0.0),
                    make_pos(reward_apr_pct=11.0,
                             reward_token_price_change_pct=-50.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", headline_apr_pct=12.0, reward_apr_pct=0.0,
                     reward_token_volatility_pct=0.0),
            make_pos(vault="Exposed", headline_apr_pct=12.0,
                     reward_apr_pct=11.0,
                     reward_token_price_change_pct=-50.0,
                     reward_token_volatility_pct=120.0),
            make_pos(vault="Mid", headline_apr_pct=12.0, reward_apr_pct=5.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_safest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["safest_vault"]], max(scores.values()))

    def test_most_exposed_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_exposed_vault"]], min(scores.values()))

    def test_safest_is_safe(self):
        self.assertEqual(self.res["aggregate"]["safest_vault"], "Safe")

    def test_most_exposed_is_exposed(self):
        self.assertEqual(self.res["aggregate"]["most_exposed_vault"], "Exposed")

    def test_high_exposure_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_exposure_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertIsNone(res["aggregate"]["most_exposed_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["high_exposure_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["safest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_exposed_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=12.0, reward_apr_pct=0.0),
            make_pos(vault="Ins", headline_apr_pct=0.0, reward_apr_pct=0.0),
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
                         reward_apr_pct=1e12,
                         reward_token_price_change_pct=1e9,
                         reward_token_volatility_pct=1e9),
                make_pos(vault="ins", headline_apr_pct=0.0,
                         reward_apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0))
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
            "headline_apr_pct": "12",
            "reward_apr_pct": "3",
            "reward_token_price_change_pct": "-10",
            "reward_token_volatility_pct": "50",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 12.0})
        self.assertIn("classification", r)
        self.assertEqual(r["classification"], "NO_REWARD_EXPOSURE")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0),
            make_pos(reward_apr_pct=10.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(reward_apr_pct=0.0),
                    make_pos(reward_apr_pct=10.0),
                    make_pos(headline_apr_pct=0.0, reward_apr_pct=0.0),
                    make_pos(headline_apr_pct=1e-9, reward_apr_pct=1e12,
                             reward_token_price_change_pct=1e9,
                             reward_token_volatility_pct=1e9),
                    make_pos(headline_apr_pct=1e12, reward_apr_pct=-1e12),
                    make_pos(reward_token_price_change_pct=-1e9),
                    make_pos(reward_token_volatility_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, reward_apr_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=-10.0, reward_apr_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(), make_pos(headline_apr_pct=0.0,
                                         reward_apr_pct=0.0),
                    make_pos(reward_apr_pct=10.0)]:
            r = A().analyze(pos)
            for k in ("reward_share_pct", "realized_reward_apr_pct",
                      "realized_apr_pct", "realization_haircut_pct",
                      "realization_ratio", "effective_loss_from_reward_pct"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))

    def test_bool_inputs_preserved(self):
        r = A().analyze(make_pos(reward_token_price_change_pct=-10.0,
                                 reward_token_volatility_pct=90.0))
        self.assertTrue(r["reward_token_depreciated"])
        self.assertTrue(r["high_reward_volatility"])


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

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

    def test_demo_includes_no_and_high_exposure(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NO_REWARD_EXPOSURE", classes)
        self.assertIn("HIGH_REWARD_EXPOSURE", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
