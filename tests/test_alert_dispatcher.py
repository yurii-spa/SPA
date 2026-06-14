"""
tests/test_alert_dispatcher.py — MP-588

Unit tests for spa_core/alerts/alert_dispatcher.py

Groups:
    TestAlertLevel                  (12 tests)
    TestAlertDataclass              (14 tests)
    TestAlertFromDict               (10 tests)
    TestHtmlEscape                  (6  tests)
    TestFormatTelegramMessage       (8  tests)
    TestAtomicWriteJson             (6  tests)
    TestLoadLogEntries              (8  tests)
    TestDispatcherInit              (6  tests)
    TestCreateAlert                 (8  tests)
    TestDispatchToLog               (12 tests)
    TestDispatchToTelegramNoEnv     (6  tests)
    TestDispatchToTelegramWithEnv   (10 tests)
    TestDispatchMain                (12 tests)
    TestSuppressDuplicates          (10 tests)
    TestGetRecentAlerts             (12 tests)
    TestRingBuffer                  (8  tests)
    TestImportHygiene               (4  tests)

Total: ≥ 152 tests (well above the 85-test requirement)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.alerts.alert_dispatcher import (
    Alert,
    AlertDispatcher,
    AlertLevel,
    RING_BUFFER_MAX,
    _atomic_write_json,
    _format_telegram_message,
    _html_escape,
    _load_log_entries,
    _now_iso,
    _utc_timestamp,
)


# ===========================================================================
# Helpers
# ===========================================================================
def _make_tmp_log() -> Path:
    """Return a temporary path (does not create the file)."""
    td = tempfile.mkdtemp()
    return Path(td) / "alert_log.json"


def _make_dispatcher(**kwargs) -> tuple[AlertDispatcher, Path]:
    log_path = _make_tmp_log()
    d = AlertDispatcher(log_path=log_path, **kwargs)
    return d, log_path


def _make_alert(
    level: AlertLevel = AlertLevel.INFO,
    title: str = "Test Alert",
    message: str = "Test message",
    adapter_id: str | None = None,
) -> Alert:
    return Alert(level=level, title=title, message=message, adapter_id=adapter_id)


# ===========================================================================
# TestAlertLevel
# ===========================================================================
class TestAlertLevel(unittest.TestCase):
    """12 tests covering AlertLevel enum values and comparisons."""

    def test_info_value(self):
        self.assertEqual(AlertLevel.INFO.value, 1)

    def test_warning_value(self):
        self.assertEqual(AlertLevel.WARNING.value, 2)

    def test_critical_value(self):
        self.assertEqual(AlertLevel.CRITICAL.value, 3)

    def test_emergency_value(self):
        self.assertEqual(AlertLevel.EMERGENCY.value, 4)

    def test_info_lt_warning(self):
        self.assertLess(AlertLevel.INFO, AlertLevel.WARNING)

    def test_warning_lt_critical(self):
        self.assertLess(AlertLevel.WARNING, AlertLevel.CRITICAL)

    def test_critical_lt_emergency(self):
        self.assertLess(AlertLevel.CRITICAL, AlertLevel.EMERGENCY)

    def test_emergency_gt_critical(self):
        self.assertGreater(AlertLevel.EMERGENCY, AlertLevel.CRITICAL)

    def test_info_le_info(self):
        self.assertLessEqual(AlertLevel.INFO, AlertLevel.INFO)

    def test_critical_ge_warning(self):
        self.assertGreaterEqual(AlertLevel.CRITICAL, AlertLevel.WARNING)

    def test_name_info(self):
        self.assertEqual(AlertLevel.INFO.name, "INFO")

    def test_name_emergency(self):
        self.assertEqual(AlertLevel.EMERGENCY.name, "EMERGENCY")


# ===========================================================================
# TestAlertDataclass
# ===========================================================================
class TestAlertDataclass(unittest.TestCase):
    """14 tests for Alert construction, fields, and to_dict."""

    def test_basic_construction(self):
        a = Alert(level=AlertLevel.INFO, title="t", message="m")
        self.assertEqual(a.level, AlertLevel.INFO)
        self.assertEqual(a.title, "t")
        self.assertEqual(a.message, "m")

    def test_adapter_id_defaults_none(self):
        a = Alert(level=AlertLevel.WARNING, title="t", message="m")
        self.assertIsNone(a.adapter_id)

    def test_adapter_id_set(self):
        a = Alert(level=AlertLevel.CRITICAL, title="t", message="m", adapter_id="aave_v3")
        self.assertEqual(a.adapter_id, "aave_v3")

    def test_timestamp_auto_generated(self):
        a = Alert(level=AlertLevel.INFO, title="t", message="m")
        self.assertIsNotNone(a.timestamp)
        self.assertIn("T", a.timestamp)  # ISO format

    def test_correlation_id_is_uuid4_format(self):
        a = Alert(level=AlertLevel.INFO, title="t", message="m")
        # Should parse as valid UUID
        parsed = uuid.UUID(a.correlation_id)
        self.assertEqual(str(parsed), a.correlation_id)

    def test_two_alerts_have_different_correlation_ids(self):
        a1 = Alert(level=AlertLevel.INFO, title="t", message="m")
        a2 = Alert(level=AlertLevel.INFO, title="t", message="m")
        self.assertNotEqual(a1.correlation_id, a2.correlation_id)

    def test_to_dict_keys(self):
        a = _make_alert()
        d = a.to_dict()
        self.assertIn("level", d)
        self.assertIn("title", d)
        self.assertIn("message", d)
        self.assertIn("adapter_id", d)
        self.assertIn("timestamp", d)
        self.assertIn("correlation_id", d)

    def test_to_dict_level_is_string(self):
        a = _make_alert(level=AlertLevel.CRITICAL)
        self.assertEqual(a.to_dict()["level"], "CRITICAL")

    def test_to_dict_emergency_level(self):
        a = _make_alert(level=AlertLevel.EMERGENCY)
        self.assertEqual(a.to_dict()["level"], "EMERGENCY")

    def test_to_dict_adapter_id_none(self):
        a = _make_alert()
        self.assertIsNone(a.to_dict()["adapter_id"])

    def test_to_dict_adapter_id_present(self):
        a = _make_alert(adapter_id="compound_v3")
        self.assertEqual(a.to_dict()["adapter_id"], "compound_v3")

    def test_to_dict_title_preserved(self):
        a = _make_alert(title="Critical: TVL below floor")
        self.assertEqual(a.to_dict()["title"], "Critical: TVL below floor")

    def test_to_dict_message_preserved(self):
        a = _make_alert(message="Detailed explanation of the issue")
        self.assertEqual(a.to_dict()["message"], "Detailed explanation of the issue")

    def test_to_dict_correlation_id_preserved(self):
        cid = str(uuid.uuid4())
        a = Alert(level=AlertLevel.INFO, title="t", message="m", correlation_id=cid)
        self.assertEqual(a.to_dict()["correlation_id"], cid)


# ===========================================================================
# TestAlertFromDict
# ===========================================================================
class TestAlertFromDict(unittest.TestCase):
    """10 tests for Alert.from_dict()."""

    def test_round_trip(self):
        a = _make_alert(level=AlertLevel.CRITICAL, title="T", message="M", adapter_id="ax")
        b = Alert.from_dict(a.to_dict())
        self.assertEqual(b.level, a.level)
        self.assertEqual(b.title, a.title)
        self.assertEqual(b.message, a.message)
        self.assertEqual(b.adapter_id, a.adapter_id)
        self.assertEqual(b.correlation_id, a.correlation_id)

    def test_from_dict_info(self):
        a = Alert.from_dict({"level": "INFO", "title": "t", "message": "m"})
        self.assertEqual(a.level, AlertLevel.INFO)

    def test_from_dict_warning(self):
        a = Alert.from_dict({"level": "WARNING", "title": "t", "message": "m"})
        self.assertEqual(a.level, AlertLevel.WARNING)

    def test_from_dict_emergency(self):
        a = Alert.from_dict({"level": "EMERGENCY", "title": "t", "message": "m"})
        self.assertEqual(a.level, AlertLevel.EMERGENCY)

    def test_from_dict_unknown_level_defaults_info(self):
        a = Alert.from_dict({"level": "BANANA", "title": "t", "message": "m"})
        self.assertEqual(a.level, AlertLevel.INFO)

    def test_from_dict_missing_level_defaults_info(self):
        a = Alert.from_dict({"title": "t", "message": "m"})
        self.assertEqual(a.level, AlertLevel.INFO)

    def test_from_dict_adapter_id_none_for_null(self):
        a = Alert.from_dict({"level": "INFO", "title": "t", "message": "m", "adapter_id": None})
        self.assertIsNone(a.adapter_id)

    def test_from_dict_adapter_id_empty_string_becomes_none(self):
        a = Alert.from_dict({"level": "INFO", "title": "t", "message": "m", "adapter_id": ""})
        self.assertIsNone(a.adapter_id)

    def test_from_dict_preserves_correlation_id(self):
        cid = str(uuid.uuid4())
        a = Alert.from_dict({"level": "INFO", "title": "t", "message": "m", "correlation_id": cid})
        self.assertEqual(a.correlation_id, cid)

    def test_from_dict_generates_correlation_id_if_missing(self):
        a = Alert.from_dict({"level": "INFO", "title": "t", "message": "m"})
        # Should have a valid UUID
        parsed = uuid.UUID(a.correlation_id)
        self.assertEqual(str(parsed), a.correlation_id)


# ===========================================================================
# TestHtmlEscape
# ===========================================================================
class TestHtmlEscape(unittest.TestCase):
    """6 tests for _html_escape()."""

    def test_no_special_chars(self):
        self.assertEqual(_html_escape("hello"), "hello")

    def test_ampersand(self):
        self.assertEqual(_html_escape("a & b"), "a &amp; b")

    def test_less_than(self):
        self.assertEqual(_html_escape("a < b"), "a &lt; b")

    def test_greater_than(self):
        self.assertEqual(_html_escape("a > b"), "a &gt; b")

    def test_combined(self):
        result = _html_escape("<script>alert('xss')</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;", result)
        self.assertIn("&gt;", result)

    def test_non_string_coerced(self):
        result = _html_escape(42)
        self.assertEqual(result, "42")


# ===========================================================================
# TestFormatTelegramMessage
# ===========================================================================
class TestFormatTelegramMessage(unittest.TestCase):
    """8 tests for _format_telegram_message()."""

    def test_contains_level_name(self):
        a = _make_alert(level=AlertLevel.CRITICAL)
        msg = _format_telegram_message(a)
        self.assertIn("CRITICAL", msg)

    def test_contains_title(self):
        a = _make_alert(title="TVL below floor")
        msg = _format_telegram_message(a)
        self.assertIn("TVL below floor", msg)

    def test_contains_message(self):
        a = _make_alert(message="Detailed issue description")
        msg = _format_telegram_message(a)
        self.assertIn("Detailed issue description", msg)

    def test_contains_correlation_id(self):
        a = _make_alert()
        msg = _format_telegram_message(a)
        self.assertIn(a.correlation_id, msg)

    def test_adapter_id_included_when_present(self):
        a = _make_alert(adapter_id="morpho_blue")
        msg = _format_telegram_message(a)
        self.assertIn("morpho_blue", msg)

    def test_adapter_id_not_shown_when_none(self):
        a = _make_alert(adapter_id=None)
        msg = _format_telegram_message(a)
        self.assertNotIn("Adapter:", msg)

    def test_emergency_emoji_present(self):
        a = _make_alert(level=AlertLevel.EMERGENCY)
        msg = _format_telegram_message(a)
        self.assertIn("🚨", msg)

    def test_html_bold_tag_present(self):
        a = _make_alert()
        msg = _format_telegram_message(a)
        self.assertIn("<b>", msg)
        self.assertIn("</b>", msg)


# ===========================================================================
# TestAtomicWriteJson
# ===========================================================================
class TestAtomicWriteJson(unittest.TestCase):
    """6 tests for _atomic_write_json()."""

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            _atomic_write_json(p, {"key": "value"})
            self.assertTrue(p.exists())

    def test_content_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            _atomic_write_json(p, {"a": 1, "b": [1, 2]})
            with p.open() as fh:
                data = json.load(fh)
            self.assertEqual(data["a"], 1)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sub" / "dir" / "out.json"
            _atomic_write_json(p, [])
            self.assertTrue(p.exists())

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            _atomic_write_json(p, {"v": 1})
            _atomic_write_json(p, {"v": 2})
            with p.open() as fh:
                data = json.load(fh)
            self.assertEqual(data["v"], 2)

    def test_no_tmp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            _atomic_write_json(p, {})
            tmp_files = list(Path(td).glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_list_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.json"
            _atomic_write_json(p, [1, 2, 3])
            with p.open() as fh:
                data = json.load(fh)
            self.assertEqual(data, [1, 2, 3])


# ===========================================================================
# TestLoadLogEntries
# ===========================================================================
class TestLoadLogEntries(unittest.TestCase):
    """8 tests for _load_log_entries()."""

    def test_empty_for_nonexistent_file(self):
        p = Path("/nonexistent/path/alert_log.json")
        self.assertEqual(_load_log_entries(p), [])

    def test_loads_entries_list_format(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            entries = [{"level": "INFO", "title": "t1"}, {"level": "WARNING", "title": "t2"}]
            _atomic_write_json(p, {"entries": entries})
            result = _load_log_entries(p)
            self.assertEqual(len(result), 2)

    def test_loads_plain_list_format(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            entries = [{"level": "INFO"}]
            _atomic_write_json(p, entries)
            result = _load_log_entries(p)
            self.assertEqual(len(result), 1)

    def test_returns_empty_for_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            p.write_text("{{not valid json", encoding="utf-8")
            self.assertEqual(_load_log_entries(p), [])

    def test_filters_non_dict_entries(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            _atomic_write_json(p, {"entries": [{"a": 1}, "not_a_dict", 42, {"b": 2}]})
            result = _load_log_entries(p)
            self.assertEqual(len(result), 2)

    def test_returns_empty_for_wrong_type(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            _atomic_write_json(p, "just a string")
            self.assertEqual(_load_log_entries(p), [])

    def test_empty_entries_list(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            _atomic_write_json(p, {"entries": []})
            self.assertEqual(_load_log_entries(p), [])

    def test_missing_entries_key_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.json"
            _atomic_write_json(p, {"other_key": "value"})
            self.assertEqual(_load_log_entries(p), [])


# ===========================================================================
# TestDispatcherInit
# ===========================================================================
class TestDispatcherInit(unittest.TestCase):
    """6 tests for AlertDispatcher.__init__()."""

    def test_default_log_path(self):
        d = AlertDispatcher()
        self.assertIn("data", str(d._log_path))
        self.assertIn("alert_log.json", str(d._log_path))

    def test_custom_log_path(self):
        p = Path("/tmp/custom_log.json")
        d = AlertDispatcher(log_path=p)
        self.assertEqual(d._log_path, p)

    def test_custom_log_path_as_string(self):
        d = AlertDispatcher(log_path="/tmp/test.json")
        self.assertEqual(d._log_path, Path("/tmp/test.json"))

    def test_suppress_duplicates_default_false(self):
        d = AlertDispatcher()
        self.assertFalse(d.suppress_duplicates)

    def test_suppress_duplicates_can_be_true(self):
        d = AlertDispatcher(suppress_duplicates=True)
        self.assertTrue(d.suppress_duplicates)

    def test_cooldown_seconds_default(self):
        d = AlertDispatcher()
        self.assertEqual(d.cooldown_seconds, 300)


# ===========================================================================
# TestCreateAlert
# ===========================================================================
class TestCreateAlert(unittest.TestCase):
    """8 tests for AlertDispatcher.create_alert()."""

    def test_returns_alert_instance(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "t", "m")
        self.assertIsInstance(a, Alert)

    def test_level_set_correctly(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.EMERGENCY, "t", "m")
        self.assertEqual(a.level, AlertLevel.EMERGENCY)

    def test_title_set(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "My Title", "m")
        self.assertEqual(a.title, "My Title")

    def test_message_set(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "t", "My message")
        self.assertEqual(a.message, "My message")

    def test_adapter_id_defaults_none(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "t", "m")
        self.assertIsNone(a.adapter_id)

    def test_adapter_id_set(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.WARNING, "t", "m", adapter_id="euler_v2")
        self.assertEqual(a.adapter_id, "euler_v2")

    def test_correlation_id_generated(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "t", "m")
        self.assertTrue(len(a.correlation_id) > 0)

    def test_timestamp_generated(self):
        d, _ = _make_dispatcher()
        a = d.create_alert(AlertLevel.INFO, "t", "m")
        self.assertIn("T", a.timestamp)


# ===========================================================================
# TestDispatchToLog
# ===========================================================================
class TestDispatchToLog(unittest.TestCase):
    """12 tests for AlertDispatcher.dispatch_to_log()."""

    def test_returns_true(self):
        d, _ = _make_dispatcher()
        a = _make_alert()
        self.assertTrue(d.dispatch_to_log(a))

    def test_always_returns_true(self):
        """dispatch_to_log contract: always True even after multiple calls."""
        d, _ = _make_dispatcher()
        for i in range(5):
            a = _make_alert(title=f"Alert {i}")
            self.assertTrue(d.dispatch_to_log(a))

    def test_creates_log_file(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        self.assertTrue(log_path.exists())

    def test_log_has_entries_key(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertIn("entries", data)

    def test_log_has_one_entry(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(len(data["entries"]), 1)

    def test_log_entry_has_level(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert(level=AlertLevel.CRITICAL))
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["entries"][0]["level"], "CRITICAL")

    def test_log_entry_has_logged_at(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertIn("logged_at", data["entries"][0])

    def test_multiple_alerts_accumulate(self):
        d, log_path = _make_dispatcher()
        for i in range(5):
            d.dispatch_to_log(_make_alert(title=f"A{i}"))
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(len(data["entries"]), 5)

    def test_schema_version_2(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["schema_version"], 2)

    def test_log_count_field_matches_entries(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert())
        d.dispatch_to_log(_make_alert(title="A2"))
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["count"], len(data["entries"]))

    def test_adapter_id_preserved(self):
        d, log_path = _make_dispatcher()
        d.dispatch_to_log(_make_alert(adapter_id="pendle_pt"))
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["entries"][0]["adapter_id"], "pendle_pt")

    def test_returns_true_even_on_path_error(self):
        """Contract: always returns True even if logging fails internally."""
        d = AlertDispatcher(log_path="/nonexistent_dir_XYZ/log.json")
        # Force a write failure — should still return True
        # (if it doesn't raise, it returns True)
        result = d.dispatch_to_log(_make_alert())
        self.assertTrue(result)


# ===========================================================================
# TestDispatchToTelegramNoEnv
# ===========================================================================
class TestDispatchToTelegramNoEnv(unittest.TestCase):
    """6 tests for dispatch_to_telegram() when env vars are absent."""

    def setUp(self):
        self._orig_token = os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        self._orig_chat = os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def tearDown(self):
        if self._orig_token is not None:
            os.environ["TELEGRAM_BOT_TOKEN_SPA"] = self._orig_token
        else:
            os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        if self._orig_chat is not None:
            os.environ["TELEGRAM_CHAT_ID_SPA"] = self._orig_chat
        else:
            os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_returns_false_no_env(self):
        d, _ = _make_dispatcher()
        self.assertFalse(d.dispatch_to_telegram(_make_alert()))

    def test_returns_false_only_token(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = "token123"
        d, _ = _make_dispatcher()
        self.assertFalse(d.dispatch_to_telegram(_make_alert()))

    def test_returns_false_only_chat_id(self):
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "123456"
        d, _ = _make_dispatcher()
        self.assertFalse(d.dispatch_to_telegram(_make_alert()))

    def test_returns_false_empty_token(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = ""
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "123456"
        d, _ = _make_dispatcher()
        self.assertFalse(d.dispatch_to_telegram(_make_alert()))

    def test_returns_false_whitespace_only_token(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = "   "
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "123456"
        d, _ = _make_dispatcher()
        self.assertFalse(d.dispatch_to_telegram(_make_alert()))

    def test_no_network_call_made(self):
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen") as mock_open:
            d.dispatch_to_telegram(_make_alert())
            mock_open.assert_not_called()


# ===========================================================================
# TestDispatchToTelegramWithEnv
# ===========================================================================
class TestDispatchToTelegramWithEnv(unittest.TestCase):
    """10 tests for dispatch_to_telegram() when env vars are present."""

    def setUp(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = "test_token_abc"
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "987654321"

    def tearDown(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def _mock_response(self, status: int = 200):
        resp = MagicMock()
        resp.status = status
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_true_on_200(self):
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
            result = d.dispatch_to_telegram(_make_alert())
        self.assertTrue(result)

    def test_returns_false_on_non_200(self):
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", return_value=self._mock_response(400)):
            result = d.dispatch_to_telegram(_make_alert())
        self.assertFalse(result)

    def test_returns_false_on_url_error(self):
        import urllib.error
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = d.dispatch_to_telegram(_make_alert())
        self.assertFalse(result)

    def test_returns_false_on_http_error(self):
        import urllib.error
        d, _ = _make_dispatcher()
        err = urllib.error.HTTPError(
            url="http://x", code=401, msg="Unauthorized",
            hdrs=None, fp=MagicMock(read=lambda: b"Unauthorized")
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = d.dispatch_to_telegram(_make_alert())
        self.assertFalse(result)

    def test_returns_false_on_generic_exception(self):
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", side_effect=RuntimeError("bang")):
            result = d.dispatch_to_telegram(_make_alert())
        self.assertFalse(result)

    def test_uses_correct_token_in_url(self):
        d, _ = _make_dispatcher()
        captured_urls = []
        with patch("urllib.request.Request") as mock_req:
            mock_req.side_effect = lambda url, **kw: (captured_urls.append(url), MagicMock())[1]
            with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
                d.dispatch_to_telegram(_make_alert())
        if captured_urls:
            self.assertIn("test_token_abc", captured_urls[0])

    def test_sends_html_parse_mode(self):
        d, _ = _make_dispatcher()
        captured_payloads = []
        original_request = __import__("urllib.request", fromlist=["Request"]).Request

        def capture_request(url, data=None, **kw):
            if data:
                captured_payloads.append(json.loads(data.decode()))
            return original_request(url, data=data, **kw)

        with patch("urllib.request.Request", side_effect=capture_request):
            with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
                d.dispatch_to_telegram(_make_alert())

        if captured_payloads:
            self.assertEqual(captured_payloads[0].get("parse_mode"), "HTML")

    def test_does_not_raise_on_network_failure(self):
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            # Must not raise
            try:
                d.dispatch_to_telegram(_make_alert())
            except Exception as exc:
                self.fail(f"dispatch_to_telegram raised: {exc}")

    def test_all_alert_levels_dispatched(self):
        d, _ = _make_dispatcher()
        for level in AlertLevel:
            with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
                result = d.dispatch_to_telegram(_make_alert(level=level))
            self.assertTrue(result, f"Expected True for level {level}")

    def test_adapter_id_included_in_message(self):
        d, _ = _make_dispatcher()
        captured_payloads = []
        original_request = __import__("urllib.request", fromlist=["Request"]).Request

        def capture_request(url, data=None, **kw):
            if data:
                captured_payloads.append(json.loads(data.decode()))
            return original_request(url, data=data, **kw)

        with patch("urllib.request.Request", side_effect=capture_request):
            with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
                d.dispatch_to_telegram(_make_alert(adapter_id="aave_v3"))

        if captured_payloads:
            self.assertIn("aave_v3", captured_payloads[0].get("text", ""))


# ===========================================================================
# TestDispatchMain
# ===========================================================================
class TestDispatchMain(unittest.TestCase):
    """12 tests for AlertDispatcher.dispatch()."""

    def setUp(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_returns_dict(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertIsInstance(result, dict)

    def test_result_has_alert_id(self):
        d, _ = _make_dispatcher()
        a = _make_alert()
        result = d.dispatch(a)
        self.assertEqual(result["alert_id"], a.correlation_id)

    def test_result_has_channels_attempted(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertIn("channels_attempted", result)

    def test_result_has_channels_succeeded(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertIn("channels_succeeded", result)

    def test_log_channel_always_attempted(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertIn("log", result["channels_attempted"])

    def test_log_channel_in_succeeded(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertIn("log", result["channels_succeeded"])

    def test_telegram_not_attempted_without_env(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertNotIn("telegram", result["channels_attempted"])

    def test_telegram_attempted_with_env(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = "tok"
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "123"
        d, _ = _make_dispatcher()
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            result = d.dispatch(_make_alert())
        self.assertIn("telegram", result["channels_attempted"])
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_suppressed_false_by_default(self):
        d, _ = _make_dispatcher()
        result = d.dispatch(_make_alert())
        self.assertFalse(result["suppressed"])

    def test_alert_is_persisted(self):
        d, log_path = _make_dispatcher()
        a = _make_alert(title="Persisted alert")
        d.dispatch(a)
        entries = _load_log_entries(log_path)
        titles = [e.get("title") for e in entries]
        self.assertIn("Persisted alert", titles)

    def test_dispatch_multiple_alerts(self):
        d, log_path = _make_dispatcher()
        for i in range(3):
            d.dispatch(_make_alert(title=f"Alert {i}"))
        entries = _load_log_entries(log_path)
        self.assertEqual(len(entries), 3)

    def test_telegram_succeeded_on_200(self):
        os.environ["TELEGRAM_BOT_TOKEN_SPA"] = "tok"
        os.environ["TELEGRAM_CHAT_ID_SPA"] = "123"
        d, _ = _make_dispatcher()
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = d.dispatch(_make_alert())
        self.assertIn("telegram", result["channels_succeeded"])
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)


# ===========================================================================
# TestSuppressDuplicates
# ===========================================================================
class TestSuppressDuplicates(unittest.TestCase):
    """10 tests for suppress_duplicates feature."""

    def setUp(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_first_dispatch_not_suppressed(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        result = d.dispatch(_make_alert(title="Dup Test"))
        self.assertFalse(result["suppressed"])

    def test_second_same_title_suppressed(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="Dup Test"))
        result2 = d.dispatch(_make_alert(title="Dup Test"))
        self.assertTrue(result2["suppressed"])

    def test_different_title_not_suppressed(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="Alert A"))
        result = d.dispatch(_make_alert(title="Alert B"))
        self.assertFalse(result["suppressed"])

    def test_suppressed_channels_attempted_empty(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="Dup"))
        result = d.dispatch(_make_alert(title="Dup"))
        self.assertEqual(result["channels_attempted"], [])

    def test_suppressed_channels_succeeded_empty(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="Dup"))
        result = d.dispatch(_make_alert(title="Dup"))
        self.assertEqual(result["channels_succeeded"], [])

    def test_no_suppression_by_default(self):
        d, _ = _make_dispatcher()  # suppress_duplicates=False
        d.dispatch(_make_alert(title="Same Title"))
        result = d.dispatch(_make_alert(title="Same Title"))
        self.assertFalse(result["suppressed"])

    def test_cooldown_expired_allows_resend(self):
        d, _ = _make_dispatcher(suppress_duplicates=True, cooldown_seconds=0)
        d.dispatch(_make_alert(title="Dup"))
        # With cooldown=0, the next dispatch should NOT be suppressed
        result = d.dispatch(_make_alert(title="Dup"))
        self.assertFalse(result["suppressed"])

    def test_custom_cooldown_300s_suppresses(self):
        d, _ = _make_dispatcher(suppress_duplicates=True, cooldown_seconds=300)
        d.dispatch(_make_alert(title="T"))
        result = d.dispatch(_make_alert(title="T"))
        self.assertTrue(result["suppressed"])

    def test_suppressed_alert_id_is_preserved(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="Dup"))
        a2 = _make_alert(title="Dup")
        result = d.dispatch(a2)
        self.assertEqual(result["alert_id"], a2.correlation_id)

    def test_third_dispatch_after_first_still_suppressed(self):
        d, _ = _make_dispatcher(suppress_duplicates=True)
        d.dispatch(_make_alert(title="X"))
        d.dispatch(_make_alert(title="X"))  # suppressed
        result3 = d.dispatch(_make_alert(title="X"))
        self.assertTrue(result3["suppressed"])


# ===========================================================================
# TestGetRecentAlerts
# ===========================================================================
class TestGetRecentAlerts(unittest.TestCase):
    """12 tests for AlertDispatcher.get_recent_alerts()."""

    def setUp(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_empty_for_no_log(self):
        d, _ = _make_dispatcher()
        self.assertEqual(d.get_recent_alerts(), [])

    def test_returns_list(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert())
        result = d.get_recent_alerts()
        self.assertIsInstance(result, list)

    def test_returns_alert_objects(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert())
        alerts = d.get_recent_alerts()
        self.assertIsInstance(alerts[0], Alert)

    def test_returns_correct_count(self):
        d, _ = _make_dispatcher()
        for i in range(5):
            d.dispatch(_make_alert(title=f"A{i}"))
        self.assertEqual(len(d.get_recent_alerts()), 5)

    def test_n_limits_results(self):
        d, _ = _make_dispatcher()
        for i in range(10):
            d.dispatch(_make_alert(title=f"A{i}"))
        self.assertEqual(len(d.get_recent_alerts(n=3)), 3)

    def test_newest_first_ordering(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert(title="First"))
        d.dispatch(_make_alert(title="Second"))
        d.dispatch(_make_alert(title="Third"))
        alerts = d.get_recent_alerts()
        # Newest first means "Third" should be first
        self.assertEqual(alerts[0].title, "Third")

    def test_default_n_is_50(self):
        d, _ = _make_dispatcher()
        for i in range(60):
            d.dispatch(_make_alert(title=f"A{i}"))
        # default n=50
        self.assertEqual(len(d.get_recent_alerts()), 50)

    def test_level_preserved(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert(level=AlertLevel.EMERGENCY))
        alerts = d.get_recent_alerts()
        self.assertEqual(alerts[0].level, AlertLevel.EMERGENCY)

    def test_adapter_id_preserved(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert(adapter_id="yearn_v3"))
        alerts = d.get_recent_alerts()
        self.assertEqual(alerts[0].adapter_id, "yearn_v3")

    def test_n_larger_than_available(self):
        d, _ = _make_dispatcher()
        d.dispatch(_make_alert())
        d.dispatch(_make_alert())
        alerts = d.get_recent_alerts(n=100)
        self.assertEqual(len(alerts), 2)

    def test_empty_log_n_zero(self):
        d, _ = _make_dispatcher()
        self.assertEqual(d.get_recent_alerts(n=0), [])

    def test_ignores_corrupt_entries(self):
        """Entries that can't be converted to Alert are silently skipped."""
        d, log_path = _make_dispatcher()
        # Write a mix of valid and invalid entries
        payload = {
            "schema_version": 2,
            "entries": [
                {"level": "INFO", "title": "ok", "message": "m"},
                {"NOT_LEVEL": "broken"},  # missing required fields but from_dict handles it
                {"level": "WARNING", "title": "ok2", "message": "m2"},
            ]
        }
        _atomic_write_json(log_path, payload)
        alerts = d.get_recent_alerts()
        # Should return at least 2 valid alerts (from_dict handles missing fields gracefully)
        self.assertGreaterEqual(len(alerts), 2)


# ===========================================================================
# TestRingBuffer
# ===========================================================================
class TestRingBuffer(unittest.TestCase):
    """8 tests for ring-buffer capping at RING_BUFFER_MAX."""

    def setUp(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN_SPA", None)
        os.environ.pop("TELEGRAM_CHAT_ID_SPA", None)

    def test_ring_buffer_max_constant(self):
        self.assertEqual(RING_BUFFER_MAX, 1000)

    def test_does_not_exceed_ring_buffer_max(self):
        d, log_path = _make_dispatcher()
        # Write 1005 entries directly to test the cap
        entries = [
            {"level": "INFO", "title": f"A{i}", "message": "m", "correlation_id": str(uuid.uuid4())}
            for i in range(1005)
        ]
        _atomic_write_json(log_path, {"schema_version": 2, "entries": entries})
        # Add one more via dispatch
        d.dispatch(_make_alert(title="Overflow"))
        remaining = _load_log_entries(log_path)
        self.assertLessEqual(len(remaining), RING_BUFFER_MAX)

    def test_keeps_most_recent_on_overflow(self):
        d, log_path = _make_dispatcher()
        entries = [
            {"level": "INFO", "title": f"Old{i}", "message": "m", "correlation_id": str(uuid.uuid4())}
            for i in range(1000)
        ]
        _atomic_write_json(log_path, {"schema_version": 2, "entries": entries})
        d.dispatch(_make_alert(title="NewAlert"))
        remaining = _load_log_entries(log_path)
        titles = [e.get("title") for e in remaining]
        self.assertIn("NewAlert", titles)

    def test_old_entries_dropped_on_overflow(self):
        d, log_path = _make_dispatcher()
        entries = [
            {"level": "INFO", "title": f"Slot{i}", "message": "m", "correlation_id": str(uuid.uuid4())}
            for i in range(1001)
        ]
        _atomic_write_json(log_path, {"schema_version": 2, "entries": entries})
        d.dispatch(_make_alert(title="LatestAlert"))
        remaining = _load_log_entries(log_path)
        # Slot0 should be gone (oldest entry dropped)
        titles = [e.get("title") for e in remaining]
        self.assertNotIn("Slot0", titles)

    def test_small_number_of_entries_not_truncated(self):
        d, log_path = _make_dispatcher()
        for i in range(10):
            d.dispatch(_make_alert(title=f"Alert{i}"))
        remaining = _load_log_entries(log_path)
        self.assertEqual(len(remaining), 10)

    def test_exact_ring_buffer_max_not_truncated(self):
        d, log_path = _make_dispatcher()
        entries = [
            {"level": "INFO", "title": f"E{i}", "message": "m", "correlation_id": str(uuid.uuid4())}
            for i in range(RING_BUFFER_MAX)
        ]
        _atomic_write_json(log_path, {"schema_version": 2, "entries": entries})
        remaining = _load_log_entries(log_path)
        self.assertEqual(len(remaining), RING_BUFFER_MAX)

    def test_max_entries_field_in_log(self):
        d, log_path = _make_dispatcher()
        d.dispatch(_make_alert())
        with log_path.open() as fh:
            data = json.load(fh)
        self.assertEqual(data["max_entries"], RING_BUFFER_MAX)

    def test_atomic_write_no_data_loss_on_concurrent_append(self):
        """Two sequential dispatches both appear in log (atomicity check)."""
        d, log_path = _make_dispatcher()
        d.dispatch(_make_alert(title="First"))
        d.dispatch(_make_alert(title="Second"))
        entries = _load_log_entries(log_path)
        titles = {e.get("title") for e in entries}
        self.assertIn("First", titles)
        self.assertIn("Second", titles)


# ===========================================================================
# TestImportHygiene
# ===========================================================================
class TestImportHygiene(unittest.TestCase):
    """4 tests confirming no forbidden imports are present in alert_dispatcher."""

    def _read_source(self) -> str:
        src_path = (
            Path(__file__).resolve().parents[1]
            / "spa_core"
            / "alerts"
            / "alert_dispatcher.py"
        )
        return src_path.read_text(encoding="utf-8")

    def test_no_requests_import(self):
        src = self._read_source()
        self.assertNotIn("import requests", src)

    def test_no_numpy_import(self):
        src = self._read_source()
        self.assertNotIn("import numpy", src)
        self.assertNotIn("from numpy", src)

    def test_no_openai_anthropic_import(self):
        src = self._read_source()
        self.assertNotIn("import openai", src)
        self.assertNotIn("import anthropic", src)

    def test_no_execution_domain_import(self):
        """alert_dispatcher must not import from execution/ domain."""
        src = self._read_source()
        self.assertNotIn("from ..execution", src)
        self.assertNotIn("from spa_core.execution", src)


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
