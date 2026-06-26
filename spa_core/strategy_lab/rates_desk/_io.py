"""
spa_core/strategy_lab/rates_desk/_io.py — the ONE atomic-write primitive for the rates desk.

Every rates-desk module that persists state/docs must write atomically (tmp file in the SAME
directory + ``shutil.move``, which is cross-device safe — repo rule #4) so a crash mid-write never
leaves a half-written JSON/markdown artifact. This module is the single source of that primitive;
the modules import ``atomic_write_text`` / ``atomic_write_json`` instead of each carrying a private
copy of the same ``mkstemp``/``move`` dance (a duplicated IO primitive is a latent drift hazard —
two copies can disagree on, e.g., encoding or cleanup).

Byte-identical to the prior per-module copies: ``json.dump(obj, f, indent=N, sort_keys=True,
default=D)`` writes exactly the same bytes as the old ``_atomic_write(json.dumps(obj, indent=N,
sort_keys=True, default=D))`` text path. Callers pass ``indent`` / ``default`` explicitly so each
file's existing on-disk shape is preserved verbatim.

PURE side-effect helper; stdlib only; LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (tmp in the same dir + ``shutil.move``, repo rule #4).

    Creates the parent directory if needed. On any failure the tmp file is removed, so a crash
    mid-write never leaves a half-written artifact at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        shutil.move(tmp, str(path))  # atomic, cross-device safe (repo rule #4)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(
    path: Path, obj: Any, *, indent: int = 1, sort_keys: bool = True,
    default: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Serialize ``obj`` to JSON and write it to ``path`` atomically (see ``atomic_write_text``).

    ``indent`` / ``sort_keys`` / ``default`` are explicit so each caller keeps its exact existing
    on-disk shape (the desk uses ``indent=1`` for data artifacts and ``indent=2`` for the
    promotion/refusal reports; ``default=str`` where Decimals are serialized)."""
    atomic_write_text(path, json.dumps(obj, indent=indent, sort_keys=sort_keys, default=default))
