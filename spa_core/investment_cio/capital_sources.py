"""Capital Sources — one view over every return source of the capital portfolio (ADR-640, CAPITAL-SOURCES-01).

NOT a second registry and NOT a store: a pure projection of what already exists —
  * the ADR-554 Oracle sleeves (DeFi books, cash, market-neutral/basis research), and
  * the Trading Alpha sleeve derived from the canonical Trading Lab (`trading_research.alpha_sleeve`),
onto the one field set :data:`contract.CAPITAL_SOURCE_FIELDS`. It writes nothing and decides nothing: weights
and eligibility for allocation stay with the Oracle policy (ADR-554), which never executes.

Rules carried over unchanged:
  * absence is its own value (invariant #17) — a cell the source does not publish is NOT_MEASURED with a reason,
    never 0; a placeholder source (no evidence) keeps every number NOT_MEASURED;
  * a return is typed: `annualized_return` of a DeFi book is its REALIZED_PAPER annualised rate (ADR-593); the
    Trading Alpha sleeve publishes FORWARD_PAPER cumulative returns and no annualised figure below 30 days;
  * percentages are normalised to fractions, the original unit is kept in the cell.

# LLM_FORBIDDEN — deterministic projection.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import contract

_NM = contract.NOT_MEASURED


def _nm(reason: str) -> Dict:
    return contract.absent(_NM, reason=reason)


def _is_cell(c: Any) -> bool:
    return isinstance(c, dict) and c.get("state") in contract.CELL_STATES


def _frac(cell: Any, *, label: str) -> Dict:
    """A cell whose unit is a percentage → the same cell in fractions (unit kept, value / 100)."""
    if not _is_cell(cell):
        return _nm(f"{label} not published by the source")
    if cell.get("state") != contract.MEASURED:
        return dict(cell)
    unit = str(cell.get("unit") or "")
    v = cell.get("value")
    if unit.startswith("pct") and isinstance(v, (int, float)) and not isinstance(v, bool):
        out = dict(cell)
        out["value"] = round(v / 100.0, 10)
        out["unit"] = unit.replace("pct", "fraction", 1) + f" (from {unit})"
        return out
    return dict(cell)


def _plain_cell(value: Any, *, unit: Optional[str], source: str, as_of: Optional[str]) -> Dict:
    return contract.measured(value, unit=unit, source=source, as_of=as_of)


def from_sleeve(sleeve: Dict, *, snapshot_digest: Optional[str] = None) -> Dict:
    """An ADR-554 sleeve projected onto the Capital Sources view."""
    sid = sleeve.get("sleeve_id")
    identity = contract.SLEEVES.get(sid, {})
    rr = sleeve.get("realized_return")
    fresh = sleeve.get("data_freshness")
    as_of = (rr or {}).get("as_of") if _is_cell(rr) and rr.get("state") == contract.MEASURED else \
        ((fresh or {}).get("as_of") if _is_cell(fresh) else None)
    vp = sleeve.get("valid_periods")
    eq, basis = contract.value_of(sleeve.get("current_equity")), contract.value_of(sleeve.get("capital_basis"))
    if isinstance(eq, (int, float)) and isinstance(basis, (int, float)) and not isinstance(basis, bool) and basis > 0:
        net = contract.measured(round(eq / basis - 1.0, 10), unit="fraction, cumulative since experiment start",
                                source="current_equity / capital_basis (ADR-554 sleeve)", as_of=as_of)
    else:
        net = _nm("cumulative return needs both current_equity and capital_basis measured")
    gates = sleeve.get("gates") if isinstance(sleeve.get("gates"), list) else []
    blockers = [f"gate {g.get('gate')}: {g.get('state')} ({g.get('reason')})" for g in gates
                if isinstance(g, dict) and g.get("state") != "PASS"]
    if not sleeve.get("allocatable"):
        blockers.insert(0, "not allocatable in the ADR-554 contract (research only)")
    stage = sleeve.get("maturity")
    mval = contract.value_of(stage)
    if sid != "cash" and mval not in (contract.MATURITY_DEVELOPING, contract.MATURITY_MATURE):
        # an immature (or unmeasured-maturity) source never gets an allocation (CAPITAL-SOURCES-01 §15)
        blockers.append(f"maturity {mval or 'NOT_MEASURED'}: fewer than "
                        f"{contract.POLICY['maturity_developing_min']} valid periods")
    return {
        "source_id": sid, "source_type": identity.get("source_type"), "name": sleeve.get("name"),
        "status": "ALLOCATABLE_PAPER" if sleeve.get("allocatable") else "RESEARCH_ONLY",
        "capital_mode": "PAPER", "oracle_sleeve": sid,
        "lifecycle_stage": dict(stage) if _is_cell(stage) else _nm("maturity not published"),
        "measurement_as_of": (_plain_cell(as_of, unit="iso8601", source="sleeve cells", as_of=as_of) if as_of else
                              _nm("no measured return or freshness cell carries a time")),
        "evidence_start": (_plain_cell(sleeve.get("experiment_start"), unit="date", source="experiment_start",
                                       as_of=as_of) if sleeve.get("experiment_start") else
                           _nm("experiment_start not published")),
        "evidence_days": dict(vp) if _is_cell(vp) else _nm("valid_periods not published"),
        "observations": (_plain_cell(vp.get("n"), unit="observations", source=vp.get("source"), as_of=vp.get("as_of"))
                         if _is_cell(vp) and vp.get("state") == contract.MEASURED and vp.get("n") is not None
                         else _nm("observation count not published")),
        "gross_return": _nm("the source publishes returns net of its modelled costs only"),
        "net_return": net,
        "annualized_return": _frac(rr, label="realized_return"),
        "drawdown": _frac(sleeve.get("max_drawdown"), label="max_drawdown"),
        "volatility": _frac(sleeve.get("volatility"), label="volatility"),
        "sharpe": _nm("not published by the ADR-554 sleeve"),
        "sortino": _nm("not published by the ADR-554 sleeve"),
        "turnover": _nm("not published at sleeve level"),
        "estimated_costs": _nm("modelled costs are inside the book's net figures, not published separately"),
        "realized_costs": _nm("paper only: no fill has ever been executed"),
        "exposure": (dict(sleeve["gross_exposure_over_nav"]) if _is_cell(sleeve.get("gross_exposure_over_nav"))
                     else _nm("gross exposure not published")),
        "liquidity": dict(sleeve["liquidity"]) if _is_cell(sleeve.get("liquidity")) else _nm("liquidity not published"),
        "capacity": dict(sleeve["capacity"]) if _is_cell(sleeve.get("capacity")) else _nm("capacity not published"),
        "confidence": (dict(sleeve["confidence"]) if _is_cell(sleeve.get("confidence"))
                       else _nm("confidence not published")),
        "data_quality": (dict(sleeve["evidence_state"]) if _is_cell(sleeve.get("evidence_state"))
                         else _nm("evidence state not published")),
        "freshness": dict(fresh) if _is_cell(fresh) else _nm("data freshness not published"),
        "correlation_state": sleeve.get("correlation_features") or {"note": "no correlation features published"},
        "eligibility": {"state": "ELIGIBLE" if not blockers else "NOT_ELIGIBLE",
                        "basis": "ADR-554 gates + maturity (≥30 valid periods); WEIGHTS are decided only by the "
                                 "Oracle policy, which never executes"},
        "blockers": blockers,
        "provenance": {"from": "investment_cio sleeves (ADR-554)", "sleeve_id": sid,
                       "snapshot_digest": snapshot_digest},
    }


def from_trading_alpha(doc: Dict) -> Dict:
    """The Trading Alpha sleeve (trading_research.alpha_sleeve) on the Capital Sources view."""
    as_of = doc.get("as_of")
    src = "trading_research/alpha_sleeve (evidence.db, ADR-640)"

    def cell(k: str, unit_hint: Optional[str] = None) -> Dict:
        c = doc.get(k)
        if not isinstance(c, dict) or "state" not in c:
            return _nm(f"{k} not produced by the sleeve")
        if c["state"] == "MEASURED":
            return contract.measured(c.get("value"), unit=c.get("unit") or unit_hint, source=src, as_of=as_of,
                                     n=c.get("n"), note=f"{c.get('evidence_class') or 'FORWARD_PAPER'}"
                                                        + (f"; {c['note']}" if c.get("note") else ""))
        state = c["state"] if c["state"] in contract.CELL_STATES else _NM
        return contract.absent(state, reason=c.get("reason") or "not measured", source=src, as_of=as_of, n=c.get("n"))

    evid = doc.get("evidence") or {}
    stages = (doc.get("research") or {}).get("stages") or {}
    members = doc.get("members") or []
    member_stages = sorted({m.get("stage") for m in members if m.get("stage")})
    blockers = list((doc.get("eligibility") or {}).get("blockers") or [])
    if not contract.SLEEVES.get("trading_research", {}).get("allocatable"):
        # review P2-9: same rule as from_sleeve — the ADR-554 contract still classes this sleeve research-only
        blockers.insert(0, "not allocatable in the ADR-554 contract (research only)")
    return {
        "source_id": doc.get("source_id", "trading_alpha"), "source_type": contract.SOURCE_TRADING_ALPHA,
        "name": "Trading Alpha (paper sleeve over the Trading Lab)",
        "status": "RESEARCH_ONLY", "capital_mode": "PAPER", "oracle_sleeve": "trading_research",
        "lifecycle_stage": (contract.measured("+".join(member_stages), unit=None, source=src, as_of=as_of,
                                              n=len(members), note=f"research stages: {stages}")
                            if member_stages else _nm("no admitted member")),
        "measurement_as_of": contract.measured(as_of, unit="iso8601", source=src, as_of=as_of),
        "evidence_start": (contract.measured(evid.get("inception"), unit="iso8601", source=src, as_of=as_of)
                           if evid.get("inception") else _nm("no sleeve inception")),
        "evidence_days": (contract.measured(evid.get("calendar_days"), unit="calendar days", source=src, as_of=as_of)
                          if evid.get("calendar_days") is not None else _nm("no sleeve inception")),
        "observations": (contract.measured(evid.get("observations_in_sleeve"), unit="observations (bars, not days)",
                                           source=src, as_of=as_of)
                         if evid.get("observations_in_sleeve") is not None else _nm("no sleeve observations")),
        "gross_return": cell("gross_return"), "net_return": cell("net_return"),
        "annualized_return": cell("annualized_return"), "drawdown": cell("max_drawdown"),
        "volatility": cell("volatility"), "sharpe": cell("sharpe"), "sortino": cell("sortino"),
        "turnover": cell("turnover"), "estimated_costs": cell("estimated_costs"),
        "realized_costs": cell("realized_costs"), "exposure": cell("exposure"),
        # review P1-2: a constant is never stamped MEASURED. What we only BELIEVE is declared below in
        # `declared_assumptions` and never feeds eligibility as a measurement.
        "liquidity": _nm("not measured by the sleeve (no order-book / volume measurement); see declared_assumptions"),
        "capacity": _nm("no capacity model (cost component UNKNOWN)"),
        "confidence": _nm("no measured confidence for this source; see declared_assumptions"),
        "data_quality": contract.measured({"anomalies": len(doc.get("anomalies") or []),
                                           "evidence_digest": (doc.get("provenance") or {}).get("evidence_digest")},
                                          unit=None, source=src, as_of=as_of),
        "freshness": cell("freshness"),
        "correlation_state": doc.get("correlation_state") or {"note": "not produced"},
        "eligibility": {"state": (doc.get("eligibility") or {}).get("state", "NOT_ELIGIBLE"),
                        "basis": "CAPITAL-SOURCES-01 §7: unknown costs / immaturity / staleness ⇒ not eligible"},
        "blockers": blockers,
        "provenance": dict(doc.get("provenance") or {}),
        "declared_assumptions": {
            "kind": "ASSUMPTION — not a measurement, never an eligibility input",
            "liquidity": "members trade BTC spot/perp only; BTC is assumed highly liquid at paper size",
            "confidence": "LOW by rule while forward evidence is under 30 days and costs are partly unmodelled",
        },
    }


def registry(sleeves: Dict, *, trading_alpha: Optional[Dict] = None, trading_alpha_refusal: Optional[str] = None,
             snapshot_digest: Optional[str] = None, generated_at: Optional[str] = None) -> Dict:
    """All capital sources, one contract. `sleeves` = the ADR-554 sleeve dict (sleeve_id → sleeve).
    The Trading Alpha source replaces the Oracle `trading_research` sleeve's view when the sleeve was built;
    if it was refused, the Oracle sleeve's own (NOT_MEASURED) view stays, with the refusal as a blocker."""
    sources: List[Dict] = []
    for sid in contract.SLEEVES:
        sl = sleeves.get(sid) if isinstance(sleeves, dict) else None
        if sid == "trading_research" and trading_alpha is not None:
            sources.append(from_trading_alpha(trading_alpha))
            continue
        if not isinstance(sl, dict):
            view = {k: _nm(f"sleeve {sid} not present in the Oracle snapshot") for k in contract.CAPITAL_SOURCE_FIELDS}
            view.update({"source_id": sid, "source_type": contract.SLEEVES[sid].get("source_type"),
                         "name": contract.SLEEVES[sid]["name"], "status": "NOT_MEASURED", "capital_mode": "PAPER",
                         "oracle_sleeve": sid, "correlation_state": {}, "eligibility": {"state": "NOT_ELIGIBLE"},
                         "blockers": ["sleeve absent"], "provenance": {"snapshot_digest": snapshot_digest}})
            sources.append(view)
            continue
        view = from_sleeve(sl, snapshot_digest=snapshot_digest)
        if sid == "trading_research" and trading_alpha_refusal:
            view["blockers"] = [f"Trading Alpha sleeve refused: {trading_alpha_refusal}"] + view["blockers"]
        sources.append(view)
    order = {t: i for i, t in enumerate(contract.SOURCE_TYPES)}
    sources.sort(key=lambda s: (order.get(s.get("source_type"), 99), s.get("source_id") or ""))
    by_type = {t: [s["source_id"] for s in sources if s.get("source_type") == t] for t in contract.SOURCE_TYPES}
    for s in sources:
        missing = [f for f in contract.CAPITAL_SOURCE_FIELDS if f not in s]
        if missing:
            raise ValueError(f"source {s.get('source_id')} misses contract fields {missing}")
    return {"schema": contract.SCHEMA_CAPITAL_SOURCES, "generated_at": generated_at, "capital_mode": "PAPER",
            "real_capital_usd": 0, "executes": False, "source_types": by_type, "sources": sources}
