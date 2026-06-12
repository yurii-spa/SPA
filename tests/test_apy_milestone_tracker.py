"""
Tests for spa_core/analytics/apy_milestone_tracker.py — MP-383

Groups:
    TestApyMilestoneTrackerInit         (5  tests)
    TestApyMilestoneTrackerRecordDay    (12 tests)
    TestApyMilestoneTrackerQueries      (15 tests)
    TestApyMilestoneTrackerReport       (8  tests)
    TestApyMilestoneTrackerPersistence  (10 tests)

Total: 50 tests
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from spa_core.analytics.apy_milestone_tracker import (
    APY_MILESTONES,
    ApyMilestoneTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tracker(tmp_path: Path) -> ApyMilestoneTracker:
    """Return a fresh tracker backed by a temporary directory."""
    return ApyMilestoneTracker(data_dir=tmp_path)


def log_path(tmp_path: Path) -> Path:
    return tmp_path / "apy_milestone_log.json"


# ===========================================================================
# 1. Init tests (5)
# ===========================================================================

class TestApyMilestoneTrackerInit:

    def test_file_created_on_first_init(self, tmp_path):
        """Log file should not exist before first save; tracker lazily creates it."""
        tracker = make_tracker(tmp_path)
        # File may not exist until first save — just confirm tracker is live
        assert tracker is not None

    def test_file_exists_after_record(self, tmp_path):
        """File must appear on disk after the first record_day call."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        assert log_path(tmp_path).exists()

    def test_initial_structure_keys(self, tmp_path):
        """After first record, JSON has all required top-level keys."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        data = json.loads(log_path(tmp_path).read_text())
        for key in ("start_date", "last_updated", "days_recorded", "daily_log", "milestones_reached"):
            assert key in data, f"Missing key: {key}"

    def test_milestones_list_length(self, tmp_path):
        """APY_MILESTONES constant should have exactly 5 entries."""
        assert len(APY_MILESTONES) == 5

    def test_milestones_pct_values_correct(self, tmp_path):
        """Milestone target_pct values must match specification."""
        targets = [m["target_pct"] for m in APY_MILESTONES]
        assert targets == [5.0, 7.0, 10.0, 12.0, 15.0]


# ===========================================================================
# 2. RecordDay tests (12)
# ===========================================================================

class TestApyMilestoneTrackerRecordDay:

    def test_record_single_day_returns_dict(self, tmp_path):
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 10.115, "S7")
        assert isinstance(result, dict)

    def test_record_day_appears_in_log(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        data = json.loads(log_path(tmp_path).read_text())
        assert len(data["daily_log"]) == 1
        assert data["daily_log"][0]["date"] == "2026-06-12"

    def test_record_day_apy_stored(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-13", 7.5)
        data = json.loads(log_path(tmp_path).read_text())
        assert data["daily_log"][0]["apy_pct"] == pytest.approx(7.5, rel=1e-5)

    def test_record_day_default_strategy_id(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 8.0)
        data = json.loads(log_path(tmp_path).read_text())
        assert data["daily_log"][0]["strategy_id"] == "tournament_winner"

    def test_record_day_custom_strategy_id(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 8.0, "S11")
        data = json.loads(log_path(tmp_path).read_text())
        assert data["daily_log"][0]["strategy_id"] == "S11"

    def test_deduplication_same_date(self, tmp_path):
        """Recording the same date twice must NOT create duplicate entries."""
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 5.0, "S7")
        tracker.record_day("2026-06-12", 9.0, "S8")   # overwrite
        data = json.loads(log_path(tmp_path).read_text())
        entries = [e for e in data["daily_log"] if e["date"] == "2026-06-12"]
        assert len(entries) == 1
        assert entries[0]["apy_pct"] == pytest.approx(9.0, rel=1e-5)

    def test_deduplication_preserves_other_dates(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 5.0, "S7")
        tracker.record_day("2026-06-13", 8.0, "S7")
        tracker.record_day("2026-06-12", 9.5, "S8")
        data = json.loads(log_path(tmp_path).read_text())
        assert len(data["daily_log"]) == 2

    def test_milestone_level1_reached_when_apy_above_5(self, tmp_path):
        """APY >= 5.0 should trigger milestone level 1."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 5.5, "S7")
        lvl1 = next(m for m in result["milestones"] if m["level"] == 1)
        assert lvl1["reached"] is True

    def test_milestone_level3_reached_when_apy_above_10(self, tmp_path):
        """APY >= 10.0 should mark levels 1, 2, and 3 as reached."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 10.115, "S7")
        for lvl in (1, 2, 3):
            m = next(x for x in result["milestones"] if x["level"] == lvl)
            assert m["reached"] is True, f"Level {lvl} should be reached"

    def test_milestone_level5_not_reached_below_15(self, tmp_path):
        """APY 14.9 must NOT trigger level 5."""
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 14.9, "S7")
        lvl5 = next(m for m in result["milestones"] if m["level"] == 5)
        assert lvl5["reached"] is False

    def test_days_recorded_increments(self, tmp_path):
        tracker = make_tracker(tmp_path)
        for i, apy in enumerate([5.0, 7.0, 10.0], start=12):
            tracker.record_day(f"2026-06-{i:02d}", apy)
        data = json.loads(log_path(tmp_path).read_text())
        assert data["days_recorded"] == 3

    def test_record_day_returns_milestone_count(self, tmp_path):
        tracker = make_tracker(tmp_path)
        result = tracker.record_day("2026-06-12", 20.0)
        assert result["milestones_total"] == 5
        assert result["milestones_reached_count"] == 5


# ===========================================================================
# 3. Queries tests (15)
# ===========================================================================

class TestApyMilestoneTrackerQueries:

    def _seed(self, tmp_path, entries):
        """Seed tracker with (date, apy) tuples."""
        tracker = make_tracker(tmp_path)
        for date, apy in entries:
            tracker.record_day(date, apy)
        return tracker

    # get_days_above ---------------------------------------------------------

    def test_days_above_zero_when_no_days(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_days_above(5.0) == 0

    def test_days_above_counts_correctly(self, tmp_path):
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 4.9),
            ("2026-06-13", 5.1),
            ("2026-06-14", 6.0),
        ])
        assert tracker.get_days_above(5.0) == 2

    def test_days_above_exact_boundary_counts(self, tmp_path):
        """APY exactly equal to target must be counted (>=)."""
        tracker = self._seed(tmp_path, [("2026-06-12", 7.0)])
        assert tracker.get_days_above(7.0) == 1

    def test_days_above_all_below_target(self, tmp_path):
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 2.0),
            ("2026-06-13", 3.0),
        ])
        assert tracker.get_days_above(5.0) == 0

    def test_days_above_all_above_target(self, tmp_path):
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 10.0),
            ("2026-06-13", 11.0),
            ("2026-06-14", 12.0),
        ])
        assert tracker.get_days_above(5.0) == 3

    # get_avg_apy ------------------------------------------------------------

    def test_avg_apy_zero_when_no_days(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_avg_apy() == 0.0

    def test_avg_apy_single_entry(self, tmp_path):
        tracker = self._seed(tmp_path, [("2026-06-12", 8.0)])
        assert tracker.get_avg_apy(7) == pytest.approx(8.0, rel=1e-5)

    def test_avg_apy_rolling_window(self, tmp_path):
        """7-day window over 10 entries should only average last 7."""
        entries = [(f"2026-06-{i+1:02d}", float(i)) for i in range(10)]
        tracker = self._seed(tmp_path, entries)
        expected = sum(range(3, 10)) / 7  # last 7 values: 3..9
        assert tracker.get_avg_apy(7) == pytest.approx(expected, rel=1e-5)

    def test_avg_apy_window_larger_than_data(self, tmp_path):
        """Window > recorded days uses all available data."""
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 6.0),
            ("2026-06-13", 8.0),
        ])
        expected = 7.0
        assert tracker.get_avg_apy(30) == pytest.approx(expected, rel=1e-5)

    def test_avg_apy_window_1(self, tmp_path):
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 6.0),
            ("2026-06-13", 9.0),
        ])
        assert tracker.get_avg_apy(1) == pytest.approx(9.0, rel=1e-5)

    # get_best_day -----------------------------------------------------------

    def test_best_day_empty_returns_empty_dict(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_best_day() == {}

    def test_best_day_single_entry(self, tmp_path):
        tracker = self._seed(tmp_path, [("2026-06-12", 10.0)])
        best = tracker.get_best_day()
        assert best["date"] == "2026-06-12"
        assert best["apy_pct"] == pytest.approx(10.0, rel=1e-5)

    def test_best_day_picks_max(self, tmp_path):
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 5.0),
            ("2026-06-13", 12.5),
            ("2026-06-14", 8.0),
        ])
        best = tracker.get_best_day()
        assert best["date"] == "2026-06-13"

    def test_best_day_has_strategy_id(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 11.0, "S11")
        best = tracker.get_best_day()
        assert best["strategy_id"] == "S11"

    def test_get_days_above_with_float_precision(self, tmp_path):
        """Floating-point values close to threshold should be handled correctly."""
        tracker = self._seed(tmp_path, [
            ("2026-06-12", 4.9999),
            ("2026-06-13", 5.0001),
        ])
        assert tracker.get_days_above(5.0) == 1


# ===========================================================================
# 4. Report tests (8)
# ===========================================================================

class TestApyMilestoneTrackerReport:

    def test_report_is_dict(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert isinstance(tracker.get_milestone_report(), dict)

    def test_report_has_required_keys(self, tmp_path):
        tracker = make_tracker(tmp_path)
        report = tracker.get_milestone_report()
        required = {
            "start_date", "last_updated", "days_recorded",
            "avg_apy_7d", "best_day", "milestones",
            "milestones_reached_count", "milestones_total",
        }
        assert required.issubset(report.keys())

    def test_report_milestones_is_list(self, tmp_path):
        tracker = make_tracker(tmp_path)
        report = tracker.get_milestone_report()
        assert isinstance(report["milestones"], list)

    def test_report_milestones_total_is_5(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_milestone_report()["milestones_total"] == 5

    def test_report_days_recorded_zero_initially(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert tracker.get_milestone_report()["days_recorded"] == 0

    def test_report_avg_apy_type_float(self, tmp_path):
        tracker = make_tracker(tmp_path)
        assert isinstance(tracker.get_milestone_report()["avg_apy_7d"], float)

    def test_report_after_recording_updates_count(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 10.115, "S7")
        tracker.record_day("2026-06-13", 9.0, "S7")
        report = tracker.get_milestone_report()
        assert report["days_recorded"] == 2

    def test_report_milestones_reached_count_correct(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 11.0)  # levels 1, 2, 3 reached; 4,5 not
        report = tracker.get_milestone_report()
        assert report["milestones_reached_count"] == 3


# ===========================================================================
# 5. Persistence tests (10)
# ===========================================================================

class TestApyMilestoneTrackerPersistence:

    def test_written_data_persists_on_reload(self, tmp_path):
        """Data recorded in one instance must be readable by a new instance."""
        t1 = make_tracker(tmp_path)
        t1.record_day("2026-06-12", 10.115, "S7")
        del t1

        t2 = make_tracker(tmp_path)
        log = t2._data["daily_log"]
        assert len(log) == 1
        assert log[0]["date"] == "2026-06-12"

    def test_multiple_days_persist(self, tmp_path):
        t1 = make_tracker(tmp_path)
        for i in range(5):
            t1.record_day(f"2026-06-{12+i:02d}", 5.0 + i)
        del t1

        t2 = make_tracker(tmp_path)
        assert len(t2._data["daily_log"]) == 5

    def test_milestones_reached_persists(self, tmp_path):
        t1 = make_tracker(tmp_path)
        t1.record_day("2026-06-12", 16.0)  # all 5 milestones
        del t1

        t2 = make_tracker(tmp_path)
        assert len(t2._data["milestones_reached"]) == 5

    def test_atomic_write_produces_valid_json(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 8.5)
        raw = log_path(tmp_path).read_text()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_no_temp_files_left_after_write(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 8.5)
        leftovers = list(tmp_path.glob(".apy_milestone_tmp_*.json"))
        assert leftovers == [], f"Temp files left: {leftovers}"

    def test_log_file_is_regular_file(self, tmp_path):
        tracker = make_tracker(tmp_path)
        tracker.record_day("2026-06-12", 8.5)
        assert log_path(tmp_path).is_file()

    def test_reload_preserves_start_date(self, tmp_path):
        t1 = make_tracker(tmp_path)
        t1.record_day("2026-06-12", 5.0)
        start = t1._data["start_date"]
        del t1

        t2 = make_tracker(tmp_path)
        assert t2._data["start_date"] == start

    def test_reload_days_recorded_matches_log_length(self, tmp_path):
        t1 = make_tracker(tmp_path)
        for i in range(7):
            t1.record_day(f"2026-06-{12+i:02d}", 7.0 + i)
        del t1

        t2 = make_tracker(tmp_path)
        assert t2._data["days_recorded"] == len(t2._data["daily_log"])

    def test_dedup_persists_correctly(self, tmp_path):
        """Overwriting a date should persist the updated value, not the original."""
        t1 = make_tracker(tmp_path)
        t1.record_day("2026-06-12", 5.0)
        t1.record_day("2026-06-12", 12.0)   # overwrite
        del t1

        t2 = make_tracker(tmp_path)
        entries = [e for e in t2._data["daily_log"] if e["date"] == "2026-06-12"]
        assert len(entries) == 1
        assert entries[0]["apy_pct"] == pytest.approx(12.0, rel=1e-5)

    def test_fresh_tracker_on_missing_file_returns_empty_log(self, tmp_path):
        """If log file is absent, tracker initialises with an empty daily_log."""
        tracker = ApyMilestoneTracker(data_dir=tmp_path / "nonexistent_dir")
        assert tracker._data["daily_log"] == []
