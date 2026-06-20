"""
spa_core/utils/kanban.py
Thread-safe KANBAN.json increment utility.
"""
from __future__ import annotations

import fcntl
import json
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_KANBAN = _REPO_ROOT / "KANBAN.json"


def increment_done(n: int = 1, kanban_path: Optional[Path] = None) -> int:
    """
    Atomically increment done_count by n.
    Uses threading.Lock + fcntl.LOCK_EX for cross-process safety.
    Returns new count, or -1 on error.
    """
    path = Path(kanban_path) if kanban_path else _DEFAULT_KANBAN
    if not path.exists():
        return -1

    with _LOCK:
        try:
            with open(path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    data = json.load(f)
                    current = int(data.get("done_count", 0))
                    data["done_count"] = current + n
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
                    return data["done_count"]
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            return -1


def get_done_count(kanban_path: Optional[Path] = None) -> int:
    """Read-only: return current done_count from KANBAN.json."""
    path = Path(kanban_path) if kanban_path else _DEFAULT_KANBAN
    if not path.exists():
        return -1
    try:
        data = json.loads(path.read_text())
        return int(data.get("done_count", 0))
    except Exception:
        return -1
