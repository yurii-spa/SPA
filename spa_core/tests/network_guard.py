"""Test-suite guard: no test may reach the LIVE network.

Why this exists (2026-08-03, cycle #93, card ``agent-tests-do-live-network-io``)
------------------------------------------------------------------------------
``spa_core/tests/`` had **no offline block at all**.  Its sibling ``tests/``
has had one since SPA-D003 (``tests/conftest.py`` assigns
``urllib.request.urlopen = _blocked_urlopen`` at import time), but the larger
suite never got the same treatment: the only interception in
``spa_core/tests/conftest.py`` was :mod:`telegram_guard`, which by design
delegates **every non-Telegram URL to the real transport**, plus an 8-second
socket timeout that is armed only under ``SPA_ENV=ci``.

The cost was measured, not assumed.  ``spa_core/tests/`` has not completed a
run on the host machine since at least 31.07 (cards
``agent-verification-outlives-cycle-budget`` and the #90 addendum on this
card): both runs stopped progressing at the same 49 % mark at ~5 tests/minute
and 6 % CPU — i.e. **waiting**, not computing.  Cycle #90 checked the process
with ``lsof``, saw no sockets at that instant and concluded "the wait is not
network".  A stack dump taken *during* the wait (``faulthandler.
dump_traceback_later``) says otherwise::

    File ".../ssl.py", line 1138 in read                     ← blocked here
    File ".../http/client.py", line 1450 in getresponse
    File ".../urllib/request.py", line 189 in urlopen
    File ".../spa_core/tests/telegram_guard.py", line 136 in _guarded_urlopen
    File ".../spa_core/strategy_lab/data/_http.py", line 42 in http_fetch
    File ".../strategy_lab/data/funding_feed.py", line 538 in _fetch_hyperliquid
    File ".../strategy_lab/rates_desk/feeds.py", line 781 in _funding_neg_frac_90d
    File ".../spa_core/dfb/risk_overlay.py", line 155 in _build_risk
    File ".../spa_core/dfb/alerts.py", line 181 in hold_verdict
    File ".../spa_core/tests/test_dfb_alerts.py", line 133 in test_property_deterministic

``lsof`` missed it because the socket is only open for the fraction of the
wait spent in that one venue call; the connection itself is fast and the wait
is in ``ssl.read`` for a response body from a rate-limited venue.  The guard
above it is in the stack **delegating**: "only Telegram is intercepted" is
exactly the hole.

Design
------
Deliberately the same shape as :mod:`telegram_guard` — one chokepoint, an
explicit ``install()``, no import side effects, stdlib only:

* **Two layers, because one is not a chokepoint.**  78 non-test modules reach
  the network through ``urllib.request.urlopen``; one (``adapters/
  sky_susds_feed.py``) uses ``requests``, which never touches ``urlopen``.  So
  the guard wraps ``urlopen`` *and* ``socket.socket.connect`` /
  ``connect_ex``.  The socket layer is the backstop that makes the claim "no
  test reaches the live network" true rather than merely likely.
* **Loopback is allowed.**  Local servers, ``TestClient`` and the fund-API
  port checks are not live network; only non-loopback destinations are
  refused.
* **The refusal is an ``OSError``.**  Production code is deliberately
  fail-CLOSED around network calls (``http_fetch`` re-raises as ``FetchError``,
  adapters return ``None``), and that behaviour is what the suite should
  exercise.  Raising ``OSError`` makes "the network is off" indistinguishable
  from "the network failed", which is the documented contract of every caller
  — the same choice ``tests/conftest.py::_OfflineError`` already made.
* **Recorded as well as raised.**  Callers swallow broad exceptions, so a bare
  raise can vanish without trace — the "claims a check it never made" class
  this repo keeps closing (#29/#31/#35–#38, #40).  Every refusal is recorded
  so a test can assert on it and a diagnostic can print it.

**Not** an assertion-level change: no test is made less strict by this module.
A test that needs an HTTP response injects a fake fetcher/feed, which is what
``.claude/rules/adapters.md`` has required all along ("тесты инжектят
FakeFeed … не завязывать тесты на живую сеть").
"""
from __future__ import annotations

import socket
import urllib.request
from typing import Any, List, Tuple

#: Hosts that are not "the live network" — a local server is fair game.
_LOOPBACK_HOSTS = frozenset(("127.0.0.1", "::1", "localhost", "0.0.0.0", ""))


class LiveNetworkAccessAttempted(OSError):
    """Raised when a test tries to reach a non-loopback network address.

    Subclasses ``OSError`` on purpose: callers under test are fail-CLOSED
    around transport errors and must take exactly that path here.
    """

    reason = "offline — live network disabled in the test suite"

    #: This failure is DETERMINISTIC — it repeats identically for as long as
    #: the guard is installed, so a retry loop's backoff would be waiting for
    #: an event excluded by construction (measured: 26 s of a 28 s test, card
    #: ``agent-offline-suite-still-pays-full-retry-backoff``).  Transport
    #: helpers read this through
    #: :func:`spa_core.utils.retry_backoff.is_retryable` and skip the sleep —
    #: the failure path itself is unchanged, so no test is made less strict.
    #: Production is untouched: this is the ONLY place in the repo that sets
    #: the attribute, and this module is never imported by runtime code (pinned
    #: by ``test_retry_backoff_deterministic.py``).
    spa_deterministic_failure = True


#: Refusals recorded since the last :func:`reset`, newest last.
#:
#: Scoped to ONE test by the autouse fixture in ``conftest.py`` (2026-08-04,
#: cycle #115).  Before that it was session-cumulative, and the only assertion
#: that reads the live ledger — "the network guard did not swallow MY Telegram
#: call" — was silently comparing 2745 other tests' refusals against ``[]``.
_ATTEMPTS: List[str] = []

#: ``(nodeid, refusals)`` per test, in the order the tests ran — filled by
#: :func:`archive`.  Scoping the ledger must not make the refusals disappear:
#: they were never reported anywhere, and "nobody looks" is how this repo's
#: recurring failure class starts.  Kept for the end-of-run report instead.
_ARCHIVE: List[Tuple[str, List[str]]] = []

#: ``(nodeid, what_was_missing)`` for every test that found this guard knocked
#: out of the ``urlopen`` chain and had it re-installed by
#: :func:`ensure_installed`.  Recorded rather than silently repaired: a guard
#: that quietly puts itself back is indistinguishable from a guard that was
#: never attacked, and "repaired without telling anyone" is the same
#: fail-OPEN shape this module exists to close.  Printed by ``conftest``'s
#: end-of-run report.
_CLOBBERS: List[Tuple[str, str]] = []

_real_urlopen = None       # set by install()
_real_connect = None       # set by install()
_real_connect_ex = None    # set by install()

_URLOPEN_MARKER = "_spa_network_guard"
_CONNECT_MARKER = "_spa_network_guard_connect"

#: Marker stamped by :mod:`telegram_guard` on ITS wrapper.  This guard installs
#: first and the Telegram guard wraps it, so after a normal conftest load the
#: current ``urlopen`` carries the Telegram marker, not this one.
#:
#: Recognising it is NOT, however, evidence that this guard is still in the
#: chain — see :func:`_urlopen_layer_present`.
_TELEGRAM_MARKER = "_spa_telegram_guard"

#: How a wrapper points at the callable it delegates to.  Both guards set it,
#: which is what makes the chain walkable instead of guessable.
_WRAPPED_ATTR = "__wrapped__"

#: How deep to follow ``__wrapped__`` before declaring the chain pathological.
#: A cycle would otherwise hang the walk; the real chain is 2 links.
_MAX_CHAIN_DEPTH = 32


def attempts() -> List[str]:
    """Live-network refusals recorded since the last :func:`reset`."""
    return list(_ATTEMPTS)


def reset() -> None:
    """Forget recorded refusals (called between tests)."""
    _ATTEMPTS.clear()


def archive(nodeid: str) -> List[str]:
    """Move the current test's refusals into the archive and clear the ledger.

    Counterpart to :func:`telegram_guard.assert_no_live_telegram`, with one
    deliberate difference: this one does **not** fail the test.  A refused call
    is the guard working as designed — production code under test tried to
    reach a feed and got a fail-CLOSED ``OSError``, which is exactly the path
    the suite should exercise.  Failing on it would turn 102 currently-passing
    tests red for doing nothing wrong.

    What it must not do is let the refusals vanish, so they are kept and
    attributed here and printed by ``conftest``'s end-of-run report.  Measured
    on ``origin/main`` d07714d07: 2745 refusals from 102 tests, 2153 of them to
    ``yields.llama.fi``.
    """
    recorded = list(_ATTEMPTS)
    reset()
    if recorded:
        _ARCHIVE.append((nodeid, recorded))
    return recorded


def archived() -> List[Tuple[str, List[str]]]:
    """Per-test refusals archived so far, in the order the tests ran."""
    return [(nodeid, list(items)) for nodeid, items in _ARCHIVE]


def clear_archive() -> None:
    """Forget the archive.  Used by this guard's own hermetic tests."""
    _ARCHIVE.clear()


def _url_of(req: Any) -> str:
    """Best-effort URL of a urlopen argument (``Request`` object or ``str``)."""
    full_url = getattr(req, "full_url", None)
    if isinstance(full_url, str):
        return full_url
    try:
        return str(req)
    except Exception:  # noqa: BLE001 — never let the guard itself explode
        return "<unrepresentable request>"


def _host_of(url: str) -> str:
    """Hostname of a URL, lowercased, without port. ``""`` when unparseable."""
    try:
        from urllib.parse import urlsplit

        return (urlsplit(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def is_loopback_host(host: str) -> bool:
    """``True`` for addresses that are not the live network."""
    host = (host or "").lower()
    if host in _LOOPBACK_HOSTS:
        return True
    # 127.0.0.0/8 without importing ipaddress for the common case
    return host.startswith("127.")


def is_loopback_url(url: Any) -> bool:
    """``True`` when a urlopen argument does NOT address the live network.

    Public so a sibling layer can ask THIS module the question instead of
    re-deriving the rule (2026-08-17, card
    ``inbox-storozh-telegram-dverei-vybivaet-storozh``): ``offline_block`` is
    the mirror image of this guard — it refuses exactly what this one allows —
    and two copies of "what counts as loopback" would drift apart silently.
    No behaviour of this module changes; it is the composition of the two
    helpers the wrapper above already calls.
    """
    return is_loopback_host(_host_of(_url_of(url)))


def urlopen_chain() -> List[Any]:
    """The ``urlopen`` delegation chain, outermost first.

    Each guard's wrapper records what it wraps in ``__wrapped__``, so the chain
    can be *walked* rather than guessed at from whatever sits on top.
    """
    chain: List[Any] = []
    current = urllib.request.urlopen
    seen = set()
    for _ in range(_MAX_CHAIN_DEPTH):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, _WRAPPED_ATTR, None)
    return chain


def _urlopen_layer_present() -> bool:
    """``True`` when THIS guard's ``urlopen`` wrapper is still in the chain.

    It is not necessarily the OUTERMOST callable: :mod:`telegram_guard` wraps
    it on purpose (so Telegram keeps its own, more specific report), and that
    wrapper delegates everything else down to this one.

    Why this walks the chain instead of reading the top marker (2026-08-08,
    cycle #163, card ``inbox-retsidiv-setevoi-strazh-snova-krasneet-t``)
    ---------------------------------------------------------------------
    It used to accept EITHER marker on the outermost callable — including
    :mod:`telegram_guard`'s.  That is a different question than the one it was
    read as answering: "some guard is on top" is not "my layer is in the
    chain".  ``tests/conftest.py`` breaks the two apart in every full run —
    line 58 replaces ``urlopen`` by plain assignment (destroying the chain),
    then line 171 re-installs ONLY the Telegram guard.  The result is
    ``telegram_guard -> _blocked_urlopen`` with this guard gone, yet the old
    check reported ``True``: :func:`is_installed` lied, :func:`install` took
    its early return and did nothing, and ``TestGuardIsInstalled`` stayed
    green while the network layer was absent.  Three tests that read the
    ledger went red instead, and only in a full run — the exact fail-OPEN
    shape ("a guard answers ITS question and is read as answering the needed
    one") this repo keeps closing.
    """
    return any(
        getattr(link, _URLOPEN_MARKER, False) for link in urlopen_chain()
    )


def is_installed() -> bool:
    """``True`` when both layers of the guard are in effect."""
    return bool(
        _real_urlopen is not None
        and _urlopen_layer_present()
        and getattr(socket.socket.connect, _CONNECT_MARKER, False)
    )


def _refuse(what: str) -> LiveNetworkAccessAttempted:
    _ATTEMPTS.append(what)
    return LiveNetworkAccessAttempted(
        f"a test tried to reach the LIVE network ({what}). The suite runs "
        "offline by design — inject a fake fetcher/feed instead of calling out "
        "(see .claude/rules/adapters.md). Loopback addresses are allowed."
    )


def install() -> None:
    """Wrap ``urlopen`` and ``socket.connect``.  Idempotent against itself.

    Re-wraps whenever the current callable is not this guard, so it composes
    with whatever another conftest installed rather than throwing it away —
    the lesson :func:`telegram_guard.install` had to learn after a plain
    assignment in ``tests/conftest.py`` silently discarded it.

    Install order matters and is asserted by the guard's tests: this module
    goes in FIRST so :mod:`telegram_guard` ends up outermost and keeps
    reporting Telegram attempts with its own, more specific message.
    """
    global _real_urlopen, _real_connect, _real_connect_ex

    if not (_real_urlopen is not None and _urlopen_layer_present()):
        _real_urlopen = urllib.request.urlopen
        # Bound HERE, once, and read from the closure — never from the module
        # global (2026-08-08, cycle #163).  Re-installing rebinds the global, so
        # a wrapper that read it would start delegating to whatever was
        # installed LAST instead of what it actually wraps.  With both guards
        # doing that, a re-install of each produced a cycle —
        # `telegram_guard -> network_guard -> telegram_guard -> …` — and the
        # first real call died with RecursionError (measured: three
        # `test_chaos_resilience::test_self_heal_*` tests).  The delegate a
        # wrapper calls must be fixed at the moment it wraps.
        _base_urlopen = _real_urlopen

        def _guarded_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
            url = _url_of(req)
            if not is_loopback_host(_host_of(url)):
                raise _refuse(f"urlopen {url[:120]}")
            return _base_urlopen(req, *args, **kwargs)  # type: ignore[misc]

        setattr(_guarded_urlopen, _URLOPEN_MARKER, True)
        # Make the link walkable: _urlopen_layer_present() follows __wrapped__
        # rather than trusting whatever marker happens to be outermost.
        setattr(_guarded_urlopen, _WRAPPED_ATTR, _base_urlopen)
        urllib.request.urlopen = _guarded_urlopen  # type: ignore[assignment]

    if not (
        _real_connect is not None
        and getattr(socket.socket.connect, _CONNECT_MARKER, False)
    ):
        _real_connect = socket.socket.connect
        _real_connect_ex = socket.socket.connect_ex
        # Same closure discipline as the urlopen layer above — see there.
        _base_connect = _real_connect
        _base_connect_ex = _real_connect_ex

        def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) and address else ""
            if not is_loopback_host(str(host)):
                raise _refuse(f"connect {address!r}")
            return _base_connect(self, address)  # type: ignore[misc]

        def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) and address else ""
            if not is_loopback_host(str(host)):
                raise _refuse(f"connect_ex {address!r}")
            return _base_connect_ex(self, address)  # type: ignore[misc]

        setattr(_guarded_connect, _CONNECT_MARKER, True)
        setattr(_guarded_connect_ex, _CONNECT_MARKER, True)
        socket.socket.connect = _guarded_connect        # type: ignore[assignment]
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[assignment]


def missing_layers() -> List[str]:
    """Which of the two layers is NOT in effect right now, by name.

    Names the gap instead of collapsing it to a bool, so a report can say what
    was knocked out rather than only that something was.
    """
    missing: List[str] = []
    if not (_real_urlopen is not None and _urlopen_layer_present()):
        missing.append("urlopen")
    if not (
        _real_connect is not None
        and getattr(socket.socket.connect, _CONNECT_MARKER, False)
    ):
        missing.append("socket.connect")
    return missing


def ensure_installed(nodeid: str = "") -> List[str]:
    """Re-install any layer that was knocked out, and RECORD that it happened.

    Called before every test by ``conftest``'s autouse fixture.  Two things
    make this a repair rather than a papering-over:

    * it is loud — the clobber is appended to :data:`_CLOBBERS` and printed at
      the end of the run, because a guard that silently restores itself is
      indistinguishable from one that was never attacked;
    * it is not the only defence — the layer it restores is the one that
      actually refuses the call, so restoring it changes what the suite
      *enforces*, not merely what it reports.

    Returns the layers that had to be restored (empty when nothing was wrong).
    """
    missing = missing_layers()
    if missing:
        install()
        _CLOBBERS.append((nodeid, ",".join(missing)))
    return missing


def clobbers() -> List[Tuple[str, str]]:
    """Tests that found this guard knocked out, in the order they ran."""
    return [(nodeid, what) for nodeid, what in _CLOBBERS]


def clear_clobbers() -> None:
    """Forget recorded clobbers.  Used by this guard's own hermetic tests."""
    _CLOBBERS.clear()


def uninstall() -> None:
    """Restore the real callables. Used by the guard's own positive controls."""
    global _real_urlopen, _real_connect, _real_connect_ex
    if _real_urlopen is not None:
        urllib.request.urlopen = _real_urlopen  # type: ignore[assignment]
        _real_urlopen = None
    if _real_connect is not None:
        socket.socket.connect = _real_connect  # type: ignore[assignment]
        _real_connect = None
    if _real_connect_ex is not None:
        socket.socket.connect_ex = _real_connect_ex  # type: ignore[assignment]
        _real_connect_ex = None
