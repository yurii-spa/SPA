"""
spa_core/audit/hash_chain.py — Tamper-evident, hash-chained audit trail.

PARALLEL LAYER — institutional integrity requirement. A blockchain-style,
append-only log where each entry carries the SHA-256 hash of the previous entry,
so any post-hoc mutation of a historical entry breaks the chain and is detectable.

This module does NOT modify or import any canonical SPA module. It is a thin,
self-contained, stdlib-only ledger that producers (cycle_runner, threat_reactor,
RiskPolicy gate, …) MAY call later to record immutable evidence.

Entry shape::

    {
        "seq":        int,            # 0-based monotonic sequence
        "ts":         str,            # ISO-8601 timestamp (caller-supplied for determinism)
        "event_type": str,            # e.g. "cycle", "risk_event"
        "payload":    dict,           # arbitrary JSON-serialisable body
        "prev_hash":  str,            # entry_hash of seq-1 ('0'*64 for genesis)
        "entry_hash": str,            # sha256 over canonical(seq, ts, event_type, payload, prev_hash)
    }

Canonical JSON = json.dumps(..., sort_keys=True, separators=(',', ':')) so the
hash is stable across processes and Python runs (deterministic).

Stored as JSONL at data/audit_chain.jsonl (one entry per line). Appends are
atomic: read-modify-write to a tmp file then os.replace over the destination,
so a crash mid-write never leaves a torn line.

Deterministic. stdlib only. No LLM anywhere in the integrity path.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_CHAIN = _DATA / "audit_chain.jsonl"

GENESIS_PREV = "0" * 64


# --------------------------------------------------------------------------- #
# Path indirection (so tests can redirect away from the real data file)
# --------------------------------------------------------------------------- #
def _chain_path() -> Path:
    """Resolve the chain file path each call so monkeypatching _CHAIN works."""
    return _CHAIN


# --------------------------------------------------------------------------- #
# Canonical hashing
# --------------------------------------------------------------------------- #
def _canonical(seq: int, ts: str, event_type: str, payload: dict, prev_hash: str) -> str:
    """Deterministic canonical JSON of the hash-covered fields (excludes entry_hash)."""
    return json.dumps(
        {
            "seq": seq,
            "ts": ts,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_entry_hash(seq: int, ts: str, event_type: str, payload: dict, prev_hash: str) -> str:
    """SHA-256 hex over the canonical JSON of the hash-covered fields."""
    canon = _canonical(seq, ts, event_type, payload, prev_hash)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Disk I/O (atomic)
# --------------------------------------------------------------------------- #
def _read_all() -> list:
    """Return every entry as a list of dicts; [] if the chain file is absent/empty."""
    path = _chain_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def _atomic_write_all(entries: list) -> None:
    """Serialise every entry to JSONL and atomically replace the chain file.

    Read-modify-write: the full ledger is rendered to a tmp file in the same
    directory, then os.replace() swaps it in (atomic on POSIX), so a partial
    write can never corrupt the live chain.
    """
    path = _chain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".audit_chain_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure; never leave .audit_chain_*
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def append(event_type: str, payload: dict, ts: Optional[str] = None) -> dict:
    """Append one entry, linking it to the current chain head, and persist.

    Args:
        event_type: short event tag (e.g. "cycle", "risk_event").
        payload: JSON-serialisable body.
        ts: ISO-8601 timestamp. MUST be supplied in tests for determinism; in
            production, defaults to UTC now.

    Returns the fully-formed entry (incl. seq, prev_hash, entry_hash).
    """
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if payload is None:
        payload = {}

    entries = _read_all()
    seq = len(entries)
    prev_hash = entries[-1]["entry_hash"] if entries else GENESIS_PREV
    entry_hash = compute_entry_hash(seq, ts, event_type, payload, prev_hash)

    entry = {
        "seq": seq,
        "ts": ts,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }
    entries.append(entry)
    _atomic_write_all(entries)
    return entry


def verify_chain() -> dict:
    """Recompute every hash and check prev-linkage; detect any tampering.

    Returns::

        {"valid": bool, "length": int, "broken_at": Optional[int]}

    ``broken_at`` is the seq of the first entry that fails verification
    (wrong recomputed hash, broken prev-link, or out-of-order seq), else None.
    An empty chain is valid.
    """
    entries = _read_all()
    expected_prev = GENESIS_PREV
    for idx, e in enumerate(entries):
        # seq must be monotonic and match position.
        if e.get("seq") != idx:
            return {"valid": False, "length": len(entries), "broken_at": idx}
        # prev_hash must link to the previous entry's entry_hash.
        if e.get("prev_hash") != expected_prev:
            return {"valid": False, "length": len(entries), "broken_at": idx}
        # entry_hash must match a fresh recompute over the covered fields.
        recomputed = compute_entry_hash(
            e.get("seq"),
            e.get("ts"),
            e.get("event_type"),
            e.get("payload"),
            e.get("prev_hash"),
        )
        if recomputed != e.get("entry_hash"):
            return {"valid": False, "length": len(entries), "broken_at": idx}
        expected_prev = e["entry_hash"]
    return {"valid": True, "length": len(entries), "broken_at": None}


def tail(n: int = 20) -> list:
    """Return the last ``n`` entries (most recent last)."""
    if n <= 0:
        return []
    return _read_all()[-n:]


def head() -> Optional[dict]:
    """Return the genesis (first) entry, or None on an empty chain."""
    entries = _read_all()
    return entries[0] if entries else None


# --------------------------------------------------------------------------- #
# Typed wrappers (thin helpers for known producers)
# --------------------------------------------------------------------------- #
def record_cycle(summary_dict: dict, ts: str) -> dict:
    """Record a paper-trading cycle summary as a 'cycle' entry."""
    return append("cycle", summary_dict, ts=ts)


def record_risk_event(reason: str, ts: str) -> dict:
    """Record a risk / kill-switch event as a 'risk_event' entry."""
    return append("risk_event", {"reason": reason}, ts=ts)


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # Fixed timestamps → deterministic demo output (also useful for a smoke check).
    record_cycle(
        {"date": "2026-06-24", "equity_usd": 100149.54, "apy_today_pct": 4.9},
        ts="2026-06-24T08:00:00+00:00",
    )
    record_risk_event(
        "TVL floor breach on example_pool (read-only advisory)",
        ts="2026-06-24T08:05:00+00:00",
    )
    print(json.dumps(verify_chain(), indent=2))
    print(json.dumps({"head": head(), "tail": tail(2)}, indent=2, ensure_ascii=False))
