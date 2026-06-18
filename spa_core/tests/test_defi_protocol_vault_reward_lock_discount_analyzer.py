"""
Tests for MP-1162: DeFiProtocolVaultRewardLockDiscountAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_reward_lock_discount_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_reward_lock_discount_analyzer import (
    DeFiProtocolVaultRewardLockDiscountAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    HIGH_HAIRCUT_SHARE_PCT,
    LONG_LOCK_DAYS,
    HIGH_PENALTY_PCT,
    DAYS_PER_YEAR,
    MOSTLY_LIQUID_SHARE,
    MODERATE_LOCK_SHARE,
    HEAVY_LOCK_SHARE,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    base_apr_pct=4.0,
    reward_apr_pct=6.0,
    lock_days=180.0,
    discount_rate_pct=30.0,
    early_unlock_penalty_pct=0.0,
    already_vested_pct=0.0,
):
    return {
        "vault": vault,
        "base_apr_pct": base_apr_pct,
        "reward_apr_pct": reward_apr_pct,
        "lock_days": lock_days,
        "discount_rate_pct": discount_rate_pct,
        "early_unlock_penalty_pct": early_unlock_penalty_pct,
        "already_vested_pct": already_vested_pct,
    }


def A():
    return DeFiProtocolVaultRewardLockDiscountAnalyzer()


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
        self.assertEqual(_f(None, 30.0), 30.0)

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
        self.assertEqual(DAYS_PER_YEAR, 365.0)
        self.assertLess(MOSTLY_LIQUID_SHARE, MODERATE_LOCK_SHARE)
        self.assertLess(MODERATE_LOCK_SHARE, HEAVY_LOCK_SHARE)
        self.assertGreater(HIGH_HAIRCUT_SHARE_PCT, 0)
        self.assertGreater(LONG_LOCK_DAYS, 0)
        self.assertGreater(HIGH_PENALTY_PCT, 0)

    def test_band_thresholds_in_range(self):
        self.assertLessEqual(HEAVY_LOCK_SHARE, 100.0)
        self.assertGreaterEqual(MOSTLY_LIQUID_SHARE, 0.0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "base_apr_pct", "reward_apr_pct", "lock_days",
            "discount_rate_pct", "early_unlock_penalty_pct",
            "already_vested_pct", "headline_apr_pct", "vested_reward_apr_pct",
            "locked_reward_apr_pct", "pv_factor", "discounted_reward_apr_pct",
            "liquid_equivalent_apr_pct", "apr_haircut_pct", "haircut_share_pct",
            "liquid_yield_apr_pct", "liquid_yield_share_pct", "locked_share_pct",
            "penalty_cost_apr_pct", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "base_apr_pct": 4.0,
                         "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "base_apr_pct": 4.0, "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"base_apr_pct": 4.0, "reward_apr_pct": 2.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "AVOID", "DEPLOY", "DEPLOY_CAUTIOUSLY", "DISCOUNT_THE_APR",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "MOSTLY_LIQUID", "MODERATE_LOCK", "HEAVY_LOCK",
            "FULLY_LOCKED", "INSUFFICIENT_DATA",
        })

    def test_pv_factor_is_float(self):
        self.assertIsInstance(self.r["pv_factor"], float)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_base_apr_negative_clamped(self):
        r = A().analyze(make_pos(base_apr_pct=-5.0, reward_apr_pct=6.0))
        self.assertAlmostEqual(r["base_apr_pct"], 0.0)

    def test_reward_apr_negative_clamped(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=-3.0))
        self.assertAlmostEqual(r["reward_apr_pct"], 0.0)

    def test_lock_days_negative_clamped(self):
        r = A().analyze(make_pos(lock_days=-10.0))
        self.assertAlmostEqual(r["lock_days"], 0.0)

    def test_discount_rate_negative_clamped(self):
        r = A().analyze(make_pos(discount_rate_pct=-5.0))
        self.assertAlmostEqual(r["discount_rate_pct"], 0.0)

    def test_penalty_clamped_high(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=200.0))
        self.assertAlmostEqual(r["early_unlock_penalty_pct"], 100.0)

    def test_penalty_clamped_low(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=-5.0))
        self.assertAlmostEqual(r["early_unlock_penalty_pct"], 0.0)

    def test_vested_clamped_high(self):
        r = A().analyze(make_pos(already_vested_pct=200.0))
        self.assertAlmostEqual(r["already_vested_pct"], 100.0)

    def test_vested_clamped_low(self):
        r = A().analyze(make_pos(already_vested_pct=-5.0))
        self.assertAlmostEqual(r["already_vested_pct"], 0.0)

    def test_discount_default_when_missing(self):
        r = A().analyze({"vault": "X", "base_apr_pct": 4.0,
                         "reward_apr_pct": 6.0, "lock_days": 180.0})
        self.assertAlmostEqual(r["discount_rate_pct"], 30.0)

    def test_headline_apr_sum(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 10.0)

    def test_vested_reward_apr(self):
        r = A().analyze(make_pos(reward_apr_pct=10.0, already_vested_pct=40.0))
        self.assertAlmostEqual(r["vested_reward_apr_pct"], 4.0)

    def test_locked_reward_apr(self):
        r = A().analyze(make_pos(reward_apr_pct=10.0, already_vested_pct=40.0))
        self.assertAlmostEqual(r["locked_reward_apr_pct"], 6.0)

    def test_pv_factor_one_when_no_lock(self):
        r = A().analyze(make_pos(lock_days=0.0))
        self.assertAlmostEqual(r["pv_factor"], 1.0)

    def test_pv_factor_one_year(self):
        # 1 year at 30% → 1/1.3
        r = A().analyze(make_pos(lock_days=365.0, discount_rate_pct=30.0))
        self.assertAlmostEqual(r["pv_factor"], 1.0 / 1.3, places=5)

    def test_pv_factor_between_zero_and_one(self):
        r = A().analyze(make_pos(lock_days=365.0, discount_rate_pct=30.0))
        self.assertGreater(r["pv_factor"], 0.0)
        self.assertLessEqual(r["pv_factor"], 1.0)

    def test_pv_factor_zero_discount(self):
        # discount 0 → pv factor 1 regardless of lock
        r = A().analyze(make_pos(lock_days=365.0, discount_rate_pct=0.0))
        self.assertAlmostEqual(r["pv_factor"], 1.0)

    def test_discounted_reward_no_lock_equals_reward(self):
        # lock 0 → pv 1 → discounted reward equals reward apr
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 lock_days=0.0, already_vested_pct=0.0))
        self.assertAlmostEqual(r["discounted_reward_apr_pct"], 6.0)

    def test_liquid_equivalent_no_lock(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 lock_days=0.0))
        self.assertAlmostEqual(r["liquid_equivalent_apr_pct"], 10.0)

    def test_liquid_equivalent_below_headline_with_lock(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 lock_days=365.0, discount_rate_pct=30.0,
                                 already_vested_pct=0.0))
        self.assertLess(r["liquid_equivalent_apr_pct"], r["headline_apr_pct"])

    def test_apr_haircut_zero_no_lock(self):
        r = A().analyze(make_pos(lock_days=0.0))
        self.assertAlmostEqual(r["apr_haircut_pct"], 0.0)

    def test_apr_haircut_positive_with_lock(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 lock_days=365.0, already_vested_pct=0.0))
        self.assertGreater(r["apr_haircut_pct"], 0.0)

    def test_apr_haircut_explicit(self):
        # base 0, reward 10, lock 365, disc 30, vested 0:
        # discounted = 10/1.3 = 7.6923; haircut = 10 - 7.6923 = 2.3077
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=10.0,
                                 lock_days=365.0, discount_rate_pct=30.0,
                                 already_vested_pct=0.0))
        self.assertAlmostEqual(r["apr_haircut_pct"], 10.0 - 10.0 / 1.3,
                               places=3)

    def test_haircut_share_explicit(self):
        # haircut share = haircut/headline*100
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=10.0,
                                 lock_days=365.0, discount_rate_pct=30.0,
                                 already_vested_pct=0.0))
        expected = (10.0 - 10.0 / 1.3) / 10.0 * 100.0
        self.assertAlmostEqual(r["haircut_share_pct"], expected, places=2)

    def test_liquid_yield_apr_base_plus_vested(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=10.0,
                                 already_vested_pct=50.0))
        self.assertAlmostEqual(r["liquid_yield_apr_pct"], 4.0 + 5.0)

    def test_liquid_yield_share(self):
        r = A().analyze(make_pos(base_apr_pct=5.0, reward_apr_pct=5.0,
                                 already_vested_pct=0.0))
        # liquid yield = 5, headline = 10 → 50%
        self.assertAlmostEqual(r["liquid_yield_share_pct"], 50.0)

    def test_locked_share_complement(self):
        r = A().analyze(make_pos(base_apr_pct=5.0, reward_apr_pct=5.0,
                                 already_vested_pct=0.0))
        self.assertAlmostEqual(r["locked_share_pct"], 50.0)

    def test_locked_share_zero_all_base(self):
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.0001,
                                 already_vested_pct=0.0))
        self.assertLess(r["locked_share_pct"], 1.0)

    def test_locked_share_full_vested_zero(self):
        # everything vested → locked share 0
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=10.0,
                                 already_vested_pct=100.0))
        self.assertAlmostEqual(r["locked_share_pct"], 0.0)

    def test_penalty_cost_apr(self):
        # locked reward 10 (vested 0), penalty 50% → 5
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=10.0,
                                 already_vested_pct=0.0,
                                 early_unlock_penalty_pct=50.0))
        self.assertAlmostEqual(r["penalty_cost_apr_pct"], 5.0)

    def test_penalty_cost_zero_no_penalty(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=0.0))
        self.assertAlmostEqual(r["penalty_cost_apr_pct"], 0.0)

    def test_full_vested_no_haircut(self):
        # fully vested reward → no locked portion → no haircut
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 lock_days=365.0, already_vested_pct=100.0))
        self.assertAlmostEqual(r["apr_haircut_pct"], 0.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("base_apr_pct", "headline_apr_pct", "apr_haircut_pct",
                  "liquid_equivalent_apr_pct", "locked_share_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_mostly_liquid(self):
        # locked share <= 10
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.5,
                                 already_vested_pct=0.0))
        self.assertEqual(r["classification"], "MOSTLY_LIQUID")

    def test_mostly_liquid_full_vested(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0,
                                 already_vested_pct=100.0))
        self.assertEqual(r["classification"], "MOSTLY_LIQUID")

    def test_moderate_lock(self):
        # locked share in (10, 35]
        r = A().analyze(make_pos(base_apr_pct=8.0, reward_apr_pct=2.0,
                                 already_vested_pct=0.0))
        # liquid yield 8, headline 10 → locked 20 → MODERATE
        self.assertEqual(r["classification"], "MODERATE_LOCK")

    def test_heavy_lock(self):
        # locked share in (35, 70]
        r = A().analyze(make_pos(base_apr_pct=5.0, reward_apr_pct=5.0,
                                 already_vested_pct=0.0))
        # locked 50 → HEAVY
        self.assertEqual(r["classification"], "HEAVY_LOCK")

    def test_fully_locked(self):
        # locked share > 70
        r = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=9.0,
                                 already_vested_pct=0.0))
        # locked 90 → FULLY_LOCKED
        self.assertEqual(r["classification"], "FULLY_LOCKED")

    def test_mostly_liquid_boundary(self):
        # exactly 10% locked → MOSTLY_LIQUID (<=)
        r = A().analyze(make_pos(base_apr_pct=9.0, reward_apr_pct=1.0,
                                 already_vested_pct=0.0))
        self.assertAlmostEqual(r["locked_share_pct"], 10.0)
        self.assertEqual(r["classification"], "MOSTLY_LIQUID")

    def test_moderate_boundary(self):
        # exactly 35% locked → MODERATE_LOCK (<=)
        r = A().analyze(make_pos(base_apr_pct=6.5, reward_apr_pct=3.5,
                                 already_vested_pct=0.0))
        self.assertAlmostEqual(r["locked_share_pct"], 35.0)
        self.assertEqual(r["classification"], "MODERATE_LOCK")

    def test_heavy_boundary(self):
        # exactly 70% locked → HEAVY_LOCK (<=)
        r = A().analyze(make_pos(base_apr_pct=3.0, reward_apr_pct=7.0,
                                 already_vested_pct=0.0))
        self.assertAlmostEqual(r["locked_share_pct"], 70.0)
        self.assertEqual(r["classification"], "HEAVY_LOCK")

    def test_classification_known_value(self):
        for pos in [make_pos(),
                    make_pos(base_apr_pct=10.0, reward_apr_pct=0.1),
                    make_pos(base_apr_pct=1.0, reward_apr_pct=9.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "MOSTLY_LIQUID", "MODERATE_LOCK", "HEAVY_LOCK",
                "FULLY_LOCKED", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_mostly_liquid(self):
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.5,
                                 already_vested_pct=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_cautiously_when_moderate(self):
        r = A().analyze(make_pos(base_apr_pct=8.0, reward_apr_pct=2.0,
                                 already_vested_pct=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_discount_the_apr_when_heavy(self):
        r = A().analyze(make_pos(base_apr_pct=5.0, reward_apr_pct=5.0,
                                 already_vested_pct=0.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_THE_APR")

    def test_avoid_when_fully_locked(self):
        r = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=9.0,
                                 already_vested_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_mostly_liquid_yield_flag(self):
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.5,
                                 already_vested_pct=0.0))
        self.assertIn("MOSTLY_LIQUID_YIELD", r["flags"])

    def test_mostly_liquid_yield_flag_absent(self):
        r = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=9.0,
                                 already_vested_pct=0.0))
        self.assertNotIn("MOSTLY_LIQUID_YIELD", r["flags"])

    def test_significant_haircut_flag(self):
        # large locked reward + long lock → big haircut share
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=20.0,
                                 lock_days=730.0, discount_rate_pct=50.0,
                                 already_vested_pct=0.0))
        self.assertIn("SIGNIFICANT_LOCK_HAIRCUT", r["flags"])

    def test_significant_haircut_flag_absent_no_lock(self):
        r = A().analyze(make_pos(lock_days=0.0))
        self.assertNotIn("SIGNIFICANT_LOCK_HAIRCUT", r["flags"])

    def test_long_lock_flag(self):
        r = A().analyze(make_pos(lock_days=365.0))
        self.assertIn("LONG_LOCK", r["flags"])

    def test_long_lock_flag_boundary(self):
        r = A().analyze(make_pos(lock_days=LONG_LOCK_DAYS))
        self.assertIn("LONG_LOCK", r["flags"])

    def test_long_lock_flag_absent(self):
        r = A().analyze(make_pos(lock_days=30.0))
        self.assertNotIn("LONG_LOCK", r["flags"])

    def test_early_unlock_penalty_flag(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=10.0))
        self.assertIn("EARLY_UNLOCK_PENALTY", r["flags"])

    def test_early_unlock_penalty_flag_absent(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=0.0))
        self.assertNotIn("EARLY_UNLOCK_PENALTY", r["flags"])

    def test_high_unlock_penalty_flag(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=60.0))
        self.assertIn("HIGH_UNLOCK_PENALTY", r["flags"])

    def test_high_unlock_penalty_flag_boundary(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=HIGH_PENALTY_PCT))
        self.assertIn("HIGH_UNLOCK_PENALTY", r["flags"])

    def test_high_unlock_penalty_flag_absent(self):
        r = A().analyze(make_pos(early_unlock_penalty_pct=20.0))
        self.assertNotIn("HIGH_UNLOCK_PENALTY", r["flags"])

    def test_no_liquid_yield_flag(self):
        # base 0, reward all locked → liquid yield 0
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=10.0,
                                 already_vested_pct=0.0))
        self.assertIn("NO_LIQUID_YIELD", r["flags"])

    def test_no_liquid_yield_flag_absent(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=6.0))
        self.assertNotIn("NO_LIQUID_YIELD", r["flags"])

    def test_partially_vested_flag(self):
        r = A().analyze(make_pos(already_vested_pct=50.0))
        self.assertIn("PARTIALLY_VESTED", r["flags"])

    def test_partially_vested_flag_absent_zero(self):
        r = A().analyze(make_pos(already_vested_pct=0.0))
        self.assertNotIn("PARTIALLY_VESTED", r["flags"])

    def test_partially_vested_flag_absent_full(self):
        r = A().analyze(make_pos(already_vested_pct=100.0))
        self.assertNotIn("PARTIALLY_VESTED", r["flags"])

    def test_fully_vested_flag(self):
        r = A().analyze(make_pos(already_vested_pct=100.0))
        self.assertIn("FULLY_VESTED", r["flags"])

    def test_fully_vested_flag_absent(self):
        r = A().analyze(make_pos(already_vested_pct=50.0))
        self.assertNotIn("FULLY_VESTED", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_flags_order(self):
        # mostly-liquid yield + early penalty + high penalty + fully vested
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.5,
                                 lock_days=365.0,
                                 early_unlock_penalty_pct=60.0,
                                 already_vested_pct=100.0))
        flags = r["flags"]
        # MOSTLY_LIQUID_YIELD comes before EARLY_UNLOCK_PENALTY
        self.assertLess(flags.index("MOSTLY_LIQUID_YIELD"),
                        flags.index("EARLY_UNLOCK_PENALTY"))
        # EARLY before HIGH unlock penalty
        self.assertLess(flags.index("EARLY_UNLOCK_PENALTY"),
                        flags.index("HIGH_UNLOCK_PENALTY"))


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_yield(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_avoid(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_base_is_sufficient(self):
        r = A().analyze(make_pos(base_apr_pct=4.0, reward_apr_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_reward_is_sufficient(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=6.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_aprs_treated_as_zero(self):
        r = A().analyze(make_pos(base_apr_pct=-4.0, reward_apr_pct=-6.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "pv_factor", "apr_haircut_pct",
                  "locked_share_pct", "score", "penalty_cost_apr_pct"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_at_false_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_vested_scores_higher(self):
        low = A().analyze(make_pos(already_vested_pct=0.0))
        high = A().analyze(make_pos(already_vested_pct=100.0))
        self.assertGreater(high["score"], low["score"])

    def test_shorter_lock_scores_higher(self):
        short = A().analyze(make_pos(lock_days=30.0))
        long = A().analyze(make_pos(lock_days=365.0))
        self.assertGreater(short["score"], long["score"])

    def test_lower_penalty_scores_higher(self):
        low = A().analyze(make_pos(early_unlock_penalty_pct=0.0))
        high = A().analyze(make_pos(early_unlock_penalty_pct=80.0))
        self.assertGreater(low["score"], high["score"])

    def test_more_liquid_scores_higher(self):
        liquid = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.5,
                                      already_vested_pct=0.0))
        locked = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=9.0,
                                      lock_days=365.0, already_vested_pct=0.0))
        self.assertGreater(liquid["score"], locked["score"])

    def test_mostly_liquid_scores_high(self):
        r = A().analyze(make_pos(base_apr_pct=10.0, reward_apr_pct=0.0001,
                                 lock_days=0.0, early_unlock_penalty_pct=0.0,
                                 already_vested_pct=100.0))
        self.assertGreater(r["score"], 85.0)

    def test_fully_locked_scores_low(self):
        r = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=19.0,
                                 lock_days=365.0, discount_rate_pct=50.0,
                                 early_unlock_penalty_pct=80.0,
                                 already_vested_pct=0.0))
        self.assertLess(r["score"], 55.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(base_apr_pct=1e6, reward_apr_pct=1e6,
                                 lock_days=1e6, discount_rate_pct=1e6,
                                 early_unlock_penalty_pct=200.0,
                                 already_vested_pct=200.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(base_apr_pct=0.0, reward_apr_pct=20.0,
                                 lock_days=3650.0, discount_rate_pct=100.0,
                                 early_unlock_penalty_pct=100.0,
                                 already_vested_pct=0.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(),
                    make_pos(already_vested_pct=100.0),
                    make_pos(lock_days=0.0),
                    make_pos(early_unlock_penalty_pct=100.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Liquid", base_apr_pct=10.0, reward_apr_pct=0.5,
                     lock_days=0.0, already_vested_pct=100.0),
            make_pos(vault="Locked", base_apr_pct=1.0, reward_apr_pct=19.0,
                     lock_days=365.0, early_unlock_penalty_pct=50.0,
                     already_vested_pct=0.0),
            make_pos(vault="Mid", base_apr_pct=6.0, reward_apr_pct=4.0,
                     lock_days=180.0, already_vested_pct=0.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_liquid_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_liquid_vault"]],
                         max(scores.values()))

    def test_least_liquid_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_liquid_vault"]],
                         min(scores.values()))

    def test_most_liquid_is_liquid(self):
        self.assertEqual(self.res["aggregate"]["most_liquid_vault"], "Liquid")

    def test_least_liquid_is_locked(self):
        self.assertEqual(self.res["aggregate"]["least_liquid_vault"], "Locked")

    def test_heavy_lock_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["heavy_lock_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_liquid_vault"])
        self.assertIsNone(res["aggregate"]["least_liquid_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(base_apr_pct=0.0, reward_apr_pct=0.0),
            make_pos(base_apr_pct=0.0, reward_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_liquid_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["heavy_lock_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_liquid_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_liquid_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_heavy_lock_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="H", base_apr_pct=1.0, reward_apr_pct=9.0,
                     lock_days=365.0, already_vested_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["heavy_lock_count"], 1)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", base_apr_pct=10.0, reward_apr_pct=0.1,
                     lock_days=0.0, already_vested_pct=100.0),
            make_pos(vault="Ins", base_apr_pct=0.0, reward_apr_pct=0.0),
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
                make_pos(vault="big", base_apr_pct=1e9, reward_apr_pct=1e9,
                         lock_days=1e6, discount_rate_pct=1e6),
                make_pos(vault="ins", base_apr_pct=0.0, reward_apr_pct=0.0),
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
            "base_apr_pct": "4",
            "reward_apr_pct": "6",
            "lock_days": "180",
            "discount_rate_pct": "30",
            "early_unlock_penalty_pct": "10",
            "already_vested_pct": "20",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "base_apr_pct": 4.0,
                         "reward_apr_pct": 6.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(base_apr_pct=0.0, reward_apr_pct=0.0),
            make_pos(already_vested_pct=100.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(already_vested_pct=100.0),
                    make_pos(lock_days=0.0),
                    make_pos(base_apr_pct=0.0, reward_apr_pct=0.0),
                    make_pos(base_apr_pct=1e9, reward_apr_pct=1e9),
                    make_pos(discount_rate_pct=0.0),
                    make_pos(discount_rate_pct=1e6, lock_days=1e6),
                    make_pos(early_unlock_penalty_pct=200.0),
                    make_pos(already_vested_pct=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_lock_days_no_crash(self):
        r = A().analyze(make_pos(lock_days=0.0))
        self.assertAlmostEqual(r["pv_factor"], 1.0)
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(base_apr_pct=1e12, reward_apr_pct=1e12,
                                 lock_days=1e9, discount_rate_pct=1e9,
                                 early_unlock_penalty_pct=100.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_huge_discount_no_inf(self):
        # very large discount over long lock → pv_factor near 0, not nan/inf
        r = A().analyze(make_pos(base_apr_pct=1.0, reward_apr_pct=10.0,
                                 lock_days=3650.0, discount_rate_pct=1e6))
        finite_check(self, r)
        self.assertGreaterEqual(r["pv_factor"], 0.0)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(base_apr_pct=-10.0, reward_apr_pct=6.0,
                                 lock_days=-5.0, discount_rate_pct=-5.0,
                                 early_unlock_penalty_pct=-5.0,
                                 already_vested_pct=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_pv_factor_never_above_one(self):
        for ld in (0.0, 30.0, 180.0, 365.0, 1000.0):
            r = A().analyze(make_pos(lock_days=ld, discount_rate_pct=30.0))
            self.assertLessEqual(r["pv_factor"], 1.0 + 1e-9)


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

    def test_demo_includes_mostly_liquid(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("MOSTLY_LIQUID", classes)

    def test_demo_includes_heavy_or_fully_locked(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "HEAVY_LOCK" in classes or "FULLY_LOCKED" in classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
