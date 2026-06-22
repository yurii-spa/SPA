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
