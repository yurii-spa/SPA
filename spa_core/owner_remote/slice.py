"""InvestmentSlice — a READ-ONLY derived projection that threads ONE object through the product chain:
OPPORTUNITY → STRATEGY → POSITION → CAPITAL → RISK → RESULT → WHY.

Not persisted canonical state. It only *references* existing canonical sources and marks every field with
one of: AVAILABLE · DERIVABLE · PARTIAL · MISSING · NOT_APPLICABLE. Blanks are NEVER filled from general
DeFi knowledge. Shared by the Desktop detail panel AND the Telegram gateway (one truth, one projection).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

AVAILABLE, DERIVABLE, PARTIAL, MISSING, NA = "AVAILABLE", "DERIVABLE", "PARTIAL", "MISSING", "NOT_APPLICABLE"


def _load(rel):
    p = REPO / rel
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _f(status, value=None, provenance=None, note=None):
    return {"status": status, "value": value, "provenance": provenance, "note": note}


def _freshness(ts):
    if not ts:
        return "UNKNOWN"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return "LIVE" if age < 900 else "RECENT" if age < 6 * 3600 else "STALE"
    except ValueError:
        return "UNKNOWN"


def build_investment_slice(protocol: str = "aave_v3") -> dict:
    adapters = (_load("data/adapter_status.json") or {}).get("adapters", {})
    a = adapters.get(protocol) or {}
    positions = _load("data/current_positions.json") or {}
    strat = _load("data/strategy_summary.json") or {}
    why = _load("studio_shell/why_aave.json")

    prov_adapter = f"data/adapter_status.json#adapters.{protocol}"

    # ── OPPORTUNITY ──────────────────────────────────────────────────────────────────────
    live_apy = a.get("live_apy")
    apy_evidenced = bool(a.get("live_apy_fresh")) and live_apy is not None
    apy_val = live_apy if apy_evidenced else a.get("apy")
    tvl = a.get("tvl_usd")
    tvl_source = a.get("tvl_source")
    tvl_evidenced = tvl_source == "live"
    opportunity = {
        "protocol": _f(AVAILABLE, a.get("display_name") or protocol, prov_adapter),
        "chain": _f(AVAILABLE if a.get("chain") else DERIVABLE, a.get("chain") or "ethereum", prov_adapter,
                    None if a.get("chain") else "derived: aave_v3 base deployment"),
        "asset": _f(DERIVABLE, "USDC", prov_adapter, "derived: stablecoin supply market"),
        "apy_pct": _f(AVAILABLE if apy_val is not None else MISSING, apy_val, prov_adapter),
        "apy_evidence": _f(AVAILABLE, "LIVE" if apy_evidenced else "UNEVIDENCED (static/fallback)", prov_adapter),
        "tvl_usd": _f(AVAILABLE if tvl is not None else MISSING, tvl, prov_adapter),
        "tvl_source": _f(AVAILABLE, tvl_source or "unknown", prov_adapter),
        "liquidity_capacity": _f(MISSING, None, None, "no capacity/liquidity field in adapter snapshot"),
        "freshness": _f(AVAILABLE, _freshness(a.get("live_apy_as_of")), prov_adapter),
    }

    # ── STRATEGY ─────────────────────────────────────────────────────────────────────────
    cands = [s for s in (strat.get("strategies") or [])
             if "aave" in (str(s.get("name", "")) + str(s.get("id", "")) + str(s.get("tags", ""))).lower()]
    strategy = {
        "candidate_strategies": _f(
            AVAILABLE if cands else MISSING,
            [{"id": s.get("id"), "name": s.get("name"), "tier": s.get("risk_tier"), "status": s.get("status")}
             for s in cands] or None,
            "data/strategy_summary.json#strategies",
            None if cands else "no strategy references this protocol"),
        "active_binding": _f(
            MISSING, None, None,
            "no canonical opportunity→strategy→position binding exists (no allocation). "
            "Required later: a position record naming the chosen strategy_id."),
    }

    # ── POSITION (passport read model) ───────────────────────────────────────────────────
    pd = (positions.get("positions_detail") or {})
    held = next((v for k, v in pd.items() if protocol.split("_")[0] in k.lower()), None)
    mode = (positions.get("execution_mode") or "read_only_simulation")
    track = "PAPER" if mode != "live" else "REAL"
    prov_pos = "data/current_positions.json#positions_detail"
    # When held, the position carries its OWN recorded APY + source, which may DIFFER from the current
    # adapter snapshot (a real, honest discrepancy — surface both, never reconcile silently).
    pos_apy = (held or {}).get("apy_pct")
    pos_src = (held or {}).get("apy_source")
    pos_apy_evidenced = pos_src == "live"
    passport = {
        "position_id": _f(MISSING if not held else AVAILABLE, None if not held else protocol),
        "strategy_id": _f(MISSING, None, None, "no active binding (see strategy.active_binding)"),
        "purpose": _f(DERIVABLE, "stablecoin yield (supply)", prov_adapter),
        "capital_amount": _f(MISSING if not held else AVAILABLE, (held or {}).get("usd"),
                             None if not held else prov_pos),
        "track": _f(AVAILABLE, track, "data/current_positions.json#execution_mode"),
        "asset": _f(DERIVABLE, "USDC"),
        "chain": opportunity["chain"],
        "protocol": _f(AVAILABLE, a.get("display_name") or protocol, prov_adapter),
        "mechanism": _f(DERIVABLE, "over-collateralised lending (supply)", prov_adapter),
        "yield_source": _f(DERIVABLE, "variable supply APY", prov_adapter),
        "position_apy": _f(AVAILABLE if held and pos_apy is not None else NA if not held else MISSING,
                           pos_apy, prov_pos if held else None,
                           "APY recorded ON the position (may differ from the live adapter snapshot)"),
        "position_apy_source": _f(AVAILABLE if held else NA, pos_src, prov_pos if held else None,
                                  "live = evidenced at/for this position; fallback_stale = not fresh"),
        "gross_apy": (_f(AVAILABLE, pos_apy, prov_pos,
                         ("position-recorded" + ("" if pos_apy_evidenced else " — source not live")))
                      if held and pos_apy is not None else opportunity["apy_pct"]),
        "costs": _f(MISSING, None, None, "no cost model for an unheld position"),
        "net_apy": _f(MISSING, None, None, "requires costs + a held position"),
        "risk_tier": _f(AVAILABLE if cands else MISSING,
                        (cands[0].get("risk_tier") if cands else None),
                        "data/strategy_summary.json" if cands else None,
                        "tier of the nearest candidate strategy; not a position tier"),
        "protocol_score": _f(MISSING, None, None, "no protocol-score field in canonical snapshot"),
        "tvl": opportunity["tvl_usd"],
        "incident_history": _f(MISSING, None, None, "no incident-history canonical source wired"),
        "audit_evidence": _f(MISSING, None, None, "no audit-evidence field in snapshot"),
        "oracle_risk": _f(MISSING, None, None, "no oracle-risk field in snapshot"),
        "timelock_status": _f(NA, None, None, "GSM timelock gate applies to Sky/sUSDS, not Aave supply"),
        "entry_route": _f(NA if not held else DERIVABLE, None, None, "no position to enter/held"),
        "entry_cost": _f(MISSING, None),
        "ongoing_cost": _f(MISSING, None),
        "exit_route": _f(NA if not held else DERIVABLE, None),
        "exit_cost": _f(MISSING, None),
        "exit_liquidity": _f(PARTIAL, None, prov_adapter, "TVL known ($ large) but no capacity/util field"),
        "exit_conditions": _f(MISSING, None),
        "stress_scenarios": _f(MISSING, None, None, "no stress-scenario canonical source wired"),
        "monitoring_policy": _f(DERIVABLE, "daily cycle re-evaluates APY/TVL evidence; stale feed → unfundable",
                                ".claude/rules/adapters.md / RiskPolicy"),
        "evidence": _f(AVAILABLE, "APY unevidenced (live_apy=null); TVL static", prov_adapter),
        "decision_history": _f(PARTIAL, "see WHY trace", "studio_shell/why_aave.json"),
        "status": _f(AVAILABLE, "NOT HELD · UNEVIDENCED", prov_adapter),
    }

    # ── CAPITAL ──────────────────────────────────────────────────────────────────────────
    total = positions.get("capital_usd")
    capital = {
        "track": _f(AVAILABLE, track, "data/current_positions.json#execution_mode"),
        "allocated_to_this": _f(AVAILABLE, (held or {}).get("usd", 0) or 0, "data/current_positions.json",
                                "0 — no capital allocated to this opportunity"),
        "book_total_usd": _f(AVAILABLE, total, "data/current_positions.json#capital_usd"),
        "deployed_usd": _f(AVAILABLE, positions.get("deployed_usd"), "data/current_positions.json"),
        "cash_usd": _f(AVAILABLE, positions.get("cash_usd"), "data/current_positions.json"),
        "allocation_pct": _f(AVAILABLE, 0.0, "data/current_positions.json", "0% of book"),
        "real_money_implication": _f(AVAILABLE, "NONE — PAPER/virtual", None),
    }

    # ── RISK (EXECUTED policy) ───────────────────────────────────────────────────────────
    risk = _risk_gates(apy_val, apy_evidenced, tvl, tvl_evidenced)

    # ── RESULT ───────────────────────────────────────────────────────────────────────────
    fundable = risk["fundable"]["value"]
    result_label = ("PAPER · HELD" if held else
                    "NOT FUNDABLE · UNEVIDENCED" if not fundable else
                    "CANDIDATE · NO LIVE ALLOCATION")
    if held:
        held_usd = (held or {}).get("usd")
        reason = (f"held ${held_usd:,.0f} (PAPER). NEW-capital fundability: "
                  + ("passes" if fundable else risk["reason"]["value"]))
    else:
        reason = risk["reason"]["value"]
    result = {
        "label": _f(AVAILABLE, result_label),
        "held": _f(AVAILABLE, bool(held)),
        "new_allocation_fundable": risk["fundable"],
        "reason": _f(AVAILABLE, reason),
    }

    # ── WHY (reuse existing trace) ───────────────────────────────────────────────────────
    why_stage = {
        "available": _f(AVAILABLE if why else MISSING, bool(why), "studio_shell/why_aave.json"),
        "trace_partial": _f(AVAILABLE if why else MISSING, (why or {}).get("trace_partial")),
        "missing_edges": _f(AVAILABLE, [e for e in (
            "strategy→position binding" if strategy["active_binding"]["status"] == MISSING else None,
            "position (no capital allocated)" if not held else None,
        ) if e]),
    }

    return {
        "schema": "earn-defi/investment-slice/1",
        "entity": {"id": f"op:{protocol}", "protocol": protocol,
                   "label": a.get("display_name") or protocol},
        "chain_stages": ["OPPORTUNITY", "STRATEGY", "POSITION", "CAPITAL", "RISK", "RESULT", "WHY"],
        "opportunity": opportunity,
        "strategy": strategy,
        "position": passport,
        "capital": capital,
        "risk": risk,
        "result": result,
        "why": why_stage,
        "note": "Read-only projection. Not canonical state. Blanks marked MISSING/NA, never invented.",
    }


def _risk_gates(apy, apy_evidenced, tvl, tvl_evidenced):
    """Evaluate the EXECUTED RiskPolicy thresholds (read from spa_core.risk.policy) against the facts."""
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        apy_min = getattr(cfg, "min_apy_for_new_position", 1.0)
        apy_max = getattr(cfg, "max_apy_for_new_position", 30.0)
        tvl_floor = getattr(cfg, "min_tvl_usd", 5_000_000)
        src = "EXECUTED — spa_core/risk/policy.py#RiskConfig"
    except Exception:
        apy_min, apy_max, tvl_floor, src = 1.0, 30.0, 5_000_000, "DOCUMENTED — fallback (policy import failed)"

    gates = []
    # APY band gate
    apy_band_ok = apy is not None and apy_min <= apy <= apy_max
    gates.append({"rule": f"APY ∈ [{apy_min}, {apy_max}]%", "input": apy, "pass": apy_band_ok,
                  "policy": src})
    # APY evidence gate (ADR-053 / allocator._fundable) — unevidenced APY is not fundable
    gates.append({"rule": "APY must be evidenced (live)", "input": "evidenced" if apy_evidenced else "UNEVIDENCED",
                  "pass": apy_evidenced, "policy": src})
    # TVL floor — checked ONLY on live TVL (ADR-053); static TVL does not clear the floor
    tvl_ok = tvl_evidenced and tvl is not None and tvl >= tvl_floor
    gates.append({"rule": f"live TVL ≥ ${tvl_floor:,.0f} (ADR-053: static does NOT count)",
                  "input": f"{tvl} ({'live' if tvl_evidenced else 'static/unevidenced'})",
                  "pass": tvl_ok, "policy": src})

    fundable = all(g["pass"] for g in gates)
    if fundable:
        reason = "all deterministic gates pass"
    else:
        failed = [g["rule"] for g in gates if not g["pass"]]
        reason = "blocked by: " + "; ".join(failed)
    return {
        "policy_version": _f(AVAILABLE, "v1.0", "spa_core/risk/policy.py"),
        "policy_kind": _f(AVAILABLE, src.split(" — ")[0]),
        "gates": _f(AVAILABLE, gates, src),
        "fundable": _f(DERIVABLE, fundable, src),
        "reason": _f(AVAILABLE, reason),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(build_investment_slice(sys.argv[1] if len(sys.argv) > 1 else "aave_v3"),
                     ensure_ascii=False, indent=1))
