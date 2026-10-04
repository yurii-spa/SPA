"""spa_core/research_factory/admission.py — PaperAdmissionReport over contract.ADMISSION_GATES.

ADR-560 WP-A06 + binding review #4/#6/#9/#10/#15. ``evaluate()`` is pure (no I/O); the caller
(normally ``run.py``) decides whether/when to persist the PASS snapshot via
:func:`write_admission_snapshot`.

``registry_view`` passed to :func:`evaluate` is a dict with two parts:
* every OTHER known candidate's identity view, keyed by candidate_id (for dedup);
* ``registry_view["_existing_book_roots"]``: the live-book ``underlying_root`` list from the
  scanners' ``existing_book_roots`` (dedup's third check).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from spa_core.research_factory import contract, dedup

PASS, FAIL, UNKNOWN = contract.GATE_PASS, contract.GATE_FAIL, contract.GATE_UNKNOWN


def _gate(verdict: str, evidence: str) -> dict:
    if verdict not in (PASS, FAIL, UNKNOWN):
        raise ValueError(f"unknown gate verdict {verdict!r}")
    return {"verdict": verdict, "evidence": evidence}


def _mechanism_understood(c: dict) -> dict:
    m = c.get("mechanism_id")
    if m not in contract.MECHANISMS:
        return _gate(FAIL, f"mechanism_id {m!r} is not in contract.MECHANISMS")
    if c.get("asset_class") != contract.MECHANISMS[m]["asset_class"]:
        return _gate(FAIL, f"asset_class {c.get('asset_class')!r} does not match mechanism {m!r}")
    return _gate(PASS, f"mechanism {m!r} recognised")


def _return_source_understood(c: dict) -> dict:
    base = c.get("base_return") or {}
    if not c.get("yield_source"):
        return _gate(UNKNOWN, "yield_source not named")
    if base.get("state") not in contract.VALUED_STATES:
        return _gate(UNKNOWN, f"base_return is {base.get('state')!r}, no value to understand")
    return _gate(PASS, f"yield_source={c.get('yield_source')!r}, base_return valued")


#: a second RETURN cell that MAY cross-check the primary return — never a cost, a derived value
#: (net_expected_return) or a risk cell. B may add cross_check_return later; the field just needs
#: to exist on the candidate dict with a valued, non-MODELLED cell to be considered.
_CROSS_CHECK_FIELDS = ("quoted_return", "measured_return", "cross_check_return")
#: mechanisms whose PRIMARY return driver is the funding leg, not base_return
_FUNDING_PRIMARY_MECHANISMS = ("FUNDING_CAPTURE", "SPOT_PERP_BASIS")


def _provenance_primary_field(c: dict) -> str:
    return "funding" if c.get("mechanism_id") in _FUNDING_PRIMARY_MECHANISMS else "base_return"


def _comparable(a: dict, b: dict) -> bool:
    """Same unit AND window — but only when BOTH sides actually annotate one (missing metadata
    is not itself a mismatch; a real disagreement in a field BOTH cells name is)."""
    if a.get("unit") is not None and b.get("unit") is not None and a.get("unit") != b.get("unit"):
        return False
    if a.get("window") is not None and b.get("window") is not None and a.get("window") != b.get("window"):
        return False
    return True


def _source_provenance_acceptable(c: dict, now: datetime) -> dict:
    """Review #4/H5: compare ONLY the candidate's primary return cell (``base_return``, or
    ``funding`` for a funding-rate mechanism) against a second, genuinely INDEPENDENT return
    cell — never ``net_expected_return`` (derived), never a cost fraction, never a MODELLED
    series. No comparable second root ⇒ PASS only when the primary cell is ITSELF a PRIMARY_*
    root; otherwise FAIL ("single aggregator root") — an aggregator-only reading is never, on
    its own, provenance-acceptable."""
    field = _provenance_primary_field(c)
    primary = c.get(field) or {}
    if primary.get("state") not in contract.VALUED_STATES:
        return _gate(UNKNOWN, f"{field} has no value to check provenance on")
    primary_root = primary.get("source_root")
    primary_class = primary.get("source_class")

    cross_checks = []
    for f in _CROSS_CHECK_FIELDS:
        other = c.get(f)
        if not isinstance(other, dict) or other.get("state") not in contract.VALUED_STATES:
            continue
        if other.get("source_class") == contract.MODELLED:
            continue
        if other.get("source_root") == primary_root:
            continue  # the same root cross-checking itself proves nothing
        if not _comparable(primary, other):
            continue
        cross_checks.append((f, other))

    if not cross_checks:
        if primary_class in contract.PRIMARY_CLASSES:
            return _gate(PASS, f"{field} is itself a PRIMARY_* root, no second root needed")
        return _gate(FAIL, f"single aggregator root for {field} ({primary_class!r}), no independent "
                           f"second root to cross-check against")

    field2, other = cross_checks[0]
    a_val, b_val = primary.get("value"), other.get("value")
    if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
        denom = max(abs(a_val), abs(b_val), 1e-12)
        rel = abs(a_val - b_val) / denom
        if rel > contract.CONFLICT_TOLERANCE_REL:
            return _gate(FAIL, f"CONFLICTED: {field} vs {field2} (different root) differ by {rel:.2%}")
    return _gate(PASS, f"{field} cross-checked against {field2} from an independent root")


def _data_fresh(c: dict, now: datetime) -> dict:
    """N5: judge the PRIMARY return field for THIS mechanism (``funding`` for
    FUNDING_CAPTURE/SPOT_PERP_BASIS, exactly as H5's provenance gate already does via
    :func:`_provenance_primary_field`) — judging ``base_return`` unconditionally meant this gate
    was PERMANENTLY UNKNOWN for a funding-rate mechanism, where ``base_return`` is legitimately
    NOT_APPLICABLE and the real evidence lives in ``funding`` instead."""
    field = _provenance_primary_field(c)
    primary = c.get(field) or {}
    if primary.get("state") == contract.STALE:
        return _gate(FAIL, f"{field} cell is itself marked STALE (e.g. a depeg)")
    fresh = contract.is_fresh(primary, now)
    if fresh is None:
        return _gate(UNKNOWN, f"{field} has no judgeable as_of")
    return _gate(PASS if fresh else FAIL, f"{field} fresh={fresh}")


def _fees_measurable(c: dict) -> dict:
    fees = c.get("fees") or {}
    if fees.get("state") == contract.NOT_APPLICABLE:
        return _gate(PASS, "fees NOT_APPLICABLE for this mechanism")
    if contract.measured_value_of(fees) is not None:
        return _gate(PASS, "fees MEASURED")
    return _gate(FAIL, f"fees is {fees.get('state')!r}, not MEASURED")


def _liquidity_measurable(c: dict) -> dict:
    liq = c.get("liquidity") or {}
    if liq.get("state") == contract.NOT_APPLICABLE:
        return _gate(PASS, "liquidity NOT_APPLICABLE for this mechanism")
    if contract.value_of(liq) is not None:
        return _gate(PASS, f"liquidity {liq.get('state')}")
    return _gate(FAIL, f"liquidity is {liq.get('state')!r}, no value")


def _counterparty_named(c: dict) -> dict:
    mech = contract.MECHANISMS.get(c.get("mechanism_id")) or {}
    required = mech.get("required_roles", ())
    cp = c.get("counterparty") or {}
    roles = cp.get("roles") or {}
    if not required:
        return _gate(PASS, "no required roles for this mechanism")
    if not roles:
        return _gate(UNKNOWN, "no counterparty data recorded")
    missing = [r for r in required if (roles.get(r) or {}).get("state") not in
              (contract.CP_OBSERVED, contract.CP_DOCUMENTED)]
    if missing:
        return _gate(FAIL, f"required role(s) not NAMED: {missing}")
    return _gate(PASS, f"every required role named: {list(required)}")


def _no_duplicate_exposure(c: dict, registry_view: dict) -> dict:
    others = [v for k, v in registry_view.items() if k != "_existing_book_roots"]
    book_roots = registry_view.get("_existing_book_roots") or []
    verdict, reason = dedup.no_duplicate_exposure(c, others, book_roots)
    return _gate(verdict, reason)


def _paper_accounting_feasible(c: dict) -> dict:
    net = contract.net_expected_return(c)
    if net.get("state") == contract.NOT_MEASURED:
        return _gate(FAIL, net.get("reason") or "net_expected_return not computable")
    return _gate(PASS, "net_expected_return computable")


def _exit_path_defined(c: dict) -> dict:
    tte = c.get("time_to_exit") or {}
    if tte.get("state") == contract.NOT_APPLICABLE:
        return _gate(PASS, "time_to_exit NOT_APPLICABLE")
    if contract.value_of(tte) is not None:
        return _gate(PASS, "time_to_exit valued")
    return _gate(FAIL, f"time_to_exit is {tte.get('state')!r}")


def _not_advertised_only(c: dict) -> dict:
    # a MEASURED cell can never cite ISSUER_CLAIM (enforced by contract.cell() itself), so a
    # MEASURED base_return is BY CONSTRUCTION not an advertised-only number.
    if contract.measured_value_of(c.get("base_return")) is not None:
        return _gate(PASS, "base_return is MEASURED (independently observed)")
    return _gate(FAIL, "base_return has no MEASURED (independently observed) value — advertised only")


def _leverage_known(c: dict) -> dict:
    mech = contract.MECHANISMS.get(c.get("mechanism_id")) or {}
    if not mech.get("leverage_required"):
        return _gate(PASS, "leverage not required by this mechanism")
    if contract.measured_value_of(c.get("leverage")) is not None:
        return _gate(PASS, "leverage MEASURED")
    return _gate(FAIL, f"leverage is {(c.get('leverage') or {}).get('state')!r} but leverage_required=True")


def _no_conflicted_inputs(c: dict) -> dict:
    conflicted = [f for f in contract.CELL_FIELDS if (c.get(f) or {}).get("state") == contract.CONFLICTED]
    if conflicted:
        return _gate(FAIL, f"CONFLICTED cell(s): {conflicted}")
    return _gate(PASS, "no CONFLICTED cells")


_EVALUATORS = {
    "mechanism_understood": lambda c, rv, now: _mechanism_understood(c),
    "return_source_understood": lambda c, rv, now: _return_source_understood(c),
    "source_provenance_acceptable": lambda c, rv, now: _source_provenance_acceptable(c, now),
    "data_fresh": lambda c, rv, now: _data_fresh(c, now),
    "fees_measurable": lambda c, rv, now: _fees_measurable(c),
    "liquidity_measurable": lambda c, rv, now: _liquidity_measurable(c),
    "counterparty_named": lambda c, rv, now: _counterparty_named(c),
    "no_duplicate_exposure": lambda c, rv, now: _no_duplicate_exposure(c, rv),
    "paper_accounting_feasible": lambda c, rv, now: _paper_accounting_feasible(c),
    "exit_path_defined": lambda c, rv, now: _exit_path_defined(c),
    "not_advertised_only": lambda c, rv, now: _not_advertised_only(c),
    "leverage_known": lambda c, rv, now: _leverage_known(c),
    "no_conflicted_inputs": lambda c, rv, now: _no_conflicted_inputs(c),
}
assert set(_EVALUATORS) == set(contract.ADMISSION_GATES)


def evaluate(candidate: dict, registry_view: dict, now: datetime) -> dict:
    """A ``PaperAdmissionReport`` (``contract.SCHEMA_ADMISSION``): every gate PASS/FAIL/UNKNOWN
    with evidence; the overall verdict is PASS only if every gate is PASS (UNKNOWN never passes)."""
    gates = {g: _EVALUATORS[g](candidate, registry_view, now) for g in contract.ADMISSION_GATES}
    if all(v["verdict"] == PASS for v in gates.values()):
        overall = PASS
    elif any(v["verdict"] == FAIL for v in gates.values()):
        overall = FAIL
    else:
        overall = UNKNOWN
    return {"schema": contract.SCHEMA_ADMISSION, "candidate_id": candidate.get("candidate_id"),
           "verdict": overall, "gates": gates}


class V1AdmissionSuperseded(Exception):
    """ADR-564 binding #1: once this ADR is in force, the v1 PASS-report path into
    PAPER_ACTIVE/EVIDENCE_ACCUMULATING is permanently refused. Only a Sherlock
    ``ADMIT_TO_PAPER`` decision (``spa_core.research_factory.decision``) plus its
    ``paper-admission/2`` snapshot (``decision.write_admission_snapshot_v2``) may open paper now;
    ``lifecycle.py`` no longer accepts a v1 ``kind="admission"`` row as a gate_ref either way.
    :func:`evaluate` is unaffected and stays in use for DISPLAY and for routing a non-PASS
    candidate to its hold state — only the WRITE of a new v1 snapshot is refused."""


def write_admission_snapshot(data_dir: Path, candidate: dict, report: dict, now: datetime) -> dict:
    """Superseded (ADR-564 binding #1) — always refuses. Kept as a function (not deleted) so the
    refusal itself is a named, importable, testable behaviour rather than a missing attribute."""
    raise V1AdmissionSuperseded(
        "ADR-564 binding #1: paper admission now requires a Sherlock ADMIT_TO_PAPER decision + a "
        "paper-admission/2 snapshot (spa_core.research_factory.decision.decide_and_record / "
        "write_admission_snapshot_v2); the v1 PASS-report path into "
        "PAPER_ACTIVE/EVIDENCE_ACCUMULATING is permanently refused. admission.evaluate() remains "
        "in force for display and hold-state routing only.")
