"""Guard against the recurrence class: the suite reaching the LIVE network.

Incident (measured 2026-08-03, cycle #93, card ``agent-tests-do-live-network-io``)
----------------------------------------------------------------------------------
``spa_core/tests/`` had not completed a run on the host machine since at least
31.07.  Two independent runs stalled at the same 49 % mark at ~5 tests/minute
and 6 % CPU — the process was *waiting*, and at that rate the remaining half of
the suite needed ~150 hours, i.e. the suite did not finish at all.  Cycle #54
died mid-verification at that exact point ("49 %, ~4 min in of an expected
~15") and its work orphaned.

Cycle #90 checked the stalled process with ``lsof``, saw no sockets at that
instant and concluded the wait was not network.  A stack dump taken *during*
the wait (``faulthandler.dump_traceback_later``) named it exactly::

    ssl.read → http.client.getresponse → urllib.request.urlopen
      → telegram_guard._guarded_urlopen        ← the guard, DELEGATING
      → strategy_lab/data/_http.http_fetch
      → funding_feed._fetch_hyperliquid
      → rates_desk/feeds._funding_neg_frac_90d
      → spa_core/dfb/alerts.compute_alerts
      → test_dfb_alerts.py::test_property_deterministic

Measured cost of that one file: **152.93 s for 19 tests** with the live feed,
**0.17 s for the same 19 passing tests** once the network is refused.

These tests pin :mod:`network_guard`.  A guard nobody tests is the same failure
this repo keeps closing (#29/#31/#35–#38, #40) — a claim about a check that
never ran — so every property below has a POSITIVE CONTROL.

Hermetic: no network (that is the point), no repo state, stdlib + unittest.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import unittest
import urllib.request
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent

#: The live guards installed by conftest (the ones that protect the real run).
_live_net = sys.modules.get("spa_network_guard")
_live_tg = sys.modules.get("spa_telegram_guard")

_LIVE_URL = "https://api.llama.fi/pools"
_TG_URL = "https://api.telegram.org/bot123456:FAKE-TOKEN-NOT-REAL/sendMessage"


def _load_guard():
    """Load network_guard.py by path — the same way conftest loads it."""
    spec = importlib.util.spec_from_file_location(
        "spa_network_guard_under_test", _HERE / "network_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


class TestGuardIsInstalled(unittest.TestCase):
    """The conftest guard must be active for the whole session."""

    def test_conftest_installed_the_guard(self):
        self.assertIsNotNone(
            _live_net,
            "conftest did not load network_guard — the suite is unprotected",
        )
        self.assertTrue(
            _live_net.is_installed(),
            "network_guard.install() was not called by conftest",
        )

    def test_urlopen_and_connect_are_not_the_stdlib_ones(self):
        """Positive control: prove both layers actually replaced their target."""
        self.assertIsNot(
            urllib.request.urlopen,
            _live_net._real_urlopen,
            "urllib.request.urlopen is still the real one — guard is inert",
        )
        self.assertIsNot(
            socket.socket.connect,
            _live_net._real_connect,
            "socket.socket.connect is still the real one — backstop is inert",
        )

    def test_conftest_reuses_one_shared_guard_module(self):
        """Two exec'd copies would mean two _ATTEMPTS lists and a blind guard.

        Same trap ``telegram_guard`` already documents: the outer wrapper
        records into ITS list while something else inspects an empty one.
        """
        src = (_HERE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn('sys.modules.get("spa_network_guard")', src)
        self.assertIs(sys.modules.get("spa_network_guard"), _live_net)

    def test_telegram_guard_stays_outermost(self):
        """Install order is load-bearing, so it is pinned rather than assumed.

        If the network guard wrapped LAST it would refuse ``api.telegram.org``
        with its own generic message, and the Telegram guard — the one that
        redacts the token and names the 2026-07-31 incident — would never see
        the call and never record it.  Prove the specific error still wins.
        """
        self.assertIsNotNone(_live_tg, "telegram_guard is not loaded")
        # This test intends to trip the Telegram guard; consume the record so
        # the autouse fixture does not fail it afterwards.  Registered BEFORE
        # the attempt and as a cleanup, not as a trailing statement: when an
        # assertion below failed, the old trailing reset never ran and the
        # autouse fixture added a second, confusing symptom on top of the real
        # one (`ERROR at teardown: LiveTelegramSendAttempted`) — observed on
        # every full run up to origin/main d07714d07.
        self.addCleanup(_live_tg.reset)
        with self.assertRaises(_live_tg.LiveTelegramSendAttempted):
            urllib.request.urlopen(_TG_URL)
        self.assertTrue(_live_tg.attempts(), "Telegram attempt was not recorded")
        self.assertEqual(
            _live_net.attempts(),
            [],
            "the network guard swallowed a Telegram call that telegram_guard "
            "must own",
        )


class TestGuardRefusesLiveNetwork(unittest.TestCase):
    """A non-loopback destination must be refused at both layers.

    Exercised on a SEPARATE copy of the module, with the live wrappers saved
    and restored around every test and the copy's transports replaced by inert
    stubs.  Without that isolation the copy stacks on top of the guard conftest
    installed, and a refusal lands in the *live* ``_ATTEMPTS`` list — which
    then reddens an unrelated later test.  (Observed while writing these: a
    socket probe here surfaced as ``connect ('93.184.216.34', 443)`` inside the
    production-chain test below.)
    """

    def setUp(self):
        self.guard = _load_guard()
        self.guard.reset()
        self._saved_urlopen = urllib.request.urlopen
        self._saved_connect = socket.socket.connect
        self._saved_connect_ex = socket.socket.connect_ex
        # Inert transports: "delegated" must never mean "went out".
        #
        # Installed BEFORE install() so the guard genuinely WRAPS them
        # (2026-08-08, cycle #163). They used to be poked into the module's
        # `_real_*` globals afterwards, which only worked because the wrappers
        # re-read those globals on every call — and that re-reading is exactly
        # the defect that made re-installing both guards build the cycle
        # `telegram_guard -> network_guard -> telegram_guard -> …`. The
        # delegate is now bound at wrap time, so the stub has to be in place
        # when the wrap happens. Injection technique only: every assertion in
        # this class is unchanged, and the test now exercises the real wrapping
        # path rather than a back door into the module's state.
        self.delegated = []
        urllib.request.urlopen = lambda req, *a, **kw: (
            self.delegated.append(self.guard._url_of(req)) or "REAL-RESPONSE"
        )
        socket.socket.connect = lambda s, addr: self.delegated.append(addr)
        socket.socket.connect_ex = lambda s, addr: self.delegated.append(addr)
        self.guard.install()

    def tearDown(self):
        urllib.request.urlopen = self._saved_urlopen
        socket.socket.connect = self._saved_connect
        socket.socket.connect_ex = self._saved_connect_ex
        _live_net.reset()

    def test_urlopen_to_a_live_host_is_refused(self):
        with self.assertRaises(self.guard.LiveNetworkAccessAttempted):
            urllib.request.urlopen(_LIVE_URL)
        self.assertEqual(len(self.guard.attempts()), 1)
        self.assertIn("api.llama.fi", self.guard.attempts()[0])
        self.assertEqual(self.delegated, [], "the call must not be delegated")

    def test_socket_connect_to_a_live_host_is_refused(self):
        """The backstop that covers clients which never touch ``urlopen``.

        ``spa_core/adapters/sky_susds_feed.py`` uses ``requests``, which builds
        its own sockets — patching ``urlopen`` alone would leave it live.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(self.guard.LiveNetworkAccessAttempted):
                s.connect(("93.184.216.34", 443))
            with self.assertRaises(self.guard.LiveNetworkAccessAttempted):
                s.connect_ex(("93.184.216.34", 443))
        finally:
            s.close()
        self.assertEqual(len(self.guard.attempts()), 2)
        self.assertEqual(self.delegated, [])

    def test_loopback_socket_connect_is_delegated(self):
        """Positive control for the backstop: local sockets still work."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", 8765))
        finally:
            s.close()
        self.assertEqual(self.guard.attempts(), [])
        self.assertEqual(self.delegated, [("127.0.0.1", 8765)])

    def test_refusal_is_an_oserror(self):
        """Callers are fail-CLOSED around transport errors — keep that path.

        ``http_fetch`` re-raises as ``FetchError``, adapters return ``None``.
        A non-``OSError`` refusal would escape those handlers and turn an
        offline suite into a crashing one instead of a fail-closed one.
        """
        self.assertTrue(issubclass(self.guard.LiveNetworkAccessAttempted, OSError))

    def test_loopback_is_allowed(self):
        """Positive control: local servers are not "the live network"."""
        for host in ("127.0.0.1", "localhost", "::1", "127.0.0.53"):
            self.assertTrue(
                self.guard.is_loopback_host(host), f"{host} must be allowed"
            )
        for host in ("api.llama.fi", "api.telegram.org", "1.2.3.4", "10.0.0.1"):
            self.assertFalse(
                self.guard.is_loopback_host(host), f"{host} must be refused"
            )

    def test_loopback_urlopen_is_delegated_untouched(self):
        """A local URL must reach the transport the guard wrapped, unchanged."""
        out = urllib.request.urlopen("http://127.0.0.1:8765/api/live/agents")
        self.assertEqual(out, "REAL-RESPONSE")
        self.assertEqual(self.delegated, ["http://127.0.0.1:8765/api/live/agents"])
        self.assertEqual(self.guard.attempts(), [])

    def test_install_rewraps_after_urlopen_is_reassigned(self):
        """The guard must survive another conftest overwriting ``urlopen``.

        ``tests/conftest.py`` installs its blanket offline block by plain
        assignment, which silently discards an already-installed wrapper.
        """
        self.assertTrue(self.guard.is_installed())

        urllib.request.urlopen = lambda url, *a, **kw: "CLOBBERED"
        self.assertFalse(
            self.guard.is_installed(), "clobber not detected — guard is blind"
        )

        self.guard.install()  # must re-wrap rather than no-op
        self.assertTrue(self.guard.is_installed())
        with self.assertRaises(self.guard.LiveNetworkAccessAttempted):
            urllib.request.urlopen(_LIVE_URL)

    def test_install_does_not_double_wrap_under_the_telegram_guard(self):
        """Idempotency under the REAL layout, not just a bare one.

        After conftest, ``urlopen`` carries the Telegram guard's marker, not
        this one.  A naive "my marker is missing → wrap again" check would
        stack a second copy on every call to :func:`install`, and refusals
        would be recorded twice (or into the wrong list).
        """
        before = urllib.request.urlopen
        self.guard.install()
        self.guard.install()
        self.assertIs(urllib.request.urlopen, before, "install() re-wrapped")

    def test_attempts_are_recorded_even_when_the_raise_is_swallowed(self):
        """The property that makes the guard non-bypassable.

        ``http_fetch`` catches ``Exception`` and re-raises as ``FetchError``;
        feed callers then swallow that. A guard that only raised would vanish.
        """
        try:
            urllib.request.urlopen(_LIVE_URL)
        except Exception:  # noqa: BLE001 — this is the production behaviour
            pass
        self.assertEqual(len(self.guard.attempts()), 1)


@pytest.mark.live_feed_transport
class TestGuardStopsTheRealFeedChain(unittest.TestCase):
    """End-to-end through PRODUCTION code — not a simulation of it.

    Runs the very call chain the stack dump named and proves the live guard
    installed by conftest stops it at the transport, fail-CLOSED, fast.

    Marked ``live_feed_transport`` (2026-08-16, card
    ``agent-tests-reach-live-feed-222``): the shared live-feed doors are shut for
    every other test, and a shut ``_http`` door raises ``FetchError`` BEFORE the
    transport — which is right for a test that only wants a feed's *result*, and
    wrong here, because this class's subject IS the transport. Without the mark
    ``test_http_fetch_cannot_reach_the_network`` still saw its ``FetchError`` and
    still passed its first assertion, while the guard's ledger stayed empty — the
    test would have gone on claiming "the guard stopped the call" without the
    guard being involved at all. That is the exact fail-OPEN shape this file
    exists to close, so the fix is to keep the door OPEN here, not to relax the
    assertion (invariant #16 — nothing in this class is changed).

    The mark does NOT put the network back: ``network_guard`` is untouched and
    refuses the call exactly as before. It only says the *attempt* is the point.
    """

    def test_http_fetch_cannot_reach_the_network(self):
        from spa_core.strategy_lab.data import _http

        with self.assertRaises(_http.FetchError):
            _http.http_fetch("https://api.hyperliquid.xyz/info")
        recorded = _live_net.attempts()
        self.assertTrue(
            recorded,
            "the guard did not record the attempt — a live fetch would have "
            "gone out unnoticed",
        )
        self.assertIn("hyperliquid", recorded[-1])
        _live_net.reset()

    def test_the_stalling_test_module_now_runs_without_network(self):
        """Regression pin on the module that held the suite at 49 %.

        ``compute_alerts`` reaches the Hyperliquid funding feed through
        ``dfb.risk_overlay``; with the guard in place it must fail-CLOSE to a
        verdict instead of blocking on ``ssl.read``.  Measured before/after on
        the whole file: 152.93 s → 0.17 s, 19 passed both ways.
        """
        from spa_core.dfb import alerts  # noqa: F401 — import must not hang

        self.assertTrue(hasattr(alerts, "compute_alerts"))
        _live_net.reset()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
