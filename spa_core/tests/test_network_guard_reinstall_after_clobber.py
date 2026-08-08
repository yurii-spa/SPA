"""The network guard survives having ``urlopen`` replaced under it.

Incident (measured 2026-08-08, cycle #163, card
``inbox-retsidiv-setevoi-strazh-snova-krasneet-t``)
---------------------------------------------------------------------------
Three tests were red in every full run and green in isolation::

    spa_core/tests/test_network_guard_ledger_is_per_test.py::test_a_a_refused_call_lands_in_the_live_ledger
    spa_core/tests/test_network_guard_ledger_is_per_test.py::test_c_the_previous_tests_refusal_was_archived_not_discarded
    spa_core/tests/test_no_live_network_in_tests.py::TestGuardStopsTheRealFeedChain::test_http_fetch_cannot_reach_the_network

This was a RECURRENCE: the closed card ``agent-network-guard-attempts-never-reset``
(04.08) fixed the ledger's *scope*; nothing defended the guard's *presence*.

Reproduced with ONE neighbour rather than the whole suite::

    pytest spa_core/tests/test_network_guard_ledger_is_per_test.py \
           spa_core/tests/test_no_live_network_in_tests.py \
           tests/test_adapter_registry.py

Two defects, and the second is why the first went unnoticed:

1. ``tests/conftest.py`` line 58 does ``urllib.request.urlopen =
   _blocked_urlopen`` — a plain assignment that discards the chain — and then
   line 171 re-installs **only** ``telegram_guard``.  Result:
   ``telegram_guard -> _blocked_urlopen``, with ``network_guard`` gone before
   the first test ran.  The network stayed blocked (the sibling block is also
   fail-CLOSED), so nothing looked wrong; only this guard's ledger went empty.
2. ``network_guard._urlopen_layer_present()`` accepted **either** guard's
   marker on the outermost callable.  "Some guard is on top" is a different
   question from "my layer is in the chain", and the two came apart exactly
   here: ``is_installed()`` returned ``True`` with the layer absent,
   ``install()`` took its early return, and ``TestGuardIsInstalled`` stayed
   green.  The fail-OPEN shape this repo keeps closing (#29/#31/#35–#38, #40,
   #84) — a guard answering ITS question and being read as answering the
   needed one.

Every test below is a positive control: each one reddens on the un-fixed
module.  Hermetic — a FRESH copy of the guard, its own transports, no repo
state, no network (stdlib + unittest only).
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: The live guard installed by conftest — used only to assert the wiring.
_live_net = sys.modules.get("spa_network_guard")


def _load_guard():
    """A FRESH copy of network_guard.py — never the installed one."""
    spec = importlib.util.spec_from_file_location(
        "spa_network_guard_clobber_under_test", _HERE / "network_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


class _GuardSandbox(unittest.TestCase):
    """Install a fresh guard copy over an inert transport, and restore after.

    The live wrappers are saved and put back verbatim, so nothing here can
    leak into the rest of the run — the mistake this file's own subject made.
    """

    def setUp(self):
        self.guard = _load_guard()
        self._saved_urlopen = urllib.request.urlopen
        self.calls = []

        def _inert_urlopen(req, *args, **kwargs):
            self.calls.append(req)
            raise OSError("inert transport — no call goes out in this test")

        self._inert = _inert_urlopen
        urllib.request.urlopen = _inert_urlopen  # type: ignore[assignment]
        self.guard.install()

    def tearDown(self):
        urllib.request.urlopen = self._saved_urlopen  # type: ignore[assignment]

    def _clobber(self):
        """Exactly what tests/conftest.py:58 does — a plain assignment."""

        def _blocked_urlopen(url, *args, **kwargs):
            raise OSError("offline — network disabled in test suite")

        urllib.request.urlopen = _blocked_urlopen  # type: ignore[assignment]
        return _blocked_urlopen


class TestPresenceIsMeasuredHonestly(_GuardSandbox):
    """`is_installed()` must answer about THIS guard's layer, nothing else."""

    def test_a_plain_assignment_is_seen_as_not_installed(self):
        self.assertTrue(self.guard.is_installed(), "sandbox did not install")
        self._clobber()
        self.assertFalse(
            self.guard.is_installed(),
            "the guard reports itself installed after urlopen was replaced — "
            "is_installed() is reading someone else's state",
        )

    def test_a_foreign_guard_marker_is_not_taken_as_our_own(self):
        """The exact 2026-08-08 shape: telegram_guard on top, us gone.

        This is the test that fails on the un-fixed module, where ANY guard
        marker counted as proof of presence.
        """
        blocked = self._clobber()

        def _foreign_wrapper(req, *args, **kwargs):
            return blocked(req, *args, **kwargs)

        # Stamp the OTHER guard's marker, and nothing of ours.
        setattr(_foreign_wrapper, "_spa_telegram_guard", True)
        setattr(_foreign_wrapper, "__wrapped__", blocked)
        urllib.request.urlopen = _foreign_wrapper  # type: ignore[assignment]

        self.assertFalse(
            self.guard.is_installed(),
            "a FOREIGN guard's marker was accepted as proof that this guard is "
            "in the chain — that is the fail-OPEN defect itself",
        )
        self.assertEqual(self.guard.missing_layers(), ["urlopen"])

    def test_being_wrapped_by_another_guard_still_counts_as_present(self):
        """The legitimate case must NOT be mistaken for a clobber.

        telegram_guard deliberately wraps this guard. If that read as absence,
        ensure_installed() would re-wrap on every test and report a clobber
        that never happened — noise which would get the report switched off.
        """
        inner = urllib.request.urlopen

        def _outer(req, *args, **kwargs):
            return inner(req, *args, **kwargs)

        setattr(_outer, "_spa_telegram_guard", True)
        setattr(_outer, "__wrapped__", inner)
        urllib.request.urlopen = _outer  # type: ignore[assignment]

        self.assertTrue(
            self.guard.is_installed(),
            "being wrapped by telegram_guard was mistaken for being gone",
        )
        self.assertEqual(self.guard.missing_layers(), [])


class TestTheGuardIsRestoredAndSaysSo(_GuardSandbox):
    """Repair is real, and it is loud."""

    def test_ensure_installed_puts_the_layer_back(self):
        self._clobber()
        restored = self.guard.ensure_installed("t.py::test_x")
        self.assertEqual(restored, ["urlopen"])
        self.assertTrue(self.guard.is_installed())

    def test_after_repair_a_live_call_is_refused_and_recorded(self):
        """The point of the repair: the ledger works again.

        This is the direct analogue of the three tests that were red.
        """
        self._clobber()
        self.guard.ensure_installed("t.py::test_x")
        self.guard.reset()
        with self.assertRaises(OSError):
            urllib.request.urlopen("https://api.llama.fi/pools")
        recorded = self.guard.attempts()
        self.assertTrue(recorded, "the restored guard recorded nothing")
        self.assertIn("api.llama.fi", recorded[-1])

    def test_the_clobber_is_recorded_not_silently_repaired(self):
        self.guard.clear_clobbers()
        self._clobber()
        self.guard.ensure_installed("t.py::test_x")
        self.assertEqual(self.guard.clobbers(), [("t.py::test_x", "urlopen")])

    def test_a_healthy_guard_is_not_reported_as_clobbered(self):
        """No crying wolf: nothing wrong ⇒ nothing recorded, nothing re-wrapped."""
        self.guard.clear_clobbers()
        before = urllib.request.urlopen
        self.assertEqual(self.guard.ensure_installed("t.py::test_ok"), [])
        self.assertEqual(self.guard.clobbers(), [])
        self.assertIs(
            urllib.request.urlopen, before, "the guard re-wrapped itself for nothing"
        )

    def test_repeated_ensure_does_not_stack_wrappers(self):
        """Guards against the obvious way to get this wrong.

        If presence were mis-measured, every call would add a layer until the
        chain blew the recursion limit.
        """
        self._clobber()
        for _ in range(20):
            self.guard.ensure_installed("t.py::test_x")
        self.assertLessEqual(len(self.guard.urlopen_chain()), 3)
        self.assertTrue(self.guard.is_installed())


class TestBothGuardsSurviveTheRepairTogether(unittest.TestCase):
    """The repair re-installs BOTH guards — that pair is where it went wrong.

    Testing the network guard alone missed this entirely: each guard read its
    delegate from a MODULE GLOBAL that ``install()`` rebinds, so re-installing
    both made each delegate to the other —
    ``telegram_guard -> network_guard -> telegram_guard -> …`` — and the next
    real call died with ``RecursionError``.  Measured on the full run: three
    ``test_chaos_resilience::test_self_heal_*`` tests, which reach
    ``urlopen`` through ``self_heal._served_cycle_age_hours``.

    Hermetic: fresh copies of BOTH guards, own transports, restored after.
    """

    def setUp(self):
        self.net = _load_guard()
        spec = importlib.util.spec_from_file_location(
            "spa_telegram_guard_clobber_under_test", _HERE / "telegram_guard.py"
        )
        self.tg = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(self.tg)                 # type: ignore[union-attr]
        self._saved = urllib.request.urlopen

        def _inert(req, *args, **kwargs):
            raise OSError("inert transport")

        urllib.request.urlopen = _inert  # type: ignore[assignment]
        # The real install order: network guard first, Telegram guard outermost.
        self.net.install()
        self.tg.install()

    def tearDown(self):
        urllib.request.urlopen = self._saved  # type: ignore[assignment]

    def _clobber_like_the_sibling_conftest(self):
        """tests/conftest.py: plain assignment, then ONLY telegram re-installed."""

        def _blocked(url, *args, **kwargs):
            raise OSError("offline — network disabled in test suite")

        urllib.request.urlopen = _blocked  # type: ignore[assignment]
        self.tg.install()

    def _repair_like_the_fixture(self):
        if self.net.ensure_installed("t.py::test_x"):
            self.tg.install()

    #: A LOOPBACK url, deliberately.  Only a call that is *delegated* all the
    #: way down walks the chain; a live host is refused by the network guard at
    #: the top and never reaches the cycle.  The three real casualties
    #: (``test_self_heal_*``) hit it through
    #: ``self_heal._served_cycle_age_hours``, which polls 127.0.0.1:8765 — an
    #: earlier version of this test used a live host and passed against the
    #: unfixed module, i.e. proved nothing.
    _LOOPBACK_URL = "http://127.0.0.1:8765/api/live/agents"

    def test_a_delegated_call_after_the_repair_does_not_recurse(self):
        """The regression itself. Without the fix this is a RecursionError."""
        self._clobber_like_the_sibling_conftest()
        self._repair_like_the_fixture()
        # The inert transport at the bottom raises OSError; reaching it at all
        # is the point. A RecursionError here is the defect, and it is NOT an
        # OSError, so it fails this test rather than being swallowed.
        with self.assertRaises(OSError):
            urllib.request.urlopen(self._LOOPBACK_URL)

    def test_the_chain_stays_finite_across_many_repairs(self):
        for _ in range(10):
            self._clobber_like_the_sibling_conftest()
            self._repair_like_the_fixture()
        chain = self.net.urlopen_chain()
        self.assertLess(
            len(chain), self.net._MAX_CHAIN_DEPTH,
            "the chain hit the walk limit — wrappers are stacking without bound",
        )
        with self.assertRaises(OSError):
            urllib.request.urlopen(self._LOOPBACK_URL)

    def test_after_the_repair_telegram_still_wins_over_the_network_guard(self):
        """Order is load-bearing: the specific message must beat the generic."""
        self._clobber_like_the_sibling_conftest()
        self._repair_like_the_fixture()
        self.net.reset()
        self.tg.reset()
        with self.assertRaises(self.tg.LiveTelegramSendAttempted):
            urllib.request.urlopen("https://api.telegram.org/bot123/sendMessage")
        self.assertTrue(self.tg.attempts(), "the Telegram guard recorded nothing")
        self.assertEqual(
            self.net.attempts(), [],
            "the network guard swallowed a call telegram_guard must own",
        )

    def test_after_the_repair_a_feed_call_is_still_refused_and_recorded(self):
        self._clobber_like_the_sibling_conftest()
        self._repair_like_the_fixture()
        self.net.reset()
        with self.assertRaises(OSError):
            urllib.request.urlopen("https://api.llama.fi/pools")
        self.assertTrue(self.net.attempts(), "the restored guard recorded nothing")


class TestTheRepairIsWiredIntoTheRun(unittest.TestCase):
    """Behaviour is pinned above; this pins the WIRING that invokes it.

    Without the fixture call, every test above still passes while the live run
    stays broken — the "deleting one call site left the feature dead in prod"
    class (#144).
    """

    def test_the_autouse_fixture_repairs_before_each_test(self):
        src = (_HERE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("network_guard.ensure_installed(request.node.nodeid)", src)

    def test_the_repair_restores_telegram_guard_to_outermost(self):
        """Re-installing puts us on top; the Telegram guard must be put back.

        Otherwise api.telegram.org would be refused with this guard's generic
        message and test_telegram_guard_stays_outermost would go red.
        """
        src = (_HERE / "conftest.py").read_text(encoding="utf-8")
        idx = src.find("network_guard.ensure_installed(request.node.nodeid)")
        self.assertGreater(idx, -1, "the repair call is gone")
        self.assertIn("telegram_guard.install()", src[idx:idx + 600])

    def test_the_live_guard_exposes_the_repair_api(self):
        self.assertIsNotNone(_live_net, "conftest did not install network_guard")
        for name in ("ensure_installed", "missing_layers", "clobbers", "urlopen_chain"):
            self.assertTrue(
                callable(getattr(_live_net, name, None)),
                f"the installed guard has no {name}() — the repair cannot run",
            )

    def test_telegram_guard_makes_its_link_walkable(self):
        """The chain walk only works if EVERY link points at what it wraps."""
        src = (_HERE / "telegram_guard.py").read_text(encoding="utf-8")
        self.assertIn('setattr(_guarded_urlopen, "__wrapped__", _base_urlopen)', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
