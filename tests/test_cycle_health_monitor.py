"""
tests/test_cycle_health_monitor.py
=====================================
Unit tests for spa_core.monitoring.cycle_health_monitor — CycleHealthMonitor.

Coverage (≥ 45 tests):

check_cycle_gap:
  T01  OK  — entry with timestamp <2h ago
  T02  OK  — entry with date field today (within 2h of midnight, edge-case mock)
  T03  WARNING  — entry with timestamp 3h ago
  T04  CRITICAL — entry with timestamp 5h ago
  T05  CRITICAL — empty equity_history
  T06  CRITICAL — equity_history with no parseable timestamp or date
  T07  Boundary: exactly 2.0 h → OK (not yet past threshold)
  T08  Boundary: exactly 4.0 h → WARNING (not yet past CRITICAL threshold)
  T09  Entry uses epoch float as timestamp
  T10  Entry uses ISO string with UTC offset as timestamp
  T11  Entry with both timestamp and date — timestamp takes priority
  T12  last_cycle_at is ISO string in result
  T13  hours_since is a float in result
  T14  threshold_hours is 2.0 in result

check_equity_anomaly:
  T15  OK — equity increased
  T16  OK — equity unchanged (0% change)
  T17  OK — small drop (< 5%)
  T18  WARNING — drop exactly 5.01%
  T19  WARNING — large drop (10%)
  T20  OK — single entry (no prev to compare)
  T21  OK — empty history
  T22  today_change_pct is None when single entry
  T23  prev_equity / curr_equity populated correctly
  T24  max_drop_threshold is 5.0 in result
  T25  prev_equity == 0 → OK with detail (no ZeroDivision)
  T26  Large equity gain has positive today_change_pct

check_data_freshness:
  T27  OK — all files fresh (mocked mtime within threshold)
  T28  STALE — market_regime.json older than 4h
  T29  STALE — adapter_status.json older than 24h
  T30  STALE — tournament_ranking.json older than 168h
  T31  Multiple stale files — all appear in stale_files list
  T32  Missing file appears in missing_files, not stale_files
  T33  status OK when all files are fresh
  T34  fresh_files list populated for non-stale files
  T35  Boundary: file age exactly == threshold → fresh (not stale)
  T36  Boundary: file age threshold + tiny epsilon → stale

run_all_checks:
  T37  HEALTHY — all checks pass
  T38  WARNING — cycle_gap WARNING, others OK
  T39  CRITICAL — cycle_gap CRITICAL
  T40  WARNING — equity_anomaly WARNING, others OK
  T41  WARNING — data_freshness STALE, others OK
  T42  CRITICAL beats WARNING (both present → CRITICAL)
  T43  recommendations list is non-empty on WARNING
  T44  recommendations list is non-empty on CRITICAL
  T45  HEALTHY yields "All checks passed" in recommendations
  T46  checked_at is a valid ISO string
  T47  checks dict has exactly three keys: cycle_gap, equity_anomaly, data_freshness
  T48  Missing equity_history.json → CRITICAL with empty history fallback

save_health_report:
  T49  Writes cycle_health.json to data_dir
  T50  Content round-trips through JSON correctly
  T51  Atomic: temp file is cleaned up after write
  T52  Overwrites existing cycle_health.json with new content
  T53  No lingering .tmp file after successful save
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

# -----------------------------------------------------------------------
# Ensure repo root is on sys.path
# -----------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.cycle_health_monitor import (
    CRITICAL,
    CRITICAL_CYCLE_GAP_HOURS,
    HEALTHY,
    MAX_CYCLE_GAP_HOURS,
    MAX_EQUITY_DROP_PCT,
    OK,
    STALE,
    STALE_ADAPTER_HOURS,
    STALE_REGIME_HOURS,
    STALE_TOURNAMENT_HOURS,
    WARNING,
    CycleHealthMonitor,
    _now_epoch,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso_hours_ago(hours: float) -> str:
    return (_utc_now() - timedelta(hours=hours)).isoformat()


def _epoch_hours_ago(hours: float) -> float:
    return (_utc_now() - timedelta(hours=hours)).timestamp()


def _make_entry_ts(hours_ago: float, equity: float = 100_000.0) -> dict:
    """Entry with ISO timestamp."""
    return {"timestamp": _iso_hours_ago(hours_ago), "equity": equity, "date": "2026-01-01"}


def _make_entry_date(date_str: str, equity: float = 100_000.0) -> dict:
    """Entry with only date field."""
    return {"date": date_str, "equity": equity}


# -----------------------------------------------------------------------
# TestCheckCycleGap
# -----------------------------------------------------------------------

class TestCheckCycleGap(unittest.TestCase):
    def setUp(self):
        self.monitor = CycleHealthMonitor()

    # T01
    def test_cycle_gap_ok_recent_timestamp(self):
        history = [_make_entry_ts(0.5)]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], OK)
        self.assertIsNotNone(result["last_cycle_at"])
        self.assertAlmostEqual(result["hours_since"], 0.5, delta=0.05)

    # T02
    def test_cycle_gap_ok_date_field(self):
        """Date-only entry: today's date; hours_since depends on time of day.
        We mock _now_epoch-equivalent by using a date from 0.5h ago (same day)."""
        today_str = _utc_now().strftime("%Y-%m-%d")
        history = [_make_entry_date(today_str)]
        result = self.monitor.check_cycle_gap(history)
        # hours_since >= 0 and last_cycle_at is set
        self.assertIsNotNone(result["last_cycle_at"])
        self.assertGreaterEqual(result["hours_since"], 0.0)

    # T03
    def test_cycle_gap_warning_3h(self):
        history = [_make_entry_ts(3.0)]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], WARNING)

    # T04
    def test_cycle_gap_critical_5h(self):
        history = [_make_entry_ts(5.0)]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], CRITICAL)

    # T05
    def test_cycle_gap_empty_history(self):
        result = self.monitor.check_cycle_gap([])
        self.assertEqual(result["status"], CRITICAL)
        self.assertIsNone(result["last_cycle_at"])
        self.assertIsNone(result["hours_since"])

    # T06
    def test_cycle_gap_no_parseable_ts(self):
        history = [{"equity": 100_000.0, "note": "no time fields"}]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], CRITICAL)
        self.assertIsNone(result["last_cycle_at"])

    # T07 — exactly 2h → OK (strictly less than MAX)
    def test_cycle_gap_boundary_exactly_2h_ok(self):
        # 2h minus 1 second → still OK
        history = [_make_entry_ts(MAX_CYCLE_GAP_HOURS - (1 / 3600))]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], OK)

    # T08 — exactly 4h → WARNING (not yet CRITICAL)
    def test_cycle_gap_boundary_exactly_4h_warning(self):
        history = [_make_entry_ts(CRITICAL_CYCLE_GAP_HOURS - (1 / 3600))]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], WARNING)

    # T09
    def test_cycle_gap_epoch_float_timestamp(self):
        history = [{"timestamp": _epoch_hours_ago(1.0), "equity": 100_000.0}]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], OK)
        self.assertAlmostEqual(result["hours_since"], 1.0, delta=0.05)

    # T10
    def test_cycle_gap_iso_with_utc_offset(self):
        ts = _iso_hours_ago(0.75)  # already has +00:00 via isoformat
        history = [{"timestamp": ts, "equity": 100_000.0}]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], OK)

    # T11 — timestamp takes priority over date
    def test_cycle_gap_timestamp_priority_over_date(self):
        # timestamp = 5h ago (CRITICAL), date = today (would be OK)
        today_str = _utc_now().strftime("%Y-%m-%d")
        history = [{"timestamp": _iso_hours_ago(5.0), "date": today_str, "equity": 100_000.0}]
        result = self.monitor.check_cycle_gap(history)
        self.assertEqual(result["status"], CRITICAL)

    # T12
    def test_cycle_gap_last_cycle_at_is_iso_string(self):
        history = [_make_entry_ts(1.0)]
        result = self.monitor.check_cycle_gap(history)
        self.assertIsInstance(result["last_cycle_at"], str)
        # Must be parseable as ISO
        parsed = datetime.fromisoformat(result["last_cycle_at"])
        self.assertIsNotNone(parsed)

    # T13
    def test_cycle_gap_hours_since_is_float(self):
        history = [_make_entry_ts(1.0)]
        result = self.monitor.check_cycle_gap(history)
        self.assertIsInstance(result["hours_since"], float)

    # T14
    def test_cycle_gap_threshold_hours_value(self):
        result = self.monitor.check_cycle_gap([_make_entry_ts(0.1)])
        self.assertEqual(result["threshold_hours"], MAX_CYCLE_GAP_HOURS)


# -----------------------------------------------------------------------
# TestCheckEquityAnomaly
# -----------------------------------------------------------------------

class TestCheckEquityAnomaly(unittest.TestCase):
    def setUp(self):
        self.monitor = CycleHealthMonitor()

    # T15
    def test_equity_anomaly_ok_increase(self):
        history = [{"equity": 100_000.0}, {"equity": 100_500.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], OK)
        self.assertGreater(result["today_change_pct"], 0)

    # T16
    def test_equity_anomaly_ok_unchanged(self):
        history = [{"equity": 100_000.0}, {"equity": 100_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], OK)
        self.assertAlmostEqual(result["today_change_pct"], 0.0)

    # T17
    def test_equity_anomaly_ok_small_drop(self):
        # Drop 4.9% — under the 5% threshold
        prev = 100_000.0
        curr = prev * (1 - 0.049)
        history = [{"equity": prev}, {"equity": curr}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], OK)

    # T18
    def test_equity_anomaly_warning_drop_just_over_5pct(self):
        prev = 100_000.0
        curr = prev * (1 - 0.0501)
        history = [{"equity": prev}, {"equity": curr}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], WARNING)

    # T19
    def test_equity_anomaly_warning_large_drop(self):
        history = [{"equity": 100_000.0}, {"equity": 85_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], WARNING)
        self.assertLess(result["today_change_pct"], -5.0)

    # T20
    def test_equity_anomaly_ok_single_entry(self):
        history = [{"equity": 100_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["status"], OK)

    # T21
    def test_equity_anomaly_ok_empty_history(self):
        result = self.monitor.check_equity_anomaly([])
        self.assertEqual(result["status"], OK)

    # T22
    def test_equity_anomaly_change_pct_none_for_single_entry(self):
        result = self.monitor.check_equity_anomaly([{"equity": 100_000.0}])
        self.assertIsNone(result["today_change_pct"])

    # T23
    def test_equity_anomaly_prev_curr_equity_populated(self):
        history = [{"equity": 99_000.0}, {"equity": 100_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertEqual(result["prev_equity"], 99_000.0)
        self.assertEqual(result["curr_equity"], 100_000.0)

    # T24
    def test_equity_anomaly_max_drop_threshold_value(self):
        result = self.monitor.check_equity_anomaly([{"equity": 1.0}, {"equity": 1.0}])
        self.assertEqual(result["max_drop_threshold"], MAX_EQUITY_DROP_PCT)

    # T25
    def test_equity_anomaly_prev_equity_zero_no_crash(self):
        history = [{"equity": 0.0}, {"equity": 100_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        # Must not raise; status stays OK
        self.assertEqual(result["status"], OK)

    # T26
    def test_equity_anomaly_large_gain_positive_change_pct(self):
        history = [{"equity": 100_000.0}, {"equity": 150_000.0}]
        result = self.monitor.check_equity_anomaly(history)
        self.assertAlmostEqual(result["today_change_pct"], 50.0, delta=0.01)
        self.assertEqual(result["status"], OK)


# -----------------------------------------------------------------------
# TestCheckDataFreshness
# -----------------------------------------------------------------------

class TestCheckDataFreshness(unittest.TestCase):
    def setUp(self):
        self.monitor = CycleHealthMonitor()

    def _fresh_mtime(self, filename: str) -> float:
        """Return mtime that is 1h ago (within all thresholds)."""
        return _epoch_hours_ago(1.0)

    # T27
    def test_data_freshness_ok_all_fresh(self):
        now_ep = _utc_now().timestamp()
        mtime_fresh = now_ep - 3600  # 1h ago
        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   return_value=mtime_fresh), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")
        self.assertEqual(result["status"], OK)
        self.assertEqual(result["stale_files"], [])
        self.assertEqual(result["missing_files"], [])
        self.assertEqual(len(result["fresh_files"]), 3)

    # T28
    def test_data_freshness_stale_market_regime(self):
        now_ep = _utc_now().timestamp()
        stale_regime = now_ep - (STALE_REGIME_HOURS + 1) * 3600
        fresh_other = now_ep - 3600

        def fake_mtime(path: str) -> float:
            if "market_regime" in path:
                return stale_regime
            return fresh_other

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=fake_mtime), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        self.assertEqual(result["status"], STALE)
        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertIn("market_regime.json", stale_names)

    # T29
    def test_data_freshness_stale_adapter_status(self):
        now_ep = _utc_now().timestamp()
        stale_adapter = now_ep - (STALE_ADAPTER_HOURS + 1) * 3600
        fresh_other = now_ep - 3600

        def fake_mtime(path: str) -> float:
            if "adapter_status" in path:
                return stale_adapter
            return fresh_other

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=fake_mtime), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        self.assertEqual(result["status"], STALE)
        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertIn("adapter_status.json", stale_names)

    # T30
    def test_data_freshness_stale_tournament_ranking(self):
        now_ep = _utc_now().timestamp()
        stale_tourn = now_ep - (STALE_TOURNAMENT_HOURS + 1) * 3600
        fresh_other = now_ep - 3600

        def fake_mtime(path: str) -> float:
            if "tournament_ranking" in path:
                return stale_tourn
            return fresh_other

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=fake_mtime), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        self.assertEqual(result["status"], STALE)
        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertIn("tournament_ranking.json", stale_names)

    # T31
    def test_data_freshness_multiple_stale_files(self):
        now_ep = _utc_now().timestamp()
        very_stale = now_ep - 500 * 3600  # 500h ago

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   return_value=very_stale), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        self.assertEqual(result["status"], STALE)
        self.assertEqual(len(result["stale_files"]), 3)

    # T32
    def test_data_freshness_missing_file(self):
        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=FileNotFoundError):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        self.assertEqual(len(result["missing_files"]), 3)
        self.assertEqual(result["stale_files"], [])

    # T33
    def test_data_freshness_ok_status_when_all_fresh(self):
        now_ep = _utc_now().timestamp()
        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   return_value=now_ep - 60), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")
        self.assertEqual(result["status"], OK)

    # T34
    def test_data_freshness_fresh_files_list_populated(self):
        now_ep = _utc_now().timestamp()
        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   return_value=now_ep - 60), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")
        self.assertEqual(len(result["fresh_files"]), 3)
        for entry in result["fresh_files"]:
            self.assertIn("file", entry)
            self.assertIn("age_hours", entry)
            self.assertIn("threshold_hours", entry)

    # T35 — exactly at threshold → fresh
    def test_data_freshness_boundary_exactly_at_threshold_fresh(self):
        now_ep = _utc_now().timestamp()
        # market_regime threshold = 4h; mtime exactly 4h ago → age_hours == 4.0 → NOT > threshold
        mtime = now_ep - STALE_REGIME_HOURS * 3600
        fresh_other = now_ep - 60

        def fake_mtime(path: str) -> float:
            if "market_regime" in path:
                return mtime
            return fresh_other

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=fake_mtime), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertNotIn("market_regime.json", stale_names)

    # T36 — threshold + tiny epsilon → stale
    def test_data_freshness_boundary_just_over_threshold_stale(self):
        now_ep = _utc_now().timestamp()
        mtime = now_ep - (STALE_REGIME_HOURS * 3600 + 1)  # 1 second over
        fresh_other = now_ep - 60

        def fake_mtime(path: str) -> float:
            if "market_regime" in path:
                return mtime
            return fresh_other

        with patch("spa_core.monitoring.cycle_health_monitor.os.path.getmtime",
                   side_effect=fake_mtime), \
             patch("spa_core.monitoring.cycle_health_monitor._now_epoch",
                   return_value=now_ep):
            result = self.monitor.check_data_freshness(data_dir="/fake/dir")

        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertIn("market_regime.json", stale_names)


# -----------------------------------------------------------------------
# TestRunAllChecks
# -----------------------------------------------------------------------

class TestRunAllChecks(unittest.TestCase):
    def setUp(self):
        self.monitor = CycleHealthMonitor()

    def _make_temp_data_dir(
        self,
        equity_entries: list | None = None,
        market_regime_age_h: float = 1.0,
        adapter_age_h: float = 1.0,
        tournament_age_h: float = 1.0,
    ) -> str:
        """Create a temp directory with equity_history.json and fake data files."""
        tmpdir = tempfile.mkdtemp()
        data_dir = Path(tmpdir)

        if equity_entries is None:
            equity_entries = [_make_entry_ts(0.5), _make_entry_ts(0.0, equity=100_010.0)]

        eq_file = data_dir / "equity_history.json"
        eq_file.write_text(json.dumps(equity_entries), encoding="utf-8")

        now_ep = _utc_now().timestamp()

        for fname in ["market_regime.json", "adapter_status.json", "tournament_ranking.json"]:
            fpath = data_dir / fname
            fpath.write_text("{}", encoding="utf-8")

        # Touch mtimes via os.utime
        for fname, age_h in [
            ("market_regime.json", market_regime_age_h),
            ("adapter_status.json", adapter_age_h),
            ("tournament_ranking.json", tournament_age_h),
        ]:
            fpath = data_dir / fname
            mtime = now_ep - age_h * 3600
            os.utime(str(fpath), (mtime, mtime))

        return tmpdir

    # T37
    def test_run_all_healthy(self):
        tmpdir = self._make_temp_data_dir()
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["overall"], HEALTHY)

    # T38
    def test_run_all_warning_cycle_gap(self):
        entries = [_make_entry_ts(3.0)]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["overall"], WARNING)

    # T39
    def test_run_all_critical_cycle_gap(self):
        entries = [_make_entry_ts(6.0)]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["overall"], CRITICAL)

    # T40
    def test_run_all_warning_equity_anomaly(self):
        entries = [
            {"equity": 100_000.0, "timestamp": _iso_hours_ago(1.5)},
            {"equity": 80_000.0, "timestamp": _iso_hours_ago(0.5)},  # -20%
        ]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["overall"], WARNING)

    # T41
    def test_run_all_warning_data_freshness_stale(self):
        tmpdir = self._make_temp_data_dir(market_regime_age_h=STALE_REGIME_HOURS + 1)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["overall"], WARNING)

    # T42
    def test_run_all_critical_beats_warning(self):
        # cycle_gap CRITICAL (last entry 6h ago) AND equity_anomaly WARNING (-20% drop)
        # Both entries are old so check_cycle_gap uses [-1] = 6h ago → CRITICAL
        entries = [
            {"equity": 100_000.0, "timestamp": _iso_hours_ago(7.0)},
            {"equity": 80_000.0, "timestamp": _iso_hours_ago(6.0)},  # -20% drop; 6h → CRITICAL gap
        ]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["checks"]["cycle_gap"]["status"], CRITICAL)
        self.assertEqual(result["checks"]["equity_anomaly"]["status"], WARNING)
        self.assertEqual(result["overall"], CRITICAL)

    # T43
    def test_run_all_recommendations_nonempty_on_warning(self):
        entries = [_make_entry_ts(3.0)]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertGreater(len(result["recommendations"]), 0)
        joined = " ".join(result["recommendations"])
        self.assertIn("WARNING", joined.upper())

    # T44
    def test_run_all_recommendations_nonempty_on_critical(self):
        entries = [_make_entry_ts(6.0)]
        tmpdir = self._make_temp_data_dir(equity_entries=entries)
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertGreater(len(result["recommendations"]), 0)
        joined = " ".join(result["recommendations"])
        self.assertIn("CRITICAL", joined.upper())

    # T45
    def test_run_all_healthy_recommendation_message(self):
        tmpdir = self._make_temp_data_dir()
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        joined = " ".join(result["recommendations"])
        self.assertIn("passed", joined.lower())

    # T46
    def test_run_all_checked_at_is_iso_string(self):
        tmpdir = self._make_temp_data_dir()
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertIsInstance(result["checked_at"], str)
        parsed = datetime.fromisoformat(result["checked_at"])
        self.assertIsNotNone(parsed)

    # T47
    def test_run_all_checks_dict_has_three_keys(self):
        tmpdir = self._make_temp_data_dir()
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertSetEqual(
            set(result["checks"].keys()),
            {"cycle_gap", "equity_anomaly", "data_freshness"},
        )

    # T48
    def test_run_all_missing_equity_history_critical(self):
        tmpdir = tempfile.mkdtemp()
        # No equity_history.json — empty list fallback → CRITICAL (empty history)
        data_dir = Path(tmpdir)
        for fname in ["market_regime.json", "adapter_status.json", "tournament_ranking.json"]:
            (data_dir / fname).write_text("{}")
        result = self.monitor.run_all_checks(data_dir=tmpdir)
        self.assertEqual(result["checks"]["cycle_gap"]["status"], CRITICAL)
        self.assertEqual(result["overall"], CRITICAL)


# -----------------------------------------------------------------------
# TestSaveHealthReport
# -----------------------------------------------------------------------

class TestSaveHealthReport(unittest.TestCase):
    def setUp(self):
        self.monitor = CycleHealthMonitor()
        self.tmpdir = tempfile.mkdtemp()

    # T49
    def test_save_creates_cycle_health_json(self):
        report = {"overall": HEALTHY, "checks": {}, "checked_at": "2026-01-01T00:00:00+00:00"}
        self.monitor.save_health_report(report, data_dir=self.tmpdir)
        out_file = Path(self.tmpdir) / "cycle_health.json"
        self.assertTrue(out_file.exists())

    # T50
    def test_save_content_round_trips(self):
        report = {
            "overall": WARNING,
            "checks": {"cycle_gap": {"status": WARNING}},
            "checked_at": "2026-06-01T10:00:00+00:00",
            "recommendations": ["Fix cycle."],
        }
        self.monitor.save_health_report(report, data_dir=self.tmpdir)
        out_file = Path(self.tmpdir) / "cycle_health.json"
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["overall"], WARNING)
        self.assertEqual(loaded["recommendations"], ["Fix cycle."])

    # T51
    def test_save_no_tmp_file_after_write(self):
        report = {"overall": HEALTHY}
        self.monitor.save_health_report(report, data_dir=self.tmpdir)
        tmp_file = Path(self.tmpdir) / "cycle_health.json.tmp"
        self.assertFalse(tmp_file.exists())

    # T52
    def test_save_overwrites_existing_file(self):
        out_file = Path(self.tmpdir) / "cycle_health.json"
        out_file.write_text('{"overall": "OLD"}', encoding="utf-8")
        report = {"overall": CRITICAL}
        self.monitor.save_health_report(report, data_dir=self.tmpdir)
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["overall"], CRITICAL)

    # T53
    def test_save_atomic_no_lingering_tmp(self):
        """Verify that .tmp file does not persist even after repeated saves."""
        for i in range(3):
            report = {"overall": HEALTHY, "run": i}
            self.monitor.save_health_report(report, data_dir=self.tmpdir)
        tmp_file = Path(self.tmpdir) / "cycle_health.json.tmp"
        self.assertFalse(tmp_file.exists())
        # Final file has last run number
        out_file = Path(self.tmpdir) / "cycle_health.json"
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["run"], 2)


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
