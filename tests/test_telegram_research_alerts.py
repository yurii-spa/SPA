"""
MP-1318 (v9.34) — Tests for TelegramResearchAlerts.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_telegram_research_alerts -v
Also compatible with pytest.

Phase-1 Telegram rebuild: TelegramResearchAlerts is RETIRED as a Telegram push.
Its public alert methods build the same text but route it to the digest queue via
``spa_core.telegram.push_policy._enqueue_digest`` and now return ``False`` (the
research view is on-demand, it no longer interrupts the owner). Tests therefore
capture the composed text from the digest enqueue call instead of a urlopen body.

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

import os
import sys
import unittest
from unittest.mock import patch

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.alerts.telegram_research_alerts import TelegramResearchAlerts


# ── shared helpers ────────────────────────────────────────────────────────────

def _make_alerts(token: str = "test-bot-token", chat_id: str = "test-chat-123") -> TelegramResearchAlerts:
    """Instantiate TelegramResearchAlerts with explicit credentials (no Keychain needed)."""
    return TelegramResearchAlerts(bot_token=token, chat_id=chat_id)


def _patch_digest(captured: list[str]):
    """
    Patch push_policy._enqueue_digest (the call site used by the retired _send)
    and append the composed message text to ``captured``.

    The module calls ``push_policy._enqueue_digest(tg_dir, item)`` where ``item``
    is a dict whose ``body`` carries the composed alert text.
    """
    def fake_enqueue(tg_dir, item, *args, **kwargs):
        captured.append(item.get("body", ""))

    return patch(
        "spa_core.telegram.push_policy._enqueue_digest",
        side_effect=fake_enqueue,
    )


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
        """source_promoted_alert() returns bool — retired push returns False (routes to digest)."""
        result = self.alerts.source_promoted_alert(
            "source-abc", "PENDING", "CLEAN_INCLUDED"
        )
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_source_promoted_returns_bool_on_failure(self):
        """source_promoted_alert() returns bool (False) even if digest route errors."""
        with patch(
            "spa_core.telegram.push_policy._enqueue_digest",
            side_effect=RuntimeError("digest boom"),
        ):
            result = self.alerts.source_promoted_alert(
                "source-xyz", "PENDING", "CLEAN_INCLUDED"
            )
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_source_promoted_text_contains_source_id(self):
        """source_promoted_alert() builds digest text containing the source_id."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.source_promoted_alert("my-source-007", "PENDING", "CLEAN_INCLUDED")

        self.assertTrue(captured, "digest was never enqueued")
        self.assertIn("my-source-007", captured[0])

    def test_source_promoted_text_contains_new_state(self):
        """source_promoted_alert() digest text includes the new state 'CLEAN_INCLUDED'."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertIn("CLEAN_INCLUDED", captured[0])

    def test_source_promoted_text_contains_promoted_emoji(self):
        """source_promoted_alert() digest text contains the 🔬 emoji."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertIn("🔬", captured[0])

    def test_source_promoted_sends_to_correct_url(self):
        """source_promoted_alert() routes to the digest queue (no Telegram URL POST)."""
        captured: list[str] = []
        with _patch_digest(captured):
            result = self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")

        self.assertFalse(result)
        self.assertTrue(captured, "digest was never enqueued")


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — cash_drag_alert() (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCashDragAlert(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_cash_drag_returns_bool(self):
        """cash_drag_alert() returns bool (False — retired push)."""
        result = self.alerts.cash_drag_alert(95.0)
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_cash_drag_text_contains_pct(self):
        """cash_drag_alert(95.0) digest text includes '95'."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.cash_drag_alert(95.0)

        self.assertIn("95", captured[0])

    def test_cash_drag_text_contains_warning_emoji(self):
        """cash_drag_alert() digest text contains ⚠️ emoji."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.cash_drag_alert(87.0)

        self.assertIn("⚠️", captured[0])

    def test_cash_drag_default_strategy_is_rs001(self):
        """cash_drag_alert() default strategy is RS-001."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.cash_drag_alert(60.0)

        self.assertIn("RS-001", captured[0])

    def test_cash_drag_custom_strategy(self):
        """cash_drag_alert(strategy='RS-002') digest text contains RS-002."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.cash_drag_alert(70.0, strategy="RS-002")

        self.assertIn("RS-002", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — owner_acceptance_signed_alert() (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestOwnerAcceptanceSignedAlert(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_owner_acceptance_returns_bool(self):
        """owner_acceptance_signed_alert() returns bool (False — retired push)."""
        result = self.alerts.owner_acceptance_signed_alert("Yurii")
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_owner_acceptance_text_contains_owner_name(self):
        """owner_acceptance_signed_alert() digest text includes the owner name."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.owner_acceptance_signed_alert("Yurii")

        self.assertIn("Yurii", captured[0])

    def test_owner_acceptance_text_contains_checkmark_emoji(self):
        """owner_acceptance_signed_alert() digest text contains ✅ emoji."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.owner_acceptance_signed_alert("Alice")

        self.assertIn("✅", captured[0])

    def test_owner_acceptance_different_owner(self):
        """owner_acceptance_signed_alert() works with any owner name."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.owner_acceptance_signed_alert("Bob Investor")

        self.assertIn("Bob Investor", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 5 — research_exclusion_warning() (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestResearchExclusionWarning(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_exclusion_warning_returns_bool(self):
        """research_exclusion_warning() returns bool (False — retired push)."""
        result = self.alerts.research_exclusion_warning("RS-001", 45.0)
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_exclusion_warning_text_contains_strategy(self):
        """research_exclusion_warning() digest text includes strategy name."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.research_exclusion_warning("RS-002", 33.0)

        self.assertIn("RS-002", captured[0])

    def test_exclusion_warning_text_contains_pct(self):
        """research_exclusion_warning() digest text includes source_needed_pct value."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.research_exclusion_warning("RS-001", 50.0)

        self.assertIn("50", captured[0])

    def test_exclusion_warning_text_contains_chart_emoji(self):
        """research_exclusion_warning() digest text contains 📊 emoji."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.research_exclusion_warning("RS-001", 25.0)

        self.assertIn("📊", captured[0])

    def test_exclusion_warning_text_contains_source_needed(self):
        """research_exclusion_warning() digest text mentions SOURCE_NEEDED."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.research_exclusion_warning("RS-001", 20.5)

        self.assertIn("SOURCE_NEEDED", captured[0])


# ─────────────────────────────────────────────────────────────────────────────
# Group 6 — weekly_digest() (7 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyDigest(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_weekly_digest_returns_bool(self):
        """weekly_digest() returns bool (False — retired push)."""
        result = self.alerts.weekly_digest(rs001_shadow_pct=1.5, rs002_shadow_pct=0.8)
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_weekly_digest_text_contains_rs001(self):
        """weekly_digest() digest text includes RS-001."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.weekly_digest(rs001_shadow_pct=2.3, rs002_shadow_pct=1.1)

        self.assertIn("RS-001", captured[0])

    def test_weekly_digest_text_contains_rs002(self):
        """weekly_digest() digest text includes RS-002."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.weekly_digest(rs001_shadow_pct=2.3, rs002_shadow_pct=1.1)

        self.assertIn("RS-002", captured[0])

    def test_weekly_digest_text_contains_rs001_value(self):
        """weekly_digest() digest text contains the RS-001 shadow pct value."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.weekly_digest(rs001_shadow_pct=10.5, rs002_shadow_pct=0.0)

        self.assertIn("10.5", captured[0])

    def test_weekly_digest_text_contains_rs002_value(self):
        """weekly_digest() digest text contains the RS-002 shadow pct value."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.weekly_digest(rs001_shadow_pct=0.0, rs002_shadow_pct=7.3)

        self.assertIn("7.3", captured[0])

    def test_weekly_digest_text_contains_digest_emoji(self):
        """weekly_digest() digest text contains 📋 emoji."""
        captured: list[str] = []
        with _patch_digest(captured):
            self.alerts.weekly_digest()

        self.assertIn("📋", captured[0])

    def test_weekly_digest_default_params(self):
        """weekly_digest() works with default (zero) parameters (returns False)."""
        result = self.alerts.weekly_digest()
        self.assertIsInstance(result, bool)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Group 7 — Error handling (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.alerts = _make_alerts()

    def test_network_error_returns_false_not_exception(self):
        """A failing digest route returns False, does not raise."""
        with patch(
            "spa_core.telegram.push_policy._enqueue_digest",
            side_effect=RuntimeError("digest boom"),
        ):
            result = self.alerts.source_promoted_alert("src", "PENDING", "CLEAN_INCLUDED")
        self.assertFalse(result)

    def test_network_error_does_not_raise(self):
        """A digest-route error is swallowed — no exception propagates to caller."""
        with patch(
            "spa_core.telegram.push_policy._enqueue_digest",
            side_effect=RuntimeError("digest boom"),
        ):
            try:
                result = self.alerts.cash_drag_alert(91.5)
                self.assertFalse(result)
            except Exception as exc:
                self.fail(f"Unexpected exception raised: {exc}")

    def test_keychain_error_returns_false(self):
        """Retired push never reads Keychain — still returns False, does not raise."""
        alerts_no_creds = TelegramResearchAlerts()  # no explicit credentials
        result = alerts_no_creds.cash_drag_alert(80.0)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Group 8 — Credential resolution (2 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCredentialResolution(unittest.TestCase):

    def test_explicit_credentials_used_directly(self):
        """When explicit token/chat_id provided, Keychain subprocess is NOT called."""
        alerts = TelegramResearchAlerts(bot_token="my-token", chat_id="my-chat")

        with patch("subprocess.run") as mock_subprocess:
            alerts.weekly_digest()

        mock_subprocess.assert_not_called()

    def test_keychain_subprocess_not_needed_for_retired_push(self):
        """Retired push routes to digest with no credentials — Keychain subprocess NOT called."""
        alerts = TelegramResearchAlerts()  # no explicit credentials

        with patch(
            "spa_core.alerts.telegram_research_alerts.subprocess.run",
        ) as mock_run:
            result = alerts.weekly_digest()

        self.assertFalse(result)
        mock_run.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
