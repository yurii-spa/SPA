"""Guard against the recurrence class: a test writing the owner's LIVE alert state.

Incident (2026-07-31, cycle #58, card ``agent-killswitch-test-messages-owner-chat``).
``SPA Tests`` on ``main`` was red for two independent reasons — the cycle-#55
live-Telegram guard fired at teardown of a kill-switch test and of a de-risk
cycle test.  Fixing only the transport would have left the deeper half in place:
``push_policy`` resolves ``data/telegram/`` from its own ``__file__``, so those
tests were writing the **live edge-trigger state** that decides whether the owner
is ever told anything.  Since ``prev_state == "bad"`` means *"still bad →
silent"*, a test run could mute the next genuine kill-switch alert; and because
the branch depends on that leftover state, the guard error itself was
order-dependent (whole file → error, same test alone → pass).

Every property below has a POSITIVE CONTROL: it is proved by making the call
that *would* have written the live directory and observing that the live
directory did not change.  A guard nobody tests is the same "claim about a check
that never ran" this repo keeps closing (#29/#31/#35–#38, #40).

Hermetic: no Keychain, no network, no live repo state (the live file is only
ever hashed, never written).  Stdlib + unittest only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from spa_core.telegram import push_policy

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_LIVE_TG_DIR = _REPO_ROOT / "data" / "telegram"

# The live guard installed by conftest — the one that actually protects the run.
_live_guard = sys.modules.get("spa_push_state_guard")


def _load_guard():
    """Load push_state_guard.py by path — the way both conftests load it."""
    spec = importlib.util.spec_from_file_location(
        "spa_push_state_guard_under_test", _HERE / "push_state_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


def _fingerprint(path: Path) -> str:
    """Content hash of a file, or a marker when it does not exist.

    Read-only by construction: the live alert state is never opened for writing
    by this module.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "<absent>"
    except OSError as exc:  # pragma: no cover — unreadable is still "not written by us"
        return f"<unreadable: {type(exc).__name__}>"


class TestGuardIsInstalled(unittest.TestCase):
    """The conftest guard must be active for the whole session."""

    def test_conftest_installed_the_guard(self):
        self.assertIsNotNone(
            _live_guard,
            "conftest did not load push_state_guard — the suite writes live alert state",
        )
        self.assertTrue(
            _live_guard.is_installed(),
            f"push_state_guard is not in effect: {_live_guard.unavailable_reason()}",
        )

    def test_default_dir_is_not_the_live_one(self):
        """Positive control: prove the redirect actually replaced the default."""
        self.assertNotEqual(
            Path(push_policy._DEFAULT_TG_DIR).resolve(),
            _LIVE_TG_DIR.resolve(),
            "push_policy still defaults to the live data/telegram — guard is inert",
        )
        self.assertEqual(
            Path(push_policy._DEFAULT_TG_DIR), _live_guard.sandbox_dir()
        )

    def test_guard_remembers_the_real_directory(self):
        """The live dir is captured, not guessed — so the redirect is provable."""
        self.assertEqual(Path(_live_guard.live_dir()).resolve(), _LIVE_TG_DIR.resolve())

    def test_both_conftests_share_one_guard_module(self):
        """The two conftests must not each exec their own copy.

        Two copies would mean two sandboxes and two ``_DEFAULT_TG_DIR``
        assignments racing each other — the last one wins and the other root's
        ``reset()`` would clear a directory nobody writes.  Same lesson as
        ``telegram_guard``: the module is looked up in ``sys.modules`` first.
        """
        conftests = [
            _HERE / "conftest.py",
            _REPO_ROOT / "tests" / "conftest.py",
        ]
        for cf in conftests:
            with self.subTest(conftest=str(cf)):
                src = cf.read_text(encoding="utf-8")
                self.assertIn("spa_push_state_guard", src)
                self.assertIn(
                    'sys.modules.get("spa_push_state_guard")', src,
                    f"{cf} does not reuse the shared guard module",
                )
                self.assertIn("push_state_guard.install()", src)


class TestLiveStateIsNeverWritten(unittest.TestCase):
    """The class this module exists for: a default-dir push must not land live."""

    def test_push_critical_without_data_dir_lands_in_the_sandbox(self):
        """POSITIVE CONTROL — the exact call that made CI red.

        ``threat_reactor`` / ``cycle_runner`` push with no ``data_dir``.  This
        makes that same call and proves (a) the live file is byte-identical
        afterwards and (b) the state really was written — to the sandbox.
        """
        before = _fingerprint(_LIVE_TG_DIR / "push_state.json")

        # send=False keeps the transport out of it; the GATE still runs and the
        # state write — the thing under test — happens exactly as in production.
        push_policy.push_critical(
            "kill_switch", "CRITICAL", "guard probe", "guard probe", send=False
        )

        after = _fingerprint(_LIVE_TG_DIR / "push_state.json")
        self.assertEqual(
            before, after,
            "a default-dir push_critical() modified the LIVE data/telegram/push_state.json",
        )

        sandbox_state = Path(_live_guard.sandbox_dir()) / "push_state.json"
        self.assertTrue(
            sandbox_state.is_file(),
            "no state was written at all — the probe proved nothing",
        )
        doc = json.loads(sandbox_state.read_text(encoding="utf-8"))
        self.assertIn("kill_switch", doc.get("events", {}))

    def test_live_state_has_no_probe_residue(self):
        """The live file must not contain this module's probe key at all."""
        live = _LIVE_TG_DIR / "push_state.json"
        if not live.is_file():
            self.skipTest("no live push_state.json on this checkout")
        raw = live.read_text(encoding="utf-8")
        self.assertNotIn("guard probe", raw)


class TestGuardMechanics(unittest.TestCase):
    """The guard's own contract, on a private instance (never the live one)."""

    def setUp(self):
        self.guard = _load_guard()
        self.orig_default = push_policy._DEFAULT_TG_DIR

    def tearDown(self):
        push_policy._DEFAULT_TG_DIR = self.orig_default

    def test_install_redirects_and_reports_itself(self):
        self.guard.install()
        self.assertTrue(self.guard.is_installed())
        self.assertNotEqual(
            Path(push_policy._DEFAULT_TG_DIR).resolve(), _LIVE_TG_DIR.resolve()
        )

    def test_reset_clears_state_between_tests(self):
        """Leftover edge-state is what made the failure order-dependent."""
        self.guard.install()
        sbox = Path(self.guard.sandbox_dir())
        (sbox / "push_state.json").write_text('{"events": {"x": 1}}', encoding="utf-8")
        (sbox / "digest_queue.json").write_text("[]", encoding="utf-8")
        self.guard.reset()
        self.assertFalse((sbox / "push_state.json").exists())
        self.assertFalse((sbox / "digest_queue.json").exists())

    def test_reset_reasserts_a_redirect_that_was_undone(self):
        """Self-healing: a reload or stray patch must not silently un-guard.

        ``telegram_guard.install()`` had to learn exactly this after another
        conftest reassigned ``urlopen`` and threw the guard away.
        """
        self.guard.install()
        push_policy._DEFAULT_TG_DIR = _LIVE_TG_DIR          # simulate the drift
        self.assertFalse(self.guard.is_installed())          # measured, not assumed
        self.guard.reset()
        self.assertTrue(self.guard.is_installed())

    def test_is_installed_is_false_when_the_default_is_live(self):
        """Fail-CLOSED: the guard reports its real state, never a stale claim."""
        self.guard.install()
        push_policy._DEFAULT_TG_DIR = _LIVE_TG_DIR
        self.assertFalse(self.guard.is_installed())

    def test_sandbox_is_reused_not_recreated(self):
        """install() is idempotent — a new dir per call would strand state."""
        self.guard.install()
        first = self.guard.sandbox_dir()
        self.guard.install()
        self.assertEqual(first, self.guard.sandbox_dir())


class TestNoLiveResidueFromTheFixedTests(unittest.TestCase):
    """The three senders that made CI red must not reach the transport again."""

    def _assert_contains(self, path: Path, needle: str) -> None:
        """assertIn without dumping the whole file into the CI log on failure."""
        src = path.read_text(encoding="utf-8")
        self.assertTrue(
            needle in src,
            f"{path.name} no longer stubs the owner-notification transport: "
            f"expected to find {needle!r}",
        )

    def test_threat_reactor_test_stubs_the_sender(self):
        # 2026-08-05: the stub literal changed with the _send_telegram API
        # (optional dedup_key — the alerts_undelivered fix); the guard now pins
        # the new capture-lambda. The guarded property is IDENTICAL: the
        # owner-notification transport is replaced by an in-memory capture and
        # restored on teardown.
        target = _REPO_ROOT / "tests" / "test_kill_switch_eval_path.py"
        self._assert_contains(
            target, "lambda msg, dedup_key=None: self.sent_alerts.append(msg)"
        )
        self._assert_contains(target, "self._tr._send_telegram = self._orig_send")

    def test_derisk_e2e_stubs_the_transport(self):
        self._assert_contains(
            _HERE / "test_cycle_derisk_e2e.py",
            'monkeypatch.setattr(push_policy, "_send", _capture)',
        )

    def test_perf_budget_stubs_the_transport(self):
        """The third sender, found only after the state was sandboxed.

        ``tests/test_perf_budget.py`` benches the real cycle; on clean
        ``origin/main`` it reached the owner's chat, but only in runs where the
        live edge-state happened not to silence it — which is why cycle #57's
        full slice reported two red files and not three.
        """
        self._assert_contains(
            _REPO_ROOT / "tests" / "test_perf_budget.py",
            'monkeypatch.setattr(push_policy, "_send", _capture)',
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
