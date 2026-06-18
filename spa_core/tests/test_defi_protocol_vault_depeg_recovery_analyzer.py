"""
Tests for MP-1165: DeFiProtocolVaultDepegRecoveryAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_depeg_recovery_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_depeg_recovery_analyzer import (
    DeFiProtocolVaultDepegRecoveryAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    AT_PEG_PCT,
    MINOR_DEPEG_PCT,
    MODERATE_DEPEG_PCT,
    DISCOUNT_SCORE_CEILING_PCT,
    FRESH_DEPEG_DAYS,
    STALE_DEPEG_DAYS,
    STRONG_RECOVERY_PCT,
    WEAK_RECOVERY_PCT,
    FULL_COLLATERAL_PCT,
    SEVERE_DISCOUNT_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    current_price_usd=0.98,
    peg_target_usd=1.0,
    days_depegged=5.0,
    historical_recoveries=8.0,
    historical_depegs=10.0,
    is_collateralized=True,
    collateral_ratio_pct=110.0,
    redemption_available=True,
):
    return {
        "vault": vault,
        "current_price_usd": current_price_usd,
        "peg_target_usd": peg_target_usd,
        "days_depegged": days_depegged,
        "historical_recoveries": historical_recoveries,
        "historical_depegs": historical_depegs,
        "is_collateralized": is_collateralized,
        "collateral_ratio_pct": collateral_ratio_pct,
        "redemption_available": redemption_available,
    }


def A():
    return DeFiProtocolVaultDepegRecoveryAnalyzer()


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
        self.assertEqual(_f(None, 1.0), 1.0)

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
        self.assertLess(AT_PEG_PCT, MINOR_DEPEG_PCT)
        self.assertLess(MINOR_DEPEG_PCT, MODERATE_DEPEG_PCT)
        self.assertGreater(DISCOUNT_SCORE_CEILING_PCT, 0)
        self.assertLess(FRESH_DEPEG_DAYS, STALE_DEPEG_DAYS)
        self.assertGreater(STRONG_RECOVERY_PCT, WEAK_RECOVERY_PCT)
        self.assertEqual(FULL_COLLATERAL_PCT, 100.0)

    def test_severe_discount_threshold(self):
        self.assertGreater(SEVERE_DISCOUNT_PCT, 0.0)
        self.assertGreaterEqual(SEVERE_DISCOUNT_PCT, MODERATE_DEPEG_PCT)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "current_price_usd", "peg_target_usd", "days_depegged",
            "historical_recoveries", "historical_depegs", "is_collateralized",
            "collateral_ratio_pct", "redemption_available", "depeg_pct",
            "discount_to_peg_pct", "recovery_rate_pct", "upside_if_recovers_pct",
            "is_stale_depeg", "undercollateralized", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "current_price_usd": 0.98})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "current_price_usd": 0.98})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"current_price_usd": 0.98})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD", "HOLD_FOR_RECOVERY", "EXIT_PARTIAL", "EXIT",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "AT_PEG", "MINOR_DEPEG", "MODERATE_DEPEG", "SEVERE_DEPEG",
            "INSUFFICIENT_DATA",
        })

    def test_is_collateralized_is_bool(self):
        self.assertIsInstance(self.r["is_collateralized"], bool)

    def test_is_stale_is_bool(self):
        self.assertIsInstance(self.r["is_stale_depeg"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_days_depegged_negative_clamped(self):
        r = A().analyze(make_pos(days_depegged=-5.0))
        self.assertAlmostEqual(r["days_depegged"], 0.0)

    def test_historical_recoveries_negative_clamped(self):
        r = A().analyze(make_pos(historical_recoveries=-5.0))
        self.assertAlmostEqual(r["historical_recoveries"], 0.0)

    def test_historical_depegs_negative_clamped(self):
        r = A().analyze(make_pos(historical_depegs=-5.0))
        self.assertAlmostEqual(r["historical_depegs"], 0.0)

    def test_collateral_ratio_negative_clamped(self):
        r = A().analyze(make_pos(collateral_ratio_pct=-5.0))
        self.assertAlmostEqual(r["collateral_ratio_pct"], 0.0)

    def test_peg_target_default(self):
        r = A().analyze({"vault": "X", "current_price_usd": 0.98})
        self.assertAlmostEqual(r["peg_target_usd"], 1.0)

    def test_depeg_pct(self):
        # (1.0 - 0.9)/1.0 * 100 = 10.0
        r = A().analyze(make_pos(current_price_usd=0.9, peg_target_usd=1.0))
        self.assertAlmostEqual(r["depeg_pct"], 10.0)

    def test_depeg_pct_premium_negative(self):
        # price above peg → depeg negative (premium)
        r = A().analyze(make_pos(current_price_usd=1.05, peg_target_usd=1.0))
        self.assertLess(r["depeg_pct"], 0.0)

    def test_discount_to_peg_pct(self):
        r = A().analyze(make_pos(current_price_usd=0.9, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 10.0)

    def test_discount_zero_on_premium(self):
        # premium → discount clamped to 0
        r = A().analyze(make_pos(current_price_usd=1.05, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 0.0)

    def test_recovery_rate_pct(self):
        # 8/10 * 100 = 80
        r = A().analyze(make_pos(historical_recoveries=8.0,
                                 historical_depegs=10.0))
        self.assertAlmostEqual(r["recovery_rate_pct"], 80.0)

    def test_recovery_rate_zero_no_history(self):
        r = A().analyze(make_pos(historical_recoveries=0.0,
                                 historical_depegs=0.0))
        self.assertAlmostEqual(r["recovery_rate_pct"], 0.0)

    def test_recovery_rate_clamped_100(self):
        # more recoveries than depegs → clamp to 100
        r = A().analyze(make_pos(historical_recoveries=20.0,
                                 historical_depegs=10.0))
        self.assertAlmostEqual(r["recovery_rate_pct"], 100.0)

    def test_upside_if_recovers(self):
        # price 0.8, peg 1.0 → (1.0/0.8 - 1)*100 = 25
        r = A().analyze(make_pos(current_price_usd=0.8, peg_target_usd=1.0))
        self.assertAlmostEqual(r["upside_if_recovers_pct"], 25.0, places=3)

    def test_upside_zero_at_or_above_peg(self):
        r = A().analyze(make_pos(current_price_usd=1.0, peg_target_usd=1.0))
        self.assertAlmostEqual(r["upside_if_recovers_pct"], 0.0)

    def test_upside_zero_premium(self):
        r = A().analyze(make_pos(current_price_usd=1.1, peg_target_usd=1.0))
        self.assertAlmostEqual(r["upside_if_recovers_pct"], 0.0)

    def test_is_stale_true(self):
        r = A().analyze(make_pos(days_depegged=40.0))
        self.assertTrue(r["is_stale_depeg"])

    def test_is_stale_false(self):
        r = A().analyze(make_pos(days_depegged=5.0))
        self.assertFalse(r["is_stale_depeg"])

    def test_is_stale_boundary(self):
        r = A().analyze(make_pos(days_depegged=STALE_DEPEG_DAYS))
        self.assertTrue(r["is_stale_depeg"])

    def test_undercollateralized_true(self):
        r = A().analyze(make_pos(is_collateralized=True,
                                 collateral_ratio_pct=80.0))
        self.assertTrue(r["undercollateralized"])

    def test_undercollateralized_false_full(self):
        r = A().analyze(make_pos(is_collateralized=True,
                                 collateral_ratio_pct=120.0))
        self.assertFalse(r["undercollateralized"])

    def test_undercollateralized_false_not_collateralized(self):
        r = A().analyze(make_pos(is_collateralized=False,
                                 collateral_ratio_pct=0.0))
        self.assertFalse(r["undercollateralized"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("depeg_pct", "discount_to_peg_pct", "recovery_rate_pct",
                  "upside_if_recovers_pct", "collateral_ratio_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_at_peg(self):
        r = A().analyze(make_pos(current_price_usd=0.9995, peg_target_usd=1.0))
        self.assertEqual(r["classification"], "AT_PEG")

    def test_minor_depeg(self):
        # discount in (0.5, 2]
        r = A().analyze(make_pos(current_price_usd=0.99, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 1.0)
        self.assertEqual(r["classification"], "MINOR_DEPEG")

    def test_moderate_depeg(self):
        # discount in (2, 10]
        r = A().analyze(make_pos(current_price_usd=0.95, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 5.0)
        self.assertEqual(r["classification"], "MODERATE_DEPEG")

    def test_severe_depeg(self):
        # discount > 10
        r = A().analyze(make_pos(current_price_usd=0.8, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 20.0)
        self.assertEqual(r["classification"], "SEVERE_DEPEG")

    def test_at_peg_boundary(self):
        # exactly 0.5% discount → AT_PEG (<=)
        r = A().analyze(make_pos(current_price_usd=0.995, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 0.5)
        self.assertEqual(r["classification"], "AT_PEG")

    def test_minor_boundary(self):
        # exactly 2% discount → MINOR (<=)
        r = A().analyze(make_pos(current_price_usd=0.98, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 2.0)
        self.assertEqual(r["classification"], "MINOR_DEPEG")

    def test_moderate_boundary(self):
        # exactly 10% discount → MODERATE (<=)
        r = A().analyze(make_pos(current_price_usd=0.9, peg_target_usd=1.0))
        self.assertAlmostEqual(r["discount_to_peg_pct"], 10.0)
        self.assertEqual(r["classification"], "MODERATE_DEPEG")

    def test_premium_is_at_peg(self):
        # price above peg → discount 0 → AT_PEG
        r = A().analyze(make_pos(current_price_usd=1.05, peg_target_usd=1.0))
        self.assertEqual(r["classification"], "AT_PEG")

    def test_classification_known_value(self):
        for pos in [make_pos(),
                    make_pos(current_price_usd=0.5),
                    make_pos(current_price_usd=0.999)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AT_PEG", "MINOR_DEPEG", "MODERATE_DEPEG", "SEVERE_DEPEG",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_hold_when_at_peg(self):
        r = A().analyze(make_pos(current_price_usd=0.9995))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_hold_for_recovery_when_minor(self):
        r = A().analyze(make_pos(current_price_usd=0.99))
        self.assertEqual(r["recommendation"], "HOLD_FOR_RECOVERY")

    def test_exit_partial_when_moderate_weak_history(self):
        r = A().analyze(make_pos(current_price_usd=0.95,
                                 historical_recoveries=1.0,
                                 historical_depegs=10.0))
        self.assertEqual(r["recommendation"], "EXIT_PARTIAL")

    def test_hold_for_recovery_when_moderate_strong_history(self):
        r = A().analyze(make_pos(current_price_usd=0.95,
                                 historical_recoveries=9.0,
                                 historical_depegs=10.0))
        self.assertEqual(r["recommendation"], "HOLD_FOR_RECOVERY")

    def test_exit_when_severe_weak_history(self):
        r = A().analyze(make_pos(current_price_usd=0.7,
                                 historical_recoveries=0.0,
                                 historical_depegs=5.0))
        self.assertEqual(r["recommendation"], "EXIT")

    def test_exit_partial_when_severe_strong_history(self):
        r = A().analyze(make_pos(current_price_usd=0.7,
                                 historical_recoveries=9.0,
                                 historical_depegs=10.0))
        self.assertEqual(r["recommendation"], "EXIT_PARTIAL")

    def test_exit_when_insufficient(self):
        r = A().analyze(make_pos(current_price_usd=0.0))
        self.assertEqual(r["recommendation"], "EXIT")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_at_peg_flag(self):
        r = A().analyze(make_pos(current_price_usd=0.9995))
        self.assertIn("AT_PEG", r["flags"])

    def test_at_peg_flag_absent(self):
        r = A().analyze(make_pos(current_price_usd=0.9))
        self.assertNotIn("AT_PEG", r["flags"])

    def test_fresh_depeg_flag(self):
        r = A().analyze(make_pos(days_depegged=3.0))
        self.assertIn("FRESH_DEPEG", r["flags"])

    def test_fresh_depeg_flag_absent(self):
        r = A().analyze(make_pos(days_depegged=10.0))
        self.assertNotIn("FRESH_DEPEG", r["flags"])

    def test_fresh_depeg_boundary(self):
        # exactly 7 days → not fresh (< 7)
        r = A().analyze(make_pos(days_depegged=FRESH_DEPEG_DAYS))
        self.assertNotIn("FRESH_DEPEG", r["flags"])

    def test_stale_depeg_flag(self):
        r = A().analyze(make_pos(days_depegged=40.0))
        self.assertIn("STALE_DEPEG", r["flags"])

    def test_stale_depeg_flag_absent(self):
        r = A().analyze(make_pos(days_depegged=10.0))
        self.assertNotIn("STALE_DEPEG", r["flags"])

    def test_stale_depeg_boundary(self):
        r = A().analyze(make_pos(days_depegged=STALE_DEPEG_DAYS))
        self.assertIn("STALE_DEPEG", r["flags"])

    def test_strong_recovery_flag(self):
        r = A().analyze(make_pos(historical_recoveries=8.0,
                                 historical_depegs=10.0))
        self.assertIn("STRONG_RECOVERY_HISTORY", r["flags"])

    def test_strong_recovery_boundary(self):
        # exactly 70% → strong (>=)
        r = A().analyze(make_pos(historical_recoveries=7.0,
                                 historical_depegs=10.0))
        self.assertIn("STRONG_RECOVERY_HISTORY", r["flags"])

    def test_strong_recovery_flag_absent(self):
        r = A().analyze(make_pos(historical_recoveries=5.0,
                                 historical_depegs=10.0))
        self.assertNotIn("STRONG_RECOVERY_HISTORY", r["flags"])

    def test_weak_recovery_flag(self):
        r = A().analyze(make_pos(historical_recoveries=2.0,
                                 historical_depegs=10.0))
        self.assertIn("WEAK_RECOVERY_HISTORY", r["flags"])

    def test_weak_recovery_flag_absent_no_history(self):
        # no history → not flagged (needs depegs>0)
        r = A().analyze(make_pos(historical_recoveries=0.0,
                                 historical_depegs=0.0))
        self.assertNotIn("WEAK_RECOVERY_HISTORY", r["flags"])

    def test_weak_recovery_boundary(self):
        # exactly 30% → not weak (< 30)
        r = A().analyze(make_pos(historical_recoveries=3.0,
                                 historical_depegs=10.0))
        self.assertNotIn("WEAK_RECOVERY_HISTORY", r["flags"])

    def test_collateralized_flag(self):
        r = A().analyze(make_pos(is_collateralized=True))
        self.assertIn("COLLATERALIZED", r["flags"])

    def test_collateralized_flag_absent(self):
        r = A().analyze(make_pos(is_collateralized=False))
        self.assertNotIn("COLLATERALIZED", r["flags"])

    def test_undercollateralized_flag(self):
        r = A().analyze(make_pos(is_collateralized=True,
                                 collateral_ratio_pct=80.0))
        self.assertIn("UNDERCOLLATERALIZED", r["flags"])

    def test_undercollateralized_flag_absent_full(self):
        r = A().analyze(make_pos(is_collateralized=True,
                                 collateral_ratio_pct=110.0))
        self.assertNotIn("UNDERCOLLATERALIZED", r["flags"])

    def test_undercollateralized_flag_absent_not_collat(self):
        r = A().analyze(make_pos(is_collateralized=False,
                                 collateral_ratio_pct=50.0))
        self.assertNotIn("UNDERCOLLATERALIZED", r["flags"])

    def test_undercollateralized_boundary(self):
        # exactly 100% → not undercollateralized (< 100)
        r = A().analyze(make_pos(is_collateralized=True,
                                 collateral_ratio_pct=100.0))
        self.assertNotIn("UNDERCOLLATERALIZED", r["flags"])

    def test_redemption_available_flag(self):
        r = A().analyze(make_pos(redemption_available=True))
        self.assertIn("REDEMPTION_AVAILABLE", r["flags"])

    def test_redemption_available_flag_absent(self):
        r = A().analyze(make_pos(redemption_available=False))
        self.assertNotIn("REDEMPTION_AVAILABLE", r["flags"])

    def test_severe_discount_flag(self):
        r = A().analyze(make_pos(current_price_usd=0.8))
        self.assertIn("SEVERE_DISCOUNT", r["flags"])

    def test_severe_discount_boundary(self):
        # exactly 10% discount → severe (>=)
        r = A().analyze(make_pos(current_price_usd=0.9))
        self.assertIn("SEVERE_DISCOUNT", r["flags"])

    def test_severe_discount_flag_absent(self):
        r = A().analyze(make_pos(current_price_usd=0.95))
        self.assertNotIn("SEVERE_DISCOUNT", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(current_price_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_price(self):
        r = A().analyze(make_pos(current_price_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_price(self):
        r = A().analyze(make_pos(current_price_usd=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_peg_target(self):
        r = A().analyze(make_pos(current_price_usd=0.98, peg_target_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_peg_target(self):
        r = A().analyze(make_pos(current_price_usd=0.98, peg_target_usd=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(current_price_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_exit(self):
        r = A().analyze(make_pos(current_price_usd=0.0))
        self.assertEqual(r["recommendation"], "EXIT")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_price_present_is_sufficient(self):
        r = A().analyze(make_pos(current_price_usd=0.98))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("discount_to_peg_pct", "recovery_rate_pct",
                  "upside_if_recovers_pct", "depeg_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_stale_depeg"])
        self.assertFalse(r["undercollateralized"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_shallower_depeg_scores_higher(self):
        shallow = A().analyze(make_pos(current_price_usd=0.99))
        deep = A().analyze(make_pos(current_price_usd=0.7))
        self.assertGreater(shallow["score"], deep["score"])

    def test_better_recovery_history_scores_higher(self):
        good = A().analyze(make_pos(historical_recoveries=10.0,
                                    historical_depegs=10.0))
        bad = A().analyze(make_pos(historical_recoveries=0.0,
                                   historical_depegs=10.0))
        self.assertGreater(good["score"], bad["score"])

    def test_fresher_depeg_scores_higher(self):
        fresh = A().analyze(make_pos(days_depegged=1.0))
        stale = A().analyze(make_pos(days_depegged=40.0))
        self.assertGreater(fresh["score"], stale["score"])

    def test_collateralized_scores_higher(self):
        collat = A().analyze(make_pos(is_collateralized=True,
                                      collateral_ratio_pct=150.0))
        nocollat = A().analyze(make_pos(is_collateralized=False,
                                        collateral_ratio_pct=0.0))
        self.assertGreater(collat["score"], nocollat["score"])

    def test_redemption_scores_higher(self):
        red = A().analyze(make_pos(redemption_available=True))
        nored = A().analyze(make_pos(redemption_available=False))
        self.assertGreater(red["score"], nored["score"])

    def test_at_peg_scores_high(self):
        r = A().analyze(make_pos(current_price_usd=0.9999, days_depegged=0.0,
                                 historical_recoveries=10.0,
                                 historical_depegs=10.0,
                                 is_collateralized=True,
                                 collateral_ratio_pct=150.0,
                                 redemption_available=True))
        self.assertGreater(r["score"], 85.0)

    def test_severe_depeg_scores_low(self):
        r = A().analyze(make_pos(current_price_usd=0.3, days_depegged=90.0,
                                 historical_recoveries=0.0,
                                 historical_depegs=5.0,
                                 is_collateralized=False,
                                 collateral_ratio_pct=0.0,
                                 redemption_available=False))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(current_price_usd=1e9, peg_target_usd=1e9,
                                 days_depegged=1e9,
                                 historical_recoveries=1e9,
                                 historical_depegs=1.0,
                                 collateral_ratio_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(current_price_usd=0.01, days_depegged=1000.0,
                                 historical_recoveries=0.0,
                                 historical_depegs=10.0,
                                 is_collateralized=False,
                                 redemption_available=False))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(),
                    make_pos(current_price_usd=0.5),
                    make_pos(days_depegged=0.0),
                    make_pos(is_collateralized=False)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Stable", current_price_usd=0.9999,
                     days_depegged=0.0, historical_recoveries=10.0,
                     historical_depegs=10.0, is_collateralized=True,
                     collateral_ratio_pct=150.0, redemption_available=True),
            make_pos(vault="Broken", current_price_usd=0.3, days_depegged=90.0,
                     historical_recoveries=0.0, historical_depegs=5.0,
                     is_collateralized=False, collateral_ratio_pct=0.0,
                     redemption_available=False),
            make_pos(vault="Mid", current_price_usd=0.96, days_depegged=10.0),
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

    def test_least_stable_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_stable_vault"]],
                         min(scores.values()))

    def test_most_stable_is_stable(self):
        self.assertEqual(self.res["aggregate"]["most_stable_vault"], "Stable")

    def test_least_stable_is_broken(self):
        self.assertEqual(self.res["aggregate"]["least_stable_vault"], "Broken")

    def test_severe_depeg_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["severe_depeg_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_stable_vault"])
        self.assertIsNone(res["aggregate"]["least_stable_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(current_price_usd=0.0),
            make_pos(current_price_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_stable_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_depeg_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_stable_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_stable_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_severe_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="S", current_price_usd=0.7),
        ])
        self.assertEqual(res["aggregate"]["severe_depeg_count"], 1)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", current_price_usd=0.9999),
            make_pos(vault="Ins", current_price_usd=0.0),
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
                make_pos(vault="big", current_price_usd=1e9,
                         peg_target_usd=1e9, days_depegged=1e9,
                         historical_recoveries=1e9, historical_depegs=1.0,
                         collateral_ratio_pct=1e9),
                make_pos(vault="ins", current_price_usd=0.0),
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
            "current_price_usd": "0.98",
            "peg_target_usd": "1.0",
            "days_depegged": "5",
            "historical_recoveries": "8",
            "historical_depegs": "10",
            "collateral_ratio_pct": "110",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "current_price_usd": 0.98})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(current_price_usd=0.0),
            make_pos(current_price_usd=0.5),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(current_price_usd=0.5),
                    make_pos(days_depegged=0.0),
                    make_pos(current_price_usd=0.0),
                    make_pos(current_price_usd=1e9, peg_target_usd=1e9),
                    make_pos(historical_depegs=0.0, historical_recoveries=0.0),
                    make_pos(current_price_usd=1e-9),
                    make_pos(collateral_ratio_pct=1e9),
                    make_pos(days_depegged=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_days_no_crash(self):
        r = A().analyze(make_pos(days_depegged=0.0))
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(current_price_usd=1e12, peg_target_usd=1e12,
                                 days_depegged=1e9,
                                 historical_recoveries=1e9,
                                 historical_depegs=1e9,
                                 collateral_ratio_pct=1e12))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_price_no_inf(self):
        # tiny price → huge upside but guarded finite
        r = A().analyze(make_pos(current_price_usd=1e-12, peg_target_usd=1.0))
        finite_check(self, r)
        self.assertGreaterEqual(r["upside_if_recovers_pct"], 0.0)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(current_price_usd=0.98,
                                 days_depegged=-5.0,
                                 historical_recoveries=-5.0,
                                 historical_depegs=-5.0,
                                 collateral_ratio_pct=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_discount_clamped_extreme(self):
        # absurd price below peg → discount clamped, finite
        r = A().analyze(make_pos(current_price_usd=0.0001, peg_target_usd=1.0))
        finite_check(self, r)
        self.assertLessEqual(r["discount_to_peg_pct"], 100.0)


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 3)

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

    def test_demo_includes_at_peg(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("AT_PEG", classes)

    def test_demo_includes_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("SEVERE_DEPEG", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
