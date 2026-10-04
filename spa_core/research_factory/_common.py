"""Small shared helpers for the Research Factory package (not part of the frozen contract).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract
from spa_core.utils.hash_ledger import HashLedger


def iso(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: M7 rework: ONE HashLedger instance per resolved data_dir, for the lifetime of this process.
#: Every call site in this package goes through :func:`ledger_for`, so they all share the SAME
#: instance (and therefore the same `read_all()` cache and the same post-verify "trusted" flag —
#: see `HashLedger.mark_verified`) instead of each re-reading the whole ledger file from disk.
#: Nothing here is shared ACROSS processes (each process gets its own fresh dict on import), so
#: the real multiprocessing/concurrency guarantees are unaffected — they are enforced by the
#: ledger's own file lock, not by this process-local convenience cache.
_LEDGER_CACHE: dict = {}


def ledger_for(data_dir: Path) -> HashLedger:
    key = str(Path(data_dir).resolve())
    led = _LEDGER_CACHE.get(key)
    if led is None:
        led = HashLedger(Path(data_dir), contract.DATA_SUBDIR, contract.ANCHORS_SUBDIR, contract.LEDGER)
        _LEDGER_CACHE[key] = led
    return led


def code_identity() -> str:
    """sha256 over every ``.py`` source file directly inside this package (not ``scanners/``,
    not tests) — ADMISSION_SNAPSHOT_FIELDS' ``code_identity``."""
    pkg_dir = Path(__file__).resolve().parent
    parts = []
    for p in sorted(pkg_dir.glob("*.py")):
        parts.append(p.name)
        parts.append(p.read_text(encoding="utf-8"))
    return contract.digest(parts)


def rel_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom
