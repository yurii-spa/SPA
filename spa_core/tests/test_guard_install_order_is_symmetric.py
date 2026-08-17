"""Both ``urlopen`` guards work in EITHER install order, and re-installing
neither blinds one nor grows the chain.

Incident (measured 2026-08-17, card
``inbox-storozh-telegram-dverei-vybivaet-storozh``)
---------------------------------------------------------------------------
The card said the Telegram guard *replaces* ``urlopen`` by assignment and so
knocks the network guard out of the chain.  That mechanic was already dead —
cycle #163 made :func:`telegram_guard.install` wrap.  Measured on the shipped
code before this file existed::

    ng.install(); tg.install()  ->  ng.is_installed() == True    # not knocked out

The live defect was the mirror image, one function over.
``telegram_guard.is_installed()`` read its marker off the OUTERMOST callable
only, while ``network_guard`` walks ``__wrapped__`` down the chain.  So the
install order decided the answer::

    tg.install(); ng.install()  ->  tg.is_installed() == False   # though tg IS in the chain

That state is not hypothetical: ``spa_core/tests/conftest.py`` calls
``telegram_guard.install()`` every time it repairs the network guard
(``_scope_network_guard_ledger``), and repairing puts ``network_guard`` on top.
With ``is_installed()`` answering ``False``, ``install()`` wrapped a SECOND
time and built ``tg -> ng -> tg -> real`` — the very
``telegram_guard -> network_guard -> telegram_guard`` shape whose
``RecursionError`` cycle #163 closed, with TWO live Telegram layers in it.

Measured honestly, so the next reader does not over-trust this file: through
the real conftest path the pile settles at four links and stops, because the
clobber that triggers a repair (``tests/conftest.py``'s plain assignment)
destroys the chain first.  Driving ``network_guard`` to re-wrap without that
reset grows it two links per cycle (measured 3, 5, 7, 9, 11, 13), which is the
same defect seen without its brake.  The damage that IS reachable every run is
the pair of live Telegram layers and an ``is_installed()`` that denies its own
presence.

Two things had to become two questions instead of one:

* :func:`telegram_guard.is_installed` — "my layer is in the chain, at any
  depth".  Governs idempotence.
* :func:`telegram_guard.is_outermost` — "my layer sees the call first".
  Governs whether ``api.telegram.org`` gets this guard's specific,
  token-redacting report instead of the network guard's generic refusal.

Neither guard is relaxed here — each door keeps catching its own case, and
that is asserted in BOTH orders.

Which tests are positive controls, measured against the un-fixed module rather
than assumed (``4 failed, 4 passed``):

* redden on the un-fixed guard —
  ``TestOrderNetworkThenTelegram::test_both_guards_report_themselves_installed``
  (it gained the ``is_outermost`` assertion),
  ``TestOrderTelegramThenNetwork::test_telegram_guard_knows_it_is_installed_while_buried``,
  ``::test_repair_restores_the_specific_telegram_report``,
  ``::test_the_buried_copy_is_retired_not_left_recording``;
* regression pins, green before and after — the two
  ``..._does_not_grow_the_chain`` tests and the two "each door catches its own
  case" tests.  They are here to stay green, not to prove the bug; see the
  chain-length note above for why the un-fixed pile self-limits.

Hermetic: FRESH copies of both guard modules (never the ones ``conftest``
installed), an inert transport, saved/restored wrappers, no repo state, no
network, no wall clock.  Stdlib + unittest only.
"""
from __future__ import annotations

import importlib.util
import socket
import unittest
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_TG_URL = "https://api.telegram.org/bot123456:FAKE-TOKEN-NOT-REAL/sendMessage"
_LIVE_URL = "https://api.llama.fi/pools"


def _load(name: str, filename: str):
    """A FRESH copy of a guard module — never the one conftest installed."""
    spec = importlib.util.spec_from_file_location(name, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


class _BothGuardsSandbox(unittest.TestCase):
    """Fresh copies of both guards over an inert transport, restored after.

    The live wrappers (``urlopen`` and both socket entry points) are saved and
    put back verbatim, so nothing here leaks into the rest of the run — the
    mistake ``test_no_live_network_in_tests`` documents having made once.
    """

    def setUp(self):
        self.tg = _load("spa_telegram_guard_order_under_test", "telegram_guard.py")
        self.ng = _load("spa_network_guard_order_under_test", "network_guard.py")
        self._saved_urlopen = urllib.request.urlopen
        self._saved_connect = socket.socket.connect
        self._saved_connect_ex = socket.socket.connect_ex
        self.delegated = []

        def _inert_urlopen(req, *args, **kwargs):
            self.delegated.append(req)
            return "REAL-RESPONSE"

        # Installed BEFORE either install() so the guards genuinely WRAP it
        # (cycle #163: the delegate is bound at wrap time, not re-read).
        urllib.request.urlopen = _inert_urlopen
        socket.socket.connect = lambda s, addr: self.delegated.append(addr)
        socket.socket.connect_ex = lambda s, addr: self.delegated.append(addr)
        self.base_urlopen = _inert_urlopen

    def tearDown(self):
        urllib.request.urlopen = self._saved_urlopen
        socket.socket.connect = self._saved_connect
        socket.socket.connect_ex = self._saved_connect_ex

    # -- helpers ---------------------------------------------------------
    def chain_len(self) -> int:
        return len(self.ng.urlopen_chain())

    def assert_telegram_door_owns_telegram(self):
        """The Telegram URL is refused BY THE TELEGRAM DOOR, and recorded."""
        self.tg.reset()
        self.ng.reset()
        with self.assertRaises(self.tg.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        self.assertTrue(
            self.tg.attempts(), "the Telegram attempt was not recorded"
        )
        self.assertNotIn(
            "FAKE-TOKEN-NOT-REAL",
            self.tg.attempts()[0],
            "the bot token must be redacted before it is recorded",
        )
        self.assertEqual(
            self.ng.attempts(),
            [],
            "the network guard swallowed a call telegram_guard must own",
        )
        self.assertEqual(self.delegated, [], "the call must not be delegated")
        self.tg.reset()

    def assert_network_door_owns_live_feed(self):
        """A non-Telegram live URL is refused BY THE NETWORK DOOR."""
        self.tg.reset()
        self.ng.reset()
        with self.assertRaises(self.ng.LiveNetworkAccessAttempted):
            urllib.request.urlopen(_LIVE_URL)
        self.assertTrue(self.ng.attempts(), "the refusal was not recorded")
        self.assertIn("api.llama.fi", self.ng.attempts()[0])
        self.assertEqual(
            self.tg.attempts(),
            [],
            "a non-Telegram URL must not land in the Telegram ledger",
        )
        self.assertEqual(self.delegated, [], "the call must not be delegated")
        self.ng.reset()

    def assert_socket_backstop_alive(self):
        """The layer that covers clients which never touch ``urlopen``."""
        self.ng.reset()
        probe = socket.socket()
        self.addCleanup(probe.close)
        with self.assertRaises(self.ng.LiveNetworkAccessAttempted):
            socket.socket.connect(probe, ("93.184.216.34", 443))
        self.ng.reset()


class TestOrderNetworkThenTelegram(_BothGuardsSandbox):
    """The canonical conftest order: ``network_guard`` first, Telegram on top."""

    def setUp(self):
        super().setUp()
        self.ng.install()
        self.tg.install()

    def test_both_guards_report_themselves_installed(self):
        self.assertTrue(self.ng.is_installed(), "network guard reports absent")
        self.assertTrue(self.tg.is_installed(), "Telegram guard reports absent")
        self.assertTrue(self.tg.is_outermost(), "Telegram guard is not on top")

    def test_each_door_catches_its_own_case(self):
        self.assert_telegram_door_owns_telegram()
        self.assert_network_door_owns_live_feed()
        self.assert_socket_backstop_alive()

    def test_reinstalling_does_not_grow_the_chain(self):
        before = self.chain_len()
        for _ in range(8):
            self.tg.install()
            self.ng.install()
        self.assertEqual(
            self.chain_len(),
            before,
            "repeated install() piled extra urlopen layers — the "
            "tg -> ng -> tg shape that produced RecursionError in #163",
        )
        self.assert_telegram_door_owns_telegram()
        self.assert_network_door_owns_live_feed()


class TestOrderTelegramThenNetwork(_BothGuardsSandbox):
    """The INVERTED order — the one that made ``is_installed()`` lie.

    Reached in real runs, not only synthetically: repairing the network guard
    (``network_guard.ensure_installed``) wraps whatever is current, which puts
    it above an already-installed Telegram guard.
    """

    def setUp(self):
        super().setUp()
        self.tg.install()
        self.ng.install()

    def test_telegram_guard_knows_it_is_installed_while_buried(self):
        """The defect itself: ``False`` here on the un-fixed module."""
        self.assertTrue(
            self.tg.is_installed(),
            "telegram_guard.is_installed() denied a layer that IS in the "
            "chain — install() would then wrap a second time",
        )
        self.assertFalse(
            self.tg.is_outermost(),
            "sanity: in this order the network guard is the one on top",
        )
        self.assertTrue(self.ng.is_installed(), "network guard reports absent")

    def test_network_door_still_catches_its_own_case(self):
        self.assert_network_door_owns_live_feed()
        self.assert_socket_backstop_alive()

    def test_repair_restores_the_specific_telegram_report(self):
        """What ``conftest`` does after a network-guard repair, in one call."""
        self.tg.install()
        self.assertTrue(self.tg.is_outermost())
        self.assertTrue(
            self.ng.is_installed(), "the repair unseated the network guard"
        )
        self.assert_telegram_door_owns_telegram()
        self.assert_network_door_owns_live_feed()
        self.assert_socket_backstop_alive()

    def test_repeated_repair_does_not_grow_the_chain(self):
        self.tg.install()          # promote to outermost (adds at most one link)
        settled = self.chain_len()
        for _ in range(8):
            self.tg.install()
            self.ng.install()
        self.assertEqual(
            self.chain_len(),
            settled,
            "repeated install() piled extra urlopen layers",
        )
        self.assert_telegram_door_owns_telegram()
        self.assert_network_door_owns_live_feed()

    def test_the_buried_copy_is_retired_not_left_recording(self):
        """Only ONE live Telegram layer, so one ledger owns the attempt.

        The buried wrapper stays physically in the chain — its delegate lives
        in another module's closure and re-pointing it from here is exactly
        the ``tg -> ng -> tg`` cycle #163 closed — so it is made inert
        instead.
        """
        self.tg.install()
        live = [
            link
            for link in self.ng.urlopen_chain()
            if self.tg._is_live_layer(link)
        ]
        self.assertEqual(
            len(live), 1, "more than one live Telegram layer is in the chain"
        )
        self.tg.reset()
        with self.assertRaises(self.tg.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        self.assertEqual(
            len(self.tg.attempts()),
            1,
            "one attempt was recorded more than once — a retired layer is "
            "still inspecting",
        )
        self.tg.reset()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
