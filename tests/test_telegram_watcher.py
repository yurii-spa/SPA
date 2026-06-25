"""
tests/test_telegram_watcher.py
================================
30 unit tests for spa_core/monitoring/telegram_watcher.py

All network calls, subprocess calls and auto_fixer are mocked.
Tests run fully offline — no Telegram token, no API keys required.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

# ── Repo root on sys.path ────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.monitoring.telegram_watcher import (
    ALERT_PATTERNS,
    COOLDOWN_TTL_SEC,
    DEDUP_TTL_SEC,
    MAX_MESSAGE_AGE_SEC,
    _content_hash,
    _is_in_cooldown,
    _is_seen,
    _load_offset,
    _mark_seen,
    _save_offset,
    _start_cooldown,
    _tg_request,
    get_bot_token,
    get_chat_id,
    get_updates,
    is_alert_message,
    is_daily_summary,
    is_message_too_old,
    parse_alert_type,
    process_updates,
    run_once,
    send_telegram,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _make_update(text: str, update_id: int = 1, age_sec: int = 0) -> dict:
    """Build a minimal Telegram update dict."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(time.time()) - age_sec,
            "text": text,
            "chat": {"id": -1001234567890, "type": "supergroup"},
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# 1-5  parse_alert_type
# ────────────────────────────────────────────────────────────────────────────

class TestParseAlertType:
    def test_import_error(self):
        text = "ImportError: No module named 'foo'"
        assert parse_alert_type(text) == "ImportError"

    def test_module_not_found(self):
        text = "ModuleNotFoundError: No module named 'bar'"
        assert parse_alert_type(text) == "ImportError"

    def test_attribute_error(self):
        text = "AttributeError: 'NoneType' object has no attribute 'strip'"
        assert parse_alert_type(text) == "AttributeError"

    def test_file_not_found(self):
        text = "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/x.json'"
        assert parse_alert_type(text) == "FileNotFoundError"

    def test_generic_error_fallback(self):
        text = "❌ Something went wrong with the pipeline"
        assert parse_alert_type(text) == "ERROR"

    def test_type_error(self):
        assert parse_alert_type("TypeError: unsupported operand type(s)") == "TypeError"

    def test_value_error(self):
        assert parse_alert_type("ValueError: invalid literal for int()") == "ValueError"

    def test_key_error(self):
        assert parse_alert_type("KeyError: 'apy'") == "KeyError"

    def test_runtime_error(self):
        assert parse_alert_type("RuntimeError: cuda out of memory") == "RuntimeError"

    def test_generic_exception(self):
        assert parse_alert_type("Traceback (most recent call last):") == "GenericException"

    def test_critical_prefix(self):
        assert parse_alert_type("CRITICAL: disk full") == "CRITICAL"

    def test_name_error(self):
        assert parse_alert_type("NameError: name 'x' is not defined") == "NameError"


# ────────────────────────────────────────────────────────────────────────────
# 6-10  is_alert_message
# ────────────────────────────────────────────────────────────────────────────

class TestIsAlertMessage:
    def test_detects_critical(self):
        assert is_alert_message("CRITICAL: disk full") is True

    def test_detects_error(self):
        assert is_alert_message("ERROR connecting to database") is True

    def test_detects_red_cross(self):
        assert is_alert_message("❌ Adapter health check FAILED") is True

    def test_detects_warning_emoji(self):
        assert is_alert_message("⚠️ APY spike detected") is True

    def test_detects_traceback(self):
        assert is_alert_message("Traceback (most recent call last):") is True

    def test_detects_exception(self):
        assert is_alert_message("Exception in thread main") is True

    def test_detects_failed(self):
        assert is_alert_message("FAILED: test_uptime_monitor") is True

    def test_plain_status_not_alert(self):
        # A plain status message with no alert words
        assert is_alert_message("✅ All systems operational") is False

    def test_empty_string(self):
        assert is_alert_message("") is False

    def test_case_insensitive_error(self):
        assert is_alert_message("error: something broke") is True


# ────────────────────────────────────────────────────────────────────────────
# 11-15  is_daily_summary
# ────────────────────────────────────────────────────────────────────────────

class TestIsDailySummary:
    def test_daily_summary_keyword(self):
        assert is_daily_summary("📊 Daily Summary: APY 12.4%") is True

    def test_apy_report_keyword(self):
        assert is_daily_summary("APY Report for June 21") is True

    def test_morning_report(self):
        assert is_daily_summary("Morning Report — equity $150k") is True

    def test_weekly_report(self):
        assert is_daily_summary("Weekly Report: 7-day performance") is True

    def test_traceback_overrides_summary_skip(self):
        # Even if summary keyword present, traceback means it IS an alert
        assert is_daily_summary(
            "Daily Summary\nTraceback (most recent call last):\n  File 'foo.py'"
        ) is False

    def test_plain_error_not_daily(self):
        assert is_daily_summary("❌ ImportError in uptime_monitor.py") is False


# ────────────────────────────────────────────────────────────────────────────
# 16-18  Dedup via _is_seen / _mark_seen
# ────────────────────────────────────────────────────────────────────────────

class TestDedup:
    def test_fresh_hash_not_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN",
            str(tmp_path) + "/spa_tw_seen_",
        )
        h = _content_hash("unique alert " + str(time.time()))
        assert _is_seen(h) is False

    def test_mark_then_seen(self, tmp_path, monkeypatch):
        prefix = str(tmp_path) + "/spa_tw_seen_"
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN", prefix)
        h = _content_hash("test alert abc")
        _mark_seen(h)
        assert _is_seen(h) is True

    def test_duplicate_alert_skipped_in_process_updates(self, tmp_path, monkeypatch):
        """Second identical alert within TTL should be skipped."""
        prefix = str(tmp_path) + "/spa_tw_seen_"
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN", prefix)
        monkeypatch.setattr(
            "spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
            str(tmp_path) + "/spa_tw_cooldown_",
        )
        text = "CRITICAL: test dedup ImportError: No module named 'spa'"
        update1 = _make_update(text, update_id=1)
        update2 = _make_update(text, update_id=2)

        # Patch telegram_watcher.run_auto_fix (module-level name) so the dedup
        # check works: first alert triggers fix, second (duplicate) is skipped.
        with patch("spa_core.monitoring.telegram_watcher.run_auto_fix",
                   return_value=True) as mock_fix:
            process_updates([update1, update2], token="tok", chat_id="cid")
        assert mock_fix.call_count == 1, "Second duplicate should be skipped"


# ────────────────────────────────────────────────────────────────────────────
# 19-21  Cooldown
# ────────────────────────────────────────────────────────────────────────────

class TestCooldown:
    def test_no_cooldown_initially(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
            str(tmp_path) + "/cd_",
        )
        h = _content_hash("something" + str(time.time()))
        assert _is_in_cooldown(h) is False

    def test_cooldown_active_after_start(self, tmp_path, monkeypatch):
        prefix = str(tmp_path) + "/cd_"
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN", prefix)
        h = _content_hash("alert-123")
        _start_cooldown(h)
        assert _is_in_cooldown(h) is True

    def test_cooldown_second_alert_skipped(self, tmp_path, monkeypatch):
        """Two similar alerts: second one should not trigger fix if cooldown active."""
        prefix_seen = str(tmp_path) + "/seen_"
        prefix_cd = str(tmp_path) + "/cd_"
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN", prefix_seen)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN", prefix_cd)

        text = "AttributeError: 'NoneType' object has no attribute 'values'"
        update1 = _make_update(text, update_id=10)
        update2 = _make_update(text + " again", update_id=11)

        # Pre-set cooldown for text2's hash
        h2 = _content_hash(text + " again")
        _start_cooldown(h2)

        with patch("spa_core.monitoring.telegram_watcher.run_auto_fix") as mock_fix:
            mock_fix.return_value = True
            process_updates([update1, update2], token="tok", chat_id="cid")
            # update2 should be blocked by cooldown
            for c in mock_fix.call_args_list:
                assert (text + " again") not in str(c)


# ────────────────────────────────────────────────────────────────────────────
# 22-24  Message age filtering
# ────────────────────────────────────────────────────────────────────────────

class TestMessageAge:
    def test_recent_message_not_old(self):
        update = _make_update("ERROR: something", age_sec=10)
        assert is_message_too_old(update) is False

    def test_old_message_filtered(self):
        update = _make_update("CRITICAL: old error", age_sec=MAX_MESSAGE_AGE_SEC + 10)
        assert is_message_too_old(update) is True

    def test_old_message_skipped_in_process(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN",
                            str(tmp_path) + "/s_")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
                            str(tmp_path) + "/c_")
        old = _make_update("CRITICAL: old error", age_sec=MAX_MESSAGE_AGE_SEC + 60)
        with patch("spa_core.monitoring.telegram_watcher.run_auto_fix") as mock_fix:
            mock_fix.return_value = True
            process_updates([old], token="tok", chat_id="cid")
            mock_fix.assert_not_called()


# ────────────────────────────────────────────────────────────────────────────
# 25-27  Offset persistence
# ────────────────────────────────────────────────────────────────────────────

class TestOffset:
    def test_load_offset_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "spa_core.monitoring.telegram_watcher.OFFSET_FILE",
            tmp_path / "nonexistent.json",
        )
        assert _load_offset() is None

    def test_save_and_load_offset(self, tmp_path, monkeypatch):
        f = tmp_path / "offset.json"
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.OFFSET_FILE", f)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.DATA_DIR", tmp_path)
        _save_offset(42)
        assert _load_offset() == 42  # _save_offset stores value as-is; _load_offset returns it
        data = json.loads(f.read_text())
        assert data["offset"] == 42

    def test_load_offset_corrupt_file(self, tmp_path, monkeypatch):
        f = tmp_path / "offset.json"
        f.write_text("NOT JSON")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.OFFSET_FILE", f)
        assert _load_offset() is None


# ────────────────────────────────────────────────────────────────────────────
# 28-30  run_once (integration — mocked network)
# ────────────────────────────────────────────────────────────────────────────

class TestRunOnce:
    def test_run_once_no_token(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.DATA_DIR", tmp_path)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.LOG_DIR", tmp_path)
        with patch("spa_core.monitoring.telegram_watcher.get_bot_token", return_value=None):
            run_once()  # should not raise

    def test_run_once_no_updates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.DATA_DIR", tmp_path)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.LOG_DIR", tmp_path)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.OFFSET_FILE",
                            tmp_path / "offset.json")
        with patch("spa_core.monitoring.telegram_watcher.get_bot_token", return_value="TOKEN"):
            with patch("spa_core.monitoring.telegram_watcher.get_chat_id", return_value="CID"):
                with patch("spa_core.monitoring.telegram_watcher.get_updates", return_value=[]):
                    run_once()  # no errors, no updates

    def test_run_once_triggers_fix_on_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.DATA_DIR", tmp_path)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.LOG_DIR", tmp_path)
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.OFFSET_FILE",
                            tmp_path / "offset.json")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN",
                            str(tmp_path) + "/s_")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
                            str(tmp_path) + "/c_")

        alert_update = _make_update(
            "Traceback (most recent call last):\n  File 'spa_core/monitoring/uptime_monitor.py'"
            ", line 42\nAttributeError: 'NoneType' object has no attribute 'get'",
            update_id=99,
        )

        with patch("spa_core.monitoring.telegram_watcher.get_bot_token", return_value="TOK"):
            with patch("spa_core.monitoring.telegram_watcher.get_chat_id", return_value="CID"):
                with patch("spa_core.monitoring.telegram_watcher.get_updates",
                           return_value=[alert_update]):
                    with patch("spa_core.monitoring.telegram_watcher.run_auto_fix",
                               return_value=True) as mock_fix:
                        run_once()
                        mock_fix.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# Extra edge-case tests (brings total to 30)
# ────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_content_hash_deterministic(self):
        h1 = _content_hash("same text")
        h2 = _content_hash("same text")
        assert h1 == h2

    def test_content_hash_different(self):
        assert _content_hash("a") != _content_hash("b")

    def test_send_telegram_success(self):
        with patch("spa_core.monitoring.telegram_watcher._tg_request",
                   return_value={"ok": True}):
            result = send_telegram("TOKEN", "CHAT", "hello")
            assert result is True

    def test_send_telegram_failure(self):
        with patch("spa_core.monitoring.telegram_watcher._tg_request",
                   return_value=None):
            result = send_telegram("TOKEN", "CHAT", "hello")
            assert result is False

    def test_get_updates_returns_list(self):
        with patch("spa_core.monitoring.telegram_watcher._tg_request",
                   return_value={"ok": True, "result": [{"update_id": 1}]}):
            updates = get_updates("TOKEN")
            assert updates == [{"update_id": 1}]

    def test_get_updates_api_error(self):
        with patch("spa_core.monitoring.telegram_watcher._tg_request", return_value=None):
            updates = get_updates("TOKEN")
            assert updates is None

    def test_non_alert_message_not_processed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN",
                            str(tmp_path) + "/s_")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
                            str(tmp_path) + "/c_")
        update = _make_update("✅ All systems healthy", update_id=5)
        with patch("spa_core.monitoring.telegram_watcher.run_auto_fix") as mock_fix:
            process_updates([update], token="tok", chat_id="cid")
            mock_fix.assert_not_called()

    def test_empty_updates_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_SEEN",
                            str(tmp_path) + "/s_")
        monkeypatch.setattr("spa_core.monitoring.telegram_watcher.TMP_PREFIX_COOLDOWN",
                            str(tmp_path) + "/c_")
        with patch("spa_core.monitoring.telegram_watcher.run_auto_fix") as mock_fix:
            process_updates([], token="tok", chat_id="cid")
            mock_fix.assert_not_called()


# ── Shim for direct import of run_auto_fix in telegram_watcher ──────────────
# telegram_watcher lazily imports run_auto_fix from auto_fixer inside process_updates.
# Patch the auto_fixer module attribute so all lazy imports pick up the mock.
@pytest.fixture(autouse=True)
def patch_auto_fixer():
    """Ensure auto_fixer.run_auto_fix is never called for real during watcher tests."""
    with patch("spa_core.monitoring.telegram_watcher.run_auto_fix", return_value=True):
        yield
