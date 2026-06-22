#!/usr/bin/env python3
"""
tests/test_alert_manager.py — MP-1451 (Sprint v10.67)

Test suite for spa_core/alerts/alert_manager.py.

Tests:
  A. Atomic write migration — _save_alert_state uses atomic_save (A1–A3)
  B. Deduplication helpers (B1–B4)
  C. _calc_period_returns (C1–C3)
  D. _top_protocols helper (D1–D3)
  E. Alert state persistence (E1–E4)

Pure stdlib. No Telegram network calls. Offline. Patches telegram_client.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
import unittest.mock

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))


# ─── Patch Telegram before importing alert_manager ────────────────────────────

class _FakeTelegramClient:
    """Stub that never actually sends messages."""
    def send_message(self, *a, **kw): return True
    def send_message_with_keyboard(self, *a, **kw): return True


# We patch at import time to avoid network dependency
import unittest.mock as _mock
_tc_patcher = _mock.patch.dict(
    "sys.modules",
    {
        "spa_core.alerts.telegram_client": _mock.MagicMock(
            send_message=_mock.MagicMock(return_value=True),
            send_message_with_keyboard=_mock.MagicMock(return_value=True),
        ),
        "spa_core.alerts.telegram_format_ru": _mock.MagicMock(
            format_message_ru=_mock.MagicMock(return_value="formatted"),
            build_detail_keyboard=_mock.MagicMock(return_value=[]),
        ),
    }
)
_tc_patcher.start()

import spa_core.alerts.alert_manager as _am
import tempfile


def _patch_data_dir(tmp_path: pathlib.Path):
    """Context manager: redirect _DATA_DIR and _ALERT_STATE_FILE to tmp_path."""
    state_file = tmp_path / "telegram_alert_state.json"
    return (
        unittest.mock.patch.object(_am, "_DATA_DIR", tmp_path),
        unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Atomic write migration
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_A1_atomic_save_imported_in_module(self):
        """alert_manager imports atomic_save from spa_core.utils.atomic after migration (MP-1451)."""
        src = (_REPO / "spa_core" / "alerts" / "alert_manager.py").read_text(encoding="utf-8")
        self.assertIn("atomic_save", src,
                      "Run MP-1451 migration: _save_alert_state should use atomic_save")

    def test_A2_save_alert_state_writes_file(self):
        """_save_alert_state persists state dict to the state file."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", tmp / "state.json"):
                _am._save_alert_state({"daily_summary": "2026-06-20"})
                state_file = tmp / "state.json"
                self.assertTrue(state_file.exists())
                data = json.loads(state_file.read_text())
                self.assertEqual(data.get("daily_summary"), "2026-06-20")

    def test_A3_no_tmp_files_after_save(self):
        """_save_alert_state leaves no .tmp files."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", tmp / "state.json"):
                _am._save_alert_state({"key": "value"})
                tmp_files = list(tmp.glob("*.tmp"))
                self.assertEqual(len(tmp_files), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — Deduplication helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeduplication(unittest.TestCase):

    def test_B1_load_alert_state_returns_empty_when_no_file(self):
        """_load_alert_state returns {} when state file does not exist."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            with unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", tmp / "no_file.json"):
                state = _am._load_alert_state()
                self.assertEqual(state, {})

    def test_B2_load_alert_state_reads_existing(self):
        """_load_alert_state reads back previously saved state."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            state_file.write_text(json.dumps({"daily_summary": "2026-06-20"}))
            with unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                state = _am._load_alert_state()
                self.assertEqual(state.get("daily_summary"), "2026-06-20")

    def test_B3_already_sent_today_false_when_no_state(self):
        """_already_sent_today returns False when state file absent."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            with unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", tmp / "no_file.json"):
                result = _am._already_sent_today("daily_summary")
                self.assertFalse(result)

    def test_B4_already_sent_today_true_when_marked(self):
        """_already_sent_today returns True after _mark_sent_today is called."""
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            state_file.write_text(json.dumps({"test_key": today}))
            with unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                result = _am._already_sent_today("test_key")
                self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — _calc_period_returns
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalcPeriodReturns(unittest.TestCase):

    def _make_daily(self, equities: list[float]) -> list[dict]:
        """Build minimal equity_curve rows."""
        from datetime import datetime, timedelta
        base = datetime(2026, 6, 1)
        return [
            {"date": (base + timedelta(days=i)).strftime("%Y-%m-%d"), "equity": e}
            for i, e in enumerate(equities)
        ]

    def test_C1_returns_dict(self):
        """_calc_period_returns returns a dict."""
        daily = self._make_daily([100000, 100100, 100200])
        result = _am._calc_period_returns(daily)
        self.assertIsInstance(result, dict)

    def test_C2_alltime_return_positive_when_equity_grew(self):
        """alltime_pct is positive when final equity > first equity."""
        daily = self._make_daily([100000, 100500, 101000])
        result = _am._calc_period_returns(daily)
        alltime = result.get("alltime_pct", 0.0)
        self.assertGreater(alltime, 0.0)

    def test_C3_empty_daily_does_not_crash(self):
        """_calc_period_returns handles empty list gracefully."""
        result = _am._calc_period_returns([])
        self.assertIsInstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — _top_protocols
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopProtocols(unittest.TestCase):
    """_top_protocols(positions, capital_usd, n) — positions values are plain floats (USD)."""

    def test_D1_returns_list(self):
        """_top_protocols returns a list."""
        positions = {
            "aave_v3": 40000.0,
            "compound_v3": 30000.0,
            "morpho_blue": 20000.0,
            "cash": 10000.0,
        }
        result = _am._top_protocols(positions, capital_usd=100000, n=3)
        self.assertIsInstance(result, list)

    def test_D2_returns_n_or_fewer_items(self):
        """_top_protocols returns at most n items."""
        positions = {"aave_v3": 50000.0, "cash": 50000.0}
        result = _am._top_protocols(positions, capital_usd=100000, n=3)
        self.assertLessEqual(len(result), 3)

    def test_D3_top_protocol_percentage_in_output(self):
        """Largest-value protocol percentage appears first in the result."""
        positions = {
            "aave_v3": 10000.0,
            "compound_v3": 60000.0,
            "morpho_blue": 30000.0,
        }
        result = _am._top_protocols(positions, capital_usd=100000, n=3)
        # compound_v3 is biggest (60%); first entry should mention it
        if result:
            self.assertIn("Compound V3", result[0])


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — Alert state persistence round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertStatePersistence(unittest.TestCase):

    def test_E1_save_then_load_roundtrip(self):
        """State saved by _save_alert_state is recovered by _load_alert_state."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            payload = {"daily_summary": "2026-06-20", "weekly": "2026-06-17"}
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                _am._save_alert_state(payload)
                recovered = _am._load_alert_state()
            self.assertEqual(recovered, payload)

    def test_E2_mark_then_check_roundtrip(self):
        """_mark_sent_today + _already_sent_today returns True for same key."""
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                _am._mark_sent_today("weekly_report")
                sent = _am._already_sent_today("weekly_report")
            self.assertTrue(sent)

    def test_E3_different_key_not_marked(self):
        """_already_sent_today is False for a different key than was marked."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                _am._mark_sent_today("daily_summary")
                not_sent = _am._already_sent_today("weekly_report")
            self.assertFalse(not_sent)

    def test_E4_state_file_is_valid_json_after_mark(self):
        """State file written by _mark_sent_today is valid JSON."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            state_file = tmp / "state.json"
            with unittest.mock.patch.object(_am, "_DATA_DIR", tmp), \
                 unittest.mock.patch.object(_am, "_ALERT_STATE_FILE", state_file):
                _am._mark_sent_today("startup_test")
                data = json.loads(state_file.read_text())
                self.assertIn("startup_test", data)


if __name__ == "__main__":
    _tc_patcher.stop()
    unittest.main(verbosity=2)
