"""
Tests for MP-1170: DeFiProtocolVaultRedemptionCooldownExposureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_redemption_cooldown_exposure_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_redemption_cooldown_exposure_analyzer import (  # noqa: E501
    DeFiProtocolVaultRedemptionCooldownExposureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    COOLDOWN_SCORE_CEILING_DAYS,
    COST_SCORE_CEILING_PCT,
    LOW_EXPOSURE_COST_PCT,
    MODERATE_EXPOSURE_COST_PCT,
    LONG_COOLDOWN_DAYS,
    HIGH_VAR_COST_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    position_usd=100000.0,
    cooldown_days=7.0,
    daily_volatility_pct=1.0,
    earns_during_cooldown=False,
    vault_apr_pct=10.0,
    exit_urgency_days=0.0,
):
    return {
        "vault": vault,
        "position_usd": position_usd,
        "cooldown_days": cooldown_days,
        "daily_volatility_pct": daily_volatility_pct,
        "earns_during_cooldown": earns_during_cooldown,
        "vault_apr_pct": vault_apr_pct,
        "exit_urgency_days": exit_urgency_days,
    }


def A():
    return DeFiProtocolVaultRedemptionCooldownExposureAnalyzer()


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

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

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
        self.assertGreater(COOLDOWN_SCORE_CEILING_DAYS, 0)
        self.assertGreater(COST_SCORE_CEILING_PCT, 0)
        self.assertLess(LOW_EXPOSURE_COST_PCT, MODERATE_EXPOSURE_COST_PCT)
        self.assertGreater(LONG_COOLDOWN_DAYS, 0)
        self.assertGreater(HIGH_VAR_COST_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "position_usd", "cooldown_days", "has_cooldown",
            "daily_volatility_pct", "expected_adverse_move_pct",
            "value_at_risk_usd", "two_sigma_var_usd", "foregone_yield_usd",
            "cooldown_cost_pct", "earns_during_cooldown", "trapped",
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
        r = A().analyze({"token": "AltKey", "position_usd": 1000.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "position_usd": 1000.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"position_usd": 1000.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD", "EXIT_ANYTIME", "ENTER_OK", "ENTER_REDUCED_SIZE",
            "AVOID_IF_LIQUIDITY_NEEDED", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "INSTANT_EXIT", "TRAPPED_RISK", "LOW_EXPOSURE",
            "MODERATE_EXPOSURE", "HIGH_EXPOSURE", "INSUFFICIENT_DATA",
        })

    def test_has_cooldown_is_bool(self):
        self.assertIsInstance(self.r["has_cooldown"], bool)

    def test_trapped_is_bool(self):
        self.assertIsInstance(self.r["trapped"], bool)

    def test_earns_is_bool(self):
        self.assertIsInstance(self.r["earns_during_cooldown"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_cooldown_negative_clamped(self):
        r = A().analyze(make_pos(cooldown_days=-5.0))
        self.assertAlmostEqual(r["cooldown_days"], 0.0)

    def test_daily_vol_negative_clamped(self):
        r = A().analyze(make_pos(daily_volatility_pct=-2.0))
        self.assertAlmostEqual(r["daily_volatility_pct"], 0.0)

    def test_position_usd_echo(self):
        r = A().analyze(make_pos(position_usd=12345.0))
        self.assertAlmostEqual(r["position_usd"], 12345.0)

    def test_position_usd_negative_insufficient(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_has_cooldown_true(self):
        r = A().analyze(make_pos(cooldown_days=3.0))
        self.assertTrue(r["has_cooldown"])

    def test_has_cooldown_false(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertFalse(r["has_cooldown"])

    def test_expected_adverse_move(self):
        # 2%/day * sqrt(9) = 6.0
        r = A().analyze(make_pos(daily_volatility_pct=2.0, cooldown_days=9.0))
        self.assertAlmostEqual(r["expected_adverse_move_pct"], 6.0)

    def test_expected_adverse_move_zero_cooldown(self):
        r = A().analyze(make_pos(cooldown_days=0.0, daily_volatility_pct=5.0))
        self.assertAlmostEqual(r["expected_adverse_move_pct"], 0.0)

    def test_expected_adverse_move_nonneg(self):
        r = A().analyze(make_pos(daily_volatility_pct=3.0, cooldown_days=16.0))
        self.assertGreaterEqual(r["expected_adverse_move_pct"], 0.0)

    def test_value_at_risk(self):
        # move = 2 * sqrt(9) = 6%; var = 100000 * 0.06 = 6000
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=2.0, cooldown_days=9.0))
        self.assertAlmostEqual(r["value_at_risk_usd"], 6000.0)

    def test_two_sigma_var(self):
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=2.0, cooldown_days=9.0))
        self.assertAlmostEqual(r["two_sigma_var_usd"],
                               2.0 * r["value_at_risk_usd"])

    def test_value_at_risk_nonneg(self):
        r = A().analyze(make_pos())
        self.assertGreaterEqual(r["value_at_risk_usd"], 0.0)

    def test_foregone_yield_when_idle(self):
        # 100000 * 10% * 365/365 = 10000
        r = A().analyze(make_pos(position_usd=100000.0, vault_apr_pct=10.0,
                                 cooldown_days=365.0,
                                 earns_during_cooldown=False))
        self.assertAlmostEqual(r["foregone_yield_usd"], 10000.0)

    def test_foregone_yield_zero_when_earns(self):
        r = A().analyze(make_pos(earns_during_cooldown=True,
                                 vault_apr_pct=20.0, cooldown_days=30.0))
        self.assertAlmostEqual(r["foregone_yield_usd"], 0.0)

    def test_foregone_yield_nonneg(self):
        r = A().analyze(make_pos(vault_apr_pct=-50.0))
        self.assertGreaterEqual(r["foregone_yield_usd"], 0.0)

    def test_cooldown_cost_pct(self):
        # var 6000 + foregone (100000*10%*9/365=246.58) over 100000
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=2.0, cooldown_days=9.0,
                                 vault_apr_pct=10.0,
                                 earns_during_cooldown=False))
        expected = (r["value_at_risk_usd"] + r["foregone_yield_usd"]) \
            / 100000.0 * 100.0
        self.assertAlmostEqual(r["cooldown_cost_pct"], round(expected, 4),
                               places=3)

    def test_cooldown_cost_pct_nonneg(self):
        r = A().analyze(make_pos())
        self.assertGreaterEqual(r["cooldown_cost_pct"], 0.0)

    def test_trapped_true(self):
        r = A().analyze(make_pos(cooldown_days=14.0, exit_urgency_days=5.0))
        self.assertTrue(r["trapped"])

    def test_trapped_false_no_urgency(self):
        r = A().analyze(make_pos(cooldown_days=14.0, exit_urgency_days=0.0))
        self.assertFalse(r["trapped"])

    def test_trapped_false_urgency_exceeds_cooldown(self):
        r = A().analyze(make_pos(cooldown_days=5.0, exit_urgency_days=30.0))
        self.assertFalse(r["trapped"])

    def test_trapped_boundary_equal(self):
        # cooldown == urgency → not trapped (strict >)
        r = A().analyze(make_pos(cooldown_days=10.0, exit_urgency_days=10.0))
        self.assertFalse(r["trapped"])

    def test_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("expected_adverse_move_pct", "value_at_risk_usd",
                  "two_sigma_var_usd", "foregone_yield_usd",
                  "cooldown_cost_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_insufficient_no_position(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_instant_exit(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertEqual(r["classification"], "INSTANT_EXIT")

    def test_trapped_risk(self):
        r = A().analyze(make_pos(cooldown_days=14.0, exit_urgency_days=3.0))
        self.assertEqual(r["classification"], "TRAPPED_RISK")

    def test_low_exposure(self):
        # tiny vol → tiny cost
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=0.01, cooldown_days=1.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["classification"], "LOW_EXPOSURE")

    def test_moderate_exposure(self):
        # cost between 1 and 5
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=1.0, cooldown_days=9.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["classification"], "MODERATE_EXPOSURE")

    def test_high_exposure(self):
        # big vol → cost > 5
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=5.0, cooldown_days=9.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["classification"], "HIGH_EXPOSURE")

    def test_trapped_takes_priority_over_cost(self):
        # high cost AND trapped → TRAPPED_RISK wins
        r = A().analyze(make_pos(position_usd=100000.0,
                                 daily_volatility_pct=5.0, cooldown_days=20.0,
                                 exit_urgency_days=2.0))
        self.assertEqual(r["classification"], "TRAPPED_RISK")

    def test_instant_exit_priority_over_trapped(self):
        # cooldown 0 → INSTANT_EXIT regardless of urgency
        r = A().analyze(make_pos(cooldown_days=0.0, exit_urgency_days=1.0))
        self.assertEqual(r["classification"], "INSTANT_EXIT")

    def test_classification_known_many(self):
        for pos in [make_pos(position_usd=0.0),
                    make_pos(cooldown_days=0.0),
                    make_pos(cooldown_days=14.0, exit_urgency_days=2.0),
                    make_pos(daily_volatility_pct=0.01,
                             earns_during_cooldown=True),
                    make_pos(daily_volatility_pct=5.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "INSTANT_EXIT", "TRAPPED_RISK", "LOW_EXPOSURE",
                "MODERATE_EXPOSURE", "HIGH_EXPOSURE", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient_hold(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_instant_exit_anytime(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertEqual(r["recommendation"], "EXIT_ANYTIME")

    def test_low_exposure_enter_ok(self):
        r = A().analyze(make_pos(daily_volatility_pct=0.01, cooldown_days=1.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["recommendation"], "ENTER_OK")

    def test_moderate_reduced_size(self):
        r = A().analyze(make_pos(daily_volatility_pct=1.0, cooldown_days=9.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["recommendation"], "ENTER_REDUCED_SIZE")

    def test_high_avoid_if_liquidity(self):
        r = A().analyze(make_pos(daily_volatility_pct=5.0, cooldown_days=9.0,
                                 earns_during_cooldown=True))
        self.assertEqual(r["recommendation"], "AVOID_IF_LIQUIDITY_NEEDED")

    def test_trapped_avoid(self):
        r = A().analyze(make_pos(cooldown_days=14.0, exit_urgency_days=2.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_rec_known_many(self):
        for pos in [make_pos(position_usd=0.0),
                    make_pos(cooldown_days=0.0),
                    make_pos(daily_volatility_pct=0.01,
                             earns_during_cooldown=True),
                    make_pos(daily_volatility_pct=5.0)]:
            r = A().analyze(pos)
            self.assertIn(r["recommendation"], {
                "HOLD", "EXIT_ANYTIME", "ENTER_OK", "ENTER_REDUCED_SIZE",
                "AVOID_IF_LIQUIDITY_NEEDED", "AVOID",
            })


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_has_cooldown_flag(self):
        r = A().analyze(make_pos(cooldown_days=5.0))
        self.assertIn("HAS_COOLDOWN", r["flags"])

    def test_instant_exit_flag(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertIn("INSTANT_EXIT", r["flags"])

    def test_earns_flag(self):
        r = A().analyze(make_pos(earns_during_cooldown=True))
        self.assertIn("EARNS_DURING_COOLDOWN", r["flags"])

    def test_idle_flag(self):
        r = A().analyze(make_pos(earns_during_cooldown=False,
                                 cooldown_days=5.0))
        self.assertIn("IDLE_DURING_COOLDOWN", r["flags"])

    def test_idle_flag_absent_when_earns(self):
        r = A().analyze(make_pos(earns_during_cooldown=True,
                                 cooldown_days=5.0))
        self.assertNotIn("IDLE_DURING_COOLDOWN", r["flags"])

    def test_idle_flag_absent_no_cooldown(self):
        r = A().analyze(make_pos(earns_during_cooldown=False,
                                 cooldown_days=0.0))
        self.assertNotIn("IDLE_DURING_COOLDOWN", r["flags"])

    def test_trapped_flag(self):
        r = A().analyze(make_pos(cooldown_days=14.0, exit_urgency_days=2.0))
        self.assertIn("TRAPPED", r["flags"])

    def test_long_cooldown_flag(self):
        r = A().analyze(make_pos(cooldown_days=20.0))
        self.assertIn("LONG_COOLDOWN", r["flags"])

    def test_long_cooldown_flag_boundary(self):
        r = A().analyze(make_pos(cooldown_days=14.0))
        self.assertIn("LONG_COOLDOWN", r["flags"])

    def test_long_cooldown_absent(self):
        r = A().analyze(make_pos(cooldown_days=7.0))
        self.assertNotIn("LONG_COOLDOWN", r["flags"])

    def test_high_var_flag(self):
        r = A().analyze(make_pos(daily_volatility_pct=5.0, cooldown_days=9.0,
                                 earns_during_cooldown=True))
        self.assertIn("HIGH_VAR", r["flags"])

    def test_high_var_flag_absent(self):
        r = A().analyze(make_pos(daily_volatility_pct=0.01, cooldown_days=1.0,
                                 earns_during_cooldown=True))
        self.assertNotIn("HIGH_VAR", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_instant_exit_no_has_cooldown(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertNotIn("HAS_COOLDOWN", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_position(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_score_zero(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_recommendation(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_negative_position(self):
        r = A().analyze(make_pos(position_usd=-50.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("position_usd", "cooldown_days", "daily_volatility_pct",
                  "expected_adverse_move_pct", "value_at_risk_usd",
                  "two_sigma_var_usd", "foregone_yield_usd",
                  "cooldown_cost_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["has_cooldown"])
        self.assertFalse(r["trapped"])
        self.assertFalse(r["earns_during_cooldown"])

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json(self):
        json.dumps(A().analyze({}))

    def test_valid_when_position_present(self):
        r = A().analyze(make_pos(position_usd=1000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_instant_exit_perfect_score(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertEqual(r["score"], 100.0)

    def test_shorter_cooldown_scores_higher(self):
        short = A().analyze(make_pos(cooldown_days=2.0,
                                     daily_volatility_pct=0.5,
                                     earns_during_cooldown=True))
        long = A().analyze(make_pos(cooldown_days=13.0,
                                    daily_volatility_pct=0.5,
                                    earns_during_cooldown=True))
        self.assertGreater(short["score"], long["score"])

    def test_lower_cost_scores_higher(self):
        cheap = A().analyze(make_pos(daily_volatility_pct=0.1,
                                     cooldown_days=4.0,
                                     earns_during_cooldown=True))
        pricey = A().analyze(make_pos(daily_volatility_pct=4.0,
                                      cooldown_days=4.0,
                                      earns_during_cooldown=True))
        self.assertGreater(cheap["score"], pricey["score"])

    def test_trapped_scores_lower(self):
        free = A().analyze(make_pos(cooldown_days=4.0,
                                    daily_volatility_pct=0.1,
                                    exit_urgency_days=0.0,
                                    earns_during_cooldown=True))
        trap = A().analyze(make_pos(cooldown_days=4.0,
                                    daily_volatility_pct=0.1,
                                    exit_urgency_days=2.0,
                                    earns_during_cooldown=True))
        self.assertGreater(free["score"], trap["score"])

    def test_score_floor(self):
        r = A().analyze(make_pos(cooldown_days=100.0,
                                 daily_volatility_pct=50.0,
                                 exit_urgency_days=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_extreme_bounds(self):
        r = A().analyze(make_pos(position_usd=1e12, cooldown_days=1e6,
                                 daily_volatility_pct=1e6))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(cooldown_days=0.0),
                    make_pos(),
                    make_pos(daily_volatility_pct=5.0),
                    make_pos(cooldown_days=14.0, exit_urgency_days=2.0),
                    make_pos(position_usd=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(cooldown_days=0.0), make_pos(),
                    make_pos(daily_volatility_pct=5.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", cooldown_days=1.0,
                     daily_volatility_pct=0.1, earns_during_cooldown=True),
            make_pos(vault="Risky", cooldown_days=20.0,
                     daily_volatility_pct=5.0),
            make_pos(vault="Mid", cooldown_days=7.0,
                     daily_volatility_pct=1.0, earns_during_cooldown=True),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_safest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["safest_vault"]], max(scores.values()))

    def test_riskiest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["riskiest_vault"]], min(scores.values()))

    def test_safest_is_safe(self):
        self.assertEqual(self.res["aggregate"]["safest_vault"], "Safe")

    def test_riskiest_is_risky(self):
        self.assertEqual(self.res["aggregate"]["riskiest_vault"], "Risky")

    def test_avg_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_trapped_count(self):
        res = A().analyze_portfolio([
            make_pos(vault="T1", cooldown_days=10.0, exit_urgency_days=2.0),
            make_pos(vault="T2", cooldown_days=10.0, exit_urgency_days=3.0),
            make_pos(vault="Safe", cooldown_days=1.0),
        ])
        self.assertEqual(res["aggregate"]["trapped_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertIsNone(res["aggregate"]["riskiest_vault"])
        self.assertEqual(res["aggregate"]["position_count"], 0)
        self.assertEqual(res["aggregate"]["trapped_count"], 0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(position_usd=0.0),
            make_pos(position_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["safest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["riskiest_vault"], "Solo")

    def test_portfolio_json(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", position_usd=0.0),
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

    def test_log_has_snapshots(self):
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

    def test_log_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="big", position_usd=1e12,
                         daily_volatility_pct=1e6, cooldown_days=1e6),
                make_pos(vault="ins", position_usd=0.0),
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

    def test_no_write_demo_no_production_log(self):
        before = os.path.exists(LOG_PATH)
        A().analyze_portfolio(_demo_positions())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "position_usd": "100000",
            "cooldown_days": "7",
            "daily_volatility_pct": "1.0",
            "vault_apr_pct": "10",
            "exit_urgency_days": "0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "position_usd": 1000.0})
        self.assertIn("classification", r)

    def test_large_portfolio(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_json_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(position_usd=0.0),
            make_pos(cooldown_days=0.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(cooldown_days=0.0),
                    make_pos(position_usd=0.0),
                    make_pos(daily_volatility_pct=1e9, cooldown_days=1e9),
                    make_pos(position_usd=1e18, vault_apr_pct=1e9,
                             cooldown_days=1e9),
                    make_pos(vault_apr_pct=-1e9),
                    make_pos(exit_urgency_days=-5.0),
                    make_pos(daily_volatility_pct=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(position_usd=1e15, cooldown_days=1e6,
                                 daily_volatility_pct=1e4,
                                 vault_apr_pct=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(cooldown_days=-10.0,
                                 daily_volatility_pct=-5.0,
                                 vault_apr_pct=-10.0,
                                 exit_urgency_days=-3.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_zero_cooldown_zero_cost(self):
        r = A().analyze(make_pos(cooldown_days=0.0))
        self.assertAlmostEqual(r["cooldown_cost_pct"], 0.0)
        self.assertAlmostEqual(r["value_at_risk_usd"], 0.0)
        finite_check(self, r)


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_count(self):
        self.assertEqual(len(_demo_positions()), 4)

    def test_demo_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        self.assertIn("aggregate", res)

    def test_demo_json(self):
        json.dumps(A().analyze_portfolio(_demo_positions()))

    def test_demo_no_inf_nan(self):
        raw = json.dumps(A().analyze_portfolio(_demo_positions()))
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)

    def test_demo_varied_classifications(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertGreater(len(classes), 1)

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_instant_exit(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSTANT_EXIT", classes)

    def test_demo_includes_trapped(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("TRAPPED_RISK", classes)

    def test_demo_each_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
