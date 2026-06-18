"""
Tests for MP-1161: DeFiProtocolVaultWithdrawalFeeDecayAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_withdrawal_fee_decay_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_withdrawal_fee_decay_analyzer import (
    DeFiProtocolVaultWithdrawalFeeDecayAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    HIGH_FEE_PCT,
    MODERATE_FEE_PCT,
    LOW_FEE_PCT,
    NEAR_FLOOR_DAYS,
    LONG_RAMP_DAYS,
    DAYS_PER_YEAR,
    FEE_EPSILON,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    initial_withdrawal_fee_pct=3.0,
    floor_withdrawal_fee_pct=0.1,
    fee_decay_days=30.0,
    days_held=10.0,
    position_usd=10000.0,
    apr_pct=8.0,
):
    return {
        "vault": vault,
        "initial_withdrawal_fee_pct": initial_withdrawal_fee_pct,
        "floor_withdrawal_fee_pct": floor_withdrawal_fee_pct,
        "fee_decay_days": fee_decay_days,
        "days_held": days_held,
        "position_usd": position_usd,
        "apr_pct": apr_pct,
    }


def A():
    return DeFiProtocolVaultWithdrawalFeeDecayAnalyzer()


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
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertIn("log_path", cfg)

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

    def test_constants_sane(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)
        self.assertLess(LOW_FEE_PCT, MODERATE_FEE_PCT)
        self.assertLess(MODERATE_FEE_PCT, HIGH_FEE_PCT)
        self.assertLess(NEAR_FLOOR_DAYS, LONG_RAMP_DAYS)
        self.assertGreater(FEE_EPSILON, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "initial_withdrawal_fee_pct", "floor_withdrawal_fee_pct",
            "fee_decay_days", "days_held", "position_usd", "apr_pct",
            "progress", "current_fee_pct", "days_to_floor", "at_floor",
            "fee_now_usd", "fee_at_floor_usd", "fee_savings_if_wait_pct",
            "fee_savings_if_wait_usd", "yield_while_waiting_pct",
            "yield_while_waiting_usd", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "initial_withdrawal_fee_pct": 3.0,
                         "fee_decay_days": 30.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "initial_withdrawal_fee_pct": 3.0,
                         "fee_decay_days": 30.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"initial_withdrawal_fee_pct": 3.0,
                         "fee_decay_days": 30.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "EXIT_OK", "WAIT_FOR_DECAY", "HOLD_TO_FLOOR",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_at_floor_is_bool(self):
        self.assertIsInstance(self.r["at_floor"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_initial_clamped_high(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=200.0))
        self.assertAlmostEqual(r["initial_withdrawal_fee_pct"], 100.0)

    def test_initial_clamped_low(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=-5.0,
                                 floor_withdrawal_fee_pct=0.1))
        self.assertAlmostEqual(r["initial_withdrawal_fee_pct"], 0.0)

    def test_floor_clamped_high(self):
        r = A().analyze(make_pos(floor_withdrawal_fee_pct=200.0,
                                 initial_withdrawal_fee_pct=5.0))
        self.assertAlmostEqual(r["floor_withdrawal_fee_pct"], 100.0)

    def test_days_held_negative_clamped(self):
        r = A().analyze(make_pos(days_held=-10.0))
        self.assertAlmostEqual(r["days_held"], 0.0)

    def test_position_usd_negative_clamped(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertAlmostEqual(r["position_usd"], 0.0)

    def test_progress_half(self):
        # 15 of 30 days = 0.5
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=15.0))
        self.assertAlmostEqual(r["progress"], 0.5)

    def test_progress_clamped_full(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=60.0))
        self.assertAlmostEqual(r["progress"], 1.0)

    def test_progress_zero_at_start(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=0.0))
        self.assertAlmostEqual(r["progress"], 0.0)

    def test_current_fee_at_start_is_initial(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=0.0))
        self.assertAlmostEqual(r["current_fee_pct"], 3.0)

    def test_current_fee_at_end_is_floor(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=30.0))
        self.assertAlmostEqual(r["current_fee_pct"], 0.1)

    def test_current_fee_midpoint(self):
        # linear: at half progress, fee = (3 + 0.1)/2 = 1.55
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=15.0))
        self.assertAlmostEqual(r["current_fee_pct"], 1.55, places=4)

    def test_current_fee_never_below_floor(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=30.0, days_held=100.0))
        self.assertGreaterEqual(r["current_fee_pct"], 0.5 - 1e-9)

    def test_days_to_floor_calc(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=10.0))
        self.assertAlmostEqual(r["days_to_floor"], 20.0)

    def test_days_to_floor_zero_when_past(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertAlmostEqual(r["days_to_floor"], 0.0)

    def test_at_floor_true_when_held_past(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=45.0))
        self.assertTrue(r["at_floor"])

    def test_at_floor_false_when_fresh(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=2.0,
                                 initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1))
        self.assertFalse(r["at_floor"])

    def test_fee_now_usd_calc(self):
        # current fee 1.55% at half, position 10000 → 155
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=15.0,
                                 position_usd=10000.0))
        self.assertAlmostEqual(r["fee_now_usd"], 155.0, places=2)

    def test_fee_at_floor_usd_calc(self):
        r = A().analyze(make_pos(floor_withdrawal_fee_pct=0.1,
                                 position_usd=10000.0))
        self.assertAlmostEqual(r["fee_at_floor_usd"], 10.0, places=2)

    def test_fee_savings_if_wait_pct(self):
        # current 1.55, floor 0.1 → savings 1.45
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=15.0))
        self.assertAlmostEqual(r["fee_savings_if_wait_pct"], 1.45, places=4)

    def test_fee_savings_if_wait_usd(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=15.0,
                                 position_usd=10000.0))
        self.assertAlmostEqual(r["fee_savings_if_wait_usd"], 145.0, places=2)

    def test_fee_savings_zero_at_floor(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertAlmostEqual(r["fee_savings_if_wait_pct"], 0.0)

    def test_yield_while_waiting_pct(self):
        # apr 8%, days_to_floor 20 → 8*20/365
        r = A().analyze(make_pos(apr_pct=8.0, fee_decay_days=30.0,
                                 days_held=10.0))
        self.assertAlmostEqual(r["yield_while_waiting_pct"],
                               8.0 * 20.0 / 365.0, places=4)

    def test_yield_while_waiting_usd(self):
        r = A().analyze(make_pos(apr_pct=8.0, fee_decay_days=30.0,
                                 days_held=10.0, position_usd=10000.0))
        expected = 10000.0 * (8.0 * 20.0 / 365.0) / 100.0
        self.assertAlmostEqual(r["yield_while_waiting_usd"], expected, places=2)

    def test_yield_zero_at_floor(self):
        r = A().analyze(make_pos(apr_pct=8.0, fee_decay_days=30.0,
                                 days_held=40.0))
        self.assertAlmostEqual(r["yield_while_waiting_pct"], 0.0)

    def test_inverted_schedule_handled(self):
        # floor > initial: should not blow up, fee within bounds
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.5,
                                 floor_withdrawal_fee_pct=2.0,
                                 fee_decay_days=30.0, days_held=10.0))
        self.assertGreaterEqual(r["current_fee_pct"], 0.0)
        self.assertLessEqual(r["current_fee_pct"], 100.0)
        finite_check(self, r)

    def test_no_decay_days_progress_full(self):
        # fee_decay_days 0 but fees present → progress 1.0
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=0.0, days_held=5.0))
        self.assertAlmostEqual(r["progress"], 1.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_matured(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertEqual(r["classification"], "MATURED")

    def test_low_exit_fee(self):
        # current fee below LOW_FEE_PCT but not at floor
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=27.0))
        # at day 27 of 30: progress 0.9, fee = 3*(1-0.9) = 0.3 < 0.5
        self.assertEqual(r["classification"], "LOW_EXIT_FEE")

    def test_moderate_exit_fee(self):
        # current fee in [LOW, MODERATE)
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=20.0))
        # progress 2/3, fee = 3*(1/3) = 1.0 in [0.5, 2.0)
        self.assertEqual(r["classification"], "MODERATE_EXIT_FEE")

    def test_high_exit_fee(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=30.0, days_held=2.0))
        self.assertEqual(r["classification"], "HIGH_EXIT_FEE")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(days_held=40.0),
                    make_pos(days_held=2.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "MATURED", "LOW_EXIT_FEE", "MODERATE_EXIT_FEE",
                "HIGH_EXIT_FEE", "INSUFFICIENT_DATA",
            })

    def test_at_floor_overrides_to_matured(self):
        # full progress → MATURED regardless of fee value
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=3.0,
                                 fee_decay_days=10.0, days_held=20.0))
        self.assertEqual(r["classification"], "MATURED")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_exit_ok_when_matured(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")

    def test_exit_ok_when_low(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=27.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")

    def test_wait_for_decay_when_moderate(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=20.0))
        self.assertEqual(r["recommendation"], "WAIT_FOR_DECAY")

    def test_hold_to_floor_when_high(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=30.0, days_held=2.0))
        self.assertEqual(r["recommendation"], "HOLD_TO_FLOOR")

    def test_exit_ok_when_insufficient(self):
        # no fee schedule → free exit → EXIT_OK
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_at_floor_flag(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertIn("AT_FLOOR", r["flags"])

    def test_at_floor_flag_absent(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=2.0))
        self.assertNotIn("AT_FLOOR", r["flags"])

    def test_early_withdrawal_penalty_flag(self):
        # current fee well above floor + LOW_FEE_PCT
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=2.0))
        self.assertIn("EARLY_WITHDRAWAL_PENALTY", r["flags"])

    def test_early_withdrawal_penalty_flag_absent_at_floor(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertNotIn("EARLY_WITHDRAWAL_PENALTY", r["flags"])

    def test_high_exit_fee_flag(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=30.0, days_held=2.0))
        self.assertIn("HIGH_EXIT_FEE", r["flags"])

    def test_high_exit_fee_flag_at_boundary(self):
        # current fee exactly MODERATE_FEE_PCT → flag (>=)
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=MODERATE_FEE_PCT,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=0.0))
        self.assertIn("HIGH_EXIT_FEE", r["flags"])

    def test_high_exit_fee_flag_absent(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0, days_held=27.0))
        self.assertNotIn("HIGH_EXIT_FEE", r["flags"])

    def test_near_floor_flag(self):
        # not at floor, days_to_floor <= NEAR_FLOOR_DAYS
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=25.0))
        self.assertIn("NEAR_FLOOR", r["flags"])

    def test_near_floor_flag_absent_when_far(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=90.0, days_held=2.0))
        self.assertNotIn("NEAR_FLOOR", r["flags"])

    def test_near_floor_flag_absent_when_at_floor(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertNotIn("NEAR_FLOOR", r["flags"])

    def test_long_ramp_remaining_flag(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=90.0, days_held=2.0))
        self.assertIn("LONG_RAMP_REMAINING", r["flags"])

    def test_long_ramp_remaining_flag_absent(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=10.0))
        self.assertNotIn("LONG_RAMP_REMAINING", r["flags"])

    def test_zero_floor_fee_flag(self):
        r = A().analyze(make_pos(floor_withdrawal_fee_pct=0.0))
        self.assertIn("ZERO_FLOOR_FEE", r["flags"])

    def test_zero_floor_fee_flag_absent(self):
        r = A().analyze(make_pos(floor_withdrawal_fee_pct=0.5))
        self.assertNotIn("ZERO_FLOOR_FEE", r["flags"])

    def test_wait_saves_fee_flag(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.1,
                                 fee_decay_days=30.0, days_held=10.0))
        self.assertIn("WAIT_SAVES_FEE", r["flags"])

    def test_wait_saves_fee_flag_absent_at_floor(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0))
        self.assertNotIn("WAIT_SAVES_FEE", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_fee_schedule(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_exit_ok(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_initial_is_sufficient(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_floor_is_sufficient(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.5,
                                 fee_decay_days=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_decay_days_is_sufficient(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=0.0,
                                 floor_withdrawal_fee_pct=0.0,
                                 fee_decay_days=30.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_progress_scores_higher(self):
        early = A().analyze(make_pos(fee_decay_days=30.0, days_held=2.0))
        late = A().analyze(make_pos(fee_decay_days=30.0, days_held=25.0))
        self.assertGreater(late["score"], early["score"])

    def test_matured_scores_high(self):
        r = A().analyze(make_pos(fee_decay_days=30.0, days_held=40.0,
                                 floor_withdrawal_fee_pct=0.1))
        self.assertGreater(r["score"], 85.0)

    def test_fresh_high_fee_scores_low(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=5.0,
                                 floor_withdrawal_fee_pct=2.0,
                                 fee_decay_days=90.0, days_held=1.0))
        self.assertLess(r["score"], 55.0)

    def test_lower_current_fee_scores_higher(self):
        low = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                   floor_withdrawal_fee_pct=0.0,
                                   fee_decay_days=30.0, days_held=27.0))
        high = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                    floor_withdrawal_fee_pct=0.0,
                                    fee_decay_days=30.0, days_held=3.0))
        self.assertGreater(low["score"], high["score"])

    def test_lower_floor_scores_higher(self):
        low_floor = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                         floor_withdrawal_fee_pct=0.0,
                                         fee_decay_days=30.0, days_held=15.0))
        high_floor = A().analyze(make_pos(initial_withdrawal_fee_pct=3.0,
                                          floor_withdrawal_fee_pct=2.0,
                                          fee_decay_days=30.0, days_held=15.0))
        self.assertGreater(low_floor["score"], high_floor["score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=100.0,
                                 floor_withdrawal_fee_pct=100.0,
                                 fee_decay_days=1.0, days_held=0.0,
                                 position_usd=1e9, apr_pct=1000.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=100.0,
                                 floor_withdrawal_fee_pct=100.0,
                                 fee_decay_days=30.0, days_held=0.0))
        self.assertGreaterEqual(r["score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Matured", fee_decay_days=30.0, days_held=40.0,
                     floor_withdrawal_fee_pct=0.0),
            make_pos(vault="Fresh", initial_withdrawal_fee_pct=5.0,
                     floor_withdrawal_fee_pct=0.5, fee_decay_days=90.0,
                     days_held=1.0),
            make_pos(vault="Mid", initial_withdrawal_fee_pct=3.0,
                     floor_withdrawal_fee_pct=0.0, fee_decay_days=30.0,
                     days_held=20.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_cheapest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["cheapest_to_exit_vault"]],
                         max(scores.values()))

    def test_most_expensive_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_expensive_to_exit_vault"]],
                         min(scores.values()))

    def test_cheapest_is_matured(self):
        self.assertEqual(self.res["aggregate"]["cheapest_to_exit_vault"],
                         "Matured")

    def test_most_expensive_is_fresh(self):
        self.assertEqual(self.res["aggregate"]["most_expensive_to_exit_vault"],
                         "Fresh")

    def test_high_fee_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_fee_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["cheapest_to_exit_vault"])
        self.assertIsNone(res["aggregate"]["most_expensive_to_exit_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(initial_withdrawal_fee_pct=0.0,
                     floor_withdrawal_fee_pct=0.0, fee_decay_days=0.0),
            make_pos(initial_withdrawal_fee_pct=0.0,
                     floor_withdrawal_fee_pct=0.0, fee_decay_days=0.0),
        ])
        self.assertIsNone(res["aggregate"]["cheapest_to_exit_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["cheapest_to_exit_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_expensive_to_exit_vault"],
                         "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_fee_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="H", initial_withdrawal_fee_pct=5.0,
                     floor_withdrawal_fee_pct=0.5, fee_decay_days=30.0,
                     days_held=2.0),
        ])
        self.assertEqual(res["aggregate"]["high_fee_count"], 1)


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
                make_pos(vault="big", initial_withdrawal_fee_pct=100.0,
                         floor_withdrawal_fee_pct=100.0, position_usd=1e9),
                make_pos(vault="ins", initial_withdrawal_fee_pct=0.0,
                         floor_withdrawal_fee_pct=0.0, fee_decay_days=0.0),
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

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "initial_withdrawal_fee_pct": "3",
            "floor_withdrawal_fee_pct": "0.1",
            "fee_decay_days": "30",
            "days_held": "10",
            "position_usd": "10000",
            "apr_pct": "8",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "initial_withdrawal_fee_pct": 3.0,
                         "fee_decay_days": 30.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(initial_withdrawal_fee_pct=0.0,
                     floor_withdrawal_fee_pct=0.0, fee_decay_days=0.0),
            make_pos(days_held=40.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(days_held=40.0),
                    make_pos(days_held=0.0),
                    make_pos(initial_withdrawal_fee_pct=0.0,
                             floor_withdrawal_fee_pct=0.0, fee_decay_days=0.0),
                    make_pos(initial_withdrawal_fee_pct=200.0,
                             floor_withdrawal_fee_pct=200.0),
                    make_pos(fee_decay_days=0.0),
                    make_pos(apr_pct=-50.0),
                    make_pos(position_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_position_usd_no_crash(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertIn("classification", r)
        self.assertAlmostEqual(r["fee_now_usd"], 0.0)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(initial_withdrawal_fee_pct=100.0,
                                 fee_decay_days=1e6, days_held=1.0,
                                 position_usd=1e12, apr_pct=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_apr_no_crash(self):
        r = A().analyze(make_pos(apr_pct=-10.0))
        self.assertIn("classification", r)
        finite_check(self, r)


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

    def test_demo_includes_matured(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("MATURED", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
