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

PURE-of-pricing: this module does NO pricing/policy — it only serializes verdicts the gate already
produced. `ts` is an explicit input (deterministic tests); production defaults to UTC now. stdlib only,
LLM-FORBIDDEN, atomic writes (the hash_chain is atomic; the jsonl mirror is tmp + os.replace).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Iterable, List, Optional

from spa_core.audit import hash_chain
from spa_core.strategy_lab.rates_desk.contracts import GateResult

_ROOT = Path(__file__).resolve().parents[3]
_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"

EVENT_TYPE = "rates_desk_decision"
LOG_CAP = 2000  # ring-buffer the human-readable mirror (the hash_chain is the authoritative append-only)


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
    """Append the chain entries to the human-readable decision_log.jsonl (ring-buffered to LOG_CAP),
    atomically (read-all → rewrite tmp → os.replace). The hash_chain is the authoritative log; this is
    the readable mirror for the dashboard / operator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if path.exists():
        try:
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            lines = []
    for e in entries:
        lines.append(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if len(lines) > LOG_CAP:
        lines = lines[-LOG_CAP:]
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
        mirror_rows.append({
            "seq": entry["seq"],
            "ts": entry["ts"],
            "entry_hash": entry["entry_hash"],
            "prev_hash": entry["prev_hash"],
            **payload,
        })
    if mirror and mirror_rows:
        _append_jsonl_mirror(mirror_rows, log_path or _LOG)
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
