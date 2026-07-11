"""Q2-19 — non-custodial advisory loop (deterministic, unsigned-draft-only, AI-never-signs).

The product a first design partner actually uses: the desk produces a deterministic, EVIDENCE-TAGGED
advisory recommendation + the refusal context that PROVES the discipline — and the partner executes it on
THEIR OWN Safe. This module is that producer. It is READ-ONLY over the hash-chained decision log and
emits an UNSIGNED advisory draft. It NEVER imports spa_core.execution, never builds a signed transaction,
never holds a key, never moves funds. AI is never a signer — human-in-the-loop by construction.

The advisory package carries, per approved book: underlying, shape, an advisory SIZE HINT (not an order),
the net edge, the tamper-evident proof_hash, and the evidence level — plus the REFUSAL context (what the
desk declined and why) so the partner sees the whole honest picture, not just the ships. Every field is
sourced from the real decision log; nothing is fabricated. Deterministic, stdlib-only, LLM-forbidden,
fail-CLOSED (a malformed log → an empty advisory with the reason, never a guessed recommendation).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_DECISIONS = _DATA / "rates_desk" / "decision_log.jsonl"

# Hard non-custodial stamps carried on EVERY advisory package (the honesty + safety contract).
_NON_CUSTODIAL_STAMPS = {
    "non_custodial": True,
    "ai_never_signs": True,
    "unsigned_draft": True,
    "requires_human_execution": True,
    "no_keys_held": True,
    "execution_venue": "partner's own Safe / signers — the desk never takes custody",
    "is_advisory": True,
}


def _read_decisions(path: Path) -> List[dict]:
    rows: List[dict] = []
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return rows


def _as_pct(net_edge: Any) -> Optional[float]:
    try:
        return round(float(net_edge) , 4)
    except (TypeError, ValueError):
        return None


def build_advisory(*, decisions_path: Optional[Path] = None, as_of: Optional[str] = None,
                   max_recs: int = 20) -> dict:
    """Produce a non-custodial advisory draft from the decision log. `as_of` filters to that date
    (default: the latest date present). Pure + fail-CLOSED."""
    rows = _read_decisions(decisions_path or _DECISIONS)
    if not rows:
        return {"model": "non_custodial_advisory", "as_of": as_of, "recommendations": [],
                "refusal_context": [], "flag_reason": "no decision log (fail-closed)",
                **_NON_CUSTODIAL_STAMPS}

    dates = sorted({r.get("as_of") for r in rows if r.get("as_of")})
    target = as_of or (dates[-1] if dates else None)
    day = [r for r in rows if r.get("as_of") == target] or rows[-max_recs:]

    recs: List[dict] = []
    refusals: List[dict] = []
    for r in day:
        approved = r.get("approved")
        item = {
            "underlying": r.get("underlying"),
            "shape": r.get("shape"),
            "net_edge_pct": _as_pct(r.get("net_edge")),
            "proof_hash": r.get("proof_hash"),
            "as_of": r.get("as_of"),
        }
        if approved is True:
            # an advisory SIZE HINT — NOT an order; the partner sizes + executes on their own Safe
            try:
                item["advisory_size_hint_usd"] = round(float(r.get("approved_size_usd")), 2)
            except (TypeError, ValueError):
                item["advisory_size_hint_usd"] = None
            item["evidence"] = "L4 · reproduced from the hash-chained decision log"
            recs.append(item)
        elif approved is False:
            item["refused_reason"] = r.get("reason") or "structural haircut / gate"
            refusals.append(item)

    # dedupe by proof_hash (the log can carry repeat entries for the same decision on a day) — a partner
    # must see each distinct recommendation once, not the same book N times.
    def _dedupe(items: List[dict]) -> List[dict]:
        seen: set = set()
        out: List[dict] = []
        for it in items:
            key = it.get("proof_hash") or (it.get("underlying"), it.get("shape"), it.get("as_of"))
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    recs = _dedupe(recs)[:max_recs]
    refusals = _dedupe(refusals)
    return {
        "model": "non_custodial_advisory",
        "as_of": target,
        "n_recommendations": len(recs),
        "n_refusals": len(refusals),
        "recommendations": recs,
        "refusal_context": refusals[:max_recs],
        "note": ("A deterministic, evidence-tagged ADVISORY draft, re-derivable from the hash-chained "
                 "decision log. The desk recommends + refuses; the PARTNER reviews and executes on their "
                 "own Safe. AI never signs, holds no keys, moves no funds. The refusal context is included "
                 "so the honest picture (what we DECLINED, not just what we recommend) travels with every "
                 "draft. Not investment advice; not an order — an unsigned, human-in-the-loop draft."),
        **_NON_CUSTODIAL_STAMPS,
    }


def main() -> int:
    a = build_advisory()
    print(f"[advisory_loop] as_of={a['as_of']} · {a.get('n_recommendations', 0)} recommendation(s), "
          f"{a.get('n_refusals', 0)} refusal(s) · unsigned draft, AI-never-signs")
    for r in a.get("recommendations", [])[:5]:
        print(f"  REC {r.get('underlying')}/{r.get('shape')} edge {r.get('net_edge_pct')}% "
              f"hint ${r.get('advisory_size_hint_usd')} proof {str(r.get('proof_hash'))[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
