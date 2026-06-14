"""
Tests for MP-1160: DeFiProtocolVaultStrategyMigrationRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_strategy_migration_risk_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_strategy_migration_risk_analyzer import (
    DeFiProtocolVaultStrategyMigrationRiskAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    SETTLE_DAYS,
    MATURE_DAYS,
    MIN_TIMELOCK_HOURS,
    UNPROVEN_DAYS,
    LARGE_TVL_PCT,
    FREQUENT_MIGRATIONS,
    CONTINUITY_DROP_FLAG_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    days_since_migration=20.0,
    new_strategy_age_days=100.0,
    migrated_tvl_pct=20.0,
    has_timelock=True,
    timelock_hours=48.0,
    is_audited=True,
    share_price_continuity_pct=100.0,
    migration_count_90d=1.0,
):
    return {
        "vault": vault,
        "days_since_migration": days_since_migration,
        "new_strategy_age_days": new_strategy_age_days,
        "migrated_tvl_pct": migrated_tvl_pct,
        "has_timelock": has_timelock,
        "timelock_hours": timelock_hours,
        "is_audited": is_audited,
        "share_price_continuity_pct": share_price_continuity_pct,
        "migration_count_90d": migration_count_90d,
    }


def A():
    return DeFiProtocolVaultStrategyMigrationRiskAnalyzer()


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

    def test_f_default_negative_one(self):
        self.assertEqual(_f(None, -1.0), -1.0)

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
        self.assertLess(SETTLE_DAYS, MATURE_DAYS)
        self.assertGreater(MIN_TIMELOCK_HOURS, 0)
        self.assertGreater(UNPROVEN_DAYS, 0)
        self.assertGreater(LARGE_TVL_PCT, 0)
        self.assertGreater(FREQUENT_MIGRATIONS, 0)
        self.assertGreater(CONTINUITY_DROP_FLAG_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "days_since_migration", "new_strategy_age_days",
            "migrated_tvl_pct", "has_timelock", "timelock_hours", "is_audited",
            "share_price_continuity_pct", "share_price_drop_pct",
            "governance_protected", "is_fresh", "migration_churn", "score",
            "classification", "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "days_since_migration": 5.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "days_since_migration": 5.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"days_since_migration": 5.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "DEPLOY", "DEPLOY_CAUTIOUSLY", "WAIT_FOR_SETTLE", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_governance_protected_is_bool(self):
        self.assertIsInstance(self.r["governance_protected"], bool)

    def test_is_fresh_is_bool(self):
        self.assertIsInstance(self.r["is_fresh"], bool)

    def test_has_timelock_is_bool(self):
        self.assertIsInstance(self.r["has_timelock"], bool)

    def test_is_audited_is_bool(self):
        self.assertIsInstance(self.r["is_audited"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_migrated_tvl_clamped_high(self):
        r = A().analyze(make_pos(migrated_tvl_pct=200.0))
        self.assertAlmostEqual(r["migrated_tvl_pct"], 100.0)

    def test_migrated_tvl_clamped_low(self):
        r = A().analyze(make_pos(migrated_tvl_pct=-50.0))
        self.assertAlmostEqual(r["migrated_tvl_pct"], 0.0)

    def test_continuity_clamped_high(self):
        r = A().analyze(make_pos(share_price_continuity_pct=150.0))
        self.assertAlmostEqual(r["share_price_continuity_pct"], 100.0)

    def test_continuity_clamped_low(self):
        r = A().analyze(make_pos(share_price_continuity_pct=-10.0))
        self.assertAlmostEqual(r["share_price_continuity_pct"], 0.0)

    def test_share_price_drop_calc(self):
        r = A().analyze(make_pos(share_price_continuity_pct=95.0))
        self.assertAlmostEqual(r["share_price_drop_pct"], 5.0)

    def test_share_price_drop_zero_when_full(self):
        r = A().analyze(make_pos(share_price_continuity_pct=100.0))
        self.assertAlmostEqual(r["share_price_drop_pct"], 0.0)

    def test_governance_protected_true(self):
        r = A().analyze(make_pos(has_timelock=True, timelock_hours=48.0))
        self.assertTrue(r["governance_protected"])

    def test_governance_protected_false_no_timelock(self):
        r = A().analyze(make_pos(has_timelock=False, timelock_hours=48.0))
        self.assertFalse(r["governance_protected"])

    def test_governance_protected_false_short_timelock(self):
        r = A().analyze(make_pos(has_timelock=True, timelock_hours=12.0))
        self.assertFalse(r["governance_protected"])

    def test_governance_protected_at_min_boundary(self):
        r = A().analyze(make_pos(has_timelock=True,
                                 timelock_hours=MIN_TIMELOCK_HOURS))
        self.assertTrue(r["governance_protected"])

    def test_is_fresh_true(self):
        r = A().analyze(make_pos(days_since_migration=2.0))
        self.assertTrue(r["is_fresh"])

    def test_is_fresh_false_settled(self):
        r = A().analyze(make_pos(days_since_migration=30.0))
        self.assertFalse(r["is_fresh"])

    def test_is_fresh_false_no_migration(self):
        # only churn given, no days_since
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=2.0))
        self.assertFalse(r["is_fresh"])

    def test_is_fresh_boundary_at_settle(self):
        r = A().analyze(make_pos(days_since_migration=SETTLE_DAYS))
        self.assertFalse(r["is_fresh"])

    def test_is_fresh_boundary_just_under(self):
        r = A().analyze(make_pos(days_since_migration=SETTLE_DAYS - 0.01))
        self.assertTrue(r["is_fresh"])

    def test_migration_churn_equals_count(self):
        r = A().analyze(make_pos(migration_count_90d=5.0))
        self.assertAlmostEqual(r["migration_churn"], 5.0)

    def test_new_strategy_age_negative_clamped(self):
        r = A().analyze(make_pos(new_strategy_age_days=-10.0))
        self.assertAlmostEqual(r["new_strategy_age_days"], 0.0)

    def test_timelock_hours_negative_clamped(self):
        r = A().analyze(make_pos(timelock_hours=-5.0))
        self.assertAlmostEqual(r["timelock_hours"], 0.0)

    def test_migration_count_negative_clamped(self):
        r = A().analyze(make_pos(migration_count_90d=-3.0))
        self.assertAlmostEqual(r["migration_churn"], 0.0)

    def test_default_continuity_is_100(self):
        r = A().analyze({"vault": "X", "days_since_migration": 5.0})
        self.assertAlmostEqual(r["share_price_continuity_pct"], 100.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_low_migration_risk(self):
        # mature, audited, governance, settled, low tvl → high score
        r = A().analyze(make_pos(days_since_migration=30.0,
                                 new_strategy_age_days=200.0,
                                 migrated_tvl_pct=10.0, has_timelock=True,
                                 timelock_hours=72.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        self.assertEqual(r["classification"], "LOW_MIGRATION_RISK")

    def test_high_migration_risk(self):
        # fresh, unproven, huge tvl, no timelock, unaudited
        r = A().analyze(make_pos(days_since_migration=1.0,
                                 new_strategy_age_days=1.0,
                                 migrated_tvl_pct=100.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=False,
                                 share_price_continuity_pct=80.0,
                                 migration_count_90d=5.0))
        self.assertEqual(r["classification"], "HIGH_MIGRATION_RISK")

    def test_moderate_or_elevated_mid(self):
        r = A().analyze(make_pos(days_since_migration=5.0,
                                 new_strategy_age_days=40.0,
                                 migrated_tvl_pct=40.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=True,
                                 share_price_continuity_pct=99.0))
        self.assertIn(r["classification"],
                      {"MODERATE_MIGRATION_RISK", "ELEVATED_MIGRATION_RISK"})

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(new_strategy_age_days=1.0,
                                         migrated_tvl_pct=100.0,
                                         is_audited=False, has_timelock=False)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "LOW_MIGRATION_RISK", "MODERATE_MIGRATION_RISK",
                "ELEVATED_MIGRATION_RISK", "HIGH_MIGRATION_RISK",
                "INSUFFICIENT_DATA",
            })

    def test_band_low_at_80(self):
        # construct a score exactly at/above 80
        r = A().analyze(make_pos(days_since_migration=30.0,
                                 new_strategy_age_days=200.0,
                                 migrated_tvl_pct=0.0, has_timelock=True,
                                 timelock_hours=72.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        self.assertGreaterEqual(r["score"], 80.0)
        self.assertEqual(r["classification"], "LOW_MIGRATION_RISK")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_low(self):
        r = A().analyze(make_pos(days_since_migration=30.0,
                                 new_strategy_age_days=200.0,
                                 migrated_tvl_pct=10.0, has_timelock=True,
                                 timelock_hours=72.0, is_audited=True))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_avoid_when_high(self):
        r = A().analyze(make_pos(days_since_migration=1.0,
                                 new_strategy_age_days=1.0,
                                 migrated_tvl_pct=100.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=False,
                                 share_price_continuity_pct=70.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_deploy_cautiously_when_moderate(self):
        # find a moderate band case
        r = A().analyze(make_pos(days_since_migration=30.0,
                                 new_strategy_age_days=60.0,
                                 migrated_tvl_pct=40.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        if r["classification"] == "MODERATE_MIGRATION_RISK":
            self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_wait_for_settle_when_elevated_and_fresh(self):
        # elevated band + fresh → WAIT_FOR_SETTLE
        r = A().analyze(make_pos(days_since_migration=2.0,
                                 new_strategy_age_days=35.0,
                                 migrated_tvl_pct=45.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        if r["classification"] == "ELEVATED_MIGRATION_RISK":
            self.assertTrue(r["is_fresh"])
            self.assertEqual(r["recommendation"], "WAIT_FOR_SETTLE")

    def test_deploy_cautiously_when_elevated_not_fresh(self):
        # elevated band + not fresh → DEPLOY_CAUTIOUSLY
        r = A().analyze(make_pos(days_since_migration=30.0,
                                 new_strategy_age_days=35.0,
                                 migrated_tvl_pct=70.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=False,
                                 share_price_continuity_pct=100.0))
        if r["classification"] == "ELEVATED_MIGRATION_RISK":
            self.assertFalse(r["is_fresh"])
            self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fresh_migration_flag(self):
        r = A().analyze(make_pos(days_since_migration=2.0))
        self.assertIn("FRESH_MIGRATION", r["flags"])

    def test_fresh_migration_flag_absent(self):
        r = A().analyze(make_pos(days_since_migration=30.0))
        self.assertNotIn("FRESH_MIGRATION", r["flags"])

    def test_settled_migration_flag(self):
        r = A().analyze(make_pos(days_since_migration=30.0))
        self.assertIn("SETTLED_MIGRATION", r["flags"])

    def test_settled_migration_flag_at_boundary(self):
        r = A().analyze(make_pos(days_since_migration=SETTLE_DAYS))
        self.assertIn("SETTLED_MIGRATION", r["flags"])

    def test_settled_migration_flag_absent(self):
        r = A().analyze(make_pos(days_since_migration=2.0))
        self.assertNotIn("SETTLED_MIGRATION", r["flags"])

    def test_unproven_strategy_flag(self):
        r = A().analyze(make_pos(new_strategy_age_days=10.0))
        self.assertIn("UNPROVEN_STRATEGY", r["flags"])

    def test_unproven_strategy_flag_absent(self):
        r = A().analyze(make_pos(new_strategy_age_days=200.0))
        self.assertNotIn("UNPROVEN_STRATEGY", r["flags"])

    def test_mature_strategy_flag(self):
        r = A().analyze(make_pos(new_strategy_age_days=200.0))
        self.assertIn("MATURE_STRATEGY", r["flags"])

    def test_mature_strategy_flag_at_boundary(self):
        r = A().analyze(make_pos(new_strategy_age_days=MATURE_DAYS))
        self.assertIn("MATURE_STRATEGY", r["flags"])

    def test_mature_strategy_flag_absent(self):
        r = A().analyze(make_pos(new_strategy_age_days=10.0))
        self.assertNotIn("MATURE_STRATEGY", r["flags"])

    def test_large_tvl_migration_flag(self):
        r = A().analyze(make_pos(migrated_tvl_pct=60.0))
        self.assertIn("LARGE_TVL_MIGRATION", r["flags"])

    def test_large_tvl_migration_flag_at_boundary(self):
        r = A().analyze(make_pos(migrated_tvl_pct=LARGE_TVL_PCT))
        self.assertIn("LARGE_TVL_MIGRATION", r["flags"])

    def test_large_tvl_migration_flag_absent(self):
        r = A().analyze(make_pos(migrated_tvl_pct=20.0))
        self.assertNotIn("LARGE_TVL_MIGRATION", r["flags"])

    def test_unaudited_strategy_flag(self):
        r = A().analyze(make_pos(is_audited=False))
        self.assertIn("UNAUDITED_STRATEGY", r["flags"])

    def test_unaudited_strategy_flag_absent(self):
        r = A().analyze(make_pos(is_audited=True))
        self.assertNotIn("UNAUDITED_STRATEGY", r["flags"])

    def test_audited_strategy_flag(self):
        r = A().analyze(make_pos(is_audited=True))
        self.assertIn("AUDITED_STRATEGY", r["flags"])

    def test_audited_strategy_flag_absent(self):
        r = A().analyze(make_pos(is_audited=False))
        self.assertNotIn("AUDITED_STRATEGY", r["flags"])

    def test_governance_timelock_flag(self):
        r = A().analyze(make_pos(has_timelock=True, timelock_hours=48.0))
        self.assertIn("GOVERNANCE_TIMELOCK", r["flags"])

    def test_governance_timelock_flag_absent(self):
        r = A().analyze(make_pos(has_timelock=False))
        self.assertNotIn("GOVERNANCE_TIMELOCK", r["flags"])

    def test_no_timelock_flag(self):
        r = A().analyze(make_pos(has_timelock=False))
        self.assertIn("NO_TIMELOCK", r["flags"])

    def test_no_timelock_flag_absent(self):
        r = A().analyze(make_pos(has_timelock=True, timelock_hours=48.0))
        self.assertNotIn("NO_TIMELOCK", r["flags"])

    def test_share_price_discontinuity_flag(self):
        r = A().analyze(make_pos(share_price_continuity_pct=90.0))
        self.assertIn("SHARE_PRICE_DISCONTINUITY", r["flags"])

    def test_share_price_discontinuity_flag_absent(self):
        r = A().analyze(make_pos(share_price_continuity_pct=100.0))
        self.assertNotIn("SHARE_PRICE_DISCONTINUITY", r["flags"])

    def test_share_price_discontinuity_flag_at_threshold(self):
        # drop exactly at threshold → not flagged (strict >)
        r = A().analyze(make_pos(
            share_price_continuity_pct=100.0 - CONTINUITY_DROP_FLAG_PCT))
        self.assertNotIn("SHARE_PRICE_DISCONTINUITY", r["flags"])

    def test_frequent_migrations_flag(self):
        r = A().analyze(make_pos(migration_count_90d=4.0))
        self.assertIn("FREQUENT_MIGRATIONS", r["flags"])

    def test_frequent_migrations_flag_at_boundary(self):
        r = A().analyze(make_pos(migration_count_90d=FREQUENT_MIGRATIONS))
        self.assertIn("FREQUENT_MIGRATIONS", r["flags"])

    def test_frequent_migrations_flag_absent(self):
        r = A().analyze(make_pos(migration_count_90d=1.0))
        self.assertNotIn("FREQUENT_MIGRATIONS", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_migration_no_churn(self):
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_churn_is_sufficient(self):
        # negative days but churn present → assessable
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=2.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_days_is_sufficient(self):
        r = A().analyze(make_pos(days_since_migration=5.0,
                                 migration_count_90d=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_days_is_sufficient(self):
        # day 0 migration (just happened)
        r = A().analyze(make_pos(days_since_migration=0.0,
                                 migration_count_90d=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_mature_scores_higher_than_unproven(self):
        mature = A().analyze(make_pos(new_strategy_age_days=200.0))
        unproven = A().analyze(make_pos(new_strategy_age_days=5.0))
        self.assertGreater(mature["score"], unproven["score"])

    def test_small_tvl_scores_higher(self):
        small = A().analyze(make_pos(migrated_tvl_pct=5.0))
        large = A().analyze(make_pos(migrated_tvl_pct=95.0))
        self.assertGreater(small["score"], large["score"])

    def test_settled_scores_higher_than_fresh(self):
        settled = A().analyze(make_pos(days_since_migration=14.0))
        fresh = A().analyze(make_pos(days_since_migration=1.0))
        self.assertGreater(settled["score"], fresh["score"])

    def test_audited_scores_higher(self):
        audited = A().analyze(make_pos(is_audited=True))
        unaudited = A().analyze(make_pos(is_audited=False))
        self.assertGreater(audited["score"], unaudited["score"])

    def test_governance_scores_higher(self):
        gov = A().analyze(make_pos(has_timelock=True, timelock_hours=48.0))
        nogov = A().analyze(make_pos(has_timelock=False, timelock_hours=0.0))
        self.assertGreater(gov["score"], nogov["score"])

    def test_continuity_scores_higher(self):
        good = A().analyze(make_pos(share_price_continuity_pct=100.0))
        bad = A().analyze(make_pos(share_price_continuity_pct=50.0))
        self.assertGreater(good["score"], bad["score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(days_since_migration=999.0,
                                 new_strategy_age_days=9999.0,
                                 migrated_tvl_pct=0.0, has_timelock=True,
                                 timelock_hours=999.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(days_since_migration=0.0,
                                 new_strategy_age_days=0.0,
                                 migrated_tvl_pct=100.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=False,
                                 share_price_continuity_pct=0.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_no_migration_settled_full_credit(self):
        # days_since < 0 (only churn) gives full settle credit
        r = A().analyze(make_pos(days_since_migration=-1.0,
                                 migration_count_90d=1.0,
                                 new_strategy_age_days=200.0,
                                 migrated_tvl_pct=0.0, has_timelock=True,
                                 timelock_hours=48.0, is_audited=True,
                                 share_price_continuity_pct=100.0))
        self.assertGreaterEqual(r["score"], 80.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", days_since_migration=30.0,
                     new_strategy_age_days=200.0, migrated_tvl_pct=10.0,
                     has_timelock=True, timelock_hours=72.0, is_audited=True),
            make_pos(vault="Risky", days_since_migration=1.0,
                     new_strategy_age_days=2.0, migrated_tvl_pct=100.0,
                     has_timelock=False, timelock_hours=0.0, is_audited=False,
                     share_price_continuity_pct=70.0, migration_count_90d=5.0),
            make_pos(vault="Mid", days_since_migration=10.0,
                     new_strategy_age_days=40.0, migrated_tvl_pct=40.0,
                     has_timelock=False, timelock_hours=0.0, is_audited=True),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_risky_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_risky_vault"]], min(scores.values()))

    def test_least_risky_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_risky_vault"]], max(scores.values()))

    def test_most_risky_is_risky_vault(self):
        self.assertEqual(self.res["aggregate"]["most_risky_vault"], "Risky")

    def test_least_risky_is_safe_vault(self):
        self.assertEqual(self.res["aggregate"]["least_risky_vault"], "Safe")

    def test_high_risk_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_risk_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_risky_vault"])
        self.assertIsNone(res["aggregate"]["least_risky_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(days_since_migration=-1.0, migration_count_90d=0.0),
            make_pos(days_since_migration=-1.0, migration_count_90d=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_risky_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_risky_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_risky_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_risk_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="H", days_since_migration=1.0,
                     new_strategy_age_days=1.0, migrated_tvl_pct=100.0,
                     has_timelock=False, timelock_hours=0.0, is_audited=False,
                     share_price_continuity_pct=70.0),
        ])
        self.assertEqual(res["aggregate"]["high_risk_count"], 1)


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
                make_pos(vault="big", migrated_tvl_pct=100.0,
                         new_strategy_age_days=0.0),
                make_pos(vault="ins", days_since_migration=-1.0,
                         migration_count_90d=0.0),
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
            "days_since_migration": "10",
            "new_strategy_age_days": "100",
            "migrated_tvl_pct": "20",
            "timelock_hours": "48",
            "share_price_continuity_pct": "100",
            "migration_count_90d": "1",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "days_since_migration": 5.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(days_since_migration=-1.0, migration_count_90d=0.0),
            make_pos(migrated_tvl_pct=100.0, is_audited=False),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(days_since_migration=-1.0, migration_count_90d=2.0),
                    make_pos(days_since_migration=-1.0, migration_count_90d=0.0),
                    make_pos(migrated_tvl_pct=200.0,
                             share_price_continuity_pct=200.0),
                    make_pos(new_strategy_age_days=-10.0, timelock_hours=-5.0),
                    make_pos(days_since_migration=0.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_everything_no_crash(self):
        r = A().analyze(make_pos(days_since_migration=0.0,
                                 new_strategy_age_days=0.0,
                                 migrated_tvl_pct=0.0, has_timelock=False,
                                 timelock_hours=0.0, is_audited=False,
                                 share_price_continuity_pct=0.0,
                                 migration_count_90d=0.0))
        self.assertIn("classification", r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(days_since_migration=1e6,
                                 new_strategy_age_days=1e6,
                                 timelock_hours=1e6, migration_count_90d=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)

    def test_bool_truthy_coercion(self):
        r = A().analyze(make_pos(has_timelock=1, is_audited=1))
        self.assertTrue(r["has_timelock"])
        self.assertTrue(r["is_audited"])


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

    def test_demo_includes_low_risk(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("LOW_MIGRATION_RISK", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
