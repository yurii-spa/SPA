"""
spa_core/utils/atomic.py
Centralized atomic file operations — replaces copy-pasted tmp+os.replace pattern.
"""
import os
import json
import tempfile
from typing import Any, Optional

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


def atomic_update(path: str, update_fn, default: Optional[Any] = None) -> Any:
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
