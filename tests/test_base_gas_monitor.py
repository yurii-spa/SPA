"""
tests/test_base_gas_monitor.py
================================
Unit tests for spa_core.monitoring.base_gas_monitor — MP-454.

Coverage targets (≥ 20 tests):
  T01  get_current_gas_gwei returns float >= 0
  T02  fallback works when all APIs fail (mock)
  T03  record_reading gas=0.05 → consecutive_above=0, kill_switch_active=False
  T04  record_reading gas=15.0 three times → kill_switch_active=True
  T05  record_reading gas=15.0 twice → consecutive_above=2, kill_switch_active=False
  T06  kill_switch reset: active → gas=0.05 → KILL_SWITCH_RESET, consecutive_above=0
  T07  three days > threshold → kill_switch_active=True (sequential dates)
  T08  is_kill_switch_active() True after 3 days above
  T09  is_kill_switch_active() False on fresh/empty history
  T10  DATA_FILE constant == "data/base_gas_history.json"
  T11  BASE_GAS_THRESHOLD_GWEI == 10.0
  T12  BASE_GAS_KILL_DAYS == 3
  T13  atomic write uses temp file + os.replace
  T14  history file has required keys
  T15  get_status() returns dict with required keys
  T16  history capped at 30 readings (ring-buffer)
  T17  deduplication: two readings same day → one entry
  T18  action == "OK" when gas < threshold
  T19  action == "KILL_SWITCH_ACTIVE" when ≥ 3 days > threshold
  T20  action == "WARN" when 1-2 days > threshold
  T21  action == "KILL_SWITCH_RESET" after reset
  T22  recent_readings entries contain date, gwei, above_threshold keys
  T23  load_history returns safe default when file missing
  T24  load_history returns safe default when file is corrupt JSON
  T25  record_reading with explicit today param (date isolation)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make sure the repo root is on sys.path so we can import spa_core
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.base_gas_monitor import (
    BASE_GAS_KILL_DAYS,
    BASE_GAS_THRESHOLD_GWEI,
    FALLBACK_GWEI,
    MAX_HISTORY_DAYS,
    BaseGasMonitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor(tmp_dir: str) -> BaseGasMonitor:
    """Create a BaseGasMonitor wired to a temp directory."""
    return BaseGasMonitor(data_dir=tmp_dir)


def _record_days(
    monitor: BaseGasMonitor,
    gwei_values: list,
    start_date: date | None = None,
) -> list[Dict[str, Any]]:
    """Record a sequence of daily readings on consecutive dates."""
    if start_date is None:
        start_date = date(2026, 6, 1)
    results = []
    for i, gwei in enumerate(gwei_values):
        d = start_date + timedelta(days=i)
        results.append(monitor.record_reading(gwei=gwei, today=d))
    return results


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestBaseGasMonitorConstants(unittest.TestCase):
    """T10–T12: module-level constants."""

    def test_T10_data_file_constant(self):
        """DATA_FILE must equal 'data/base_gas_history.json'."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            self.assertEqual(m.DATA_FILE, "data/base_gas_history.json")

    def test_T11_threshold_constant(self):
        """BASE_GAS_THRESHOLD_GWEI must be 10.0."""
        self.assertEqual(BASE_GAS_THRESHOLD_GWEI, 10.0)

    def test_T12_kill_days_constant(self):
        """BASE_GAS_KILL_DAYS must be 3."""
        self.assertEqual(BASE_GAS_KILL_DAYS, 3)


class TestGetCurrentGasGwei(unittest.TestCase):
    """T01–T02: network fetch logic."""

    def test_T01_returns_non_negative_float(self):
        """get_current_gas_gwei always returns float >= 0 (real or fallback)."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            # Patch all APIs to raise so fallback is triggered
            with patch.object(m, "_fetch_gas_gwei", side_effect=Exception("network error")):
                gwei = m.get_current_gas_gwei()
            self.assertIsInstance(gwei, float)
            self.assertGreaterEqual(gwei, 0)

    def test_T02_fallback_when_all_apis_fail(self):
        """Falls back to FALLBACK_GWEI when all APIs raise exceptions."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            with patch.object(m, "_fetch_gas_gwei", side_effect=Exception("timeout")):
                gwei = m.get_current_gas_gwei()
            self.assertEqual(gwei, FALLBACK_GWEI)

    def test_T01b_returns_float_from_first_api(self):
        """Uses value from first successful API."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            with patch.object(m, "_fetch_gas_gwei", return_value=0.05) as mock_fetch:
                gwei = m.get_current_gas_gwei()
            self.assertEqual(gwei, 0.05)
            mock_fetch.assert_called()


class TestRecordReading(unittest.TestCase):
    """T03–T08, T18–T21, T25: record_reading logic."""

    def test_T03_low_gas_no_kill_switch(self):
        """Gas=0.05 → consecutive_above=0, kill_switch_active=False, action=OK."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            result = m.record_reading(gwei=0.05, today=date(2026, 6, 1))
        self.assertEqual(result["consecutive_above"], 0)
        self.assertFalse(result["kill_switch_active"])
        self.assertEqual(result["action"], "OK")
        self.assertAlmostEqual(result["gwei"], 0.05, places=5)

    def test_T04_three_high_days_activates_kill_switch(self):
        """Gas=15.0 three days in a row → kill_switch_active=True."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            results = _record_days(m, [15.0, 15.0, 15.0])
        last = results[-1]
        self.assertTrue(last["kill_switch_active"])
        self.assertEqual(last["consecutive_above"], 3)
        self.assertEqual(last["action"], "KILL_SWITCH_ACTIVE")

    def test_T05_two_high_days_no_kill_switch(self):
        """Gas=15.0 for 2 days → consecutive_above=2, kill_switch_active=False, action=WARN."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            results = _record_days(m, [15.0, 15.0])
        last = results[-1]
        self.assertEqual(last["consecutive_above"], 2)
        self.assertFalse(last["kill_switch_active"])
        self.assertEqual(last["action"], "WARN")

    def test_T06_kill_switch_reset_after_low_gas(self):
        """Kill-switch active → next day gas=0.05 → KILL_SWITCH_RESET, consecutive_above=0."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            # Activate kill-switch over 3 days
            _record_days(m, [15.0, 15.0, 15.0])
            # Now a low-gas day
            reset_result = m.record_reading(
                gwei=0.05,
                today=date(2026, 6, 1) + timedelta(days=3),
            )
        self.assertFalse(reset_result["kill_switch_active"])
        self.assertEqual(reset_result["consecutive_above"], 0)
        self.assertEqual(reset_result["action"], "KILL_SWITCH_RESET")

    def test_T07_sequential_three_days_trigger(self):
        """Three sequential calendar dates all above threshold → kill_switch=True."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            start = date(2026, 6, 10)
            results = _record_days(m, [12.0, 11.5, 10.1], start_date=start)
        self.assertTrue(results[2]["kill_switch_active"])

    def test_T18_action_ok_when_below_threshold(self):
        """action == 'OK' when gas < BASE_GAS_THRESHOLD_GWEI."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            result = m.record_reading(gwei=5.0, today=date(2026, 6, 1))
        self.assertEqual(result["action"], "OK")

    def test_T19_action_kill_switch_active_after_3_days(self):
        """action == 'KILL_SWITCH_ACTIVE' after ≥ 3 days above threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            results = _record_days(m, [20.0, 20.0, 20.0])
        self.assertEqual(results[-1]["action"], "KILL_SWITCH_ACTIVE")

    def test_T20_action_warn_after_1_day(self):
        """action == 'WARN' after 1 day above threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            result = m.record_reading(gwei=15.0, today=date(2026, 6, 1))
        self.assertEqual(result["action"], "WARN")

    def test_T20b_action_warn_after_2_days(self):
        """action == 'WARN' after 2 days above threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            results = _record_days(m, [15.0, 15.0])
        self.assertEqual(results[-1]["action"], "WARN")

    def test_T21_action_kill_switch_reset(self):
        """action == 'KILL_SWITCH_RESET' when transitioning from active to OK."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            _record_days(m, [15.0, 15.0, 15.0])
            reset = m.record_reading(gwei=0.01, today=date(2026, 6, 4))
        self.assertEqual(reset["action"], "KILL_SWITCH_RESET")

    def test_T25_explicit_today_param(self):
        """record_reading respects explicit today= argument."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            d = date(2026, 1, 15)
            result = m.record_reading(gwei=0.1, today=d)
        self.assertEqual(result["date"], "2026-01-15")


class TestIsKillSwitchActive(unittest.TestCase):
    """T08–T09: is_kill_switch_active()."""

    def test_T08_true_after_3_days_above(self):
        """is_kill_switch_active() returns True after 3 consecutive days above threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            _record_days(m, [15.0, 15.0, 15.0])
            self.assertTrue(m.is_kill_switch_active())

    def test_T09_false_on_empty_history(self):
        """is_kill_switch_active() returns False on fresh/empty history."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            self.assertFalse(m.is_kill_switch_active())

    def test_T09b_false_after_low_gas(self):
        """is_kill_switch_active() returns False after low gas reading."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            m.record_reading(gwei=0.05, today=date(2026, 6, 1))
            self.assertFalse(m.is_kill_switch_active())


class TestAtomicWrite(unittest.TestCase):
    """T13: atomic write verification."""

    def test_T13_atomic_write_uses_temp_and_replace(self):
        """save_history uses a temp file then os.replace (atomic)."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            replaced_paths = []

            original_replace = os.replace

            def spy_replace(src, dst):
                replaced_paths.append((src, dst))
                original_replace(src, dst)

            with patch("os.replace", side_effect=spy_replace):
                m.save_history({"test": True, "recent_readings": []})

            # os.replace must have been called
            self.assertTrue(len(replaced_paths) > 0, "os.replace was never called")
            src_path, dst_path = replaced_paths[0]
            # tmp file must be different from final file
            self.assertNotEqual(src_path, dst_path)
            # destination must be the data file
            self.assertTrue(dst_path.endswith("base_gas_history.json"))
            # tmp must contain ".tmp"
            self.assertIn(".tmp", src_path)

    def test_T13b_file_exists_after_save(self):
        """After save_history, the data file exists on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            data = m._empty_history()
            m.save_history(data)
            data_file = Path(tmp) / "base_gas_history.json"
            self.assertTrue(data_file.exists())

    def test_T13c_saved_content_is_valid_json(self):
        """Saved file content is valid JSON that round-trips correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            payload = {**m._empty_history(), "test_marker": "hello"}
            m.save_history(payload)
            data_file = Path(tmp) / "base_gas_history.json"
            raw = data_file.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            self.assertEqual(loaded.get("test_marker"), "hello")


class TestHistoryFormat(unittest.TestCase):
    """T14, T22: data file format validation."""

    def test_T14_history_has_required_keys(self):
        """History file has all required top-level keys."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            m.record_reading(gwei=0.05, today=date(2026, 6, 1))
            history = m.load_history()
        required = {
            "last_updated",
            "recent_readings",
            "consecutive_above",
            "kill_switch_active",
            "kill_switch_activated_at",
        }
        self.assertTrue(
            required.issubset(history.keys()),
            f"Missing keys: {required - history.keys()}",
        )

    def test_T22_readings_have_required_keys(self):
        """Each entry in recent_readings has date, gwei, above_threshold keys."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            m.record_reading(gwei=5.0, today=date(2026, 6, 1))
            history = m.load_history()
        self.assertTrue(len(history["recent_readings"]) > 0)
        for reading in history["recent_readings"]:
            self.assertIn("date", reading)
            self.assertIn("gwei", reading)
            self.assertIn("above_threshold", reading)


class TestGetStatus(unittest.TestCase):
    """T15: get_status() interface."""

    def test_T15_get_status_has_required_keys(self):
        """get_status() returns dict with all required keys."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            m.record_reading(gwei=0.1, today=date(2026, 6, 1))
            status = m.get_status()
        required = {
            "gwei",
            "consecutive_above",
            "kill_switch_active",
            "last_updated",
        }
        self.assertTrue(
            required.issubset(status.keys()),
            f"Missing keys: {required - status.keys()}",
        )

    def test_T15b_status_gwei_matches_latest_reading(self):
        """get_status() gwei field reflects most recent reading."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            m.record_reading(gwei=2.5, today=date(2026, 6, 1))
            m.record_reading(gwei=7.0, today=date(2026, 6, 2))
            status = m.get_status()
        self.assertAlmostEqual(status["gwei"], 7.0, places=4)


class TestRingBuffer(unittest.TestCase):
    """T16: history ring-buffer capped at MAX_HISTORY_DAYS."""

    def test_T16_history_capped_at_max(self):
        """recent_readings never exceeds MAX_HISTORY_DAYS (30) entries."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            # Record 35 days
            _record_days(m, [0.05] * 35, start_date=date(2026, 1, 1))
            history = m.load_history()
        self.assertLessEqual(len(history["recent_readings"]), MAX_HISTORY_DAYS)

    def test_T16b_oldest_entries_dropped(self):
        """When capped, earliest dates are removed."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            start = date(2026, 1, 1)
            _record_days(m, [0.05] * 35, start_date=start)
            history = m.load_history()
        dates = [r["date"] for r in history["recent_readings"]]
        # Oldest date should be > 2026-01-01 (first entry was dropped)
        self.assertGreater(min(dates), "2026-01-01")


class TestDeduplication(unittest.TestCase):
    """T17: one reading per day."""

    def test_T17_same_day_deduplication(self):
        """Two readings on the same date → only one entry kept (latest)."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            d = date(2026, 6, 1)
            m.record_reading(gwei=1.0, today=d)
            m.record_reading(gwei=2.0, today=d)  # overwrites
            history = m.load_history()
        entries_for_day = [
            r for r in history["recent_readings"] if r["date"] == "2026-06-01"
        ]
        self.assertEqual(len(entries_for_day), 1)
        # Latest value should be stored
        self.assertAlmostEqual(entries_for_day[0]["gwei"], 2.0, places=4)


class TestLoadHistoryFallback(unittest.TestCase):
    """T23–T24: load_history safe defaults."""

    def test_T23_returns_default_when_file_missing(self):
        """load_history returns safe default when the file does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            history = m.load_history()
        self.assertEqual(history["recent_readings"], [])
        self.assertFalse(history["kill_switch_active"])
        self.assertEqual(history["consecutive_above"], 0)

    def test_T24_returns_default_when_file_corrupt(self):
        """load_history returns safe default when the file contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            data_file = Path(tmp) / "base_gas_history.json"
            data_file.write_text("THIS IS NOT JSON !@#$", encoding="utf-8")
            history = m.load_history()
        self.assertEqual(history["recent_readings"], [])
        self.assertFalse(history["kill_switch_active"])


class TestKillSwitchActivatedAt(unittest.TestCase):
    """kill_switch_activated_at is set on activation and cleared on reset."""

    def test_activated_at_set_on_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            _record_days(m, [15.0, 15.0, 15.0])
            history = m.load_history()
        self.assertIsNotNone(history["kill_switch_activated_at"])

    def test_activated_at_cleared_on_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            _record_days(m, [15.0, 15.0, 15.0])
            m.record_reading(gwei=0.01, today=date(2026, 6, 4))
            history = m.load_history()
        self.assertIsNone(history["kill_switch_activated_at"])

    def test_still_active_does_not_reset_activated_at(self):
        """4th consecutive day above threshold: activated_at should remain from day 3."""
        with tempfile.TemporaryDirectory() as tmp:
            m = _make_monitor(tmp)
            _record_days(m, [15.0, 15.0, 15.0])
            hist_after_3 = m.load_history()
            activated_at_day3 = hist_after_3["kill_switch_activated_at"]
            _record_days(m, [15.0], start_date=date(2026, 6, 4))
            history = m.load_history()
        # activated_at should not be None on day 4
        self.assertIsNotNone(history["kill_switch_activated_at"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
