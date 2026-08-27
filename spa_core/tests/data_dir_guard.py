"""Test-suite guard: no test may read or write the LIVE repo-root ``data/``.

Why this module exists (2026-08-27, cycle #391 — card
``inbox-autouse-zaslon-data-ne-dohodit-do-kornya``)
------------------------------------------------------------------------------
The isolation itself is old: ``tests/conftest.py`` has carried an autouse
fixture that points ``SPA_DATA_DIR`` at a per-test tmp dir since the live track
became a thing worth protecting.  What was measured by cycle #386 is that the
fixture reached **one** of the suite's two roots:

===========================================  ==============================
run                                          ``os.environ["SPA_DATA_DIR"]``
===========================================  ==============================
``pytest tests/test_zz_probe.py``            ``…/_spa_isolated_data``
``pytest spa_core/tests/test_zz_probe.py``   ``None``
===========================================  ==============================

``spa_core/tests/`` is a **sibling** of ``tests/``, not a descendant, so a
conftest in the latter cannot reach it by construction.  ~96 950 of the suite's
checks live in ``spa_core/tests/`` — i.e. essentially the whole set ran with the
env unset, and every module resolving its data dir through the canonical hook
resolved it to the host's real ``data/``.

The fix is the shape already used three times in this suite
(:mod:`telegram_guard`, :mod:`push_state_guard`, :mod:`backup_dir_guard`): the
behaviour lives in ONE module, loaded by absolute path from BOTH conftests, so
the two roots cannot drift apart.  A fixture declaration must still be written
in each conftest (pytest discovers fixtures by module, not by import), but the
body is one line delegating here — a copy of the *policy* is what drifts, and
there is now only one.

What it does NOT cover
----------------------
Only code that resolves its data dir through ``SPA_DATA_DIR`` (directly or via
``spa_core.utils.data_dir.own_data_dir``).  A module that computes
``Path(__file__).parents[N] / "data"`` is unaffected — that is the other half of
the same problem, ratcheted down by
``spa_core/tests/test_data_dir_env_ratchet.py``, and no fixture can fix it from
the outside.  Two guards exist precisely because one of them cannot answer the
other's question.

Opting out
----------
A test that reads the live track ON PURPOSE (SSOT cross-checks, evidence chain,
"is the artifact there at all") marks itself ``live_data`` and guards its own
reads with ``require_live_data()``.  Opting out is a declaration, not a
loophole: it is visible in the marker, greppable, and countable.
"""
from __future__ import annotations

import os
from pathlib import Path

# The dir the guard protects.  Derived from THIS file (spa_core/tests/…), so it
# is the repo root's data/ in every worktree and never the host's by accident.
LIVE_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

#: Prefix of the per-test sandbox dir. It is created by ``tmp_path_factory``, i.e.
#: a SIBLING of the test's own ``tmp_path`` — deliberately NOT inside it.
#:
#: The older wording lived at ``tmp_path / "_spa_isolated_data"`` and picked that
#: name to avoid a FileExistsError against tests that mkdir their own
#: ``tmp_path / "data"``. Collision was the right worry, containment was not:
#: measured 2026-08-27, ``test_package_data_guard.py::
#: test_snapshot_sees_what_lies_in_the_directory`` writes one file into
#: ``tmp_path`` and asserts the directory holds exactly that one file. A sandbox
#: created inside ``tmp_path`` is a second entry there, so the guard would fail
#: every test that inspects its own tmp dir WHOLESALE — an isolation that
#: rewrites what the test sees is not isolation.
SANDBOX_PREFIX = "spa_isolated_data"


def isolate(request, tmp_path_factory, monkeypatch) -> Path | None:
    """Point ``SPA_DATA_DIR`` at a per-test tmp dir; return it (None if opted out).

    Called from the autouse ``_isolate_data_dir`` fixture of BOTH test roots.
    Tests marked ``live_data`` keep the real environment untouched.

    Takes ``tmp_path_factory`` rather than ``tmp_path`` on purpose: the sandbox
    must not be an entry inside the directory the test itself works in (see
    ``SANDBOX_PREFIX``). One dir per test either way — this one is just next to
    ``tmp_path`` instead of in it.
    """
    if request.node.get_closest_marker("live_data"):
        return None
    sandbox = Path(tmp_path_factory.mktemp(SANDBOX_PREFIX))
    monkeypatch.setenv("SPA_DATA_DIR", str(sandbox))
    return sandbox


def current_is_isolated() -> bool:
    """True when the env currently points somewhere other than the live data/.

    Used by the guard's own tests to state the effect rather than the wiring.
    """
    raw = os.environ.get("SPA_DATA_DIR")
    if not raw:
        return False
    try:
        return Path(raw).resolve() != LIVE_DATA_DIR.resolve()
    except OSError:
        return False
