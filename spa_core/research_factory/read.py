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


def _derive_latest(data_dir: Path, *, verdict: Optional[dict] = None) -> dict:
    ledger = ledger_for(data_dir)
    last_run = _last_run_row(ledger)
    # M5: generated_at is the last RUN's own recorded moment, never the wall clock — a status
    # read hours after the last run must still say WHEN the data is from, not "just now".
    generated_at = (last_run.get("payload") or {}).get("generated_at") or last_run.get("at") \
        if last_run else iso(datetime.now(timezone.utc))
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
            "admission_id": admission_id,
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

    return {
        "schema": contract.SCHEMA_STATUS, "generated_at": generated_at, "integrity": integrity,
        "ledger_head_hash": head, "authorization": contract.AUTHORIZATION_TEXT,
        "real_capital_usd": contract.REAL_CAPITAL_USD, "live_authorized": contract.LIVE_AUTHORIZED,
        "denominators": denominators, "by_state": by_state, "by_domain": by_domain,
        "by_mechanism": by_mechanism, "counterparty_unknown_count": counterparty_unknown_count,
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
