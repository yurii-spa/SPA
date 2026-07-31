"""Guard against the recurrence class: a test messaging the owner for real.

Incident (2026-07-31, owner card «вот такое сообщение приходит в час несколько
раз»).  The owner kept receiving the production alert *«🚨 Не удалось проверить,
был ли сегодня цикл»* while the production watchdog was healthy and silent —
``data/telegram/push_state.json`` never left ``cycle_gap: ok`` and
``/tmp/spa_cycle_gap_monitor.log`` said ``✅ No gap`` on every 5-minute run.  The
sender was the test suite: ``test_cycle_gap_monitor`` called
``run_cycle_gap_monitor(dry_run=False)`` with no stubbed sender, so the alert
took the real path into the owner's chat.  Autonomous cycles run the suite
almost continuously — hence "several times an hour".

These tests pin the guard itself.  A guard nobody tests is the same failure this
repo keeps closing (#29/#31/#35–#38, #40): a claim about a check that never ran.
So every property below has a POSITIVE CONTROL — it is proved by making a call
that *would* have gone out and observing that it does not.

Hermetic: no Keychain, no network, no repo state.  Stdlib + unittest only.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent


def _load_guard():
    """Load telegram_guard.py by path — same way both conftests load it."""
    spec = importlib.util.spec_from_file_location(
        "spa_telegram_guard_under_test", _HERE / "telegram_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


# The live guard installed by conftest (the one that actually protects the run).
_live_guard = sys.modules.get("spa_telegram_guard")

_TG_URL = "https://api.telegram.org/bot123456:FAKE-TOKEN-NOT-REAL/sendMessage"


class TestGuardIsInstalled(unittest.TestCase):
    """The conftest guard must be active for the whole session."""

    def test_conftest_installed_the_guard(self):
        self.assertIsNotNone(
            _live_guard,
            "conftest did not load telegram_guard — the suite is unprotected",
        )
        self.assertTrue(
            _live_guard.is_installed(),
            "telegram_guard.install() was not called by conftest",
        )

    def test_urlopen_is_not_the_stdlib_one(self):
        """Positive control: prove the patch actually replaced urlopen."""
        self.assertIsNot(
            urllib.request.urlopen,
            _live_guard._real_urlopen,
            "urllib.request.urlopen is still the real one — guard is inert",
        )

    def test_both_conftests_share_one_guard_module(self):
        """The two conftests must not each exec their own copy.

        Found while building this guard: a repo-root ``pytest`` run loads both
        ``spa_core/tests/conftest.py`` and ``tests/conftest.py``.  With a copy
        each there would be two ``_ATTEMPTS`` lists and two stacked urlopen
        wrappers — the outer one raises and records into ITS list, while the
        other conftest's fixture inspects an empty one and reports nothing.  A
        guard that silently stops reporting is exactly the failure class it
        exists to prevent, so the single shared instance is pinned here.
        """
        conftests = [
            _HERE / "conftest.py",
            _HERE.parent.parent / "tests" / "conftest.py",
        ]
        for cf in conftests:
            src = cf.read_text(encoding="utf-8")
            self.assertIn(
                'sys.modules.get("spa_telegram_guard")',
                src,
                f"{cf} exec's its own guard copy instead of reusing the shared one",
            )
        # And the shared instance is the one actually installed.
        self.assertIs(sys.modules.get("spa_telegram_guard"), _live_guard)

    def test_install_rewraps_after_urlopen_is_reassigned(self):
        """The guard must survive another conftest overwriting ``urlopen``.

        ``tests/conftest.py`` installs a blanket offline block by plain
        assignment, which threw an already-installed guard away outright — and
        silently, since ``install()`` used to consider itself done.  Reproduce
        the clobber and prove the guard comes back on top, still delegating
        non-Telegram traffic to whatever it wrapped.
        """
        guard = _load_guard()
        saved = urllib.request.urlopen
        try:
            delegated = []
            guard.install()
            self.assertTrue(guard.is_installed())

            # Another conftest clobbers it (exactly what tests/conftest.py does).
            def _blocked(url, *a, **kw):
                delegated.append(guard._url_of(url))
                raise OSError("offline — network disabled in test suite")

            urllib.request.urlopen = _blocked
            self.assertFalse(
                guard.is_installed(), "clobber not detected — guard is blind"
            )

            guard.install()  # must re-wrap rather than no-op
            self.assertTrue(guard.is_installed())

            with self.assertRaises(guard.LiveTelegramSendAttempted):
                urllib.request.urlopen(_TG_URL)
            self.assertEqual(len(guard.attempts()), 1)

            # Non-Telegram traffic still reaches the clobberer, not the network.
            with self.assertRaises(OSError):
                urllib.request.urlopen("https://api.llama.fi/pools")
            self.assertEqual(delegated, ["https://api.llama.fi/pools"])
        finally:
            urllib.request.urlopen = saved


class TestGuardBlocksTelegram(unittest.TestCase):
    """A Telegram URL must raise AND be recorded; anything else passes through."""

    def setUp(self):
        self.guard = _load_guard()
        self.delegated = []
        # Stand in for the real urlopen so "delegates everything else" can be
        # proved without touching the network.
        self.guard._real_urlopen = lambda req, *a, **kw: self.delegated.append(
            getattr(req, "full_url", req)
        ) or "REAL-RESPONSE"
        self._saved = urllib.request.urlopen
        # install() is a no-op once _real_urlopen is set, so wire the guarded
        # callable in the same way install() does.
        self.guard._real_urlopen = self.guard._real_urlopen  # keep the stub
        self.guard.install()  # idempotent: returns immediately
        urllib.request.urlopen = self._make_guarded()

    def tearDown(self):
        urllib.request.urlopen = self._saved

    def _make_guarded(self):
        """Rebuild install()'s closure against this test's stub transport."""
        guard = self.guard
        real = guard._real_urlopen

        def _guarded(req, *a, **kw):
            url = guard._url_of(req)
            if guard.TELEGRAM_HOST in url:
                redacted = guard._redact(url)
                guard._ATTEMPTS.append(redacted)
                raise guard.LiveTelegramSendAttempted(redacted)
            return real(req, *a, **kw)

        return _guarded

    def test_telegram_url_raises(self):
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            urllib.request.urlopen(urllib.request.Request(_TG_URL, data=b"{}"))

    def test_telegram_url_is_recorded(self):
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        self.assertEqual(len(self.guard.attempts()), 1)

    def test_recorded_attempt_never_contains_the_token(self):
        """Invariant #7 — a real token must never reach a log or CI output."""
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        recorded = self.guard.attempts()[0]
        self.assertNotIn("FAKE-TOKEN-NOT-REAL", recorded)
        self.assertIn("<redacted>", recorded)
        self.assertIn("sendMessage", recorded, "the method must stay visible")

    def test_non_telegram_url_is_delegated_untouched(self):
        """Positive control: the guard must not disturb the rest of the suite."""
        out = urllib.request.urlopen("https://api.llama.fi/pools")
        self.assertEqual(out, "REAL-RESPONSE")
        self.assertEqual(self.delegated, ["https://api.llama.fi/pools"])
        self.assertEqual(self.guard.attempts(), [])

    def test_assert_no_live_telegram_is_silent_when_clean(self):
        self.guard.reset()
        self.guard.assert_no_live_telegram("some::test")  # must not raise

    def test_assert_no_live_telegram_fails_after_an_attempt(self):
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        with self.assertRaises(self.guard.LiveTelegramSendAttempted) as ctx:
            self.guard.assert_no_live_telegram("some::test")
        self.assertIn("some::test", str(ctx.exception))

    def test_attempts_are_cleared_after_being_reported(self):
        """Otherwise one offender would redden every later test in the run."""
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            self.guard.assert_no_live_telegram()
        self.assertEqual(self.guard.attempts(), [])

    def test_swallowed_exception_is_still_reported(self):
        """The property that makes the guard non-bypassable.

        Production senders are deliberately fail-safe: ``_post_message`` catches
        broad exceptions and returns ``False``.  A guard that only raised would
        therefore be swallowed and report nothing — the exact "claimed a check
        it never made" class.  Simulate that swallow and prove the after-test
        assertion still fires.
        """
        try:
            urllib.request.urlopen(_TG_URL)
        except Exception:  # noqa: BLE001 — this is the production behaviour
            pass
        with self.assertRaises(self.guard.LiveTelegramSendAttempted):
            self.guard.assert_no_live_telegram()


class TestGuardCatchesTheRealSenderChain(unittest.TestCase):
    """End-to-end through PRODUCTION code — not a simulation of it.

    Runs the real ``telegram_client._post_message`` with fake credentials (so no
    Keychain is needed and the test is identical on CI) and proves the live
    guard installed by conftest stops it at the transport.
    """

    def test_post_message_cannot_reach_the_network(self):
        from spa_core.alerts import telegram_client as tc

        with patch.object(tc, "get_bot_token", return_value="123:FAKE"), \
             patch.object(tc, "get_chat_id", return_value="42"), \
             patch.object(tc, "_rate_limit_ok", return_value=True), \
             patch.object(tc, "_record_history"):
            sent = tc._post_message({"text": "guard probe — must never leave"})

        # The production sender is fail-safe, so it reports False rather than
        # propagating — which is precisely why the recording layer exists.
        self.assertFalse(sent, "the guard must prevent delivery")
        recorded = _live_guard.attempts()
        self.assertTrue(
            recorded,
            "the guard did not record the attempt — a real send would have "
            "gone out unnoticed",
        )
        self.assertIn("api.telegram.org", recorded[0])
        self.assertNotIn("FAKE", recorded[0], "token must be redacted")
        # Consume the record: this test *intends* to trip the guard, so the
        # autouse fixture must not fail it afterwards.
        _live_guard.reset()


class TestCycleGapTestsAreStubbed(unittest.TestCase):
    """Structural pin on the file that caused the incident.

    The suite-wide guard turns a live send into a red test; this pin keeps the
    offending module hermetic in the first place, so removing the stubs is
    caught as an explicit regression rather than as a confusing failure
    elsewhere.
    """

    def test_module_stubs_both_senders(self):
        src = (_HERE / "test_cycle_gap_monitor.py").read_text(encoding="utf-8")
        self.assertIn("def setUpModule()", src)
        self.assertIn(
            "spa_core.paper_trading.cycle_gap_monitor._send_telegram_alert", src
        )
        self.assertIn(
            "spa_core.paper_trading.cycle_gap_monitor._resolve_cycle_gap", src
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
