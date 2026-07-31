"""Test-suite guard: no test may write the owner's LIVE alert state.

Why this exists (2026-07-31, cycle #58 — card
``agent-killswitch-test-messages-owner-chat``)
------------------------------------------------------------------------------
Cycle #55 built :mod:`telegram_guard`, which stops a test from POSTing to the
owner's chat.  It did not stop a test from writing the **state that decides
whether the owner is ever told anything**.

``spa_core/telegram/push_policy.py`` is the single Tier-1 push authority.  Its
state file is resolved statically::

    _REPO_ROOT      = Path(__file__).resolve().parents[2]
    _DEFAULT_TG_DIR = _REPO_ROOT / "data" / "telegram"

and ~19 production senders (``threat_reactor``, ``cycle_runner``,
``peg_monitor``, ``self_heal``, ``agent_health_monitor``, …) call
``push_critical(...)`` **without** ``data_dir``.  So any test that drives one of
those code paths writes the LIVE ``data/telegram/push_state.json`` and
``digest_queue.json`` — no matter how carefully the test sandboxed its own
``data_dir``.  ``tests/conftest.py`` isolates ``SPA_DATA_DIR`` per test, which
does **not** cover this: push_policy never consults that env, it resolves the
repo root from ``__file__``.

Two measured consequences, both real:

1. **The owner's most critical alert can be muted by a test run.**  push_policy
   is edge-triggered: ``prev_state == "bad"`` → *"still bad → silent"*.  A test
   that drives a kill-switch/derisk path leaves ``kill_switch: bad`` in the live
   file, and the next *genuine* firing is then suppressed — a fail-SILENT on the
   one event that means capital moved.
2. **Guard errors became state-dependent, i.e. flaky.**  Running
   ``spa_core/tests/test_cycle_derisk_e2e.py`` as a whole file raised
   ``LiveTelegramSendAttempted``; running the same test **alone** passed —
   because the leftover ``bad`` state took the silent branch.  That is why cycle
   #55, which enumerated senders from one run, could not have produced a
   complete list, and why CI on ``main`` went red for a reason no report named.

Design (same shape as :mod:`telegram_guard`, deliberately)
----------------------------------------------------------
* **One chokepoint.**  ``_DEFAULT_TG_DIR`` is the only way a caller reaches the
  live directory (``_tg_dir()`` returns it whenever ``data_dir is None``), so
  re-pointing that one global covers every present and future sender.
* **Not a mock.**  The whole policy — whitelist, edge-trigger, daily ceiling,
  digest demotion — still runs, byte for byte.  Only the *location* of the state
  changes, so tests keep exercising the real gate.
* **Self-healing.**  :func:`reset` re-points the global if something (a module
  reload, a test's own monkeypatch) put the live directory back — the same
  lesson as ``telegram_guard.install()``, which had to learn to re-wrap after
  another conftest reassigned ``urlopen``.
* **Fail-CLOSED honesty.**  If ``push_policy`` cannot be imported, the guard
  reports :func:`is_installed` ``False`` and keeps the reason verbatim.  It
  never claims a protection it did not apply (#29/#31/#35–#38/#40).

Stdlib only.  Import has no side effects; call :func:`install` explicitly.
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path
from typing import Optional

#: Files push_policy keeps in its telegram dir.  Cleared between tests so one
#: test's edge-state cannot decide another test's branch.
STATE_FILENAMES = ("push_state.json", "digest_queue.json")

_sandbox: Optional[Path] = None
_live_dir: Optional[Path] = None
_unavailable_reason: Optional[str] = None


def _push_policy():
    """Import the push authority, or record why it is unavailable."""
    global _unavailable_reason
    try:
        from spa_core.telegram import push_policy  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — the guard must never explode
        _unavailable_reason = f"{type(exc).__name__}: {exc}"
        return None
    _unavailable_reason = None
    return push_policy


def live_dir() -> Optional[Path]:
    """The real ``<repo>/data/telegram`` captured before the redirect."""
    return _live_dir


def sandbox_dir() -> Optional[Path]:
    """The throwaway directory the suite's alert state is written to."""
    return _sandbox


def unavailable_reason() -> Optional[str]:
    """Verbatim reason the guard could not install, or ``None``."""
    return _unavailable_reason


def is_installed() -> bool:
    """``True`` only when push_policy's default dir IS the sandbox.

    Deliberately measured against the live module, not against a flag set at
    install time: a reload or a stray monkeypatch must show up as *not
    installed* rather than as a stale claim.
    """
    pp = _push_policy()
    if pp is None or _sandbox is None:
        return False
    return Path(pp._DEFAULT_TG_DIR) == _sandbox


def install() -> None:
    """Point push_policy's default telegram dir at a throwaway directory.

    Idempotent: the sandbox is created once per process and re-pointed whenever
    the current default is not it.
    """
    global _sandbox, _live_dir
    pp = _push_policy()
    if pp is None:
        return
    if _sandbox is None:
        _live_dir = Path(pp._DEFAULT_TG_DIR)
        _sandbox = Path(tempfile.mkdtemp(prefix="spa_push_state_"))
        atexit.register(shutil.rmtree, str(_sandbox), True)
    pp._DEFAULT_TG_DIR = _sandbox


def reset() -> None:
    """Clear sandboxed alert state and re-assert the redirect (between tests)."""
    install()
    if _sandbox is None:
        return
    for name in STATE_FILENAMES:
        try:
            (_sandbox / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:  # pragma: no cover — a locked temp file is not a test failure
            pass
