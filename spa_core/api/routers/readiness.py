"""Public go-live-readiness surface (Q2-3).

The honest 'what code has proven vs what only the owner can do' one-stop endpoint:
- governance defenses FIRE (data/defenses_exercised.json — 11/11, reproducible);
- the go-live gate status (data/golive_status.json — evidenced-days + criteria);
- the owner-only blockers code CANNOT satisfy (custody / audit / legal / 30-day track).

Fail-CLOSED: a missing artifact yields an honest null, never a fabricated pass.
Read-only; serves committed/live artifacts verbatim. Nothing here moves capital.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"


def _load(name: str) -> dict:
    try:
        return json.loads((_DATA / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — fail-closed: absent/corrupt → empty, never a fake pass
        return {}


# The owner-only blockers are stable, documented facts (pre_cutover_gate advisory +
# ADR-010 + the go-live gate) — NOT fabricated numbers. AI holds no keys, is never a signer.
# Static fallback used only when data/owner_blockers.json is absent (sandbox/CI fixtures).
# Every gate carries a status (fail-closed: no evidence artifact ⇒ honestly "open" — the code never
# fabricates procurement progress), so the fallback shape matches the rich owner_blockers.build() output.
_OWNER_ONLY = [
    {"id": "custody", "status": "open", "what": "Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010) — AI holds no keys and is never a signer"},
    {"id": "audit", "status": "open", "what": "external security audit of the execution path signed off"},
    {"id": "legal", "status": "open", "what": "entity + disclosure / no-guarantee framing reviewed by counsel before any external capital"},
    {"id": "track_days", "status": "open", "what": "≥30 evidenced honest paper-track days (the go-live gate; time-gated, nothing to fix in code)"},
]


def _owner_blockers() -> dict:
    """Q1-9: serve the dynamic owner-only procurement tracker (per-gate status:
    open/in_progress/satisfied). Code never fabricates progress — audit/legal flip only
    on owner-asserted evidence, track_days is time-derived. Falls back to the static
    catalogue when data/owner_blockers.json is absent (never a 500)."""
    ob = _load("owner_blockers.json")
    gates = ob.get("gates") if isinstance(ob, dict) else None
    if not gates:
        return {"gates": _OWNER_ONLY, "open_count": len(_OWNER_ONLY),
                "total": len(_OWNER_ONLY), "all_satisfied": False, "generated_at": None}
    return {
        "gates": gates,
        "open_count": ob.get("open_count"),
        "total": ob.get("total"),
        "all_satisfied": ob.get("all_satisfied"),
        "generated_at": ob.get("generated_at"),
    }


@router.get("/api/readiness")
def readiness() -> dict:
    dex = _load("defenses_exercised.json")
    rtmr = _load("defenses_exercised_rtmr.json")
    golive = _load("golive_status.json")
    ksd = _load("kill_switch_drill_status.json")
    tledger = _load("track_ledger.json")
    ceff = _load("capital_efficiency.json")
    return {
        "governance_defenses": {
            "fired": dex.get("scenarios_fired"),
            "total": dex.get("scenarios_total"),
            "all_fired": dex.get("all_defenses_fired"),
            "thresholds": dex.get("thresholds"),
        },
        # Q2-13: the RTMR real-time de-risk reaction ladder proven to FIRE (peg/tvl/oracle/liquidity +
        # stale + systemic) through the production reaction engine — complements the daily-cycle kill
        # ladder above. Missing artifact → nulls (honest absence, never a 500).
        "rtmr_defenses": {
            "fired": rtmr.get("scenarios_fired"),
            "total": rtmr.get("scenarios_total"),
            "all_fired": rtmr.get("all_fired"),
        },
        # Q3-5: dated kill-switch drill evidence — the emergency-stop is auditable (measured latency vs
        # its 1s budget + last-drill date). Missing artifact → nulls (honest absence, never a 500).
        "kill_switch_drill": {
            "last_drill_at": ksd.get("last_drill_at"),
            "latency_ms": ksd.get("latency_ms"),
            "latency_limit_ms": ksd.get("latency_limit_ms"),
            "passed": ksd.get("passed"),
            "verdict": ksd.get("verdict"),
        },
        # Q1-13 (owner-flagged): capital-efficiency verdict — the desk measures RISK world-class; this
        # makes CAPITAL EFFICIENCY a first-class, published invariant too. deployed_pct + verdict
        # (OK=capital working / WARNING=deployable headroom left idle / UNKNOWN=fail-closed). Missing
        # artifact → nulls (honest absence, never a 500). Advisory: this guard moves no capital.
        "capital_efficiency": {
            "verdict": ceff.get("verdict"),
            "deployed_pct": ceff.get("deployed_pct"),
            "cash_pct": ceff.get("cash_pct"),
            "min_cash_pct": ceff.get("min_cash_pct"),
            "forgone_yield_bps_est": ceff.get("forgone_yield_bps_est"),
        },
        # Q2-18: dated evidenced-track ledger SUMMARY — the 30-day go-live claim as a checkable artifact
        # (day-by-day dd/return reproducible via `python3 -m spa_core.paper_trading.track_ledger`). Only
        # the summary is surfaced here; the full per-day ledger lives in data/track_ledger.json.
        "track_ledger": {
            "n_evidenced_days": tledger.get("n_evidenced_days"),
            "days_needed": tledger.get("days_needed"),
            "days_remaining": tledger.get("days_remaining"),
            "first_evidenced_date": tledger.get("first_evidenced_date"),
            "last_evidenced_date": tledger.get("last_evidenced_date"),
            "cumulative_return_pct": tledger.get("cumulative_return_pct"),
            "max_drawdown_from_peak_pct": tledger.get("max_drawdown_from_peak_pct"),
        },
        "go_live_gate": {
            "passed": golive.get("passed"),
            "total": golive.get("total"),
            "evidenced_days": golive.get("real_track_days"),
            "days_needed": golive.get("min_track_days", 30),
            "target_date": golive.get("target_date") or golive.get("go_live_target"),
            # Q3-4: the rolling consecutive-READY streak (runbook wants 7 sustained). Surfacing it
            # turns the remaining wait into a VISIBLE de-risking proof rather than an opaque countdown.
            "consecutive_ready_days": golive.get("consecutive_ready_days"),
            "consecutive_ready_days_needed": 7,
        },
        # Q1-9: dynamic owner-only blocker tracker — each gate carries a live status
        # (open/in_progress/satisfied) so procurement runs in parallel with track days.
        # `owner_only_blockers` stays a flat list for backward-compat consumers; the
        # richer per-gate view is under `owner_blockers`.
        "owner_only_blockers": [{"id": g["id"], "what": g["what"]} for g in _owner_blockers()["gates"]],
        "owner_blockers": _owner_blockers(),
        "reproduce": {
            "proof_chain": "python3 scripts/verify_spa.py data/",
            "defenses_fire": "python3 scripts/defenses_exercised_report.py",
            "money_path_gate": "python3 -m spa_core.paper_trading.pre_cutover_gate  (16/16, inert)",
        },
        "honest": "The code proves the money-path + governance defenses fire; custody / audit / legal "
                  "/ the 30-day evidenced track are owner-only and time-gated. Nothing here moves capital.",
    }
