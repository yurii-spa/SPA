"""The GATE that stops a NEW test from reaching for a live feed.

Why this exists (2026-08-18, card ``agent-tests-reach-live-feed-222``)
----------------------------------------------------------------------
Three things already exist and none of them is a gate:

* :mod:`network_guard` **refuses** the call — it answers "did anything reach the
  live network" (no, never since cycle #93) and deliberately does *not* fail the
  test: "refusing a live call is the guard doing its job";
* :mod:`live_feed_doors` **shuts the shared doors** so most tests stop even
  walking up to a feed — measured −72 % on the ``dfb`` slice;
* ``conftest``'s end-of-run banner **reports** what is left.

So today a brand-new test that reaches for a feed is *reported* at the bottom of
a run that exits **0**.  Nothing fails, nobody has to look, and the number grows
back — which is exactly how this card got to 222 tests in the first place.  The
card's own history is the proof: "ноль отказов" was true of ONE test, was read as
true of the suite, and the suite quietly went back to 1726.

This module turns the report into a **refusal**: a test whose production code
reaches for a live feed FAILS, immediately and by name, unless the baseline
already knows about it.

What is gated, and what is honestly NOT
---------------------------------------
Full-suite measurement is not affordable — ``spa_core/tests/`` is 96 352 tests in
1 547 files and a complete run costs hours (measured 2026-08-18: collection alone
58 s; the 171-file measured slice, 4 715 tests, 4 m 25 s).  A default-deny gate
whose baseline was *guessed* for the other 89 % of files would turn main red for
pre-existing offenders nobody measured — and a gate that goes red for being
unmeasured teaches people to switch it off.  That is the ``frozen_date_ratchet``
lesson, written down in ``.claude/rules/deployment.md``.

So the gate is fail-CLOSED where it has evidence and silent where it has none:

=================================  ==========================================
test file                          verdict when its test refuses
=================================  ==========================================
in ``measured_files``, nodeid has  allowed up to that cap; **more → RED**
a cap in the baseline
in ``measured_files``, nodeid has  cap 0 → **RED** (a new test in a file that
NO cap                             was measured clean, or a renamed one)
NEW: untracked, or first committed  cap 0 → **RED** — this is the "новый тест
after ``cutoff_epoch``             не ходит в сеть" case, and it covers the
                                   whole suite, measured or not
neither of the above (old,         **not gated** — reported by the banner only.
unmeasured)                        Named in ``coverage`` so nobody reads the
                                   green as "the suite is hermetic"
=================================  ==========================================

The baseline may only **shrink**: caps come down as doors get shut, and
``test_live_feed_gate.py`` pins that they match a real measurement rather than a
wish.  Adding a cap to silence a red test is the forbidden move (invariant #16) —
the fix is to inject a fake feed, which is what ``.claude/rules/adapters.md`` has
required all along.

Opting out
----------
``@pytest.mark.live_feed_transport`` — the SAME mark that keeps the doors open
for tests whose subject *is* the transport.  It is a declaration in the test
file, not a switch in the gate, and it does not let the call out: the network
guard still refuses it.

Stdlib only.  Import has no side effects.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

#: Where the ratchet lives.  One file, next to this one, like every other
#: baseline in this suite.
BASELINE_PATH = Path(__file__).resolve().parent / "live_feed_refusal_baseline.json"

#: Repo root — three levels up from this file (``spa_core/tests/x.py``).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Set when the ``git`` binary is missing/unusable, so the report can SAY that
#: the newness half of the gate is inert instead of quietly passing everything.
#: Never swallowed: ``conftest``'s terminal summary prints it.
_GIT_TROUBLE: List[str] = []

#: ``path -> epoch of the commit that ADDED it`` (``None`` = untracked/unknown).
_ADDED_EPOCH_CACHE: Dict[str, Optional[int]] = {}


def git_trouble() -> List[str]:
    """Reasons the newness check could not run, if any."""
    return list(_GIT_TROUBLE)


def load_baseline(path: Optional[Path] = None) -> dict:
    """Read the ratchet.  A missing/broken baseline is NOT a silent pass."""
    p = Path(path) if path is not None else BASELINE_PATH
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("cutoff_epoch", "measured_files", "caps"):
        if key not in data:
            raise ValueError(f"live-feed baseline {p} has no {key!r}")
    return data


def _run_git(args: List[str]) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # git absent / hung
        reason = f"{type(exc).__name__}: {exc}"
        if reason not in _GIT_TROUBLE:
            _GIT_TROUBLE.append(reason)
        return None
    if out.returncode != 0:
        return ""
    return out.stdout


def added_epoch(relpath: str) -> Optional[int]:
    """Commit time of the commit that ADDED ``relpath``; ``None`` if unknown.

    Deliberately the ADD date, not the last-touch date.  Last-touch would turn a
    file red for an unrelated typo fix years after the refusals were introduced —
    punishing the wrong edit is how a gate gets switched off.
    """
    if relpath in _ADDED_EPOCH_CACHE:
        return _ADDED_EPOCH_CACHE[relpath]
    out = _run_git(["log", "--diff-filter=A", "--format=%ct", "--", relpath])
    epoch: Optional[int] = None
    if out:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if lines:
            try:
                epoch = int(lines[-1])  # oldest = the add
            except ValueError:
                epoch = None
    _ADDED_EPOCH_CACHE[relpath] = epoch
    return epoch


def file_is_new(relpath: str, cutoff_epoch: int) -> bool:
    """``True`` for a file the baseline never saw: untracked, or added after it.

    When ``git`` itself is unusable this returns ``False`` — the newness half of
    the gate goes inert rather than reddening every file in an environment it
    cannot judge — and the reason is recorded in :func:`git_trouble`, which the
    end-of-run report prints.  The measured half keeps working regardless.
    """
    if _GIT_TROUBLE:
        return False
    epoch = added_epoch(relpath)
    if _GIT_TROUBLE:  # discovered during THIS call
        return False
    if epoch is None:
        return True  # untracked — written in this session, the strictest case
    return epoch > int(cutoff_epoch)


def file_of(nodeid: str) -> str:
    """Test file part of a pytest nodeid."""
    return nodeid.split("::", 1)[0]


def verdict(
    nodeid: str,
    count: int,
    marked: bool,
    baseline: dict,
    is_new: Optional[bool] = None,
) -> Optional[str]:
    """Message when this test violates the gate, else ``None``.

    Pure: every input is passed in, including newness, so the whole decision
    table is testable without a repo, a network or a clock.
    """
    if count <= 0:
        return None
    if marked:
        # The transport IS the subject here; the guard still refused the call.
        return None
    relpath = file_of(nodeid)
    caps = baseline.get("caps", {})
    if nodeid in caps:
        cap = int(caps[nodeid])
        if count <= cap:
            return None
        return (
            f"live-feed GATE: {nodeid} made {count} live-network attempt(s), "
            f"but the baseline allows {cap}. Something under test started "
            f"reaching for a feed it used not to. Inject a fake feed "
            f"(.claude/rules/adapters.md); raising the cap is the forbidden "
            f"move (invariant #16)."
        )
    measured = relpath in set(baseline.get("measured_files", ()))
    if is_new is None:
        is_new = file_is_new(relpath, int(baseline["cutoff_epoch"]))
    if not (measured or is_new):
        return None  # old, unmeasured: no evidence, so no claim — see module doc
    why = "is NEW (untracked or added after the baseline)" if is_new else (
        "was measured clean when the baseline was taken"
    )
    return (
        f"live-feed GATE: {nodeid} made {count} live-network attempt(s) and is "
        f"not allowed any — its file {why}. The attempt was REFUSED (nothing "
        f"went out), and that refusal is exactly the problem: a test whose green "
        f"depends on a failed feed call passes when the thing it means to check "
        f"is broken. Inject a fake feed (.claude/rules/adapters.md), or — only "
        f"if the transport itself is this test's subject — mark it "
        f"@pytest.mark.live_feed_transport."
    )


def check(nodeid: str, refusals: List[str], marked: bool) -> Optional[str]:
    """:func:`verdict` against the on-disk baseline. Used by ``conftest``."""
    return verdict(nodeid, len(refusals), marked, load_baseline())


# ---------------------------------------------------------------------------
# The TIME half of the same card: "одна медленная зона съедает цикл".
# ---------------------------------------------------------------------------
#: How far over its recorded cap a test may drift before it is called a
#: regression.  Wide on purpose: this container measured load average 7–20 with
#: other agents running, and a tight time gate on a shared machine is a flaky
#: gate — and a flaky gate gets switched off, which costs more than it saves.
#: 3x still catches the recidive this exists for: ``test_dfb_alerts.py`` went
#: 152.93 s -> 2.2 s when ONE door was shut (card #93 / 2026-08-17), i.e. the
#: regressions in this class are two orders of magnitude, not twenty percent.
DURATION_TOLERANCE = 3.0


def duration_verdict(
    nodeid: str,
    seconds: float,
    marked_slow: bool,
    baseline: dict,
    is_new: Optional[bool] = None,
) -> Optional[str]:
    """Message when this test blew the time budget, else ``None``.

    Deliberately NOT a ban on slow tests — ``@pytest.mark.slow`` (already
    registered in ``pytest.ini``) declares a legitimately long test and opts it
    out, and a measured long-runner keeps its own recorded cap.  What is refused
    is the *unannounced* long-runner: the profile of the measured slice
    (2026-08-18) was 240.95 s total with 126 s of it in THREE tests — 52 % of a
    run in 0.06 % of its tests. That is the shape that eats a cycle, and it is
    invisible until somebody runs ``--durations``.
    """
    if marked_slow:
        return None
    caps = baseline.get("duration_caps", {})
    budget = float(baseline.get("slow_test_seconds", 30.0))
    cap = caps.get(nodeid)
    # max(), never min(): a recorded cap may only RAISE the limit above the
    # budget.  Measured 2026-08-18 on this container — a test profiled at 28.6 s
    # took 34.1 s in the very next run under other agents' load.  A cap that
    # tightened the limit would turn machine load into red tests, and a gate that
    # is red for reasons the code does not own is a gate people learn to ignore.
    limit = max(budget, float(cap) * DURATION_TOLERANCE) if cap else budget
    if seconds <= limit:
        return None
    relpath = file_of(nodeid)
    measured = relpath in set(baseline.get("measured_files", ()))
    if is_new is None:
        is_new = file_is_new(relpath, int(baseline["cutoff_epoch"]))
    if not (measured or is_new):
        return None  # same honest scope rule as the network half
    known = f"its recorded cap {cap}s (x{DURATION_TOLERANCE:g} tolerance)" if cap \
        else f"the {budget:g}s budget for an undeclared test"
    return (
        f"time GATE: {nodeid} took {seconds:.1f}s, over {known}. One slow zone "
        f"eats the cycle: on the measured slice 52% of a 241s run sat in three "
        f"tests. Either make it fast (usually: stop waiting on something), or "
        f"declare it with @pytest.mark.slow — silence is the one option that is "
        f"not available."
    )


def check_duration(nodeid: str, seconds: float, marked_slow: bool) -> Optional[str]:
    """:func:`duration_verdict` against the on-disk baseline. Used by ``conftest``."""
    return duration_verdict(nodeid, seconds, marked_slow, load_baseline())


def coverage(baseline: Optional[dict] = None) -> str:
    """One line the report can print so green is never read as 'suite hermetic'."""
    b = baseline if baseline is not None else load_baseline()
    return (
        f"live-feed gate: {len(b.get('measured_files', ()))} measured file(s) "
        f"gated at their measured caps; every NEW test file gated at zero; "
        f"older unmeasured files reported only "
        f"({b.get('coverage_note', 'coverage unrecorded')})"
    )


__all__ = [
    "BASELINE_PATH",
    "added_epoch",
    "check",
    "coverage",
    "file_is_new",
    "file_of",
    "git_trouble",
    "load_baseline",
    "verdict",
]
