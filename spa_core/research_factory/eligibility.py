"""spa_core/research_factory/eligibility.py — contract.CIO_ELIGIBILITY_GATES, re-checked every run.

ADR-560 binding review #9/#11/#5. Promotion EVIDENCE_ACCUMULATING -> CIO_ELIGIBLE happens only
when EVERY gate is PASS; a later failure of ANY gate on a re-check demotes CIO_ELIGIBLE straight
back to EVIDENCE_ACCUMULATING (never UNKNOWN passes, ever).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from spa_core.research_factory import admission, contract, counterparty, dedup, forward, lifecycle

PASS, FAIL, UNKNOWN = contract.GATE_PASS, contract.GATE_FAIL, contract.GATE_UNKNOWN


def _gate(verdict: str, evidence: str) -> dict:
    return {"verdict": verdict, "evidence": evidence}


#: M2: the ONE declared unit every return cell is converted to before any comparison — a bare
#: fraction (0.045 == 4.5%). ``unit=None`` is treated as already a fraction (the overwhelming
#: majority of cells in this package never set `unit` at all). A unit NOT in this map is
#: UNKNOWN — never guessed, never silently treated as a fraction.
#: a unit-less value is NOT assumed to be a fraction (it could be a percent) — unknown ⇒ UNKNOWN
_UNIT_TO_FRACTION = {"fraction": 1.0, "pct_apy": 1.0 / 100.0, "pct_apy_annualised": 1.0 / 100.0}


def _as_fraction(cell_: dict) -> Optional[float]:
    """The cell's value converted to a bare fraction, or ``None`` when the value is missing OR
    the unit is not one this function knows how to convert (an unknown unit must never be
    silently treated as already-a-fraction)."""
    v = contract.value_of(cell_)
    if v is None:
        return None
    unit = cell_.get("unit")
    if unit not in _UNIT_TO_FRACTION:
        return None
    return v * _UNIT_TO_FRACTION[unit]


def evaluate(data_dir: Path, candidate: dict, registry_view: dict, now: datetime) -> dict:
    cid = candidate["candidate_id"]
    gates = {}

    periods = forward.forward_periods(data_dir, cid)
    gates["forward_periods"] = _gate(
        PASS if periods >= contract.MIN_FORWARD_PERIODS_CIO else FAIL,
        f"{periods} of {contract.MIN_FORWARD_PERIODS_CIO} required counted periods")

    admission_id = lifecycle.active_admission_id(data_dir, cid)
    gates["admission_still_valid"] = _gate(PASS if admission_id else FAIL,
                                          f"active admission id: {admission_id!r}")

    rows = forward.counted_rows(data_dir, cid)
    if not rows:
        gates["data_fresh"] = _gate(UNKNOWN, "no counted period to judge freshness from")
    else:
        latest = rows[-1]
        fresh = contract.is_fresh((latest.get("payload") or {}).get("observed_return"), now)
        gates["data_fresh"] = _gate(PASS if fresh else FAIL, f"latest counted period fresh={fresh}")

    cp_summary = counterparty.summarize(candidate)
    gates["counterparty_no_unknown_role"] = _gate(
        PASS if not cp_summary["roles_unknown"] and not cp_summary["required_roles_missing"] else FAIL,
        f"roles_unknown={cp_summary['roles_unknown']} required_missing={cp_summary['required_roles_missing']}")

    bar_ok, bar_reason = counterparty.credit_bar_passes(candidate)
    gates["counterparty_credit_bar"] = _gate(PASS if bar_ok else FAIL, bar_reason)

    others = [v for k, v in registry_view.items() if k != "_existing_book_roots"]
    book_roots = registry_view.get("_existing_book_roots") or []
    dd_verdict, dd_reason = dedup.no_duplicate_exposure(candidate, others, book_roots)
    gates["no_duplicate_exposure"] = _gate(dd_verdict, dd_reason)

    kind, realised_cell = forward.realised_return(data_dir, cid)
    if kind != contract.RETURN_REALISED_PAPER:
        gates["realised_vs_observed_consistent"] = _gate(UNKNOWN, "realised_return is MODELLED, not independent")
    else:
        # M2: realised_cell is already ANNUALISED (forward.realised_return), but that alone is
        # not enough — the two cells must also be compared in the SAME DECLARED UNIT. A
        # perfectly consistent series (index growing at 4.5%/yr vs. base_return 4.5 "pct_apy")
        # used to fail with a spurious ~99% rel_diff because 4.5 (percent) was compared
        # directly against 0.045 (fraction). Convert BOTH to a bare fraction via `_as_fraction`
        # before comparing; an unknown unit on EITHER side is UNKNOWN, never guessed.
        primary_field = admission._provenance_primary_field(candidate)
        observed = candidate.get(primary_field) or {}
        observed_frac = _as_fraction(observed)
        realised_frac = _as_fraction(realised_cell)
        if observed_frac is None or realised_frac is None:
            unknown_unit = (contract.value_of(observed) is not None and observed_frac is None) or \
                (contract.value_of(realised_cell) is not None and realised_frac is None)
            reason = ("unit not convertible to a fraction" if unknown_unit else "missing value to compare")
            gates["realised_vs_observed_consistent"] = _gate(UNKNOWN, reason)
        else:
            denom = max(abs(observed_frac), abs(realised_frac), 1e-12)
            rel = abs(observed_frac - realised_frac) / denom
            gates["realised_vs_observed_consistent"] = _gate(
                PASS if rel <= contract.CONFLICT_TOLERANCE_REL else FAIL,
                f"{primary_field}(fraction)={observed_frac} realised(annualised,fraction)={realised_frac} "
                f"rel_diff={rel:.2%}")

    assert set(gates) == set(contract.CIO_ELIGIBILITY_GATES)
    all_pass = all(g["verdict"] == PASS for g in gates.values())
    return {"candidate_id": cid, "gates": gates, "all_pass": all_pass}


def recheck_and_apply(data_dir: Path, candidate: dict, registry_view: dict, now: datetime) -> dict:
    """Runs :func:`evaluate` and applies the lifecycle consequence: promote
    EVIDENCE_ACCUMULATING -> CIO_ELIGIBLE on an all-PASS report, or demote CIO_ELIGIBLE back to
    EVIDENCE_ACCUMULATING the instant any gate fails/unknowns."""
    cid = candidate["candidate_id"]
    report = evaluate(data_dir, candidate, registry_view, now)
    state = lifecycle.current_state(data_dir, cid)
    if report["all_pass"] and state == contract.EVIDENCE_ACCUMULATING:
        lifecycle.transition(data_dir, cid, contract.CIO_ELIGIBLE,
                             gate_ref={"all_pass": True, "gates": {g: v["verdict"] for g, v in report["gates"].items()}},
                             reason="all CIO eligibility gates PASS", now=now)
    elif not report["all_pass"] and state == contract.CIO_ELIGIBLE:
        admission_id = lifecycle.active_admission_id(data_dir, cid)
        failed = [g for g, v in report["gates"].items() if v["verdict"] != PASS]
        lifecycle.transition(data_dir, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id,
                             reason=f"CIO eligibility gate(s) failed on re-check: {failed}", now=now)
    return report
