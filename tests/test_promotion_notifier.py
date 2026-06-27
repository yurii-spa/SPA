"""
Tests for spa_core/reporting/promotion_notifier.py (ADR-029).

All tests mock _send_message so no real HTTP requests are made.
Subprocess / Keychain access is also mocked where needed.
"""
from __future__ import annotations

import os
import sys
import importlib
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path setup — ensure project root is on sys.path
# ---------------------------------------------------------------------------
import pathlib
PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from spa_core.reporting.promotion_notifier import (
    PromotionNotifier,
    _get_secret,
    _read_keychain,
    _TOKEN_SERVICE,
    _CHAT_ID_SERVICE,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _notifier(token: str = "TEST_TOKEN", chat_id: str = "12345") -> PromotionNotifier:
    """Return a PromotionNotifier with credentials injected via monkeypatching."""
    n = PromotionNotifier()
    n._get_token   = lambda: token
    n._get_chat_id = lambda: chat_id
    return n


def _mock_send(notifier: PromotionNotifier, return_value: bool = True) -> MagicMock:
    """Patch _send_message on *notifier*, return the mock."""
    mock = MagicMock(return_value=return_value)
    notifier._send_message = mock
    return mock


# ===========================================================================
# 1. Tier A — send_tier_a_alert
# ===========================================================================

class TestTierAAlert(unittest.TestCase):

    def _make(self):
        n = _notifier()
        m = _mock_send(n)
        return n, m

    def test_tier_a_returns_true_on_success(self):
        n, m = self._make()
        result = n.send_tier_a_alert("s1", {"name": "S1", "realized_apy": 12.5, "target_apy": 10.0, "sharpe": 1.5, "max_drawdown_pct": 2.3, "paper_days": 30})
        self.assertTrue(result)

    def test_tier_a_message_format(self):
        n, m = self._make()
        n.send_tier_a_alert("s1", {"name": "S1 Strategy", "realized_apy": 12.5, "target_apy": 10.0, "sharpe": 1.50, "max_drawdown_pct": 2.3, "paper_days": 30})
        text = m.call_args[0][0]
        self.assertIn("AUTO-PROMOTED", text)
        self.assertIn("S1 Strategy", text)
        self.assertIn("12.5%", text)
        self.assertIn("10.0%", text)
        self.assertIn("1.50", text)
        self.assertIn("2.3%", text)
        self.assertIn("30", text)
        self.assertIn("AUTO_PROMOTE", text)

    def test_tier_a_message_contains_lightning_emoji(self):
        n, m = self._make()
        n.send_tier_a_alert("s1", {"name": "S1"})
        text = m.call_args[0][0]
        self.assertIn("⚡", text)

    def test_tier_a_missing_metrics_renders_na(self):
        n, m = self._make()
        n.send_tier_a_alert("s1", {})
        text = m.call_args[0][0]
        self.assertIn("N/A", text)

    def test_tier_a_uses_strategy_id_as_fallback_name(self):
        n, m = self._make()
        n.send_tier_a_alert("my_strategy_id", {})
        text = m.call_args[0][0]
        self.assertIn("my_strategy_id", text)

    def test_tier_a_apy_rounded_to_one_decimal(self):
        n, m = self._make()
        n.send_tier_a_alert("s1", {"realized_apy": 7.777})
        text = m.call_args[0][0]
        self.assertIn("7.8%", text)

    def test_tier_a_send_called_once(self):
        n, m = self._make()
        n.send_tier_a_alert("s1", {"name": "S1"})
        m.assert_called_once()

    def test_tier_a_propagates_send_false(self):
        n = _notifier()
        _mock_send(n, return_value=False)
        result = n.send_tier_a_alert("s1", {"name": "S1"})
        self.assertFalse(result)


# ===========================================================================
# 2. Tier B — send_tier_b_alert
# ===========================================================================

class TestTierBAlert(unittest.TestCase):

    def _make(self):
        n = _notifier()
        m = _mock_send(n)
        return n, m

    def test_tier_b_returns_true_on_success(self):
        n, m = self._make()
        result = n.send_tier_b_alert("s2", {"name": "S2", "realized_apy": 8.0, "sharpe": 1.1})
        self.assertTrue(result)

    def test_tier_b_message_format(self):
        n, m = self._make()
        n.send_tier_b_alert("s2", {"name": "S2 Strategy", "realized_apy": 8.0, "sharpe": 1.1, "deadline_iso": "2026-06-14T12:00:00Z"})
        text = m.call_args[0][0]
        self.assertIn("PENDING AUTO-PROMOTE", text)
        self.assertIn("S2 Strategy", text)
        self.assertIn("48h", text)
        self.assertIn("8.0%", text)
        self.assertIn("1.10", text)
        self.assertIn("2026-06-14T12:00:00Z", text)

    def test_tier_b_message_contains_cancel(self):
        n, m = self._make()
        n.send_tier_b_alert("s2", {"name": "S2"})
        text = m.call_args[0][0]
        self.assertIn("CANCEL", text)

    def test_tier_b_message_contains_clock_emoji(self):
        n, m = self._make()
        n.send_tier_b_alert("s2", {})
        text = m.call_args[0][0]
        self.assertIn("🕐", text)

    def test_tier_b_deadline_auto_computed_48h_ahead(self):
        n, m = self._make()
        before = datetime.now(timezone.utc) + timedelta(hours=47, minutes=59)
        n.send_tier_b_alert("s2", {"name": "S2"})
        after  = datetime.now(timezone.utc) + timedelta(hours=48, minutes=1)
        text   = m.call_args[0][0]
        # Extract the deadline from the text
        deadline_str = None
        for line in text.splitlines():
            if "Deadline:" in line:
                deadline_str = line.split("Deadline:")[-1].strip()
        self.assertIsNotNone(deadline_str, "Deadline line not found in message")
        # Parse and compare
        deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(deadline_dt, before)
        self.assertLessEqual(deadline_dt, after)

    def test_tier_b_explicit_deadline_overrides_auto(self):
        n, m = self._make()
        n.send_tier_b_alert("s2", {"deadline_iso": "2099-01-01T00:00:00Z"})
        text = m.call_args[0][0]
        self.assertIn("2099-01-01T00:00:00Z", text)

    def test_tier_b_missing_metrics_renders_na(self):
        n, m = self._make()
        n.send_tier_b_alert("s2", {})
        text = m.call_args[0][0]
        self.assertIn("N/A", text)

    def test_tier_b_propagates_send_false(self):
        n = _notifier()
        _mock_send(n, return_value=False)
        result = n.send_tier_b_alert("s2", {})
        self.assertFalse(result)


# ===========================================================================
# 3. Tier C — send_tier_c_alert
# ===========================================================================

class TestTierCAlert(unittest.TestCase):

    def _make(self):
        n = _notifier()
        m = _mock_send(n)
        return n, m

    def test_tier_c_returns_true_on_success(self):
        n, m = self._make()
        result = n.send_tier_c_alert("s3", {"name": "S3"}, "Drawdown exceeded threshold")
        self.assertTrue(result)

    def test_tier_c_message_format(self):
        n, m = self._make()
        n.send_tier_c_alert("s3", {"name": "S3 Strategy", "realized_apy": 5.0, "sharpe": 0.8}, "Low Sharpe ratio")
        text = m.call_args[0][0]
        self.assertIn("MANUAL REVIEW REQUIRED", text)
        self.assertIn("S3 Strategy", text)
        self.assertIn("5.0%", text)
        self.assertIn("0.80", text)
        self.assertIn("USER_APPROVAL_NEEDED", text)

    def test_tier_c_message_contains_reason(self):
        n, m = self._make()
        reason = "Capital-at-risk exceeds 50000 USD"
        n.send_tier_c_alert("s3", {}, reason)
        text = m.call_args[0][0]
        self.assertIn(reason, text)

    def test_tier_c_message_contains_red_circle_emoji(self):
        n, m = self._make()
        n.send_tier_c_alert("s3", {}, "reason")
        text = m.call_args[0][0]
        self.assertIn("🔴", text)

    def test_tier_c_missing_metrics_renders_na(self):
        n, m = self._make()
        n.send_tier_c_alert("s3", {}, "reason")
        text = m.call_args[0][0]
        self.assertIn("N/A", text)

    def test_tier_c_uses_strategy_id_as_fallback_name(self):
        n, m = self._make()
        n.send_tier_c_alert("s3_raw_id", {}, "reason")
        text = m.call_args[0][0]
        self.assertIn("s3_raw_id", text)

    def test_tier_c_propagates_send_false(self):
        n = _notifier()
        _mock_send(n, return_value=False)
        result = n.send_tier_c_alert("s3", {}, "reason")
        self.assertFalse(result)

    def test_tier_c_empty_reason_still_sends(self):
        n, m = self._make()
        result = n.send_tier_c_alert("s3", {}, "")
        self.assertTrue(result)
        m.assert_called_once()


# ===========================================================================
# 4. Health alert — send_health_alert
# ===========================================================================

class TestHealthAlert(unittest.TestCase):

    def _make(self):
        n = _notifier()
        m = _mock_send(n)
        return n, m

    def test_health_alert_returns_true_on_success(self):
        n, m = self._make()
        result = n.send_health_alert({"overall": "WARNING", "checks": []})
        self.assertTrue(result)

    def test_health_alert_warning(self):
        n, m = self._make()
        n.send_health_alert({"overall": "WARNING", "checks": [{"name": "cycle_lag", "status": "WARN", "message": "20 min late"}]})
        text = m.call_args[0][0]
        self.assertIn("WARNING", text)
        self.assertIn("cycle_lag", text)
        self.assertIn("20 min late", text)

    def test_health_alert_critical(self):
        n, m = self._make()
        n.send_health_alert({"overall": "CRITICAL", "checks": [{"name": "equity_curve", "status": "FAIL", "message": "missing"}]})
        text = m.call_args[0][0]
        self.assertIn("CRITICAL", text)
        self.assertIn("equity_curve", text)

    def test_health_alert_warning_uses_warning_emoji(self):
        n, m = self._make()
        n.send_health_alert({"overall": "WARNING"})
        text = m.call_args[0][0]
        self.assertIn("⚠️", text)

    def test_health_alert_critical_uses_siren_emoji(self):
        n, m = self._make()
        n.send_health_alert({"overall": "CRITICAL"})
        text = m.call_args[0][0]
        self.assertIn("🚨", text)

    def test_health_alert_timestamp_included(self):
        n, m = self._make()
        n.send_health_alert({"overall": "WARNING", "timestamp": "2026-06-12T08:00:00Z"})
        text = m.call_args[0][0]
        self.assertIn("2026-06-12T08:00:00Z", text)

    def test_health_alert_auto_timestamp_when_missing(self):
        n, m = self._make()
        before = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        n.send_health_alert({"overall": "CRITICAL"})
        text = m.call_args[0][0]
        # Timestamp line should contain today's date prefix
        self.assertIn(before, text)

    def test_health_alert_multiple_checks(self):
        n, m = self._make()
        checks = [
            {"name": "check_a", "status": "OK"},
            {"name": "check_b", "status": "FAIL", "message": "broken"},
            {"name": "check_c", "status": "WARN"},
        ]
        n.send_health_alert({"overall": "WARNING", "checks": checks})
        text = m.call_args[0][0]
        self.assertIn("check_a", text)
        self.assertIn("check_b", text)
        self.assertIn("check_c", text)
        self.assertIn("broken", text)

    def test_health_alert_no_checks_still_sends(self):
        n, m = self._make()
        result = n.send_health_alert({})
        self.assertTrue(result)
        m.assert_called_once()

    def test_health_alert_propagates_send_false(self):
        n = _notifier()
        _mock_send(n, return_value=False)
        result = n.send_health_alert({"overall": "WARNING"})
        self.assertFalse(result)


# ===========================================================================
# 5. _send_message (unit) — no real HTTP
# ===========================================================================

class TestSendMessage(unittest.TestCase):

    def test_send_failure_returns_false_http_error(self):
        """HTTPError from urllib → _send_message returns False."""
        import urllib.error
        n = PromotionNotifier()
        n._get_token   = lambda: "tok"
        n._get_chat_id = lambda: "chat"
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 400, "Bad", {}, None)):
            result = n._send_message("hello")
        self.assertFalse(result)

    def test_send_failure_returns_false_url_error(self):
        import urllib.error
        n = PromotionNotifier()
        n._get_token   = lambda: "tok"
        n._get_chat_id = lambda: "chat"
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network down")):
            result = n._send_message("hello")
        self.assertFalse(result)

    def test_send_failure_returns_false_generic_exception(self):
        n = PromotionNotifier()
        n._get_token   = lambda: "tok"
        n._get_chat_id = lambda: "chat"
        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            result = n._send_message("hello")
        self.assertFalse(result)

    def test_message_no_token_returns_false(self):
        n = PromotionNotifier()
        n._get_token   = lambda: ""
        n._get_chat_id = lambda: "chat"
        with patch("urllib.request.urlopen") as mock_url:
            result = n._send_message("hello")
        self.assertFalse(result)
        mock_url.assert_not_called()

    def test_message_no_chat_id_returns_false(self):
        n = PromotionNotifier()
        n._get_token   = lambda: "tok"
        n._get_chat_id = lambda: ""
        with patch("urllib.request.urlopen") as mock_url:
            result = n._send_message("hello")
        self.assertFalse(result)
        mock_url.assert_not_called()

    def test_message_both_missing_returns_false(self):
        n = PromotionNotifier()
        n._get_token   = lambda: ""
        n._get_chat_id = lambda: ""
        result = n._send_message("hello")
        self.assertFalse(result)

    def test_send_message_routes_to_digest(self):
        """Phase-1 Telegram rebuild: promotions are informational and no longer
        push — _send_message routes the text to the digest queue and returns
        False (its old urlopen POST path is gone)."""
        n = PromotionNotifier()

        with patch("spa_core.telegram.push_policy._enqueue_digest") as enq:
            result = n._send_message("Test payload")

        self.assertFalse(result)
        enq.assert_called_once()
        # _enqueue_digest(tg_dir, item) — the item dict carries the text in body.
        item = enq.call_args.args[1]
        self.assertEqual(item["body"], "Test payload")


# ===========================================================================
# 6. Credential retrieval — _get_token / _get_chat_id / env fallback
# ===========================================================================

class TestCredentials(unittest.TestCase):

    def test_token_from_env_fallback(self):
        """When subprocess (Keychain) fails, fall back to env var."""
        with patch("spa_core.reporting.promotion_notifier._read_keychain", return_value=""):
            with patch.dict(os.environ, {_TOKEN_SERVICE: "env_token_value"}):
                n = PromotionNotifier()
                self.assertEqual(n._get_token(), "env_token_value")

    def test_chat_id_from_env_fallback(self):
        with patch("spa_core.reporting.promotion_notifier._read_keychain", return_value=""):
            with patch.dict(os.environ, {_CHAT_ID_SERVICE: "env_chat_id"}):
                n = PromotionNotifier()
                self.assertEqual(n._get_chat_id(), "env_chat_id")

    def test_keychain_value_takes_priority_over_env(self):
        with patch("spa_core.reporting.promotion_notifier._read_keychain", return_value="keychain_token"):
            with patch.dict(os.environ, {_TOKEN_SERVICE: "env_token"}):
                n = PromotionNotifier()
                self.assertEqual(n._get_token(), "keychain_token")

    def test_empty_credentials_send_returns_false(self):
        with patch("spa_core.reporting.promotion_notifier._read_keychain", return_value=""):
            with patch.dict(os.environ, {}, clear=True):
                # Remove relevant env vars if present
                env = {k: v for k, v in os.environ.items() if k not in (_TOKEN_SERVICE, _CHAT_ID_SERVICE)}
                with patch.dict(os.environ, env, clear=True):
                    n = PromotionNotifier()
                    result = n._send_message("test")
                    self.assertFalse(result)

    def test_read_keychain_returns_empty_on_nonzero_returncode(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout     = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = _read_keychain("FAKE_SERVICE")
        self.assertEqual(result, "")

    def test_read_keychain_returns_empty_on_subprocess_exception(self):
        with patch("subprocess.run", side_effect=OSError("no security")):
            result = _read_keychain("FAKE_SERVICE")
        self.assertEqual(result, "")

    def test_read_keychain_returns_stripped_value(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout     = "  actual_secret\n"
        with patch("subprocess.run", return_value=mock_proc):
            result = _read_keychain("SERVICE")
        self.assertEqual(result, "actual_secret")


# ===========================================================================
# 7. Edge cases / robustness
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_tier_a_zero_values_rendered(self):
        n = _notifier()
        m = _mock_send(n)
        n.send_tier_a_alert("s1", {"realized_apy": 0.0, "target_apy": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0, "paper_days": 0})
        text = m.call_args[0][0]
        self.assertNotIn("N/A", text)
        self.assertIn("0.0%", text)

    def test_tier_b_zero_values_rendered(self):
        n = _notifier()
        m = _mock_send(n)
        n.send_tier_b_alert("s2", {"realized_apy": 0.0, "sharpe": 0.0})
        text = m.call_args[0][0]
        self.assertIn("0.0%", text)

    def test_tier_c_special_chars_in_reason(self):
        n = _notifier()
        m = _mock_send(n)
        reason = "Capital > 50000 & risk < threshold"
        n.send_tier_c_alert("s3", {}, reason)
        text = m.call_args[0][0]
        self.assertIn(reason, text)

    def test_all_methods_dont_raise_on_broken_send(self):
        """Even if _send_message itself raises, public methods must not propagate."""
        n = _notifier()
        n._send_message = MagicMock(side_effect=RuntimeError("totally broken"))
        # All these should return False without raising
        self.assertFalse(n.send_tier_a_alert("s1", {}))
        self.assertFalse(n.send_tier_b_alert("s2", {}))
        self.assertFalse(n.send_tier_c_alert("s3", {}, "r"))
        self.assertFalse(n.send_health_alert({}))

    def test_tier_a_large_apy_formatted(self):
        n = _notifier()
        m = _mock_send(n)
        n.send_tier_a_alert("s1", {"realized_apy": 99.9})
        text = m.call_args[0][0]
        self.assertIn("99.9%", text)

    def test_health_alert_check_without_message_field(self):
        """Checks that omit 'message' should still render without error."""
        n = _notifier()
        m = _mock_send(n)
        n.send_health_alert({"overall": "WARNING", "checks": [{"name": "db", "status": "OK"}]})
        text = m.call_args[0][0]
        self.assertIn("db", text)
        self.assertIn("OK", text)

    def test_no_import_of_external_packages(self):
        """The module must import only stdlib modules."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "promotion_notifier",
            str(pathlib.Path(__file__).parent.parent / "spa_core" / "reporting" / "promotion_notifier.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # This import must succeed with no third-party packages
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "PromotionNotifier"))


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
