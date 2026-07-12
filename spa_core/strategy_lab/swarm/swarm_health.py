"""Swarm block 5 — L4 immune layer: the agent that watches the swarm itself.

Charter: docs/SWARM_ARCHITECTURE.md. A monitoring swarm that silently dies is WORSE than no
swarm — consumers keep reading yesterday's "all calm" while the market moves. This module checks,
deterministically, that every swarm organ is alive and fresh, and that the fail-closed contracts
are actually honored in the artifacts (not just promised in docstrings):

  freshness   each swarm status JSON exists, parses, and is younger than its freshness budget
              (hourly agents → stale after FRESH_HOURS).
  contracts   guardian: books present; blend: state ∈ known set; regime: regime ∈ known set and
              consumer_contract mentions fail-closed; brain: every levered book with flagged/
              missing depth is REFUSED (null reco) — the refusal-first invariant, re-verified
              from the artifact itself each run.
  proofs      each proof chain file exists and its LAST line's hash verifies against its content
              (cheap tamper check; the full chain is verified by scripts/verify_spa.py).

Output: data/swarm/swarm_health.json with overall OK / WARNING and per-organ detail. WARNING is
edge-triggered honest — a missing organ is reported as "never ran", never invented as healthy.
This module only READS swarm artifacts and writes ONLY its own status. Deterministic, stdlib-only.
LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from spa_core.utils.atomic import atomic_save

__all__ = ["run_swarm_health", "ORGANS"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "swarm_health.json"
FRESH_HOURS = 3.0  # hourly agents; 3h budget tolerates one missed tick + drift

ORGANS = {
    "guardian_forward": {"status": "guardian_forward.json", "proof": "guardian_forward_proof.jsonl"},
    "blend_forward": {"status": "blend_forward.json", "proof": "blend_forward_proof.jsonl"},
    "funding_regime": {"status": "funding_regime.json", "proof": "funding_regime_proof.jsonl"},
    "leverage_brain": {"status": "leverage_brain.json", "proof": "leverage_brain_proof.jsonl"},
    "swarm_book": {"status": "swarm_book.json", "proof": "swarm_book_proof.jsonl"},
}

_KNOWN_BLEND_STATES = {"TRACKING", "WARMUP", "DEGRADED", "STALE_LEG"}
_KNOWN_REGIMES = {"GREEN", "YELLOW", "RED", "UNKNOWN"}


def _load(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text())
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _age_hours(doc: dict, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(str(doc.get("as_of_utc")))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def _last_proof_line_ok(path: Path) -> tuple[bool, str]:
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return False, "proof file missing"
    if not lines:
        return False, "proof file empty"
    try:
        rec = json.loads(lines[-1])
    except ValueError:
        return False, "last proof line unparseable"
    expect = rec.pop("hash", None)
    got = hashlib.sha256((rec.get("prev_hash", "") + json.dumps(rec, sort_keys=True)).encode()
                         ).hexdigest()
    return (got == expect), ("last proof hash verifies" if got == expect
                             else "last proof hash MISMATCH — possible tamper/corruption")


def _contract_check(organ: str, doc: dict) -> tuple[bool, str]:
    """Re-verify each organ's fail-closed contract FROM its artifact (not from trust)."""
    if organ == "guardian_forward":
        books = doc.get("books")
        if not isinstance(books, dict) or not books:
            return False, "no books in guardian output"
        bad = [n for n, b in books.items()
               if b.get("state") not in ("ARMED", "DERISKED", "WARMUP", "NO_FORWARD")]
        return (not bad), (f"unknown guardian states: {bad}" if bad else
                           f"{len(books)} books, states valid")
    if organ == "blend_forward":
        st = doc.get("state")
        return (st in _KNOWN_BLEND_STATES), f"state={st}"
    if organ == "funding_regime":
        if doc.get("regime") not in _KNOWN_REGIMES:
            return False, f"unknown regime {doc.get('regime')!r}"
        if "not-GREEN" not in str(doc.get("consumer_contract", "")):
            return False, "consumer_contract missing the fail-closed clause"
        return True, f"regime={doc['regime']}"
    if organ == "leverage_brain":
        # THE invariant: a levered-shape book may have a numeric reco ONLY in state RECOMMENDED/
        # ZERO_EXPOSURE with a non-null depth factor; refusals must be null.
        for name, b in (doc.get("books") or {}).items():
            reco, df = b.get("leverage_reco"), (b.get("factors") or {}).get("depth_factor")
            if b.get("levered_shape") and df is None and reco is not None:
                return False, f"{name}: levered book has reco {reco} WITHOUT depth — invariant broken"
            if str(b.get("state", "")).startswith("REFUSED") and reco is not None:
                return False, f"{name}: state REFUSED but reco={reco} — must be null"
        return True, f"{len(doc.get('books') or {})} books, refusal invariant holds"
    if organ == "swarm_book":
        if not isinstance(doc.get("equity"), (int, float)) or doc["equity"] <= 0:
            return False, f"equity invalid: {doc.get('equity')!r}"
        weights = doc.get("weights")
        if not isinstance(weights, dict):
            return False, "weights missing"
        total = sum(v for v in weights.values() if isinstance(v, (int, float)))
        if total > 1.0 + 1e-6:
            return False, f"weights sum {total:.4f} > 1 — the book can never be levered"
        return True, f"equity ${doc['equity']:,.0f}, {len(weights)} books, Σw={total:.3f}"
    return False, "unknown organ"


def run_swarm_health(now: Optional[datetime] = None,
                     swarm_dir: Path = SWARM_DIR,
                     out_dir: Optional[Path] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out_dir = out_dir or swarm_dir
    organs: Dict[str, dict] = {}
    for organ, files in ORGANS.items():
        doc = _load(swarm_dir / files["status"])
        if doc is None:
            organs[organ] = {"ok": False, "detail": "status missing/unreadable — never ran?"}
            continue
        age = _age_hours(doc, now)
        fresh = age is not None and age <= FRESH_HOURS
        c_ok, c_detail = _contract_check(organ, doc)
        p_ok, p_detail = _last_proof_line_ok(swarm_dir / files["proof"])
        organs[organ] = {
            "ok": bool(fresh and c_ok and p_ok),
            "age_hours": age if age is None else round(age, 2),
            "fresh": fresh,
            "contract": {"ok": c_ok, "detail": c_detail},
            "proof": {"ok": p_ok, "detail": p_detail},
        }

    overall_ok = all(o["ok"] for o in organs.values())
    doc = {
        "domain": "swarm.swarm_health",
        "label": "SWARM L4 immune layer / monitors the monitors",
        "is_advisory": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "overall": "OK" if overall_ok else "WARNING",
        "fresh_hours_budget": FRESH_HOURS,
        "organs": organs,
        "note": ("WARNING means an organ is missing, stale, contract-violating or proof-broken — "
                 "consumers of swarm signals should treat the swarm as fail-closed (not-GREEN) "
                 "until this returns OK."),
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    doc = run_swarm_health()
    print(f"swarm.swarm_health: {doc['overall']}")
    for organ, o in doc["organs"].items():
        mark = "✅" if o["ok"] else "⚠️ "
        extra = o.get("contract", {}).get("detail", o.get("detail", ""))
        print(f"  {mark} {organ:18s} age={o.get('age_hours')}h {extra}")
    return 0 if doc["overall"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
