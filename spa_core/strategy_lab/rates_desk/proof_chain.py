"""
spa_core/strategy_lab/rates_desk/proof_chain.py — the rates-desk DECISION PROOF CHAIN.

The public "what we traded AND what we refused — and why" log. Every gate verdict (an APPROVED entry
AND every REFUSAL) is hashed into the tamper-evident spa_core.audit.hash_chain, and mirrored into a
human-readable data/rates_desk/decision_log.jsonl. Refusals are first-class evidence here: the desk's
whole edge is the tail-comp it REFUSES, so the refusal record is the proof of discipline, not noise.

Each decision carries the verbatim, string-exact proof of the verdict:
  • the GateResult.proof_hash() (deterministic SHA-256 over the FULL verdict incl. the decomposition),
  • the YieldDecomposition.proof() (baseline − the 5 haircuts → fair_yield),
  • the gate fields (approved, reason, net_edge, approved_size_usd, detail).

Two re-runs over the same (scan, gate) verdicts produce byte-identical payloads → identical chain
hashes (the proof-chain anchor). The hash_chain itself guarantees prev-linkage: mutating any historical
decision breaks the chain and is detectable via hash_chain.verify_chain().

THE PUBLIC MIRROR IS ONE COHERENT CHAIN (re-based, single genesis)
-----------------------------------------------------------------
``data/rates_desk/decision_log.jsonl`` is the public artifact an outsider downloads and verifies
WITHOUT our code, following docs/PROOF_CHAIN_SPEC.md §5 (walk in seq order: ``seq == idx``,
``prev_hash == prev.entry_hash``, genesis ``prev_hash = "0"*64``, ``head_hash`` = LAST row's
entry_hash). To make that guarantee true, every append RE-BASES the entire mirror into a single
contiguous chain: ``seq`` is renumbered 0..N, ``prev_hash`` is re-linked, and ``entry_hash`` is
recomputed over each row's own payload per the spec rule. The DECISION BODY (payload: kind, reason,
decomposition, proof_hash, …) is never altered — only the chain-linkage envelope (seq/prev_hash/
entry_hash) is normalized so the file is a single verifiable chain instead of a blind concatenation
of many runs' independent genesis chains. This is the honest fix for the historical corruption where
sandbox/hermetic/test runs each started their own genesis chain yet appended to the same mirror.

SANDBOX INTERLOCK
-----------------
The CANONICAL mirror (``_LOG``) is written ONLY by the real production paper tick. Sandbox / hermetic
/ test runs MUST pass an explicit ``log_path`` (their own temp file); if a run is detected as sandboxed
(``SPA_SANDBOX`` env or pytest) and does NOT pass an explicit ``log_path``, the canonical mirror write
is REFUSED (fail-CLOSED) so transient runs can never pollute the published chain again — same class of
guard as the track-corruption fix.

PURE-of-pricing: this module does NO pricing/policy — it only serializes verdicts the gate already
produced. `ts` is an explicit input (deterministic tests); production defaults to UTC now. stdlib only,
LLM-FORBIDDEN, atomic writes (the hash_chain is atomic; the jsonl mirror is tmp + os.replace).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from spa_core.audit import hash_chain
from spa_core.strategy_lab.rates_desk.contracts import GateResult

_ROOT = Path(__file__).resolve().parents[3]
_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"

EVENT_TYPE = "rates_desk_decision"
LOG_CAP = 2000  # ring-buffer the human-readable mirror (the hash_chain is the authoritative append-only)

# The chain-linkage envelope keys re-derived on every mirror append; everything else is the signed
# decision body (payload) which is NEVER mutated by re-basing.
_ENVELOPE_KEYS = ("seq", "ts", "entry_hash", "prev_hash")


def _is_sandbox() -> bool:
    """True when this process is a sandbox / hermetic / test run that must NOT touch the canonical
    mirror unless an explicit log_path is given. Detected via SPA_SANDBOX env or an active pytest."""
    if os.environ.get("SPA_SANDBOX"):
        return True
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _payload_of(row: dict) -> dict:
    """The signed decision body = the row with the four chain-linkage envelope keys removed."""
    return {k: v for k, v in row.items() if k not in _ENVELOPE_KEYS}


def _rebase_rows(rows: List[dict]) -> List[dict]:
    """Re-base an ordered list of mirror rows into ONE contiguous, single-genesis, prev-linked chain.

    Renumbers seq 0..N, re-links prev_hash, and recomputes entry_hash over each row's OWN payload
    (the decision body is preserved verbatim — only the envelope is normalized). The result verifies
    standalone per docs/PROOF_CHAIN_SPEC.md §5: head_hash = the LAST row's entry_hash. Deterministic."""
    rebased: List[dict] = []
    prev = hash_chain.GENESIS_PREV
    for seq, row in enumerate(rows):
        payload = _payload_of(row)
        ts = row.get("ts")
        entry_hash = hash_chain.compute_entry_hash(seq, ts, EVENT_TYPE, payload, prev)
        rebased.append({"seq": seq, "ts": ts, "entry_hash": entry_hash, "prev_hash": prev, **payload})
        prev = entry_hash
    return rebased


def verify_mirror(rows: List[dict]) -> dict:
    """Verify the PUBLIC mirror as ONE chain, EXACTLY per docs/PROOF_CHAIN_SPEC.md §5.

    Walk in seq order; at each row require (1) seq == idx, (2) prev_hash == previous row's entry_hash
    (genesis prev_hash == '0'*64), (3) recompute_entry_hash(row) == entry_hash. Returns
    {"valid", "length", "broken_at", "head_hash"}; head_hash = the LAST row's entry_hash; empty is
    vacuously valid. fail-CLOSED on any malformed row. This is the single shared verifier — the API,
    the smoke test, and a third party following the spec all reach the IDENTICAL verdict."""
    expected_prev = hash_chain.GENESIS_PREV
    head_hash = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("seq") != idx:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = hash_chain.compute_entry_hash(
                row.get("seq"), row.get("ts"), EVENT_TYPE, _payload_of(row), row.get("prev_hash"))
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED at this row
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


def decision_payload(result: GateResult) -> dict:
    """The verbatim, string-exact, hashable proof body for ONE gate verdict (entry OR refusal).

    Deterministic: only the verdict's own string-exact fields go in (no clock, no run-id), so the same
    verdict always produces the same payload → the same chain hash."""
    return {
        "kind": "ENTRY" if result.approved else "REFUSAL",
        "approved": bool(result.approved),
        "reason": result.reason.value,
        "as_of": result.as_of,
        "underlying": result.underlying,
        "shape": result.shape.value,
        "net_edge": str(result.net_edge),
        "approved_size_usd": str(result.approved_size_usd),
        "decomposition": result.decomposition.proof(),
        "detail": dict(sorted(result.detail.items())),
        "proof_hash": result.proof_hash(),
    }


def _append_jsonl_mirror(entries: List[dict], path: Path) -> None:
    """Append entries to the human-readable decision_log.jsonl AS ONE COHERENT CHAIN, atomically.

    Reads the existing mirror, appends the new decision bodies, ring-buffers to LOG_CAP, then RE-BASES
    the whole file into a single contiguous, single-genesis, prev-linked chain (seq/prev_hash/
    entry_hash recomputed; decision body preserved) so the published file verifies standalone per
    docs/PROOF_CHAIN_SPEC.md §5. Atomic: read-all → rewrite tmp → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[dict] = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    existing.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue  # drop a corrupt historical line — re-basing rebuilds a clean chain
        except OSError:
            existing = []
    combined = existing + list(entries)
    if len(combined) > LOG_CAP:
        combined = combined[-LOG_CAP:]
    rebased = _rebase_rows(combined)
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in rebased]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def record_decisions(
    verdicts: Iterable[GateResult],
    *,
    ts: Optional[str] = None,
    log_path: Optional[Path] = None,
    mirror: bool = True,
) -> List[dict]:
    """Append every verdict (APPROVED entries AND refusals) to the hash_chain + the readable mirror.

    Args:
        verdicts: the GateResults from a scan+gate run (sleeve.scan_and_enter / tick_hold return these).
        ts:       ISO-8601 timestamp for the chain entries (MUST be supplied in tests for determinism;
                  production defaults to UTC now). One ts is used for the whole batch.
        log_path: override the decision_log.jsonl path (tests/hermetic).
        mirror:   also write the human-readable jsonl mirror (default True).

    Returns the list of hash_chain entries appended (each carries seq / prev_hash / entry_hash). The
    hash_chain append is atomic + tamper-evident; verify with hash_chain.verify_chain()."""
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    appended: List[dict] = []
    mirror_rows: List[dict] = []
    for result in verdicts:
        payload = decision_payload(result)
        entry = hash_chain.append(EVENT_TYPE, payload, ts=ts)
        appended.append(entry)
        # Carry only the decision body + ts forward; the chain-linkage envelope (seq/prev_hash/
        # entry_hash) is RE-DERIVED for the single coherent mirror chain by _append_jsonl_mirror.
        mirror_rows.append({"ts": entry["ts"], **payload})
    if mirror and mirror_rows:
        target = log_path or _LOG
        # SANDBOX INTERLOCK (fail-CLOSED): a sandbox/hermetic/test run may write only to an EXPLICIT
        # log_path it owns — never the canonical published mirror. This is what stops transient runs
        # from re-polluting decision_log.jsonl (the historical root cause).
        if log_path is None and _is_sandbox():
            return appended
        _append_jsonl_mirror(mirror_rows, target)
    return appended


def recent_decisions(n: int = 50, log_path: Optional[Path] = None) -> List[dict]:
    """Return the last `n` decisions from the readable mirror (most recent last). Graceful: an absent
    log yields []. Includes refusals — the 'what we refused + why' record."""
    if n <= 0:
        return []
    path = log_path or _LOG
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
    return rows[-n:]


def verify() -> dict:
    """Verify the underlying hash_chain (tamper-evidence over ALL events, incl. these decisions)."""
    return hash_chain.verify_chain()
