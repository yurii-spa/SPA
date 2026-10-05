"""spa_core/research_factory/read.py — the two read interfaces of Appendix I (A -> C).

N1/N2 rework. ``status.json`` is DISPLAY ONLY — neither function trusts a byte of its CONTENT
for anything that matters:

* ``latest()`` runs a full, FRESH ``ledger.verify()`` from disk on EVERY call, unconditionally.
  A cached ``status.json`` may still be served, but only for its non-integrity fields, and only
  AFTER that fresh verify came back OK — "milliseconds at this size" (N1) is the accepted cost;
  the earlier "head hash matches ⇒ trust the whole cached blob" shortcut let a tampered MIDDLE
  row (one that doesn't change the TAIL's own recorded hash) report OK forever.
* ``cio_view()`` derives ``observe_only``/``paper_active``/``cio_eligible`` (and the candidate
  list behind ``correlation_groups``) directly from the ledger's own transition rows, AFTER its
  own fresh ``verify()`` — never from ``status.json``'s cached candidate list, which is not
  hash-chained and can be forged independently of the ledger (N2).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract, counterparty, dedup, forward, lifecycle, registry
from spa_core.research_factory import bundle as bundle_mod
from spa_core.research_factory import decision as decision_mod
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory._common import iso, ledger_for


def _run_rows(ledger) -> list:
    return [e for e in ledger.read_all() if e.get("kind") == "run"]


def _last_run_row(ledger) -> Optional[dict]:
    rows = _run_rows(ledger)
    return rows[-1] if rows else None


def _latest_run_denominators(ledger) -> dict:
    last = _last_run_row(ledger)
    if last is None:
        return {"scanned": None, "discovered": None, "truncated": None}
    payload = last.get("payload") or {}
    return payload.get("denominators") or {"scanned": None, "discovered": None, "truncated": None}


def _rejection_reasons(ledger, candidate_id: str) -> list:
    out = []
    for e in ledger.read_all():
        if e.get("kind") != "transition":
            continue
        p = e.get("payload") or {}
        if p.get("candidate_id") == candidate_id and p.get("to_state") in contract.HOLD_STATES:
            out.append(p.get("reason"))
    return out


def latest(data_dir: Path) -> dict:
    """N8: always derived from the verified ledger (status.json is never read back). N1: ``ledger.verify()`` runs FRESH FROM DISK on every single call, unconditionally — see
    the module docstring. Only once that comes back OK may a cached ``status.json`` be served
    (and only when its recorded ``ledger_head_hash`` still matches the JUST-VERIFIED live head);
    a BROKEN verdict always falls through to :func:`_derive_latest`, which reports it honestly."""
    ledger = ledger_for(data_dir)
    verdict = ledger.verify()  # HashLedger.verify() itself never trusts the cache either (N3)
    # N8 (second review): status.json is NEVER served back — its content is not bound to the ledger, so a
    # hand-edited file reached Mission Control and the readiness reason. Every read derives from the
    # verified ledger; status.json is a written artifact for humans only.
    return _derive_latest(data_dir, verdict=verdict)


def _position_for(data_dir: Path, candidate_id: str) -> Optional[dict]:
    """The latest paper position NAV view for this candidate, or ``None`` (no position opened,
    or Package E2's ``paper.py`` is not importable — tolerated, never a crash)."""
    try:
        from spa_core.research_factory import paper
    except ImportError:
        return None
    try:
        views = [v for v in paper.positions(data_dir) if v.get("candidate_id") == candidate_id]
    except Exception:  # noqa: BLE001 — a read model never crashes the caller over a paper.py defect
        return None
    return views[-1] if views else None


def _evidence_block_for(data_dir: Path, candidate_id: str, candidate: dict) -> dict:
    """Appendix I's per-candidate ``evidence`` block, derived from the candidate's LATEST
    recorded evidence bundle (never from ``status.json``)."""
    b = bundle_mod.latest_bundle(data_dir, candidate_id)
    who_pays = (contract.MECHANISMS.get(candidate.get("mechanism_id")) or {}).get("who_pays")
    if b is None:
        return {"grades": {}, "evidence_ceiling": None, "issuer_asserted_roles": [],
               "circularity_concerns": [], "who_pays": who_pays, "counterparties": {},
               "measured": [], "documented": [], "unknown": [], "blocking_gaps": [],
               "paper_mode": None, "latest_decision": None,
               "paper_position": _position_for(data_dir, candidate_id)}
    grades = b.get("grades") or {}
    counterparties = {role: {"state": (entry or {}).get("state"), "identity": (entry or {}).get("identity")}
                      for role, entry in (b.get("counterparty_evidence") or {}).items()}
    latest_decision = decision_mod.latest_decision(data_dir, candidate_id)
    latest_decision_view = None
    if latest_decision is not None:
        latest_decision_view = {
            "decision_id": latest_decision.get("decision_id"), "decision": latest_decision.get("decision"),
            "generated_at": latest_decision.get("generated_at"),
            "failed_gates": latest_decision.get("failed_gates"),
            # ADR-564 Round 5 ("also"): a decision can block on UNKNOWN gates alone (e.g. OUSG's
            # NEEDS_MORE_EVIDENCE with failed_gates=[]) — surfacing only failed_gates then reads as
            # "no reason". The decision payload's own "unknowns" (ec.GATE_UNKNOWN gates ∪ UNKNOWN
            # dimensions, decision.decide()'s own field) is exactly that missing reason.
            "unknown_gates": latest_decision.get("unknowns"),
            "required_next_evidence": latest_decision.get("required_next_evidence"),
            "rationale": latest_decision.get("rationale"),
        }
    return {
        "grades": grades, "evidence_ceiling": b.get("evidence_ceiling"),
        "issuer_asserted_roles": b.get("issuer_asserted_roles") or [],
        "circularity_concerns": b.get("circularity_concerns") or [], "who_pays": who_pays,
        "counterparties": counterparties,
        "measured": sorted(d for d, g in grades.items() if g in (ec.ADEQUATE, ec.STRONG)),
        "documented": sorted(d for d, g in grades.items() if g == ec.WEAK),
        "unknown": sorted(d for d, g in grades.items() if g in (ec.UNKNOWN, ec.STALE, ec.CONFLICTED)),
        "blocking_gaps": b.get("blocking_gaps") or [], "paper_mode": b.get("paper_mode"),
        "latest_decision": latest_decision_view, "paper_position": _position_for(data_dir, candidate_id),
    }


def _sherlock_block(data_dir: Path, ledger, run_now: datetime, denom_counts: dict) -> dict:
    """Appendix I's ``sherlock`` read-model block — the Research Universe card's "Sherlock — Head
    of Research" row. Derived from the verified ledger's ``evidence_bundle``/``admission_decision``
    rows, never from ``status.json``."""
    today = run_now.date()
    decision_rows = [e for e in ledger.read_all() if e.get("kind") == "admission_decision"]
    latest_by_candidate: dict = {}
    for e in decision_rows:
        p = e.get("payload") or {}
        cid = p.get("candidate_id")
        if cid and (cid not in latest_by_candidate or e["seq"] > latest_by_candidate[cid]["seq"]):
            latest_by_candidate[cid] = e

    reviewed_today = any(contract.parse_ts(e.get("payload", {}).get("generated_at")) is not None
                        and contract.parse_ts(e["payload"]["generated_at"]).date() == today
                        for e in decision_rows)

    evidence_ready = conflicted = stale = counterparty_unknown = 0
    blocker_counts: dict = {}
    decisions_today = []
    for cid, e in latest_by_candidate.items():
        p = e.get("payload") or {}
        bundle_digest = p.get("bundle_digest")
        bundle = bundle_mod.find_bundle(data_dir, cid, bundle_digest) if bundle_digest else None
        if bundle is not None:
            if not bundle.get("blocking_gaps"):
                evidence_ready += 1
            if bundle.get("conflicts"):
                conflicted += 1
            if bundle.get("stale_evidence"):
                stale += 1
            if (bundle.get("grades") or {}).get("COUNTERPARTY") == ec.UNKNOWN:
                counterparty_unknown += 1
        # an UNKNOWN gate blocks admission exactly like a FAIL one — counting only FAILs under-reported the
        # blockers of candidates held purely by unknowns (live run: OUSG showed no reason at all)
        unknown_gate_names = [g for g in (p.get("unknowns") or []) if g in ec.ADMISSION_V2_GATES]
        for gate in list(p.get("failed_gates") or []) + unknown_gate_names:
            blocker_counts[gate] = blocker_counts.get(gate, 0) + 1

        gen_at = contract.parse_ts(p.get("generated_at"))
        if gen_at is not None and gen_at.date() == today:
            candidate = registry.current_candidate(data_dir, cid) or {}
            decisions_today.append({
                "candidate_id": cid, "instrument": candidate.get("instrument"),
                "decision": p.get("decision"), "failed_gates": p.get("failed_gates"),
                # see _evidence_block_for's matching comment: a decision may block on UNKNOWN
                # gates alone, and failed_gates=[] must never read as "no reason".
                "unknown_gates": p.get("unknowns"),
                "required_next_evidence": p.get("required_next_evidence"),
                "evidence_ceiling": p.get("evidence_ceiling"), "paper_mode": p.get("paper_mode"),
                "rationale": p.get("rationale"),
            })

    top_blockers = sorted(({"gate": g, "count": n} for g, n in blocker_counts.items()),
                          key=lambda row: (-row["count"], row["gate"]))[:5]

    return {
        "role_id": ec.ROLE_ID, "display_name": ec.ROLE_DISPLAY_NAME, "reviewed_today": reviewed_today,
        "evidence_ready": evidence_ready, "paper_active": denom_counts["paper_active"],
        "cio_eligible": denom_counts["cio_eligible"], "counterparty_unknown": counterparty_unknown,
        "conflicts": conflicted, "stale_evidence": stale, "top_blockers": top_blockers,
        "decisions_today": decisions_today,
    }


def _derive_latest(data_dir: Path, *, verdict: Optional[dict] = None) -> dict:
    ledger = ledger_for(data_dir)
    last_run = _last_run_row(ledger)
    # M5: generated_at is the last RUN's own recorded moment, never the wall clock — a status
    # read hours after the last run must still say WHEN the data is from, not "just now".
    if last_run:
        generated_at = (last_run.get("payload") or {}).get("generated_at") or last_run.get("at")
    else:
        # tail of ADR-564 (found when the calendar turned 04.10 → 05.10): with no run row the reader fell
        # back to the WALL CLOCK, so "today's decisions" emptied at midnight. The ledger's own newest entry
        # is the moment the data is from; the wall clock is used only for an empty ledger.
        entries = ledger.read_all()
        generated_at = (entries[-1].get("at") if entries else None) or iso(datetime.now(timezone.utc))
    # M5 leftover: every OTHER freshness judgement below (stale_feeds, basis_track) is also
    # judged against the RUN's own time, never the wall clock at read time.
    run_now = contract.parse_ts(generated_at) or datetime.now(timezone.utc)
    verdict = verdict if verdict is not None else ledger.verify()  # N1: always fresh (see latest())
    integrity = "OK" if verdict["ok"] else "BROKEN"
    head = ledger.head_hash()

    by_state: dict = {}
    by_domain: dict = {}
    by_mechanism: dict = {}
    counterparty_unknown_count = 0
    candidates_out = []
    rejections = []
    denom_counts = {k: 0 for k in ("rejected", "disappeared", "paper_active", "cio_eligible", "observe_only")}

    for cid in registry.all_candidate_ids(ledger):
        candidate = registry.current_candidate(data_dir, cid) or {}
        state = lifecycle.current_state(data_dir, cid)
        by_state[state] = by_state.get(state, 0) + 1
        domain = candidate.get("domain")
        if domain:
            by_domain[domain] = by_domain.get(domain, 0) + 1
        mech = candidate.get("mechanism_id")
        if mech:
            by_mechanism[mech] = by_mechanism.get(mech, 0) + 1

        cp_summary = counterparty.summarize(candidate)
        if cp_summary["roles_unknown"]:
            counterparty_unknown_count += 1

        if state in contract.HOLD_STATES:
            if state == contract.REJECTED:
                denom_counts["rejected"] += 1
            if state == contract.DISAPPEARED:
                denom_counts["disappeared"] += 1
            rejections.append({"candidate_id": cid, "state": state, "reasons": _rejection_reasons(ledger, cid)})
        if state in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING):
            # LOW: EVIDENCE_ACCUMULATING is still an actively-tracked paper candidate (it is
            # PAPER_ACTIVE plus counted evidence, not a different thing) — it belongs in the
            # SAME "paper" bucket, not invisible between PAPER_ACTIVE and CIO_ELIGIBLE.
            denom_counts["paper_active"] += 1
        if state == contract.CIO_ELIGIBLE:
            denom_counts["cio_eligible"] += 1
        if state == contract.OBSERVE_ONLY:
            denom_counts["observe_only"] += 1

        admission_id = lifecycle.active_admission_id(data_dir, cid)
        periods = forward.forward_periods(data_dir, cid)
        candidates_out.append({
            "candidate_id": cid, "exposure_key": candidate.get("exposure_key"), "domain": domain,
            "mechanism_id": mech, "instrument": candidate.get("instrument"),
            "venue_or_protocol": candidate.get("venue_or_protocol"), "network": candidate.get("network"),
            "admission_state": state, "economic_driver_key": candidate.get("economic_driver_key"),
            "yield_source": candidate.get("yield_source"), "base_return": candidate.get("base_return"),
            "net_expected_return": contract.net_expected_return(candidate),
            "evidence_maturity": {"forward_periods": periods, "required": contract.MIN_FORWARD_PERIODS_CIO},
            "counterparty_summary": cp_summary, "reasons": _rejection_reasons(ledger, cid),
            "admission_id": admission_id, "evidence": _evidence_block_for(data_dir, cid, candidate),
        })

    run_denom = _latest_run_denominators(ledger)
    denominators = {
        "scanned": run_denom.get("scanned"), "discovered": sum(by_state.values()),
        "truncated": run_denom.get("truncated"), "rejected": denom_counts["rejected"],
        "disappeared": denom_counts["disappeared"], "paper_active": denom_counts["paper_active"],
        "cio_eligible": denom_counts["cio_eligible"], "observe_only": denom_counts["observe_only"],
    }
    assert set(denominators) == set(contract.STATUS_DENOMINATORS)

    stale_feeds = []
    for cid in registry.all_candidate_ids(ledger):
        candidate = registry.current_candidate(data_dir, cid) or {}
        br = candidate.get("base_return") or {}
        if br.get("state") in contract.VALUED_STATES and contract.is_fresh(br, run_now) is False:
            t = contract.parse_ts(br.get("as_of"))
            age_h = ((run_now - t).total_seconds() / 3600.0) if t else None
            stale_feeds.append({"source_root": br.get("source_root"), "age_h": age_h})

    basis_track = {"state": "NOT_MEASURED", "funding_as_of": None, "reason": "no FUNDING_CAPTURE candidate recorded"}
    for cid in registry.all_candidate_ids(ledger):
        candidate = registry.current_candidate(data_dir, cid) or {}
        if candidate.get("mechanism_id") == "FUNDING_CAPTURE":
            funding = candidate.get("funding") or {}
            fresh = contract.is_fresh(funding, run_now)
            basis_track = {
                "state": "MEASURED" if fresh else ("STALE" if fresh is False else "NOT_MEASURED"),
                "funding_as_of": funding.get("as_of"),
                "reason": "live funding cell" if fresh else "funding cell stale or unjudgeable",
            }
            break

    sherlock = _sherlock_block(data_dir, ledger, run_now, denom_counts)

    return {
        "schema": contract.SCHEMA_STATUS, "generated_at": generated_at, "integrity": integrity,
        "ledger_head_hash": head, "authorization": contract.AUTHORIZATION_TEXT,
        "real_capital_usd": contract.REAL_CAPITAL_USD, "live_authorized": contract.LIVE_AUTHORIZED,
        "denominators": denominators, "by_state": by_state, "by_domain": by_domain,
        "by_mechanism": by_mechanism, "counterparty_unknown_count": counterparty_unknown_count,
        "sherlock": sherlock,
        "stale_feeds": stale_feeds, "candidates": candidates_out, "rejections": rejections,
        "domain_decisions": contract.DOMAIN_DECISIONS, "basis_track": basis_track,
    }


def _status_path(data_dir: Path) -> Path:
    return ledger_for(data_dir).root() / contract.STATUS


def cio_view(data_dir: Path, now: datetime) -> dict:
    """N2: ``observe_only``/``paper_active``/``cio_eligible`` are derived DIRECTLY from the
    ledger's own transition rows, after a fresh ``verify()`` — NEVER from ``status.json``'s
    candidate list, which carries no hash chain of its own and can be forged independently of
    the ledger it is supposed to describe. ``status.json`` is consulted for exactly one thing:
    "has there been a run recently enough" — and even that now comes from the ledger's own
    ``run`` rows, not the file; ``status.json`` ends up display-only, read by nothing here."""
    ledger = ledger_for(data_dir)
    verdict = ledger.verify()
    if not verdict["ok"]:
        return {"state": "BROKEN", "reason": verdict.get("reason"), "observe_only": [], "paper_active": [],
               "cio_eligible": [], "correlation_groups": {}, "ledger_head_hash": None}

    live_head = ledger.head_hash()
    last_run = _last_run_row(ledger)
    if last_run is None:
        return {"state": "NOT_MEASURED", "reason": "no run recorded in the ledger yet", "observe_only": [],
               "paper_active": [], "cio_eligible": [], "correlation_groups": {}, "ledger_head_hash": live_head}

    generated_at_str = (last_run.get("payload") or {}).get("generated_at") or last_run.get("at")
    generated_at = contract.parse_ts(generated_at_str)
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_h = (now_aware - generated_at).total_seconds() / 3600.0 if generated_at else None
    fresh_enough = age_h is not None and age_h <= contract.CIO_READ_MODEL_MAX_AGE_H

    observe_only, paper_active, cio_eligible_all = [], [], []
    all_candidates: dict = {}
    for cid in registry.all_candidate_ids(ledger):
        state = lifecycle.current_state(data_dir, cid)
        if state == contract.OBSERVE_ONLY:
            observe_only.append(cid)
        elif state in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING):
            paper_active.append(cid)
        elif state == contract.CIO_ELIGIBLE:
            cio_eligible_all.append(cid)
        all_candidates[cid] = registry.current_candidate(data_dir, cid) or {}
    # the 26h recency gate (contract review #11/#14) applies ONLY to cio_eligible — a stale run
    # must never let the CIO believe a candidate is allocatable off old evidence.
    cio_eligible = cio_eligible_all if fresh_enough else []

    groups = dedup.correlation_groups(list(all_candidates.values()))

    if fresh_enough:
        reason, state = "ok", "OK"
    else:
        reason, state = "no run in the ledger within the last 26h", "STALE"
    return {"state": state, "reason": reason, "observe_only": observe_only, "paper_active": paper_active,
           "cio_eligible": cio_eligible, "correlation_groups": groups, "ledger_head_hash": live_head}
