"""
Tests for MP-1173: DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_harvest_cycle_entry_timing_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_harvest_cycle_entry_timing_analyzer import (
    DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    EARLY_PCT,
    MID_PCT,
    LATE_PCT,
    PENDING_CEILING_PCT,
    PENDING_HIGH_PCT,
    NEAR_HARVEST_FRACTION,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    harvest_interval_hours=24.0,
    hours_since_last_harvest=9.0,
    pending_yield_pct=0.4,
    snapshot_gated=False,
):
    return {
        "vault": vault,
        "harvest_interval_hours": harvest_interval_hours,
        "hours_since_last_harvest": hours_since_last_harvest,
        "pending_yield_pct": pending_yield_pct,
        "snapshot_gated": snapshot_gated,
    }


def A():
    return DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer()


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
        self.assertLess(EARLY_PCT, MID_PCT)
        self.assertLess(MID_PCT, LATE_PCT)
        self.assertLess(LATE_PCT, 100.0)
        self.assertGreater(PENDING_CEILING_PCT, 0)
        self.assertGreater(PENDING_HIGH_PCT, 0)
        self.assertGreater(NEAR_HARVEST_FRACTION, 0)
        self.assertLess(NEAR_HARVEST_FRACTION, 1.0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "harvest_interval_hours", "hours_since_last_harvest",
            "pending_yield_pct", "cycle_position_pct", "hours_to_next_harvest",
            "is_overdue", "near_harvest", "just_harvested", "snapshot_gated",
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
        r = A().analyze({"token": "AltKey", "harvest_interval_hours": 24.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "harvest_interval_hours": 24.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"harvest_interval_hours": 24.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "DEPOSIT_NOW", "CONSIDER_WAIT", "WAIT_FOR_HARVEST",
            "DEPOSIT_NOW_FOR_SNAPSHOT", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "OPTIMAL_ENTRY", "GOOD_ENTRY", "LATE_CYCLE", "PRE_HARVEST",
            "INSUFFICIENT_DATA",
        })

    def test_is_overdue_is_bool(self):
        self.assertIsInstance(self.r["is_overdue"], bool)

    def test_near_harvest_is_bool(self):
        self.assertIsInstance(self.r["near_harvest"], bool)

    def test_just_harvested_is_bool(self):
        self.assertIsInstance(self.r["just_harvested"], bool)

    def test_snapshot_gated_is_bool(self):
        self.assertIsInstance(self.r["snapshot_gated"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_interval_passthrough(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["harvest_interval_hours"], 24.0)

    def test_hours_since_negative_clamped(self):
        r = A().analyze(make_pos(hours_since_last_harvest=-5.0))
        self.assertAlmostEqual(r["hours_since_last_harvest"], 0.0)

    def test_pending_negative_clamped(self):
        r = A().analyze(make_pos(pending_yield_pct=-2.0))
        self.assertAlmostEqual(r["pending_yield_pct"], 0.0)

    def test_cycle_position_pct(self):
        # 12 / 24 = 50%
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=12.0))
        self.assertAlmostEqual(r["cycle_position_pct"], 50.0, places=4)

    def test_cycle_position_clamped_at_100(self):
        # overdue: 30 / 24 → clamp to 100
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=30.0))
        self.assertAlmostEqual(r["cycle_position_pct"], 100.0, places=4)

    def test_hours_to_next_harvest(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=9.0))
        self.assertAlmostEqual(r["hours_to_next_harvest"], 15.0, places=4)

    def test_hours_to_next_harvest_floor_zero(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=30.0))
        self.assertAlmostEqual(r["hours_to_next_harvest"], 0.0, places=4)

    def test_is_overdue_true(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=25.0))
        self.assertTrue(r["is_overdue"])

    def test_is_overdue_boundary(self):
        # exactly equal → overdue (>=)
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=24.0))
        self.assertTrue(r["is_overdue"])

    def test_is_overdue_false(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=9.0))
        self.assertFalse(r["is_overdue"])

    def test_near_harvest_true(self):
        # 23/24 → 1h to next, threshold 2.4h
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=23.0))
        self.assertTrue(r["near_harvest"])

    def test_near_harvest_false(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=9.0))
        self.assertFalse(r["near_harvest"])

    def test_just_harvested_true(self):
        # 2/24 = 8.3% <= EARLY 15%
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=2.0))
        self.assertTrue(r["just_harvested"])

    def test_just_harvested_false(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=12.0))
        self.assertFalse(r["just_harvested"])

    def test_just_harvested_boundary(self):
        # exactly 15% → just_harvested (<=)
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=15.0))
        self.assertTrue(r["just_harvested"])

    def test_snapshot_gated_passthrough(self):
        r = A().analyze(make_pos(snapshot_gated=True))
        self.assertTrue(r["snapshot_gated"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.3333,
                                 hours_since_last_harvest=9.1111,
                                 pending_yield_pct=0.4444))
        for k in ("harvest_interval_hours", "hours_since_last_harvest",
                  "pending_yield_pct", "cycle_position_pct",
                  "hours_to_next_harvest"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_optimal_entry(self):
        # 2/24 = 8.3% <= EARLY
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=2.0))
        self.assertEqual(r["classification"], "OPTIMAL_ENTRY")

    def test_good_entry(self):
        # 9/24 = 37.5% (> EARLY, <= MID)
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=9.0))
        self.assertEqual(r["classification"], "GOOD_ENTRY")

    def test_late_cycle(self):
        # 18/24 = 75% (> MID, <= LATE)
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=18.0))
        self.assertEqual(r["classification"], "LATE_CYCLE")

    def test_pre_harvest(self):
        # 23/24 = 95.8% (> LATE)
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=23.0))
        self.assertEqual(r["classification"], "PRE_HARVEST")

    def test_early_boundary(self):
        # exactly 15% → OPTIMAL_ENTRY (<=)
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=15.0))
        self.assertEqual(r["classification"], "OPTIMAL_ENTRY")

    def test_mid_boundary(self):
        # exactly 50% → GOOD_ENTRY (<=)
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=50.0))
        self.assertEqual(r["classification"], "GOOD_ENTRY")

    def test_late_boundary(self):
        # exactly 85% → LATE_CYCLE (<=)
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=85.0))
        self.assertEqual(r["classification"], "LATE_CYCLE")

    def test_above_late_pre_harvest(self):
        # 86% → PRE_HARVEST
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=86.0))
        self.assertEqual(r["classification"], "PRE_HARVEST")

    def test_insufficient_no_interval(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_interval(self):
        r = A().analyze(make_pos(harvest_interval_hours=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(hours_since_last_harvest=2.0),
                    make_pos(hours_since_last_harvest=9.0),
                    make_pos(hours_since_last_harvest=18.0),
                    make_pos(hours_since_last_harvest=23.0),
                    make_pos(harvest_interval_hours=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "OPTIMAL_ENTRY", "GOOD_ENTRY", "LATE_CYCLE", "PRE_HARVEST",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deposit_now_optimal(self):
        r = A().analyze(make_pos(hours_since_last_harvest=2.0))
        self.assertEqual(r["recommendation"], "DEPOSIT_NOW")

    def test_deposit_now_good(self):
        r = A().analyze(make_pos(hours_since_last_harvest=9.0))
        self.assertEqual(r["recommendation"], "DEPOSIT_NOW")

    def test_consider_wait_late(self):
        r = A().analyze(make_pos(hours_since_last_harvest=18.0))
        self.assertEqual(r["recommendation"], "CONSIDER_WAIT")

    def test_wait_for_harvest_pre(self):
        r = A().analyze(make_pos(hours_since_last_harvest=23.0))
        self.assertEqual(r["recommendation"], "WAIT_FOR_HARVEST")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_snapshot_gated_pre_harvest_flips(self):
        # PRE_HARVEST + snapshot_gated → DEPOSIT_NOW_FOR_SNAPSHOT
        r = A().analyze(make_pos(hours_since_last_harvest=23.0,
                                 snapshot_gated=True))
        self.assertEqual(r["recommendation"], "DEPOSIT_NOW_FOR_SNAPSHOT")

    def test_snapshot_gated_near_harvest_flips(self):
        # near_harvest but classification LATE_CYCLE → still flips via near
        r = A().analyze(make_pos(harvest_interval_hours=100.0,
                                 hours_since_last_harvest=92.0,
                                 snapshot_gated=True))
        self.assertEqual(r["recommendation"], "DEPOSIT_NOW_FOR_SNAPSHOT")

    def test_snapshot_gated_early_no_flip(self):
        # snapshot_gated but optimal entry, not near harvest → normal
        r = A().analyze(make_pos(hours_since_last_harvest=2.0,
                                 snapshot_gated=True))
        self.assertEqual(r["recommendation"], "DEPOSIT_NOW")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_optimal_entry_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=2.0))
        self.assertIn("OPTIMAL_ENTRY", r["flags"])

    def test_good_entry_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=9.0))
        self.assertIn("GOOD_ENTRY", r["flags"])

    def test_late_cycle_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=18.0))
        self.assertIn("LATE_CYCLE", r["flags"])

    def test_pre_harvest_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=23.0))
        self.assertIn("PRE_HARVEST", r["flags"])

    def test_just_harvested_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=2.0))
        self.assertIn("JUST_HARVESTED", r["flags"])

    def test_just_harvested_flag_absent(self):
        r = A().analyze(make_pos(hours_since_last_harvest=12.0))
        self.assertNotIn("JUST_HARVESTED", r["flags"])

    def test_near_harvest_flag(self):
        r = A().analyze(make_pos(hours_since_last_harvest=23.0))
        self.assertIn("NEAR_HARVEST", r["flags"])

    def test_near_harvest_flag_absent(self):
        r = A().analyze(make_pos(hours_since_last_harvest=9.0))
        self.assertNotIn("NEAR_HARVEST", r["flags"])

    def test_harvest_overdue_flag(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=30.0))
        self.assertIn("HARVEST_OVERDUE", r["flags"])

    def test_harvest_overdue_flag_absent(self):
        r = A().analyze(make_pos(hours_since_last_harvest=9.0))
        self.assertNotIn("HARVEST_OVERDUE", r["flags"])

    def test_snapshot_gated_flag(self):
        r = A().analyze(make_pos(snapshot_gated=True))
        self.assertIn("SNAPSHOT_GATED", r["flags"])

    def test_snapshot_gated_flag_absent(self):
        r = A().analyze(make_pos(snapshot_gated=False))
        self.assertNotIn("SNAPSHOT_GATED", r["flags"])

    def test_high_pending_stake_flag(self):
        # pending 1.2 >= PENDING_HIGH 1.0
        r = A().analyze(make_pos(pending_yield_pct=1.2))
        self.assertIn("HIGH_PENDING_STAKE", r["flags"])

    def test_high_pending_stake_flag_boundary(self):
        r = A().analyze(make_pos(pending_yield_pct=1.0))
        self.assertIn("HIGH_PENDING_STAKE", r["flags"])

    def test_high_pending_stake_flag_absent(self):
        r = A().analyze(make_pos(pending_yield_pct=0.4))
        self.assertNotIn("HIGH_PENDING_STAKE", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_interval(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("harvest_interval_hours", "hours_since_last_harvest",
                  "pending_yield_pct", "cycle_position_pct",
                  "hours_to_next_harvest", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_overdue"])
        self.assertFalse(r["near_harvest"])
        self.assertFalse(r["just_harvested"])
        self.assertFalse(r["snapshot_gated"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_interval(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_earlier_scores_higher(self):
        early = A().analyze(make_pos(harvest_interval_hours=24.0,
                                     hours_since_last_harvest=2.0,
                                     pending_yield_pct=0.4))
        late = A().analyze(make_pos(harvest_interval_hours=24.0,
                                    hours_since_last_harvest=20.0,
                                    pending_yield_pct=0.4))
        self.assertGreater(early["score"], late["score"])

    def test_less_pending_scores_higher_when_late(self):
        low = A().analyze(make_pos(harvest_interval_hours=24.0,
                                   hours_since_last_harvest=20.0,
                                   pending_yield_pct=0.1))
        high = A().analyze(make_pos(harvest_interval_hours=24.0,
                                    hours_since_last_harvest=20.0,
                                    pending_yield_pct=1.8))
        self.assertGreater(low["score"], high["score"])

    def test_pending_irrelevant_at_start(self):
        # at cycle position 0, pending should not affect score
        low = A().analyze(make_pos(harvest_interval_hours=24.0,
                                   hours_since_last_harvest=0.0,
                                   pending_yield_pct=0.0))
        high = A().analyze(make_pos(harvest_interval_hours=24.0,
                                    hours_since_last_harvest=0.0,
                                    pending_yield_pct=1.8))
        self.assertAlmostEqual(low["score"], high["score"], places=4)

    def test_snapshot_gated_does_not_change_score(self):
        no = A().analyze(make_pos(hours_since_last_harvest=20.0,
                                  pending_yield_pct=1.0, snapshot_gated=False))
        yes = A().analyze(make_pos(hours_since_last_harvest=20.0,
                                   pending_yield_pct=1.0, snapshot_gated=True))
        self.assertAlmostEqual(no["score"], yes["score"], places=4)

    def test_optimal_entry_high_score(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=0.0,
                                 pending_yield_pct=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_pre_harvest_high_pending_low_score(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=24.0,
                                 pending_yield_pct=2.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(harvest_interval_hours=1e9,
                                 hours_since_last_harvest=1e12,
                                 pending_yield_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(harvest_interval_hours=24.0,
                                 hours_since_last_harvest=24.0,
                                 pending_yield_pct=1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(hours_since_last_harvest=2.0),
                    make_pos(hours_since_last_harvest=9.0),
                    make_pos(hours_since_last_harvest=23.0),
                    make_pos(harvest_interval_hours=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(hours_since_last_harvest=0.0),
                    make_pos(hours_since_last_harvest=24.0,
                             pending_yield_pct=2.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Best", harvest_interval_hours=24.0,
                     hours_since_last_harvest=1.0, pending_yield_pct=0.1),
            make_pos(vault="Worst", harvest_interval_hours=24.0,
                     hours_since_last_harvest=23.0, pending_yield_pct=1.8),
            make_pos(vault="Mid", harvest_interval_hours=24.0,
                     hours_since_last_harvest=12.0, pending_yield_pct=0.5),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_best_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["best_entry_vault"]], max(scores.values()))

    def test_worst_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["worst_entry_vault"]], min(scores.values()))

    def test_best_is_best(self):
        self.assertEqual(self.res["aggregate"]["best_entry_vault"], "Best")

    def test_worst_is_worst(self):
        self.assertEqual(self.res["aggregate"]["worst_entry_vault"], "Worst")

    def test_pre_harvest_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["pre_harvest_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["best_entry_vault"])
        self.assertIsNone(res["aggregate"]["worst_entry_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(harvest_interval_hours=0.0),
            make_pos(harvest_interval_hours=0.0),
        ])
        self.assertIsNone(res["aggregate"]["best_entry_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["pre_harvest_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["best_entry_vault"], "Solo")
        self.assertEqual(res["aggregate"]["worst_entry_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", harvest_interval_hours=0.0),
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
                make_pos(vault="big", harvest_interval_hours=1e9,
                         hours_since_last_harvest=1e12,
                         pending_yield_pct=1e9),
                make_pos(vault="ins", harvest_interval_hours=0.0),
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
            "harvest_interval_hours": "24",
            "hours_since_last_harvest": "9",
            "pending_yield_pct": "0.4",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "harvest_interval_hours": 24.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(harvest_interval_hours=0.0),
            make_pos(hours_since_last_harvest=23.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(hours_since_last_harvest=23.0),
                    make_pos(harvest_interval_hours=0.0),
                    make_pos(harvest_interval_hours=1e9,
                             hours_since_last_harvest=1e12,
                             pending_yield_pct=1e9),
                    make_pos(harvest_interval_hours=-1e9,
                             hours_since_last_harvest=-1e9),
                    make_pos(pending_yield_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(harvest_interval_hours=1e12,
                                 hours_since_last_harvest=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(hours_since_last_harvest=-10.0,
                                 pending_yield_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_truthy_snapshot_flag(self):
        r = A().analyze(make_pos(snapshot_gated=1))
        self.assertTrue(r["snapshot_gated"])

    def test_falsy_snapshot_flag(self):
        r = A().analyze(make_pos(snapshot_gated=0))
        self.assertFalse(r["snapshot_gated"])

    def test_zero_hours_since_optimal(self):
        r = A().analyze(make_pos(hours_since_last_harvest=0.0))
        self.assertEqual(r["classification"], "OPTIMAL_ENTRY")


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

    def test_demo_includes_optimal_and_pre_harvest(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("OPTIMAL_ENTRY", classes)
        self.assertIn("PRE_HARVEST", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("OPTIMAL_ENTRY", "GOOD_ENTRY", "LATE_CYCLE", "PRE_HARVEST",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
