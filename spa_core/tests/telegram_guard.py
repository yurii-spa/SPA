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
    """``True`` when the guard is the ``urllib.request.urlopen`` in effect."""
    return getattr(urllib.request.urlopen, _MARKER, False)


def install() -> None:
    """Wrap ``urllib.request.urlopen`` with the guard.

    Idempotent against ITSELF but **not** blind: it re-wraps whenever the
    current ``urlopen`` is not the guard.  That matters because
    ``tests/conftest.py`` installs a blanket offline block by plain assignment
    (``urllib.request.urlopen = _blocked_urlopen``) — which silently threw the
    guard away when it happened to be imported second.  Wrapping whatever is
    current preserves both: Telegram URLs are caught here, everything else is
    handed to the offline block (or the real transport) exactly as before.
    """
    global _real_urlopen
    if is_installed():
        return
    _real_urlopen = urllib.request.urlopen
    # Bound HERE and read from the closure, never from the module global
    # (cycle #163). install() rebinds that global, so a wrapper reading it would
    # delegate to whatever was installed LAST rather than to what it wraps —
    # with network_guard doing the same, re-installing both built the cycle
    # `telegram_guard -> network_guard -> telegram_guard -> …` and the next real
    # call died with RecursionError.
    _base_urlopen = _real_urlopen

    def _guarded_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
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
