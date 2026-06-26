"""
spa_core/utils/filelock.py
==========================

Cross-process advisory file lock + locked read-modify-write helpers.

Hardens SPA against the recurring concurrent-edit / lost-update hazards where an
autonomous hourly cycle rewrites ``KANBAN.json`` / a registry file while another
process edits the same file (see memory notes: concurrent-kanban-writer,
strategy-registry-concurrent-writer).

Design
------
- stdlib only (``fcntl.flock`` advisory lock on a ``<target>.lock`` sidecar file).
- Deterministic, fail-SAFE: if locking is unavailable on this platform (no
  ``fcntl``) it degrades to a best-effort **no-op** with a one-time warning —
  it NEVER hangs and NEVER raises just because the platform lacks flock.
- Bounded ``timeout`` (default 10s) with a short poll interval. On timeout a
  :class:`FileLockTimeout` is raised so the caller can fail loudly rather than
  silently racing.
- The lock is *advisory*: it only serializes writers that also go through this
  helper (which is the whole point — all SPA writers of a given file must use it).

Typical use::

    from spa_core.utils.filelock import locked_json_update

    def bump(data):
        data["done_count"] = data.get("done_count", 0) + 1
        return data

    # reload-under-lock -> modify -> atomic write -> release, no lost updates
    locked_json_update("KANBAN.json", bump)
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

# fcntl is POSIX-only; degrade safely on platforms (e.g. plain Windows) without it.
try:  # pragma: no cover - import guard is platform dependent
    import fcntl as _fcntl
except Exception:  # pragma: no cover
    _fcntl = None  # type: ignore[assignment]

_DEFAULT_TIMEOUT = 10.0
_POLL_INTERVAL = 0.05

# Emit the "flock unavailable" warning at most once per process — avoid log floods.
_warned_no_flock = False


class FileLockTimeout(TimeoutError):
    """Raised when an advisory lock cannot be acquired within the timeout."""


def _warn_no_flock(path: str) -> None:
    global _warned_no_flock
    if not _warned_no_flock:
        warnings.warn(
            "fcntl.flock unavailable on this platform — file locking degraded to a "
            f"best-effort no-op for {path!r}. Concurrent writers are NOT serialized.",
            RuntimeWarning,
            stacklevel=3,
        )
        _warned_no_flock = True


@contextlib.contextmanager
def file_lock(
    target: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    exclusive: bool = True,
) -> Iterator[bool]:
    """Acquire an advisory lock on ``<target>.lock``.

    Yields ``True`` if the lock was actually held, ``False`` if locking was
    unavailable (degraded no-op). Never hangs: respects ``timeout``; raises
    :class:`FileLockTimeout` if the lock is held by someone else past the deadline.

    The lock file is created next to *target* (NOT *target* itself), so the data
    file is never opened in a truncating mode just to lock it.
    """
    target = os.fspath(target)

    # Fail-SAFE degrade: no fcntl → best-effort no-op (warn once, never hang).
    if _fcntl is None:
        _warn_no_flock(target)
        yield False
        return

    lock_path = target + ".lock"
    # Ensure the parent dir exists so we can create the sidecar.
    parent = os.path.dirname(os.path.abspath(lock_path)) or "."
    os.makedirs(parent, exist_ok=True)

    flag = _fcntl.LOCK_EX if exclusive else _fcntl.LOCK_SH
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + max(0.0, timeout)
    acquired = False
    try:
        while True:
            try:
                _fcntl.flock(lock_fd, flag | _fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise FileLockTimeout(
                        f"Could not acquire lock on {lock_path!r} within {timeout}s "
                        "(another process holds it)."
                    )
                time.sleep(_POLL_INTERVAL)
        yield True
    finally:
        if acquired:
            try:
                _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(lock_fd)
        except OSError:
            pass


def locked_json_update(
    path: str,
    update_fn: Callable[[Any], Any],
    *,
    default: Optional[Any] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Any:
    """Locked, reload-before-write, atomic read-modify-write for a JSON file.

    The whole reload -> ``update_fn`` -> atomic write happens while holding the
    advisory lock, so two serialized writers cannot lose each other's update:
    the second writer always observes the first writer's committed state before
    computing its own change.

    Args:
        path:      Target JSON file.
        update_fn: ``Callable(current_data) -> new_data``. Receives the freshly
                   reloaded on-disk data (NOT a stale snapshot).
        default:   Seed value if the file does not exist (default: ``{}``).
        timeout:   Max seconds to wait for the lock.

    Returns:
        The new data written by ``update_fn``.
    """
    seed = {} if default is None else default
    with file_lock(path, timeout=timeout):
        current = atomic_load(path, default=seed)
        new_data = update_fn(current)
        atomic_save(new_data, path)
    return new_data


def locked_text_rewrite(
    path: str,
    render_fn: Callable[[Optional[str]], str],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """Locked, reload-before-write, atomic rewrite for a TEXT file.

    Used for source/registry files (e.g. a ``.py`` registry that an autonomous
    cycle appends to). ``render_fn`` receives the current file text (or ``None``
    if the file is absent) read fresh under the lock, and returns the new text.
    """
    from spa_core.utils.atomic import atomic_save_text

    with file_lock(path, timeout=timeout):
        current: Optional[str] = None
        p = Path(path)
        if p.exists():
            current = p.read_text(encoding="utf-8")
        new_text = render_fn(current)
        atomic_save_text(new_text, path)
    return new_text
