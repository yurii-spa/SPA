"""One way to spawn a CHILD `pytest` run — anchored so it cannot walk the system temp tree.

Why this module exists (cycle #382, 2026-08-25 — measured, not assumed)
-----------------------------------------------------------------------
A whole class of tests in this repo measures its subject **in a child process**,
because the effect is invisible from inside the process that causes it (lesson
``pytest-diversion-blinds-effect-tests``, cards #226/#229).

Cycle #315 hit the symptom: a child run whose test file sat in the parent's
``tmp_path`` did not reach ``--collect-only`` in **300 s**, while the same file
in a ``tempfile.mkdtemp()`` directory answered in **0.00 s**. The cause was
recorded as unknown, with two guesses (numbered-dir cleanup, ``TempPathFactory``
locks). Cycle #382 measured it, and **both guesses were wrong**:

1. ``pytest`` with no ini file among the argument's ancestors picks its rootdir
   as the **common ancestor of the invocation directory and the arguments**.
   ``tmp_path`` is a *resolved* path (``/private/var/folders/…`` on macOS) and
   the invocation dir is usually resolved too (``/private/tmp/…``), so the
   common ancestor collapses to **``/private``**.
2. ``confcutdir`` defaults to that rootdir, and ``Session.collect`` keeps every
   ancestor of the argument that is inside confcutdir. So the chain becomes
   ``/private → /private/var → … → $TMPDIR → pytest-of-<user> → pytest-N → …``.
3. ``Dir.collect`` (``_pytest/main.py``) calls ``scandir`` on each of those.
   ``$TMPDIR`` on this machine held **9 780 560** entries when measured. That
   scan is the hang — it is not a deadlock, it is O(size of the system temp).

The stack captured with ``faulthandler.dump_traceback_later`` while it hung::

    File "_pytest/pathlib.py", line 969 in scandir
    File "_pytest/main.py", line 557 in collect          # Dir.collect
    ...
    File "_pytest/main.py", line 837 in perform_collect

**``mkdtemp`` is not a fix — it works by accident.** ``tempfile.mkdtemp()``
returns the *unresolved* ``/var/folders/…`` path on macOS, which shares no
ancestor but ``/`` with the invocation dir, so pytest falls back to the
argument's own directory. Resolve that same path once and it hangs exactly like
``tmp_path`` (measured: ``mkdtemp RESOLVED /private/var/… → TIMEOUT >25 s``).
A single ``.resolve()`` anywhere would silently bring the five-minute stall back.

What actually fixes it, measured
--------------------------------
Pinning the child's rootdir. All three of these answered in ≤ 0.26 s with the
test file sitting in the parent's ``tmp_path``::

    --rootdir <dir>        0.26 s
    --confcutdir <dir>     0.13 s
    cwd=<dir>              0.13 s

This module standardises on ``--rootdir`` because it is explicit at the call
site, survives a caller that needs its own ``cwd`` (both live-data guards run
the child with ``cwd=REPO_ROOT`` on purpose), and is what the lint in
``test_child_pytest_rootdir.py`` can check by reading the argv.

stdlib only. No LLM anywhere near it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

__all__ = ["child_pytest_argv", "run_child_pytest", "ROOTDIR_FLAGS"]

#: The flags that anchor a child run. Either one prunes the ancestor walk; the
#: lint accepts both so a caller with a reason can choose the other.
ROOTDIR_FLAGS = ("--rootdir", "--confcutdir")


def child_pytest_argv(
    test_path: str | Path,
    *extra_args: str,
    python: str | None = None,
) -> list[str]:
    """argv for a child ``pytest`` run anchored at the test file's own directory.

    The anchor is what keeps the child from building ``Dir`` collectors for
    ``$TMPDIR`` and scanning millions of entries (see the module docstring).
    """
    path = Path(test_path)
    anchor = path if path.is_dir() else path.parent
    return [
        python or sys.executable,
        "-m",
        "pytest",
        str(path),
        "--rootdir",
        str(anchor),
        *extra_args,
    ]


def run_child_pytest(
    test_path: str | Path,
    *extra_args: str,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 120,
    python: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a child ``pytest`` on ``test_path`` and return the completed process.

    ``cwd`` is passed through untouched — several callers deliberately run the
    child from the repository root so that production imports resolve the way
    they do in the real suite. The rootdir anchor does not depend on it.
    """
    argv: Sequence[str] = child_pytest_argv(test_path, *extra_args, python=python)
    return subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
