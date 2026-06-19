"""
MP-1318 (v9.34) — Tests for TelegramResearchAlerts.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_telegram_research_alerts -v
Also compatible with pytest.

IMPORTANT: All tests mock urllib.request.urlopen and subprocess.run to prevent
real network calls and Keychain access.

35 tests across 8 groups:
  1. Instantiation                       (3 tests)
  2. source_promoted_alert()             (6 tests)
  3. cash_drag_alert()                   (5 tests)
  4. owner_acceptance_signed_alert()     (4 tests)
  5. research_exclusion_warning()        (5 tests)
  6. weekly_digest()                     (7 tests)
  7. Error handling                      (3 tests)
  8. Credential resolution               (2 tests)
"""

import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.alerts.telegram_research_alerts import TelegramResearchAlerts


# ── shared helpers ────────────────────────────────────────────────────────────

def _make_alerts(token: str = "test-bot-token", chat_id: str = "test-chat-123") -> TelegramResearchAlerts:
    """Instantiate TelegramResearchAlerts with explicit credentials (no Keychain needed)."""
    return TelegramResearchAlerts(bot_token=token, chat_id=chat_id)


def _success_urlopen() -> MagicMock:
    """
    Returns a mock for urllib.request.urlopen that simulates HTTP 200 ok=True.
    Must be used as a context manager.
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"ok": True, "result": {}}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _failure_urlopen(*args, **kwargs):
    """Raises URLError to simulate a network error."""
    raise urllib.error.URLError("simulated network failure")


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — Instantiation (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):

    def test_instantiate_with_credentials(self):
        """TelegramResearchAlerts instantiates with explicit bot_token and chat_id."""
        alerts = TelegramResearchAlerts(bot_token="token", chat_id="chat")
        self.assertIsInstance(alerts, TelegramResearchAlerts)

    def test_instantiate_without_credentials(self):
        """TelegramResearchAlerts instantiates without credentials (Keychain-deferred)."""
        alerts = TelegramResearchAlerts()
        self.assertIsInstance(alerts, TelegramResearchAlerts)

    def test_instantiate_with_none_credentials(self):
        """TelegramResearchAlerts accepts None for both params."""
        alerts = TelegramResearchAlerts(bot_token=None, chat_id=None)
        self.assertIsInstance(alerts, TelegramResearchAlerts)


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — source_promoted_alert() (6 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSourcePromotedAlert(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_source_promoted_returns_bool_on_success(self):
        """source_promoted_alert() returns bool (True) on success."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.source_promoted_alert(
                "source-abc", "PENDING", "CLEAN_INCLUDED"
            )
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_source_promoted_returns_bool_on_failure(self):
        """source_promoted_alert() returns bool (False) on network error."""
        with patch("urllib.request.urlopen", side_effect=_failure_urlopen):
            result = self.alerts.source_promoted_alert(
                "source-xyz", "PENDING", "CLEAN_INCLUDED"
            )
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_source_promoted_text_contains_source_id(self):
        """source_promoted_alert() builds text containing the source_id."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            body = req.data.decode()
            captured.append(json.loads(body)["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.source_promoted_alert("my-source-007", "PENDING", "CLEAN_INCLUDED")

        self.assertTrue(captured, "urlopen was never called")
        self.assertIn("my-source-007", captured[0])

    def test_source_promoted_text_contains_new_state(self):
        """source_promoted_alert() text includes the new state 'CLEAN_INCLUDED'."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            body = req.data.decode()
            captured.append(json.loads(body)["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertIn("CLEAN_INCLUDED", captured[0])

    def test_source_promoted_text_contains_promoted_emoji(self):
        """source_promoted_alert() text contains the 🔬 emoji."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            body = req.data.decode()
            captured.append(json.loads(body)["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertIn("🔬", captured[0])

    def test_source_promoted_sends_to_correct_url(self):
        """source_promoted_alert() POSTs to Telegram sendMessage URL."""
        captured_urls: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured_urls.append(req.full_url)
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertTrue(captured_urls)
        self.assertIn("sendMessage", captured_urls[0])
        self.assertIn("api.telegram.org", captured_urls[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — cash_drag_alert() (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCashDragAlert(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_cash_drag_returns_bool(self):
        """cash_drag_alert() returns bool."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.cash_drag_alert(95.0)
        self.assertIsInstance(result, bool)

    def test_cash_drag_text_contains_pct(self):
        """cash_drag_alert(95.0) text includes '95'."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.cash_drag_alert(95.0)

        self.assertIn("95", captured[0])

    def test_cash_drag_text_contains_warning_emoji(self):
        """cash_drag_alert() text contains ⚠️ emoji."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.cash_drag_alert(87.0)

        self.assertIn("⚠️", captured[0])

    def test_cash_drag_default_strategy_is_rs001(self):
        """cash_drag_alert() default strategy is RS-001."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.cash_drag_alert(60.0)

        self.assertIn("RS-001", captured[0])

    def test_cash_drag_custom_strategy(self):
        """cash_drag_alert(strategy='RS-002') text contains RS-002."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.cash_drag_alert(70.0, strategy="RS-002")

        self.assertIn("RS-002", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — owner_acceptance_signed_alert() (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestOwnerAcceptanceSignedAlert(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_owner_acceptance_returns_bool(self):
        """owner_acceptance_signed_alert() returns bool."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.owner_acceptance_signed_alert("Yurii")
        self.assertIsInstance(result, bool)

    def test_owner_acceptance_text_contains_owner_name(self):
        """owner_acceptance_signed_alert() text includes the owner name."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.owner_acceptance_signed_alert("Yurii")

        self.assertIn("Yurii", captured[0])

    def test_owner_acceptance_text_contains_checkmark_emoji(self):
        """owner_acceptance_signed_alert() text contains ✅ emoji."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.owner_acceptance_signed_alert("Alice")

        self.assertIn("✅", captured[0])

    def test_owner_acceptance_different_owner(self):
        """owner_acceptance_signed_alert() works with any owner name."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.owner_acceptance_signed_alert("Bob Investor")

        self.assertIn("Bob Investor", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 5 — research_exclusion_warning() (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestResearchExclusionWarning(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_exclusion_warning_returns_bool(self):
        """research_exclusion_warning() returns bool."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.research_exclusion_warning("RS-001", 45.0)
        self.assertIsInstance(result, bool)

    def test_exclusion_warning_text_contains_strategy(self):
        """research_exclusion_warning() text includes strategy name."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.research_exclusion_warning("RS-002", 33.0)

        self.assertIn("RS-002", captured[0])

    def test_exclusion_warning_text_contains_pct(self):
        """research_exclusion_warning() text includes source_needed_pct value."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.research_exclusion_warning("RS-001", 50.0)

        self.assertIn("50", captured[0])

    def test_exclusion_warning_text_contains_chart_emoji(self):
        """research_exclusion_warning() text contains 📊 emoji."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.research_exclusion_warning("RS-001", 25.0)

        self.assertIn("📊", captured[0])

    def test_exclusion_warning_text_contains_source_needed(self):
        """research_exclusion_warning() text mentions SOURCE_NEEDED."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.research_exclusion_warning("RS-001", 20.5)

        self.assertIn("SOURCE_NEEDED", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 6 — weekly_digest() (7 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyDigest(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_weekly_digest_returns_bool(self):
        """weekly_digest() returns bool."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.weekly_digest(rs001_shadow_pct=1.5, rs002_shadow_pct=0.8)
        self.assertIsInstance(result, bool)

    def test_weekly_digest_text_contains_rs001(self):
        """weekly_digest() text includes RS-001."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.weekly_digest(rs001_shadow_pct=2.3, rs002_shadow_pct=1.1)

        self.assertIn("RS-001", captured[0])

    def test_weekly_digest_text_contains_rs002(self):
        """weekly_digest() text includes RS-002."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.weekly_digest(rs001_shadow_pct=2.3, rs002_shadow_pct=1.1)

        self.assertIn("RS-002", captured[0])

    def test_weekly_digest_text_contains_rs001_value(self):
        """weekly_digest() text contains the RS-001 shadow pct value."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.weekly_digest(rs001_shadow_pct=10.5, rs002_shadow_pct=0.0)

        self.assertIn("10.5", captured[0])

    def test_weekly_digest_text_contains_rs002_value(self):
        """weekly_digest() text contains the RS-002 shadow pct value."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.weekly_digest(rs001_shadow_pct=0.0, rs002_shadow_pct=7.3)

        self.assertIn("7.3", captured[0])

    def test_weekly_digest_text_contains_digest_emoji(self):
        """weekly_digest() text contains 📋 emoji."""
        captured: list[str] = []

        def capture_urlopen(req, **kwargs):
            captured.append(json.loads(req.data.decode())["text"])
            return _success_urlopen()

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            self.alerts.weekly_digest()

        self.assertIn("📋", captured[0])

    def test_weekly_digest_default_params(self):
        """weekly_digest() works with default (zero) parameters."""
        with patch("urllib.request.urlopen", return_value=_success_urlopen()):
            result = self.alerts.weekly_digest()
        self.assertIsInstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Group 7 — Error handling (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_network_error_returns_false_not_exception(self):
        """Network error during send returns False, does not raise."""
        with patch("urllib.request.urlopen", side_effect=_failure_urlopen):
            result = self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")
        self.assertFalse(result)

    def test_network_error_does_not_raise(self):
        """Network error is swallowed — no exception propagates to caller."""
        with patch("urllib.request.urlopen", side_effect=_failure_urlopen):
            try:
                result = self.alerts.cash_drag_alert(91.5)
                self.assertFalse(result)
            except Exception as exc:
                self.fail(f"Unexpected exception raised: {exc}")

    def test_keychain_error_returns_false(self):
        """Keychain read failure returns False, does not raise."""
        alerts_no_creds = TelegramResearchAlerts()  # no explicit credentials
        with patch(
            "spa_core.alerts.telegram_research_alerts._read_keychain",
            side_effect=EnvironmentError("Keychain not available"),
        ):
            result = alerts_no_creds.cash_drag_alert(80.0)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Group 8 — Credential resolution (2 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCredentialResolution(unittest.TestCase):

    def test_explicit_credentials_used_directly(self):
        """When explicit token/chat_id provided, Keychain subprocess is NOT called."""
        alerts = TelegramResearchAlerts(bot_token="my-token", chat_id="my-chat")

        with patch("urllib.request.urlopen", return_value=_success_urlopen()), \
             patch("subprocess.run") as mock_subprocess:
            alerts.weekly_digest()

        mock_subprocess.assert_not_called()

    def test_keychain_subprocess_called_for_missing_credentials(self):
        """When no credentials provided, subprocess.run is called for Keychain."""
        alerts = TelegramResearchAlerts()  # no explicit credentials

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "fake-token\n"

        with patch(
            "spa_core.alerts.telegram_research_alerts.subprocess.run",
            return_value=mock_proc,
        ) as mock_run, \
             patch("urllib.request.urlopen", return_value=_success_urlopen()):
            alerts.weekly_digest()

        mock_run.assert_called()
        # Verify it was called with the 'security' command (Keychain)
        first_call_args = mock_run.call_args_list[0][0][0]  # first positional arg = command list
        self.assertIn("security", first_call_args)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
