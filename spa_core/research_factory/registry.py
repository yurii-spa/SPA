"""spa_core/research_factory/registry.py — candidate upsert + disposable read-model index.

ADR-560 (RM-EXPAND-01). RESEARCH / PAPER only; see ``contract`` module docstring.

A "candidate" is identified by ``candidate_id`` (``contract.candidate_id(exposure_key)``). This
module records, for one candidate, every snapshot of its SCANNED fields (identity/cells/risk) —
written only when the fingerprint changes (``contract.SNAPSHOT_FINGERPRINT_EXCLUDES`` and, inside
every cell, ``contract.CELL_FINGERPRINT_EXCLUDES``, are both excluded from the fingerprint so a
bare re-observation of the SAME facts never creates a duplicate row). Concurrent upserts of the
SAME exposure key collapse to one row via the ledger's own keyed idempotency
(``kind="candidate_snapshot"``, ``key=[candidate_id, fingerprint]``) under its file lock.

``index.json`` is a disposable read-model cache. Every function in THIS module that needs the
truth reads the ledger directly — nothing here ever trusts the index over the ledger; a
corrupt or missing index is simply rebuilt (see :func:`load_index`).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from spa_core.research_factory import contract
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.atomic import atomic_save
from spa_core.utils.hash_ledger import DuplicateKey, HashLedger


def _strip_timestamps(value: Any) -> Any:
    """H2 rework: strip ``CELL_FINGERPRINT_EXCLUDES`` keys (``as_of``/``recorded_at``) from
    EVERY dict found ANYWHERE in the structure — not only the top-level named cell fields.
    Real scanner output nests cells inside lists too (``source_refs``, counterparty role/
    dimension maps), and each one carries its own re-observation timestamp that must never
    make an otherwise-identical candidate look changed."""
    if isinstance(value, dict):
        return {k: _strip_timestamps(v) for k, v in value.items() if k not in contract.CELL_FINGERPRINT_EXCLUDES}
    if isinstance(value, list):
        return [_strip_timestamps(v) for v in value]
    return value


def fingerprint_of(candidate: dict) -> str:
    """Digest of a candidate dict EXCLUDING the lifecycle-owned fields
    (``SNAPSHOT_FINGERPRINT_EXCLUDES``) and, EVERYWHERE in the remaining structure, every
    ``as_of``/``recorded_at`` key (``CELL_FINGERPRINT_EXCLUDES``) — so re-observing the same
    facts (same numbers, fresh timestamps) never looks like change, no matter how deeply the
    timestamp is nested (a single cell, a list of ``source_refs`` cells, a counterparty
    role/dimension map, ...)."""
    reduced = {k: v for k, v in candidate.items() if k not in contract.SNAPSHOT_FINGERPRINT_EXCLUDES}
    return contract.digest(_strip_timestamps(reduced))


def latest_snapshot(ledger: HashLedger, candidate_id: str) -> Optional[dict]:
    best = None
    for e in ledger.read_all():
        if e.get("kind") != "candidate_snapshot":
            continue
        payload = e.get("payload") or {}
        if (payload.get("candidate") or {}).get("candidate_id") != candidate_id:
            continue
        if best is None or e["seq"] > best["seq"]:
            best = e
    return best


def all_candidate_ids(ledger: HashLedger) -> list:
    seen = []
    for e in ledger.read_all():
        if e.get("kind") != "candidate_snapshot":
            continue
        cid = ((e.get("payload") or {}).get("candidate") or {}).get("candidate_id")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


def upsert(data_dir: Path, candidate: dict, now: datetime) -> dict:
    """Write a new ``candidate_snapshot`` row only if the fingerprint changed; otherwise return
    the existing latest snapshot untouched. First-ever sighting also enters the candidate into
    the lifecycle at DISCOVERED."""
    ledger = ledger_for(data_dir)
    cid = candidate["candidate_id"]
    fp = fingerprint_of(candidate)
    prior = latest_snapshot(ledger, cid)
    is_new = prior is None
    if prior is not None and (prior.get("payload") or {}).get("fingerprint") == fp:
        return prior
    at = iso(now)
    payload = {"candidate": candidate, "fingerprint": fp}
    key = ["candidate_snapshot", cid, fp]
    try:
        entry = ledger.append("candidate_snapshot", key, payload, at)
    except DuplicateKey as dup:
        entry = dup.existing  # a concurrent writer already recorded this exact fingerprint
    if is_new:
        from spa_core.research_factory import lifecycle
        lifecycle.ensure_discovered(data_dir, cid, now)
    return entry


def record_unresolved(data_dir: Path, scanner: str, domain: str, entry: dict, now: datetime) -> dict:
    """A scanner entry that could not build an exposure key. Minted a synthetic id (never a
    symbol fallback for a REAL exposure key — this is a DIFFERENT, scanner-local identity) and
    is placed straight into DATA_INSUFFICIENT with the reason named."""
    from spa_core.research_factory import lifecycle
    name = entry.get("name", "")
    reason = entry.get("reason", "unresolved")
    cid = contract.candidate_id(f"unresolved|{scanner}|{name}")
    skeleton = {f: None for f in contract.CANDIDATE_FIELDS}
    skeleton.update({
        "candidate_id": cid, "exposure_key": None, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": None, "asset_class": None, "domain": domain, "venue_or_protocol": scanner,
        "instrument": name, "unknowns": [reason],
    })
    skeleton["producing_scanner"] = scanner
    snap = upsert(data_dir, skeleton, now)
    lifecycle.transition(data_dir, cid, contract.DATA_INSUFFICIENT, reason=f"unresolved: {reason}", now=now)
    return snap


def current_candidate(data_dir: Path, candidate_id: str) -> Optional[dict]:
    ledger = ledger_for(data_dir)
    snap = latest_snapshot(ledger, candidate_id)
    return (snap.get("payload") or {}).get("candidate") if snap else None


def rebuild_index(data_dir: Path) -> dict:
    """The disposable read model: candidate_id -> {fingerprint, candidate, snapshot_seq}. Always
    derived fresh from the ledger; never the other way around."""
    ledger = ledger_for(data_dir)
    out: dict = {}
    for cid in all_candidate_ids(ledger):
        snap = latest_snapshot(ledger, cid)
        if snap is None:
            continue
        payload = snap.get("payload") or {}
        out[cid] = {"fingerprint": payload.get("fingerprint"), "candidate": payload.get("candidate"),
                   "snapshot_seq": snap.get("seq")}
    index = {"schema": "research-factory-index/1", "candidates": out, "ledger_head_hash": ledger.head_hash()}
    atomic_save(index, str(ledger.root() / contract.INDEX))
    return index


def load_index(data_dir: Path) -> dict:
    """Try the cached index; a missing/corrupt/stale file is rebuilt transparently — it is NEVER
    trusted over the ledger. 'Stale' means its recorded head hash no longer matches the ledger's
    current head: rather than serve data that no longer matches the ledger, rebuild."""
    ledger = ledger_for(data_dir)
    path = ledger.root() / contract.INDEX
    if path.exists():
        try:
            with open(path, "r") as f:
                cached = json.load(f)
            if isinstance(cached, dict) and cached.get("ledger_head_hash") == ledger.head_hash():
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    return rebuild_index(data_dir)
