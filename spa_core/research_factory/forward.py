"""spa_core/research_factory/forward.py — WP-S06 forward paper factory (binding review #5/#11).

The counting rule (what makes a forward period COUNT toward maturity) lives in exactly ONE
place: ``contract.period_countable()``. This module never re-implements it — it builds
``prev_counted`` (the previous COUNTED observation, same shape, or ``None``) and the active
admission's ``as_of``, then asks the contract function and records its verdict (H1 rework).
The ONE exception (N1, post-implementation review 2026-10-04): ``contract.period_countable``
has no notion of lifecycle state at all, so a row recorded while the candidate's CURRENT state
is ``PAUSED_PAPER`` is forced ``counted=False`` here, before ever asking the contract function —
``run.py`` keeps recording observations for a paused candidate on purpose ("tracking only"), and
without this, those periods would count toward ``contract.MIN_FORWARD_PERIODS_CIO`` and a
re-ADMIT under the SAME admission would resume already mature.

The FIRST-recorded value for a ``(candidate_id, period)`` is frozen (the ledger's own keyed
idempotency: a later DIFFERENT value for the same key is written as a separate ``revision`` row
and never changes maturity or any earlier outcome). Three consecutive NOT-COUNTED periods — for
ANY reason, including a missing observation synthesised by ``run.py`` as NOT_MEASURED (H4) —
move the candidate to STALE. ``realised_return`` is computed ONLY from an independent
``realised_index`` series across consecutive COUNTED periods, compound-ANNUALISED over the real
elapsed time so it is comparable to ``base_return`` (M2); absent an independent series, it is
MODELLED and the eligibility consistency gate is UNKNOWN (which never passes).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract, lifecycle
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import DuplicateKey


def _observation_rows(ledger, candidate_id: str) -> list:
    out = [e for e in ledger.read_all() if e.get("kind") == "observation"
          and (e.get("payload") or {}).get("candidate_id") == candidate_id]
    out.sort(key=lambda e: ((e.get("payload") or {}).get("period") or "", e["seq"]))
    return out


def _voided_periods(ledger, candidate_id: str) -> set:
    return {(e.get("payload") or {}).get("period") for e in ledger.read_all()
            if e.get("kind") == "observation_void" and (e.get("payload") or {}).get("candidate_id") == candidate_id}


def counted_rows(data_dir: Path, candidate_id: str) -> list:
    ledger = ledger_for(data_dir)
    admission_id = lifecycle.active_admission_id(data_dir, candidate_id)
    rows = _observation_rows(ledger, candidate_id)
    voided = _voided_periods(ledger, candidate_id)
    return [r for r in rows if (r.get("payload") or {}).get("counted")
           and (r.get("payload") or {}).get("admission_id") == admission_id
           and (r.get("payload") or {}).get("period") not in voided]


def void_unconfirmed_periods(data_dir: Path, candidate_id: str, now: datetime, reason: str) -> list:
    """Tail of ADR-564 (N4; re-review M1): a run records a paper candidate's observation BEFORE Sherlock
    reviews it, so the period recorded in the run in which the evidence lapses was judged while the candidate
    was still active. When Sherlock pauses it, every counted period NOT YET CONFIRMED by a completed run — any
    observation recorded after the last ``run`` row, including one left by a run that crashed between
    recording and review — is voided by an APPENDED ``observation_void`` row (the observation itself is kept,
    never rewritten). Returns the voided periods."""
    ledger = ledger_for(data_dir)
    # second re-review: confirmation is LEDGER ORDER, not time — a run row written AFTER the observation
    # (a higher seq). A future-dated run row (a replay, `--now` in the future, clock skew) must never
    # pre-confirm every later observation.
    last_run_seq = max((e["seq"] for e in ledger.read_all() if e.get("kind") == "run"), default=None)
    at = iso(now)
    out = []
    for e in _observation_rows(ledger, candidate_id):
        payload = e.get("payload") or {}
        unconfirmed = last_run_seq is None or e["seq"] > last_run_seq
        if payload.get("counted") and unconfirmed:
            period = payload.get("period")
            ledger.append_idempotent("observation_void", ["observation_void", candidate_id, period],
                                     {"candidate_id": candidate_id, "period": period, "reason": reason,
                                      "observation_seq": e.get("seq")}, at)
            out.append(period)
    return out


def forward_periods(data_dir: Path, candidate_id: str) -> int:
    """Maturity = count of counted periods against the CURRENTLY active admission — a
    re-admission (a NEW active admission id) restarts this at 0 automatically, because a prior
    admission's counted rows no longer match the new active id."""
    return len(counted_rows(data_dir, candidate_id))


def record(data_dir: Path, candidate_id: str, obs: dict, now: datetime) -> dict:
    """``obs``: ``{"observed_return": cell, "realised_index": cell|None, "period": "YYYY-MM-DD",
    "backfill": bool}`` — exactly the per-candidate shape a scanner's ``observations`` dict
    carries (Appendix I). Counting is delegated ENTIRELY to ``contract.period_countable`` — no
    local re-implementation of the counting rule lives here (H1)."""
    ledger = ledger_for(data_dir)
    period = obs["period"]
    observed = obs.get("observed_return") or {}
    admission_id = lifecycle.active_admission_id(data_dir, candidate_id)
    admission_row = None
    if admission_id:
        for e in ledger.read_all():
            # ADR-564 binding #1: the live gate_ref is now a v2 "paper_admission_v2" snapshot id
            # (v1's "admission" kind can no longer be newly written at all — admission.py refuses
            # it — but its lookup is kept here too so a pre-ADR-564 ledger still replays).
            if e.get("kind") in ("admission", "paper_admission_v2") \
                    and (e.get("payload") or {}).get("admission_id") == admission_id:
                admission_row = e
                break
    at = iso(now)

    if admission_id is None or admission_row is None:
        payload = {"candidate_id": candidate_id, "period": period, "observed_return": observed,
                  "realised_index": obs.get("realised_index"), "backfill": bool(obs.get("backfill")),
                  "admission_id": None, "counted": False, "reason": "no active PASS admission"}
        key = ["observation", candidate_id, period]
        try:
            return ledger.append("observation", key, payload, at)
        except DuplicateKey as dup:
            return dup.existing

    admission_as_of = (admission_row.get("payload") or {}).get("as_of")
    prior_rows = counted_rows(data_dir, candidate_id)
    prev_counted = (prior_rows[-1].get("payload") or {}) if prior_rows else None

    # N1 (post-implementation review, 2026-10-04): run.py keeps calling record() for a
    # PAUSED_PAPER candidate on purpose ("marks continue as labelled tracking") — but
    # contract.period_countable has no notion of lifecycle state at all, so without this check a
    # paused candidate's observations counted toward contract.MIN_FORWARD_PERIODS_CIO exactly like
    # an active one, and a later re-ADMIT under the SAME admission resumed already mature. The
    # current state — never the admission's own state at write time — decides this: a period
    # recorded before the pause (while PAPER_ACTIVE/EVIDENCE_ACCUMULATING/CIO_ELIGIBLE) is
    # unaffected and keeps whatever contract.period_countable already decided for it.
    current_state = lifecycle.current_state(data_dir, candidate_id)
    if current_state == contract.PAUSED_PAPER:
        countable, reason = False, PAUSED_REASON
    else:
        countable, reason = contract.period_countable(obs, prev_counted, admission_as_of, now)

    counted = bool(countable)
    payload = {"candidate_id": candidate_id, "period": period, "observed_return": observed,
              "realised_index": obs.get("realised_index"), "backfill": bool(obs.get("backfill")),
              "admission_id": admission_id, "counted": counted, "reason": None if counted else reason}
    key = ["observation", candidate_id, period]
    try:
        entry = ledger.append("observation", key, payload, at)
    except DuplicateKey as dup:
        existing = dup.existing
        existing_payload = existing.get("payload") or {}
        if contract.canonical_json(existing_payload.get("observed_return")) == contract.canonical_json(observed):
            return existing  # identical re-submission — no-op, not a revision
        rev_payload = {"candidate_id": candidate_id, "period": period, "observed_return": observed,
                      "original_seq": existing.get("seq"), "note": "revision — never counted, never frozen over"}
        rev_key = ["revision", candidate_id, period, at]
        entry, _ = ledger.append_idempotent("revision", rev_key, rev_payload, at)
        _maybe_mark_stale(data_dir, candidate_id, now)
        return entry

    _maybe_mark_stale(data_dir, candidate_id, now)
    return entry


#: the reason a PAUSED_PAPER observation carries; such rows are tracking, neither a count nor a miss
PAUSED_REASON = "paused: tracking only, not counted toward maturity"


def _maybe_mark_stale(data_dir: Path, candidate_id: str, now: datetime) -> None:
    """H4: 3 consecutive NOT-COUNTED periods move a paper-state candidate to STALE — regardless
    of the SPECIFIC reason (a genuinely stale-at-recording period, a missing observation this
    run synthesised as NOT_MEASURED by run.py, or any other `period_countable` refusal). A
    not-counted period is, by construction, a period the factory could not confirm fresh
    evidence for — that is exactly what STALE means; narrowing this to one particular reason
    string left the "no observation at all" case (H4) outside the rule it was meant to feed."""
    ledger = ledger_for(data_dir)
    # second re-review N3: rows recorded while PAUSED_PAPER are tracking only — not a miss either;
    # counting them let a resumed position go STALE on its first honestly quiet day
    rows = [r for r in _observation_rows(ledger, candidate_id)
            if (r.get("payload") or {}).get("reason") != PAUSED_REASON]
    tail = rows[-contract.STALE_PERIODS_TO_STALE_STATE:]
    if len(tail) < contract.STALE_PERIODS_TO_STALE_STATE:
        return
    if all(not (r.get("payload") or {}).get("counted") for r in tail):
        state = lifecycle.current_state(data_dir, candidate_id)
        if state in contract.PAPER_STATES:
            lifecycle.transition(data_dir, candidate_id, contract.STALE_STATE,
                                reason=f"{contract.STALE_PERIODS_TO_STALE_STATE} consecutive not-counted periods",
                                now=now)


_SECONDS_PER_YEAR = 365.25 * 86400.0


def realised_return(data_dir: Path, candidate_id: str) -> tuple[str, dict]:
    """``(kind, cell)`` — ``kind`` is ``contract.RETURN_REALISED_PAPER`` when computed from an
    independent ``realised_index`` series across >=2 counted periods, else
    ``contract.RETURN_MODELLED`` with a ``NOT_MEASURED`` cell (never silently a number).

    M2: the raw share-price/index delta is a PERIOD fraction (e.g. 0.3% over three weeks), not
    an annual rate — comparing it directly against an APY-shaped ``base_return`` could never
    agree even when the two are perfectly consistent. The value returned here is ANNUALISED
    (compounded) over the real elapsed time between the first and last counted
    ``realised_index`` observation, so it is in the SAME unit as ``base_return``."""
    rows = counted_rows(data_dir, candidate_id)
    series: list[tuple] = []
    for r in rows:
        idx = (r.get("payload") or {}).get("realised_index") or {}
        v = contract.measured_value_of(idx)
        t = contract.parse_ts(idx.get("as_of"))
        if v is not None and t is not None:
            series.append((t, v))
    series.sort(key=lambda p: p[0])
    if len(series) < 2:
        return contract.RETURN_MODELLED, contract.cell(
            contract.NOT_MEASURED, reason="no independent realised_index series across >=2 counted periods")
    (t0, first), (t1, last) = series[0], series[-1]
    if first == 0:
        return contract.RETURN_MODELLED, contract.cell(contract.NOT_MEASURED, reason="realised_index first value is 0")
    span_s = (t1 - t0).total_seconds()
    if span_s <= 0:
        return contract.RETURN_MODELLED, contract.cell(
            contract.NOT_MEASURED, reason="realised_index series does not advance in time")
    growth = last / first
    years = span_s / _SECONDS_PER_YEAR
    if growth <= 0:
        return contract.RETURN_MODELLED, contract.cell(
            contract.NOT_MEASURED, reason="realised_index implies a non-positive growth factor")
    annualised = growth ** (1.0 / years) - 1.0
    return contract.RETURN_REALISED_PAPER, contract.cell(
        contract.ESTIMATED_WITH_METHOD, round(annualised, 10), unit="fraction",
        method=f"realised_index compound-annualised over {years:.6f}y across {len(series)} counted periods")
