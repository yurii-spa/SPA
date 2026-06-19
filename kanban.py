"""
spa_core/utils/kanban.py
Thread-safe KANBAN.json updater with file locking.
"""
import fcntl
import json
import os
from typing import Optional


def increment_done(base_dir: str = ".", n: int = 1, sprint: Optional[str] = None) -> int:
    """
    Atomically increments done_count by n using fcntl.LOCK_EX.
    Returns new done_count.
    """
    path = os.path.join(base_dir, "KANBAN.json")
    with open(path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = json.load(f)
            data["done_count"] = data.get("done_count", 0) + n
            if sprint:
                data["sprint_completed"] = sprint
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
            return data["done_count"]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
