#!/usr/bin/env python3
"""ADR-107 — a live emergency halt must survive a tree restore.

Owner decision of 2026-08-21 09:40Z (card
``owner-decision-avariinaya-ostanovka-teryaetsya-pri-vosst``, **вариант 1**):
take ``data/kill_switch_active.json`` out of git.

What was actually measured (and what was NOT the danger)
--------------------------------------------------------
The original note assumed the danger ran one way — restore the tree and
production comes back up already halted. That premise is false and was checked:
the copy in git records a *deactivation* (``active: false``, 2026-06-20), and
``check_manual_trigger`` reads that as "no halt". Restoring does not stop
anything.

The danger runs the other way, and it is worse. The halt file is state, and git
holds a stale copy of it. If production genuinely halts — ``active: true``
written by ``KillSwitchChecker`` — and anyone then restores the tree, checks out
``data/``, or rolls back a bad deploy, git quietly overwrites the live halt with
its own six-week-old "deactivated" snapshot. Trading resumes with the brake
pulled. A brake that a routine git command can release is not a brake.

The three tests below split that into cause and effect:

* the effect is demonstrated on a throwaway repository, both ways round — a
  tracked halt file does not survive ``git checkout``, an untracked one does;
* the cause is asserted on THIS repository — the file must not be tracked.

The last one is the acceptance criterion of the card and the one that was red.
"""
from __future__ import annotations

# FROZEN-DATE-OK: prose-provenance — no date in this file is ever compared with
# a clock. The fixtures deliberately carry no timestamps (check_manual_trigger
# reads only ``active``), and the dates that remain are references, in comments
# and one assertion message, to the owner decision this file implements.

import json
import subprocess
from pathlib import Path

import pytest

from spa_core.governance.kill_switch import (
    KILL_SWITCH_ACTIVE_FILENAME,
    KillSwitchChecker,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACKED_PATH = f"data/{KILL_SWITCH_ACTIVE_FILENAME}"

# The snapshot git used to hold: a halt that was lifted long ago.
# No timestamps here on purpose — ``check_manual_trigger`` reads ``active`` and
# nothing else, so a date in this fixture would be decoration that the calendar
# could later break for a reason unrelated to the behaviour under test.
_STALE_DEACTIVATION = {
    "active": False,
    "reason": "deactivated: an old, long-resolved incident",
}
# What production writes when the brake is actually pulled.
_LIVE_HALT = {
    "active": True,
    "reason": "drawdown -11.2% ≥ HARD_KILL 10%",
}


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120
    )


def _halt_is_live(data_dir: Path) -> bool:
    """Ask the REAL checker, not the file — the brake is what the code reads."""
    triggered, _reason = KillSwitchChecker(data_dir=str(data_dir)).check_manual_trigger()
    return triggered


def _throwaway_repo(tmp_path: Path, *, track_the_halt_file: bool) -> Path:
    """A minimal repo with a data/ directory, halt file tracked or not."""
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@example.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)

    halt = repo / "data" / KILL_SWITCH_ACTIVE_FILENAME
    if track_the_halt_file:
        halt.write_text(json.dumps(_STALE_DEACTIVATION), encoding="utf-8")
        _git("add", "-f", _TRACKED_PATH, cwd=repo)
    else:
        (repo / ".gitignore").write_text("data/*.json\n", encoding="utf-8")
        _git("add", ".gitignore", cwd=repo)
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git("add", "README", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    return repo


def test_a_tracked_halt_file_is_erased_by_a_restore(tmp_path):
    """The hazard itself, reproduced end to end.

    This one is green with or without the fix — it is the measurement the
    decision rests on, not the fix's guard. It exists so that "git can release
    the brake" is a fact in the suite rather than a claim in a card.
    """
    repo = _throwaway_repo(tmp_path, track_the_halt_file=True)
    data = repo / "data"

    # Production halts for real.
    (data / KILL_SWITCH_ACTIVE_FILENAME).write_text(
        json.dumps(_LIVE_HALT), encoding="utf-8"
    )
    assert _halt_is_live(data), "setup failed: the halt was not live to begin with"

    # Somebody restores the tree / rolls back a bad deploy.
    _git("checkout", "--", ".", cwd=repo)

    assert not _halt_is_live(data), (
        "expected the tracked halt to be silently overwritten by git's stale "
        "copy — if this no longer happens, the premise of ADR-107 changed and "
        "the decision should be re-read, not the test relaxed"
    )


def test_an_untracked_halt_file_survives_a_restore(tmp_path):
    """The same restore, with the file out of git: the brake holds."""
    repo = _throwaway_repo(tmp_path, track_the_halt_file=False)
    data = repo / "data"

    (data / KILL_SWITCH_ACTIVE_FILENAME).write_text(
        json.dumps(_LIVE_HALT), encoding="utf-8"
    )
    assert _halt_is_live(data)

    _git("checkout", "--", ".", cwd=repo)

    assert _halt_is_live(data), (
        "an untracked halt file was still lost across a restore — untracking is "
        "then not the whole fix and ADR-107 is incomplete"
    )


def test_halt_file_is_not_tracked_in_this_repository():
    """The card's acceptance criterion, on the real repo. Red before ADR-107."""
    out = _git("ls-files", "--", _TRACKED_PATH, cwd=_REPO_ROOT)
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    assert out.stdout.strip() == "", (
        f"{_TRACKED_PATH} is tracked in git again. It is live state, not source: "
        f"any restore, checkout or rollback will overwrite a real halt with "
        f"whatever snapshot git happens to hold, and trading resumes with the "
        f"brake pulled (ADR-107, owner decision 2026-08-21)"
    )


def test_no_committed_halt_file_ever_says_active_true():
    """The owner's separate instruction, kept enforceable if the file returns.

    "никогда не коммитить файл остановки со значением «включён»" — committing an
    active halt is the ONLY way to also get the danger the original note
    imagined: production coming back up halted by a decision already reversed.
    Vacuous while the file is untracked, and deliberately so — it is the second
    lock on a door we have just closed.
    """
    shown = _git("show", f"HEAD:{_TRACKED_PATH}", cwd=_REPO_ROOT)
    if shown.returncode != 0:
        pytest.skip("no committed halt file — nothing to inspect (the good case)")
    doc = json.loads(shown.stdout)
    assert doc.get("active") is not True, (
        "a halt file with active=true is committed: restoring this tree would "
        "stop production on an order the owner has already lifted"
    )
