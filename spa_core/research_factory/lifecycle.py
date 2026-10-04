"""spa_core/research_factory/lifecycle.py — the deterministic state machine of ``contract.TRANSITIONS``.

ADR-560 binding revision #1 ("no admission bypass"). Every transition is recorded as a
``transition`` ledger row; the CURRENT state of a candidate is always the ``to_state`` of its
latest transition row (never cached, never guessed).

Gate enforcement (``contract.GATED_TARGETS``):

* ``PAPER_ACTIVE`` / ``EVIDENCE_ACCUMULATING`` — ``gate_ref`` must be the ``admission_id`` of an
  existing, ``PASS`` admission snapshot for THIS candidate; ``EVIDENCE_ACCUMULATING`` additionally
  must reuse the SAME admission id that produced the candidate's ``PAPER_ACTIVE`` entry.
* ``CIO_ELIGIBLE`` — ``gate_ref`` must be a dict ``{"all_pass": True, "gates": {...}}`` naming a
  PASS verdict for every one of ``contract.CIO_ELIGIBILITY_GATES`` (eligibility.py is the only
  caller that is allowed to construct this honestly).
* ``SCREENED`` from a hold state — ``gate_ref`` must be a dict
  ``{"prev_digest": str, "new_digest": str}`` with the two digests DIFFERENT (the failed gate's
  input actually changed — no re-screen shopping).
* ``PAUSED_PAPER`` resumes ONLY to its own recorded ``paused_from`` state, through that state's
  gate exactly as above.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from spa_core.research_factory import contract
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import DuplicateKey, HashLedger


class InvalidTransition(Exception):
    """A transition the contract's TRANSITIONS graph (or a gate) refuses."""


def current_state(data_dir: Path, candidate_id: str) -> Optional[str]:
    return _current_state(ledger_for(data_dir), candidate_id)


def _current_state(ledger: HashLedger, candidate_id: str) -> Optional[str]:
    best = None
    for e in ledger.read_all():
        if e.get("kind") != "transition":
            continue
        payload = e.get("payload") or {}
        if payload.get("candidate_id") != candidate_id:
            continue
        if best is None or e["seq"] > best["seq"]:
            best = e
    return (best.get("payload") or {}).get("to_state") if best else None


def _latest_transition_row(ledger: HashLedger, candidate_id: str) -> Optional[dict]:
    best = None
    for e in ledger.read_all():
        if e.get("kind") != "transition":
            continue
        if (e.get("payload") or {}).get("candidate_id") != candidate_id:
            continue
        if best is None or e["seq"] > best["seq"]:
            best = e
    return best


def _last_transition_to(ledger: HashLedger, candidate_id: str, to_state: str) -> Optional[dict]:
    best = None
    for e in ledger.read_all():
        if e.get("kind") != "transition":
            continue
        p = e.get("payload") or {}
        if p.get("candidate_id") != candidate_id or p.get("to_state") != to_state:
            continue
        if best is None or e["seq"] > best["seq"]:
            best = e
    return best


def active_admission_id(data_dir: Path, candidate_id: str) -> Optional[str]:
    """The ``gate_ref`` (admission id) of the latest PAPER_ACTIVE entry still in force — i.e. the
    admission snapshot forward evidence must count against. ``None`` if the candidate never
    reached PAPER_ACTIVE, or was re-admitted after a reset (in which case the LATEST PAPER_ACTIVE
    row is still the right one — maturity-restart is enforced by forward.py counting only rows
    recorded at-or-after that row's ``at``)."""
    ledger = ledger_for(data_dir)
    row = _last_transition_to(ledger, candidate_id, contract.PAPER_ACTIVE)
    if row is None:
        return None
    gate_ref = (row.get("payload") or {}).get("gate_ref")
    return gate_ref if isinstance(gate_ref, str) else None


def _find_admission(ledger: HashLedger, candidate_id: str, admission_id: str) -> Optional[dict]:
    for e in ledger.read_all():
        if e.get("kind") != "admission":
            continue
        p = e.get("payload") or {}
        if p.get("candidate_id") == candidate_id and p.get("admission_id") == admission_id:
            return e
    return None


def _validate_admission_gate(ledger: HashLedger, candidate_id: str, gate_ref: Any) -> None:
    if not isinstance(gate_ref, str) or not gate_ref:
        raise InvalidTransition("gate_ref must name a PASS admission snapshot id")
    row = _find_admission(ledger, candidate_id, gate_ref)
    if row is None:
        raise InvalidTransition(f"no admission snapshot {gate_ref!r} recorded for {candidate_id!r}")
    if (row.get("payload") or {}).get("verdict") != contract.GATE_PASS:
        raise InvalidTransition(f"admission snapshot {gate_ref!r} is not a PASS verdict")


def _validate_cio_gate(gate_ref: Any) -> None:
    if not isinstance(gate_ref, dict) or gate_ref.get("all_pass") is not True:
        raise InvalidTransition("CIO_ELIGIBLE needs gate_ref={'all_pass': True, 'gates': {...}}")
    gates = gate_ref.get("gates")
    if not isinstance(gates, dict):
        raise InvalidTransition("CIO_ELIGIBLE gate_ref missing its per-gate verdicts")
    missing = [g for g in contract.CIO_ELIGIBILITY_GATES if gates.get(g) != contract.GATE_PASS]
    if missing:
        raise InvalidTransition(f"CIO eligibility gates not all PASS: {missing}")


def _validate_rescreen_gate(gate_ref: Any) -> None:
    if not isinstance(gate_ref, dict):
        raise InvalidTransition("re-screen from a hold needs gate_ref={'prev_digest','new_digest'}")
    prev, new = gate_ref.get("prev_digest"), gate_ref.get("new_digest")
    if not prev or not new or prev == new:
        raise InvalidTransition("re-screen from a hold requires the failed gate's input digest to "
                                "have CHANGED — no re-screen shopping")


def ensure_discovered(data_dir: Path, candidate_id: str, now: datetime) -> dict:
    """Idempotent: the FIRST time a candidate is seen it enters DISCOVERED; afterwards a no-op."""
    ledger = ledger_for(data_dir)
    if _current_state(ledger, candidate_id) is not None:
        return _latest_transition_row(ledger, candidate_id)
    return transition(data_dir, candidate_id, contract.DISCOVERED, reason="first sighting", now=now)


def transition(data_dir: Path, candidate_id: str, to_state: str, *, gate_ref: Any = None,
               reason: str, now: datetime) -> dict:
    if to_state not in contract.LIFECYCLE_STATES:
        raise InvalidTransition(f"unknown target state {to_state!r}")
    if not reason:
        raise InvalidTransition("a transition always names its reason")
    ledger = ledger_for(data_dir)
    with ledger.file_lock():
        frm = _current_state(ledger, candidate_id)

        if frm is None:
            if to_state != contract.DISCOVERED:
                raise InvalidTransition(f"{candidate_id}: the first transition must be to DISCOVERED, "
                                        f"got {to_state!r}")
        elif frm == to_state:
            return _latest_transition_row(ledger, candidate_id)  # idempotent no-op, never a duplicate row
        elif not contract.transition_allowed(frm, to_state):
            raise InvalidTransition(f"{candidate_id}: {frm} -> {to_state} is not in contract.TRANSITIONS")

        if to_state == contract.OBSERVE_ONLY:
            # only a candidate projected from another engine may be OBSERVE_ONLY (ADR-560 Appendix I)
            from spa_core.research_factory import registry as _registry
            snap = _registry.latest_snapshot(ledger, candidate_id)
            dom = None
            if isinstance(snap, dict) and isinstance(snap.get("payload"), dict):
                cand = snap["payload"].get("candidate")
                dom = cand.get("domain") if isinstance(cand, dict) else None
            if dom != "TRADING_RESEARCH":
                raise InvalidTransition(f"{candidate_id}: OBSERVE_ONLY is reserved for TRADING_RESEARCH "
                                        f"projections, candidate domain is {dom!r}")

        if frm == contract.PAUSED_PAPER and to_state in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING):
            paused_row = _last_transition_to(ledger, candidate_id, contract.PAUSED_PAPER)
            paused_from = (paused_row.get("payload") or {}).get("paused_from") if paused_row else None
            if to_state != paused_from:
                raise InvalidTransition(f"{candidate_id}: PAUSED_PAPER resumes only to its recorded "
                                        f"paused_from ({paused_from!r}), not {to_state!r}")

        gated_by = contract.GATED_TARGETS.get(to_state)
        if gated_by == "admission":
            _validate_admission_gate(ledger, candidate_id, gate_ref)
            if to_state == contract.EVIDENCE_ACCUMULATING:
                active = active_admission_id(data_dir, candidate_id)
                if active is not None and active != gate_ref:
                    raise InvalidTransition(f"{candidate_id}: EVIDENCE_ACCUMULATING must reuse the SAME "
                                            f"admission id as PAPER_ACTIVE ({active!r}), got {gate_ref!r}")
        elif gated_by == "cio_eligibility":
            _validate_cio_gate(gate_ref)
        elif gated_by == "rescreen_inputs_changed" and frm in contract.HOLD_STATES:
            _validate_rescreen_gate(gate_ref)

        payload: dict = {"candidate_id": candidate_id, "from_state": frm, "to_state": to_state,
                         "reason": reason, "gate_ref": gate_ref}
        if to_state == contract.PAUSED_PAPER:
            payload["paused_from"] = frm
        at = iso(now)
        key = ["transition", candidate_id, frm, to_state, at]
        try:
            # the lock is ALREADY held by this `with` block (one acquisition covers both the
            # state READ above and this WRITE) — ledger.append_locked() assumes exactly that,
            # never ledger.append() itself, which would try to re-acquire the same lock from a
            # freshly-opened fd and deadlock against itself.
            return ledger.append_locked("transition", key, payload, at)
        except DuplicateKey as dup:
            return dup.existing
