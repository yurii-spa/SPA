"""No test may write the LIVE off-site backup of the paper-trading track.

Found 2026-08-04 (cycle #112, card
``agent-track-persistence-test-writes-to-real-icloud-backup``), fixed here in
cycle #113.

The defect
==========
``spa_core/tests/test_track_persistence.py`` calls the REAL
``cycle_runner._default_track_persister`` and passes no ``backup_dir``, so
``spa_core.persistence.backup.run_backup`` falls through to
``default_backup_dir()``::

    $SPA_BACKUP_DIR → ~/Library/Mobile Documents/…/SPA_backups (iCloud) → ~/SPA_backups

On the production Mac host ``SPA_BACKUP_DIR`` is unset and the iCloud parent
exists, so the test wrote into the **real off-site backup of the live track** —
the last line of recovery — and then blocked forever inside ``os.replace`` on
the iCloud sync layer. Measured on this host at 16:5x UTC 2026-08-04: a plain
``os.listdir`` of that root did not return within 20 s. Consequence: the full
``spa_core/tests/`` run — the very slice every cycle quotes as "N passed /
0 failed" before pushing — could not complete at all on this machine. It hung
rather than failed, which reads as "slow" (one orphaned run sat at 0 % CPU for
3.5 h).

This is the class already named in the shared memory as *tests write live
state*: the same reason ``push_state_guard`` exists. CI never saw it — on a
Linux runner the iCloud parent does not exist and the fallback ``~/SPA_backups``
answers instantly.

What the guard does
===================
Pins ``$SPA_BACKUP_DIR`` to a per-session sandbox under pytest's own tmp area
before every test, and restores the pre-test value afterwards. It is a
**redirection, not a mock**: ``default_backup_dir()``, ``run_backup()``,
``_atomic_copy()``, rotation and the manifest all still run for real, against a
directory the suite owns. Coverage is unchanged; only the destination moves.

Per-test (not once per session) because a test may legitimately set or delete
the variable itself — ``tests/test_backup.py::test_A2`` deletes it in a
``finally`` — and that must not leak into the next test's default resolution.

``install()`` is idempotent and the sandbox root is created lazily, so importing
this module costs nothing.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ENV_VAR = "SPA_BACKUP_DIR"

_SANDBOX_ROOT: Path | None = None
_UNSET = object()
_saved: object = _UNSET


def sandbox_root() -> Path:
    """The per-process sandbox backup root (created on first use)."""
    global _SANDBOX_ROOT
    if _SANDBOX_ROOT is None:
        _SANDBOX_ROOT = Path(tempfile.mkdtemp(prefix="spa_test_backups_"))
    return _SANDBOX_ROOT


def install() -> None:
    """Pin ``$SPA_BACKUP_DIR`` into the sandbox, remembering the current value."""
    global _saved
    _saved = os.environ.get(ENV_VAR, _UNSET)
    os.environ[ENV_VAR] = str(sandbox_root())


def restore() -> None:
    """Put ``$SPA_BACKUP_DIR`` back the way ``install()`` found it."""
    global _saved
    if _saved is _UNSET:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = _saved  # type: ignore[assignment]
    _saved = _UNSET
