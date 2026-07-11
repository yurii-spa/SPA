"""Shared helpers for swarm modules — metrics + the daily hash-chain proof appender.

Extracted from guardian_forward.py (block 1) so blend_forward.py (block 2) and later blocks reuse
ONE implementation. Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Sequence

GENESIS_HASH = "0" * 64


def max_drawdown_pct(equity: Sequence[float]) -> float:
    """Worst peak-to-trough drawdown of an equity path, as a negative percent (rounded)."""
    peak, worst = float("-inf"), 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return round(worst * 100.0, 4)


def apy_pct(equity: Sequence[float], days: int) -> Optional[float]:
    """Annualized return of an equity path over `days` calendar days (None if not computable)."""
    if days < 1 or len(equity) < 2 or equity[0] <= 0 or equity[-1] <= 0:
        return None
    return round(((equity[-1] / equity[0]) ** (365.0 / days) - 1.0) * 100.0, 4)


def append_daily_proof(payload: dict, proof_path: Path, *, day: str) -> bool:
    """Append one hash-chained line per UTC day (idempotent per day). `payload` must be
    JSON-serializable and must NOT already contain 'hash'/'prev_hash'/'date' — they are added here.
    Returns True if a line was appended, False if today's line already exists."""
    prev_hash, last_day = GENESIS_HASH, None
    try:
        with proof_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    prev_hash = rec.get("hash", prev_hash)
                    last_day = rec.get("date", last_day)
                except ValueError:
                    continue
    except OSError:
        pass
    if last_day == day:
        return False
    rec = dict(payload)
    rec["date"] = day
    rec["prev_hash"] = prev_hash
    rec["hash"] = hashlib.sha256((prev_hash + json.dumps(rec, sort_keys=True)).encode()).hexdigest()
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return True
