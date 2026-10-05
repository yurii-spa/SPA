"""spa_core/tests/test_research_remediation_cost.py — review-fix tests (ADR-564 remediation,
2026-10-04), covering exactly three independent reviewer findings:

* H2 (HIGH): ``grades.grade_cost`` used to read ONLY ``v2_evidence["cost_components"]`` — a
  funding PAIR's v1 ``fees``/``gas`` cells are NOT_APPLICABLE by construction (basis.py), so a
  pair with no measured fee on EITHER leg could grade COST ADEQUATE purely because its hedging
  slippage cell happened to be measured. Fixed in ``spa_core/research_factory/grades.py``
  (``grade_cost``) + ``spa_core/research_factory/bundle.py`` (now builds
  ``paper_accounting_evidence`` once and forwards it into grading).
* M1 (LOW): ``eligibility.pending_cio_amendment_gates``'s ``reserves_groups_sufficient_for_cio``/
  ``custody_groups_sufficient_for_cio`` used to FAIL on an empty group set even when RESERVES/
  CUSTODY is NOT_APPLICABLE for the candidate's mechanism. Fixed in
  ``spa_core/research_factory/eligibility.py``.
* M5 (LOW): ``scanners/rwa.py``'s ``_phase0_fee_cell``/``paper_accounting_hints`` could print a
  DOCUMENTED figure built from an INCOMPLETE set of facts (OUSG's total annual fee when
  fee_expenses_cap was missing/refused; USYC's total annual fee from a partial subscription/
  redemption/performance set), and the OUSG waiver's END DATE was never checked against ``now``
  at all. Fixed in ``spa_core/research_factory/scanners/rwa.py``.

RESEARCH / PAPER only — nothing here moves money, signs or orders.

# FROZEN-DATE-OK: injected-clock — every judgement below is made against the single literal
anchor NOW, passed explicitly as `now=`/the second positional datetime argument to every
contract.cell/bundle/grades/registry_loader call under test; nothing here asks the wall clock.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.research_factory import admission_v2, bundle as bundle_mod, contract as c1
from spa_core.research_factory import eligibility, evidence_contract as ec, grades as grades_mod
from spa_core.research_factory import registry_loader
from spa_core.research_factory.scanners import basis, rwa

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
REGISTRY_DIR = Path(rwa.__file__).resolve().parent.parent / "registry"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# H2 — grades.grade_cost must fold in EVERY paper-accounting fee component, on EVERY leg
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _fee_cell(venue: str, *, measured: bool) -> dict:
    if measured:
        return c1.cell(c1.MEASURED, 0.0005, unit="fraction_one_off", source_ref=f"test:{venue}",
                       source_class=c1.OFFICIAL_API, source_root=f"venue:{venue}",
                       as_of=NOW.isoformat(), recorded_at=NOW.isoformat(), now=NOW)
    return c1.cell(c1.NOT_MEASURED, reason=f"{venue}: no official fee source cited")


def _fee_component(kind: str, cell: dict) -> dict:
    return {"kind": kind, "cell": cell, "unit": "fraction_one_off", "effective_from": NOW.isoformat(),
           "subject_to_change": False, "one_off": True}


def _leg(venue: str, *, measured: bool) -> dict:
    cell = _fee_cell(venue, measured=measured)
    return {"entry_fee_components": [_fee_component("entry", cell)],
           "exit_fee_components": [_fee_component("exit", cell)]}


# ── unit-level: grade_cost's own branches, backward compatibility and the new leg-aware logic ──

def test_grade_cost_unchanged_when_paper_accounting_evidence_omitted():
    """Backward compatibility: calling grade_cost with ONLY v2_evidence (the old call shape) must
    behave exactly as before the fix — this is the exact assertion from the pre-existing
    test_grade_cost_all_branches, repeated here as this fix's own non-regression anchor."""
    na = c1.cell(c1.NOT_APPLICABLE, reason="x")
    measured = c1.cell(c1.MEASURED, 1.0, unit="usd", source_ref="x", source_class=c1.OFFICIAL_API,
                       source_root="venue:test", as_of=NOW.isoformat(), now=NOW)
    not_measured = c1.cell(c1.NOT_MEASURED, reason="x")
    conflicted = c1.cell(c1.CONFLICTED, reason="x")
    assert grades_mod.grade_cost({}) == ec.UNKNOWN
    assert grades_mod.grade_cost({"cost_components": {"entry": na, "exit": na}}) == ec.ADEQUATE
    assert grades_mod.grade_cost({"cost_components": {"entry": measured}}) == ec.ADEQUATE
    assert grades_mod.grade_cost({"cost_components": {"entry": not_measured}}) == ec.WEAK
    assert grades_mod.grade_cost({"cost_components": {"entry": conflicted}}) == ec.CONFLICTED


def test_grade_cost_two_leg_not_measured_on_one_leg_is_weak_even_with_no_cost_components():
    """The exact live defect shape: v2_evidence carries no cost_components at all (or only
    NOT_APPLICABLE ones, as a funding pair's v1 cells do) and ONE leg's fee components are all
    NOT_MEASURED — COST must be WEAK, never ADEQUATE on an empty cost_components dict alone."""
    pae = {"legs": {"perp": _leg("kucoin", measured=True), "spot": _leg("binance", measured=False)}}
    assert grades_mod.grade_cost({}, pae) == ec.WEAK
    assert grades_mod.grade_cost({"cost_components": {"fees": c1.cell(c1.NOT_APPLICABLE, reason="x")}}, pae) \
        == ec.WEAK


def test_grade_cost_two_leg_all_measured_is_adequate():
    pae = {"legs": {"perp": _leg("kucoin", measured=True), "spot": _leg("binance", measured=True)}}
    assert grades_mod.grade_cost({}, pae) == ec.ADEQUATE


def test_grade_cost_two_leg_empty_component_list_on_a_leg_is_weak_not_adequate():
    """An unlisted fee is not a zero fee: a leg with NO components at all (empty list, after
    dropping NOT_APPLICABLE) must never let COST read as if that leg had nothing to report."""
    pae = {"legs": {"perp": _leg("kucoin", measured=True), "spot": {"entry_fee_components": [], "exit_fee_components": []}}}
    assert grades_mod.grade_cost({}, pae) == ec.WEAK


def test_grade_cost_two_leg_conflicted_component_wins_over_weak():
    pae = {"legs": {"perp": _leg("kucoin", measured=True),
                    "spot": _leg("binance", measured=False)}}
    pae["legs"]["spot"]["entry_fee_components"][0]["cell"] = c1.cell(c1.CONFLICTED, reason="x")
    assert grades_mod.grade_cost({}, pae) == ec.CONFLICTED


def test_grade_cost_single_leg_paper_accounting_still_folds_in():
    """The single-leg (non-"legs") shape — everything that is not a funding pair — is read the
    same way: entry_fee_components/exit_fee_components directly on the top-level dict."""
    pae = {"entry_fee_components": [_fee_component("entry", _fee_cell("x", measured=False))],
          "exit_fee_components": [_fee_component("exit", _fee_cell("x", measured=False))]}
    assert grades_mod.grade_cost({}, pae) == ec.WEAK
    pae_ok = {"entry_fee_components": [_fee_component("entry", _fee_cell("x", measured=True))],
             "exit_fee_components": [_fee_component("exit", _fee_cell("x", measured=True))]}
    assert grades_mod.grade_cost({}, pae_ok) == ec.ADEQUATE


# ── gate-level positive control (the reviewer's own shape): a real kucoin-perp x binance-spot
#    funding-pair candidate, built end-to-end through bundle.py, graded by admission_v2 ──────────

def _funding_rows(settlement_pct_per_8h: float = 0.0001) -> list:
    return [{"claim": "funding_settlement:ETH", "origin": "venue:kucoin", "state": c1.MEASURED,
            "value": settlement_pct_per_8h, "upstream_ts": NOW.isoformat(), "ref": "test:kucoin"}]


def _book_rows() -> list:
    return [
        {"claim": "perp_mark:ETH", "origin": "venue:kucoin", "state": c1.MEASURED, "value": 3500.0,
         "unit": "usd", "upstream_ts": NOW.isoformat(), "ref": "test:kucoin-mark"},
        {"claim": "spot_slippage_bps:ETH", "origin": "venue:binance", "state": c1.MEASURED, "value": 2.0,
         "ref": "test:binance-slip"},
    ]


def _kucoin_binance_pair_candidate() -> dict:
    cands = basis.funding_pair_candidates("ETH", _funding_rows(), _book_rows(), NOW)
    return next(c for c in cands if c["venue_or_protocol"] == "kucoin+binance")


def _v2_evidence_for(cand: dict) -> dict:
    """Mirrors run.py's own ``_default_v2_evidence`` cost_components derivation + its
    paper_accounting_hints passthrough — never a parallel, hand-rolled shape."""
    cost_components = {f: cand[f] for f in ("fees", "gas", "hedging_cost")
                       if isinstance(cand.get(f), dict) and cand[f].get("state")}
    v2 = {"identity": {}, "cost_components": cost_components, "redemption": {}, "reserves": {},
         "legal": {}, "holder_eligibility": {}}
    hints = cand.get("paper_accounting_hints")
    if isinstance(hints, dict):
        v2["paper_accounting"] = hints
    return v2


def _build_pair_bundle(cand: dict, v2_evidence: dict) -> dict:
    return bundle_mod.build_bundle(cand, profile={}, v2_evidence=v2_evidence, facts=[],
                                   paper_mode=ec.PAPER_MODE_HOLDABLE, registry={}, now=NOW)


def test_h2_real_kucoin_perp_binance_spot_pair_cost_is_weak_and_fees_measured_gate_fails():
    """GATE-level positive control for the live finding: kucoin's perp taker fee IS cited
    (DOCUMENTED) but binance's spot taker fee is NOT (no venue has one cited, by design) — COST
    must be WEAK, never ADEQUATE on the perp leg's fee alone, and the v2 gate `fees_measured`
    must FAIL, not pass, for this pair."""
    cand = _kucoin_binance_pair_candidate()
    hints = cand["paper_accounting_hints"]
    assert hints["legs"]["perp"]["entry_fee_components"][0]["cell"]["state"] == c1.DOCUMENTED  # kucoin: cited
    assert hints["legs"]["spot"]["entry_fee_components"][0]["cell"]["state"] == c1.NOT_MEASURED  # binance: never cited

    bundle = _build_pair_bundle(cand, _v2_evidence_for(cand))
    assert bundle["grades"]["COST"] == ec.WEAK, bundle["grades"]

    report = admission_v2.evaluate(bundle, cand)
    assert report["gates"]["fees_measured"]["verdict"] == ec.FAIL, report["gates"]["fees_measured"]


def test_h2_binance_perp_binance_spot_pair_both_legs_unmeasured_is_also_weak():
    """binance/bybit/okx perps have no cited taker fee EITHER (only kucoin/hyperliquid do) — a
    pair with NO measured fee on either leg must still be WEAK, never UNKNOWN/ADEQUATE."""
    cands = basis.funding_pair_candidates("ETH", _funding_rows(), _book_rows(), NOW)
    cand = next(c for c in cands if c["venue_or_protocol"] == "binance+binance")
    bundle = _build_pair_bundle(cand, _v2_evidence_for(cand))
    assert bundle["grades"]["COST"] == ec.WEAK, bundle["grades"]
    report = admission_v2.evaluate(bundle, cand)
    assert report["gates"]["fees_measured"]["verdict"] == ec.FAIL


def test_h2_all_measured_synthetic_pair_cost_is_adequate_and_fees_measured_gate_passes():
    """Positive control, other direction: when EVERY fee component on EVERY leg is actually
    measured, COST grades ADEQUATE and the gate PASSES — the fix does not just make everything
    WEAK, it reads what is actually there."""
    cand = _kucoin_binance_pair_candidate()
    v2_evidence = _v2_evidence_for(cand)
    v2_evidence["paper_accounting"] = {
        "legs": {"perp": _leg("kucoin", measured=True), "spot": _leg("binance", measured=True)}}
    bundle = _build_pair_bundle(cand, v2_evidence)
    assert bundle["grades"]["COST"] in (ec.ADEQUATE, ec.STRONG), bundle["grades"]

    report = admission_v2.evaluate(bundle, cand)
    assert report["gates"]["fees_measured"]["verdict"] == ec.PASS, report["gates"]["fees_measured"]


def test_h2_mutation_check_reverting_grade_cost_lets_the_broken_pair_pass(monkeypatch):
    """MUTATION CHECK: the pre-fix grade_cost (cost_components only, no paper_accounting_evidence
    parameter at all) must let the SAME kucoin/binance pair from
    test_h2_real_kucoin_perp_binance_spot_pair_cost_is_weak_and_fees_measured_gate_fails grade
    ADEQUATE and PASS `fees_measured` — proving that test actually depends on the fix in
    grades.grade_cost, not on some unrelated detail of the fixture."""
    def _pre_fix_grade_cost(v2_evidence, paper_accounting_evidence=None):  # the exact old body
        components = v2_evidence.get("cost_components") or {}
        if not components:
            return ec.UNKNOWN
        states = [cell.get("state") for cell in components.values()
                 if isinstance(cell, dict) and cell.get("state") != c1.NOT_APPLICABLE]
        if not states:
            return ec.ADEQUATE
        if any(s == c1.CONFLICTED for s in states):
            return ec.CONFLICTED
        if all(s in (c1.MEASURED, c1.DOCUMENTED) for s in states):
            return ec.ADEQUATE
        return ec.WEAK

    cand = _kucoin_binance_pair_candidate()
    v2_evidence = _v2_evidence_for(cand)
    # confirm the live defect's own precondition: the only non-NOT_APPLICABLE cost_components
    # entry is hedging_cost (MEASURED slippage) — fees/gas are NOT_APPLICABLE for FUNDING_CAPTURE.
    assert v2_evidence["cost_components"]["fees"]["state"] == c1.NOT_APPLICABLE
    assert v2_evidence["cost_components"]["hedging_cost"]["state"] == c1.MEASURED

    monkeypatch.setattr(grades_mod, "grade_cost", _pre_fix_grade_cost)
    broken_bundle = _build_pair_bundle(cand, v2_evidence)
    assert broken_bundle["grades"]["COST"] == ec.ADEQUATE  # the bug, reproduced under the OLD body
    broken_report = admission_v2.evaluate(broken_bundle, cand)
    assert broken_report["gates"]["fees_measured"]["verdict"] == ec.PASS  # wrongly passes

    monkeypatch.undo()  # restore grades_mod.grade_cost to the fixed version for the next line
    fixed_bundle = _build_pair_bundle(cand, v2_evidence)
    assert fixed_bundle["grades"]["COST"] == ec.WEAK  # the fix, confirmed back in place
    fixed_report = admission_v2.evaluate(fixed_bundle, cand)
    assert fixed_report["gates"]["fees_measured"]["verdict"] == ec.FAIL


# ══════════════════════════════════════════════════════════════════════════════════════════════
# M1 — eligibility.pending_cio_amendment_gates: NOT_APPLICABLE grade ⇒ group-count gate PASSes
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _bundle_for_group_gates(*, reserves_grade: str, custody_grade: str, reserves_evidence: dict = None,
                            custody_citations: list = None) -> dict:
    grades = {d: ec.ADEQUATE for d in ec.DIMENSIONS}
    grades["RESERVES"] = reserves_grade
    grades["CUSTODY"] = custody_grade
    return {
        "mechanism_id": "FUNDING_CAPTURE", "grades": grades,
        "reserves_evidence": reserves_evidence or {},
        "custody_evidence": {"profile_entry": {"citations": custody_citations or []}},
    }


def test_reserves_groups_sufficient_for_cio_passes_not_applicable_with_no_groups():
    """The live finding: a funding-mechanism candidate has RESERVES graded NOT_APPLICABLE and an
    (honestly) empty reserves group set — the gate must PASS, naming NOT_APPLICABLE, never FAIL
    on a dimension the mechanism was never going to carry evidence for."""
    bundle = _bundle_for_group_gates(reserves_grade=ec.NOT_APPLICABLE, custody_grade=ec.ADEQUATE)
    gates = eligibility.pending_cio_amendment_gates(bundle, registry={})
    assert gates["reserves_groups_sufficient_for_cio"]["verdict"] == c1.GATE_PASS
    assert "NOT_APPLICABLE" in gates["reserves_groups_sufficient_for_cio"]["evidence"]


def test_reserves_groups_sufficient_for_cio_still_fails_on_a_genuinely_insufficient_set():
    """Direction control: when RESERVES is NOT NOT_APPLICABLE, the old insufficient-groups FAIL
    behaviour must be unchanged."""
    bundle = _bundle_for_group_gates(reserves_grade=ec.ADEQUATE, custody_grade=ec.ADEQUATE,
                                     reserves_evidence={"attested": True, "auditor_group": "same",
                                                       "issuer_group": "same"})
    gates = eligibility.pending_cio_amendment_gates(bundle, registry={})
    assert gates["reserves_groups_sufficient_for_cio"]["verdict"] == c1.GATE_FAIL


def test_custody_groups_sufficient_for_cio_passes_not_applicable_even_without_a_registry():
    """NOT_APPLICABLE must win over the (otherwise correct) 'no registry supplied' UNKNOWN — a
    candidate that was never going to carry a CUSTODY claim at all must not need a registry to
    say so."""
    bundle = _bundle_for_group_gates(reserves_grade=ec.ADEQUATE, custody_grade=ec.NOT_APPLICABLE)
    gates = eligibility.pending_cio_amendment_gates(bundle, registry=None)
    assert gates["custody_groups_sufficient_for_cio"]["verdict"] == c1.GATE_PASS
    assert "NOT_APPLICABLE" in gates["custody_groups_sufficient_for_cio"]["evidence"]


def test_custody_groups_sufficient_for_cio_still_unknown_without_registry_when_applicable():
    """Direction control: when CUSTODY is NOT NOT_APPLICABLE, the old 'no registry' UNKNOWN
    behaviour must be unchanged."""
    cit_a = ec.citation(origin="custodian:a", channel=ec.CHANNEL_OFFICIAL_DOC, ref="https://a.example",
                        quote="custodian a", retrieved_at=NOW.isoformat())
    bundle = _bundle_for_group_gates(reserves_grade=ec.ADEQUATE, custody_grade=ec.ADEQUATE,
                                     custody_citations=[cit_a])
    gates = eligibility.pending_cio_amendment_gates(bundle, registry=None)
    assert gates["custody_groups_sufficient_for_cio"]["verdict"] == c1.GATE_UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════════════════════
# M5 — scanners/rwa.py: a figure built from an incomplete fact set must be NOT_MEASURED, never a
# silent 0; a waiver's end date that is not machine-readable must stop being assumed past it.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _load_real_facts() -> list:
    out = []
    with open(REGISTRY_DIR / "facts.jsonl", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _reviewed_facts_missing(*drop: "tuple[str, str]") -> list:
    """The real facts.jsonl, independently reviewed (same discipline as
    test_research_evidence_tracks.py's _patch_reviewed_facts), with the named
    (entity, claim_type) pairs REMOVED — simulating a fact that is missing/refused this run."""
    drop_set = set(drop)
    out = []
    for row in _load_real_facts():
        if (row["entity"], row["claim_type"]) in drop_set:
            continue
        row = dict(row)
        row["reviewed_by"] = "test-fixture-independent-review"
        out.append(row)
    return out


def _patch_facts(monkeypatch, facts: list) -> None:
    monkeypatch.setattr(registry_loader, "load_facts", lambda path=None: facts)


def test_usyc_missing_one_of_three_fee_facts_is_not_measured_never_a_partial_zero(monkeypatch):
    """The live finding: USYC's 'no recurring annual fee' figure is built from subscription AND
    redemption AND performance together — missing even one must be NOT_MEASURED, naming which
    fact is missing, never a DOCUMENTED 0.0 built from whichever two happened to be cited."""
    _patch_facts(monkeypatch, _reviewed_facts_missing(("USYC", "fee_redemption")))
    cell = rwa._phase0_fee_cell("USYC", NOW)
    assert cell["state"] == c1.NOT_MEASURED
    assert cell["value"] is None
    assert "fee_redemption" in cell["reason"]


def test_usyc_all_three_fee_facts_present_is_still_documented_zero(monkeypatch):
    """Direction control: with all three facts present, the figure is unchanged — DOCUMENTED 0.0,
    the exact live-bug-fix value this package already relies on elsewhere."""
    _patch_facts(monkeypatch, _reviewed_facts_missing())
    cell = rwa._phase0_fee_cell("USYC", NOW)
    assert cell["state"] == c1.DOCUMENTED
    assert cell["value"] == 0.0
    assert cell["unit"] == rwa.UNIT_ANNUAL


def test_ousg_missing_expenses_cap_fact_is_not_measured_never_the_management_fee_only_zero(monkeypatch):
    """The live finding: OUSG's management fee alone (waived, cited) was enough to print a
    DOCUMENTED 0.0 for the TOTAL annual cost whenever fee_expenses_cap was simply missing/refused
    — the missing fact must block the figure, never be treated as if it agreed with 0."""
    _patch_facts(monkeypatch, _reviewed_facts_missing(("OUSG", "fee_expenses_cap")))
    cell = rwa._phase0_fee_cell("OUSG", NOW)
    assert cell["state"] == c1.NOT_MEASURED
    assert cell["value"] is None
    assert "fee_expenses_cap" in cell["reason"]


def _ousg_mgmt_fact_never_expiring() -> list:
    """A synthetic fee_management fact with ``expires_at=None`` (never stale by
    ``registry_loader.is_stale``'s own mechanical check) — isolates the waiver-END-DATE question
    this test is actually about from fact RE-CURATION staleness (a real curated fact's
    ``expires_at`` is only ~1 month out; jumping `now` to 2027 against the real file would hit
    'fact not found' for the wrong reason entirely)."""
    import spa_core.research_factory.instruments as instruments_mod
    cid = instruments_mod.candidate_id_for("OUSG")
    return [{"fact_id": "fact-test-ousg-mgmt", "candidate_ids": [cid], "entity": "OUSG",
            "claim_type": "fee_management", "value": 0.0015, "ref": "https://docs.ondo.finance/test",
            "effective_from": "2026-10-04", "retrieved_at": "2026-10-04T00:00:00+00:00",
            "expires_at": None, "reviewed_by": "test-fixture-independent-review",
            # tail of ADR-564: the waiver end is the fact's structured `effective_until` (was a rwa.py constant)
            "effective_until": "2027-01-01T00:00:00+00:00"}]


def test_ousg_management_fee_component_is_not_measured_on_or_after_the_waiver_end_date(monkeypatch):
    """The live finding: 'waived until January 1, 2027' is cited only as free text — nothing in
    the fact itself is machine-readable past that date. Before the cutoff, the management-fee
    COMPONENT (paper_accounting_hints, independent of the expenses-cap question) is still a
    DOCUMENTED 0; on/after it, it must become NOT_MEASURED rather than silently keep reporting 0."""
    _patch_facts(monkeypatch, _ousg_mgmt_fact_never_expiring())
    before = rwa.paper_accounting_hints("OUSG", NOW)
    mgmt_before = before["entry_fee_components"][0]
    assert mgmt_before["kind"] == "management"
    assert mgmt_before["cell"]["state"] == c1.DOCUMENTED
    assert mgmt_before["cell"]["value"] == 0.0

    on_cutoff = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    after = rwa.paper_accounting_hints("OUSG", on_cutoff)
    mgmt_after = after["entry_fee_components"][0]
    assert mgmt_after["cell"]["state"] == c1.NOT_MEASURED
    assert mgmt_after["cell"]["value"] is None
    assert "effective_until" in mgmt_after["cell"]["reason"]  # tail of ADR-564: ended by the fact's own field

    just_before_cutoff = on_cutoff - timedelta(seconds=1)
    still_before = rwa.paper_accounting_hints("OUSG", just_before_cutoff)
    assert still_before["entry_fee_components"][0]["cell"]["state"] == c1.DOCUMENTED


def test_fact_effective_until_boundary():
    """Tail of ADR-564: the waiver-end boundary moved from rwa._ousg_waiver_expired (a literal) to the
    loader's structured `effective_until` — ended on/after the instant, naive `now` treated as UTC."""
    from spa_core.research_factory import registry_loader
    fact = {"effective_until": "2027-01-01T00:00:00+00:00"}
    assert registry_loader.has_ended(fact, datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)) is False
    assert registry_loader.has_ended(fact, datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)) is True
    assert registry_loader.has_ended(fact, datetime(2027, 6, 1)) is True
    assert registry_loader.has_ended({}, datetime(2030, 1, 1, tzinfo=timezone.utc)) is False
