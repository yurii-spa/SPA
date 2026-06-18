"""
Tests for MP-1178: DeFiProtocolVaultRewardSellPressureRunwayAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_reward_sell_pressure_runway_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_reward_sell_pressure_runway_analyzer import (
    DeFiProtocolVaultRewardSellPressureRunwayAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    NEGLIGIBLE_OVERHANG_RATIO,
    LOW_OVERHANG_RATIO,
    MODERATE_OVERHANG_RATIO,
    ABSORBABLE_RATIO,
    THIN_BUYSIDE_RATIO,
    OVERHANG_CEILING,
    HIGH_REWARD_SHARE_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=16.0,
    reward_apr_pct=6.0,
    daily_emission_sell_usd=80000.0,
    reward_token_daily_volume_usd=2000000.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "reward_apr_pct": reward_apr_pct,
        "daily_emission_sell_usd": daily_emission_sell_usd,
        "reward_token_daily_volume_usd": reward_token_daily_volume_usd,
    }


def A():
    return DeFiProtocolVaultRewardSellPressureRunwayAnalyzer()


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
        self.assertLess(NEGLIGIBLE_OVERHANG_RATIO, LOW_OVERHANG_RATIO)
        self.assertLess(LOW_OVERHANG_RATIO, MODERATE_OVERHANG_RATIO)
        self.assertEqual(ABSORBABLE_RATIO, 0.02)
        self.assertGreater(OVERHANG_CEILING, 0)
        self.assertGreater(THIN_BUYSIDE_RATIO, 0)
        self.assertEqual(HIGH_REWARD_SHARE_PCT, 50.0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "base_apr_pct", "reward_apr_pct",
            "reward_share_pct", "daily_emission_sell_usd",
            "reward_token_daily_volume_usd", "sell_pressure_ratio",
            "est_sell_pressure_pct", "absorbable", "thin_buyside",
            "high_reward_share", "score", "classification", "recommendation",
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
            "TRUST_HEADLINE", "MINOR_REWARD_DISCOUNT",
            "DISCOUNT_REWARD_LAYER", "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NO_EMISSIONS", "NEGLIGIBLE_OVERHANG", "LOW_OVERHANG",
            "MODERATE_OVERHANG", "HIGH_OVERHANG", "INSUFFICIENT_DATA",
        })

    def test_absorbable_is_bool(self):
        self.assertIsInstance(self.r["absorbable"], bool)

    def test_thin_buyside_is_bool(self):
        self.assertIsInstance(self.r["thin_buyside"], bool)

    def test_high_reward_share_is_bool(self):
        self.assertIsInstance(self.r["high_reward_share"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 16.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_reward_negative_clamped_no_emissions(self):
        r = A().analyze(make_pos(reward_apr_pct=-2.0))
        self.assertEqual(r["classification"], "NO_EMISSIONS")

    def test_reward_clamped_to_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, reward_apr_pct=15.0))
        self.assertAlmostEqual(r["reward_apr_pct"], 10.0)

    def test_base_apr(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=6.0))
        self.assertAlmostEqual(r["base_apr_pct"], 10.0, places=4)

    def test_reward_share(self):
        # 6 / 16 * 100 = 37.5
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=6.0))
        self.assertAlmostEqual(r["reward_share_pct"], 37.5, places=4)

    def test_sell_pressure_ratio(self):
        # 80000 / 2000000 = 0.04
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertAlmostEqual(r["sell_pressure_ratio"], 0.04, places=4)

    def test_est_sell_pressure(self):
        # ratio 0.04 * 100 = 4.0
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertAlmostEqual(r["est_sell_pressure_pct"], 4.0, places=4)

    def test_est_sell_pressure_clamped_100(self):
        # huge emission vs tiny volume → clamps to 100
        r = A().analyze(make_pos(daily_emission_sell_usd=1e9,
                                 reward_token_daily_volume_usd=1.0))
        self.assertAlmostEqual(r["est_sell_pressure_pct"], 100.0, places=4)

    def test_absorbable_true(self):
        # ratio 0.01 <= 0.02
        r = A().analyze(make_pos(daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertTrue(r["absorbable"])

    def test_absorbable_boundary(self):
        # ratio exactly 0.02
        r = A().analyze(make_pos(daily_emission_sell_usd=40000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertTrue(r["absorbable"])

    def test_absorbable_false(self):
        # ratio 0.04 > 0.02
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertFalse(r["absorbable"])

    def test_thin_buyside_true(self):
        # ratio 0.2 >= 0.10
        r = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertTrue(r["thin_buyside"])

    def test_thin_buyside_boundary(self):
        # ratio exactly 0.10
        r = A().analyze(make_pos(daily_emission_sell_usd=200000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertTrue(r["thin_buyside"])

    def test_thin_buyside_false(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertFalse(r["thin_buyside"])

    def test_high_reward_share_true(self):
        # reward 12 / headline 16 = 75% >= 50
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=12.0))
        self.assertTrue(r["high_reward_share"])

    def test_high_reward_share_boundary(self):
        # reward 8 / 16 = 50%
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=8.0))
        self.assertTrue(r["high_reward_share"])

    def test_high_reward_share_false(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=2.0))
        self.assertFalse(r["high_reward_share"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=16.3333,
                                 reward_apr_pct=6.1111,
                                 daily_emission_sell_usd=55555.0,
                                 reward_token_daily_volume_usd=1888888.0))
        for k in ("headline_apr_pct", "base_apr_pct", "reward_apr_pct",
                  "reward_share_pct", "daily_emission_sell_usd",
                  "reward_token_daily_volume_usd", "sell_pressure_ratio",
                  "est_sell_pressure_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_no_emissions(self):
        r = A().analyze(make_pos(reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_EMISSIONS")

    def test_negligible_overhang(self):
        # ratio 0.004
        r = A().analyze(make_pos(daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=5000000.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE_OVERHANG")

    def test_low_overhang(self):
        # ratio 0.04
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "LOW_OVERHANG")

    def test_moderate_overhang(self):
        # ratio 0.10
        r = A().analyze(make_pos(daily_emission_sell_usd=200000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "MODERATE_OVERHANG")

    def test_high_overhang(self):
        # ratio 0.20
        r = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "HIGH_OVERHANG")

    def test_negligible_boundary(self):
        # ratio exactly NEGLIGIBLE_OVERHANG_RATIO=0.02
        r = A().analyze(make_pos(daily_emission_sell_usd=40000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE_OVERHANG")

    def test_low_boundary(self):
        # ratio exactly LOW_OVERHANG_RATIO=0.05
        r = A().analyze(make_pos(daily_emission_sell_usd=100000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "LOW_OVERHANG")

    def test_moderate_boundary(self):
        # ratio exactly MODERATE_OVERHANG_RATIO=0.15
        r = A().analyze(make_pos(daily_emission_sell_usd=300000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "MODERATE_OVERHANG")

    def test_above_moderate_high(self):
        # ratio 0.16 > 0.15
        r = A().analyze(make_pos(daily_emission_sell_usd=320000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["classification"], "HIGH_OVERHANG")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_reward_no_volume(self):
        # reward > 0 but volume <= 0 → INSUFFICIENT
        r = A().analyze(make_pos(reward_apr_pct=6.0,
                                 reward_token_daily_volume_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(reward_apr_pct=0.0),
                    make_pos(daily_emission_sell_usd=20000.0,
                             reward_token_daily_volume_usd=5000000.0),
                    make_pos(daily_emission_sell_usd=200000.0),
                    make_pos(daily_emission_sell_usd=400000.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NO_EMISSIONS", "NEGLIGIBLE_OVERHANG", "LOW_OVERHANG",
                "MODERATE_OVERHANG", "HIGH_OVERHANG", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_headline_no_emissions(self):
        r = A().analyze(make_pos(reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_headline_negligible(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=5000000.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_minor_discount_low(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["recommendation"], "MINOR_REWARD_DISCOUNT")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=200000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_REWARD_LAYER")

    def test_avoid_high(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_verify_reward_no_volume(self):
        r = A().analyze(make_pos(reward_apr_pct=6.0,
                                 reward_token_daily_volume_usd=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_no_emissions_flag(self):
        r = A().analyze(make_pos(reward_apr_pct=0.0))
        self.assertIn("NO_EMISSIONS", r["flags"])

    def test_negligible_flag(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=5000000.0))
        self.assertIn("NEGLIGIBLE_OVERHANG", r["flags"])

    def test_low_flag(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertIn("LOW_OVERHANG", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=200000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertIn("MODERATE_OVERHANG", r["flags"])

    def test_high_flag(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertIn("HIGH_OVERHANG", r["flags"])

    def test_thin_buyside_flag(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertIn("THIN_BUYSIDE", r["flags"])

    def test_thin_buyside_flag_absent(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertNotIn("THIN_BUYSIDE", r["flags"])

    def test_high_reward_share_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=12.0,
                                 daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=5000000.0))
        self.assertIn("HIGH_REWARD_SHARE", r["flags"])

    def test_high_reward_share_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=2.0,
                                 daily_emission_sell_usd=20000.0,
                                 reward_token_daily_volume_usd=5000000.0))
        self.assertNotIn("HIGH_REWARD_SHARE", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        self.assertIn("LOW_OVERHANG", r["flags"])
        self.assertNotIn("HIGH_OVERHANG", r["flags"])


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
        self.assertIsNone(r["reward_share_pct"])

    def test_insufficient_projection_none(self):
        r = A().analyze({})
        self.assertIsNone(r["sell_pressure_ratio"])
        self.assertIsNone(r["est_sell_pressure_pct"])

    def test_reward_no_volume_insufficient(self):
        r = A().analyze(make_pos(reward_apr_pct=6.0,
                                 reward_token_daily_volume_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["est_sell_pressure_pct"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["absorbable"])
        self.assertFalse(r["thin_buyside"])
        self.assertFalse(r["high_reward_share"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "base_apr_pct", "reward_apr_pct",
                  "daily_emission_sell_usd", "reward_token_daily_volume_usd",
                  "score"):
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
    def test_more_sustainable_scores_higher(self):
        clean = A().analyze(make_pos(daily_emission_sell_usd=20000.0,
                                     reward_token_daily_volume_usd=5000000.0))
        dirty = A().analyze(make_pos(daily_emission_sell_usd=400000.0,
                                     reward_token_daily_volume_usd=2000000.0))
        self.assertGreater(clean["score"], dirty["score"])

    def test_no_emissions_full_score(self):
        r = A().analyze(make_pos(reward_apr_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_tiny_overhang_near_full_score(self):
        r = A().analyze(make_pos(daily_emission_sell_usd=1.0,
                                 reward_token_daily_volume_usd=1e9))
        self.assertGreater(r["score"], 99.0)

    def test_deeper_volume_higher_score(self):
        shallow = A().analyze(make_pos(daily_emission_sell_usd=100000.0,
                                       reward_token_daily_volume_usd=1000000.0))
        deep = A().analyze(make_pos(daily_emission_sell_usd=100000.0,
                                    reward_token_daily_volume_usd=10000000.0))
        self.assertGreater(deep["score"], shallow["score"])

    def test_worst_case_low_score(self):
        # huge emission into tiny volume → ratio huge, high reward share
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=16.0,
                                 daily_emission_sell_usd=1e9,
                                 reward_token_daily_volume_usd=1.0))
        self.assertLess(r["score"], 5.0)

    def test_known_score_low_overhang(self):
        # ratio 0.04, reward 6/16=37.5%:
        # pressure_norm = 0.04/0.25 = 0.16
        # pressure_comp = 60*(1-0.16)=50.4
        # share_comp = 40*(1-0.16*0.375)=40*(1-0.06)=37.6
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=6.0,
                                 daily_emission_sell_usd=80000.0,
                                 reward_token_daily_volume_usd=2000000.0))
        pn = 0.04 / 0.25
        expected = 60.0 * (1.0 - pn) + 40.0 * (1.0 - pn * 0.375)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=16.0, reward_apr_pct=16.0,
                                 daily_emission_sell_usd=1e9,
                                 reward_token_daily_volume_usd=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, reward_apr_pct=1e9,
                                 daily_emission_sell_usd=1e9,
                                 reward_token_daily_volume_usd=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(reward_apr_pct=0.0),
                    make_pos(daily_emission_sell_usd=80000.0),
                    make_pos(daily_emission_sell_usd=400000.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(reward_apr_pct=0.0),
                    make_pos(headline_apr_pct=16.0, reward_apr_pct=16.0,
                             daily_emission_sell_usd=1e9,
                             reward_token_daily_volume_usd=1.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_reward_share_lower_score_same_ratio(self):
        # same overhang ratio, but more of the headline on reward → lower score
        low_share = A().analyze(make_pos(headline_apr_pct=20.0,
                                         reward_apr_pct=2.0,
                                         daily_emission_sell_usd=400000.0,
                                         reward_token_daily_volume_usd=2000000.0))
        high_share = A().analyze(make_pos(headline_apr_pct=20.0,
                                          reward_apr_pct=18.0,
                                          daily_emission_sell_usd=400000.0,
                                          reward_token_daily_volume_usd=2000000.0))
        self.assertGreater(low_share["score"], high_share["score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Clean", daily_emission_sell_usd=20000.0,
                     reward_token_daily_volume_usd=5000000.0),
            make_pos(vault="Dirty", daily_emission_sell_usd=500000.0,
                     reward_token_daily_volume_usd=1500000.0),
            make_pos(vault="Mid", daily_emission_sell_usd=200000.0,
                     reward_token_daily_volume_usd=2000000.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_sustainable_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_sustainable_vault"]],
                         max(scores.values()))

    def test_most_overhang_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_overhang_vault"]],
                         min(scores.values()))

    def test_most_sustainable_is_clean(self):
        self.assertEqual(self.res["aggregate"]["most_sustainable_vault"],
                         "Clean")

    def test_most_overhang_is_dirty(self):
        self.assertEqual(self.res["aggregate"]["most_overhang_vault"], "Dirty")

    def test_high_overhang_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["high_overhang_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_high_overhang_count_only_high(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", daily_emission_sell_usd=400000.0,
                     reward_token_daily_volume_usd=2000000.0),
            make_pos(vault="B", daily_emission_sell_usd=500000.0,
                     reward_token_daily_volume_usd=1500000.0),
            make_pos(vault="C", daily_emission_sell_usd=20000.0,
                     reward_token_daily_volume_usd=5000000.0),
        ])
        self.assertEqual(res["aggregate"]["high_overhang_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_sustainable_vault"])
        self.assertIsNone(res["aggregate"]["most_overhang_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_sustainable_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["high_overhang_count"], 0)

    def test_no_emissions_counts_as_scored(self):
        # NO_EMISSIONS is not INSUFFICIENT → participates in aggregate
        res = A().analyze_portfolio([
            make_pos(vault="NoEm", reward_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["most_sustainable_vault"], "NoEm")

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_sustainable_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_overhang_vault"], "Solo")

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
                         reward_apr_pct=1e9, daily_emission_sell_usd=1e9,
                         reward_token_daily_volume_usd=1.0),
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
            "reward_apr_pct": "6",
            "daily_emission_sell_usd": "80000",
            "reward_token_daily_volume_usd": "2000000",
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
            make_pos(daily_emission_sell_usd=400000.0,
                     reward_token_daily_volume_usd=2000000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(daily_emission_sell_usd=400000.0,
                             reward_token_daily_volume_usd=2000000.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(reward_apr_pct=0.0),
                    make_pos(reward_apr_pct=6.0,
                             reward_token_daily_volume_usd=0.0),
                    make_pos(headline_apr_pct=1e9, reward_apr_pct=1e9,
                             daily_emission_sell_usd=1e9,
                             reward_token_daily_volume_usd=1.0),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(reward_apr_pct=-1e9, daily_emission_sell_usd=-1e9,
                             reward_token_daily_volume_usd=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, reward_apr_pct=1e9,
                                 daily_emission_sell_usd=1e9,
                                 reward_token_daily_volume_usd=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(reward_apr_pct=-10.0,
                                 daily_emission_sell_usd=-8.0,
                                 reward_token_daily_volume_usd=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_reward_no_emissions(self):
        r = A().analyze(make_pos(reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "NO_EMISSIONS")


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

    def test_demo_includes_no_emissions_and_high(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NO_EMISSIONS", classes)
        self.assertIn("HIGH_OVERHANG", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NO_EMISSIONS", "NEGLIGIBLE_OVERHANG", "LOW_OVERHANG",
                  "MODERATE_OVERHANG", "HIGH_OVERHANG", "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_HEADLINE", recs)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
