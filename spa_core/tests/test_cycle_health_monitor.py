"""
Tests for spa_core.analytics.cycle_health_monitor (MP-631).

Coverage: 38 unit tests across:
  - TestCycleHealthEntryDataclass     (6)
  - TestComputeStatus                 (8)
  - TestRecordCycle                   (6)
  - TestGetRecentCycles               (5)
  - TestComputeHealthScore            (6)
  - TestGetErrorFrequency             (4)
  - TestIsSystemHealthy               (3)
  - TestGenerateReport                (5)
  - TestRingBuffer                    (2)
  - TestAtomicWrite                   (2)  (total = 47)

Run:
  python3 -m unittest spa_core.tests.test_cycle_health_monitor -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.cycle_health_monitor import (
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_OK,
    CycleHealthEntry,
    CycleHealthMonitor,
    _HEALTH_LOG_FILE,
    _RING_BUFFER_MAX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor(tmp_dir: str) -> CycleHealthMonitor:
    return CycleHealthMonitor(data_dir=tmp_dir)


def _record(
    monitor: CycleHealthMonitor,
    cycle_id: str = "C001",
    strategies_run: int = 5,
    adapters_polled: int = 10,
    errors: list | None = None,
    duration_seconds: float = 30.0,
    apy_snapshot: dict | None = None,
) -> CycleHealthEntry:
    return monitor.record_cycle(
        cycle_id=cycle_id,
        strategies_run=strategies_run,
        adapters_polled=adapters_polled,
        errors=errors or [],
        duration_seconds=duration_seconds,
        apy_snapshot=apy_snapshot or {"aave_v3": 3.5, "compound_v3": 4.8},
    )


# ---------------------------------------------------------------------------
# TestCycleHealthEntryDataclass
# ---------------------------------------------------------------------------

class TestCycleHealthEntryDataclass(unittest.TestCase):
    """6 tests."""

    def _make(self, **kwargs) -> CycleHealthEntry:
        defaults = dict(
            timestamp="2026-06-13T08:00:00+00:00",
            cycle_id="C001",
            strategies_run=5,
            adapters_polled=10,
            errors=[],
            duration_seconds=45.0,
            status=STATUS_OK,
            apy_snapshot={"aave_v3": 3.5},
        )
        defaults.update(kwargs)
        return CycleHealthEntry(**defaults)

    def test_to_dict_keys(self):
        e = self._make()
        d = e.to_dict()
        self.assertIn("timestamp", d)
        self.assertIn("cycle_id", d)
        self.assertIn("strategies_run", d)
        self.assertIn("adapters_polled", d)
        self.assertIn("errors", d)
        self.assertIn("duration_seconds", d)
        self.assertIn("status", d)
        self.assertIn("apy_snapshot", d)

    def test_to_dict_values(self):
        e = self._make(strategies_run=7, adapters_polled=12, status=STATUS_OK)
        d = e.to_dict()
        self.assertEqual(d["strategies_run"], 7)
        self.assertEqual(d["adapters_polled"], 12)
        self.assertEqual(d["status"], STATUS_OK)

    def test_from_dict_roundtrip(self):
        e = self._make(errors=["err1"], duration_seconds=95.5)
        d = e.to_dict()
        e2 = CycleHealthEntry.from_dict(d)
        self.assertEqual(e2.cycle_id, e.cycle_id)
        self.assertEqual(e2.errors, ["err1"])
        self.assertAlmostEqual(e2.duration_seconds, 95.5, places=2)

    def test_from_dict_missing_fields_defaults(self):
        e = CycleHealthEntry.from_dict({})
        self.assertEqual(e.cycle_id, "")
        self.assertEqual(e.strategies_run, 0)
        self.assertEqual(e.adapters_polled, 0)
        self.assertEqual(e.errors, [])
        self.assertAlmostEqual(e.duration_seconds, 0.0)
        self.assertEqual(e.status, STATUS_OK)

    def test_apy_snapshot_rounded(self):
        e = self._make(apy_snapshot={"aave_v3": 3.14159265358})
        d = e.to_dict()
        # Should be rounded to 6 decimal places
        self.assertEqual(d["apy_snapshot"]["aave_v3"], round(3.14159265358, 6))

    def test_errors_list_copy(self):
        original_errors = ["err_a", "err_b"]
        e = self._make(errors=original_errors)
        d = e.to_dict()
        d["errors"].append("extra")
        self.assertEqual(len(e.errors), 2)  # original unaffected


# ---------------------------------------------------------------------------
# TestComputeStatus
# ---------------------------------------------------------------------------

class TestComputeStatus(unittest.TestCase):
    """8 tests for _compute_status via record_cycle."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_ok_no_errors_fast(self):
        e = _record(self.m, errors=[], duration_seconds=10.0)
        self.assertEqual(e.status, STATUS_OK)

    def test_ok_max_duration_below_threshold(self):
        e = _record(self.m, errors=[], duration_seconds=119.9)
        self.assertEqual(e.status, STATUS_OK)

    def test_degraded_one_error(self):
        e = _record(self.m, errors=["some error"], duration_seconds=10.0)
        self.assertEqual(e.status, STATUS_DEGRADED)

    def test_degraded_duration_exactly_120(self):
        e = _record(self.m, errors=[], duration_seconds=120.0)
        self.assertEqual(e.status, STATUS_DEGRADED)

    def test_degraded_duration_between_120_and_300(self):
        e = _record(self.m, errors=[], duration_seconds=250.0)
        self.assertEqual(e.status, STATUS_DEGRADED)

    def test_failed_duration_exactly_300(self):
        e = _record(self.m, errors=[], duration_seconds=300.0)
        self.assertEqual(e.status, STATUS_FAILED)

    def test_failed_duration_above_300(self):
        e = _record(self.m, errors=[], duration_seconds=400.0)
        self.assertEqual(e.status, STATUS_FAILED)

    def test_failed_five_or_more_errors(self):
        errors = ["e1", "e2", "e3", "e4", "e5"]
        e = _record(self.m, errors=errors, duration_seconds=10.0)
        self.assertEqual(e.status, STATUS_FAILED)

    def test_failed_four_errors_not_failed(self):
        # 4 errors is still DEGRADED (threshold is >=5)
        errors = ["e1", "e2", "e3", "e4"]
        e = _record(self.m, errors=errors, duration_seconds=10.0)
        self.assertEqual(e.status, STATUS_DEGRADED)


# ---------------------------------------------------------------------------
# TestRecordCycle
# ---------------------------------------------------------------------------

class TestRecordCycle(unittest.TestCase):
    """6 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_returns_entry(self):
        e = _record(self.m)
        self.assertIsInstance(e, CycleHealthEntry)

    def test_entry_persisted(self):
        _record(self.m, cycle_id="C-persist")
        entries = self.m.get_recent_cycles(10)
        self.assertEqual(entries[-1].cycle_id, "C-persist")

    def test_multiple_entries_accumulate(self):
        for i in range(5):
            _record(self.m, cycle_id=f"C{i:03d}")
        entries = self.m.get_recent_cycles(10)
        self.assertEqual(len(entries), 5)

    def test_strategies_run_stored(self):
        e = _record(self.m, strategies_run=11)
        self.assertEqual(e.strategies_run, 11)

    def test_apy_snapshot_stored(self):
        snap = {"morpho": 6.5, "yearn": 5.1}
        e = _record(self.m, apy_snapshot=snap)
        self.assertIn("morpho", e.apy_snapshot)
        self.assertAlmostEqual(e.apy_snapshot["morpho"], 6.5)

    def test_negative_strategies_run_clamped(self):
        e = _record(self.m, strategies_run=-3)
        self.assertEqual(e.strategies_run, 0)


# ---------------------------------------------------------------------------
# TestGetRecentCycles
# ---------------------------------------------------------------------------

class TestGetRecentCycles(unittest.TestCase):
    """5 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_empty_returns_empty(self):
        result = self.m.get_recent_cycles(10)
        self.assertEqual(result, [])

    def test_returns_last_n(self):
        for i in range(15):
            _record(self.m, cycle_id=f"C{i:03d}")
        recent = self.m.get_recent_cycles(5)
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[-1].cycle_id, "C014")

    def test_n_larger_than_total(self):
        for i in range(3):
            _record(self.m, cycle_id=f"C{i:03d}")
        recent = self.m.get_recent_cycles(100)
        self.assertEqual(len(recent), 3)

    def test_n_equals_one(self):
        for i in range(5):
            _record(self.m, cycle_id=f"C{i:03d}")
        recent = self.m.get_recent_cycles(1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].cycle_id, "C004")

    def test_returns_cycle_health_entry_objects(self):
        _record(self.m)
        recent = self.m.get_recent_cycles(5)
        self.assertIsInstance(recent[0], CycleHealthEntry)


# ---------------------------------------------------------------------------
# TestComputeHealthScore
# ---------------------------------------------------------------------------

class TestComputeHealthScore(unittest.TestCase):
    """6 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_empty_returns_100(self):
        score = self.m.compute_health_score(10)
        self.assertAlmostEqual(score, 100.0)

    def test_all_ok_score_100(self):
        for _ in range(5):
            _record(self.m, errors=[], duration_seconds=30.0)
        score = self.m.compute_health_score(5)
        self.assertAlmostEqual(score, 100.0)

    def test_one_degraded_deducts_10(self):
        # 5 cycles: 4 OK + 1 DEGRADED
        for _ in range(4):
            _record(self.m, errors=[], duration_seconds=30.0)
        _record(self.m, errors=["err"], duration_seconds=30.0)
        score = self.m.compute_health_score(5)
        self.assertAlmostEqual(score, 90.0)

    def test_one_failed_deducts_30(self):
        for _ in range(4):
            _record(self.m, errors=[], duration_seconds=30.0)
        _record(self.m, errors=[], duration_seconds=350.0)
        score = self.m.compute_health_score(5)
        self.assertAlmostEqual(score, 70.0)

    def test_floor_at_zero(self):
        # 4 FAILEDs: 4*30 = 120 → score would be -20 → clamped to 0
        for _ in range(4):
            _record(self.m, errors=[], duration_seconds=350.0)
        score = self.m.compute_health_score(4)
        self.assertAlmostEqual(score, 0.0)

    def test_window_n_limits_lookback(self):
        # Record 10 cycles: first 5 OK, last 5 DEGRADED
        for _ in range(5):
            _record(self.m, errors=[], duration_seconds=30.0)
        for _ in range(5):
            _record(self.m, errors=["bad"], duration_seconds=30.0)
        # n=5 looks at last 5 (all DEGRADED): 100 - 5*10 = 50
        score = self.m.compute_health_score(5)
        self.assertAlmostEqual(score, 50.0)


# ---------------------------------------------------------------------------
# TestGetErrorFrequency
# ---------------------------------------------------------------------------

class TestGetErrorFrequency(unittest.TestCase):
    """4 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_empty_returns_empty_dict(self):
        freq = self.m.get_error_frequency(20)
        self.assertEqual(freq, {})

    def test_counts_errors_correctly(self):
        _record(self.m, errors=["adapter_timeout", "rpc_error"])
        _record(self.m, errors=["adapter_timeout"])
        _record(self.m, errors=["adapter_timeout", "rpc_error"])
        freq = self.m.get_error_frequency(10)
        self.assertEqual(freq["adapter_timeout"], 3)
        self.assertEqual(freq["rpc_error"], 2)

    def test_sorted_by_count_descending(self):
        _record(self.m, errors=["err_a"])
        _record(self.m, errors=["err_b", "err_b"])
        _record(self.m, errors=["err_c", "err_c", "err_c"])
        freq = self.m.get_error_frequency(10)
        keys = list(freq.keys())
        self.assertEqual(keys[0], "err_c")  # highest count first
        self.assertEqual(keys[-1], "err_a")

    def test_window_n_limits_frequency_lookback(self):
        # 5 cycles with "old_error", then 5 with "new_error"
        for _ in range(5):
            _record(self.m, errors=["old_error"])
        for _ in range(5):
            _record(self.m, errors=["new_error"])
        # n=5 → only last 5 cycles → only "new_error"
        freq = self.m.get_error_frequency(5)
        self.assertIn("new_error", freq)
        self.assertNotIn("old_error", freq)


# ---------------------------------------------------------------------------
# TestIsSystemHealthy
# ---------------------------------------------------------------------------

class TestIsSystemHealthy(unittest.TestCase):
    """3 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_empty_is_healthy(self):
        self.assertTrue(self.m.is_system_healthy(5))

    def test_all_ok_is_healthy(self):
        for _ in range(5):
            _record(self.m, errors=[], duration_seconds=30.0)
        self.assertTrue(self.m.is_system_healthy(5))

    def test_too_many_failed_is_not_healthy(self):
        # 3 FAILEDs out of 5: score = 100 - 3*30 = 10 < 70
        for _ in range(2):
            _record(self.m, errors=[], duration_seconds=30.0)
        for _ in range(3):
            _record(self.m, errors=[], duration_seconds=350.0)
        self.assertFalse(self.m.is_system_healthy(5))


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):
    """5 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_report_keys(self):
        report = self.m.generate_report()
        expected_keys = {
            "generated_at", "health_score", "is_healthy",
            "recent_summary", "error_frequency", "last_cycle", "advisory"
        }
        self.assertEqual(set(report.keys()), expected_keys)

    def test_no_entries_report(self):
        report = self.m.generate_report()
        self.assertAlmostEqual(report["health_score"], 100.0)
        self.assertTrue(report["is_healthy"])
        self.assertIsNone(report["last_cycle"])
        self.assertIn("No cycles", report["advisory"])

    def test_healthy_report(self):
        for _ in range(5):
            _record(self.m, errors=[], duration_seconds=30.0)
        report = self.m.generate_report()
        self.assertAlmostEqual(report["health_score"], 100.0)
        self.assertTrue(report["is_healthy"])
        self.assertIsNotNone(report["last_cycle"])

    def test_degraded_report_advisory(self):
        for _ in range(3):
            _record(self.m, errors=[], duration_seconds=350.0)  # FAILED
        report = self.m.generate_report()
        self.assertFalse(report["is_healthy"])
        self.assertIn("DEGRADED", report["advisory"])

    def test_recent_summary_counts(self):
        _record(self.m, errors=[], duration_seconds=30.0)       # OK
        _record(self.m, errors=["err"], duration_seconds=30.0)  # DEGRADED
        _record(self.m, errors=[], duration_seconds=350.0)       # FAILED
        report = self.m.generate_report()
        summary = report["recent_summary"]
        self.assertEqual(summary["OK"], 1)
        self.assertEqual(summary["DEGRADED"], 1)
        self.assertEqual(summary["FAILED"], 1)


# ---------------------------------------------------------------------------
# TestRingBuffer
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):
    """2 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_ring_buffer_max_100(self):
        for i in range(110):
            _record(self.m, cycle_id=f"C{i:04d}")
        entries = self.m.get_recent_cycles(200)
        self.assertLessEqual(len(entries), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(105):
            _record(self.m, cycle_id=f"C{i:04d}")
        entries = self.m.get_recent_cycles(200)
        last_cycle_id = entries[-1].cycle_id
        self.assertEqual(last_cycle_id, "C0104")


# ---------------------------------------------------------------------------
# TestAtomicWrite
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):
    """2 tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_log_file_valid_json(self):
        _record(self.m)
        log_path = Path(self.tmp) / _HEALTH_LOG_FILE
        self.assertTrue(log_path.exists())
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_no_tmp_files_left(self):
        _record(self.m)
        tmp_files = list(Path(self.tmp).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)


# ---------------------------------------------------------------------------
# TestComputeStatusEdgeCases (bonus tests to exceed 35)
# ---------------------------------------------------------------------------

class TestComputeStatusEdgeCases(unittest.TestCase):
    """5 bonus tests — total test count now 47."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_zero_duration_ok(self):
        e = _record(self.m, errors=[], duration_seconds=0.0)
        self.assertEqual(e.status, STATUS_OK)

    def test_empty_apy_snapshot(self):
        # Call record_cycle directly with an explicit empty snapshot
        e = self.m.record_cycle(
            cycle_id="C-empty-snap",
            strategies_run=5,
            adapters_polled=10,
            errors=[],
            duration_seconds=30.0,
            apy_snapshot={},
        )
        self.assertIsInstance(e.apy_snapshot, dict)
        self.assertEqual(len(e.apy_snapshot), 0)

    def test_health_score_mixed_all_statuses(self):
        # 1 OK, 1 DEGRADED, 1 FAILED in n=3: 100 - 10 - 30 = 60
        _record(self.m, errors=[], duration_seconds=30.0)
        _record(self.m, errors=["x"], duration_seconds=30.0)
        _record(self.m, errors=[], duration_seconds=301.0)
        score = self.m.compute_health_score(3)
        self.assertAlmostEqual(score, 60.0)

    def test_get_recent_n_minimum_one(self):
        for i in range(5):
            _record(self.m, cycle_id=f"C{i}")
        # n=0 should be treated as 1
        recent = self.m.get_recent_cycles(0)
        self.assertEqual(len(recent), 1)

    def test_get_error_frequency_n_minimum_one(self):
        _record(self.m, errors=["err_x"])
        freq = self.m.get_error_frequency(0)
        # Should not raise and return something meaningful
        self.assertIsInstance(freq, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ===========================================================================
# Tests for spa_core.monitoring.cycle_health_monitor  (P1-FIX-002 / AGENT-P0-003)
# ===========================================================================
# The analytics module above (spa_core.analytics.cycle_health_monitor) and the
# monitoring module (spa_core.monitoring.cycle_health_monitor) are separate
# implementations.  The monitoring module has zero pre-existing tests; this
# section brings coverage to 30+ new cases.
#
# Total test count across both sections: 47 + 30 = 77
# ===========================================================================

import unittest.mock as mock
from datetime import datetime as _dt, timezone as _tz, timedelta as _td

from spa_core.monitoring.cycle_health_monitor import (
    CycleHealthMonitor as MonCycleHealthMonitor,
    _load_equity_history,
    _load_last_cycle_ts,
    _load_json_list,
    _parse_iso,
    _now_epoch,
    HEALTH_FILE,
    OK as MON_OK,
    WARNING as MON_WARNING,
    CRITICAL as MON_CRITICAL,
    STALE as MON_STALE,
    HEALTHY as MON_HEALTHY,
    MAX_CYCLE_GAP_HOURS,
    CRITICAL_CYCLE_GAP_HOURS,
    MAX_EQUITY_DROP_PCT,
)


def _write_json(path: Path, data: object) -> None:
    """Helper: write JSON to a path (creates parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_equity_curve(
    tmp_dir: str,
    *,
    generated_at: "str | None" = "2099-01-01T08:00:00+00:00",
    n_bars: int = 2,
    equities: "list | None" = None,
) -> Path:
    """Write a minimal equity_curve_daily.json into tmp_dir/data/."""
    data_dir = Path(tmp_dir) / "data"
    data_dir.mkdir(exist_ok=True)
    if equities is None:
        equities = [100000.0 + i * 100 for i in range(n_bars)]
    daily = [
        {"date": f"2099-01-{i+1:02d}", "equity": e, "close_equity": e}
        for i, e in enumerate(equities)
    ]
    doc: dict = {"daily": daily}
    if generated_at is not None:
        doc["generated_at"] = generated_at
    path = data_dir / "equity_curve_daily.json"
    _write_json(path, doc)
    return data_dir


def _make_pts(tmp_dir: str, last_cycle_ts: str = "2099-01-01T08:00:00+00:00") -> Path:
    """Write a minimal paper_trading_status.json into tmp_dir/data/."""
    data_dir = Path(tmp_dir) / "data"
    data_dir.mkdir(exist_ok=True)
    pts = {"last_cycle_ts": last_cycle_ts, "current_equity": 100500.0}
    path = data_dir / "paper_trading_status.json"
    _write_json(path, pts)
    return data_dir


# ---------------------------------------------------------------------------
# TestParseIso (2 tests)
# ---------------------------------------------------------------------------

class TestParseIso(unittest.TestCase):
    """_parse_iso returns UTC-aware datetime for various formats."""

    def test_offset_aware_string(self):
        dt = _parse_iso("2026-06-20T14:33:10.479894+00:00")
        from datetime import timezone
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.year, 2026)

    def test_naive_string_treated_as_utc(self):
        from datetime import timezone
        dt = _parse_iso("2026-06-20T08:00:00")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 8)


# ---------------------------------------------------------------------------
# TestLoadLastCycleTs (3 tests)
# ---------------------------------------------------------------------------

class TestLoadLastCycleTs(unittest.TestCase):
    """_load_last_cycle_ts reads last_cycle_ts from paper_trading_status.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp) / "data"
        self.data_dir.mkdir()

    def test_returns_ts_when_present(self):
        _write_json(
            self.data_dir / "paper_trading_status.json",
            {"last_cycle_ts": "2099-01-01T08:00:00+00:00", "current_equity": 100000},
        )
        ts = _load_last_cycle_ts(self.data_dir)
        self.assertEqual(ts, "2099-01-01T08:00:00+00:00")

    def test_returns_none_when_file_missing(self):
        ts = _load_last_cycle_ts(self.data_dir)
        self.assertIsNone(ts)

    def test_returns_none_when_key_absent(self):
        _write_json(
            self.data_dir / "paper_trading_status.json",
            {"current_equity": 100000},
        )
        ts = _load_last_cycle_ts(self.data_dir)
        self.assertIsNone(ts)


# ---------------------------------------------------------------------------
# TestLoadEquityHistory (7 tests — fallback chain P1-FIX-002)
# ---------------------------------------------------------------------------

class TestLoadEquityHistory(unittest.TestCase):
    """_load_equity_history covers all 5 source-priority levels."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_uses_generated_at_when_present(self):
        data_dir = _make_equity_curve(
            self.tmp, generated_at="2099-06-01T08:00:00+00:00", n_bars=2
        )
        history = _load_equity_history(data_dir)
        self.assertEqual(history[-1]["timestamp"], "2099-06-01T08:00:00+00:00")

    def test_falls_back_to_pts_when_generated_at_missing(self):
        data_dir = _make_equity_curve(self.tmp, generated_at=None, n_bars=2)
        _write_json(
            data_dir / "paper_trading_status.json",
            {"last_cycle_ts": "2099-06-01T09:00:00+00:00"},
        )
        history = _load_equity_history(data_dir)
        self.assertEqual(history[-1]["timestamp"], "2099-06-01T09:00:00+00:00")

    def test_date_only_when_both_generated_at_and_pts_missing(self):
        data_dir = _make_equity_curve(self.tmp, generated_at=None, n_bars=1)
        # No paper_trading_status.json
        history = _load_equity_history(data_dir)
        self.assertEqual(len(history), 1)
        # No timestamp key — only date
        self.assertNotIn("timestamp", history[-1])
        self.assertIn("date", history[-1])

    def test_uses_pts_alone_when_curve_missing(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        _write_json(
            data_dir / "paper_trading_status.json",
            {"last_cycle_ts": "2099-06-01T10:00:00+00:00"},
        )
        history = _load_equity_history(data_dir)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["timestamp"], "2099-06-01T10:00:00+00:00")

    def test_legacy_equity_history_fallback(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        legacy = [
            {"date": "2026-06-12", "equity": 99000.0},
            {"date": "2026-06-13", "equity": 99100.0},
        ]
        _write_json(data_dir / "equity_history.json", legacy)
        history = _load_equity_history(data_dir)
        self.assertEqual(len(history), 2)
        self.assertAlmostEqual(history[-1]["equity"], 99100.0)

    def test_all_sources_missing_returns_empty(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        history = _load_equity_history(data_dir)
        self.assertEqual(history, [])

    def test_curve_with_malformed_bars_skipped(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        doc = {
            "generated_at": "2099-06-01T08:00:00+00:00",
            "daily": [
                "not-a-dict",
                {"date": "2099-06-01"},                # missing equity
                {"date": "2099-06-02", "equity": 100.0},  # valid
            ],
        }
        _write_json(data_dir / "equity_curve_daily.json", doc)
        history = _load_equity_history(data_dir)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["equity"], 100.0)


# ---------------------------------------------------------------------------
# TestMonCheckCycleGap (6 tests)
# ---------------------------------------------------------------------------

class TestMonCheckCycleGap(unittest.TestCase):
    """CycleHealthMonitor.check_cycle_gap status levels."""

    def setUp(self):
        self.m = MonCycleHealthMonitor()

    def _entry(self, hours_ago: float) -> dict:
        """Produce a history entry with a timestamp `hours_ago` hours in the past."""
        ts = (_dt.now(tz=_tz.utc) - _td(hours=hours_ago)).isoformat()
        return {"timestamp": ts, "equity": 100000.0}

    def test_empty_history_is_critical(self):
        result = self.m.check_cycle_gap([])
        self.assertEqual(result["status"], MON_CRITICAL)
        self.assertIsNone(result["last_cycle_at"])

    def test_recent_cycle_is_ok(self):
        result = self.m.check_cycle_gap([self._entry(0.5)])
        self.assertEqual(result["status"], MON_OK)

    def test_exactly_at_warning_boundary(self):
        # Just above MAX_CYCLE_GAP_HOURS → WARNING
        result = self.m.check_cycle_gap([self._entry(MAX_CYCLE_GAP_HOURS + 0.01)])
        self.assertEqual(result["status"], MON_WARNING)

    def test_above_critical_boundary(self):
        result = self.m.check_cycle_gap([self._entry(CRITICAL_CYCLE_GAP_HOURS + 0.1)])
        self.assertEqual(result["status"], MON_CRITICAL)

    def test_date_key_fallback_midnight_utc(self):
        # Entry with only "date" → midnight UTC → old enough to be CRITICAL
        old_date = (
            _dt.now(tz=_tz.utc) - _td(days=10)
        ).strftime("%Y-%m-%d")
        result = self.m.check_cycle_gap([{"date": old_date, "equity": 100000}])
        self.assertEqual(result["status"], MON_CRITICAL)

    def test_unparseable_timestamp_is_critical(self):
        result = self.m.check_cycle_gap([{"timestamp": "not-a-date", "equity": 0}])
        self.assertEqual(result["status"], MON_CRITICAL)


# ---------------------------------------------------------------------------
# TestMonCheckEquityAnomaly (5 tests)
# ---------------------------------------------------------------------------

class TestMonCheckEquityAnomaly(unittest.TestCase):
    """CycleHealthMonitor.check_equity_anomaly edge cases."""

    def setUp(self):
        self.m = MonCycleHealthMonitor()

    def test_no_drop_is_ok(self):
        history = [
            {"equity": 100000.0},
            {"equity": 100100.0},
        ]
        result = self.m.check_equity_anomaly(history)
        self.assertEqual(result["status"], MON_OK)

    def test_drop_above_threshold_is_warning(self):
        drop_pct = MAX_EQUITY_DROP_PCT + 1.0
        prev = 100000.0
        curr = prev * (1 - drop_pct / 100)
        result = self.m.check_equity_anomaly(
            [{"equity": prev}, {"equity": curr}]
        )
        self.assertEqual(result["status"], MON_WARNING)
        self.assertLess(result["today_change_pct"], -MAX_EQUITY_DROP_PCT)

    def test_single_entry_insufficient(self):
        result = self.m.check_equity_anomaly([{"equity": 100000.0}])
        self.assertEqual(result["status"], MON_OK)
        self.assertIn("insufficient", result.get("detail", ""))

    def test_empty_history_ok_with_detail(self):
        result = self.m.check_equity_anomaly([])
        self.assertEqual(result["status"], MON_OK)

    def test_zero_prev_equity_no_crash(self):
        result = self.m.check_equity_anomaly(
            [{"equity": 0.0}, {"equity": 100.0}]
        )
        # Should return gracefully (detail set, no ZeroDivisionError)
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)


# ---------------------------------------------------------------------------
# TestMonCheckDataFreshness (4 tests)
# ---------------------------------------------------------------------------

class TestMonCheckDataFreshness(unittest.TestCase):
    """CycleHealthMonitor.check_data_freshness — fresh, stale, missing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = MonCycleHealthMonitor()

    def test_fresh_files_ok(self):
        import time
        data_dir = Path(self.tmp)
        for fname in ("market_regime.json", "adapter_status.json", "tournament_ranking.json"):
            (data_dir / fname).write_text("{}", encoding="utf-8")
        result = self.m.check_data_freshness(data_dir=str(data_dir))
        self.assertEqual(result["status"], MON_OK)
        self.assertEqual(result["stale_files"], [])

    def test_missing_file_reported(self):
        data_dir = Path(self.tmp)
        result = self.m.check_data_freshness(data_dir=str(data_dir))
        self.assertIn("market_regime.json", result["missing_files"])

    def test_stale_file_sets_stale_status(self):
        import time
        data_dir = Path(self.tmp)
        mr = data_dir / "market_regime.json"
        mr.write_text("{}", encoding="utf-8")
        # Back-date mtime by 5 hours (threshold is 4h → STALE)
        old_time = time.time() - 5 * 3600
        os.utime(str(mr), (old_time, old_time))
        result = self.m.check_data_freshness(data_dir=str(data_dir))
        self.assertEqual(result["status"], MON_STALE)
        stale_names = [e["file"] for e in result["stale_files"]]
        self.assertIn("market_regime.json", stale_names)

    def test_result_keys_present(self):
        result = self.m.check_data_freshness(data_dir=self.tmp)
        for key in ("status", "stale_files", "fresh_files", "missing_files"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# TestMonRunAllChecks (4 tests)
# ---------------------------------------------------------------------------

class TestMonRunAllChecks(unittest.TestCase):
    """CycleHealthMonitor.run_all_checks integration."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = MonCycleHealthMonitor()

    def test_healthy_when_equity_curve_fresh(self):
        data_dir = _make_equity_curve(
            self.tmp,
            generated_at=_dt.now(tz=_tz.utc).isoformat(),
            n_bars=2,
        )
        # Write watched files so data_freshness passes
        for fname in ("market_regime.json", "adapter_status.json", "tournament_ranking.json"):
            (data_dir / fname).write_text("{}", encoding="utf-8")
        report = self.m.run_all_checks(data_dir=str(data_dir))
        self.assertIn(report["overall"], (MON_HEALTHY, MON_WARNING))
        self.assertIn("checks", report)
        self.assertIn("checked_at", report)

    def test_critical_when_no_equity_data(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        report = self.m.run_all_checks(data_dir=str(data_dir))
        self.assertEqual(report["overall"], MON_CRITICAL)

    def test_recommendations_not_empty(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        report = self.m.run_all_checks(data_dir=str(data_dir))
        self.assertIsInstance(report["recommendations"], list)
        self.assertGreater(len(report["recommendations"]), 0)

    def test_pts_fallback_cycle_gap_ok(self):
        """When equity_curve_daily.json is absent, pts last_cycle_ts keeps gap OK."""
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        now_iso = _dt.now(tz=_tz.utc).isoformat()
        _write_json(data_dir / "paper_trading_status.json", {"last_cycle_ts": now_iso})
        report = self.m.run_all_checks(data_dir=str(data_dir))
        cycle_gap = report["checks"]["cycle_gap"]
        self.assertEqual(cycle_gap["status"], MON_OK)


# ---------------------------------------------------------------------------
# TestMonSaveHealthReport (4 tests)
# ---------------------------------------------------------------------------

class TestMonSaveHealthReport(unittest.TestCase):
    """CycleHealthMonitor.save_health_report — atomic write guarantees."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = MonCycleHealthMonitor()

    def test_writes_cycle_health_json(self):
        report = {"overall": "HEALTHY", "checked_at": "2099-01-01T00:00:00+00:00"}
        self.m.save_health_report(report, data_dir=self.tmp)
        out = Path(self.tmp) / HEALTH_FILE
        self.assertTrue(out.exists())

    def test_content_is_valid_json(self):
        report = {"overall": "HEALTHY", "checks": {}, "checked_at": "t"}
        self.m.save_health_report(report, data_dir=self.tmp)
        content = (Path(self.tmp) / HEALTH_FILE).read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertEqual(parsed["overall"], "HEALTHY")

    def test_no_tmp_file_left_after_write(self):
        report = {"overall": "HEALTHY"}
        self.m.save_health_report(report, data_dir=self.tmp)
        tmp_files = list(Path(self.tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_overwrite_updates_content(self):
        self.m.save_health_report({"overall": "HEALTHY"}, data_dir=self.tmp)
        self.m.save_health_report({"overall": "CRITICAL"}, data_dir=self.tmp)
        content = json.loads(
            (Path(self.tmp) / HEALTH_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(content["overall"], "CRITICAL")
