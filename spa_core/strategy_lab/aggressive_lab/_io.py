"""
spa_core/strategy_lab/aggressive_lab/_io.py — the ONE atomic writer for the Aggressive Lab,
ROUTED THROUGH the isolation guard.

Every persistence the lab does goes through here. Before any byte is written, the target path is
passed through ``isolation.assert_safe_write_path`` — so a coding mistake, a malicious strategy id,
or a path-traversal can NEVER land a write on a go-live / live-allocation file. The write itself is
atomic (tmp in the SAME dir + os.replace — repo rule #4, no cross-device EXDEV).

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.strategy_lab.aggressive_lab.isolation import assert_safe_write_path


def atomic_write_text(path: Path, text: str, *, lab_root: Optional[Path] = None) -> Path:
    """Atomically write text to a SAFE aggressive-lab path (isolation-guarded). Returns the
    resolved path. Creates the parent dir. On any failure the tmp file is removed.

    ``lab_root`` (default data/aggressive_lab/) is the sandbox root the guard pins writes inside;
    tests pass their temp state_dir. The protected-name refusal is ALWAYS active regardless."""
    safe = assert_safe_write_path(path, lab_root=lab_root)
    safe.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(safe.parent), prefix="." + safe.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(safe))  # atomic, same-dir → no EXDEV
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return safe


def atomic_write_json(
    path: Path, obj: Any, *, indent: int = 2, sort_keys: bool = True,
    default: Optional[Callable[[Any], Any]] = str, lab_root: Optional[Path] = None,
) -> Path:
    """Serialize obj → JSON and atomically write it to a SAFE aggressive-lab path."""
    return atomic_write_text(
        path, json.dumps(obj, indent=indent, sort_keys=sort_keys, default=default), lab_root=lab_root)


def atomic_append_jsonl_line(path: Path, obj: dict, *, lab_root: Optional[Path] = None) -> Path:
    """Append ONE JSON object as a line to a SAFE aggressive-lab JSONL file, atomically.

    Read-modify-write: the existing file is read, the new line appended, and the whole file is
    re-written atomically (tmp + os.replace). For the lab's per-day cadence this is cheap and keeps
    the file always-valid (a crash can never leave a half-written line). Idempotency (don't double-
    append the same UTC day) is the CALLER's job — see harness.upsert_day."""
    safe = assert_safe_write_path(path, lab_root=lab_root)
    existing = ""
    if safe.is_file():
        existing = safe.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n"):
            existing += "\n"
    line = json.dumps(obj, sort_keys=True) + "\n"
    return atomic_write_text(safe, existing + line)


def read_jsonl(path: Path) -> list:
    """Read a JSONL file → list of parsed objects (malformed lines dropped). Missing → []."""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001 — a bad line is dropped, never fabricated
            continue
    return out
