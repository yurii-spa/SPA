"""
Tests for MP-1167: DeFiProtocolVaultHarvestTimingAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_harvest_timing_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_harvest_timing_analyzer import (
    DeFiProtocolVaultHarvestTimingAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_HARVEST_RATIO_MIN,
    MIN_HARVEST_RATIO_MAX,
    APPROACHING_OPTIMAL_FRACTION,
    OVERDUE_OPTIMAL_MULTIPLE,
    GAS_DRAG_SCORE_CEILING_PCT,
    HIGH_GAS_DRAG_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    pending_rewards_usd=200.0,
    harvest_gas_usd=25.0,
    reward_accrual_usd_per_day=6.0,
    days_since_last_harvest=10.0,
    min_harvest_ratio=3.0,
):
    return {
        "vault": vault,
        "pending_rewards_usd": pending_rewards_usd,
        "harvest_gas_usd": harvest_gas_usd,
        "reward_accrual_usd_per_day": reward_accrual_usd_per_day,
        "days_since_last_harvest": days_since_last_harvest,
        "min_harvest_ratio": min_harvest_ratio,
    }


def A():
    return DeFiProtocolVaultHarvestTimingAnalyzer()


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
        self.assertLess(MIN_HARVEST_RATIO_MIN, MIN_HARVEST_RATIO_MAX)
        self.assertGreater(APPROACHING_OPTIMAL_FRACTION, 0.0)
        self.assertLess(APPROACHING_OPTIMAL_FRACTION, 1.0)
        self.assertGreater(OVERDUE_OPTIMAL_MULTIPLE, 1.0)
        self.assertGreater(GAS_DRAG_SCORE_CEILING_PCT, 0)
        self.assertGreater(HIGH_GAS_DRAG_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "pending_rewards_usd", "harvest_gas_usd",
            "reward_accrual_usd_per_day", "days_since_last_harvest",
            "min_harvest_ratio", "gas_to_reward_ratio", "reward_to_gas_ratio",
            "harvest_worthwhile_now", "optimal_harvest_pending_usd",
            "days_to_optimal", "optimal_interval_days",
            "net_if_harvest_now_usd", "gas_drag_pct", "overdue",
            "current_accrual_per_day", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "pending_rewards_usd": 200.0,
                         "harvest_gas_usd": 25.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "pending_rewards_usd": 200.0, "harvest_gas_usd": 25.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"pending_rewards_usd": 200.0, "harvest_gas_usd": 25.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HARVEST_NOW", "WAIT_SHORT", "WAIT", "DO_NOT_HARVEST_YET",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "HARVEST_NOW", "APPROACHING_OPTIMAL", "TOO_EARLY",
            "GAS_EXCEEDS_REWARD", "INSUFFICIENT_DATA",
        })

    def test_harvest_worthwhile_is_bool(self):
        self.assertIsInstance(self.r["harvest_worthwhile_now"], bool)

    def test_overdue_is_bool(self):
        self.assertIsInstance(self.r["overdue"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_pending_negative_clamped(self):
        # pending<0 → 0, but accrual keeps it sufficient
        r = A().analyze(make_pos(pending_rewards_usd=-100.0))
        self.assertAlmostEqual(r["pending_rewards_usd"], 0.0)

    def test_gas_negative_clamped(self):
        r = A().analyze(make_pos(harvest_gas_usd=-5.0))
        self.assertAlmostEqual(r["harvest_gas_usd"], 0.0)

    def test_accrual_negative_clamped(self):
        r = A().analyze(make_pos(reward_accrual_usd_per_day=-6.0))
        self.assertAlmostEqual(r["reward_accrual_usd_per_day"], 0.0)

    def test_days_since_negative_clamped(self):
        r = A().analyze(make_pos(days_since_last_harvest=-10.0))
        self.assertAlmostEqual(r["days_since_last_harvest"], 0.0)

    def test_min_ratio_clamped_low(self):
        r = A().analyze(make_pos(min_harvest_ratio=0.01))
        self.assertAlmostEqual(r["min_harvest_ratio"], MIN_HARVEST_RATIO_MIN)

    def test_min_ratio_clamped_high(self):
        r = A().analyze(make_pos(min_harvest_ratio=999.0))
        self.assertAlmostEqual(r["min_harvest_ratio"], MIN_HARVEST_RATIO_MAX)

    def test_min_ratio_default(self):
        r = A().analyze({"vault": "X", "pending_rewards_usd": 200.0,
                         "harvest_gas_usd": 25.0,
                         "reward_accrual_usd_per_day": 6.0})
        self.assertAlmostEqual(r["min_harvest_ratio"], 3.0)

    def test_gas_to_reward_ratio(self):
        # gas 25 / pending 200 = 0.125
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertAlmostEqual(r["gas_to_reward_ratio"], 0.125)

    def test_gas_to_reward_ratio_none_no_pending(self):
        # no pending but accrual present
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=6.0))
        self.assertIsNone(r["gas_to_reward_ratio"])

    def test_reward_to_gas_ratio(self):
        # pending 200 / gas 25 = 8
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertAlmostEqual(r["reward_to_gas_ratio"], 8.0)

    def test_reward_to_gas_ratio_none_free_gas(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=0.0))
        self.assertIsNone(r["reward_to_gas_ratio"])

    def test_harvest_worthwhile_now_true(self):
        # pending 200 >= 25*3 = 75
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertTrue(r["harvest_worthwhile_now"])

    def test_harvest_worthwhile_now_false(self):
        # pending 40 < 75
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertFalse(r["harvest_worthwhile_now"])

    def test_harvest_worthwhile_free_gas(self):
        r = A().analyze(make_pos(pending_rewards_usd=1.0, harvest_gas_usd=0.0))
        self.assertTrue(r["harvest_worthwhile_now"])

    def test_optimal_harvest_pending(self):
        # gas 25 * ratio 3 = 75
        r = A().analyze(make_pos(harvest_gas_usd=25.0, min_harvest_ratio=3.0))
        self.assertAlmostEqual(r["optimal_harvest_pending_usd"], 75.0)

    def test_days_to_optimal(self):
        # (75 - 40)/6 = 5.8333
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 reward_accrual_usd_per_day=6.0,
                                 min_harvest_ratio=3.0))
        self.assertAlmostEqual(r["days_to_optimal"], (75.0 - 40.0) / 6.0,
                               places=2)

    def test_days_to_optimal_zero_when_past(self):
        # pending already above optimal → 0
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0,
                                 reward_accrual_usd_per_day=6.0,
                                 min_harvest_ratio=3.0))
        self.assertAlmostEqual(r["days_to_optimal"], 0.0)

    def test_days_to_optimal_none_no_accrual(self):
        r = A().analyze(make_pos(pending_rewards_usd=40.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertIsNone(r["days_to_optimal"])

    def test_optimal_interval_days(self):
        # 75 / 6 = 12.5
        r = A().analyze(make_pos(harvest_gas_usd=25.0,
                                 reward_accrual_usd_per_day=6.0,
                                 min_harvest_ratio=3.0))
        self.assertAlmostEqual(r["optimal_interval_days"], 75.0 / 6.0, places=2)

    def test_optimal_interval_none_no_accrual(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertIsNone(r["optimal_interval_days"])

    def test_net_if_harvest_now(self):
        # pending 200 - gas 25 = 175
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertAlmostEqual(r["net_if_harvest_now_usd"], 175.0)

    def test_net_negative(self):
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0))
        self.assertAlmostEqual(r["net_if_harvest_now_usd"], -15.0)

    def test_gas_drag_pct(self):
        # gas 25 / pending 200 * 100 = 12.5
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 12.5)

    def test_gas_drag_zero_no_pending(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=6.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 0.0)

    def test_overdue_true(self):
        # pending 200 >= 75*1.5 = 112.5
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertTrue(r["overdue"])

    def test_overdue_false(self):
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertFalse(r["overdue"])

    def test_current_accrual_passthrough(self):
        r = A().analyze(make_pos(reward_accrual_usd_per_day=6.0))
        self.assertAlmostEqual(r["current_accrual_per_day"], 6.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("pending_rewards_usd", "harvest_gas_usd", "gas_drag_pct",
                  "optimal_harvest_pending_usd", "net_if_harvest_now_usd"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_harvest_now(self):
        # worthwhile and net > 0
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertEqual(r["classification"], "HARVEST_NOW")

    def test_approaching_optimal(self):
        # pending 40 >= optimal 75 * 0.5 = 37.5, net > 0, not worthwhile
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertEqual(r["classification"], "APPROACHING_OPTIMAL")

    def test_too_early(self):
        # pending 20 < optimal 75 * 0.5 = 37.5, net < 0? 20-10=10>0
        r = A().analyze(make_pos(pending_rewards_usd=20.0, harvest_gas_usd=10.0,
                                 min_harvest_ratio=5.0))
        # optimal = 50, half = 25, pending 20 < 25, net = 10 > 0 → TOO_EARLY
        self.assertEqual(r["classification"], "TOO_EARLY")

    def test_gas_exceeds_reward(self):
        # net <= 0 and pending > 0
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertEqual(r["classification"], "GAS_EXCEEDS_REWARD")

    def test_insufficient_no_pending_no_accrual(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0, harvest_gas_usd=25.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_free_harvest_classifies_harvest_now(self):
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=0.0))
        self.assertEqual(r["classification"], "HARVEST_NOW")

    def test_classification_known_value(self):
        for pos in [make_pos(),
                    make_pos(pending_rewards_usd=40.0),
                    make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0),
                    make_pos(pending_rewards_usd=0.0,
                             reward_accrual_usd_per_day=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "HARVEST_NOW", "APPROACHING_OPTIMAL", "TOO_EARLY",
                "GAS_EXCEEDS_REWARD", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_harvest_now_rec(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertEqual(r["recommendation"], "HARVEST_NOW")

    def test_wait_short_rec(self):
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertEqual(r["recommendation"], "WAIT_SHORT")

    def test_wait_rec(self):
        r = A().analyze(make_pos(pending_rewards_usd=20.0, harvest_gas_usd=10.0,
                                 min_harvest_ratio=5.0))
        self.assertEqual(r["recommendation"], "WAIT")

    def test_do_not_harvest_yet_rec(self):
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0))
        self.assertEqual(r["recommendation"], "DO_NOT_HARVEST_YET")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertEqual(r["recommendation"], "DO_NOT_HARVEST_YET")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_harvest_now_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0))
        self.assertIn("HARVEST_NOW", r["flags"])

    def test_overdue_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertIn("OVERDUE", r["flags"])

    def test_overdue_flag_absent(self):
        r = A().analyze(make_pos(pending_rewards_usd=40.0, harvest_gas_usd=25.0,
                                 min_harvest_ratio=3.0))
        self.assertNotIn("OVERDUE", r["flags"])

    def test_too_early_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=20.0, harvest_gas_usd=10.0,
                                 min_harvest_ratio=5.0))
        self.assertIn("TOO_EARLY", r["flags"])

    def test_gas_exceeds_reward_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0))
        self.assertIn("GAS_EXCEEDS_REWARD", r["flags"])

    def test_free_harvest_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=50.0, harvest_gas_usd=0.0))
        self.assertIn("FREE_HARVEST", r["flags"])

    def test_free_harvest_flag_absent(self):
        r = A().analyze(make_pos(harvest_gas_usd=25.0))
        self.assertNotIn("FREE_HARVEST", r["flags"])

    def test_high_gas_drag_flag(self):
        # gas 25 / pending 50 * 100 = 50 >= 33
        r = A().analyze(make_pos(pending_rewards_usd=50.0, harvest_gas_usd=25.0))
        self.assertIn("HIGH_GAS_DRAG", r["flags"])

    def test_high_gas_drag_flag_absent(self):
        r = A().analyze(make_pos(pending_rewards_usd=1000.0, harvest_gas_usd=25.0))
        self.assertNotIn("HIGH_GAS_DRAG", r["flags"])

    def test_no_accrual_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertIn("NO_ACCRUAL", r["flags"])

    def test_no_accrual_flag_absent(self):
        r = A().analyze(make_pos(reward_accrual_usd_per_day=6.0))
        self.assertNotIn("NO_ACCRUAL", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_pending_no_accrual(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertEqual(r["recommendation"], "DO_NOT_HARVEST_YET")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_pending_alone_is_sufficient(self):
        r = A().analyze(make_pos(pending_rewards_usd=200.0,
                                 reward_accrual_usd_per_day=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_accrual_alone_is_sufficient(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0,
                                 reward_accrual_usd_per_day=6.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_inputs_insufficient(self):
        r = A().analyze(make_pos(pending_rewards_usd=-100.0,
                                 reward_accrual_usd_per_day=-6.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["gas_to_reward_ratio"])
        self.assertIsNone(r["reward_to_gas_ratio"])
        self.assertIsNone(r["days_to_optimal"])
        self.assertIsNone(r["optimal_interval_days"])

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("pending_rewards_usd", "harvest_gas_usd", "gas_drag_pct",
                  "optimal_harvest_pending_usd", "net_if_harvest_now_usd",
                  "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["harvest_worthwhile_now"])
        self.assertFalse(r["overdue"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_lower_gas_drag_scores_higher(self):
        low = A().analyze(make_pos(pending_rewards_usd=1000.0,
                                   harvest_gas_usd=25.0))
        high = A().analyze(make_pos(pending_rewards_usd=50.0,
                                    harvest_gas_usd=25.0))
        self.assertGreater(low["score"], high["score"])

    def test_worthwhile_scores_higher(self):
        worth = A().analyze(make_pos(pending_rewards_usd=200.0,
                                     harvest_gas_usd=25.0))
        notyet = A().analyze(make_pos(pending_rewards_usd=40.0,
                                      harvest_gas_usd=25.0))
        self.assertGreater(worth["score"], notyet["score"])

    def test_harvest_now_scores_high(self):
        r = A().analyze(make_pos(pending_rewards_usd=1000.0, harvest_gas_usd=10.0))
        self.assertGreater(r["score"], 70.0)

    def test_gas_exceeds_scores_low(self):
        r = A().analyze(make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0))
        self.assertLess(r["score"], 55.0)

    def test_free_harvest_high_score(self):
        r = A().analyze(make_pos(pending_rewards_usd=100.0, harvest_gas_usd=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(pending_rewards_usd=1e12, harvest_gas_usd=1e-9,
                                 reward_accrual_usd_per_day=1e9,
                                 min_harvest_ratio=50.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(pending_rewards_usd=1.0, harvest_gas_usd=1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(),
                    make_pos(pending_rewards_usd=40.0),
                    make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0),
                    make_pos(harvest_gas_usd=0.0),
                    make_pos(pending_rewards_usd=0.0,
                             reward_accrual_usd_per_day=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(pending_rewards_usd=1000.0, harvest_gas_usd=10.0),
                    make_pos(pending_rewards_usd=10.0, harvest_gas_usd=25.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Ready", pending_rewards_usd=1000.0,
                     harvest_gas_usd=10.0),
            make_pos(vault="NotReady", pending_rewards_usd=10.0,
                     harvest_gas_usd=25.0),
            make_pos(vault="Mid", pending_rewards_usd=40.0,
                     harvest_gas_usd=25.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_ready_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_ready_vault"]], max(scores.values()))

    def test_least_ready_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_ready_vault"]], min(scores.values()))

    def test_most_ready_is_ready(self):
        self.assertEqual(self.res["aggregate"]["most_ready_vault"], "Ready")

    def test_least_ready_is_notready(self):
        self.assertEqual(self.res["aggregate"]["least_ready_vault"], "NotReady")

    def test_harvest_now_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["harvest_now_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_ready_vault"])
        self.assertIsNone(res["aggregate"]["least_ready_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(pending_rewards_usd=0.0, reward_accrual_usd_per_day=0.0),
            make_pos(pending_rewards_usd=0.0, reward_accrual_usd_per_day=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_ready_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["harvest_now_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_ready_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_ready_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", pending_rewards_usd=1000.0,
                     harvest_gas_usd=10.0),
            make_pos(vault="Ins", pending_rewards_usd=0.0,
                     reward_accrual_usd_per_day=0.0),
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
                make_pos(vault="big", pending_rewards_usd=1e12,
                         harvest_gas_usd=1e-9,
                         reward_accrual_usd_per_day=1e9,
                         min_harvest_ratio=50.0),
                make_pos(vault="ins", pending_rewards_usd=0.0,
                         reward_accrual_usd_per_day=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            # full result with None fields must serialize to JSON null
            res = A().analyze(make_pos(pending_rewards_usd=0.0,
                                       reward_accrual_usd_per_day=6.0))
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
            "pending_rewards_usd": "200",
            "harvest_gas_usd": "25",
            "reward_accrual_usd_per_day": "6",
            "days_since_last_harvest": "10",
            "min_harvest_ratio": "3",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "pending_rewards_usd": 200.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(pending_rewards_usd=0.0, reward_accrual_usd_per_day=0.0),
            make_pos(harvest_gas_usd=0.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(pending_rewards_usd=40.0),
                    make_pos(pending_rewards_usd=0.0,
                             reward_accrual_usd_per_day=6.0),
                    make_pos(pending_rewards_usd=0.0,
                             reward_accrual_usd_per_day=0.0),
                    make_pos(pending_rewards_usd=1e12, harvest_gas_usd=1e-9),
                    make_pos(harvest_gas_usd=0.0),
                    make_pos(reward_accrual_usd_per_day=1e9),
                    make_pos(harvest_gas_usd=1e12),
                    make_pos(pending_rewards_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_accrual_no_crash(self):
        r = A().analyze(make_pos(reward_accrual_usd_per_day=0.0))
        self.assertIsNone(r["days_to_optimal"])
        self.assertIsNone(r["optimal_interval_days"])
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(pending_rewards_usd=1e12, harvest_gas_usd=1e9,
                                 reward_accrual_usd_per_day=1e9,
                                 min_harvest_ratio=50.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_huge_gas_no_inf(self):
        r = A().analyze(make_pos(pending_rewards_usd=1.0, harvest_gas_usd=1e12))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(pending_rewards_usd=-100.0,
                                 harvest_gas_usd=-25.0,
                                 reward_accrual_usd_per_day=-6.0,
                                 days_since_last_harvest=-10.0,
                                 min_harvest_ratio=-3.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(), make_pos(harvest_gas_usd=0.0),
                    make_pos(reward_accrual_usd_per_day=0.0),
                    make_pos(pending_rewards_usd=0.0,
                             reward_accrual_usd_per_day=6.0)]:
            r = A().analyze(pos)
            for k in ("gas_to_reward_ratio", "reward_to_gas_ratio",
                      "days_to_optimal", "optimal_interval_days"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))


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

    def test_demo_includes_harvest_now(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("HARVEST_NOW", classes)

    def test_demo_includes_early_or_gas_exceeds(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "TOO_EARLY" in classes or "GAS_EXCEEDS_REWARD" in classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
