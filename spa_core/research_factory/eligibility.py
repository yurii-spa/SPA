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
from spa_core.research_factory import bundle as bundle_mod
from spa_core.research_factory import evidence_contract, registry_loader

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
    primary_field = admission._provenance_primary_field(candidate)
    observed = candidate.get(primary_field) or {}
    if kind != contract.RETURN_REALISED_PAPER:
        gates["realised_vs_observed_consistent"] = _gate(UNKNOWN, "realised_return is MODELLED, not independent")
    else:
        # ADR-564 amendment: the realised_index series and the observed primary return sharing an
        # origin (here: the SAME v1 source_root — the closest proxy available to a v1 cell, which
        # carries no v2 origin) make the "independent consistency" check circular. UNKNOWN, never
        # a numeric PASS, however close the two values land.
        rows = forward.counted_rows(data_dir, cid)
        idx_root = None
        for r in reversed(rows):
            idx = (r.get("payload") or {}).get("realised_index") or {}
            if idx.get("source_root"):
                idx_root = idx["source_root"]
                break
        observed_root = observed.get("source_root")
        if idx_root and observed_root and idx_root == observed_root:
            gates["realised_vs_observed_consistent"] = _gate(
                UNKNOWN, f"realised_index and {primary_field} share source_root {idx_root!r} — not independent")
        else:
            # M2: realised_cell is already ANNUALISED (forward.realised_return), but that alone is
            # not enough — the two cells must also be compared in the SAME DECLARED UNIT. A
            # perfectly consistent series (index growing at 4.5%/yr vs. base_return 4.5 "pct_apy")
            # used to fail with a spurious ~99% rel_diff because 4.5 (percent) was compared
            # directly against 0.045 (fraction). Convert BOTH to a bare fraction via `_as_fraction`
            # before comparing; an unknown unit on EITHER side is UNKNOWN, never guessed.
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

    # ADR-564 review #13 amendment to ADR-560's CIO_ELIGIBILITY_GATES: paper admission must never
    # quietly become CIO eligibility on issuer-only evidence or on a position SPA could not hold.
    # All four read the candidate's LATEST evidence bundle (evidence_contract.CIO_GATES_ADDED).
    evidence_bundle = bundle_mod.latest_bundle(data_dir, cid)
    if evidence_bundle is None:
        for gate_name in evidence_contract.CIO_GATES_ADDED + PENDING_CIO_AMENDMENT_GATES:
            gates[gate_name] = _gate(UNKNOWN, "no evidence bundle recorded for this candidate")
    else:
        # ADR-564 post-impl review M1: the six CIO_MIN_GRADE / MIN_GROUPS_CIO bars, now part of the
        # asserted tuple. Registry unreadable ⇒ {} ⇒ custody independence UNKNOWN (fail closed).
        try:
            origins_registry = registry_loader.load_origins()
        except registry_loader.OriginRegistryError:  # malformed registry is UNKNOWN, never PASS
            origins_registry = {}
        gates.update(pending_cio_amendment_gates(evidence_bundle, registry=origins_registry))
        need = evidence_contract.MIN_GROUPS_CIO.get("return", 2)
        have = evidence_bundle.get("independent_root_count", 0)
        gates["min_origins_cio"] = _gate(
            PASS if have >= need else FAIL, f"independent_root_count={have} need>={need}")

        bundle_mechanism = evidence_bundle.get("mechanism_id")
        if bundle_mechanism in contract.CREDIT_LIKE_MECHANISMS:
            cp_grade = (evidence_bundle.get("grades") or {}).get("COUNTERPARTY")
            gates["counterparty_grade_strong_for_credit_like"] = _gate(
                PASS if cp_grade == evidence_contract.STRONG else FAIL,
                f"{bundle_mechanism} is credit-like, COUNTERPARTY grade={cp_grade!r} (need STRONG)")
        else:
            gates["counterparty_grade_strong_for_credit_like"] = _gate(
                PASS, f"{bundle_mechanism} is not credit-like — bar does not apply")

        # post-implementation review M1 (2026-10-04): a bare state==SPA_ELIGIBLE assertion is
        # NOT "documented" — the GRADE (grades.grade_holder_eligibility) already requires a
        # RECORDED requirement (evidence_contract.ELIGIBILITY_REQUIREMENTS) behind that state;
        # reading the grade, not the raw state, is what actually enforces CIO_MIN_GRADE's
        # "HOLDER_ELIGIBILITY": ADEQUATE bar.
        holder_grade = (evidence_bundle.get("grades") or {}).get("HOLDER_ELIGIBILITY")
        gates["holder_eligibility_documented"] = _gate(
            PASS if evidence_contract.GRADE_ORDER.get(holder_grade, 0)
            >= evidence_contract.GRADE_ORDER[evidence_contract.CIO_MIN_GRADE["HOLDER_ELIGIBILITY"]] else FAIL,
            f"HOLDER_ELIGIBILITY grade={holder_grade!r} (need >= "
            f"{evidence_contract.CIO_MIN_GRADE['HOLDER_ELIGIBILITY']!r})")

        is_reference_track = evidence_bundle.get("paper_mode") == evidence_contract.PAPER_MODE_REFERENCE_TRACK
        gates["not_reference_track"] = _gate(
            FAIL if is_reference_track else PASS, f"paper_mode={evidence_bundle.get('paper_mode')!r}")

    assert set(gates) == set(contract.CIO_ELIGIBILITY_GATES)
    all_pass = all(g["verdict"] == PASS for g in gates.values())
    return {"candidate_id": cid, "gates": gates, "all_pass": all_pass}


#: post-implementation review M1 (2026-10-04): every ``evidence_contract.CIO_MIN_GRADE`` entry and
#: ``MIN_GROUPS_CIO`` reserves/custody group count not covered by an earlier gate. AMENDED into
#: ``contract.CIO_ELIGIBILITY_GATES`` (ADR-564 post-impl remediation) and evaluated by
#: :func:`evaluate` on every candidate with an evidence bundle; UNKNOWN without one.
PENDING_CIO_AMENDMENT_GATES = (
    "return_grade_strong_for_cio", "custody_grade_strong_for_cio", "reserves_grade_adequate_for_cio",
    "legal_grade_adequate_for_cio", "reserves_groups_sufficient_for_cio", "custody_groups_sufficient_for_cio",
)


def pending_cio_amendment_gates(evidence_bundle: dict, registry: Optional[dict] = None) -> dict:
    """The gates named in :data:`PENDING_CIO_AMENDMENT_GATES`, computed from ``evidence_bundle``
    exactly like :func:`evaluate`'s own CIO_GATES_ADDED block; evaluate() merges them into the asserted gate
    set. ``registry`` (optional) is needed for ``custody_groups_sufficient_for_cio`` (the
    custodian role's own citations, via ``evidence_contract.origin_groups``); omitted, that one
    gate reports UNKNOWN rather than guessing at independence with no registry to check against."""
    registry = registry or {}
    grades = evidence_bundle.get("grades") or {}
    gates = {}

    for dim, gate_name in (("RETURN", "return_grade_strong_for_cio"), ("CUSTODY", "custody_grade_strong_for_cio"),
                           ("RESERVES", "reserves_grade_adequate_for_cio"),
                           ("LEGAL", "legal_grade_adequate_for_cio")):
        grade = grades.get(dim)
        need = evidence_contract.CIO_MIN_GRADE[dim]
        if grade == evidence_contract.NOT_APPLICABLE:
            gates[gate_name] = _gate(PASS, f"{dim} is NOT_APPLICABLE for this mechanism")
        else:
            gates[gate_name] = _gate(
                PASS if evidence_contract.GRADE_ORDER.get(grade, 0) >= evidence_contract.GRADE_ORDER[need] else FAIL,
                f"{dim} grade={grade!r} (need >= {need!r})")

    # M1 (post-implementation review, 2026-10-04): a mechanism for which RESERVES/CUSTODY simply
    # does not apply (e.g. funding) has an empty reserves/custodian set by construction — the
    # GROUP-COUNT gate must not FAIL on that silence when the GRADE beside it already says
    # NOT_APPLICABLE for this mechanism; it must PASS with the same reason the grade gates use,
    # never block a candidate on a dimension it was never going to carry evidence for.
    reserves = evidence_bundle.get("reserves_evidence") or {}
    reserves_groups = {g for g in (reserves.get("auditor_group"), reserves.get("issuer_group")) if g}
    need_reserves = evidence_contract.MIN_GROUPS_CIO.get("reserves", 0)
    if grades.get("RESERVES") == evidence_contract.NOT_APPLICABLE:
        gates["reserves_groups_sufficient_for_cio"] = _gate(
            PASS, "RESERVES is NOT_APPLICABLE for this mechanism")
    else:
        gates["reserves_groups_sufficient_for_cio"] = _gate(
            PASS if len(reserves_groups) >= need_reserves else FAIL,
            f"reserves groups={sorted(reserves_groups)} need>={need_reserves}")

    custodian_entry = (evidence_bundle.get("custody_evidence") or {}).get("profile_entry") or {}
    custodian_citations = custodian_entry.get("citations") or []
    need_custody = evidence_contract.MIN_GROUPS_CIO.get("custody", 0)
    if grades.get("CUSTODY") == evidence_contract.NOT_APPLICABLE:
        gates["custody_groups_sufficient_for_cio"] = _gate(
            PASS, "CUSTODY is NOT_APPLICABLE for this mechanism")
    elif not registry:
        gates["custody_groups_sufficient_for_cio"] = _gate(
            UNKNOWN, "no registry supplied — custodian citation independence cannot be judged")
    else:
        custody_groups = evidence_contract.origin_groups(custodian_citations, registry)
        gates["custody_groups_sufficient_for_cio"] = _gate(
            PASS if len(custody_groups) >= need_custody else FAIL,
            f"custody groups={custody_groups} need>={need_custody}")

    assert set(gates) == set(PENDING_CIO_AMENDMENT_GATES)
    return gates


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
