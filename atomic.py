"""
spa_core/utils/atomic.py
Centralized atomic file operations — replaces copy-pasted tmp+os.replace pattern.
"""
import contextlib
import os
import json
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_MISSING = object()  # sentinel to distinguish "no default" from "default=None"


def atomic_save(data: Any, path: str, indent: int = 2) -> None:
    """
    Safely saves JSON-serializable data to path using tmp+os.replace.
    Creates parent directories if needed.
    Never leaves partial writes on crash.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_load(path: str, default: Optional[Any] = _MISSING) -> Any:
    """Loads JSON from path. Returns default (empty dict) if file missing."""
    if not os.path.exists(path):
        return {} if default is _MISSING else default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_append(item: Any, path: str, key: str = "items", cap: Optional[int] = None) -> None:
    """Appends item to list[key] in JSON file, respecting optional ring-buffer cap."""
    data = atomic_load(path, {key: []})
    lst = data.setdefault(key, [])
    lst.append(item)
    if cap and len(lst) > cap:
        data[key] = lst[-cap:]
    atomic_save(data, path)


def atomic_append_ring(
    item: Any,
    path: str,
    *,
    cap: int = 100,
    list_key: Optional[str] = None,
) -> int:
    """Append *item* to a JSON ring-buffer, capped at *cap* entries.

    Two storage formats:
      - list_key=None  → file is a JSON array [...]
      - list_key="k"   → file is {"k": [...], ...}  (extra keys preserved)

    Returns new list length (<=cap).
    This is AUDIT-001 canonical replacement for _append_ring_log scattered
    across ~400 analytics modules.
    """
    if list_key is None:
        try:
            existing = atomic_load(path, default=[])
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, ValueError):
            existing = []
        existing.append(item)
        if len(existing) > cap:
            existing = existing[-cap:]
        atomic_save(existing, path)
        return len(existing)
    else:
        try:
            data = atomic_load(path, default={})
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, ValueError):
            data = {}
        lst = data.get(list_key, [])
        if not isinstance(lst, list):
            lst = []
        lst.append(item)
        if len(lst) > cap:
            lst = lst[-cap:]
        data[list_key] = lst
        atomic_save(data, path)
        return len(lst)


def atomic_save_text(text: str, path: str, encoding: str = "utf-8", fsync: bool = True) -> None:
    """Safely saves text to path using tmp+os.replace.

    Replaces copy-pasted ``_atomic_write_text`` / ``tempfile.mkstemp`` patterns
    in text-output modules (markdown tear-sheets, monthly reports, etc.).
    Creates parent directories if needed. Never leaves partial writes on crash.

    Args:
        text:     String content to write.
        path:     Destination file path (str or PathLike accepted as str).
        encoding: Character encoding (default utf-8).
        fsync:    If True (default), flushes OS buffers before rename.
    """
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def atomic_write_via_tmp(path: str) -> Iterator[Path]:
    """Context manager for binary or external-writer atomic writes.

    Yields a temporary :class:`~pathlib.Path` in the same directory as
    *path*.  The caller writes its content to the yielded path (e.g. PDF,
    CSV, binary).  On clean exit the tmp file is renamed to *path*; on any
    exception the tmp file is cleaned up and the exception re-raised.

    Replaces the ``tempfile.mkstemp / os.close / try / os.replace`` pattern
    in modules that cannot use :func:`atomic_save` because they produce
    non-JSON output (MP-1471).

    Example::

        with atomic_write_via_tmp(str(out_path)) as tmp:
            _build_pdf(ctx, tmp)          # writes binary PDF to tmp
        # tmp is now renamed to out_path atomically
    """
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_str = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_str)
    try:
        yield tmp_path
        os.replace(tmp_str, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_update(path: str, update_fn: Callable[[Any], Any], default: Optional[Any] = None) -> Any:
    """Read-modify-write helper (single-process contexts only).

    For concurrent multi-process access use kanban.increment_done (fcntl.flock).

    Args:
        path: File path.
        update_fn: Callable(current_data) -> new_data.
        default: Seed value if the file does not exist (default: {}).

    Returns:
        The new data after update_fn is applied.

    Example::

        atomic_update("state.json", lambda d: {**d, "count": d.get("count", 0) + 1})
    """
    current = atomic_load(path, default=default)
    new_data = update_fn(current)
    atomic_save(new_data, path)
    return new_data
