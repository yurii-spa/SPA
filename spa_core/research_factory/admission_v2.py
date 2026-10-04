"""spa_core/research_factory/admission_v2.py — the 20 ADMISSION_V2_GATES (ADR-564 review #1/#7).

Each gate reads ONLY the inputs ``evidence_contract.GATE_INPUTS`` declares for it (named in each
function's docstring below). NOT_APPLICABLE only where ``evidence_contract.GATE_NA`` names the
mechanism; everywhere else a gate is PASS/FAIL/UNKNOWN and UNKNOWN never passes.

(The earlier ``GATE_NA`` name collision — the verdict string shadowed by the mechanism-exemption
dict — is fixed in the frozen contract: the verdict is ``evidence_contract.GATE_NA_VERDICT``,
``GATE_NA`` is only ever the dict now.)

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec

PASS, FAIL, GATE_UNKNOWN = ec.PASS, ec.FAIL, ec.GATE_UNKNOWN
_NA_VERDICT = ec.GATE_NA_VERDICT

SCHEMA_REPORT_V2 = "paper-admission-report/2"


def _gate(verdict: str, evidence: str) -> dict:
    return {"verdict": verdict, "evidence": evidence}


def _na_for(gate: str, mechanism_id: str) -> bool:
    return mechanism_id in ec.GATE_NA.get(gate, ())


def _grade_gate(dim: str, grade: str, *, ok=(ec.ADEQUATE, ec.STRONG)) -> dict:
    if grade == ec.NOT_APPLICABLE:
        return _gate(_NA_VERDICT, f"{dim} is NOT_APPLICABLE for this mechanism")
    if grade in ok:
        return _gate(PASS, f"{dim} grade={grade}")
    if grade == ec.UNKNOWN:
        return _gate(GATE_UNKNOWN, f"{dim} grade is UNKNOWN")
    return _gate(FAIL, f"{dim} grade={grade} does not clear the bar")


# ── gates ─────────────────────────────────────────────────────────────────────────────────────
def _identity_verified(bundle, candidate, extra, now):
    """GATE_INPUTS: ("PRIMARY_IDENTITY",)."""
    return _grade_gate("PRIMARY_IDENTITY", bundle["grades"]["PRIMARY_IDENTITY"])


def _mechanism_understood(bundle, candidate, extra, now):
    """GATE_INPUTS: ("mechanism_id",)."""
    mech = candidate.get("mechanism_id")
    return _gate(PASS, f"mechanism {mech!r} recognised") if mech in c1.MECHANISMS \
        else _gate(FAIL, f"mechanism_id {mech!r} is not in contract.MECHANISMS")


def _return_source_verified(bundle, candidate, extra, now):
    """GATE_INPUTS: ("RETURN",)."""
    return _grade_gate("RETURN", bundle["grades"]["RETURN"])


def _net_return_computable(bundle, candidate, extra, now):
    """GATE_INPUTS: ("COST", "RETURN", "net_expected_return"). ``net_expected_return`` lives on
    ``return_evidence`` (this package's own admission concern) — ``paper_accounting_evidence`` is
    E2's frozen shape (``evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS``) and carries no such
    key."""
    net = bundle["return_evidence"]["net_expected_return"]
    state = net.get("state")
    if state in c1.VALUED_STATES:
        return _gate(PASS, f"net_expected_return={state}")
    if state == c1.NOT_MEASURED:
        return _gate(FAIL, net.get("reason") or "net_expected_return not computable")
    return _gate(GATE_UNKNOWN, f"net_expected_return state={state!r}")


def _source_independence_sufficient(bundle, candidate, extra, now):
    """GATE_INPUTS: ("RETURN", "COUNTERPARTY", "MIN_GROUPS_PAPER")."""
    grade = bundle["grades"]["RETURN"]
    if grade == ec.UNKNOWN:
        return _gate(GATE_UNKNOWN, "RETURN grade UNKNOWN — cannot judge independence")
    need = ec.MIN_GROUPS_PAPER.get("return", 1)
    have = bundle.get("independent_root_count", 0)
    return _gate(PASS if have >= need else FAIL, f"independent_root_count={have} need>={need}")


def _data_fresh(bundle, candidate, extra, now):
    """GATE_INPUTS: ("RETURN", "FORWARD_SERIES")."""
    r, f = bundle["grades"]["RETURN"], bundle["grades"]["FORWARD_SERIES"]
    if ec.STALE in (r, f):
        return _gate(FAIL, f"RETURN={r} FORWARD_SERIES={f}")
    if ec.UNKNOWN in (r, f):
        return _gate(GATE_UNKNOWN, f"RETURN={r} FORWARD_SERIES={f}")
    return _gate(PASS, f"RETURN={r} FORWARD_SERIES={f}")


def _counterparty_roles_sufficient(bundle, candidate, extra, now):
    """GATE_INPUTS: ("COUNTERPARTY",)."""
    return _grade_gate("COUNTERPARTY", bundle["grades"]["COUNTERPARTY"])


def _redemption_understood(bundle, candidate, extra, now):
    """GATE_INPUTS: ("REDEMPTION",)."""
    mech = candidate.get("mechanism_id")
    if _na_for("redemption_understood", mech):
        return _gate(_NA_VERDICT, f"redemption_understood NOT_APPLICABLE for {mech!r}")
    return _grade_gate("REDEMPTION", bundle["grades"]["REDEMPTION"])


def _custody_understood(bundle, candidate, extra, now):
    """GATE_INPUTS: ("CUSTODY",)."""
    return _grade_gate("CUSTODY", bundle["grades"]["CUSTODY"])


def _fees_measured(bundle, candidate, extra, now):
    """GATE_INPUTS: ("COST",)."""
    return _grade_gate("COST", bundle["grades"]["COST"])


def _liquidity_measured(bundle, candidate, extra, now):
    """GATE_INPUTS: ("LIQUIDITY", "paper_mode")."""
    return _grade_gate("LIQUIDITY", bundle["grades"]["LIQUIDITY"])


def _exit_path_defined(bundle, candidate, extra, now):
    """GATE_INPUTS: ("LIQUIDITY", "REDEMPTION", "paper_mode"). ADR-564 binding #5: a
    REFERENCE_TRACK position (holder eligibility recorded as anything other than
    SPA_ELIGIBLE) is a NAV tracker SPA could never actually hold — it carries no exit-liquidity
    claim to define, so this gate is NOT_APPLICABLE for it, documented here (never added to the
    frozen evidence_contract.GATE_NA map, which this file does not own)."""
    if bundle.get("paper_mode") == ec.PAPER_MODE_REFERENCE_TRACK:
        return _gate(_NA_VERDICT, "REFERENCE_TRACK candidates track NAV — no exit-liquidity claim "
                                  "to define (ADR-564 binding #5)")
    liq, red = bundle["grades"]["LIQUIDITY"], bundle["grades"]["REDEMPTION"]
    ok_grades = (ec.ADEQUATE, ec.STRONG)
    if liq in ok_grades or red in ok_grades:
        return _gate(PASS, f"LIQUIDITY={liq} REDEMPTION={red}")
    if liq == ec.UNKNOWN and red == ec.UNKNOWN:
        return _gate(GATE_UNKNOWN, f"LIQUIDITY={liq} REDEMPTION={red}")
    return _gate(FAIL, f"LIQUIDITY={liq} REDEMPTION={red}")


def _contract_identity_verified_or_na(bundle, candidate, extra, now):
    """GATE_INPUTS: ("CONTRACT", "PRIMARY_IDENTITY")."""
    mech = candidate.get("mechanism_id")
    if _na_for("contract_identity_verified_or_not_applicable", mech):
        return _gate(_NA_VERDICT, f"NOT_APPLICABLE for {mech!r}")
    return _grade_gate("CONTRACT", bundle["grades"]["CONTRACT"])


def _paper_accounting_feasible(bundle, candidate, extra, now):
    """GATE_INPUTS: ("CONTRACT", "COST", "paper_mode")."""
    contract_grade, cost_grade = bundle["grades"]["CONTRACT"], bundle["grades"]["COST"]
    if contract_grade == ec.UNKNOWN or cost_grade == ec.UNKNOWN:
        return _gate(GATE_UNKNOWN, f"CONTRACT={contract_grade} COST={cost_grade}")
    contract_ok = contract_grade in (ec.ADEQUATE, ec.STRONG, ec.NOT_APPLICABLE)
    cost_ok = cost_grade in (ec.ADEQUATE, ec.STRONG)
    return _gate(PASS if contract_ok and cost_ok else FAIL, f"CONTRACT={contract_grade} COST={cost_grade}")


def _forward_collection_ready(bundle, candidate, extra, now):
    """GATE_INPUTS: ("FORWARD_SERIES",)."""
    return _grade_gate("FORWARD_SERIES", bundle["grades"]["FORWARD_SERIES"])


def _duplicate_exposure_clear(bundle, candidate, extra, now):
    """GATE_INPUTS: ("exposure_family", "underlying_root", "existing_book_roots")."""
    extra = extra or {}
    root = candidate.get("underlying_root")
    book_roots = set(extra.get("existing_book_roots") or [])
    if root and root in book_roots:
        return _gate(FAIL, f"underlying_root {root!r} already held in the live books")
    # post-implementation review M6 (2026-10-04): a wrapper or other-chain copy of the SAME
    # fund shares underlying_root but — for a mechanism not in run._FAMILY_ROOTED_MECHANISMS —
    # gets its OWN exposure_family (bundle.py defaults it to the candidate's own exposure_key),
    # so the exposure_family check below alone never catches it. Checked ADMITTED candidates
    # ONLY (run._sherlock_review_all builds this from contract.PAPER_STATES), same discipline
    # as other_admitted_exposure_families — a merely-screened/under-review duplicate is not yet
    # a live double-exposure.
    other_roots = extra.get("other_admitted_underlying_roots") or {}
    root_holder = other_roots.get(root) if root else None
    if root_holder and root_holder != candidate.get("candidate_id"):
        return _gate(FAIL, f"underlying_root {root!r} already admitted via candidate {root_holder!r} "
                           f"(a wrapper/other-chain copy of the same fund)")
    family = bundle.get("exposure_family")
    other_families = extra.get("other_admitted_exposure_families") or {}
    holder = other_families.get(family)
    if holder and holder != candidate.get("candidate_id"):
        return _gate(FAIL, f"exposure_family {family!r} already admitted via candidate {holder!r}")
    return _gate(PASS, "no shared underlying_root in the live books / exposure_family already admitted")


def _no_conflicted_critical_inputs(bundle, candidate, extra, now):
    """GATE_INPUTS: ("RETURN", "COST", "COUNTERPARTY", "PRIMARY_IDENTITY")."""
    critical = ("RETURN", "COST", "COUNTERPARTY", "PRIMARY_IDENTITY")
    conflicted = [d for d in critical if bundle["grades"][d] == ec.CONFLICTED]
    return _gate(FAIL, f"CONFLICTED: {conflicted}") if conflicted else _gate(PASS, "no CONFLICTED critical input")


def _leverage_known(bundle, candidate, extra, now):
    """GATE_INPUTS: ("leverage", "liquidation_distance")."""
    mech = candidate.get("mechanism_id")
    if _na_for("leverage_known", mech):
        return _gate(_NA_VERDICT, f"leverage not required by {mech!r}")
    if c1.measured_value_of(candidate.get("leverage")) is not None:
        return _gate(PASS, "leverage MEASURED")
    return _gate(FAIL, f"leverage is {(candidate.get('leverage') or {}).get('state')!r} but leverage_required=True")


def _not_advertised_only(bundle, candidate, extra, now):
    """GATE_INPUTS: ("RETURN",). Post-implementation review M2 (2026-10-04), two fixes:

    1. Reads ``bundle["return_evidence"]["primary_cell"]`` — the SAME override-aware cell
       ``grades.grade_return`` grades (honours ``v2_evidence["return_primary_cell_override"]``,
       e.g. a REFERENCE_TRACK instrument's own on-chain oracle NAV reading, ADR-564 decision #5)
       — never re-derives from the v1 candidate's raw cell, which for exactly such an instrument
       (USYC) is NOT_MEASURED (the oracle reading lives only in the override): the old code read
       ``candidate.get(primary_field)`` directly and would FAIL this gate for USYC even though
       its RETURN evidence is a genuinely independent, STRONG-graded oracle reading.
    2. Requires a PRIMARY-class source (``contract.PRIMARY_CLASSES``) — a DeFiLlama aggregator
       relay is not "independently observed" just because its cell's ``state`` happens to be
       MEASURED; the old code accepted ANY MEASURED state regardless of source_class."""
    primary = bundle["return_evidence"].get("primary_cell") or {}
    if c1.measured_value_of(primary) is not None and primary.get("source_class") in c1.PRIMARY_CLASSES:
        return _gate(PASS, f"primary return cell is MEASURED from a PRIMARY-class source "
                           f"(source_class={primary.get('source_class')!r})")
    grade = bundle["grades"]["RETURN"]
    if grade == ec.UNKNOWN:
        return _gate(GATE_UNKNOWN, "no MEASURED PRIMARY-class return value and RETURN grade is UNKNOWN")
    return _gate(FAIL, f"return evidence has no MEASURED PRIMARY-class value "
                       f"(source_class={primary.get('source_class')!r}) — advertised only")


def _holder_eligibility_recorded(bundle, candidate, extra, now):
    """GATE_INPUTS: ("HOLDER_ELIGIBILITY", "paper_mode")."""
    grade = bundle["grades"]["HOLDER_ELIGIBILITY"]
    return _gate(GATE_UNKNOWN, "holder eligibility not recorded") if grade == ec.UNKNOWN \
        else _gate(PASS, f"holder eligibility recorded (grade={grade})")


_EVALUATORS = {
    "identity_verified": _identity_verified,
    "mechanism_understood": _mechanism_understood,
    "return_source_verified": _return_source_verified,
    "net_return_computable": _net_return_computable,
    "source_independence_sufficient": _source_independence_sufficient,
    "data_fresh": _data_fresh,
    "counterparty_roles_sufficient": _counterparty_roles_sufficient,
    "redemption_understood": _redemption_understood,
    "custody_understood": _custody_understood,
    "fees_measured": _fees_measured,
    "liquidity_measured": _liquidity_measured,
    "exit_path_defined": _exit_path_defined,
    "contract_identity_verified_or_not_applicable": _contract_identity_verified_or_na,
    "paper_accounting_feasible": _paper_accounting_feasible,
    "forward_collection_ready": _forward_collection_ready,
    "duplicate_exposure_clear": _duplicate_exposure_clear,
    "no_conflicted_critical_inputs": _no_conflicted_critical_inputs,
    "leverage_known": _leverage_known,
    "not_advertised_only": _not_advertised_only,
    "holder_eligibility_recorded": _holder_eligibility_recorded,
}
assert set(_EVALUATORS) == set(ec.ADMISSION_V2_GATES)
assert set(_EVALUATORS) == set(ec.GATE_INPUTS)


def evaluate(bundle: dict, candidate: dict, extra: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """A v2 ``PaperAdmissionReport``: every ``ADMISSION_V2_GATES`` gate PASS/FAIL/UNKNOWN/NOT_APPLICABLE
    with evidence. UNKNOWN never passes (a caller computing an overall verdict must treat UNKNOWN
    the same way as FAIL — ``decision.py`` is the one caller that does, via ``failed_gates``/
    ``unknown_gates``)."""
    extra = extra or {}
    gates = {name: fn(bundle, candidate, extra, now) for name, fn in _EVALUATORS.items()}
    return {"schema": SCHEMA_REPORT_V2, "candidate_id": candidate.get("candidate_id"),
           "bundle_digest": bundle.get("evidence_digest"), "gates": gates}
