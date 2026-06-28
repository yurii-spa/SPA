"""
spa_core/strategy_lab/rates_desk/anchors.py — the CROSS-EVICTION immutability anchor ledger.

THE PROBLEM this closes (docs/PROOF_CHAIN_SPEC.md §5 "Anchoring caveat"): the PUBLIC decision mirror
(`decision_log.jsonl`) is a re-based, RING-BUFFERED window (`LOG_CAP = 2000`). Its `head_hash` is a
*sliding-window* head — stable across normal appends, but it re-bases when the ring evicts old rows.
So "anchor the head now, re-check it later" proves immutability ONLY within the current window. The
all-time guarantee lives in the authoritative, append-only producer ledger `data/audit_chain.jsonl`
(never re-based, never truncated) — but that file grows without bound and an outsider has no compact
external checkpoint of it.

THE FIX: periodically publish a tiny, APPEND-ONLY anchor record that checkpoints the PUBLIC decision
chain's current re-based head:

    {"ts", "seq", "head_hash", "chain_length", "event_type"}

  • `head_hash`    — the `head_hash` of the PUBLIC `data/rates_desk/decision_log.jsonl` at that moment
                     (= its LAST row's entry_hash, per PROOF_CHAIN_SPEC §5). This is the value a third
                     party RE-DERIVES standalone with verify_spa.py — so each anchor is independently
                     checkable from public files alone (no producer ledger access needed).
  • `chain_length` — how many rows the public mirror had at that checkpoint.
  • `seq`          — the anchor's own monotonic 0..N index in THIS ledger (append-only).

`data/rates_desk/anchors.jsonl` is APPEND-ONLY, MONOTONIC, and NEVER re-based or truncated (the very
opposite of the ring-buffered mirror). Each anchor is a time-stamped external checkpoint: a reviewer
who recorded an anchor at window-length L (with its head_hash) can later re-run verify_spa.py and
confirm the published chain at that length STILL hashes to the same head — proving no in-window
decision was silently rewritten between the two checks, across as many checkpoints as they have
collected. Combined with the authoritative append-only producer ledger `data/audit_chain.jsonl`
(which hash_chain owns and which is never re-based), this gives cross-eviction immutability that
extends BEYOND the 2000-row public window.

verify_spa.py (the standalone verifier) confirms each anchor against the decision-chain head it
checkpoints (the anchor whose chain_length == the re-derived chain length must carry that exact head),
so the whole mechanism is third-party-reproducible WITHOUT our code.

PURE serialization (no pricing/policy); stdlib only; LLM-FORBIDDEN; APPEND-ONLY atomic write
(append a single line via tmp-rewrite + os.replace so a crash mid-write never tears a line).
Idempotent per producer head: appending when the head is unchanged is a no-op (no duplicate anchors).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import List, Optional

from spa_core.strategy_lab.rates_desk import proof_chain

_ROOT = Path(__file__).resolve().parents[3]
_ANCHORS = _ROOT / "data" / "rates_desk" / "anchors.jsonl"
_DECISION_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"

ANCHOR_EVENT_TYPE = "rates_desk_anchor"


def _read_anchors(path: Path) -> List[dict]:
    """Read the append-only anchor ledger; [] if absent. fail-CLOSED skips corrupt lines (but the
    verifier treats a corrupt ledger as invalid — see verify_spa.py)."""
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
                continue
    except OSError:
        return []
    return rows


def _decision_log_head(log_path: Optional[Path] = None) -> tuple[Optional[str], int]:
    """The PUBLIC decision chain's current (head_hash, chain_length) — re-derived EXACTLY as a third
    party would per PROOF_CHAIN_SPEC §5 (delegating to the single shared verifier proof_chain.
    verify_mirror so the anchored head is byte-identical to what /api/rates-desk/proof and
    verify_spa.py report). A broken/absent chain → (None, length); anchors are never minted over an
    unverified head (fail-CLOSED). This is the value verify_spa.py can re-derive from public files."""
    path = log_path or _DECISION_LOG
    rows: List[dict] = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    rows.append({"__corrupt__": True})
        except OSError:
            return None, 0
    res = proof_chain.verify_mirror(rows)
    if not res.get("valid"):
        return None, res.get("length", len(rows))  # fail-CLOSED: never anchor an unverified head
    return res.get("head_hash"), res.get("length", len(rows))


def _atomic_append_line(path: Path, line: str) -> None:
    """APPEND-ONLY atomic write: read existing bytes, append the new line, rewrite a tmp file in the
    same dir, os.replace. Never re-bases or rewrites existing lines (only appends one). Atomic so a
    crash mid-write can never tear a line. (We rewrite-the-whole-file-plus-one rather than O_APPEND so
    the swap is atomic and crash-safe, while the CONTENT is strictly append-only — existing lines are
    copied verbatim, never mutated.)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n"):
            existing += "\n"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(existing + line + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def append_anchor(
    *,
    ts: Optional[str] = None,
    anchors_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
    head_hash: Optional[str] = None,
    chain_length: Optional[int] = None,
) -> Optional[dict]:
    """Append ONE cross-eviction anchor checkpointing the producer ledger's all-time head.

    Idempotent: if the latest anchor already checkpoints the SAME (head_hash, chain_length), this is a
    no-op and returns None (no duplicate anchors when nothing has appended). Monotonic: refuses to
    append an anchor whose chain_length is SHORTER than the last anchor's (the append-only producer
    ledger length never decreases — a shorter length would indicate corruption; fail-CLOSED no-op).

    Args:
        ts:            ISO-8601 timestamp (supply in tests for determinism; prod defaults to UTC now).
        anchors_path:  override the ledger path (tests/hermetic).
        log_path:      override the decision_log path to anchor (tests/hermetic).
        head_hash:     override the head to anchor (tests); else re-derive from the public chain.
        chain_length:  override the chain length (tests); else re-derive from the public chain.

    Returns the appended anchor dict, or None on a no-op."""
    path = anchors_path or _ANCHORS
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if head_hash is None or chain_length is None:
        ph, pl = _decision_log_head(log_path)
        head_hash = head_hash if head_hash is not None else ph
        chain_length = chain_length if chain_length is not None else pl

    if head_hash is None or chain_length is None or chain_length <= 0:
        return None  # nothing verified to checkpoint yet (empty/broken chain) — fail-CLOSED no-op

    existing = _read_anchors(path)
    if existing:
        last = existing[-1]
        # idempotent: same head already checkpointed → no-op.
        if last.get("head_hash") == head_hash and last.get("chain_length") == chain_length:
            return None
        # monotonic guard: never checkpoint a SHORTER chain than the last anchor (fail-CLOSED).
        last_len = last.get("chain_length")
        if isinstance(last_len, int) and chain_length < last_len:
            return None

    seq = len(existing)
    anchor = {
        "event_type": ANCHOR_EVENT_TYPE,
        "seq": seq,
        "ts": ts,
        "head_hash": head_hash,
        "chain_length": int(chain_length),
    }
    line = json.dumps(anchor, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    _atomic_append_line(path, line)
    return anchor


def verify_anchors(anchors: Optional[List[dict]] = None,
                   anchors_path: Optional[Path] = None,
                   log_path: Optional[Path] = None) -> dict:
    """Verify the anchor ledger is append-only + monotonic, and the anchor that checkpoints the CURRENT
    chain length carries the current head_hash. Mirrors the standalone verify_spa.py logic so the
    server verdict == the verifier's. Returns {valid, length, broken_at, latest_matches_head}. Empty
    is vacuously valid."""
    rows = anchors if anchors is not None else _read_anchors(anchors_path or _ANCHORS)
    n = len(rows)
    if n == 0:
        return {"valid": True, "length": 0, "broken_at": None, "latest_matches_head": None}
    prod_head, prod_len = _decision_log_head(log_path)
    prev_seq = -1
    prev_len = -1
    latest_matches: Optional[bool] = None
    for idx, a in enumerate(rows):
        if not isinstance(a, dict):
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        seq, clen, head = a.get("seq"), a.get("chain_length"), a.get("head_hash")
        if not isinstance(seq, int) or seq != idx or seq <= prev_seq:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if not isinstance(clen, int) or clen < prev_len:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if not isinstance(head, str) or len(head) != 64:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if prod_head is not None and clen == prod_len:
            if head != prod_head:
                return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": False}
            latest_matches = True
        prev_seq, prev_len = seq, clen
    return {"valid": True, "length": n, "broken_at": None, "latest_matches_head": latest_matches}


def recent_anchors(n: int = 20, anchors_path: Optional[Path] = None) -> List[dict]:
    """The last `n` anchors (most recent last). Graceful: absent ledger → []."""
    if n <= 0:
        return []
    return _read_anchors(anchors_path or _ANCHORS)[-n:]


def main() -> int:
    a = append_anchor()
    if a is None:
        print("anchor: no-op (producer head unchanged or empty ledger)")
    else:
        print(f"anchor appended: seq={a['seq']} chain_length={a['chain_length']} head={a['head_hash']}")
    v = verify_anchors()
    print(json.dumps(v, indent=2))
    print(f"Ledger: {_ANCHORS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
