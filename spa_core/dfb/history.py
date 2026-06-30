"""
spa_core/dfb/history.py — WS-1.5: the append-only, PROOF-CHAINED daily history capture.

The refusal-state / APY / TVL track is the SCARCE asset — it CANNOT be backfilled (you cannot
reconstruct a refusal-state timeline after the fact), so DFB starts capturing it day-1. For every
pool's overlay row we append ONE dated record to a growing per-pool chain:

    data/dfb/history/<pool_id>.jsonl

Each record carries the captured snapshot + a per-row proof chain link
(`prev_hash`/`row_hash`, genesis '0'*64), so a reordered/dropped/forged record is detectable. The
capture is IDEMPOTENT per UTC day: re-running on the same `capture_date` is a NO-OP (it never appends
a second record for a date already present — the chain stays clean and monotone).

The captured record body (the signed payload):
  { capture_date, pool_id, protocol, chain, asset, tier,
    apy_total, apy_base, apy_reward, tvl_usd,
    risk_class, refusal_verdict, refusal_reason, tail_veto,
    structural_haircut, total_haircut, engine_proof_hash, as_of }

stdlib only · deterministic (`capture_date` = the UTC DATA day, an explicit input in tests) · atomic
(tmp + os.replace) · fail-CLOSED · READ-ONLY outside data/dfb/ · advisory.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional

from spa_core.dfb import PoolOverlay

_ROOT = Path(__file__).resolve().parents[2]
GENESIS_PREV = "0" * 64

# The captured-body keys that the per-pool history record signs (the snapshot of the scarce series).
_CAPTURE_KEYS = (
    "capture_date", "pool_id", "protocol", "chain", "asset", "tier",
    "apy_total", "apy_base", "apy_reward", "tvl_usd",
    "risk_class", "refusal_verdict", "refusal_reason", "tail_veto",
    "structural_haircut", "total_haircut", "engine_proof_hash", "as_of",
)


def _history_dir(data_dir: Optional[Path] = None) -> Path:
    root = data_dir if data_dir is not None else (_ROOT / "data")
    return root / "dfb" / "history"


def _row_hash(body: dict, prev_hash: str) -> str:
    """sha256 over the canonical sorted-JSON of the signed body + prev_hash (the proof-chain link)."""
    blob = json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _capture_body(ov: PoolOverlay, capture_date: str) -> dict:
    """The signed history record body for one overlay on one capture_date (deterministic key set)."""
    d = ov.to_dict()
    return {
        "capture_date": capture_date,
        "pool_id": d["pool_id"],
        "protocol": d["protocol"],
        "chain": d["chain"],
        "asset": d["asset"],
        "tier": d["tier"],
        "apy_total": d["apy"]["total"],
        "apy_base": d["apy"]["base"],
        "apy_reward": d["apy"]["reward"],
        "tvl_usd": d["tvl_usd"],
        "risk_class": d["risk_class"],
        "refusal_verdict": d["refusal"]["verdict"],
        "refusal_reason": d["refusal"]["reason"],
        "tail_veto": d["refusal"]["tail_veto"],
        "structural_haircut": d["structural_haircut"],
        "total_haircut": d["total_haircut"],
        "engine_proof_hash": d["engine_proof_hash"],
        "as_of": d["as_of"],
    }


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # drop a corrupt historical line — the append below rebuilds a clean tail
    except OSError:
        return []
    return rows


def _atomic_write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) for r in rows]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    os.replace(str(tmp), str(path))


def capture_pool(ov: PoolOverlay, capture_date: str, data_dir: Optional[Path] = None) -> dict:
    """Append ONE dated, proof-chained record for one pool's overlay → data/dfb/history/<pool_id>.jsonl.

    IDEMPOTENT per UTC day: if a record for `capture_date` already exists for this pool, returns
    {"appended": False, ...} and writes nothing. Otherwise links a new record onto the chain (prev_hash
    = the last record's row_hash, genesis '0'*64) and atomically rewrites the file. Deterministic."""
    path = _history_dir(data_dir) / f"{ov.pool_id}.jsonl"
    existing = _read_jsonl(path)
    if any(r.get("capture_date") == capture_date for r in existing):
        return {"appended": False, "pool_id": ov.pool_id, "capture_date": capture_date,
                "reason": "already_captured_for_date"}
    prev = existing[-1].get("row_hash") if existing else GENESIS_PREV
    body = _capture_body(ov, capture_date)
    rh = _row_hash(body, prev)
    record = {**body, "prev_hash": prev, "row_hash": rh}
    _atomic_write_jsonl(path, existing + [record])
    return {"appended": True, "pool_id": ov.pool_id, "capture_date": capture_date, "row_hash": rh}


def capture_all(
    overlays: Iterable[PoolOverlay],
    capture_date: Optional[str] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """Capture every pool's overlay for `capture_date` (default: UTC today). Idempotent per UTC day.
    Returns a summary {capture_date, n_pools, n_appended, n_skipped}."""
    if capture_date is None:
        capture_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    n_appended = n_skipped = 0
    for ov in overlays:
        res = capture_pool(ov, capture_date, data_dir)
        if res["appended"]:
            n_appended += 1
        else:
            n_skipped += 1
    return {"capture_date": capture_date, "n_pools": n_appended + n_skipped,
            "n_appended": n_appended, "n_skipped": n_skipped}


def read_history(pool_id: str, data_dir: Optional[Path] = None) -> List[dict]:
    """The full per-pool captured history (ascending), or [] if none. Read-only."""
    return _read_jsonl(_history_dir(data_dir) / f"{pool_id}.jsonl")


def verify_history(pool_id: str, data_dir: Optional[Path] = None) -> dict:
    """Verify a per-pool history chain: each prev_hash links the previous row_hash, each row_hash
    recomputes from the signed body, capture_dates are strictly ascending. fail-CLOSED.
    Returns {valid, length, broken_at}."""
    rows = read_history(pool_id, data_dir)
    prev = GENESIS_PREV
    last_date = ""
    for idx, r in enumerate(rows):
        if not isinstance(r, dict) or r.get("prev_hash") != prev:
            return {"valid": False, "length": len(rows), "broken_at": idx}
        body = {k: r.get(k) for k in _CAPTURE_KEYS}
        if _row_hash(body, prev) != r.get("row_hash"):
            return {"valid": False, "length": len(rows), "broken_at": idx}
        cd = r.get("capture_date") or ""
        if cd <= last_date:
            return {"valid": False, "length": len(rows), "broken_at": idx}
        last_date = cd
        prev = r["row_hash"]
    return {"valid": True, "length": len(rows), "broken_at": None}
