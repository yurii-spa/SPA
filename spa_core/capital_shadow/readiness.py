"""capital_shadow.readiness — ``PilotReadinessReport`` (ADR-556, binding review #6/#7).

Readiness is not authorization. ``system_checks`` are machine gates, independent of any owner
decision; ``owner_preconditions`` are reported SEPARATELY and never folded into the gate list
(review #6). ``MANUAL_PILOT_READY`` requires set-equality against the frozen
:data:`contract.SYSTEM_GATES` list with every one ``PASS`` — an empty or short list is a FAIL by
construction, never a vacuous pass (review #7). UNKNOWN never becomes safe: it blocks exactly like
FAIL.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.capital_shadow import contract, ledger
from spa_core.capital_shadow.intent import _read_json, book_digest_and_asof, is_test_scenario, read_kill_switch_state
from spa_core.utils.observation import observed

#: sleeve_id -> book file (the same mapping intent.py uses — the book is the single source)
_BOOK_FILE = {"defi_conservative": "trades.json", "defi_balanced": "hy_paper_trading.json",
             "defi_aggressive": "lp_paper_trading.json"}
#: daily cycle (conservative) vs the hourly-ish hy_cycle/lp_cycle (same constants as
#: investment_cio/sleeves.py — not reinvented).
_CADENCE_DAILY_H = 26.0
_CADENCE_HOURLY_H = 3.0
_FRESHNESS_CADENCE_H = {"defi_conservative": _CADENCE_DAILY_H, "defi_balanced": _CADENCE_HOURLY_H,
                       "defi_aggressive": _CADENCE_HOURLY_H}


def _gate(state: str, *, evidence: Any = None, probe: str) -> dict:
    return {"state": state, "evidence": evidence, "probe": probe}


def _held_protocols(data_dir: Path, sleeve_id: str) -> list:
    if sleeve_id == "defi_conservative":
        doc, _ = _read_json(Path(data_dir) / "trades.json")
        if isinstance(doc, list) and doc and isinstance(doc[-1], dict):
            alloc = doc[-1].get("to_allocation") or {}
            return sorted(k for k, v in alloc.items() if isinstance(v, (int, float)) and v > 0)
        return []
    _, _, book_doc = book_digest_and_asof(data_dir, _BOOK_FILE[sleeve_id])
    positions = observed(book_doc, "positions", kind=list) or []
    out = []
    for p in positions:
        if isinstance(p, dict):
            v = p.get("venue") or p.get("protocol")
            if v:
                out.append(v)
    return sorted(out)


def _norm(slug: str) -> str:
    return slug.lower().replace("-", "_")


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        v = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(v)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def _freshness_source(data_dir: Path, sleeve_id: str) -> tuple[Optional[str], Optional[str]]:
    """``(as_of, source_name)`` for the sleeve's own CYCLE, never its last REBALANCE (found via an
    integration run: ``trades.json``'s last trade can be weeks old precisely because the book kept
    recommending HOLD — that is a healthy, FRESH book, and reading trade age as "data freshness"
    reported a 533h-stale book that was in fact cycling every day).

    conservative: ``current_positions.json.generated_at``, else ``equity_curve_daily.json
    .generated_at``, else the shared ``defi_engine/status.json.generated_at``.
    balanced/aggressive: the book's own ``last_cycle_at`` (``hy_paper_trading.json`` /
    ``lp_paper_trading.json`` — already correct before this fix), else
    ``defi_engine/status.json.generated_at``.
    """
    if sleeve_id == "defi_conservative":
        for relpath, key in (("current_positions.json", "generated_at"), ("equity_curve_daily.json",
                             "generated_at")):
            doc, _ = _read_json(Path(data_dir) / relpath)
            as_of = observed(doc, key, kind=str) if doc is not None else None
            if as_of is not None:
                return as_of, relpath
    else:
        _, as_of, doc = book_digest_and_asof(data_dir, _BOOK_FILE[sleeve_id])
        if doc is not None and as_of is not None:
            return as_of, _BOOK_FILE[sleeve_id]
    doc, _ = _read_json(Path(data_dir) / "defi_engine" / "status.json")
    as_of = observed(doc, "generated_at", kind=str) if doc is not None else None
    if as_of is not None:
        return as_of, "defi_engine/status.json"
    return None, None


def _data_freshness_gate(data_dir: Path, sleeve_id: str, now: datetime) -> dict:
    cadence_h = _FRESHNESS_CADENCE_H[sleeve_id]
    as_of, source = _freshness_source(data_dir, sleeve_id)
    if as_of is None:
        return _gate(contract.GATE_UNKNOWN, evidence="no readable cycle timestamp (current_positions.json / "
                    "equity_curve_daily.json / book last_cycle_at / defi_engine/status.json all absent)",
                    probe="sleeve cycle freshness (not the last trade/rebalance)")
    dt = _parse_iso(as_of)
    if dt is None:
        return _gate(contract.GATE_UNKNOWN, evidence=f"unparsable as_of {as_of!r} from {source}", probe="parse as_of")
    age_h = (now - dt).total_seconds() / 3600.0
    evidence = {"age_hours": round(age_h, 2), "cadence_hours": cadence_h, "source": source}
    # review #10: a NEGATIVE age (the timestamp is in the future — clock skew or bad data) is not
    # "very fresh"; it is refused, never treated as the best possible answer.
    if age_h < 0:
        return _gate(contract.GATE_FAIL, evidence=evidence,
                    probe=f"{source} timestamp is in the future (clock skew or bad data) — refused")
    if age_h > cadence_h:
        return _gate(contract.GATE_FAIL, evidence=evidence, probe=f"{source} age vs {cadence_h}h cadence")
    return _gate(contract.GATE_PASS, evidence=evidence, probe=f"{source} age vs {cadence_h}h cadence")


def _sleeve_projection(sleeves_doc: dict, sleeve_id: str) -> Optional[dict]:
    """``build_sleeves()`` returns ``{"schema", "generated_at", "sleeves": {sleeve_id: {...}}, ...}``
    — the per-sleeve dict is nested under ``"sleeves"``, never at the top level (found via an
    integration run: reading ``sleeves_doc[sleeve_id]`` directly always missed, reporting every
    sleeve as "not projected" even though ``build_sleeves`` succeeded)."""
    if not isinstance(sleeves_doc, dict):
        return None
    sleeves = sleeves_doc.get("sleeves")
    if not isinstance(sleeves, dict):
        return None
    return sleeves.get(sleeve_id)


def _strategy_evidence_gate(sleeves_doc: dict, sleeve_id: str) -> dict:
    sleeve = _sleeve_projection(sleeves_doc, sleeve_id)
    if sleeve is None:
        return _gate(contract.GATE_UNKNOWN, evidence="sleeve not projected by investment_cio.sleeves",
                    probe="investment_cio.sleeves.build_sleeves()['sleeves'][sleeve_id].maturity")
    maturity = sleeve.get("maturity") or {}
    if maturity.get("state") != "MEASURED":
        return _gate(contract.GATE_FAIL, evidence=maturity, probe="sleeves.build_sleeves()['sleeves'].maturity")
    value = contract.value_of(maturity)
    return _gate(contract.GATE_PASS if value == "MATURE" else contract.GATE_FAIL,
                evidence=maturity, probe="sleeves.build_sleeves()['sleeves'].maturity == MATURE (ADR-554)")


def _risk_evidence_gate(sleeve_id: str, data_dir: Path) -> dict:
    """review #8: RiskPolicy coverage alone is not enough — depeg must ALSO be MEASURED, or this
    gate FAILs. Today depeg is always NOT_MEASURED (no real source exists yet), so this gate FAILs
    for conservative too, honestly, until a real depeg source lands (a future dedicated
    ``depeg_measured`` system gate is tracked separately; the frozen ``contract.SYSTEM_GATES`` list
    is not editable here)."""
    if sleeve_id != "defi_conservative":
        return _gate(contract.GATE_FAIL, evidence="caps mirrored, not imported from RiskPolicy",
                    probe="B/C sleeve RiskPolicy coverage (ADR-556 inherited blocker)")
    from spa_core.capital_shadow.intent import read_depeg_state, read_riskpolicy_state
    cell = read_riskpolicy_state(data_dir)
    depeg = read_depeg_state(data_dir)
    if cell["state"] != contract.MEASURED:
        return _gate(contract.GATE_UNKNOWN, evidence=cell["reason"], probe="current_positions.json policy_compliant")
    verdict = (cell["value"] or {}).get("verdict")
    if verdict != "PASS":
        return _gate(contract.GATE_FAIL, evidence={"riskpolicy_verdict": verdict},
                    probe="current_positions.json policy_compliant")
    if depeg["state"] != contract.MEASURED:
        return _gate(contract.GATE_FAIL, evidence={"riskpolicy_verdict": verdict, "depeg_state": depeg["state"],
                    "depeg_reason": depeg["reason"]}, probe="RiskPolicy PASS AND depeg MEASURED")
    return _gate(contract.GATE_PASS, evidence={"riskpolicy_verdict": verdict, "depeg": depeg["value"]},
                probe="RiskPolicy PASS AND depeg MEASURED")


def _protocol_evidence_gate(data_dir: Path, sleeve_id: str) -> dict:
    """review #10: EXACT slug matching only — the old prefix match (``startswith`` either way) let
    an empty slug (``""``) match EVERY held protocol, since ``anything.startswith("")`` is always
    True; a single malformed ``risk_scores.json`` row then silently graded the whole book. An empty
    held-protocol list is ALSO a FAIL, never a vacuous PASS (nothing to grade is not "all graded")."""
    held = _held_protocols(data_dir, sleeve_id)
    if not held:
        return _gate(contract.GATE_FAIL, evidence="no held venues to evaluate protocol grading against "
                    "(a vacuous pass is refused)", probe="held protocols vs risk_scores.json scores[].slug")
    doc, _ = _read_json(Path(data_dir) / "risk_scores.json")
    if doc is None:
        return _gate(contract.GATE_FAIL, evidence="risk_scores.json unavailable; default-graded protocols "
                    "presumed: maple, fluid_fusdc", probe="read risk_scores.json")
    scores = observed(doc, "scores", kind=list) or []
    known = {_norm(s.get("slug", "")) for s in scores if isinstance(s, dict)} - {""}
    unscored = [p for p in held if _norm(p) not in known]
    if unscored:
        return _gate(contract.GATE_FAIL, evidence={"default_graded": unscored},
                    probe="held protocols vs risk_scores.json scores[].slug (exact match)")
    return _gate(contract.GATE_PASS, evidence={"held": held},
                probe="held protocols vs risk_scores.json scores[].slug (exact match)")


def _counterparty_evidence_gate() -> dict:
    return _gate(contract.GATE_UNKNOWN, evidence="no counterparty-risk source (Maple credit, Ethena) — "
                "BLOCKS_ALL_PILOTS (ADR-556)", probe="counterparty risk source (none exists)")


#: sleeve_id -> defi_engine/status.json books.* key
_DEFI_ENGINE_BOOK_KEY = {"defi_conservative": "conservative", "defi_balanced": "balanced",
                        "defi_aggressive": "aggressive"}


def _liquidity_evidence_gate(data_dir: Path, sleeve_id: str) -> dict:
    """Real shape: ``defi_engine/status.json`` → ``books.<book_key>.exit.{share_illiquid,
    max_illiquid_share, policy_ok, share_basis}`` — there is no top-level ``share_illiquid`` (found
    via an integration run: the flat top-level read always missed, reporting UNKNOWN for every
    sleeve even though the real file carries the figure, per book, under ``exit``)."""
    doc, _ = _read_json(Path(data_dir) / "defi_engine" / "status.json")
    if doc is None:
        return _gate(contract.GATE_UNKNOWN, evidence="defi_engine/status.json unavailable",
                    probe="defi_engine/status.json books.<book>.exit.share_illiquid")
    book_key = _DEFI_ENGINE_BOOK_KEY.get(sleeve_id)
    books = observed(doc, "books", kind=dict)
    book = observed(books, book_key, kind=dict) if books is not None and book_key else None
    exit_ = observed(book, "exit", kind=dict) if book is not None else None
    if exit_ is None:
        return _gate(contract.GATE_UNKNOWN, evidence=f"defi_engine/status.json books.{book_key}.exit not published",
                    probe="defi_engine/status.json books.<book>.exit.share_illiquid")
    share_illiquid = observed(exit_, "share_illiquid", kind=(int, float))
    max_illiquid_share = observed(exit_, "max_illiquid_share", kind=(int, float))
    policy_ok = observed(exit_, "policy_ok", kind=bool)
    evidence = {"share_illiquid": share_illiquid, "max_illiquid_share": max_illiquid_share, "policy_ok": policy_ok,
               "share_basis": observed(exit_, "share_basis", kind=str)}
    if policy_ok is not None:
        return _gate(contract.GATE_PASS if policy_ok else contract.GATE_FAIL, evidence=evidence,
                    probe="defi_engine/status.json books.<book>.exit.policy_ok")
    if share_illiquid is None or max_illiquid_share is None:
        return _gate(contract.GATE_UNKNOWN, evidence=evidence,
                    probe="defi_engine/status.json books.<book>.exit.share_illiquid vs max_illiquid_share")
    return _gate(contract.GATE_PASS if share_illiquid <= max_illiquid_share else contract.GATE_FAIL,
                evidence=evidence, probe="defi_engine/status.json books.<book>.exit.share_illiquid <= "
                "max_illiquid_share")


def _mtm_gate(sleeves_doc: dict, sleeve_id: str) -> dict:
    sleeve = _sleeve_projection(sleeves_doc, sleeve_id)
    cell = (sleeve or {}).get("mtm_coverage") or {}
    if cell.get("state") != "MEASURED":
        return _gate(contract.GATE_FAIL, evidence=cell.get("reason") or "mtm_coverage not measured",
                    probe="sleeves.build_sleeves()['sleeves'].mtm_coverage")
    value = contract.value_of(cell)
    ok = isinstance(value, (int, float)) and value >= 0.99
    return _gate(contract.GATE_PASS if ok else contract.GATE_FAIL, evidence=value,
                probe="sleeves.build_sleeves().mtm_coverage >= 0.99")


def _scenario_intent_ids(ledger_entries: list) -> set:
    """Every ``intent_id`` whose OWNING intent's own ``scenario`` field starts with
    :data:`contract.SCENARIO_TEST_PREFIX` — read straight off the ``intent`` kind rows in
    ``ledger_entries`` (never off the simulation/reconciliation/unwind_probe payload itself,
    which — confirmed by reading ``ledger.record_simulation_entry``/``reconcile.forward_reconcile``
    — carries no ``scenario`` field of its own; ``ledger.py``/``reconcile.py`` are a concurrent
    agent's files this round, so this is a READ-side cross-reference, not a payload-shape change)."""
    ids = set()
    for e in ledger_entries:
        if e.get("kind") != "intent":
            continue
        payload = e.get("payload") or {}
        scenario = payload.get("scenario")
        if is_test_scenario(scenario):
            iid = payload.get("intent_id")
            if iid is not None:
                ids.add(iid)
    return ids


def _real_sleeve_rows(ledger_entries: list, kind: str, sleeve_id: str) -> list:
    """Rows of ``kind`` whose OWNING intent's own ``sleeve_id`` is this exact real sleeve — never
    :data:`intent_mod.CANARY_SLEEVE` (review #3 HIGH: a TEST_SCENARIO simulation/reconciliation for
    the same VENUE used to satisfy a real sleeve's gate just because the venue matched; every
    scenario intent now carries a dedicated non-candidate sleeve id precisely so this filter is a
    single equality check, not a lookup into the owning intent's own scenario field).

    review round-3 L5: filtering by ``sleeve_id`` ALONE relies entirely on every TEST_SCENARIO
    intent-builder disciplining itself to always set :data:`intent_mod.CANARY_SLEEVE` — true today,
    but a single future bug in ANY intent-builder (a scenario intent accidentally carrying a REAL
    sleeve_id) would then leak straight into a real sleeve's gates with NO second check catching
    it. A row is excluded here whenever its OWNING intent's ``scenario`` field starts with
    :data:`contract.SCENARIO_TEST_PREFIX`, REGARDLESS of what ``sleeve_id`` that intent carries —
    two independent signals, not one."""
    scenario_ids = _scenario_intent_ids(ledger_entries)
    out = []
    for e in ledger_entries:
        if e.get("kind") != kind:
            continue
        payload = e.get("payload") or {}
        if payload.get("sleeve_id") != sleeve_id:
            continue
        if payload.get("intent_id") in scenario_ids:
            continue
        out.append(e)
    return out


def _reconciliation_gate(data_dir: Path, ledger_entries: list, sleeve_id: str) -> dict:
    """PASS only when EVERY venue the sleeve holds has a MATCHED reconciliation on record, from a
    row recorded for THIS sleeve (never a scenario-canary row, review #3)."""
    held = _held_protocols(data_dir, sleeve_id)
    if not held:
        return _gate(contract.GATE_UNKNOWN, evidence="no held venues to reconcile", probe="held protocols")
    latest_by_venue: dict = {}
    for e in _real_sleeve_rows(ledger_entries, "reconciliation", sleeve_id):
        venue = (e.get("payload") or {}).get("venue")
        if venue not in held:
            continue
        prev = latest_by_venue.get(venue)
        if prev is None or e["seq"] > prev["seq"]:
            latest_by_venue[venue] = e
    missing = [v for v in held if v not in latest_by_venue]
    not_matched = [v for v, e in latest_by_venue.items()
                   if (e.get("payload") or {}).get("outcome") != contract.REC_MATCHED]
    if missing or not_matched:
        return _gate(contract.GATE_FAIL, evidence={"missing": missing, "not_matched": not_matched},
                    probe="latest reconciliation per held venue (this sleeve only) == MATCHED")
    return _gate(contract.GATE_PASS, evidence={"venues": held},
                probe="latest reconciliation per held venue (this sleeve only) == MATCHED")


def _simulation_gate(data_dir: Path, ledger_entries: list, sleeve_id: str) -> dict:
    held = _held_protocols(data_dir, sleeve_id)
    if not held:
        return _gate(contract.GATE_UNKNOWN, evidence="no held venues to simulate", probe="held protocols")
    permissioned = [v for v in held if v in contract.PERMISSIONED_VENUES]
    if permissioned:
        return _gate(contract.GATE_FAIL, evidence={"NOT_SIMULATABLE": permissioned},
                    probe="permissioned venues are never simulatable")
    sims = ledger.simulations_for_venues(_real_sleeve_rows(ledger_entries, "simulation", sleeve_id), held)
    missing = [v for v, e in sims.items() if e is None]
    failing = [v for v, e in sims.items() if e is not None and (e.get("payload") or {}).get("result") !=
              contract.SIM_PASS]
    if missing or failing:
        return _gate(contract.GATE_FAIL, evidence={"missing": missing, "not_pass": failing},
                    probe="latest simulation ledger row per held venue (this sleeve only) == SIM_PASS")
    return _gate(contract.GATE_PASS, evidence={"venues": held},
                probe="latest simulation ledger row per held venue (this sleeve only) == SIM_PASS")


def _unwind_gate(data_dir: Path, ledger_entries: list, sleeve_id: str) -> dict:
    held = _held_protocols(data_dir, sleeve_id)
    if not held:
        return _gate(contract.GATE_UNKNOWN, evidence="no held venues", probe="held protocols")
    permissioned = [v for v in held if v in contract.PERMISSIONED_VENUES]
    if permissioned:
        return _gate(contract.GATE_FAIL, evidence={"NOT_SIMULATABLE": permissioned},
                    probe="unwind probe requires a simulatable venue")
    probes = {e["payload"]["venue"]: e["payload"] for e in _real_sleeve_rows(ledger_entries, "unwind_probe",
             sleeve_id) if (e.get("payload") or {}).get("venue") in held}
    missing = [v for v in held if v not in probes]
    bad = [v for v, p in probes.items() if p.get("state") != contract.GATE_PASS or (p.get("ratio") or 0) < 3.0]
    if missing or bad:
        return _gate(contract.GATE_FAIL, evidence={"missing": missing, "below_ratio_or_failed": bad},
                    probe="unwind probe PASS and liquidity ratio >= 3x per held venue (this sleeve only)")
    return _gate(contract.GATE_PASS, evidence={"venues": held},
                probe="unwind probe PASS and liquidity ratio >= 3x per held venue (this sleeve only)")


def _incident_response_gate(data_dir: Path) -> dict:
    from spa_core.capital_shadow import incidents as cs_incidents
    try:
        open_incidents = cs_incidents.open_incidents(data_dir)
    except Exception as exc:
        return _gate(contract.GATE_UNKNOWN, evidence=f"incidents unreadable: {exc!r}", probe="incidents.open_incidents")
    if open_incidents:
        return _gate(contract.GATE_FAIL, evidence={"open_incidents": len(open_incidents)}, probe="no open INCIDENT")
    try:
        from spa_core.alerts import alert_dispatcher
        has_path = hasattr(alert_dispatcher, "AlertDispatcher") and hasattr(alert_dispatcher.AlertDispatcher,
                                                                            "dispatch")
    except ImportError:
        has_path = False
    if not has_path:
        return _gate(contract.GATE_FAIL, evidence="alert dispatcher not importable", probe="import alert_dispatcher")
    return _gate(contract.GATE_PASS, evidence={"open_incidents": 0, "alert_path": True},
                probe="no open INCIDENT + alert dispatcher importable")


#: sleeve_id -> the launchd agent label whose health stands in for the book's own cycle
_BOOK_AGENT_LABEL = {"defi_conservative": "com.spa.daily_cycle", "defi_balanced": "com.spa.hy_cycle",
                     "defi_aggressive": "com.spa.lp_cycle"}


def _observability_gate(data_dir: Path, sleeve_id: str) -> dict:
    """Real shape: ``agent_health.json`` has no top-level ``status`` — it has ``agents``, a LIST
    of ``{"label", "status", ...}`` rows, one per launchd agent (found via an integration run: the
    flat top-level read always missed, reporting UNKNOWN regardless of the fleet's real state)."""
    doc, _ = _read_json(Path(data_dir) / "agent_health.json")
    if doc is None:
        return _gate(contract.GATE_UNKNOWN, evidence="agent_health.json unavailable", probe="read agent_health.json")
    label = _BOOK_AGENT_LABEL.get(sleeve_id)
    agents = observed(doc, "agents", kind=list) or []
    row = next((a for a in agents if isinstance(a, dict) and a.get("label") == label), None)
    if row is None:
        return _gate(contract.GATE_UNKNOWN, evidence=f"no agent_health.json row for label {label!r}",
                    probe=f"agent_health.json agents[].label == {label!r}")
    # review #10 caveat: an ALLOWLIST, not a denylist — PASS only on a status EXACTLY "OK" or
    # "HEALTHY"; anything else (a future status string this gate has never seen, included) FAILs.
    # A denylist of known-bad strings fails OPEN on any status it hasn't been told about yet.
    status = row.get("status")
    ok = status in ("OK", "HEALTHY")
    return _gate(contract.GATE_PASS if ok else contract.GATE_FAIL,
                evidence={"label": label, "status": status, "log_age_min": row.get("log_age_min")},
                probe=f"agent_health.json agents[].label == {label!r} -> status in (OK, HEALTHY) exactly")


def _offhost_anchor_gate() -> dict:
    return _gate(contract.GATE_FAIL, evidence="no off-host publication of the ledger head; local sibling dir "
                "does not count", probe="remote (origin) copy of the ledger head vs local — none published")


#: N1(b): a CLEAR reading that is itself stale is not trustworthy — same daily cadence as
def _kill_switch_gate(data_dir: Path, now: datetime) -> dict:
    """review N1(b): freshness is NOT just "state == CLEAR" — a stale kill_switch_status.json
    (sentinel stopped writing) must FAIL too, never be read as a standing CLEAR forever. Delegates
    to verify.freshness_check (the SHARED helper, landed this round — never a second,
    independently-reinvented age calculation that could silently disagree with verify.py's own)."""
    from spa_core.capital_shadow import verify as verify_mod
    cell = read_kill_switch_state(data_dir)
    value = cell.get("value")
    if value != "CLEAR":
        return _gate(contract.GATE_FAIL, evidence={"state": value, "reason": cell.get("reason")},
                    probe="kill_switch_status.json state == CLEAR")
    fresh = verify_mod.freshness_check(data_dir, "kill_switch_status.json", now)
    if not fresh["fresh"]:
        return _gate(contract.GATE_FAIL, evidence={"state": value, "age_hours": fresh["age_h"],
                    "reason": fresh["reason"]},
                    probe=f"kill_switch_status.json generated_at within {verify_mod.FRESHNESS_MAX_AGE_H}h")
    return _gate(contract.GATE_PASS, evidence={"state": value, "age_hours": fresh["age_h"]},
                probe=f"kill_switch_status.json state == CLEAR AND generated_at within "
                      f"{verify_mod.FRESHNESS_MAX_AGE_H}h")


def _owner_preconditions(data_dir: Path) -> dict:
    out = {}
    golive_doc, _ = _read_json(Path(data_dir) / "golive_status.json")
    go_state = observed(golive_doc, "go_live_state", kind=str) if golive_doc is not None else None
    if go_state is not None:
        out["golive_decision"] = {"state": contract.PRECONDITION_GRANTED if go_state == "GO" else
                                  contract.PRECONDITION_PENDING, "decision_ref": "golive_status.json:go_live_state"}
    else:
        ready = observed(golive_doc, "ready", kind=bool) if golive_doc is not None else None
        out["golive_decision"] = {"state": contract.PRECONDITION_GRANTED if ready is True else
                                  contract.PRECONDITION_PENDING, "decision_ref": "golive_status.json:ready"}

    gate_doc, _ = _read_json(Path(data_dir) / "live_trading_gate.json")
    active = observed(gate_doc, "active", kind=bool) if gate_doc is not None else None
    out["live_admission"] = {"state": contract.PRECONDITION_GRANTED if active is True else
                             contract.PRECONDITION_PENDING, "decision_ref": "live_trading_gate.json:active"}

    out["custody"] = {"state": contract.PRECONDITION_PENDING, "decision_ref": "no owner Safe configured"}
    out["pilot_amount"] = {"state": contract.PRECONDITION_PENDING, "decision_ref": "OWNER_DECISION_REQUIRED"}
    assert set(out.keys()) == set(contract.OWNER_PRECONDITIONS)
    return out


_GATE_BUILDERS = {
    "data_freshness": lambda dd, sid, now, le, sd: _data_freshness_gate(dd, sid, now),
    "strategy_evidence": lambda dd, sid, now, le, sd: _strategy_evidence_gate(sd, sid),
    "risk_evidence": lambda dd, sid, now, le, sd: _risk_evidence_gate(sid, dd),
    "protocol_evidence": lambda dd, sid, now, le, sd: _protocol_evidence_gate(dd, sid),
    "counterparty_evidence": lambda dd, sid, now, le, sd: _counterparty_evidence_gate(),
    "liquidity_evidence": lambda dd, sid, now, le, sd: _liquidity_evidence_gate(dd, sid),
    "mark_to_market_evidence": lambda dd, sid, now, le, sd: _mtm_gate(sd, sid),
    "reconciliation_readiness": lambda dd, sid, now, le, sd: _reconciliation_gate(dd, le, sid),
    "execution_simulation_readiness": lambda dd, sid, now, le, sd: _simulation_gate(dd, le, sid),
    "unwind_path": lambda dd, sid, now, le, sd: _unwind_gate(dd, le, sid),
    "incident_response_readiness": lambda dd, sid, now, le, sd: _incident_response_gate(dd),
    "observability_readiness": lambda dd, sid, now, le, sd: _observability_gate(dd, sid),
    "offhost_anchor": lambda dd, sid, now, le, sd: _offhost_anchor_gate(),
    "kill_switch_clear": lambda dd, sid, now, le, sd: _kill_switch_gate(dd, now),
}
assert set(_GATE_BUILDERS) == set(contract.SYSTEM_GATES)


def _evaluate_defi_sleeve(data_dir: Path, sleeve_id: str, now: datetime, ledger_entries: list,
                           sleeves_doc: dict) -> dict:
    system_checks = {name: builder(data_dir, sleeve_id, now, ledger_entries, sleeves_doc)
                     for name, builder in _GATE_BUILDERS.items()}
    owner_preconditions = _owner_preconditions(data_dir)

    chain = ledger.verify_chain(data_dir)
    from spa_core.capital_shadow import incidents as cs_incidents
    try:
        open_incidents = cs_incidents.open_incidents(data_dir)
        incidents_read_error = None
    except Exception as exc:
        # review #10: an incidents-READ failure is the WORST case, not the best one — it must
        # never be silently treated as "no open incidents" (`[]`). Unreadable incidents block.
        open_incidents = []
        incidents_read_error = repr(exc)
    kill_value = system_checks["kill_switch_clear"]["evidence"]
    # review round-3 L4: the REAL writer (spa_core/governance/kill_switch.py, ADR-531) publishes
    # state in {"TRIGGERED", "UNMEASURED", "CLEAR_PARTIAL", "CLEAR"} — it never writes "HARD_KILL"
    # or "ARMED" at all. The OLD allowlist-of-two only matched names the real writer never
    # produces, so a genuinely TRIGGERED kill-switch never tripped this INDEPENDENT hard-block
    # signal (the kill_switch_clear GATE itself still correctly FAILed on state != "CLEAR" — this
    # is a SEPARATE, harder signal that forces readiness_state straight to R_BLOCKED). Fail-closed
    # (inv. #2): ANY state other than exactly "CLEAR" is armed, including a missing/unmeasured
    # state (None) and the legacy triggered=true/false-derived fallback states
    # ("HARD_KILL"/"CLEAR_PARTIAL" respectively — both already != "CLEAR").
    kill_armed = isinstance(kill_value, dict) and kill_value.get("state") != "CLEAR"

    blocked = bool(open_incidents) or kill_armed or not chain.get("ok", False) or incidents_read_error is not None
    all_pass = set(system_checks) == set(contract.SYSTEM_GATES) and \
        all(g["state"] == contract.GATE_PASS for g in system_checks.values())
    shadow_pass = all(system_checks[g]["state"] == contract.GATE_PASS for g in contract.SHADOW_GATES)

    if blocked:
        readiness_state = contract.R_BLOCKED
    elif all_pass:
        readiness_state = contract.R_MANUAL_PILOT_READY
    elif shadow_pass:
        readiness_state = contract.R_SHADOW_READY
    else:
        readiness_state = contract.R_NOT_READY

    blocking_conditions = [{"gate": name, "state": g["state"], "reason": g["evidence"]}
                           for name, g in system_checks.items() if g["state"] != contract.GATE_PASS]
    if incidents_read_error is not None:
        blocking_conditions.append({"gate": "incidents", "state": "READ_ERROR", "reason": incidents_read_error})
    pending = sum(1 for p in owner_preconditions.values() if p["state"] != contract.PRECONDITION_GRANTED)
    unknowns = [{"gate": name, "reason": g["evidence"]} for name, g in system_checks.items()
               if g["state"] == contract.GATE_UNKNOWN]

    report = {
        "schema": contract.SCHEMA_READINESS,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate_sleeve": sleeve_id,
        "candidate_strategy": f"{sleeve_id}:default",
        "readiness_state": readiness_state,
        "readiness_display": contract.READINESS_DISPLAY.get(readiness_state, readiness_state),
        "execution_mode": contract.LAYER_MODE,
        "required_owner_action": f"Owner decisions pending: {pending}",
        "system_checks": system_checks,
        "owner_preconditions": owner_preconditions,
        "custody_readiness": owner_preconditions["custody"],
        "blocking_conditions": blocking_conditions,
        "warnings": [],
        "unknowns": unknowns,
        "evidence_refs": [_BOOK_FILE[sleeve_id], "risk_scores.json", "kill_switch_status.json",
                         "current_positions.json"],
        "trust_model": contract.TRUST_MODEL,
        "authorization": contract.AUTHORIZATION_TEXT,
    }
    for name in contract.SYSTEM_GATES:
        if name not in ("offhost_anchor", "kill_switch_clear"):
            report[name] = system_checks[name]
    assert set(report.keys()) == set(contract.READINESS_FIELDS), sorted(set(report) ^ set(contract.READINESS_FIELDS))
    return report


def _not_ready_report(sleeve_id: str, now: datetime, reason: str) -> dict:
    empty_gate = _gate(contract.GATE_UNKNOWN, evidence=reason, probe="not evaluated for this sleeve class")
    system_checks = {g: empty_gate for g in contract.SYSTEM_GATES}
    owner_preconditions = {p: {"state": contract.PRECONDITION_PENDING, "decision_ref": reason}
                           for p in contract.OWNER_PRECONDITIONS}
    report = {
        "schema": contract.SCHEMA_READINESS, "generated_at": now.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"), "candidate_sleeve": sleeve_id, "candidate_strategy": None,
        "readiness_state": contract.R_NOT_READY, "readiness_display": contract.R_NOT_READY,
        "execution_mode": contract.LAYER_MODE, "required_owner_action": "Owner decisions pending: 4",
        "system_checks": system_checks, "owner_preconditions": owner_preconditions,
        "custody_readiness": owner_preconditions["custody"], "blocking_conditions": [{"gate": "all", "state":
        contract.GATE_UNKNOWN, "reason": reason}], "warnings": [], "unknowns": [{"gate": "all", "reason": reason}],
        "evidence_refs": [], "trust_model": contract.TRUST_MODEL, "authorization": contract.AUTHORIZATION_TEXT,
    }
    for name in contract.SYSTEM_GATES:
        if name not in ("offhost_anchor", "kill_switch_clear"):
            report[name] = system_checks[name]
    assert set(report.keys()) == set(contract.READINESS_FIELDS)
    return report


#: the six ADR-554 sleeves — every one gets a report, even the ones that are never a pilot candidate
_ALL_SLEEVES = ("defi_conservative", "defi_balanced", "defi_aggressive", "cash", "trading_research",
               "market_neutral_basis")
#: ADR-560 binding #8: this key STAYS, unconditionally, for "market_neutral_basis" — the sleeve can
#: NEVER become a pilot candidate no matter what the research factory measures; the readiness
#: repair below only ever changes the REASON TEXT, never whether the gate fires. The literal string
#: here is the fail-closed FALLBACK used when the factory's basis-track read is unavailable/broken.
_NEVER_CANDIDATE = {
    "cash": "cash sleeve is not an execution candidate (no action type applies)",
    "trading_research": "no venue sandbox, no keys — observe-only (ADR-556 inherited blocker)",
    "market_neutral_basis": ("research/observe-only — never a pilot candidate (ADR-560); "
                             "basis track NOT_MEASURED (research factory has no status)"),
}


def _market_neutral_basis_reason(data_dir: Path, *, fallback: str) -> str:
    """ADR-560 binding #8: only the REASON TEXT is derived from the research factory's measured
    ``basis_track`` — the sleeve itself is NEVER a pilot candidate regardless of what the factory
    measures (the gate that fires is ``_NEVER_CANDIDATE`` membership, unconditional, in
    :func:`evaluate` below). A missing module, an unreadable/broken status, or a status without a
    ``basis_track`` all fall back to the same fail-closed literal, never a crash and never silence."""
    try:
        from spa_core.research_factory import read as rf_read
    except ImportError:
        return fallback
    try:
        status = rf_read.latest(Path(data_dir))
    except Exception:  # noqa: BLE001 — an unreadable factory status is the fallback, never a crash
        return fallback
    if not isinstance(status, dict) or status.get("integrity") == "BROKEN":
        return fallback
    basis_track = status.get("basis_track")
    if not isinstance(basis_track, dict) or not basis_track.get("state"):
        return fallback
    state = basis_track["state"]
    reason = basis_track.get("reason")
    tail = f"basis track {state}" + (f" — {reason}" if reason else "")
    return f"research/observe-only — never a pilot candidate (ADR-560); {tail}"


def venue_canary_section(ledger_entries: list) -> dict:
    """Diagnostic-only visibility into the TEST_SCENARIO machinery, kept entirely SEPARATE from
    every real sleeve's ``system_checks`` (review #3 HIGH). Never consulted by any gate above —
    this is purely "did the canary itself work", for a human/Mission Control to read."""
    from spa_core.capital_shadow.intent import CANARY_SLEEVE
    sims: dict = {}
    seq_sims: dict = {}
    for e in ledger_entries:
        if e.get("kind") != "simulation" or (e.get("payload") or {}).get("sleeve_id") != CANARY_SLEEVE:
            continue
        p = e["payload"]
        venue = p.get("venue")
        if venue not in seq_sims or e["seq"] > seq_sims[venue]:
            seq_sims[venue] = e["seq"]
            sims[venue] = {"result": p.get("result"), "block": p.get("block"), "intent_id": p.get("intent_id")}
    recs: dict = {}
    seq_recs: dict = {}
    for e in ledger_entries:
        if e.get("kind") != "reconciliation" or (e.get("payload") or {}).get("sleeve_id") != CANARY_SLEEVE:
            continue
        p = e["payload"]
        venue = p.get("venue")
        if venue not in seq_recs or e["seq"] > seq_recs[venue]:
            seq_recs[venue] = e["seq"]
            recs[venue] = {"outcome": p.get("outcome"), "old_block": p.get("old_block"),
                          "new_block": p.get("new_block"), "intent_id": p.get("intent_id")}
    return {"sleeve_id": CANARY_SLEEVE, "note": "diagnostic only — never consulted by any real sleeve's gates",
           "simulations": sims, "reconciliations": recs}


def evaluate(data_dir: Path, ledger_entries: list, now: datetime) -> dict:
    """Per-sleeve :data:`contract.READINESS_FIELDS` reports for all six ADR-554 sleeves — ONLY
    sleeves (review #5 MEDIUM finding N5): the diagnostic ``venue_canary`` section used to live
    inside this SAME dict, under a 7th, non-sleeve key, which broke every caller that assumed
    ``evaluate()``'s values are all sleeve reports (e.g. ``{k: v["readiness_state"] for k, v in
    evaluate(...).items()}`` raised on the venue_canary entry). It is still available — call
    :func:`venue_canary_section` directly (``read.latest()`` does, as its own separate top-level
    key) — just never mixed into this map. The exchange simulator never feeds a verdict here
    (review #12) — only on-chain simulation/unwind evidence does."""
    data_dir = Path(data_dir)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    from spa_core.investment_cio.sleeves import build_sleeves
    try:
        sleeves_doc = build_sleeves(data_dir, now)
    except Exception:
        sleeves_doc = {}

    out = {}
    for sleeve_id in _ALL_SLEEVES:
        if sleeve_id in _NEVER_CANDIDATE:
            reason = _NEVER_CANDIDATE[sleeve_id]
            if sleeve_id == "market_neutral_basis":
                reason = _market_neutral_basis_reason(data_dir, fallback=reason)
            out[sleeve_id] = _not_ready_report(sleeve_id, now, reason)
        else:
            out[sleeve_id] = _evaluate_defi_sleeve(data_dir, sleeve_id, now, ledger_entries, sleeves_doc)
    return out
