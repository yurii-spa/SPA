"""
tests/test_evidence_auto_calculator.py

MP-1409 (v10.25): 45 unit tests for EvidenceAutoCalculator and EvidenceDay.

Coverage:
  - EvidenceDay dataclass fields and defaults (4 tests)
  - EvidenceDay.to_dict() / from_dict() round-trip (3 tests)
  - EvidenceAutoCalculator construction (2 tests)
  - record_day() basic recording (5 tests)
  - record_day() deduplication by date (3 tests)
  - calculate_score() with zero days (2 tests)
  - calculate_score() Daily Cycles points (4 tests)
  - calculate_score() APY Tracking points (4 tests)
  - calculate_score() Risk Policy points (4 tests)
  - calculate_score() APY streak bonus (4 tests)
  - calculate_score() Risk streak bonus (4 tests)
  - calculate_score() is_eligible (3 tests)
  - days_to_target() (4 tests)
  - save() / load() round-trip (4 tests)
  - to_markdown() (3 tests)

Run:
    python3 -m pytest tests/test_evidence_auto_calculator.py -v
    python3 -m unittest tests/test_evidence_auto_calculator.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.evidence_auto_calculator import (
    APY_STREAK_BONUS,
    APY_STREAK_THRESHOLD,
    MAX_APY_PTS,
    MAX_CYCLE_PTS,
    MAX_RISK_PTS,
    RISK_STREAK_BONUS,
    RISK_STREAK_THRESHOLD,
    TARGET_PTS,
    EvidenceAutoCalculator,
    EvidenceDay,
    EvidenceScore,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _calc(tmp_dir: str) -> EvidenceAutoCalculator:
    """Return a fresh calculator pointing at a temp directory."""
    return EvidenceAutoCalculator(base_dir=tmp_dir)


def _add_days(calc: EvidenceAutoCalculator, n: int,
              cycle: bool = True, apy: bool = True, risk: bool = True,
              start: int = 1) -> None:
    """Add n identical days starting from 2026-01-{start:02d}."""
    for i in range(n):
        day = start + i
        calc.record_day(
            date=f"2026-01-{day:02d}",
            cycle_completed=cycle,
            apy_verified=apy,
            risk_policy_passed=risk,
        )


# ─── Group 1: EvidenceDay dataclass fields and defaults (4 tests) ─────────────

class TestEvidenceDayDefaults(unittest.TestCase):

    def test_date_field(self):
        d = EvidenceDay(date="2026-06-01")
        self.assertEqual(d.date, "2026-06-01")

    def test_cycle_default_false(self):
        d = EvidenceDay(date="2026-06-01")
        self.assertFalse(d.cycle_completed)

    def test_apy_default_false(self):
        d = EvidenceDay(date="2026-06-01")
        self.assertFalse(d.apy_verified)

    def test_risk_default_false(self):
        d = EvidenceDay(date="2026-06-01")
        self.assertFalse(d.risk_policy_passed)


# ─── Group 2: EvidenceDay to_dict / from_dict (3 tests) ──────────────────────

class TestEvidenceDaySerialization(unittest.TestCase):

    def setUp(self):
        self.day = EvidenceDay(
            date="2026-06-10",
            cycle_completed=True,
            apy_verified=True,
            risk_policy_passed=False,
            notes="test note",
        )

    def test_to_dict_has_all_keys(self):
        d = self.day.to_dict()
        for key in ("date", "cycle_completed", "apy_verified", "risk_policy_passed", "notes"):
            self.assertIn(key, d)

    def test_from_dict_round_trip(self):
        restored = EvidenceDay.from_dict(self.day.to_dict())
        self.assertEqual(restored.date, self.day.date)
        self.assertEqual(restored.cycle_completed, self.day.cycle_completed)
        self.assertEqual(restored.apy_verified, self.day.apy_verified)
        self.assertEqual(restored.risk_policy_passed, self.day.risk_policy_passed)
        self.assertEqual(restored.notes, self.day.notes)

    def test_from_dict_missing_keys_use_defaults(self):
        restored = EvidenceDay.from_dict({"date": "2026-01-01"})
        self.assertFalse(restored.cycle_completed)
        self.assertFalse(restored.apy_verified)
        self.assertFalse(restored.risk_policy_passed)


# ─── Group 3: EvidenceAutoCalculator construction (2 tests) ──────────────────

class TestCalculatorConstruction(unittest.TestCase):

    def test_instantiates_with_default(self):
        calc = EvidenceAutoCalculator()
        self.assertIsNotNone(calc)

    def test_instantiates_with_custom_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            calc = EvidenceAutoCalculator(base_dir=tmp)
            self.assertIn(tmp, str(calc._data_file))


# ─── Group 4: record_day() basic recording (5 tests) ─────────────────────────

class TestRecordDay(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_returns_evidence_day(self):
        result = self.calc.record_day("2026-01-01", True, True, True)
        self.assertIsInstance(result, EvidenceDay)

    def test_history_grows(self):
        self.calc.record_day("2026-01-01", True, True, True)
        self.assertEqual(len(self.calc._history), 1)

    def test_two_different_days(self):
        self.calc.record_day("2026-01-01", True, True, True)
        self.calc.record_day("2026-01-02", True, True, True)
        self.assertEqual(len(self.calc._history), 2)

    def test_notes_stored(self):
        d = self.calc.record_day("2026-01-01", True, True, True, notes="hello")
        self.assertEqual(d.notes, "hello")

    def test_history_sorted_by_date(self):
        self.calc.record_day("2026-01-03", True, True, True)
        self.calc.record_day("2026-01-01", True, True, True)
        self.calc.record_day("2026-01-02", True, True, True)
        dates = [d.date for d in self.calc._history]
        self.assertEqual(dates, sorted(dates))


# ─── Group 5: record_day() deduplication (3 tests) ───────────────────────────

class TestRecordDayDedup(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_duplicate_date_does_not_grow_history(self):
        self.calc.record_day("2026-01-01", True, True, True)
        self.calc.record_day("2026-01-01", False, False, False)
        self.assertEqual(len(self.calc._history), 1)

    def test_duplicate_date_updates_values(self):
        self.calc.record_day("2026-01-01", True, True, True)
        self.calc.record_day("2026-01-01", False, False, False)
        d = self.calc._history[0]
        self.assertFalse(d.cycle_completed)
        self.assertFalse(d.apy_verified)
        self.assertFalse(d.risk_policy_passed)

    def test_duplicate_date_updates_notes(self):
        self.calc.record_day("2026-01-01", True, True, True, notes="first")
        self.calc.record_day("2026-01-01", True, True, True, notes="second")
        self.assertEqual(self.calc._history[0].notes, "second")


# ─── Group 6: calculate_score() with zero days (2 tests) ─────────────────────

class TestScoreZeroDays(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_total_zero_with_no_days(self):
        score = self.calc.calculate_score()
        self.assertEqual(score.total, 0)

    def test_not_eligible_with_no_days(self):
        score = self.calc.calculate_score()
        self.assertFalse(score.is_eligible)


# ─── Group 7: calculate_score() Daily Cycles pts (4 tests) ───────────────────

class TestCyclePts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_one_cycle_gives_one_pt(self):
        _add_days(self.calc, 1)
        score = self.calc.calculate_score()
        self.assertEqual(score.daily_cycles_pts, 1)

    def test_fifteen_cycles_gives_fifteen_pts(self):
        _add_days(self.calc, 15)
        score = self.calc.calculate_score()
        self.assertEqual(score.daily_cycles_pts, MAX_CYCLE_PTS)

    def test_twenty_cycles_capped_at_fifteen(self):
        _add_days(self.calc, 20)
        score = self.calc.calculate_score()
        self.assertEqual(score.daily_cycles_pts, MAX_CYCLE_PTS)

    def test_failed_cycle_gives_zero_pts(self):
        _add_days(self.calc, 3, cycle=False)
        score = self.calc.calculate_score()
        self.assertEqual(score.daily_cycles_pts, 0)


# ─── Group 8: calculate_score() APY Tracking pts (4 tests) ───────────────────

class TestApyPts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_one_apy_day_gives_one_pt(self):
        _add_days(self.calc, 1, apy=True)
        score = self.calc.calculate_score()
        self.assertGreaterEqual(score.apy_tracking_pts, 1)

    def test_eight_apy_days_gives_eight_pts(self):
        _add_days(self.calc, 8, apy=True)
        score = self.calc.calculate_score()
        self.assertEqual(score.apy_tracking_pts, MAX_APY_PTS)

    def test_more_than_eight_capped(self):
        _add_days(self.calc, 12, apy=True)
        score = self.calc.calculate_score()
        self.assertEqual(score.apy_tracking_pts, MAX_APY_PTS)

    def test_no_apy_days_zero_pts(self):
        _add_days(self.calc, 5, apy=False)
        score = self.calc.calculate_score()
        self.assertEqual(score.apy_tracking_pts, 0)


# ─── Group 9: calculate_score() Risk Policy pts (4 tests) ────────────────────

class TestRiskPts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_one_risk_day_gives_one_pt(self):
        _add_days(self.calc, 1, risk=True)
        score = self.calc.calculate_score()
        self.assertGreaterEqual(score.risk_policy_pts, 1)

    def test_seven_risk_days_gives_seven_pts(self):
        _add_days(self.calc, 7, risk=True)
        score = self.calc.calculate_score()
        self.assertEqual(score.risk_policy_pts, MAX_RISK_PTS)

    def test_more_than_seven_capped(self):
        _add_days(self.calc, 10, risk=True)
        score = self.calc.calculate_score()
        self.assertEqual(score.risk_policy_pts, MAX_RISK_PTS)

    def test_no_risk_days_zero_pts(self):
        _add_days(self.calc, 5, risk=False)
        score = self.calc.calculate_score()
        self.assertEqual(score.risk_policy_pts, 0)


# ─── Group 10: APY streak bonus (4 tests) ────────────────────────────────────

class TestApyStreakBonus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_six_day_streak_no_bonus(self):
        _add_days(self.calc, 6, apy=True)
        score = self.calc.calculate_score()
        self.assertEqual(score.bonus_pts, 0)

    def test_seven_day_streak_gives_bonus(self):
        _add_days(self.calc, APY_STREAK_THRESHOLD, apy=True)
        score = self.calc.calculate_score()
        self.assertGreaterEqual(score.bonus_pts, APY_STREAK_BONUS)

    def test_bonus_breaks_after_non_apy_day(self):
        # 7 verified, then 1 unverified → streak resets
        _add_days(self.calc, 7, apy=True, start=1)
        self.calc.record_day("2026-01-08", True, False, True)  # apy_verified=False
        score = self.calc.calculate_score()
        self.assertEqual(score.bonus_pts, 0)

    def test_apy_streak_method_counts_correctly(self):
        _add_days(self.calc, 5, apy=True, start=1)
        streak = self.calc._apy_streak()
        self.assertEqual(streak, 5)


# ─── Group 11: Risk streak bonus (4 tests) ───────────────────────────────────

class TestRiskStreakBonus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_thirteen_day_streak_no_bonus(self):
        _add_days(self.calc, 13, risk=True)
        score = self.calc.calculate_score()
        # Only apy bonus possible if apy streak ≥ 7, but risk bonus not yet
        self.assertLess(score.bonus_pts, RISK_STREAK_BONUS)

    def test_fourteen_day_streak_gives_bonus(self):
        _add_days(self.calc, RISK_STREAK_THRESHOLD, risk=True, apy=False)
        score = self.calc.calculate_score()
        self.assertGreaterEqual(score.bonus_pts, RISK_STREAK_BONUS)

    def test_risk_streak_breaks_after_fail(self):
        _add_days(self.calc, 14, risk=True, start=1)
        self.calc.record_day("2026-01-15", True, True, False)  # risk_policy_passed=False
        score = self.calc.calculate_score()
        # bonus_pts should not include risk bonus
        # APY streak may give +2, but risk bonus is 0
        self.assertNotIn(RISK_STREAK_BONUS, [score.bonus_pts - APY_STREAK_BONUS,
                                              score.bonus_pts])

    def test_risk_streak_method_counts_correctly(self):
        _add_days(self.calc, 10, risk=True, start=1)
        streak = self.calc._risk_streak()
        self.assertEqual(streak, 10)


# ─── Group 12: is_eligible (3 tests) ─────────────────────────────────────────

class TestIsEligible(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_not_eligible_with_29_pts(self):
        # Max without bonus: 15+8+7=30. We need exactly <30.
        # Add 14 full days (cycle+apy+risk) → 14+8+7=29 (apy capped at 8, risk at 7)
        # Actually: 14 cycle pts + 8 apy pts + 7 risk pts = 29 pts (no bonus)
        _add_days(self.calc, 14, apy=False, risk=False)   # 14 cycle only
        _add_days(self.calc, 8,  cycle=False, risk=False, start=15)  # 8 apy only
        _add_days(self.calc, 7,  cycle=False, apy=False, start=23)   # 7 risk only
        score = self.calc.calculate_score()
        self.assertEqual(score.total, 29)
        self.assertFalse(score.is_eligible)

    def test_eligible_at_thirty_or_more_pts(self):
        # 15 full days → 15 cycle + 8 apy + 7 risk + streak bonuses ≥ 30
        _add_days(self.calc, 15)  # all True → all three categories + bonuses
        score = self.calc.calculate_score()
        self.assertGreaterEqual(score.total, TARGET_PTS)
        self.assertTrue(score.is_eligible)

    def test_is_eligible_true_when_total_ge_target(self):
        # With bonuses total can exceed 30
        _add_days(self.calc, 14, apy=True, risk=True)  # 14 cycle, ≥8 apy, ≥7 risk
        score = self.calc.calculate_score()
        self.assertEqual(score.is_eligible, score.total >= TARGET_PTS)


# ─── Group 13: days_to_target() (4 tests) ────────────────────────────────────

class TestDaysToTarget(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_zero_pts_returns_30(self):
        score = self.calc.calculate_score()
        self.assertEqual(self.calc.days_to_target(score), TARGET_PTS)

    def test_twenty_nine_pts_returns_1(self):
        _add_days(self.calc, 14, apy=False, risk=False)
        _add_days(self.calc, 8,  cycle=False, risk=False, start=15)
        _add_days(self.calc, 7,  cycle=False, apy=False, start=23)
        score = self.calc.calculate_score()
        self.assertEqual(score.total, 29)
        self.assertEqual(self.calc.days_to_target(score), 1)

    def test_already_eligible_returns_0(self):
        _add_days(self.calc, 15)
        score = self.calc.calculate_score()
        self.assertTrue(score.is_eligible)
        self.assertEqual(self.calc.days_to_target(score), 0)

    def test_proportional_pessimistic_estimate(self):
        # 20 pts scored → gap = 10 → estimate = 10
        _add_days(self.calc, 15)    # 15+8+7 = 30? — let's use only cycles (15 pts)
        # Actually add 15 cycle-only days, 5 apy-only days → 15+5+0 = 20
        calc2 = _calc(self.tmp + "_2")
        os.makedirs(calc2._data_file.parent, exist_ok=True)
        _add_days(calc2, 15, apy=False, risk=False)
        _add_days(calc2, 5,  cycle=False, risk=False, start=16)
        score2 = calc2.calculate_score()
        self.assertEqual(score2.total, 20)
        self.assertEqual(calc2.days_to_target(score2), 10)


# ─── Group 14: save() / load() round-trip (4 tests) ─────────────────────────

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_save_creates_file(self):
        _add_days(self.calc, 2)
        self.calc.save()
        self.assertTrue(self.calc._data_file.exists())

    def test_load_after_save_restores_history(self):
        _add_days(self.calc, 3)
        self.calc.save()

        calc2 = _calc(self.tmp)
        calc2.load()
        self.assertEqual(len(calc2._history), 3)

    def test_save_is_valid_json(self):
        _add_days(self.calc, 2)
        self.calc.save()
        with open(self.calc._data_file, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("history", data)
        self.assertEqual(len(data["history"]), 2)

    def test_load_from_missing_file_starts_empty(self):
        calc = _calc(self.tmp + "_missing")
        calc.load()
        self.assertEqual(len(calc._history), 0)


# ─── Group 15: to_markdown() (3 tests) ───────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc = _calc(self.tmp)

    def test_markdown_contains_total_pts(self):
        _add_days(self.calc, 5)
        score = self.calc.calculate_score()
        md = self.calc.to_markdown(score)
        self.assertIn(str(score.total), md)

    def test_markdown_contains_target(self):
        score = self.calc.calculate_score()
        md = self.calc.to_markdown(score)
        self.assertIn(str(TARGET_PTS), md)

    def test_markdown_eligible_label(self):
        _add_days(self.calc, 15)
        score = self.calc.calculate_score()
        md = self.calc.to_markdown(score)
        if score.is_eligible:
            self.assertIn("ELIGIBLE", md)
        else:
            self.assertIn("Not yet", md)


if __name__ == "__main__":
    unittest.main()
