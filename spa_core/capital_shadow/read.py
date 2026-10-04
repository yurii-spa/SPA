"""capital_shadow.read — the separate, read-only VERIFIER (ADR-556 binding review #10).

``run.py`` WRITES intents / simulations / transitions / the ledger. This module NEVER writes
anything. It recomputes the readiness verdict straight from the ledger (+ verifies the hash chain
and the external anchors); Mission Control, Telegram and the runbook renderer are meant to call
only this, never ``run.py``'s in-process state.

A broken chain is reported as ``state=NOT_MEASURED, integrity=BROKEN`` — never served as if it
were a trustworthy readiness verdict (the tampered entry might be the tail itself).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.capital_shadow import contract, incidents, ledger, readiness

_DEFI_SLEEVES = ("defi_conservative", "defi_balanced", "defi_aggressive")


#: review #3: the one non-candidate sleeve id every scenario/canary row carries.
_CANARY_SLEEVE = "scenario_canary"


def _is_scenario_payload(payload: dict) -> bool:
    s = payload.get("scenario")
    return isinstance(s, str) and s.startswith(contract.SCENARIO_TEST_PREFIX)


def _short(intent_id) -> Optional[str]:
    return intent_id[:12] if isinstance(intent_id, str) else None


def _row_is_canary(payload: dict) -> bool:
    return payload.get("sleeve_id") == _CANARY_SLEEVE


def _last_of_kind(entries: list, kind: str, *, canary: Optional[bool] = None) -> Optional[dict]:
    """``canary=None`` -> any row. ``canary=False``/``True`` -> only rows whose owning payload's
    own ``sleeve_id`` is/isn't :data:`_CANARY_SLEEVE` (review #15: a simulation/reconciliation row
    always carries its OWN sleeve_id; a shadow_fill's payload carries it too)."""
    last = None
    for e in entries:
        if e.get("kind") != kind:
            continue
        if canary is not None and _row_is_canary(e.get("payload") or {}) != canary:
            continue
        if last is None or e["seq"] > last["seq"]:
            last = e
    return last


def _intent_state_counts(entries: list) -> tuple[dict, dict]:
    """``(current_state_counts, scenario_counts)`` — one tally per intent (by scenario vs
    current-state), keyed by the intent's CURRENT state (``NO_ACTION`` for an intent whose own
    action_type is NO_ACTION; otherwise the latest recorded transition's ``to_state``, or
    ``DRAFT`` if none exists yet)."""
    intents_by_id: dict = {}
    for e in entries:
        if e.get("kind") == "intent":
            intents_by_id[e["payload"]["intent_id"]] = e["payload"]
    latest_transition: dict = {}
    for e in entries:
        if e.get("kind") != "transition":
            continue
        iid = e["payload"]["intent_id"]
        if iid not in latest_transition or e["seq"] > latest_transition[iid]["seq"]:
            latest_transition[iid] = e

    current_counts: dict = {}
    scenario_counts: dict = {}
    for iid, payload in intents_by_id.items():
        if payload.get("action_type") == contract.ACTION_NO_ACTION:
            state = "NO_ACTION"
        else:
            t = latest_transition.get(iid)
            state = t["payload"]["to_state"] if t is not None else contract.S_DRAFT
        bucket = scenario_counts if _is_scenario_payload(payload) else current_counts
        bucket[state] = bucket.get(state, 0) + 1
    return current_counts, scenario_counts


def _owner_decisions_pending(reports: dict) -> int:
    """Deduplicated by PRECONDITION NAME across sleeves — four preconditions exist in total
    (golive_decision, live_admission, custody, pilot_amount); a precondition pending in every
    sleeve still counts once, never once per sleeve."""
    pending_names: set = set()
    for report in reports.values():
        for name, p in (report.get("owner_preconditions") or {}).items():
            if p.get("state") == contract.PRECONDITION_PENDING:
                pending_names.add(name)
    return len(pending_names)


def _top_blockers(reports: dict, *, top_n: int = 5) -> list:
    """The N most common FAILING/UNKNOWN system gates across the three DeFi sleeves (the only
    sleeves with a real ``system_checks`` set today — ``cash``/``trading_research``/
    ``market_neutral_basis`` are never a pilot candidate and carry no real gate evidence)."""
    counts: dict = {}
    for sleeve_id in _DEFI_SLEEVES:
        report = reports.get(sleeve_id)
        if not report:
            continue
        for gate, g in (report.get("system_checks") or {}).items():
            if g.get("state") != contract.GATE_PASS:
                counts[gate] = counts.get(gate, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"gate": gate, "count": n} for gate, n in ordered[:top_n]]


def _build_summary(entries: list, reports: dict, data_dir: Path) -> dict:
    """Everything here is read straight off the ledger/verifier — the writer computes nothing new
    for Mission Control; this function only re-shapes what ``run.py`` already recorded. Secret-free
    and path-free by construction: every field is a short id, a venue/action/outcome/count/mode
    string, a block number, or a timestamp — never a filesystem path."""
    def _simulation_view(e):
        if e is None:
            return None
        p = e["payload"]
        intent_row = next((x for x in entries if x.get("kind") == "intent"
                           and x["payload"].get("intent_id") == p.get("intent_id")), None)
        action = intent_row["payload"].get("action_type") if intent_row else None
        return {"intent_id": _short(p.get("intent_id")), "venue": p.get("venue"), "action": action,
               "result": p.get("result"), "block": p.get("block"), "at": e.get("at"),
               "scenario": _row_is_canary(p)}

    def _shadow_execution_view(e):
        if e is None:
            return None
        p = e["payload"]
        intent_row = next((x for x in entries if x.get("kind") == "intent"
                           and x["payload"].get("intent_id") == p.get("intent_id")), None)
        action = intent_row["payload"].get("action_type") if intent_row else None
        venue = intent_row["payload"].get("network_or_venue") if intent_row else None
        return {"intent_id": _short(p.get("intent_id")), "venue": venue, "action": action,
               "sleeve_id": p.get("sleeve_id"), "at": e.get("at"), "scenario": _row_is_canary(p)}

    def _reconciliation_view(e):
        if e is None:
            return None
        p = e["payload"]
        return {"intent_id": _short(p.get("intent_id")), "venue": p.get("venue"), "outcome": p.get("outcome"),
               "blocks": {"old": p.get("old_block"), "new": p.get("new_block")}, "at": e.get("at"),
               "scenario": _row_is_canary(p)}

    # review #15: prefer the last CURRENT-STATE item; fall back to the last of ANY kind only when
    # no current-state row exists yet (e.g. a fresh data_dir that has only ever run a scenario
    # pass) — and ALWAYS report the last canary separately too, never conflated with the real one.
    last_sim_current = _last_of_kind(entries, "simulation", canary=False)
    last_sim_canary = _last_of_kind(entries, "simulation", canary=True)
    last_shadow_current = _last_of_kind(entries, "shadow_fill", canary=False)
    last_shadow_canary = _last_of_kind(entries, "shadow_fill", canary=True)
    last_recon_current = _last_of_kind(entries, "reconciliation", canary=False)
    last_recon_canary = _last_of_kind(entries, "reconciliation", canary=True)

    last_simulation = _simulation_view(last_sim_current or _last_of_kind(entries, "simulation"))
    last_shadow_execution = _shadow_execution_view(last_shadow_current or _last_of_kind(entries, "shadow_fill"))
    last_reconciliation = _reconciliation_view(last_recon_current or _last_of_kind(entries, "reconciliation"))
    last_simulation_canary = _simulation_view(last_sim_canary)
    last_shadow_execution_canary = _shadow_execution_view(last_shadow_canary)
    last_reconciliation_canary = _reconciliation_view(last_recon_canary)

    current_counts, scenario_counts = _intent_state_counts(entries)
    # review N4: a broken incident store must SURFACE as broken, never be silently read as "no
    # open incidents" ([]) — incidents.store_state(data_dir) (the SHARED helper, landed this round)
    # answers this without a try/except around open_incidents's own exception; readiness's own
    # defi-sleeve gates separately force BLOCKED on the equivalent exception.
    store = incidents.store_state(data_dir)
    incidents_store_state = store["state"]
    incidents_store_reason = store["reason"]
    open_incs = incidents.open_incidents(data_dir) if incidents_store_state == "OK" else []

    last_entry = entries[-1] if entries else None
    return {
        "last_simulation": last_simulation, "last_shadow_execution": last_shadow_execution,
        "last_reconciliation": last_reconciliation,
        "last_simulation_canary": last_simulation_canary,
        "last_shadow_execution_canary": last_shadow_execution_canary,
        "last_reconciliation_canary": last_reconciliation_canary,
        "current_state_intent_counts": current_counts, "scenario_intent_counts": scenario_counts,
        "open_incidents": {
            "state": incidents_store_state, "reason": incidents_store_reason,
            "count": len(open_incs) if incidents_store_state == "OK" else None,
            "kinds": sorted({i.get("kind") for i in open_incs}) if incidents_store_state == "OK" else [],
        },
        "owner_decisions_pending": _owner_decisions_pending(reports),
        "current_execution_mode": contract.LAYER_MODE,
        "automated_live_execution": contract.AUTOMATED_LIVE_EXECUTION,
        "real_capital_usd": contract.REAL_CAPITAL_USD,
        "top_blockers": _top_blockers(reports),
        "generated_at": last_entry.get("at") if last_entry else None,
    }


def latest(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    try:
        entries = ledger.read_all(data_dir)
    except ledger.LedgerError as exc:
        return {"state": contract.NOT_MEASURED, "integrity": "BROKEN", "reason": str(exc)}

    chain = ledger.verify_chain(data_dir)
    if not chain.get("ok", False):
        return {"state": contract.NOT_MEASURED, "integrity": "BROKEN",
                "reason": f"ledger chain is not intact (break_at={chain.get('break_at')}, "
                         f"reason={chain.get('reason') or 'chain'}) — readiness withheld"}

    reports = readiness.evaluate(data_dir, entries, now)
    summary = _build_summary(entries, reports, data_dir)
    # review N5: venue_canary is a SEPARATE top-level key, never mixed into "readiness" — that map
    # now contains ONLY sleeve reports (readiness.evaluate() no longer emits it either).
    venue_canary = readiness.venue_canary_section(entries)
    return {"state": contract.MEASURED, "integrity": "OK", "ledger": {"entries": len(entries), "chain_ok": True},
           "readiness": reports, "venue_canary": venue_canary, "summary": summary,
           "authorization": contract.AUTHORIZATION_TEXT}
