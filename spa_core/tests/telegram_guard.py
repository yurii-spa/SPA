"""Test-suite guard: no test may reach the LIVE Telegram API.

Why this exists (2026-07-31, owner card «вот такое сообщение приходит в час
несколько раз»)
------------------------------------------------------------------------------
The owner was receiving the production alert *«🚨 Не удалось проверить, был ли
сегодня цикл»* several times an hour while the production watchdog was healthy
and silent the whole time (``data/telegram/push_state.json`` never left
``cycle_gap: ok``).  The sender was the **test suite**:
``spa_core/tests/test_cycle_gap_monitor.py::TestRunCycleGapMonitorBehavior::
test_never_raises_corrupt_status_json`` called ``run_cycle_gap_monitor`` with
``dry_run=False`` and no stubbed sender, so the call went
``_send_telegram_alert → push_policy.push_critical → telegram_client._post_message
→ HTTPS POST to api.telegram.org`` — into the owner's real chat.  Autonomous
orchestrator cycles run the suite almost continuously, which is exactly the
observed cadence.

Patching those two call sites would fix the symptom.  This module fixes the
**class**: any test, anywhere in the repo, that reaches the live Telegram API
fails loudly and names itself.

Design
------
* **One chokepoint.** Every Telegram sender in the repo (≈20 modules:
  ``telegram_client``, ``alert_dispatcher``, ``bot``, ``telegram_manager``,
  ``site_freshness_monitor``, …) builds a ``https://api.telegram.org/bot…`` URL
  and calls ``urllib.request.urlopen``.  No module imports ``urlopen`` by name
  (``from urllib.request import urlopen`` — zero hits repo-wide), so patching
  ``urllib.request.urlopen`` covers all of them, present and future.
* **Only Telegram is intercepted.** Any other URL is delegated to the real
  ``urlopen`` untouched, so this guard changes nothing about the rest of the
  suite.
* **Not swallowable — fail-CLOSED.** Raising alone is not enough: production
  senders are deliberately fail-safe and catch broad exceptions
  (``_post_message`` returns ``False`` on *any* failure), so a raise can be
  silently absorbed and the guard would report nothing — the "claims a check it
  never made" failure class this repo keeps closing (#29/#31/#35–#38, #40).  So
  every attempt is also **recorded**, and :func:`assert_no_live_telegram` fails
  the test from the outside, after it returns, whether or not the raise
  survived.

Stdlib only.  Import has no side effects; call :func:`install` explicitly.
"""
from __future__ import annotations

import urllib.request
from typing import Any, List

#: Hostname that identifies a live Telegram Bot API call.
TELEGRAM_HOST = "api.telegram.org"


class LiveTelegramSendAttempted(AssertionError):
    """Raised when a test tries to POST to the live Telegram Bot API."""


#: Attempts recorded since the last :func:`reset`.  Each entry is a redacted
#: URL — the bot token is never stored (invariant #7: no secrets in files, and
#: pytest prints this list on failure).
_ATTEMPTS: List[str] = []

_real_urlopen = None  # set by install(): the callable the guard delegates to

#: Attribute stamped on the guarded callable so install() can recognise itself
#: even after another conftest reassigned urllib.request.urlopen.
_MARKER = "_spa_telegram_guard"

#: How a wrapper points at the callable it delegates to.  Both guards set it,
#: which is what makes the delegation chain walkable instead of guessable.
_WRAPPED_ATTR = "__wrapped__"

#: Per-wrapper mutable state, stamped on the wrapper itself (never a module
#: global — see the closure note in :func:`install`).  Holds ``retired``: a
#: wrapper that has been superseded by a newer copy of this guard stops
#: inspecting and becomes a pure pass-through.
_STATE_ATTR = "_spa_telegram_guard_state"

#: How deep to follow ``__wrapped__`` before declaring the chain pathological.
#: A cycle would otherwise hang the walk; the healthy chain is 2-3 links.
_MAX_CHAIN_DEPTH = 32


def urlopen_chain() -> List[Any]:
    """The ``urlopen`` delegation chain, outermost first.

    Each guard's wrapper records what it delegates to in ``__wrapped__``, so
    the chain can be *walked* rather than guessed at from whatever sits on top.
    Cycle-safe: identity-seen set plus a depth cap.
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


def _is_live_layer(link: Any) -> bool:
    """``True`` when ``link`` is a wrapper of THIS guard that still inspects."""
    if not getattr(link, _MARKER, False):
        return False
    state = getattr(link, _STATE_ATTR, None)
    return not (isinstance(state, dict) and state.get("retired"))


def _url_of(req: Any) -> str:
    """Best-effort URL of a urlopen argument (``Request`` object or ``str``)."""
    full_url = getattr(req, "full_url", None)
    if isinstance(full_url, str):
        return full_url
    try:
        return str(req)
    except Exception:  # noqa: BLE001 — never let the guard itself explode
        return "<unrepresentable request>"


def _redact(url: str) -> str:
    """Strip the bot token out of a Telegram URL before recording it.

    ``https://api.telegram.org/bot<TOKEN>/sendMessage`` → ``…/bot<redacted>/sendMessage``.
    The suite prints recorded attempts on failure, and a real token in CI output
    would be an incident (invariant #7).
    """
    if "/bot" not in url:
        return url
    head, _, tail = url.partition("/bot")
    method = tail.split("/", 1)[1] if "/" in tail else "<no-method>"
    return f"{head}/bot<redacted>/{method}"


def attempts() -> List[str]:
    """Redacted live-Telegram attempts recorded since the last :func:`reset`."""
    return list(_ATTEMPTS)


def reset() -> None:
    """Forget recorded attempts (called between tests)."""
    _ATTEMPTS.clear()


def is_installed() -> bool:
    """``True`` when this guard's wrapper is SOMEWHERE in the ``urlopen`` chain.

    Why this walks the chain instead of reading the top marker (2026-08-17,
    card ``inbox-storozh-telegram-dverei-vybivaet-storozh``)
    ---------------------------------------------------------------------
    It used to read the marker off ``urllib.request.urlopen`` only, i.e. off
    the OUTERMOST callable.  That answers "am I on top", which is a different
    question from "am I installed" — and :mod:`network_guard` legitimately ends
    up on top whenever ``conftest`` repairs it (``ensure_installed`` wraps
    whatever is current).  Measured on the shipped code::

        tg.install(); ng.install()  ->  tg.is_installed() == False

    …while the tg wrapper was demonstrably still in the chain.  ``install()``
    read that ``False`` as "not installed" and wrapped a SECOND time, building
    ``tg -> ng -> tg -> real`` with TWO live Telegram layers in it —
    the very shape cycle #163 closed after it produced ``RecursionError``.
    ``spa_core/tests/conftest.py`` reaches that state on every network-guard
    repair, because repairing wraps whatever is current and so puts
    :mod:`network_guard` on top of an already-installed Telegram guard.

    Measured honestly: through the real conftest path the pile settles at four
    links and stops (the clobber that triggers a repair destroys the chain
    first).  Driving ``network_guard`` to re-wrap without that reset grew it
    two links per cycle — 3, 5, 7, 9, 11, 13.  The damage reachable in every
    run is the duplicate live layer and this function denying its own
    presence; the unbounded version is the same defect without its brake.

    Retired wrappers (superseded by a newer copy of this guard, see
    :func:`install`) do not count: they no longer inspect anything.
    """
    return any(_is_live_layer(link) for link in urlopen_chain())


def is_outermost() -> bool:
    """``True`` when this guard's live wrapper is the ``urlopen`` in effect.

    The separate, stricter question :func:`is_installed` used to be misread as
    answering.  It is load-bearing on its own: only the outermost layer sees a
    call first, so only then does ``api.telegram.org`` get this guard's
    specific, token-redacting report instead of the network guard's generic
    refusal (pinned by ``test_telegram_guard_stays_outermost``).
    """
    return _is_live_layer(urllib.request.urlopen)


def install() -> None:
    """Wrap ``urllib.request.urlopen`` with the guard, staying OUTERMOST.

    Idempotent against ITSELF but **not** blind: it re-wraps whenever this
    guard is not the callable in effect.  That matters because
    ``tests/conftest.py`` installs a blanket offline block by plain assignment
    (``urllib.request.urlopen = _blocked_urlopen``) — which silently threw the
    guard away when it happened to be imported second.  Wrapping whatever is
    current preserves both: Telegram URLs are caught here, everything else is
    handed to the offline block (or the real transport) exactly as before.

    Two distinct states, two distinct answers (2026-08-17):

    * already outermost  -> nothing to do;
    * present but buried under :mod:`network_guard` (the state ``conftest``
      leaves behind after repairing that guard) -> wrap again so Telegram keeps
      its specific message, and **retire the buried copy** so exactly ONE live
      Telegram layer exists and the chain stops accumulating.  A retired wrapper stays
      physically in the chain — its delegate is captured in another module's
      closure and cannot be re-pointed from here without risking the
      ``tg -> ng -> tg`` cycle of #163 — but it is inert: it inspects nothing
      and delegates straight through.
    """
    global _real_urlopen
    if is_outermost():
        return
    for link in urlopen_chain():
        state = getattr(link, _STATE_ATTR, None)
        if getattr(link, _MARKER, False) and isinstance(state, dict):
            state["retired"] = True
    _real_urlopen = urllib.request.urlopen
    # Bound HERE and read from the closure, never from the module global
    # (cycle #163). install() rebinds that global, so a wrapper reading it would
    # delegate to whatever was installed LAST rather than to what it wraps —
    # with network_guard doing the same, re-installing both built the cycle
    # `telegram_guard -> network_guard -> telegram_guard -> …` and the next real
    # call died with RecursionError.
    _base_urlopen = _real_urlopen
    # Per-wrapper, bound in the closure for the same reason as the delegate:
    # a module global would be shared by every copy, so retiring one would
    # blind them all.
    _state = {"retired": False}

    def _guarded_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
        if _state["retired"]:
            # Superseded by a newer copy of this guard sitting above us; that
            # one owns the report. Pass straight through — inspecting here
            # would double-record the same attempt.
            return _base_urlopen(req, *args, **kwargs)  # type: ignore[misc]
        url = _url_of(req)
        if TELEGRAM_HOST in url:
            redacted = _redact(url)
            _ATTEMPTS.append(redacted)
            raise LiveTelegramSendAttempted(
                "a test tried to POST to the LIVE Telegram API "
                f"({redacted}). Tests must never message the owner — stub the "
                "sender (patch the module's _send_* / _post_message) or pass "
                "dry_run=True."
            )
        return _base_urlopen(req, *args, **kwargs)  # type: ignore[misc]

    setattr(_guarded_urlopen, _MARKER, True)
    setattr(_guarded_urlopen, _STATE_ATTR, _state)
    # Point at what this wrapper delegates to, so the chain can be WALKED.
    # network_guard.is_installed() used to read only the outermost marker and
    # therefore mistook this guard's presence for its own (cycle #163); it now
    # follows __wrapped__ down, which only works if every link sets it.
    setattr(_guarded_urlopen, "__wrapped__", _base_urlopen)
    urllib.request.urlopen = _guarded_urlopen  # type: ignore[assignment]


def uninstall() -> None:
    """Restore the real ``urlopen``. Used by the guard's own positive control."""
    global _real_urlopen
    if _real_urlopen is not None:
        urllib.request.urlopen = _real_urlopen  # type: ignore[assignment]
        _real_urlopen = None


def assert_no_live_telegram(nodeid: str = "") -> None:
    """Fail if any live-Telegram attempt was recorded, then clear the record.

    Called from the autouse fixture *after* each test, so an attempt is reported
    even when the test (or fail-safe production code inside it) swallowed the
    exception raised at the call site.
    """
    if not _ATTEMPTS:
        return
    recorded = list(_ATTEMPTS)
    reset()
    where = f" in {nodeid}" if nodeid else ""
    raise LiveTelegramSendAttempted(
        f"{len(recorded)} live Telegram API call(s) attempted{where}: "
        f"{recorded}. A test must never message the owner's chat — this is how "
        "the production cycle-gap alert was spammed to the owner on 2026-07-31. "
        "Stub the sender in the test, or pass dry_run=True."
    )
