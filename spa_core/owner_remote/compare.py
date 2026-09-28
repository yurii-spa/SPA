"""Factual side-by-side of two InvestmentSlices — NOT a score/ranking/recommendation engine.

Reads the same shared projection for each object and lays the facts next to each other so the Owner can
see WHY one object is closer to fundable than another. No ranking, no advice, no invented numbers.
"""
from __future__ import annotations

from spa_core.owner_remote.slice import build_investment_slice


def _v(f):
    return None if not isinstance(f, dict) else f.get("value")


def _row_from(slice_):
    o, r, res = slice_["opportunity"], slice_["risk"], slice_["result"]
    gates = {g["rule"]: g["pass"] for g in (r["gates"]["value"] or [])}
    passed = sum(1 for p in gates.values() if p)
    # count MISSING/PARTIAL fields across the passport-bearing stages
    missing = 0
    for stage in ("opportunity", "position", "strategy"):
        for f in slice_[stage].values():
            if isinstance(f, dict) and f.get("status") in ("MISSING", "PARTIAL"):
                missing += 1
    held = res["held"]["value"]
    return {
        "protocol": slice_["entity"]["label"],
        "id": slice_["entity"]["id"],
        "evidence": _v(o["apy_evidence"]),
        "apy_pct": _v(o["apy_pct"]),
        "position_apy": _v(slice_["position"].get("position_apy")) if held else None,
        "tvl_usd": _v(o["tvl_usd"]),
        "tvl_source": _v(o["tvl_source"]),
        "strategy_binding": slice_["strategy"]["active_binding"]["status"],
        "candidate_strategies": len(_v(slice_["strategy"]["candidate_strategies"]) or []),
        "held": held,
        "paper_capital_usd": _v(slice_["capital"]["allocated_to_this"]),
        "risk_gates_passed": f"{passed}/{len(gates)}",
        "risk_gate_detail": gates,
        "freshness": _v(o["freshness"]),
        "result": _v(res["label"]),
        "new_allocation_fundable": _v(r["fundable"]),
        "missing_or_partial_fields": missing,
    }


def compare_slices(protocol_a: str, protocol_b: str) -> dict:
    a = build_investment_slice(protocol_a)
    b = build_investment_slice(protocol_b)
    return {
        "schema": "earn-defi/slice-comparison/1",
        "kind": "FACTUAL_SIDE_BY_SIDE (not a ranking/recommendation)",
        "rows": ["evidence", "apy_pct", "position_apy", "tvl_usd", "tvl_source",
                 "strategy_binding", "candidate_strategies", "held", "paper_capital_usd",
                 "risk_gates_passed", "freshness", "result", "missing_or_partial_fields"],
        "a": _row_from(a),
        "b": _row_from(b),
        "note": "Same shared projections. No score, no advice — facts side by side so the Owner sees WHY "
                "one object is closer to fundable than another.",
    }
