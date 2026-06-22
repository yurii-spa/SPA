"""MP-144 / AGENT-P0-006: Unit tests for cycle_gap_monitor.py.

Covers:
- Gap detection thresholds (24h, 26h, 48h)
- No gap when cycle is recent (<26h)
- Deduplication (same day = no second alert)
- State file atomicity (no .tmp files left behind)
- Missing/null last_cycle_ts handling
- CLI --check flag (dry-run, no writes)
- Never-raise guarantee (corrupt JSON, missing files)
- Return dict structure validation
- Telegram send mocking
- Heartbeat guarantee (AGENT-P0-006): cycle_gap_state.json written on EVERY
  run (even when no gap), so external tools can verify the monitor is alive.

Run::

    python3 -m unittest discover -s spa_core/tests -p "test_cycle_gap_monitor.py" -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from spa_core.paper_trading.cycle_gap_monitor import (
    GAP_THRESHOLD_HOURS,
    GAP_STATE_FILENAME,
    STATUS_FILENAME,
    CYCLE_LOG_FILENAME,
    _UNKNOWN_HOURS,
    _atomic_write_json,
    _build_heartbeat_state,
    _compute_days_to_golive,
    _compute_paper_days,
    _format_alert_message,
    _get_last_cycle_ts,
    _parse_iso,
    _read_json,
    _should_send_alert,
    _updated_gap_state,
    detect_gap,
    main,
    run_cycle_gap_monitor,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utc(year, month, day, hour=12, minute=0, second=0) -> datetime:
    """Construct a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _make_ts(dt: datetime) -> str:
    """Format datetime as ISO-8601 string."""
    return dt.isoformat()


def _write_json_file(path: Path, obj) -> None:
    """Write JSON file directly (for test setup)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _read_state(ddir: Path) -> dict:
    """Load cycle_gap_state.json from ddir."""
    path = ddir / GAP_STATE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Category 1: detect_gap() ─────────────────────────────────────────────────

class TestDetectGap(unittest.TestCase):
    """Tests for the detect_gap() pure function."""

    def test_no_gap_recent_2h(self):
        """Cycle ran 2h ago — no gap."""
        now = _utc(2026, 6, 12, 12)
        last_ts = _make_ts(_utc(2026, 6, 12, 10))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertFalse(gap)
        self.assertAlmostEqual(hours, 2.0, places=1)

    def test_no_gap_recent_24h(self):
        """Cycle ran exactly 24h ago — still under threshold."""
        now = _utc(2026, 6, 12, 12)
        last_ts = _make_ts(_utc(2026, 6, 11, 12))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertFalse(gap)
        self.assertAlmostEqual(hours, 24.0, places=1)

    def test_no_gap_at_exact_threshold_26h(self):
        """Exactly 26h — boundary is exclusive (> not >=)."""
        now = _utc(2026, 6, 12, 12)
        last_ts = _make_ts(_utc(2026, 6, 11, 10))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertAlmostEqual(hours, 26.0, places=4)
        self.assertFalse(gap)  # 26.0 is not > 26.0

    def test_gap_at_26_1h(self):
        """26.1h after 10:00 UTC — gap detected."""
        now = _utc(2026, 6, 12, 12, 6)  # 12:06 UTC
        last_ts = _make_ts(_utc(2026, 6, 11, 10, 0))  # 10:00 yesterday = 26.1h ago
        gap, hours = detect_gap(last_ts, now=now)
        self.assertTrue(gap)
        self.assertGreater(hours, 26.0)

    def test_gap_at_48h(self):
        """48h gap detected when hour >= 10."""
        now = _utc(2026, 6, 13, 11)
        last_ts = _make_ts(_utc(2026, 6, 11, 11))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertTrue(gap)
        self.assertAlmostEqual(hours, 48.0, places=1)

    def test_no_gap_time_condition_not_met_hour_9(self):
        """26.1h gap but UTC hour is 9 — no alert yet."""
        now = _utc(2026, 6, 12, 9, 6)  # 09:06 UTC
        # 2026-06-11 07:00 → 2026-06-12 09:06 = 26h 6min = 26.1h
        last_ts = _make_ts(_utc(2026, 6, 11, 7, 0))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertFalse(gap)
        self.assertGreater(hours, GAP_THRESHOLD_HOURS)

    def test_no_gap_time_condition_not_met_hour_0(self):
        """48h gap but it is midnight UTC — no alert."""
        now = _utc(2026, 6, 13, 0)
        last_ts = _make_ts(_utc(2026, 6, 11, 0))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertFalse(gap)

    def test_gap_at_exactly_alert_hour_10(self):
        """Hour == 10 is allowed (>= check), 27h gap → gap detected."""
        now = _utc(2026, 6, 12, 10, 0)
        last_ts = _make_ts(_utc(2026, 6, 11, 7, 0))  # 27h ago
        gap, hours = detect_gap(last_ts, now=now)
        self.assertTrue(gap)

    def test_null_ts_gap_when_hour_ge_10(self):
        """None timestamp + hour >= 10 → gap detected with sentinel hours."""
        now = _utc(2026, 6, 12, 11)
        gap, hours = detect_gap(None, now=now)
        self.assertTrue(gap)
        self.assertEqual(hours, _UNKNOWN_HOURS)

    def test_null_ts_no_gap_when_hour_lt_10(self):
        """None timestamp + hour < 10 → no gap yet."""
        now = _utc(2026, 6, 12, 9)
        gap, hours = detect_gap(None, now=now)
        self.assertFalse(gap)
        self.assertEqual(hours, _UNKNOWN_HOURS)

    def test_unparseable_ts_treated_as_unknown(self):
        """Garbage timestamp → sentinel hours → gap if hour >= 10."""
        now = _utc(2026, 6, 12, 11)
        gap, hours = detect_gap("not-a-date", now=now)
        self.assertTrue(gap)
        self.assertEqual(hours, _UNKNOWN_HOURS)

    def test_large_gap_100h(self):
        """100h gap → definitely detected."""
        now = _utc(2026, 6, 16, 12)
        last_ts = _make_ts(_utc(2026, 6, 12, 12))
        gap, hours = detect_gap(last_ts, now=now)
        self.assertTrue(gap)
        self.assertAlmostEqual(hours, 96.0, places=0)  # 4 days

    def test_returns_tuple_two_elements(self):
        """detect_gap always returns a 2-tuple."""
        now = _utc(2026, 6, 12, 11)
        result = detect_gap(None, now=now)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


# ─── Category 2: _get_last_cycle_ts() ────────────────────────────────────────

class TestGetLastCycleTs(unittest.TestCase):
    """Tests for resolving last_cycle_ts from data files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)

    def test_reads_from_status_file(self):
        """last_cycle_ts from paper_trading_status.json is returned."""
        ts = "2026-06-12T08:00:00+00:00"
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": ts, "is_demo": False},
        )
        result = _get_last_cycle_ts(self.ddir)
        self.assertEqual(result, ts)

    def test_fallback_to_cycle_log(self):
        """Falls back to cycle_log.json when status has no last_cycle_ts."""
        ts = "2026-06-11T08:00:00+00:00"
        _write_json_file(self.ddir / STATUS_FILENAME, {"is_demo": False})
        _write_json_file(
            self.ddir / CYCLE_LOG_FILENAME,
            [{"ts": ts, "status": "ok"}],
        )
        result = _get_last_cycle_ts(self.ddir)
        self.assertEqual(result, ts)

    def test_returns_none_if_both_missing(self):
        """Returns None when neither status nor cycle_log file exists."""
        result = _get_last_cycle_ts(self.ddir)
        self.assertIsNone(result)

    def test_returns_none_if_last_cycle_ts_null(self):
        """Returns None if last_cycle_ts field is null."""
        _write_json_file(
            self.ddir / STATUS_FILENAME, {"last_cycle_ts": None}
        )
        result = _get_last_cycle_ts(self.ddir)
        self.assertIsNone(result)

    def test_handles_corrupt_status_json(self):
        """Corrupt status.json → falls back to cycle_log gracefully."""
        (self.ddir / STATUS_FILENAME).write_text("NOT JSON", encoding="utf-8")
        result = _get_last_cycle_ts(self.ddir)
        self.assertIsNone(result)

    def test_cycle_log_uses_timestamp_field(self):
        """Falls back to 'timestamp' key if 'ts' is absent."""
        ts = "2026-06-11T09:00:00+00:00"
        _write_json_file(self.ddir / STATUS_FILENAME, {})
        _write_json_file(
            self.ddir / CYCLE_LOG_FILENAME,
            [{"timestamp": ts, "status": "ok"}],
        )
        result = _get_last_cycle_ts(self.ddir)
        self.assertEqual(result, ts)


# ─── Category 3: Deduplication helpers ───────────────────────────────────────

class TestDeduplication(unittest.TestCase):
    """Tests for alert deduplication logic."""

    def test_should_send_when_no_previous_alert(self):
        self.assertTrue(_should_send_alert({}, "2026-06-12"))

    def test_should_not_send_on_same_day(self):
        state = {"last_alert_date": "2026-06-12"}
        self.assertFalse(_should_send_alert(state, "2026-06-12"))

    def test_should_send_on_different_day(self):
        state = {"last_alert_date": "2026-06-11"}
        self.assertTrue(_should_send_alert(state, "2026-06-12"))

    def test_updated_gap_state_sets_date(self):
        state = {}
        updated = _updated_gap_state(state, today="2026-06-12", now_ts="2026-06-12T11:00:00+00:00")
        self.assertEqual(updated["last_alert_date"], "2026-06-12")

    def test_updated_gap_state_sets_ts(self):
        state = {}
        ts = "2026-06-12T11:00:00+00:00"
        updated = _updated_gap_state(state, today="2026-06-12", now_ts=ts)
        self.assertEqual(updated["last_alert_ts"], ts)

    def test_updated_gap_state_preserves_other_keys(self):
        state = {"some_other_key": 42}
        updated = _updated_gap_state(state, today="2026-06-12", now_ts="ts")
        self.assertEqual(updated["some_other_key"], 42)


# ─── Category 4: _atomic_write_json() ────────────────────────────────────────

class TestAtomicWriteJson(unittest.TestCase):
    """Tests for the atomic JSON writer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)

    def test_creates_file(self):
        path = self.ddir / "test.json"
        _atomic_write_json(path, {"key": "value"})
        self.assertTrue(path.exists())

    def test_no_tmp_files_left(self):
        path = self.ddir / "test.json"
        _atomic_write_json(path, {"a": 1})
        tmp_files = list(self.ddir.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No .tmp files should remain after atomic write")

    def test_content_is_valid_json(self):
        path = self.ddir / "test.json"
        obj = {"x": 1, "y": [1, 2, 3]}
        _atomic_write_json(path, obj)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded, obj)

    def test_overwrites_existing_file(self):
        path = self.ddir / "test.json"
        _atomic_write_json(path, {"v": 1})
        _atomic_write_json(path, {"v": 2})
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["v"], 2)

    def test_creates_parent_directory(self):
        path = self.ddir / "subdir" / "deep" / "test.json"
        _atomic_write_json(path, {"ok": True})
        self.assertTrue(path.exists())


# ─── Category 5: Return dict structure ───────────────────────────────────────

class TestReturnDictStructure(unittest.TestCase):
    """run_cycle_gap_monitor always returns the correct dict shape."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)
        # Write a fresh status so there is no gap
        now = datetime.now(timezone.utc)
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": now.isoformat(), "is_demo": False},
        )

    def test_returns_dict(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIsInstance(result, dict)

    def test_has_gap_detected_key(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIn("gap_detected", result)

    def test_has_hours_since_key(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIn("hours_since", result)

    def test_has_alert_sent_key(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIn("alert_sent", result)

    def test_gap_detected_is_bool(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIsInstance(result["gap_detected"], bool)

    def test_hours_since_is_float(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIsInstance(result["hours_since"], float)

    def test_alert_sent_is_bool(self):
        result = run_cycle_gap_monitor(data_dir=self.ddir)
        self.assertIsInstance(result["alert_sent"], bool)


# ─── Category 6: run_cycle_gap_monitor() behavior ────────────────────────────

class TestRunCycleGapMonitorBehavior(unittest.TestCase):
    """Integration-style tests for the main entry point."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)

    def _recent_ts(self, hours_ago: float = 1.0) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

    def _old_ts(self, hours_ago: float = 30.0) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

    def test_no_gap_when_cycle_recent(self):
        """Recent last_cycle_ts → gap_detected=False, alert_sent=False."""
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": self._recent_ts(1.0)},
        )
        now = datetime.now(timezone.utc).replace(hour=12)
        result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertFalse(result["gap_detected"])
        self.assertFalse(result["alert_sent"])

    def test_gap_detected_when_old_cycle(self):
        """Old last_cycle_ts (30h) + hour>=10 → gap_detected=True."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ):
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertTrue(result["gap_detected"])

    def test_alert_sent_when_telegram_succeeds(self):
        """Gap + fresh day + Telegram OK → alert_sent=True."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ):
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertTrue(result["alert_sent"])

    def test_alert_not_sent_when_telegram_fails(self):
        """Gap + Telegram fails → alert_sent=False."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=False,
        ):
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertFalse(result["alert_sent"])

    def test_deduplication_prevents_second_alert_same_day(self):
        """Second call on same day → alert_sent=False (already alerted)."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        today = "2026-06-12"
        _write_json_file(
            self.ddir / GAP_STATE_FILENAME,
            {"last_alert_date": today},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ) as mock_send:
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        mock_send.assert_not_called()
        self.assertFalse(result["alert_sent"])

    def test_dry_run_no_telegram_call(self):
        """dry_run=True → Telegram is never called even if gap detected."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ) as mock_send:
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now, dry_run=True)
        mock_send.assert_not_called()
        self.assertTrue(result["gap_detected"])
        self.assertFalse(result["alert_sent"])

    def test_state_written_after_successful_alert(self):
        """Gap state file is written after a successful Telegram send."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state_path = self.ddir / GAP_STATE_FILENAME
        self.assertTrue(state_path.exists())
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state.get("last_alert_date"), "2026-06-12")

    def test_state_written_even_when_telegram_fails(self):
        """Heartbeat is written even when Telegram delivery fails (AGENT-P0-006)."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=False,
        ):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state_path = self.ddir / GAP_STATE_FILENAME
        self.assertTrue(state_path.exists(), "State must be written even when telegram fails")
        state = _read_state(self.ddir)
        self.assertIn("last_check_ts", state)

    def test_never_raises_corrupt_status_json(self):
        """Corrupt status JSON → result returned, no exception raised."""
        (self.ddir / STATUS_FILENAME).write_text("{{INVALID", encoding="utf-8")
        now = _utc(2026, 6, 12, 12)
        try:
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"run_cycle_gap_monitor raised unexpectedly: {exc}")
        self.assertIn("gap_detected", result)

    def test_never_raises_missing_data_dir(self):
        """Completely absent data directory → no exception raised."""
        missing_dir = Path(self.tmpdir) / "nonexistent"
        now = _utc(2026, 6, 12, 12)
        try:
            result = run_cycle_gap_monitor(data_dir=missing_dir, now=now)
        except Exception as exc:
            self.fail(f"run_cycle_gap_monitor raised unexpectedly: {exc}")
        self.assertIn("gap_detected", result)

    def test_hours_since_approximately_correct(self):
        """hours_since in result is close to the actual elapsed hours."""
        now = _utc(2026, 6, 12, 12)
        elapsed = 30.0
        last_ts = (now - timedelta(hours=elapsed)).isoformat()
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": last_ts})
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ):
            result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertAlmostEqual(result["hours_since"], elapsed, delta=0.1)

    def test_never_raises_corrupt_gap_state(self):
        """Corrupt gap_state.json → no exception, still detects gap."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        (self.ddir / GAP_STATE_FILENAME).write_text("NOT JSON", encoding="utf-8")
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ):
            try:
                result = run_cycle_gap_monitor(data_dir=self.ddir, now=now)
            except Exception as exc:
                self.fail(f"run_cycle_gap_monitor raised: {exc}")
        self.assertTrue(result["gap_detected"])


# ─── Category 7: CLI --check flag ────────────────────────────────────────────

class TestCLICheck(unittest.TestCase):
    """Tests that --check is a true dry-run (no writes, no sends)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)

    def test_cli_check_no_state_file_written(self):
        """--check must not write cycle_gap_state.json even if gap exists."""
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": old_ts},
        )
        with patch(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
            return_value=True,
        ) as mock_send:
            try:
                main(["--check", "--data-dir", str(self.ddir)])
            except SystemExit:
                pass
        mock_send.assert_not_called()
        self.assertFalse((self.ddir / GAP_STATE_FILENAME).exists())

    def test_cli_check_does_not_crash_missing_dir(self):
        """--check with a non-existent directory must not crash."""
        missing = Path(self.tmpdir) / "nowhere"
        try:
            main(["--check", "--data-dir", str(missing)])
        except SystemExit:
            pass
        except Exception as exc:
            self.fail(f"CLI --check raised unexpectedly: {exc}")

    def test_cli_check_produces_output(self, capsys=None):
        """--check prints something to stdout (basic smoke test)."""
        import io
        import sys
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            main(["--check", "--data-dir", str(self.ddir)])
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        self.assertIn("Cycle Gap Monitor", output)

    def test_cli_no_args_writes_heartbeat(self):
        """Running without --check writes heartbeat file (AGENT-P0-006)."""
        _write_json_file(
            self.ddir / STATUS_FILENAME,
            {"last_cycle_ts": datetime.now(timezone.utc).isoformat()},
        )
        import io
        import sys
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            main(["--data-dir", str(self.ddir)])
        except SystemExit:
            pass
        except Exception as exc:
            self.fail(f"main() raised unexpectedly: {exc}")
        finally:
            sys.stdout = old_stdout
        # Heartbeat must have been written
        state_path = self.ddir / GAP_STATE_FILENAME
        self.assertTrue(state_path.exists(), "Heartbeat state must be written on default run")


# ─── Category 8: Helper functions ────────────────────────────────────────────

class TestHelperFunctions(unittest.TestCase):
    """Tests for utility/helper functions."""

    def test_parse_iso_utc(self):
        dt = _parse_iso("2026-06-12T08:00:00+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 8)

    def test_parse_iso_z_suffix(self):
        dt = _parse_iso("2026-06-12T08:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_invalid(self):
        self.assertIsNone(_parse_iso("not-a-date"))

    def test_parse_iso_empty_string(self):
        self.assertIsNone(_parse_iso(""))

    def test_format_alert_message_contains_hours(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertIn("28.5h ago", msg)

    def test_format_alert_message_contains_golive(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 3, 33)
        self.assertIn("go-live 33d", msg)

    def test_format_alert_message_contains_day(self):
        msg = _format_alert_message("2026-06-11T08:00:00Z", 28.5, 7, 33)
        self.assertIn("Day 7", msg)

    def test_compute_paper_days_basic(self):
        status = {"paper_start_date": "2026-06-10"}
        now = _utc(2026, 6, 12)
        days = _compute_paper_days(status, now)
        self.assertEqual(days, 3)  # day 1=10, day 2=11, day 3=12

    def test_compute_paper_days_invalid_date_fallback(self):
        status = {"paper_start_date": "not-a-date", "days_running": 5}
        days = _compute_paper_days(status, _utc(2026, 6, 12))
        self.assertEqual(days, 5)

    def test_compute_days_to_golive_in_future(self):
        now = _utc(2026, 6, 12)
        days = _compute_days_to_golive(now)
        self.assertGreater(days, 0)

    def test_compute_days_to_golive_past_returns_zero(self):
        now = _utc(2026, 8, 1)  # after golive date
        days = _compute_days_to_golive(now)
        self.assertEqual(days, 0)

    def test_read_json_missing_file(self):
        path = Path("/tmp/nonexistent_spa_test_xyz.json")
        result = _read_json(path, {"default": True})
        self.assertEqual(result, {"default": True})

    def test_read_json_corrupt_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            f.write("INVALID")
            fname = f.name
        try:
            result = _read_json(Path(fname), "fallback")
            self.assertEqual(result, "fallback")
        finally:
            os.unlink(fname)


# ─── Category 9: Heartbeat guarantee (AGENT-P0-006) ──────────────────────────

class TestHeartbeatGuarantee(unittest.TestCase):
    """AGENT-P0-006: cycle_gap_state.json must be written on EVERY run.

    Even when no gap is detected the file must exist so that GoLiveChecker
    and dashboards can confirm the monitor is alive.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ddir = Path(self.tmpdir)

    def _recent_ts(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

    def _old_ts(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()

    # ── No-gap path ────────────────────────────────────────────────────────

    def test_heartbeat_created_when_no_gap(self):
        """State file must be CREATED even when cycle is healthy (no gap)."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertTrue(
            (self.ddir / GAP_STATE_FILENAME).exists(),
            "cycle_gap_state.json must be written even when no gap detected",
        )

    def test_heartbeat_no_gap_has_last_check_ts(self):
        """Heartbeat written on no-gap path contains last_check_ts."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertIn("last_check_ts", state)

    def test_heartbeat_no_gap_gap_detected_is_false(self):
        """Heartbeat written on no-gap path has gap_detected=False."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertFalse(state["gap_detected"])

    def test_heartbeat_no_gap_alert_sent_is_false(self):
        """Heartbeat written on no-gap path has alert_sent=False."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertFalse(state["alert_sent"])

    def test_heartbeat_no_gap_preserves_last_alert_date(self):
        """No-gap heartbeat preserves existing last_alert_date for dedup."""
        existing = {"last_alert_date": "2026-06-11", "last_alert_ts": "ts-prev"}
        _write_json_file(self.ddir / GAP_STATE_FILENAME, existing)
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertEqual(state.get("last_alert_date"), "2026-06-11",
                         "last_alert_date must be preserved across no-gap heartbeat writes")

    def test_heartbeat_no_gap_hours_since_correct(self):
        """Heartbeat has hours_since reflecting actual elapsed time."""
        now = _utc(2026, 6, 12, 12)
        last_dt = now - timedelta(hours=5)
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": last_dt.isoformat()})
        run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertAlmostEqual(state["hours_since"], 5.0, delta=0.1)

    # ── Already-alerted-today (dedup) path ────────────────────────────────

    def test_heartbeat_written_when_already_alerted_today(self):
        """Heartbeat written even when dedup suppresses a second alert."""
        today = "2026-06-12"
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / GAP_STATE_FILENAME,
            {"last_alert_date": today, "last_alert_ts": "prev-ts"},
        )
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=True) as mock_send:
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        mock_send.assert_not_called()
        state = _read_state(self.ddir)
        self.assertIn("last_check_ts", state,
                      "Heartbeat must include last_check_ts even in dedup path")

    def test_heartbeat_dedup_path_gap_detected_is_true(self):
        """Heartbeat in dedup path records gap_detected=True."""
        today = "2026-06-12"
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(self.ddir / GAP_STATE_FILENAME, {"last_alert_date": today})
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=True):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertTrue(state["gap_detected"])

    def test_heartbeat_dedup_path_preserves_last_alert_date(self):
        """Heartbeat in dedup path does NOT overwrite last_alert_date."""
        today = "2026-06-12"
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(
            self.ddir / GAP_STATE_FILENAME,
            {"last_alert_date": today, "last_alert_ts": "orig-ts"},
        )
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=True):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        self.assertEqual(state.get("last_alert_date"), today)
        self.assertEqual(state.get("last_alert_ts"), "orig-ts")

    # ── Telegram-failed path ──────────────────────────────────────────────

    def test_heartbeat_written_when_telegram_fails(self):
        """State file is written even when Telegram send returns False."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=False):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        self.assertTrue((self.ddir / GAP_STATE_FILENAME).exists())
        state = _read_state(self.ddir)
        self.assertIn("last_check_ts", state)
        self.assertFalse(state["alert_sent"])

    def test_heartbeat_telegram_fail_does_not_update_last_alert_date(self):
        """When Telegram fails, last_alert_date dedup state is NOT advanced."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=False):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now)
        state = _read_state(self.ddir)
        # last_alert_date should NOT be set to today because no alert was sent
        self.assertNotEqual(state.get("last_alert_date"), "2026-06-12",
                            "Telegram failure must not advance last_alert_date dedup field")

    # ── dry_run must NOT write ─────────────────────────────────────────────

    def test_dry_run_does_not_write_heartbeat_no_gap(self):
        """dry_run=True must not write state even in no-gap path."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})
        now = datetime.now(timezone.utc).replace(hour=12)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now, dry_run=True)
        self.assertFalse(
            (self.ddir / GAP_STATE_FILENAME).exists(),
            "dry_run=True must never write cycle_gap_state.json",
        )

    def test_dry_run_does_not_write_heartbeat_gap_detected(self):
        """dry_run=True must not write state even when gap is detected."""
        now = _utc(2026, 6, 12, 12)
        old_ts = (now - timedelta(hours=30)).isoformat()
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": old_ts})
        with patch("spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert",
                   return_value=True):
            run_cycle_gap_monitor(data_dir=self.ddir, now=now, dry_run=True)
        self.assertFalse(
            (self.ddir / GAP_STATE_FILENAME).exists(),
            "dry_run=True must never write cycle_gap_state.json (gap path)",
        )

    # ── _build_heartbeat_state() unit tests ───────────────────────────────

    def test_build_heartbeat_state_sets_last_check_ts(self):
        """_build_heartbeat_state() always sets last_check_ts."""
        state = _build_heartbeat_state(
            {}, gap_detected=False, hours_since=2.0, alert_sent=False,
            now_ts="2026-06-12T12:00:00+00:00",
        )
        self.assertEqual(state["last_check_ts"], "2026-06-12T12:00:00+00:00")

    def test_build_heartbeat_state_sets_gap_detected(self):
        state = _build_heartbeat_state(
            {}, gap_detected=True, hours_since=30.0, alert_sent=False,
            now_ts="ts",
        )
        self.assertTrue(state["gap_detected"])

    def test_build_heartbeat_state_sets_hours_since(self):
        state = _build_heartbeat_state(
            {}, gap_detected=False, hours_since=5.5, alert_sent=False,
            now_ts="ts",
        )
        self.assertAlmostEqual(state["hours_since"], 5.5, places=2)

    def test_build_heartbeat_state_sets_alert_sent(self):
        state = _build_heartbeat_state(
            {}, gap_detected=True, hours_since=30.0, alert_sent=True,
            now_ts="ts",
        )
        self.assertTrue(state["alert_sent"])

    def test_build_heartbeat_state_preserves_existing_alert_dedup(self):
        existing = {"last_alert_date": "2026-06-10", "last_alert_ts": "some-ts"}
        state = _build_heartbeat_state(
            existing, gap_detected=False, hours_since=1.0, alert_sent=False,
            now_ts="ts",
        )
        self.assertEqual(state["last_alert_date"], "2026-06-10")
        self.assertEqual(state["last_alert_ts"], "some-ts")

    def test_build_heartbeat_state_does_not_mutate_existing(self):
        """_build_heartbeat_state must not mutate the input dict."""
        original = {"last_alert_date": "2026-06-10"}
        _ = _build_heartbeat_state(
            original, gap_detected=False, hours_since=1.0, alert_sent=False,
            now_ts="ts",
        )
        self.assertNotIn("last_check_ts", original, "Input dict must not be mutated")

    def test_build_heartbeat_state_hours_since_rounded(self):
        """hours_since is stored rounded to 2 decimal places."""
        state = _build_heartbeat_state(
            {}, gap_detected=False, hours_since=3.14159, alert_sent=False,
            now_ts="ts",
        )
        self.assertEqual(state["hours_since"], 3.14)

    # ── Successive runs update last_check_ts ──────────────────────────────

    def test_heartbeat_last_check_ts_updates_on_each_run(self):
        """Successive runs with no gap each update last_check_ts."""
        _write_json_file(self.ddir / STATUS_FILENAME, {"last_cycle_ts": self._recent_ts()})

        now1 = _utc(2026, 6, 12, 10)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now1)
        ts1 = _read_state(self.ddir)["last_check_ts"]

        now2 = _utc(2026, 6, 12, 11)
        run_cycle_gap_monitor(data_dir=self.ddir, now=now2)
        ts2 = _read_state(self.ddir)["last_check_ts"]

        self.assertNotEqual(ts1, ts2, "last_check_ts must advance on each run")
        self.assertGreater(ts2, ts1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
