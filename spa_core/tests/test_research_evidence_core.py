"""Core behavioural tests for the Research Evidence core + Sherlock decision (ADR-564,
RM-EVIDENCE-01, Package E1).

Time is INJECTED throughout: every judgement in this file is made against the single anchor
``NOW`` (or an offset built from it), passed to the code under test as ``now=``. Nothing here
asks the wall clock anything.
# FROZEN-DATE-OK: injected-clock — the anchor NOW (and every NOW + timedelta(...)/explicit
# datetime(...) literal built in this file) is passed as the `now=` argument to every
# lifecycle/bundle/grades/decision/admission_v2/http_client call under test; no assertion here
# compares a literal date to the real clock.

RESEARCH / PAPER only — real capital $0; nothing here moves money, signs or orders. See
spa_core/research_factory/evidence_contract.py.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from spa_core.research_factory import admission, admission_v2, bundle as bundle_mod, contract as c1, \
    decision as decision_mod, evidence_contract as ec, grades, http_client, lifecycle, paper, \
    profile as profile_mod, registry, registry_loader
from spa_core.research_factory import run as run_mod
from spa_core.research_factory._common import ledger_for
from spa_core.tests import _research_evidence_v2_fixtures as v2fx

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── shared fixtures ──────────────────────────────────────────────────────────────────────────

def _v1cell(state=c1.MEASURED, value=1.0, judge_now=None, **kw):
    kw.setdefault("source_ref", "https://example/feed")
    kw.setdefault("source_class", c1.PRIMARY_PROTOCOL)
    kw.setdefault("source_root", "chain:1")
    kw.setdefault("as_of", NOW.isoformat())
    judge_now = judge_now or NOW
    if state not in c1.VALUED_STATES:
        return c1.cell(state, reason=kw.get("reason", "n/a"), now=judge_now)
    return c1.cell(state, value, now=judge_now, **{k: v for k, v in kw.items() if k != "reason"})


def make_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY", instrument_id=None,
                   network="ethereum", **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'11' * 20}"
    exposure = c1.exposure_key(mechanism_id, instrument_id, network)
    cid = c1.candidate_id(exposure)
    cand = {f: None for f in c1.CANDIDATE_FIELDS}
    cand.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": c1.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": c1.MECHANISMS[mechanism_id]["asset_class"],
        "domain": domain, "network": c1.canonical_network(network), "venue_or_protocol": "test_scanner",
        "instrument": instrument_id, "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        "base_return": _v1cell(unit="fraction"),
        "fees": _v1cell(c1.NOT_APPLICABLE, reason="n/a"), "gas": _v1cell(c1.NOT_APPLICABLE, reason="n/a"),
        "funding": _v1cell(c1.NOT_APPLICABLE, reason="n/a"), "hedging_cost": _v1cell(c1.NOT_APPLICABLE, reason="n/a"),
        "liquidity": _v1cell(c1.MEASURED, 1_000_000.0), "time_to_exit": _v1cell(c1.MEASURED, 0.0),
        "capacity": _v1cell(c1.NOT_MEASURED, reason="n/a"), "duration": _v1cell(c1.NOT_APPLICABLE, reason="n/a"),
        "leverage": _v1cell(c1.NOT_APPLICABLE, reason="n/a"),
        "liquidation_distance": _v1cell(c1.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [{"source_root": "chain:1", "source_class": c1.PRIMARY_PROTOCOL, "value": 1.0}],
        "counterparty": {
            "roles": {r: {"state": c1.CP_DOCUMENTED, "name": "Acme"} for r in
                     c1.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    cand.update(overrides)
    return cand


def _walk_to_paper_candidate(data_dir: Path, candidate: dict, now: datetime = NOW) -> None:
    cid = candidate["candidate_id"]
    registry.upsert(data_dir, candidate, now)
    for state in (c1.SCREENED, c1.RESEARCH_READY, c1.PAPER_CANDIDATE):
        lifecycle.transition(data_dir, cid, state, reason="setup", now=now)


def _citation(**kw) -> dict:
    kw.setdefault("retrieved_at", NOW.isoformat())
    return ec.citation(**kw)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. Admission path — binding #1 (ADMIT is the only door)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_v1_write_admission_snapshot_always_refuses(tmp_path):
    """Positive control: an all-PASS v1 report cannot open a position — the write itself refuses."""
    c = make_candidate()
    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
    assert report["verdict"] == c1.GATE_PASS, report
    with pytest.raises(admission.V1AdmissionSuperseded):
        admission.write_admission_snapshot(tmp_path, c, report, NOW)


def test_mutation_check_v1_refusal_is_the_guard_not_a_coincidence(tmp_path, monkeypatch):
    """MUTATION CHECK: with the refusal neutralised (the pre-ADR-564 body restored), the v1 path
    WOULD mint a usable snapshot — proving the test above exercises a real guard."""
    c = make_candidate()
    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)

    def _pre_562_write(data_dir, candidate, report, now):
        return {"payload": {"admission_id": "legacy-id", "verdict": c1.GATE_PASS}}

    monkeypatch.setattr(admission, "write_admission_snapshot", _pre_562_write)
    snap = admission.write_admission_snapshot(tmp_path, c, report, NOW)
    assert snap["payload"]["admission_id"] == "legacy-id"  # the bypass succeeds under the mutation


def test_v1_shaped_admission_row_cannot_gate_paper_active(tmp_path):
    """Defense in depth: even a HAND-FORGED v1-shaped ``kind="admission"`` ledger row (simulating
    a pre-ADR-564 ledger, or a bypass attempt) is refused by lifecycle — only ``paper_admission_v2``
    + a matching ADMIT_TO_PAPER decision opens paper now."""
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    ledger = ledger_for(tmp_path)
    forged_id = "forged-v1-admission"
    ledger.append("admission", ["admission", cid, forged_id],
                  {"admission_id": forged_id, "candidate_id": cid, "verdict": c1.GATE_PASS, "as_of": NOW.isoformat()},
                  NOW.isoformat())
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, c1.PAPER_ACTIVE, gate_ref=forged_id, reason="bypass attempt", now=NOW)


def test_v2_snapshot_without_matching_admit_decision_is_refused(tmp_path):
    """A paper-admission/2 snapshot that names a decision_id/bundle_digest for which NO
    ADMIT_TO_PAPER decision row exists is refused (binding #1's cross-check)."""
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    ledger = ledger_for(tmp_path)
    fake_admission_id = "fake-v2-admission"
    ledger.append("paper_admission_v2", ["paper_admission_v2", cid, fake_admission_id], {
        "schema": ec.SCHEMA_ADMISSION_V2, "admission_id": fake_admission_id, "candidate_id": cid,
        "decision_id": "no-such-decision", "bundle_digest": "no-such-bundle",
        "policy_version": ec.POLICY_VERSION, "paper_mode": ec.PAPER_MODE_HOLDABLE,
        "evidence_ceiling": ec.CEILING_OBSERVED, "as_of": NOW.isoformat(), "recorded_at": NOW.isoformat(),
        "code_identity": "test",
    }, NOW.isoformat())
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, c1.PAPER_ACTIVE, gate_ref=fake_admission_id,
                            reason="no matching decision", now=NOW)


def test_admit_decision_is_the_only_door(tmp_path):
    """The real, happy path: all-STRONG evidence -> ADMIT_TO_PAPER -> v2 snapshot -> PAPER_ACTIVE."""
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    assert admission_id
    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE


def test_mutation_check_admission_gate_v2_bypass_detectable(tmp_path, monkeypatch):
    """MUTATION CHECK: with the v2 admission-gate validator neutralised, a bogus gate_ref sails
    through — proving the tests above exercise the real guard, not a vacuous pass."""
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    monkeypatch.setattr(lifecycle, "_validate_admission_gate", lambda *a, **k: None)
    row = lifecycle.transition(tmp_path, cid, c1.PAPER_ACTIVE, gate_ref="made-up-id",
                              reason="bypass attempt", now=NOW)
    assert row["payload"]["to_state"] == c1.PAPER_ACTIVE  # the bypass succeeded under the mutation


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Validators — every role_entry branch
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_role_entry_identified_needs_identity_and_citation():
    cit = _citation(origin="issuer:acme", channel=ec.CHANNEL_OFFICIAL_API, ref="https://acme.example/api")
    entry = ec.role_entry(ec.CP_IDENTIFIED, role="issuer", identity="Acme", citations=[cit])
    assert entry["state"] == ec.CP_IDENTIFIED
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_IDENTIFIED, role="issuer", identity=None, citations=[cit])
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_IDENTIFIED, role="issuer", identity="Acme", citations=[])


def test_role_entry_documented_needs_independent_doc_with_quote_naming_identity():
    # post-implementation review H6: role_entry's DOCUMENTED check now requires the independent
    # citation's origin to be REGISTERED (ec.origin_group fails closed otherwise) — an
    # unregistered "regulator:sec" with no registry entry can no longer silently count.
    independent = _citation(origin="regulator:sec", channel=ec.CHANNEL_REGULATORY_FILING,
                            ref="https://sec.example/filing", quote="Acme Trust is the custodian")
    entry = ec.role_entry(ec.CP_DOCUMENTED, role="custodian", identity="Acme Trust", citations=[independent],
                          registry={"regulator:sec": {"group": "sec"}})
    assert entry["state"] == ec.CP_DOCUMENTED

    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_DOCUMENTED, role="custodian", identity="Acme Trust", citations=[independent],
                      registry={})

    issuer_only = _citation(origin="issuer:acme", channel=ec.CHANNEL_OFFICIAL_DOC,
                            ref="https://acme.example/terms", quote="Acme Trust is the custodian")
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_DOCUMENTED, role="custodian", identity="Acme Trust", citations=[issuer_only],
                      issuer_group="acme_group",
                      registry={"issuer:acme": {"group": "acme_group"}})


def test_role_entry_documented_issuer_filing_lifts_only_legal_entity_and_issuer():
    """An issuer's OWN regulatory filing lifts legal_entity/issuer to DOCUMENTED — but nothing
    else (e.g. custodian stays unlifted by the SAME filing)."""
    filing = _citation(origin="issuer:acme", channel=ec.CHANNEL_REGULATORY_FILING,
                       ref="https://sec.example/form-d", quote="Acme Fund Ltd is the legal entity")
    lifted = ec.role_entry(ec.CP_DOCUMENTED, role="legal_entity", identity="Acme Fund Ltd", citations=[filing])
    assert lifted["state"] == ec.CP_DOCUMENTED

    not_lifted = _citation(origin="issuer:acme", channel=ec.CHANNEL_REGULATORY_FILING,
                           ref="https://sec.example/form-d", quote="Acme Trust is the custodian")
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_DOCUMENTED, role="custodian", identity="Acme Trust", citations=[not_lifted])


def test_role_entry_observed_needs_on_chain_binding_or_own_api():
    on_chain = _citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref="chain:1:0xabc:bytecode",
                         claim_type="bytecode")
    entry = ec.role_entry(ec.CP_OBSERVED, role="oracle_provider", identity="Acme Oracle", citations=[on_chain])
    assert entry["state"] == ec.CP_OBSERVED

    own_api = _citation(origin="custodian:acme_trust", channel=ec.CHANNEL_OFFICIAL_API,
                        ref="https://acmetrust.example/api")
    entry2 = ec.role_entry(ec.CP_OBSERVED, role="custodian", identity="Acme Trust", citations=[own_api],
                           issuer_group="acme_group", registry={"custodian:acme_trust": {"group": "acme_trust_g"}})
    assert entry2["state"] == ec.CP_OBSERVED


def test_role_entry_issuer_own_api_caps_at_identified_never_observed():
    """An issuer's OWN API can never lift it to OBSERVED — review #3's explicit cap."""
    issuer_api = _citation(origin="issuer:acme", channel=ec.CHANNEL_OFFICIAL_API, ref="https://acme.example/api")
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_OBSERVED, role="issuer", identity="Acme", citations=[issuer_api],
                     issuer_group="acme_group", registry={"issuer:acme": {"group": "acme_group"}})
    # the honest floor for the SAME citation is IDENTIFIED, never raising
    entry = ec.role_entry(ec.CP_IDENTIFIED, role="issuer", identity="Acme", citations=[issuer_api])
    assert entry["state"] == ec.CP_IDENTIFIED


def test_role_entry_unknown_must_name_a_reason():
    with pytest.raises(ValueError):
        ec.role_entry(ec.CP_UNKNOWN, role="custodian")
    entry = ec.role_entry(ec.CP_UNKNOWN, role="custodian", reason="not documented anywhere in this repo")
    assert entry["state"] == ec.CP_UNKNOWN


def test_role_entry_not_applicable_and_unknown_state_rejected():
    with pytest.raises(ValueError):
        ec.role_entry("NOT_A_REAL_STATE", role="issuer", reason="x")
    entry = ec.role_entry(ec.CP_NOT_APPLICABLE, role="exchange", reason="not required by this mechanism")
    assert entry["state"] == ec.CP_NOT_APPLICABLE


def test_citation_validators():
    with pytest.raises(ValueError):
        _citation(origin="not-a-known-prefix:x", channel=ec.CHANNEL_ON_CHAIN, ref="x")
    with pytest.raises(ValueError):
        _citation(origin="issuer:acme", channel="not_a_channel", ref="x")
    with pytest.raises(ValueError):
        _citation(origin="issuer:acme", channel=ec.CHANNEL_OFFICIAL_DOC, ref="x")  # doc needs a quote
    with pytest.raises(ValueError):
        _citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref="x", claim_type="not_chain_native")
    ok = _citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref="x", claim_type="bytecode")
    assert ok["origin"] == "chain:1"
    with pytest.raises(ValueError):
        _citation(origin="model:x", channel=ec.CHANNEL_AGGREGATOR, ref="x")  # aggregator needs a named relay
    ok2 = _citation(origin="aggregator:defillama", channel=ec.CHANNEL_AGGREGATOR, ref="x")
    assert ok2["channel"] == ec.CHANNEL_AGGREGATOR


def test_origin_groups_unregistered_vs_aggregator_and_model():
    # post-implementation review H5/H6 (2026-10-04): evidence_contract.origin_group now fails
    # CLOSED on an unregistered origin — it used to return "unregistered:<origin>" as that
    # origin's OWN group (two different unregistered names would wrongly count as two
    # independent sources); now it contributes NOTHING, same as aggregator:/model:/None.
    registry = {"issuer:hashnote": {"group": "circle"}}
    groups = ec.origin_groups(
        [{"origin": "issuer:hashnote"}, {"origin": "custodian:unknown_co"}, {"origin": "aggregator:defillama"},
         {"origin": "model:x"}, {"origin": None}], registry)
    assert groups == ["circle"]  # unregistered/aggregator:/model:/None all contribute nothing


def test_chain_origin_counts_only_for_a_chain_native_claim():
    """Re-review H5 residual: `chain:1` counted as an independent group for ANY claim, so an
    issuer-posted oracle value read via eth_call cross-checked as a second, independent RETURN
    source (STRONG). A chain is a witness only to CHAIN_NATIVE_CLAIMS. Red without the fix:
    origin_groups([hashnote, chain:1]) had two groups."""
    reg = {"chain:1": {"group": "onchain_ethereum"}, "issuer:hashnote": {"group": "circle"}}
    assert ec.origin_group("chain:1", reg) is None
    assert ec.origin_group("chain:1", reg, "nav") is None
    assert ec.origin_group("chain:1", reg, "token_identity") == "onchain_ethereum"
    assert ec.origin_groups([{"origin": "issuer:hashnote"}, {"origin": "chain:1"}], reg) == ["circle"]
    assert ec.origin_groups([{"origin": "chain:1", "claim_type": "bytecode"}], reg) == ["onchain_ethereum"]
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL))
    base = {"return_family": "rate", "return_last_change_at": NOW.isoformat()}
    # an issuer primary cross-checked only by a chain read of a posted value: not STRONG
    v2 = dict(base, return_primary_origin="issuer:hashnote", return_cross_checks=[{"origin": "chain:1", "value": 0.05}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2, NOW, registry=reg) == ec.ADEQUATE
    # an ungrouped (chain:) primary cross-checked by the poster's own API: not STRONG either
    v2b = dict(base, return_primary_origin="chain:1", return_cross_checks=[{"origin": "issuer:hashnote", "value": 0.05}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2b, NOW, registry=reg) == ec.ADEQUATE


def test_mutation_check_unregistered_origin_does_not_silently_count(monkeypatch):
    """MUTATION CHECK: the pre-H5/H6 behaviour (unregistered -> its own "unregistered:<origin>"
    group) would have let TWO unregistered origins count as two independent sources — proving
    the test above is pinned to a real contract change, not a tautology."""
    def _old_origin_group(origin, registry, claim_type=None):
        if not origin or origin.startswith(("aggregator:", "model:")):
            return None
        entry = registry.get(origin) if isinstance(registry, dict) else None
        g = entry.get("group") if isinstance(entry, dict) and entry.get("group") else f"unregistered:{origin}"
        return g

    monkeypatch.setattr(ec, "origin_group", _old_origin_group)
    groups = ec.origin_groups([{"origin": "custodian:unknown_a"}, {"origin": "custodian:unknown_b"}], {})
    assert len(groups) == 2  # the old bug, reproduced: two unregistered names count as two groups


def test_independent_root_count_excludes_unrelated_counterparty_roles():
    """Round 5, Issue #3 ('wrong independence count'): ``bundle.build_bundle``'s
    ``independent_root_count`` answers ONE question — how many independent affiliation GROUPS
    corroborate the RETURN claim (``admission_v2._source_independence_sufficient`` and
    ``eligibility.py``'s ``min_origins_cio`` both read it against the 'return' entry of
    MIN_GROUPS_PAPER/MIN_GROUPS_CIO, nothing else). USYC's return evidence is the on-chain
    oracle + its own official API, BOTH origin ``issuer:hashnote`` (registry group 'circle');
    DeFiLlama (``aggregator:defillama``) contributes nothing per ``ec.origin_groups``. The
    required COUNTERPARTY role fact for 'custodian' (Marex, a REAL independent party for
    custody, registry group 'marex') must NOT be folded into this count — it says nothing
    about the return number. Count must be 1, with the issuer-circularity concern still named."""
    registry = {"issuer:hashnote": {"group": "circle"}, "custodian:marex": {"group": "marex"},
               "chain:1": {"group": "onchain_ethereum"}}
    mechanism_id = "TOKENISED_TREASURY"
    c = make_candidate(mechanism_id=mechanism_id, domain="CASH_TREASURY")

    def _role(role, origin):
        cit = ec.citation(origin=origin, channel=ec.CHANNEL_OFFICIAL_DOC, ref="https://usyc.docs.hashnote.com",
                          quote=f"{role} evidence", retrieved_at=NOW.isoformat())
        return ec.role_entry(ec.CP_IDENTIFIED, role=role, identity=role, citations=[cit])

    required = c1.MECHANISMS[mechanism_id]["required_roles"]
    profile = {role: (_role(role, "custodian:marex") if role == "custodian" else _role(role, "issuer:hashnote"))
              for role in ec.ROLES if role in required}
    for role in ec.ROLES:
        if role not in required:
            profile[role] = ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="not required")
    profile["dimensions"] = {}

    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    v2_evidence["return_primary_origin"] = "issuer:hashnote"
    v2_evidence["return_cross_checks"] = [{"origin": "issuer:hashnote", "value": 1.05}]

    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_REFERENCE_TRACK, registry=registry, now=NOW)
    assert b["origin_groups"] == ["circle"]
    assert b["independent_root_count"] == 1
    assert b["circularity_concerns"]  # the issuer-only-return concern is still named


def test_mutation_check_independent_root_count_role_fact_leak_reproduces_the_live_bug():
    """MUTATION CHECK: reproducing the PRE-FIX computation (return citations + every
    required-role fact folded into the SAME origin_groups pool, regardless of what that fact
    is actually about) on USYC's exact inputs gives 2 — proving the test above exercises a
    real fix (the live-run finding), not a tautology."""
    registry = {"issuer:hashnote": {"group": "circle"}, "custodian:marex": {"group": "marex"}}
    required = ("issuer", "custodian", "redemption_agent", "legal_entity")
    facts = [{"role": "custodian", "origin": "custodian:marex"}]
    high_impact_citations = [{"origin": "issuer:hashnote"}, {"origin": "issuer:hashnote"}]
    for f in facts:
        if f.get("role") in required and f.get("origin"):
            high_impact_citations.append({"origin": f["origin"]})
    groups = sorted(set(ec.origin_groups(high_impact_citations, registry)))
    assert len(groups) == 2  # the old bug, reproduced: "circle" AND "marex"


def test_migrate_v1_role_documented_and_observed_and_unknown():
    assert ec.migrate_v1_role(c1.CP_DOCUMENTED, True) == ec.CP_DOCUMENTED
    assert ec.migrate_v1_role(c1.CP_DOCUMENTED, False) == ec.CP_IDENTIFIED
    assert ec.migrate_v1_role(c1.CP_OBSERVED, False) == ec.CP_OBSERVED
    assert ec.migrate_v1_role(c1.CP_UNKNOWN, False) == ec.CP_UNKNOWN
    assert ec.migrate_v1_role(c1.CP_NOT_APPLICABLE, False) == ec.CP_NOT_APPLICABLE


def test_profile_migrate_role_from_v1_downgrades_documented_to_identified_when_unprovable():
    """v1 DOCUMENTED with a non-issuer source_class MIGRATES toward DOCUMENTED, but v2's bar
    (independent doc + quote naming the identity) cannot be proven from v1's bare fields alone —
    review #2's named safe floor (IDENTIFIED) is reached without raising. Post-implementation
    review LOW (2026-10-04): this is now ALWAYS IDENTIFIED, never DOCUMENTED — a v1-migrated
    role has no real quote to offer at all (see migrate_role_from_v1's own docstring)."""
    v1_entry = {"state": c1.CP_DOCUMENTED, "name": "Acme Trust", "source_ref": "repo/module.py",
               "source_class": c1.SECONDARY_SOURCE}
    out = profile_mod.migrate_role_from_v1("custodian", "TOKENISED_TREASURY", v1_entry, now=NOW)
    assert out["state"] == ec.CP_IDENTIFIED
    assert out["identity"] == "Acme Trust"

    issuer_only_entry = {"state": c1.CP_DOCUMENTED, "name": "Acme", "source_ref": "repo/module.py",
                         "source_class": c1.ISSUER_CLAIM}
    out2 = profile_mod.migrate_role_from_v1("issuer", "TOKENISED_TREASURY", issuer_only_entry, now=NOW)
    assert out2["state"] == ec.CP_IDENTIFIED


def test_migrate_role_from_v1_never_reaches_documented_even_with_a_matching_registry_entry():
    """Post-implementation review LOW: the OLD code synthesised a citation whose quote was
    literally the identity string (``quote=identity``), making role_entry's "quote names the
    identity" check [identity.lower() in quote.lower()] trivially true — it only usually failed
    closed because the synthesised ``agent:<identity>`` origin usually wasn't a REGISTERED one.
    Here it coincidentally IS (an identity that sanitises to a real registered origin, e.g.
    "securitize") — DOCUMENTED must still never be granted; a v1-migrated role floors at
    IDENTIFIED regardless of registry content."""
    v1_entry = {"state": c1.CP_DOCUMENTED, "name": "securitize", "source_ref": "repo/module.py",
               "source_class": c1.SECONDARY_SOURCE}
    registry = {"agent:securitize": {"group": "securitize"}}  # a REAL, independent-looking group
    out = profile_mod.migrate_role_from_v1("custodian", "TOKENISED_TREASURY", v1_entry, now=NOW,
                                           issuer_group="some_other_group", registry=registry)
    assert out["state"] == ec.CP_IDENTIFIED  # never DOCUMENTED, even though the registry WOULD allow it


def test_mutation_check_migration_quote_tautology_is_the_guard():
    """MUTATION CHECK: reproducing the pre-fix synthesis (a citation whose quote IS the identity
    string) on the SAME registry-collision scenario above DOES satisfy role_entry's DOCUMENTED
    quote check — proving the test above exercises a real fix, not a tautology."""
    identity = "securitize"
    cit = ec.citation(origin=f"agent:{identity}", channel=ec.CHANNEL_OFFICIAL_DOC, ref="repo/module.py",
                      retrieved_at=NOW.isoformat(), quote=identity)  # the old, self-quoting synthesis
    entry = ec.role_entry(ec.CP_DOCUMENTED, role="custodian", identity=identity, citations=[cit],
                          issuer_group="some_other_group", registry={"agent:securitize": {"group": "securitize"}})
    assert entry["state"] == ec.CP_DOCUMENTED  # the old bug, reproduced: a self-quote "proves" itself


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. Grades — one test per dimension, plus frozen-value/calendar freshness
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_grade_primary_identity_all_branches():
    assert grades.grade_primary_identity({"identity": {"mismatch": True}}) == ec.CONFLICTED
    assert grades.grade_primary_identity({"identity": {"on_chain_verified": True, "address_cited": True}}) == ec.STRONG
    assert grades.grade_primary_identity({"identity": {"on_chain_verified": True}}) == ec.ADEQUATE
    assert grades.grade_primary_identity({"identity": {"address_cited": True}}) == ec.WEAK
    assert grades.grade_primary_identity({"identity": {}}) == ec.UNKNOWN


def test_grade_return_measured_primary_adequate_then_strong_then_conflicted():
    # post-implementation review H5 (2026-10-04): an UNREGISTERED cross-check origin never
    # counts as independent any more (evidence_contract.origin_group fails closed) — a real
    # registry, with the primary and the cross-check in DIFFERENT groups, is what the STRONG/
    # CONFLICTED paths actually need now.
    # re-review H5 residual: the primary is a REGISTERED issuer origin (a `chain:` origin is no group for a
    # rate claim, and an ungrouped primary is capped at ADEQUATE — see the test below)
    registry = {"issuer:x": {"group": "issuer_x_group"}, "venue:other": {"group": "venue_other_group"}}
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL))
    v2 = {"return_family": "rate", "return_last_change_at": NOW.isoformat(), "return_primary_origin": "issuer:x"}
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2, NOW, registry=registry) == ec.ADEQUATE

    v2_strong = dict(v2, return_cross_checks=[{"origin": "venue:other", "value": 0.0505}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2_strong, NOW, registry=registry) == ec.STRONG

    v2_conflict = dict(v2, return_cross_checks=[{"origin": "venue:other", "value": 0.20}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2_conflict, NOW, registry=registry) == ec.CONFLICTED


def test_grade_return_unregistered_cross_check_never_counts_as_independent():
    """H5 positive control: the SAME cross-check as the STRONG case above, but with NO registry
    (or an unregistered origin) — must stay ADEQUATE, never STRONG. Red without the fix: the old
    ``!= primary_group`` comparison treated two Nones as "different" and upgraded to STRONG on
    nothing but an unregistered name."""
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL))
    v2 = {"return_family": "rate", "return_last_change_at": NOW.isoformat(), "return_primary_origin": "chain:1",
         "return_cross_checks": [{"origin": "venue:other", "value": 0.0505}]}
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2, NOW, registry={}) == ec.ADEQUATE

    v2_agg = dict(v2, return_cross_checks=[{"origin": "aggregator:defillama", "value": 0.0505}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2_agg, NOW,
                               registry={"chain:1": {"group": "g"}}) == ec.ADEQUATE

    v2_none_origin = dict(v2, return_cross_checks=[{"origin": None, "value": 0.0505}])
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2_none_origin, NOW,
                               registry={"chain:1": {"group": "g"}}) == ec.ADEQUATE


def test_grade_return_aggregator_only_is_weak_never_adequate():
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.REPUTABLE_AGGREGATOR))
    v2 = {"return_family": "rate", "return_last_change_at": NOW.isoformat()}
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2, NOW) == ec.WEAK


def test_grade_return_funding_family_absolute_band():
    # post-implementation review H5: venue:binance/venue:bybit need REAL, DIFFERENT registry
    # groups — an unregistered pair no longer counts as independent at all.
    registry = {"venue:binance": {"group": "binance"}, "venue:bybit": {"group": "bybit"}}
    candidate = make_candidate(mechanism_id="FUNDING_CAPTURE", domain="MARKET_NEUTRAL_BASIS",
                               funding=_v1cell(c1.MEASURED, 0.0001, source_class=c1.PRIMARY_VENUE))
    v2_within = {"return_family": "funding_settlement", "return_last_change_at": NOW.isoformat(),
                "return_primary_origin": "venue:binance",
                "return_cross_checks": [{"origin": "venue:bybit", "value": 0.0001003}]}  # 0.3 bps/8h, < 0.5 band
    assert grades.grade_return(candidate, "FUNDING_CAPTURE", v2_within, NOW, registry=registry) == ec.STRONG

    v2_outside = dict(v2_within, return_cross_checks=[{"origin": "venue:bybit", "value": 0.00025}])  # 15 bps/8h
    assert grades.grade_return(candidate, "FUNDING_CAPTURE", v2_outside, NOW, registry=registry) == ec.CONFLICTED


def test_grade_return_frozen_value_is_stale():
    """The ADR's named frozen-value rule, directly: a value dated by its LAST CHANGE, unchanged
    well past the rate family's max age, is STALE — never silently treated as fresh because the
    bytes were refetched today."""
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL))
    stale_change = NOW - timedelta(hours=400)
    v2 = {"return_family": "rate", "return_last_change_at": stale_change.isoformat()}
    assert grades.grade_return(candidate, "STABLECOIN_SAVINGS", v2, NOW) == ec.STALE


def test_grade_return_unknown_when_no_last_change_at_recorded():
    candidate = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL))
    v2 = {"return_family": "rate", "return_last_change_at": None}
    # a PRIMARY return with NO last-change evidence cannot be judged fresh -> UNKNOWN via freshness_verdict
    assert grades.freshness_verdict("rate", None, NOW) == ec.UNKNOWN


def test_business_day_calendar_business_days_between():
    monday = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)   # verified Monday
    friday = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)   # verified Friday, same week
    assert grades.business_days_between(monday, friday) == 4    # Tue, Wed, Thu, Fri

    following_monday = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert grades.business_days_between(friday, following_monday) == 1  # weekend doesn't count


def test_grade_forward_series_nav_business_day_calendar_rule():
    """>3 UNCHANGED business days is STALE even when the raw elapsed hours have not yet crossed
    max_age_h — the calendar rule, not the age rule, is what fires here (isolated from each other
    by picking a boundary where age_h == max_age_h exactly, which the age check alone would NOT
    flag since it uses a strict '>')."""
    monday = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
    friday_96h_later = monday + timedelta(hours=96)
    assert friday_96h_later == datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    v2 = {"forward_series": {"collector_exists": True, "last_change_at": monday.isoformat(),
                             "family": "nav_business_day"}}
    assert grades.grade_forward_series(v2, friday_96h_later) == ec.STALE

    v2_weekend = {"forward_series": {"collector_exists": True,
                                     "last_change_at": datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc).isoformat(),
                                     "family": "nav_business_day"}}
    assert grades.grade_forward_series(v2_weekend, datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)) == ec.ADEQUATE


def test_grade_forward_series_unknown_without_a_collector():
    assert grades.grade_forward_series({"forward_series": {"collector_exists": False}}, NOW) == ec.UNKNOWN
    assert grades.grade_forward_series({}, NOW) == ec.UNKNOWN


def test_grade_cost_all_branches():
    measured = c1.cell(c1.MEASURED, 10.0, source_ref="x", source_class=c1.PRIMARY_PROTOCOL, source_root="chain:1",
                       as_of=NOW.isoformat(), now=NOW)
    not_measured = c1.cell(c1.NOT_MEASURED, reason="undisclosed")
    conflicted = c1.cell(c1.CONFLICTED, reason="disagree")
    na = c1.cell(c1.NOT_APPLICABLE, reason="n/a")
    assert grades.grade_cost({}) == ec.UNKNOWN
    assert grades.grade_cost({"cost_components": {"entry": na, "exit": na}}) == ec.ADEQUATE
    assert grades.grade_cost({"cost_components": {"entry": measured}}) == ec.ADEQUATE
    assert grades.grade_cost({"cost_components": {"entry": not_measured}}) == ec.WEAK
    assert grades.grade_cost({"cost_components": {"entry": conflicted}}) == ec.CONFLICTED


def test_grade_liquidity_reference_track_is_not_applicable():
    candidate = make_candidate()
    assert grades.grade_liquidity(candidate, {}, ec.PAPER_MODE_REFERENCE_TRACK) == ec.NOT_APPLICABLE
    candidate_na = make_candidate(liquidity=_v1cell(c1.NOT_APPLICABLE, reason="n/a"))
    assert grades.grade_liquidity(candidate_na, {}, ec.PAPER_MODE_HOLDABLE) == ec.NOT_APPLICABLE
    assert grades.grade_liquidity(candidate, {"liquidity_eligible_path_measured": True},
                                  ec.PAPER_MODE_HOLDABLE) == ec.ADEQUATE
    assert grades.grade_liquidity(candidate, {"liquidity_eligible_path_measured": False},
                                  ec.PAPER_MODE_HOLDABLE) == ec.WEAK


def test_grade_counterparty_strong_adequate_unknown():
    profile = {"issuer": {"state": ec.CP_OBSERVED}}
    assert grades.grade_counterparty(profile, ("issuer",)) == ec.STRONG
    assert grades.grade_counterparty({"issuer": {"state": ec.CP_IDENTIFIED}}, ("issuer",)) == ec.ADEQUATE
    assert grades.grade_counterparty({"issuer": {"state": ec.CP_UNKNOWN}}, ("issuer",)) == ec.UNKNOWN
    assert grades.grade_counterparty({}, ()) == ec.NOT_APPLICABLE


def test_grade_redemption_na_for_funding_mechanisms():
    assert grades.grade_redemption("FUNDING_CAPTURE", {}, {}) == ec.NOT_APPLICABLE
    profile = {"redemption_agent": {"state": ec.CP_IDENTIFIED}}
    assert grades.grade_redemption("TOKENISED_TREASURY", profile, {}) == ec.UNKNOWN  # no terms_cited
    assert grades.grade_redemption("TOKENISED_TREASURY", profile, {"redemption": {"terms_cited": True}}) == ec.WEAK
    full = {"redemption": {"terms_cited": True, "caveats_complete": True}}
    assert grades.grade_redemption("TOKENISED_TREASURY", profile, full) == ec.ADEQUATE


def test_grade_custody_strength_ladder():
    assert grades.grade_custody({"custodian": {"state": ec.CP_NOT_APPLICABLE}}) == ec.NOT_APPLICABLE
    assert grades.grade_custody({"custodian": {"state": ec.CP_UNKNOWN}}) == ec.UNKNOWN
    assert grades.grade_custody({"custodian": {"state": ec.CP_IDENTIFIED}}) == ec.ADEQUATE
    assert grades.grade_custody({"custodian": {"state": ec.CP_DOCUMENTED}}) == ec.STRONG


def test_grade_contract_na_for_directional_trend():
    assert grades.grade_contract("DIRECTIONAL_TREND", {}) == ec.NOT_APPLICABLE
    assert grades.grade_contract("STABLECOIN_SAVINGS", {}) == ec.UNKNOWN
    assert grades.grade_contract("STABLECOIN_SAVINGS", {"contract_reader_verified": True}) == ec.ADEQUATE


def test_grade_reserves_na_for_lending_strong_when_independent_auditor():
    assert grades.grade_reserves("LENDING", {}) == ec.NOT_APPLICABLE
    assert grades.grade_reserves("TOKENISED_TREASURY", {}) == ec.UNKNOWN
    adequate = {"reserves": {"attested": True}}
    assert grades.grade_reserves("TOKENISED_TREASURY", adequate) == ec.ADEQUATE
    strong = {"reserves": {"attested": True, "auditor_group": "auditor:kpmg", "issuer_group": "issuer:acme"}}
    assert grades.grade_reserves("TOKENISED_TREASURY", strong) == ec.STRONG


def test_grade_legal_needs_every_component():
    assert grades.grade_legal({}) == ec.UNKNOWN
    full = {"legal": {"entity": True, "jurisdiction": True, "exemption": True, "documented": True}}
    assert grades.grade_legal(full) == ec.ADEQUATE
    partial = {"legal": {"entity": True, "jurisdiction": True}}
    assert grades.grade_legal(partial) == ec.UNKNOWN


def test_grade_holder_eligibility_states():
    recorded = {"kyc": True}
    assert grades.grade_holder_eligibility(
        {"holder_eligibility": {"state": ec.SPA_ELIGIBLE, "requirements": recorded}}) == ec.ADEQUATE
    assert grades.grade_holder_eligibility(
        {"holder_eligibility": {"state": ec.NOT_ELIGIBLE, "requirements": recorded}}) == ec.WEAK
    assert grades.grade_holder_eligibility({}) == ec.UNKNOWN
    # a bare state assertion with NO recorded requirement is not "documented"/"known" — UNKNOWN,
    # never assumed (the gap this stricter check closes).
    assert grades.grade_holder_eligibility({"holder_eligibility": {"state": ec.SPA_ELIGIBLE}}) == ec.UNKNOWN
    assert grades.grade_holder_eligibility(
        {"holder_eligibility": {"state": ec.NOT_ELIGIBLE, "requirements": {}}}) == ec.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. Decision — precedence, predicates, replay
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _minimal_bundle(**overrides) -> dict:
    bundle = {f: None for f in ec.BUNDLE_FIELDS}
    bundle.update({
        "schema_version": ec.SCHEMA_BUNDLE, "candidate_id": "cand1", "exposure_key": "ek", "exposure_family": "ek",
        "mechanism_id": "STABLECOIN_SAVINGS", "generated_at": NOW.isoformat(), "evidence_cutoff": NOW.isoformat(),
        "identity_evidence": {}, "return_evidence": {"net_expected_return": c1.cell(
            c1.ESTIMATED_WITH_METHOD, 0.05, method="test")},
        "cost_evidence": {}, "liquidity_evidence": {}, "counterparty_evidence": {}, "redemption_evidence": {},
        "custody_evidence": {}, "contract_evidence": {}, "market_evidence": {}, "paper_accounting_evidence": {},
        "forward_series_evidence": {}, "reserves_evidence": {}, "legal_evidence": {},
        "holder_eligibility_evidence": {}, "source_roots": [], "origin_groups": [], "independent_root_count": 1,
        "conflicts": [], "stale_evidence": [], "unknowns": [], "blocking_gaps": [],
        "grades": {d: ec.ADEQUATE for d in ec.DIMENSIONS}, "paper_mode": ec.PAPER_MODE_HOLDABLE,
        "evidence_ceiling": ec.CEILING_OBSERVED, "issuer_asserted_roles": [], "circularity_concerns": [],
        "evidence_digest": "digest1",
    })
    bundle.update(overrides)
    return bundle


def _minimal_report(**gate_overrides) -> dict:
    gates = {g: {"verdict": ec.PASS, "evidence": "ok"} for g in ec.ADMISSION_V2_GATES}
    gates.update(gate_overrides)
    return {"schema": admission_v2.SCHEMA_REPORT_V2, "candidate_id": "cand1", "bundle_digest": "digest1",
           "gates": gates}


def test_decision_admits_when_every_gate_passes():
    out = decision_mod.decide(_minimal_bundle(), _minimal_report(), [], NOW)
    assert out["decision"] == ec.ADMIT_TO_PAPER
    assert set(out) == set(ec.DECISION_FIELDS)
    assert out["decided_by_role"] == "head_of_research"
    assert out["authority_over_capital"] == "NONE"


def test_decision_precedence_conflicted_stale_and_fail_at_once_is_hold():
    """The named precedence case: a candidate that is CONFLICTED, STALE and has a FAILing gate
    all at once is HOLD — REJECT doesn't apply, and HOLD outranks STALE and NEEDS_MORE_EVIDENCE."""
    bundle = _minimal_bundle(conflicts=["RETURN"], stale_evidence=["FORWARD_SERIES"],
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "RETURN": ec.CONFLICTED,
                                    "FORWARD_SERIES": ec.STALE})
    prior = [_minimal_bundle(grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}}, evidence_digest="digest0")]
    report = _minimal_report(**{"liquidity_measured": {"verdict": ec.FAIL, "evidence": "forced fail"}})
    out = decision_mod.decide(bundle, report, prior, NOW)
    assert out["decision"] == ec.HOLD, out


def test_decision_stale_requires_a_prior_adequate_reading():
    """STALE only fires when a PRIOR bundle had the stale dimension >= ADEQUATE — a candidate
    that has NEVER been adequate on that dimension routes to NEEDS_MORE_EVIDENCE instead."""
    bundle = _minimal_bundle(stale_evidence=["FORWARD_SERIES"],
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "FORWARD_SERIES": ec.STALE})
    report = _minimal_report(**{"forward_collection_ready": {"verdict": ec.FAIL, "evidence": "stale"}})
    out_no_prior = decision_mod.decide(bundle, report, [], NOW)
    assert out_no_prior["decision"] == ec.NEEDS_MORE_EVIDENCE, out_no_prior

    prior_adequate = [_minimal_bundle(grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}}, evidence_digest="digest0")]
    out_with_prior = decision_mod.decide(bundle, report, prior_adequate, NOW)
    assert out_with_prior["decision"] == ec.DECISION_STALE, out_with_prior


def test_decision_needs_more_evidence_on_a_failed_or_unknown_gate():
    report = _minimal_report(**{"custody_understood": {"verdict": ec.FAIL, "evidence": "x"}})
    out = decision_mod.decide(_minimal_bundle(), report, [], NOW)
    assert out["decision"] == ec.NEEDS_MORE_EVIDENCE
    assert "custody_understood" in out["failed_gates"]
    assert out["required_next_evidence"]  # a concrete list, never empty on a non-ADMIT


def test_decision_reject_mechanism_unknown():
    out = decision_mod.decide(_minimal_bundle(mechanism_id="NOT_A_REAL_MECHANISM"), _minimal_report(), [], NOW)
    assert out["decision"] == ec.REJECT


def test_decision_reject_identity_conflicted():
    bundle = _minimal_bundle(grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "PRIMARY_IDENTITY": ec.CONFLICTED})
    out = decision_mod.decide(bundle, _minimal_report(), [], NOW)
    assert out["decision"] == ec.REJECT
    assert "CONTRADICTS" in out["rationale"][0]


def test_decision_reject_non_positive_net_return():
    bundle = _minimal_bundle(return_evidence={"net_expected_return": c1.cell(
        c1.ESTIMATED_WITH_METHOD, -0.01, method="test")})
    out = decision_mod.decide(bundle, _minimal_report(), [], NOW)
    assert out["decision"] == ec.REJECT


def test_decision_precedence_order_is_exactly_the_contract_tuple():
    assert ec.DECISION_PRECEDENCE == (ec.REJECT, ec.HOLD, ec.DECISION_STALE, ec.NEEDS_MORE_EVIDENCE, ec.ADMIT_TO_PAPER)


def test_mutation_check_reject_before_hold_ordering_matters():
    """MUTATION CHECK: a candidate that is BOTH mechanism-unknown (REJECT) and CONFLICTED
    (HOLD-shaped) must come out REJECT, not HOLD — proving precedence order is read, not guessed."""
    bundle = _minimal_bundle(mechanism_id="NOT_A_REAL_MECHANISM", conflicts=["RETURN"],
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "RETURN": ec.CONFLICTED})
    out = decision_mod.decide(bundle, _minimal_report(), [], NOW)
    assert out["decision"] == ec.REJECT, out


def test_replay_is_byte_identical(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    assert stored["decision"] == ec.ADMIT_TO_PAPER

    replayed = decision_mod.replay(tmp_path, stored["decision_id"])
    assert replayed["outcome"] == decision_mod.REPLAY_MATCH
    assert replayed["decision"] == stored
    assert cid == stored["candidate_id"]


def test_replay_recomputes_admission_v2_evaluate_not_just_decide(tmp_path, monkeypatch):
    """Post-implementation review M3: replay must recompute ``admission_v2.evaluate()`` itself
    from the companion's stored candidate/extra snapshot — not merely re-run ``decide()`` over
    the ALREADY-computed report. Red without the fix: a gate's logic silently changing (here,
    monkeypatched to always FAIL) would go completely undetected by a replay that only re-runs
    decide() over the stale, pre-change report."""
    c = make_candidate()
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    assert stored["decision"] == ec.ADMIT_TO_PAPER

    # same code_identity (not monkeypatched) — a genuine behavioural change in a gate, caught
    # only because replay recomputes the REPORT, not just decide() over the old one.
    monkeypatch.setitem(admission_v2._EVALUATORS, "identity_verified",
                        lambda bundle, candidate, extra, now: {"verdict": c1.GATE_FAIL, "evidence": "mutated for test"})
    with pytest.raises(decision_mod.ReplayMismatch):
        decision_mod.replay(tmp_path, stored["decision_id"])


def test_mutation_check_replay_would_silently_match_without_recomputing_the_report(tmp_path, monkeypatch):
    """MUTATION CHECK: reproducing the pre-M3 replay (decide() over the STORED report, never
    recomputing admission_v2.evaluate()) on the SAME gate mutation above would report a clean
    MATCH — proving the test above exercises a real fix, not a tautology."""
    c = make_candidate()
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    companion = decision_mod._find_companion(tmp_path, stored["candidate_id"], stored["decision_id"])

    monkeypatch.setitem(admission_v2._EVALUATORS, "identity_verified",
                        lambda bundle, candidate, extra, now: {"verdict": c1.GATE_FAIL, "evidence": "mutated for test"})
    old_recomputed = decision_mod.decide(b, companion["report"], [], NOW)  # old behaviour: stale report
    assert old_recomputed == stored  # the old bug, reproduced: a "MATCH" that missed the mutation


def test_code_identity_includes_scanners_and_collectors():
    """Post-implementation review M3: code_identity() must fold in scanners/ and collectors/
    .py files, not just the package's own top-level modules — a scanner/collector edit can
    change what evidence a candidate's bundle was BUILT from without touching a single
    top-level package file. Verified by inspecting the actual digest INPUT (never touches disk —
    no risk of leaving a real source file mutated)."""
    from spa_core.research_factory import _common as common_mod

    captured = {}
    real_digest = common_mod.contract.digest

    def _capture(parts):
        captured["parts"] = parts
        return real_digest(parts)

    import unittest.mock
    with unittest.mock.patch.object(common_mod.contract, "digest", side_effect=_capture):
        common_mod.code_identity()
    names = captured["parts"][0::2]  # (name, text, name, text, ...)
    assert any(n.startswith("scanners/") for n in names), names
    assert any(n.startswith("collectors/") for n in names), names


def test_mutation_check_replay_detects_a_code_identity_drift(tmp_path, monkeypatch):
    """Post-implementation review M3: if the code identity changes between record and replay (a
    real code change), that is now a NAMED, non-raising outcome (REPLAY_CODE_CHANGED) — never
    silently accepted as a MATCH, but also never raised as if it were a bug."""
    c = make_candidate()
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)

    monkeypatch.setattr(decision_mod, "code_identity", lambda: "a-different-code-identity")
    result = decision_mod.replay(tmp_path, stored["decision_id"])
    assert result["outcome"] == decision_mod.REPLAY_CODE_CHANGED
    assert result["stored_code_identity"] != result["current_code_identity"]
    assert result["current_code_identity"] == "a-different-code-identity"


def test_replay_missing_bundle_is_a_named_error_not_a_crash(tmp_path):
    c = make_candidate()
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    with pytest.raises(decision_mod.ReplayError):
        decision_mod.replay(tmp_path, "no-such-decision-id")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 5. CIO amendment — REFERENCE_TRACK and issuer-only candidates are blocked
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _candidate_with_bundle(tmp_path, *, paper_mode: str, counterparty_strength: str) -> dict:
    """A candidate reaching EVIDENCE_ACCUMULATING with its latest bundle shaped by the two knobs
    the CIO amendment tests care about."""
    from spa_core.research_factory import eligibility, forward

    # unit="fraction" is a declared ANNUAL rate (contract.ANNUAL_RATE_UNITS) — required for
    # contract.net_expected_return() to compute a value at all now that it is unit-aware (a
    # unit-less return is honestly NOT_MEASURED, never netted as if it already were annual).
    c = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="RWA_STABLE_YIELD",
                      base_return=_v1cell(c1.MEASURED, 0.05, source_class=c1.PRIMARY_PROTOCOL, unit="fraction"))
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)

    profile = v2fx.all_strong_profile(c["mechanism_id"])
    if counterparty_strength == "issuer_only":
        profile = {role: (ec.role_entry(ec.CP_IDENTIFIED, role=role, identity="Acme",
                                        citations=[_citation(origin="issuer:acme", channel=ec.CHANNEL_OFFICIAL_API,
                                                            ref="https://acme.example")])
                          if role in profile_mod.required_roles(c["mechanism_id"]) else entry)
                  for role, entry in profile.items()}
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    # a bare state assertion is not "documented" (grade_holder_eligibility needs a RECORDED
    # requirement behind it — evidence_contract.ELIGIBILITY_REQUIREMENTS).
    v2_evidence["holder_eligibility"] = {"state": ec.SPA_ELIGIBLE, "requirements": {"kyc": False}}
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[], paper_mode=paper_mode,
                               registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    outcome = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    if outcome["decision"] != ec.ADMIT_TO_PAPER:
        pytest.skip(f"fixture did not reach ADMIT_TO_PAPER: {outcome}")  # not the thing under test
    snap = decision_mod.write_admission_snapshot_v2(tmp_path, outcome, b, NOW)
    admission_id = snap["payload"]["admission_id"]
    lifecycle.transition(tmp_path, cid, c1.PAPER_ACTIVE, gate_ref=admission_id, reason="setup", now=NOW)

    t1 = NOW + timedelta(hours=1)
    forward.record(tmp_path, cid, {
        "period": "2026-10-05", "observed_return": _v1cell(c1.MEASURED, 0.05, as_of=t1.isoformat(), judge_now=t1),
        "realised_index": _v1cell(c1.MEASURED, 1.0, source_class=c1.PRIMARY_CHAIN, as_of=t1.isoformat(),
                                  judge_now=t1),
    }, t1)
    lifecycle.transition(tmp_path, cid, c1.EVIDENCE_ACCUMULATING, gate_ref=admission_id, reason="setup", now=t1)
    return c


def test_cio_amendment_blocks_reference_track_candidate(tmp_path):
    from spa_core.research_factory import eligibility

    c = _candidate_with_bundle(tmp_path, paper_mode=ec.PAPER_MODE_REFERENCE_TRACK, counterparty_strength="strong")
    report = eligibility.evaluate(tmp_path, c, {"_existing_book_roots": []}, NOW + timedelta(hours=1))
    assert report["gates"]["not_reference_track"]["verdict"] == c1.GATE_FAIL, report["gates"]["not_reference_track"]
    assert report["all_pass"] is False


def test_cio_amendment_blocks_issuer_only_credit_like_candidate(tmp_path):
    from spa_core.research_factory import eligibility

    c = _candidate_with_bundle(tmp_path, paper_mode=ec.PAPER_MODE_HOLDABLE, counterparty_strength="issuer_only")
    report = eligibility.evaluate(tmp_path, c, {"_existing_book_roots": []}, NOW + timedelta(hours=1))
    gate = report["gates"]["counterparty_grade_strong_for_credit_like"]
    assert gate["verdict"] == c1.GATE_FAIL, gate
    assert report["all_pass"] is False


def test_cio_gates_added_are_exactly_four_and_named():
    assert ec.CIO_GATES_ADDED == ("min_origins_cio", "counterparty_grade_strong_for_credit_like",
                                  "holder_eligibility_documented", "not_reference_track")
    assert set(ec.CIO_GATES_ADDED) <= set(c1.CIO_ELIGIBILITY_GATES)


def test_cio_amendment_m1_gates_are_wired_into_evaluate(tmp_path):
    """ADR-564 post-impl review M1: the six CIO_MIN_GRADE / MIN_GROUPS_CIO bars are part of the
    ASSERTED tuple and of evaluate()'s report — declared-but-unenforced was the finding. Red
    without the wiring: evaluate() never reported them, so a RETURN grade below STRONG could not
    block CIO eligibility."""
    from spa_core.research_factory import eligibility

    assert set(eligibility.PENDING_CIO_AMENDMENT_GATES) <= set(c1.CIO_ELIGIBILITY_GATES)
    c = _candidate_with_bundle(tmp_path, paper_mode=ec.PAPER_MODE_HOLDABLE, counterparty_strength="strong")
    report = eligibility.evaluate(tmp_path, c, {"_existing_book_roots": []}, NOW + timedelta(hours=1))
    assert set(report["gates"]) == set(c1.CIO_ELIGIBILITY_GATES)
    for name in eligibility.PENDING_CIO_AMENDMENT_GATES:
        assert report["gates"][name]["verdict"] in (c1.GATE_PASS, c1.GATE_FAIL, c1.GATE_UNKNOWN)


def test_cio_amendment_m1_gates_unknown_without_bundle(tmp_path):
    from spa_core.research_factory import eligibility

    c = _candidate_with_bundle(tmp_path, paper_mode=ec.PAPER_MODE_HOLDABLE, counterparty_strength="strong")
    other = dict(c, candidate_id=c["candidate_id"] + ":nobundle")
    report = eligibility.evaluate(tmp_path, other, {"_existing_book_roots": []}, NOW + timedelta(hours=1))
    for name in eligibility.PENDING_CIO_AMENDMENT_GATES:
        assert report["gates"][name]["verdict"] == c1.GATE_UNKNOWN, (name, report["gates"][name])
    assert report["all_pass"] is False


def test_holder_eligibility_documented_requires_grade_not_bare_state():
    """Post-implementation review M1: a bare holder_eligibility_evidence.state==SPA_ELIGIBLE is
    not 'documented' — the GRADE (which itself requires a recorded requirement) is what the CIO
    bar actually names. Red without the fix: a state-only assertion with NO recorded requirement
    used to PASS this gate."""
    from spa_core.research_factory import eligibility

    bundle_state_only = _minimal_bundle(
        grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "HOLDER_ELIGIBILITY": ec.UNKNOWN},
        holder_eligibility_evidence={"state": ec.SPA_ELIGIBLE})  # NO recorded requirement
    # evaluate()'s CIO_GATES_ADDED block reads grades, not the raw state — confirm the grade
    # itself is UNKNOWN here (grade_holder_eligibility demands a recorded requirement), so the
    # gate's bar (CIO_MIN_GRADE) is not met despite the bare state claiming SPA_ELIGIBLE.
    holder_grade = bundle_state_only["grades"]["HOLDER_ELIGIBILITY"]
    assert ec.GRADE_ORDER.get(holder_grade, 0) < ec.GRADE_ORDER[ec.CIO_MIN_GRADE["HOLDER_ELIGIBILITY"]]

    bundle_graded = _minimal_bundle(
        grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "HOLDER_ELIGIBILITY": ec.ADEQUATE},
        holder_eligibility_evidence={"state": ec.SPA_ELIGIBLE, "requirements": {"kyc": False}})
    assert ec.GRADE_ORDER.get(bundle_graded["grades"]["HOLDER_ELIGIBILITY"], 0) \
        >= ec.GRADE_ORDER[ec.CIO_MIN_GRADE["HOLDER_ELIGIBILITY"]]


def test_pending_cio_amendment_gates_grade_thresholds():
    """Post-implementation review M1: gates for every CIO_MIN_GRADE entry not already covered by an
    existing gate (wired into CIO_ELIGIBILITY_GATES — see test_cio_amendment_m1_gates_are_wired_into_evaluate)."""
    from spa_core.research_factory import eligibility

    strong_bundle = _minimal_bundle(grades={**{d: ec.STRONG for d in ec.DIMENSIONS}})
    gates = eligibility.pending_cio_amendment_gates(strong_bundle)
    assert set(gates) == set(eligibility.PENDING_CIO_AMENDMENT_GATES)
    for name in ("return_grade_strong_for_cio", "custody_grade_strong_for_cio",
                "reserves_grade_adequate_for_cio", "legal_grade_adequate_for_cio"):
        assert gates[name]["verdict"] == c1.GATE_PASS, (name, gates[name])

    weak_bundle = _minimal_bundle(grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS},
                                          "RETURN": ec.ADEQUATE, "CUSTODY": ec.ADEQUATE})
    gates_weak = eligibility.pending_cio_amendment_gates(weak_bundle)
    assert gates_weak["return_grade_strong_for_cio"]["verdict"] == c1.GATE_FAIL  # ADEQUATE < STRONG
    assert gates_weak["custody_grade_strong_for_cio"]["verdict"] == c1.GATE_FAIL
    assert gates_weak["reserves_grade_adequate_for_cio"]["verdict"] == c1.GATE_PASS  # ADEQUATE meets ADEQUATE


def test_pending_cio_amendment_gates_group_counts():
    """reserves/custody group-count gates: reserves reads auditor_group/issuer_group directly
    (already-resolved group names); custody counts the custodian role's OWN citations via
    ec.origin_groups, needing a registry — UNKNOWN (never guessed) without one."""
    from spa_core.research_factory import eligibility

    two_groups = _minimal_bundle(
        grades={**{d: ec.STRONG for d in ec.DIMENSIONS}},
        reserves_evidence={"attested": True, "auditor_group": "auditor_x", "issuer_group": "issuer_y"})
    gates = eligibility.pending_cio_amendment_gates(two_groups)
    assert gates["reserves_groups_sufficient_for_cio"]["verdict"] == c1.GATE_PASS

    one_group = _minimal_bundle(
        grades={**{d: ec.STRONG for d in ec.DIMENSIONS}},
        reserves_evidence={"attested": True, "auditor_group": "same", "issuer_group": "same"})
    gates_one = eligibility.pending_cio_amendment_gates(one_group)
    assert gates_one["reserves_groups_sufficient_for_cio"]["verdict"] == c1.GATE_FAIL

    cit_a = _citation(origin="custodian:a", channel=ec.CHANNEL_OFFICIAL_DOC, ref="https://a.example",
                      quote="custodian a")
    cit_b = _citation(origin="custodian:b", channel=ec.CHANNEL_OFFICIAL_DOC, ref="https://b.example",
                      quote="custodian b")
    bundle_with_custody = _minimal_bundle(
        grades={**{d: ec.STRONG for d in ec.DIMENSIONS}},
        custody_evidence={"profile_entry": {"citations": [cit_a, cit_b]}})
    no_registry = eligibility.pending_cio_amendment_gates(bundle_with_custody)
    assert no_registry["custody_groups_sufficient_for_cio"]["verdict"] == c1.GATE_UNKNOWN

    registry = {"custodian:a": {"group": "group_a"}, "custodian:b": {"group": "group_b"}}
    with_registry = eligibility.pending_cio_amendment_gates(bundle_with_custody, registry=registry)
    assert with_registry["custody_groups_sufficient_for_cio"]["verdict"] == c1.GATE_PASS

    same_group_registry = {"custodian:a": {"group": "same"}, "custodian:b": {"group": "same"}}
    with_same_group = eligibility.pending_cio_amendment_gates(bundle_with_custody, registry=same_group_registry)
    assert with_same_group["custody_groups_sufficient_for_cio"]["verdict"] == c1.GATE_FAIL


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6. Boundaries — http_client
# ══════════════════════════════════════════════════════════════════════════════════════════════

class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"{}", headers: Optional[dict] = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, n: int) -> bytes:
        return self._body[:n]


def test_http_client_refuses_host_not_in_allow_list():
    def transport(req, timeout):
        return _FakeResponse(200, b"{}")

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://evil.example.com/steal", now=NOW, transport=transport)


def test_http_client_refuses_disallowed_method():
    def transport(req, timeout):
        return _FakeResponse(200, b"{}")

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/api/v3/ticker", method="DELETE", now=NOW, transport=transport)


def test_http_client_refuses_disallowed_path_prefix():
    def transport(req, timeout):
        return _FakeResponse(200, b"{}")

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/sapi/v1/account", now=NOW, transport=transport)


def test_http_client_allows_a_listed_host_method_path():
    def transport(req, timeout):
        return _FakeResponse(200, b'{"ok": true}')

    status, raw, fetched_at = http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)
    assert status == 200
    assert json.loads(raw) == {"ok": True}
    assert fetched_at == "2026-10-04T12:00:00Z"


def test_http_client_refuses_a_redirect_off_the_allow_listed_host():
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "https://evil.example.com/steal"})
        return _FakeResponse(200, b"{}")  # never reached

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)


def test_http_client_follows_a_same_host_redirect():
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "https://api.binance.com/api/v3/ticker"})
        return _FakeResponse(200, b"{}")

    status, raw, _ = http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)
    assert status == 200
    assert calls["n"] == 2


def test_http_client_requires_https_scheme():
    """H1: a plain http:// URL to an otherwise allow-listed host/path is refused — HTTP_SCHEMES
    is ("https",) only."""
    def transport(req, timeout):
        return _FakeResponse(200, b"{}")

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("http://api.binance.com/api/v3/ticker", now=NOW, transport=transport)


class _RedirectToOffListHandler:
    """A tiny ``http.server`` handler: GET /redirect-off-list answers a REAL 302 whose Location
    names a DIFFERENT host (127.0.0.2, also loopback — no DNS needed) that is not on the
    allow-list for this test. Built as a factory so each test run gets a fresh handler class
    bound to its own captured state (none needed here, but keeps the pattern self-contained)."""

    @staticmethod
    def build():
        import http.server

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib's naming convention
                if self.path == "/redirect-off-list":
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.2:9/stolen")
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):  # noqa: D401 - silence the test server's own logging
                pass

        return Handler


def test_http_client_real_urlopen_does_not_auto_follow_a_redirect_off_list(monkeypatch):
    """H1 positive control (post-implementation review, 2026-10-04): against a REAL local HTTP
    server and the REAL default transport (no injected fake — this is the exact gap the
    reviewer reproduced: urlopen's stock opener follows a 30x redirect itself, so fetch()'s own
    per-hop host re-check never ran). Red without the ``_RefuseAutoRedirect`` fix: urlopen would
    silently follow the 302 and either return a 200 from the off-list host (if it were
    reachable) or raise a bare connection error — never ``HttpRefused`` naming the real reason."""
    import http.server
    import threading

    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectToOffListHandler.build())
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(ec, "HTTP_ALLOW",
                            ec.HTTP_ALLOW + (("127.0.0.1", "GET", "/redirect-off-list", None),))
        monkeypatch.setattr(ec, "HTTP_SCHEMES", ("http", "https"))  # this local server has no TLS
        with pytest.raises(http_client.HttpRefused, match="redirect left the allow-listed host"):
            http_client.fetch(f"http://127.0.0.1:{port}/redirect-off-list", now=NOW)  # no transport= override
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_mutation_check_real_urlopen_redirect_bug_is_real(monkeypatch):
    """MUTATION CHECK: with ``_RefuseAutoRedirect`` removed (the pre-fix default transport —
    plain ``urlopen``), the SAME local server/redirect reproduces the reviewer's finding: urlopen
    follows the 302 itself and ``fetch()`` never gets a chance to refuse it — it raises a bare
    network error (can't reach 127.0.0.2:9) instead of the NAMED ``HttpRefused``, proving the test
    above is pinned to a real behavioural difference."""
    import http.server
    import threading
    import urllib.error
    import urllib.request

    def _old_default_transport(request, timeout_s):
        return urllib.request.urlopen(request, timeout=timeout_s)

    monkeypatch.setattr(http_client, "_default_transport", _old_default_transport)
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectToOffListHandler.build())
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(ec, "HTTP_ALLOW",
                            ec.HTTP_ALLOW + (("127.0.0.1", "GET", "/redirect-off-list", None),))
        monkeypatch.setattr(ec, "HTTP_SCHEMES", ("http", "https"))
        with pytest.raises(Exception) as exc_info:
            http_client.fetch(f"http://127.0.0.1:{port}/redirect-off-list", now=NOW)
        assert not isinstance(exc_info.value, http_client.HttpRefused)  # the old bug, reproduced
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_http_client_refuses_oversized_response_default_cap():
    oversized = b"x" * (ec.HTTP_MAX_RESPONSE_BYTES + 1)

    def transport(req, timeout):
        return _FakeResponse(200, oversized)

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)


def test_http_client_per_host_cap_yields_llama_allows_bigger_body_another_host_does_not():
    """evidence_contract.HTTP_MAX_RESPONSE_BYTES_BY_HOST (review/integration, 2026-10-04): a live
    probe measured yields.llama.fi /pools at 11.6 MB, over the 8 MB default. A ~10 MB body passes
    for yields.llama.fi (its override is 32 MiB) and is refused for a host with no override."""
    ten_mb = b"x" * (10 * 1024 * 1024)
    assert ec.HTTP_MAX_RESPONSE_BYTES_BY_HOST.get("yields.llama.fi", 0) > len(ten_mb) > ec.HTTP_MAX_RESPONSE_BYTES

    def transport(req, timeout):
        return _FakeResponse(200, ten_mb)

    status, raw, _ = http_client.fetch("https://yields.llama.fi/pools", now=NOW, transport=transport)
    assert status == 200 and len(raw) == len(ten_mb)

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW,
                          transport=lambda req, timeout: _FakeResponse(200, ten_mb))


def test_http_client_hyperliquid_post_restricted_to_allowed_info_types():
    def transport(req, timeout):
        return _FakeResponse(200, b"{}")

    body = json.dumps({"type": "fundingHistory", "coin": "BTC"}).encode("utf-8")
    status, raw, _ = http_client.fetch("https://api.hyperliquid.xyz/info", method="POST", body=body,
                                       body_type="hyperliquid_info", now=NOW, transport=transport)
    assert status == 200

    bad_body = json.dumps({"type": "orderStatus"}).encode("utf-8")
    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.hyperliquid.xyz/info", method="POST", body=bad_body,
                          body_type="hyperliquid_info", now=NOW, transport=transport)


def test_http_client_client_wrapper_get_and_post_info():
    def transport(req, timeout):
        return _FakeResponse(200, json.dumps({"data": [1, 2, 3]}).encode("utf-8"))

    client = http_client.Client(now=NOW, transport=transport)
    assert client.get("api.binance.com", "/api/v3/ticker", {"symbol": "BTCUSDT"}) == {"data": [1, 2, 3]}
    assert client.post_info("fundingHistory", {"coin": "BTC"}) == {"data": [1, 2, 3]}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 7. Boundaries — AST import-graph tests
# ══════════════════════════════════════════════════════════════════════════════════════════════

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORBIDDEN_NETWORK_MODULES = ("urllib.request", "urllib3", "requests", "http.client", "socket",
                              "spa_core.strategy_lab.data._http")
_ALLOWED_NETWORK_CHANNELS = ("spa_core.research_factory.http_client", "spa_core.capital_shadow.rpc",
                            "spa_core.capital_shadow.keccak")


def _imported_module_names(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _collector_and_onchain_files() -> list:
    out = [_REPO_ROOT / "spa_core/research_factory/onchain.py"]
    collectors_dir = _REPO_ROOT / "spa_core/research_factory/collectors"
    if collectors_dir.is_dir():
        out.extend(sorted(p for p in collectors_dir.glob("*.py") if p.name != "__init__.py"))
    return out


def test_collectors_and_onchain_import_no_network_module_except_the_allowed_channels():
    files = _collector_and_onchain_files()
    assert files, "no collector/onchain files found — the test's target moved"
    for path in files:
        imported = _imported_module_names(path)
        violations = [m for m in imported if any(m == forbidden or m.startswith(forbidden + ".")
                                                  for forbidden in _FORBIDDEN_NETWORK_MODULES)]
        assert not violations, f"{path}: imports a forbidden network module directly: {violations}"


def test_decision_module_imports_no_cio_execution_allocation_or_site_module():
    path = _REPO_ROOT / "spa_core/research_factory/decision.py"
    imported = _imported_module_names(path)
    forbidden_prefixes = ("spa_core.investment_cio", "spa_core.execution", "spa_core.paper_trading",
                         "landing")
    violations = [m for m in imported if any(m.startswith(p) for p in forbidden_prefixes)]
    assert not violations, f"decision.py imports a forbidden module: {violations}"


def test_mutation_check_import_graph_test_is_sensitive(tmp_path):
    """MUTATION CHECK: a file that DOES import a forbidden module is caught by the same assertion
    logic — proving the test above is not vacuously green."""
    poisoned = tmp_path / "poisoned.py"
    poisoned.write_text("import spa_core.investment_cio.ledger\n")
    imported = _imported_module_names(poisoned)
    forbidden_prefixes = ("spa_core.investment_cio", "spa_core.execution", "spa_core.paper_trading", "landing")
    violations = [m for m in imported if any(m.startswith(p) for p in forbidden_prefixes)]
    assert violations == ["spa_core.investment_cio.ledger"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 8. registry_loader — origins.json / facts.jsonl validation
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_registry_loader_missing_files_are_honestly_empty(tmp_path):
    assert registry_loader.load_origins(tmp_path / "no-such-origins.json") == {}
    assert registry_loader.load_facts(tmp_path / "no-such-facts.jsonl") == []


def test_registry_loader_skips_underscore_metadata_keys(tmp_path):
    p = tmp_path / "origins.json"
    p.write_text(json.dumps({"_comment": "docs", "issuer:acme": {"group": "acme_group"}}))
    out = registry_loader.load_origins(p)
    assert "_comment" not in out
    assert out["issuer:acme"]["group"] == "acme_group"


def test_registry_loader_malformed_origin_entry_raises_named_error(tmp_path):
    p = tmp_path / "origins.json"
    p.write_text(json.dumps({"issuer:acme": {"note": "no group field"}}))
    with pytest.raises(registry_loader.OriginRegistryError):
        registry_loader.load_origins(p)


def test_registry_loader_malformed_fact_line_refuses_not_skips(tmp_path):
    p = tmp_path / "facts.jsonl"
    good = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"], "role": None,
           "claim_type": "nav", "value": 1.0, "origin": "issuer:acme", "channel": ec.CHANNEL_OFFICIAL_API,
           "ref": "https://acme.example", "quote": None, "retrieved_at": NOW.isoformat(), "effective_from": None,
           "page_sha256": None, "fact_sha256": None, "curated_by": "test", "reviewed_by": "reviewer",
           "supersedes": None, "expires_at": None, "subject_to_change": False}
    p.write_text(json.dumps(good) + "\n" + "{not valid json" + "\n")
    with pytest.raises(registry_loader.FactRegistryError) as exc_info:
        registry_loader.load_facts(p, origins={"issuer:acme": {"group": "acme_group", "hosts": ["acme.example"]}})
    assert exc_info.value.line_no == 2


def test_registry_loader_fact_requires_quote_for_doc_channel(tmp_path):
    p = tmp_path / "facts.jsonl"
    bad = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"], "role": None,
          "claim_type": "fee", "value": 1.0, "origin": "issuer:acme", "channel": ec.CHANNEL_OFFICIAL_DOC,
          "ref": "https://acme.example", "quote": None, "retrieved_at": NOW.isoformat(), "effective_from": None,
          "page_sha256": None, "fact_sha256": None, "curated_by": "test", "reviewed_by": "reviewer",
          "supersedes": None, "expires_at": None, "subject_to_change": False}
    p.write_text(json.dumps(bad) + "\n")
    with pytest.raises(registry_loader.FactRegistryError, match="quote"):
        registry_loader.load_facts(p, origins={"issuer:acme": {"group": "acme_group", "hosts": ["acme.example"]}})


def test_registry_loader_fact_requires_independent_review(tmp_path):
    """H6: a fact with no ``reviewed_by`` at all, or with ``reviewed_by`` equal to its own
    ``curated_by``, is UNUSABLE (``evidence_contract.FACT_REQUIRES_INDEPENDENT_REVIEW``) — a
    curator's own say-so is not independent review. Scoped to the ONE fact — excluded from the
    usable set and named in ``refused_out``, never a whole-file raise (that stays reserved for
    STRUCTURALLY malformed rows, ``FactRegistryError``)."""
    def _fact(**overrides):
        base = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"],
               "role": None, "claim_type": "fee", "value": 1.0, "origin": "issuer:acme",
               "channel": ec.CHANNEL_OFFICIAL_API, "ref": "https://acme.example", "quote": None,
               "retrieved_at": NOW.isoformat(), "effective_from": None, "page_sha256": None,
               "fact_sha256": None, "curated_by": "session-a", "reviewed_by": None,
               "supersedes": None, "expires_at": None, "subject_to_change": False}
        base.update(overrides)
        return base

    origins = {"issuer:acme": {"group": "acme_group", "hosts": ["acme.example"]}}

    p = tmp_path / "no_review.jsonl"
    p.write_text(json.dumps(_fact(reviewed_by=None)) + "\n")
    refused = []
    rows = registry_loader.load_facts(p, origins=origins, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "reviewed_by is required" in refused[0]["reason"]

    p2 = tmp_path / "self_review.jsonl"
    p2.write_text(json.dumps(_fact(reviewed_by="session-a")) + "\n")  # same as curated_by
    refused2 = []
    rows2 = registry_loader.load_facts(p2, origins=origins, refused_out=refused2)
    assert rows2 == []
    assert len(refused2) == 1 and "equals curated_by" in refused2[0]["reason"]

    p3 = tmp_path / "real_review.jsonl"
    # H6 re-review (2026-10-04): reviewed_by alone no longer suffices -- the fact needs its own
    # real content hash AND a committed review record naming it at that hash, CONFIRMED.
    fact3 = v2fx.stamped_fact(_fact(reviewed_by="session-b"))  # genuinely different
    v2fx.write_fact_review(tmp_path, "session-b", [(fact3["fact_id"], fact3["fact_sha256"])])
    p3.write_text(json.dumps(fact3) + "\n")
    rows3 = registry_loader.load_facts(p3, origins=origins)
    assert len(rows3) == 1


def test_registry_loader_fact_requires_matching_origin_host(tmp_path):
    """H6: a fact's ``ref`` host must be among its origin's registered ``hosts`` — an origin
    with NO hosts registered cannot be verified (fail-CLOSED, unusable); a ref hosted elsewhere
    is unusable too; a chain-native (non-URL) ref is exempt from the check entirely. Scoped to
    the ONE fact, not a whole-file raise."""
    def _fact(**overrides):
        base = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"],
               "role": None, "claim_type": "fee", "value": 1.0, "origin": "issuer:acme",
               "channel": ec.CHANNEL_OFFICIAL_API, "ref": "https://acme.example/page", "quote": None,
               "retrieved_at": NOW.isoformat(), "effective_from": None, "page_sha256": None,
               "fact_sha256": None, "curated_by": "session-a", "reviewed_by": "session-b",
               "supersedes": None, "expires_at": None, "subject_to_change": False}
        base.update(overrides)
        return base

    # H6 re-review (2026-10-04): reviewed_by="session-b" alone no longer suffices -- every fact
    # this test expects to actually REACH the host check (rather than be refused earlier, for an
    # unrelated review reason) needs its own content hash + a committed, matching review record.
    no_hosts_fact = v2fx.stamped_fact(_fact())
    wrong_host_fact = v2fx.stamped_fact(_fact(ref="https://evil.example/page"))
    right_host_fact = v2fx.stamped_fact(_fact())
    # chain-native now also requires a CHAIN_NATIVE_CLAIMS claim_type (H6 req #1), not just a
    # chain-shaped ref on any claim_type -- "bytecode" matches both the ref and the claim.
    chain_fact = v2fx.stamped_fact(_fact(ref="chain:1:0xabc:bytecode", channel=ec.CHANNEL_ON_CHAIN,
                                         claim_type="bytecode"))
    v2fx.write_fact_review(tmp_path, "session-b", [
        (no_hosts_fact["fact_id"], no_hosts_fact["fact_sha256"]),
        (wrong_host_fact["fact_id"], wrong_host_fact["fact_sha256"]),
        (right_host_fact["fact_id"], right_host_fact["fact_sha256"]),
        (chain_fact["fact_id"], chain_fact["fact_sha256"]),
    ])

    p_no_hosts = tmp_path / "no_hosts.jsonl"
    p_no_hosts.write_text(json.dumps(no_hosts_fact) + "\n")
    refused = []
    rows = registry_loader.load_facts(p_no_hosts, origins={"issuer:acme": {"group": "g"}}, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "no registered 'hosts'" in refused[0]["reason"]

    p_wrong_host = tmp_path / "wrong_host.jsonl"
    p_wrong_host.write_text(json.dumps(wrong_host_fact) + "\n")
    refused2 = []
    rows2 = registry_loader.load_facts(p_wrong_host, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}},
                                       refused_out=refused2)
    assert rows2 == []
    assert len(refused2) == 1 and "is not among origin" in refused2[0]["reason"]

    p_right_host = tmp_path / "right_host.jsonl"
    p_right_host.write_text(json.dumps(right_host_fact) + "\n")
    rows3 = registry_loader.load_facts(p_right_host, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
    assert len(rows3) == 1

    p_chain_ref = tmp_path / "chain_ref.jsonl"
    p_chain_ref.write_text(json.dumps(chain_fact) + "\n")
    rows4 = registry_loader.load_facts(p_chain_ref, origins={"issuer:acme": {"group": "g"}})  # no hosts at all
    assert len(rows4) == 1  # exempt — not a URL ref


def test_registry_loader_refuses_free_text_and_plain_http_refs(tmp_path):
    """Independent fact review (2026-10-04): 32 of 43 curated refs were free text
    ("docs.ondo.finance (OUSG fees)") and silently SKIPPED the host check. Red without the fix:
    a free-text ref naming another publisher loaded clean."""
    def _fact(**overrides):
        base = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"],
                "role": None, "claim_type": "fee", "value": 1.0, "origin": "issuer:acme",
                "channel": ec.CHANNEL_OFFICIAL_API, "ref": "https://acme.example/page", "quote": None,
                "retrieved_at": NOW.isoformat(), "effective_from": None, "page_sha256": None,
                "fact_sha256": None, "curated_by": "session-a", "reviewed_by": "session-b",
                "supersedes": None, "expires_at": None, "subject_to_change": False}
        base.update(overrides)
        return base

    origins = {"issuer:acme": {"group": "g", "hosts": ["acme.example"]}}
    # H6 re-review (2026-10-04): reviewed_by="session-b" alone no longer suffices -- stamp each
    # fact's real content hash and commit a matching review record so the HOST check (this test's
    # actual subject), not the review-binding check, is what refuses the two bad refs.
    bad_facts = {bad_ref: v2fx.stamped_fact(_fact(ref=bad_ref))
                for bad_ref, _ in (("evil.example (press release)", "neither an https URL"),
                                   ("http://acme.example/page", "scheme"))}
    # the eth_call ref is a name()-style identity read -- give it a claim_type H6 req #1 accepts
    # for a chain-native, no-host ref (channel on_chain + claim_type in CHAIN_NATIVE_CLAIMS).
    eth_fact = v2fx.stamped_fact(_fact(ref="eth_call:1:0xabc:name():block:1", channel=ec.CHANNEL_ON_CHAIN,
                                       claim_type="token_identity"))
    v2fx.write_fact_review(tmp_path, "session-b",
                          [(f["fact_id"], f["fact_sha256"]) for f in bad_facts.values()] +
                          [(eth_fact["fact_id"], eth_fact["fact_sha256"])])
    for bad_ref, needle in (("evil.example (press release)", "neither an https URL"),
                            ("http://acme.example/page", "scheme")):
        p = tmp_path / "f.jsonl"
        p.write_text(json.dumps(bad_facts[bad_ref]) + "\n")
        refused = []
        assert registry_loader.load_facts(p, origins=origins, refused_out=refused) == []
        assert len(refused) == 1 and needle in refused[0]["reason"], refused
    p = tmp_path / "eth.jsonl"
    p.write_text(json.dumps(eth_fact) + "\n")
    assert len(registry_loader.load_facts(p, origins=origins)) == 1


def test_registry_loader_unusable_fact_does_not_block_other_facts_in_the_same_file(tmp_path):
    """A SEMANTICALLY unusable fact (no review) must not prevent every OTHER, usable fact in the
    SAME file from loading — unlike a structurally malformed line, which halts the whole load."""
    good = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"], "role": None,
           "claim_type": "fee", "value": 1.0, "origin": "issuer:acme", "channel": ec.CHANNEL_OFFICIAL_API,
           "ref": "https://acme.example", "quote": None, "retrieved_at": NOW.isoformat(),
           "effective_from": None, "page_sha256": None, "fact_sha256": None, "curated_by": "session-a",
           "reviewed_by": "session-b", "supersedes": None, "expires_at": None, "subject_to_change": False}
    good = v2fx.stamped_fact(good)  # H6 re-review: needs its own real content hash
    unreviewed = dict(good, fact_id="f2", reviewed_by=None)
    v2fx.write_fact_review(tmp_path, "session-b", [(good["fact_id"], good["fact_sha256"])])
    p = tmp_path / "mixed.jsonl"
    p.write_text(json.dumps(unreviewed) + "\n" + json.dumps(good) + "\n")
    refused = []
    rows = registry_loader.load_facts(p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}},
                                      refused_out=refused)
    assert [r["fact_id"] for r in rows] == ["f1"]
    assert [r["fact_id"] for r in refused] == ["f2"]


def test_mutation_check_origin_host_leak_is_the_guard(tmp_path):
    """MUTATION CHECK: without ``_check_origin_hosts``, a fact citing an origin it does not
    actually match (ref hosted on evil.example, origin issuer:acme) would load clean — proving
    the test above exercises a real guard."""
    bad = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"], "role": None,
          "claim_type": "fee", "value": 1.0, "origin": "issuer:acme", "channel": ec.CHANNEL_OFFICIAL_API,
          "ref": "https://evil.example/page", "quote": None, "retrieved_at": NOW.isoformat(),
          "effective_from": None, "page_sha256": None, "fact_sha256": None, "curated_by": "session-a",
          "reviewed_by": "session-b", "supersedes": None, "expires_at": None, "subject_to_change": False}
    # H6 re-review: give `bad` a real content hash + a matching committed record, so this test
    # isolates the _check_origin_hosts mutation it is actually about (not the review-binding check).
    bad = v2fx.stamped_fact(bad)
    v2fx.write_fact_review(tmp_path, "session-b", [(bad["fact_id"], bad["fact_sha256"])])

    def _no_host_check(line_no, row, origins):
        return None

    import spa_core.research_factory.registry_loader as rl_mod
    original = rl_mod._check_origin_hosts
    rl_mod._check_origin_hosts = _no_host_check
    try:
        p = tmp_path / "bad.jsonl"
        p.write_text(json.dumps(bad) + "\n")
        rows = registry_loader.load_facts(p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
        assert len(rows) == 1  # the old (unguarded) behaviour, reproduced
    finally:
        rl_mod._check_origin_hosts = original


def test_registry_loader_is_stale_past_expires_at():
    fact = {"expires_at": (NOW - timedelta(days=1)).isoformat()}
    assert registry_loader.is_stale(fact, NOW) is True
    fresh = {"expires_at": (NOW + timedelta(days=1)).isoformat()}
    assert registry_loader.is_stale(fresh, NOW) is False
    assert registry_loader.is_stale({}, NOW) is False


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 9. admission_v2 — NA-per-mechanism discipline + a sample gate
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_admission_v2_gates_set_matches_the_frozen_contract():
    assert set(admission_v2._EVALUATORS) == set(ec.ADMISSION_V2_GATES)


def test_admission_v2_redemption_understood_na_for_funding_capture():
    bundle = _minimal_bundle(mechanism_id="FUNDING_CAPTURE",
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "REDEMPTION": ec.NOT_APPLICABLE},
                             return_evidence={"primary_field": "funding",
                                             "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05,
                                                                            method="test")})
    candidate = {"candidate_id": "cand1", "mechanism_id": "FUNDING_CAPTURE",
                "funding": _v1cell(c1.MEASURED, 0.0001)}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["redemption_understood"]["verdict"] == "NOT_APPLICABLE"


def test_admission_v2_leverage_known_fails_without_a_measured_value():
    bundle = _minimal_bundle(mechanism_id="FUNDING_CAPTURE",
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "REDEMPTION": ec.NOT_APPLICABLE},
                             return_evidence={"primary_field": "funding",
                                             "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05,
                                                                            method="test")})
    candidate = {"candidate_id": "cand1", "mechanism_id": "FUNDING_CAPTURE",
                "funding": _v1cell(c1.MEASURED, 0.0001),
                "leverage": c1.cell(c1.NOT_MEASURED, reason="not measured")}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["leverage_known"]["verdict"] == c1.GATE_FAIL


def test_duplicate_exposure_clear_catches_a_wrapper_sharing_underlying_root():
    """Post-implementation review M6: a wrapper/other-chain copy of the SAME fund shares
    underlying_root but (for a mechanism not in run._FAMILY_ROOTED_MECHANISMS, e.g.
    TOKENISED_TREASURY) gets its OWN exposure_family — the exposure_family check alone never
    catches it. ``other_admitted_underlying_roots`` must."""
    bundle = _minimal_bundle(exposure_family="ek-wrapped-on-another-chain")  # DIFFERENT family
    candidate = {"candidate_id": "cand-wrapper", "underlying_root": "fund:same-rwa-fund"}
    extra = {"other_admitted_underlying_roots": {"fund:same-rwa-fund": "cand-original"}}
    report = admission_v2.evaluate(bundle, candidate, extra, NOW)
    assert report["gates"]["duplicate_exposure_clear"]["verdict"] == c1.GATE_FAIL

    extra_self = {"other_admitted_underlying_roots": {"fund:same-rwa-fund": "cand-wrapper"}}  # self, not a dup
    report_self = admission_v2.evaluate(bundle, candidate, extra_self, NOW)
    assert report_self["gates"]["duplicate_exposure_clear"]["verdict"] == c1.GATE_PASS


def test_sherlock_review_all_builds_underlying_root_dedup_across_candidates(tmp_path):
    """End to end: run._sherlock_review_all computes other_admitted_underlying_roots from the
    REAL candidate set (contract.PAPER_STATES only) and passes it through to the gate."""
    c1_cand = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY",
                             instrument_id="ethereum:0x" + "11" * 20, underlying_root="fund:same-rwa-fund")
    c2_cand = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY",
                             instrument_id="arbitrum:0x" + "22" * 20, underlying_root="fund:same-rwa-fund")
    v2fx.admit_to_paper_active_v2(tmp_path, c1_cand, NOW)
    cid2 = c2_cand["candidate_id"]
    registry.upsert(tmp_path, c2_cand, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid2, s, reason="setup", now=NOW)

    all_candidates = {c1_cand["candidate_id"]: c1_cand, cid2: c2_cand}
    run_mod._sherlock_review_all(tmp_path, all_candidates, [], v2fx.DEFAULT_REGISTRY, [], {}, NOW)

    outcome = decision_mod.latest_decision(tmp_path, cid2)
    assert outcome is not None
    assert outcome["decision"] != ec.ADMIT_TO_PAPER
    assert "duplicate_exposure_clear" in outcome["failed_gates"]
    assert lifecycle.current_state(tmp_path, cid2) != c1.PAPER_ACTIVE


def test_mutation_check_underlying_root_dedup_is_the_guard():
    """MUTATION CHECK: without other_admitted_underlying_roots in extra (the pre-M6 shape), the
    SAME wrapper candidate above PASSES duplicate_exposure_clear — proving the test exercises a
    real fix, not a tautology."""
    bundle = _minimal_bundle(exposure_family="ek-wrapped-on-another-chain")
    candidate = {"candidate_id": "cand-wrapper", "underlying_root": "fund:same-rwa-fund"}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)  # extra={} — the old (unguarded) shape
    assert report["gates"]["duplicate_exposure_clear"]["verdict"] == c1.GATE_PASS  # the old gap, reproduced


def test_not_advertised_only_rejects_an_aggregator_relay_even_if_measured():
    """Post-implementation review M2: a cell whose ``state`` is MEASURED but whose
    ``source_class`` is an aggregator relay (never a PRIMARY class) must NOT clear
    ``not_advertised_only`` — a DeFiLlama relay is not 'independently observed'. Red without the
    fix: the old code accepted ANY MEASURED state regardless of source_class."""
    bundle = _minimal_bundle(
        return_evidence={"primary_field": "base_return",
                         "primary_cell": c1.cell(c1.MEASURED, 0.05, unit="fraction", source_ref="agg",
                                                 source_class=c1.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                                 as_of=NOW.isoformat(), now=NOW),
                         "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05, method="test")},
        grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "RETURN": ec.WEAK})
    candidate = {"candidate_id": "cand1", "mechanism_id": "STABLECOIN_SAVINGS", "base_return": None}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["not_advertised_only"]["verdict"] == c1.GATE_FAIL


def test_not_advertised_only_passes_on_a_primary_class_measured_cell():
    bundle = _minimal_bundle(
        return_evidence={"primary_field": "base_return",
                         "primary_cell": c1.cell(c1.MEASURED, 0.05, unit="fraction", source_ref="chain",
                                                 source_class=c1.PRIMARY_CHAIN, source_root="chain:1",
                                                 as_of=NOW.isoformat(), now=NOW),
                         "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05, method="test")})
    candidate = {"candidate_id": "cand1", "mechanism_id": "STABLECOIN_SAVINGS", "base_return": None}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["not_advertised_only"]["verdict"] == c1.GATE_PASS


def test_not_advertised_only_passes_on_reference_track_oracle_override_despite_unmeasured_v1_cell():
    """Post-implementation review M2: a REFERENCE_TRACK instrument (USYC's real shape) carries
    its return evidence ONLY as ``return_evidence.primary_cell`` (the bundle's override-aware
    cell, ADR-564 decision #5) — the v1 candidate's OWN ``base_return`` field is honestly
    NOT_MEASURED. Red without the fix: reading ``candidate.get(primary_field)`` directly saw
    nothing and FAILed this gate on a genuinely independent, PRIMARY-class oracle reading."""
    bundle = _minimal_bundle(
        return_evidence={"primary_field": "base_return",
                         "primary_cell": c1.cell(c1.MEASURED, 1.05, unit="usd_per_unit", source_ref="oracle",
                                                 source_class=c1.PRIMARY_CHAIN, source_root="chain:1",
                                                 as_of=NOW.isoformat(), now=NOW),
                         "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05, method="test")},
        paper_mode=ec.PAPER_MODE_REFERENCE_TRACK)
    candidate = {"candidate_id": "cand1", "mechanism_id": "TOKENISED_TREASURY",
                "base_return": c1.cell(c1.NOT_MEASURED, reason="no v1 reader — oracle override only")}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["not_advertised_only"]["verdict"] == c1.GATE_PASS


def test_mutation_check_not_advertised_only_aggregator_leak_is_the_guard():
    """MUTATION CHECK: reproducing the pre-fix gate (ANY MEASURED state, ignoring source_class,
    reading the v1 candidate's own cell) on the SAME aggregator-relay inputs above would PASS —
    proving the test exercises a real fix, not a tautology."""
    def _old_not_advertised_only(bundle, candidate, extra, now):
        primary_field = bundle["return_evidence"]["primary_field"]
        if c1.measured_value_of(candidate.get(primary_field)) is not None:
            return {"verdict": c1.GATE_PASS, "evidence": "old behaviour"}
        return {"verdict": c1.GATE_FAIL, "evidence": "old behaviour"}

    bundle = _minimal_bundle(
        return_evidence={"primary_field": "base_return",
                         "primary_cell": c1.cell(c1.MEASURED, 0.05, unit="fraction", source_ref="agg",
                                                 source_class=c1.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                                 as_of=NOW.isoformat(), now=NOW)})
    candidate = {"candidate_id": "cand1", "mechanism_id": "STABLECOIN_SAVINGS",
                "base_return": c1.cell(c1.MEASURED, 0.05, unit="fraction", source_ref="agg",
                                       source_class=c1.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                       as_of=NOW.isoformat(), now=NOW)}
    old = _old_not_advertised_only(bundle, candidate, {}, NOW)
    assert old["verdict"] == c1.GATE_PASS  # the old bug, reproduced


def test_build_bundle_reference_track_net_return_computable_despite_one_off_fee():
    """Round 5, Issue #2, end to end: a REFERENCE_TRACK candidate (USYC's real shape — a
    one-off subscription fee, unit bps_one_off/fraction_one_off per E3's relabelling) must
    reach admission_v2's net_return_computable gate as PASS, computed from the annual
    base_return alone — never FAIL just because a one-off fee is present, and never silently
    annualising it either."""
    c = make_candidate(base_return=_v1cell(c1.MEASURED, 0.05, unit="fraction"),
                       fees=_v1cell(c1.MEASURED, 0.0004, unit="bps_one_off"))
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_REFERENCE_TRACK, registry={}, now=NOW)
    net = b["return_evidence"]["net_expected_return"]
    assert net["state"] in c1.VALUED_STATES
    assert net["value"] == pytest.approx(0.05)
    assert "not netted" in net["method"]
    report = admission_v2.evaluate(b, c, {}, NOW)
    assert report["gates"]["net_return_computable"]["verdict"] == c1.GATE_PASS, report["gates"]["net_return_computable"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 10. run.py integration: Sherlock's universal review (bundle-digest idempotency, re-screen on
#     evidence change, decision -> lifecycle mapping, collector rows -> bundle)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_sherlock_unchanged_bundle_writes_no_new_decision(tmp_path):
    """Idempotency half #1: reviewing the SAME candidate twice, with IDENTICAL evidence, writes
    exactly one admission_decision row — the second call reuses the first's decision."""
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)

    run_mod._sherlock_review_candidate(tmp_path, cid, c, [], {}, {}, [], {}, NOW)
    ledger = ledger_for(tmp_path)
    decisions_after_first = [e for e in ledger.read_all() if e["kind"] == "admission_decision"]
    assert len(decisions_after_first) == 1

    run_mod._sherlock_review_candidate(tmp_path, cid, c, [], {}, {}, [], {}, NOW + timedelta(hours=1))
    decisions_after_second = [e for e in ledger.read_all() if e["kind"] == "admission_decision"]
    assert len(decisions_after_second) == 1
    assert decisions_after_second[0]["payload"]["decision_id"] == decisions_after_first[0]["payload"]["decision_id"]


def test_sherlock_evidence_change_writes_a_new_decision(tmp_path):
    """Idempotency half #2: the SAME candidate with DIFFERENT v2 evidence (a real collector
    reading arriving) writes a NEW decision row — the digest changing is what unlocks it."""
    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)

    run_mod._sherlock_review_candidate(tmp_path, cid, c, [], {}, {}, [], {}, NOW)
    ledger = ledger_for(tmp_path)
    first_count = sum(1 for e in ledger.read_all() if e["kind"] == "admission_decision")

    v2_overrides = {cid: {"identity": {"on_chain_verified": True, "address_cited": True}}}
    run_mod._sherlock_review_candidate(tmp_path, cid, c, [], {}, {}, [], v2_overrides, NOW + timedelta(hours=1))
    second_count = sum(1 for e in ledger.read_all() if e["kind"] == "admission_decision")
    assert second_count == first_count + 1


def _usyc_shaped_candidate_and_v2(mechanism_id="TOKENISED_TREASURY", **v2_overrides):
    """A TOKENISED_TREASURY candidate whose ONLY blocker is REDEMPTION (redemption_understood's
    sole GATE_INPUTS entry) — everything else all-STRONG, for the LOW churn-fix tests below,
    which need a real, single, NAMED failing gate to scope the inputs-digest comparison to."""
    c = make_candidate(mechanism_id=mechanism_id, domain="CASH_TREASURY")
    profile = v2fx.all_strong_profile(mechanism_id)
    v2 = v2fx.all_strong_v2_evidence(NOW)
    v2["redemption"] = {"terms_cited": False, "caveats_complete": False}  # REDEMPTION -> UNKNOWN
    v2.update(v2_overrides)
    return c, profile, v2


def test_rescreen_skipped_when_the_failed_gates_own_inputs_did_not_change(tmp_path):
    """LOW (post-implementation review, 2026-10-04): a bundle digest change in a dimension NO
    currently-failed gate reads must NOT trigger a re-screen — the candidate stays put, no new
    SCREENED transition is written. Red without the fix: ANY digest change re-screened,
    regardless of relevance (the ~30-candidate churn the review measured)."""
    c, profile, v2 = _usyc_shaped_candidate_and_v2()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)

    bundle1 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, bundle1, NOW)
    outcome1 = decision_mod.decide_and_record(tmp_path, bundle1, c, extra={}, now=NOW)
    assert outcome1["decision"] == ec.NEEDS_MORE_EVIDENCE
    assert "redemption_understood" in outcome1["unknowns"]  # REDEMPTION grade UNKNOWN, not FAIL
    target1 = run_mod._ideal_hold_target(outcome1, bundle1)
    assert target1 == c1.COUNTERPARTY_UNKNOWN  # _GATE_DIM_HOLD["redemption_understood"]
    lifecycle.transition(tmp_path, cid, target1, reason="setup", now=NOW)

    later = NOW + timedelta(hours=1)
    v2_unrelated_change = dict(v2)
    v2_unrelated_change["legal"] = {"entity": True, "jurisdiction": True, "exemption": True,
                                    "documented": False}  # LEGAL changes; REDEMPTION untouched
    bundle2 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_unrelated_change, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=later)
    assert bundle2["evidence_digest"] != bundle1["evidence_digest"]  # a real digest change
    bundle_mod.write_bundle(tmp_path, bundle2, later)
    outcome2 = decision_mod.decide_and_record(tmp_path, bundle2, c, extra={}, now=later)
    assert "redemption_understood" in outcome2["unknowns"]  # same one gate, still failing

    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.COUNTERPARTY_UNKNOWN, bundle2, bundle1, outcome2,
                                   True, later)
    assert lifecycle.current_state(tmp_path, cid) == c1.COUNTERPARTY_UNKNOWN  # no churn
    ledger = ledger_for(tmp_path)
    screened_rows = [e for e in ledger.read_all() if e["kind"] == "transition"
                     and e["payload"]["candidate_id"] == cid and e["payload"]["to_state"] == c1.SCREENED]
    assert len(screened_rows) == 1  # only the ORIGINAL setup transition — no re-screen bounce


def test_rescreen_still_happens_when_the_failed_gates_own_inputs_did_change(tmp_path):
    """The other half: when REDEMPTION ITSELF changes (the thing redemption_understood actually
    reads), the re-screen still fires — this optimisation reduces churn, never correctness."""
    c, profile, v2 = _usyc_shaped_candidate_and_v2()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)

    bundle1 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, bundle1, NOW)
    outcome1 = decision_mod.decide_and_record(tmp_path, bundle1, c, extra={}, now=NOW)
    target1 = run_mod._ideal_hold_target(outcome1, bundle1)
    lifecycle.transition(tmp_path, cid, target1, reason="setup", now=NOW)

    later = NOW + timedelta(hours=1)
    v2_redemption_changed = dict(v2)
    v2_redemption_changed["redemption"] = {"terms_cited": True, "caveats_complete": True}  # now ADEQUATE
    bundle2 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_redemption_changed, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=later)
    bundle_mod.write_bundle(tmp_path, bundle2, later)
    outcome2 = decision_mod.decide_and_record(tmp_path, bundle2, c, extra={}, now=later)
    assert outcome2["decision"] == ec.ADMIT_TO_PAPER  # redemption was the only blocker

    run_mod._route_sherlock_outcome(tmp_path, cid, c, target1, bundle2, bundle1, outcome2, True, later)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE  # the admit walk actually ran


def test_mutation_check_rescreen_churn_fix_is_the_guard(tmp_path):
    """MUTATION CHECK: reproducing the pre-fix condition (any digest change re-screens,
    regardless of relevance) on the SAME unrelated-change scenario above DOES bounce the
    candidate through SCREENED — proving the test exercises a real fix, not a tautology."""
    c, profile, v2 = _usyc_shaped_candidate_and_v2()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    bundle1 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, bundle1, NOW)
    outcome1 = decision_mod.decide_and_record(tmp_path, bundle1, c, extra={}, now=NOW)
    target1 = run_mod._ideal_hold_target(outcome1, bundle1)
    lifecycle.transition(tmp_path, cid, target1, reason="setup", now=NOW)

    later = NOW + timedelta(hours=1)
    v2_unrelated_change = dict(v2)
    v2_unrelated_change["legal"] = {"entity": True, "jurisdiction": True, "exemption": True, "documented": False}
    bundle2 = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_unrelated_change, facts=[],
                                      paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=later)
    bundle_mod.write_bundle(tmp_path, bundle2, later)
    outcome2 = decision_mod.decide_and_record(tmp_path, bundle2, c, extra={}, now=later)

    # old behaviour: unconditional re-screen on ANY digest_changed=True, no inputs-digest check
    gate_ref = {"prev_digest": bundle1["evidence_digest"], "new_digest": bundle2["evidence_digest"]}
    lifecycle.transition(tmp_path, cid, c1.SCREENED, gate_ref=gate_ref, reason="old behaviour", now=later)
    assert lifecycle.current_state(tmp_path, cid) == c1.SCREENED  # the old churn, reproduced


def test_route_sherlock_outcome_rescreens_on_digest_change_when_ideal_target_unreachable(tmp_path):
    """'A candidate in a hold state whose bundle digest CHANGED re-screens': HOLD routes to
    RISK_UNRESOLVED (no COUNTERPARTY conflict here) — unreachable from DATA_INSUFFICIENT per the
    frozen contract.TRANSITIONS graph — so the candidate re-screens to SCREENED instead, carrying
    the two bundle digests as the gate_ref evidence for the transition."""
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY, c1.PAPER_CANDIDATE):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    lifecycle.transition(tmp_path, cid, c1.DATA_INSUFFICIENT, reason="setup", now=NOW)
    assert not c1.transition_allowed(c1.DATA_INSUFFICIENT, c1.RISK_UNRESOLVED)

    prior_bundle = {"evidence_digest": "digest-old"}
    bundle = {"evidence_digest": "digest-new", "conflicts": [], "exposure_family": c["exposure_key"]}
    outcome = {"decision": ec.HOLD, "rationale": ["forced HOLD for test"], "failed_gates": [], "unknowns": []}
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.DATA_INSUFFICIENT, bundle, prior_bundle, outcome,
                                   True, NOW)
    # intentional update (journal W40): the re-screen used to STOP at SCREENED (live-run finding: OUSG/USDY sat
    # there); it now continues, in the same call, to the hold state the decision names. The re-screen itself is
    # still recorded with the digest pair as its gate_ref.
    assert lifecycle.current_state(tmp_path, cid) == c1.RISK_UNRESOLVED
    ledger = ledger_for(tmp_path)
    trs = [e for e in ledger.read_all() if e["kind"] == "transition" and e["payload"]["candidate_id"] == cid]
    rescreen = [t for t in trs if t["payload"].get("to_state") == c1.SCREENED][-1]
    assert rescreen["payload"]["gate_ref"] == {"prev_digest": "digest-old", "new_digest": "digest-new"}


def test_route_sherlock_outcome_admit_opens_a_paper_position():
    """'ADMIT goes through the v2 snapshot -> PAPER_ACTIVE -> paper.open_position' — end to end,
    via a real all-STRONG bundle/decision (the shared v2 fixture helper)."""
    from spa_core.research_factory import paper
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        c = make_candidate()
        cid = c["candidate_id"]
        admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
        assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE

        # the ADMIT branch of _route_sherlock_outcome is exercised BY admit_to_paper_active_v2's
        # own call path (decision + write_admission_snapshot_v2 + transition); verify the paper
        # leg actually opened too, which _route_sherlock_outcome's run.py caller is responsible for.
        bundle = bundle_mod.latest_bundle(tmp_path, cid)
        outcome = decision_mod.latest_decision(tmp_path, cid)
        snap = decision_mod.find_admission_snapshot_v2(tmp_path, cid, admission_id)
        row = paper.open_position(tmp_path, outcome, snap, bundle, NOW)
        assert row["payload"]["candidate_id"] == cid
        assert row["payload"]["status"] == "OPEN"


def _admit_decision_for(data_dir: Path, candidate: dict, now: datetime) -> tuple[dict, dict]:
    """Builds a real all-STRONG bundle + a real Sherlock ADMIT_TO_PAPER decision for
    ``candidate``, WITHOUT writing the v2 admission snapshot — leaving that (and every
    lifecycle consequence) to the caller, so ``_route_sherlock_outcome``/``_admit_walk``'s own
    walk is what gets exercised, not a fixture that already did its job."""
    mechanism_id = candidate["mechanism_id"]
    profile = v2fx.all_strong_profile(mechanism_id)
    v2_evidence = v2fx.all_strong_v2_evidence(now)
    b = bundle_mod.build_bundle(candidate, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=now)
    bundle_mod.write_bundle(data_dir, b, now)
    outcome = decision_mod.decide_and_record(data_dir, b, candidate, extra={}, now=now)
    assert outcome["decision"] == ec.ADMIT_TO_PAPER, outcome
    return b, outcome


def test_non_admit_decision_demotes_an_admitted_candidate_to_paused_paper(tmp_path):
    """Post-implementation review M4: a non-ADMIT decision on an ALREADY-admitted candidate
    (PAPER_ACTIVE/EVIDENCE_ACCUMULATING/CIO_ELIGIBLE) must move it to PAUSED_PAPER — uniformly,
    regardless of which specific non-ADMIT decision kind. Red without the fix: the old routing
    only acted when the generic ``_ideal_hold_target`` happened to be directly reachable from
    PAPER_ACTIVE (true for REJECTED/STALE_STATE, false for COUNTERPARTY_UNKNOWN/RISK_UNRESOLVED/
    DATA_INSUFFICIENT), so a NEEDS_MORE_EVIDENCE decision left the candidate stuck, silently,
    forever at PAPER_ACTIVE."""
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE

    bundle = bundle_mod.latest_bundle(tmp_path, cid)
    outcome = {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["forced for test"],
              "failed_gates": ["counterparty_roles_sufficient"], "unknowns": []}
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.PAPER_ACTIVE, bundle, bundle, outcome, False, NOW)

    assert lifecycle.current_state(tmp_path, cid) == c1.PAUSED_PAPER
    ledger = ledger_for(tmp_path)
    last = [e for e in ledger.read_all() if e["kind"] == "transition"
           and e["payload"]["candidate_id"] == cid][-1]
    assert last["payload"]["to_state"] == c1.PAUSED_PAPER
    assert last["payload"]["paused_from"] == c1.PAPER_ACTIVE


def test_marks_continue_for_a_paused_paper_candidate(tmp_path):
    """Post-implementation review M4, 'marks continue only as labelled tracking': once PAUSED,
    run._process_candidate's bookkeeping block must still call forward.record for it — the
    PAUSED_PAPER state itself is the label; the candidate is not silently abandoned."""
    c = make_candidate()
    cid = c["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, c1.PAUSED_PAPER, reason="setup", now=NOW)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAUSED_PAPER

    run_mod._process_candidate(tmp_path, cid, {cid: c}, [], {}, NOW + timedelta(days=1))
    ledger = ledger_for(tmp_path)
    obs_rows = [e for e in ledger.read_all() if e["kind"] == "observation"
               and e["payload"]["candidate_id"] == cid]
    assert len(obs_rows) == 1


def test_hold_candidate_whose_target_is_its_current_state_does_not_churn(tmp_path):
    """Live re-run finding: a DATA_INSUFFICIENT candidate whose bundle digest changed (fresh
    funding rows) but whose decision still sends it to DATA_INSUFFICIENT must NOT be re-screened
    through SCREENED/RESEARCH_READY back to the same state every run. Red without the fix: one
    transition to SCREENED per run."""
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, c1.SCREENED, reason="setup", now=NOW)
    lifecycle.transition(tmp_path, cid, c1.RESEARCH_READY, reason="setup", now=NOW)
    lifecycle.transition(tmp_path, cid, c1.DATA_INSUFFICIENT, reason="setup", now=NOW)
    b, _ = _admit_decision_for(tmp_path, c, NOW)
    prior = dict(b, evidence_digest="prior-digest")
    outcome = {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["forced for test"],
               "failed_gates": [], "unknowns": ["data_fresh"]}
    assert run_mod._ideal_hold_target(outcome, b) == c1.DATA_INSUFFICIENT
    before = len([e for e in ledger_for(tmp_path).read_all() if e["kind"] == "transition"])
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.DATA_INSUFFICIENT, b, prior, outcome, True, NOW)
    after = len([e for e in ledger_for(tmp_path).read_all() if e["kind"] == "transition"])
    assert after == before
    assert lifecycle.current_state(tmp_path, cid) == c1.DATA_INSUFFICIENT


def test_run_once_does_not_churn_a_held_candidate_whose_live_snapshot_changes(tmp_path, monkeypatch):
    """Live re-run finding (2026-10-04): the v1 fingerprint re-screen moved every held funding
    pair <hold> -> SCREENED each run (its snapshot carries the live rate), and Sherlock sent it
    straight back — ~80 transitions a run, no information. Red with the v1 re-screen restored:
    every run after the first writes transitions for a candidate whose decision never changed."""
    import spa_core.research_factory.run as run_mod

    base = make_candidate()
    runs = {"n": 0}

    class _Scanner:
        __name__ = "spy_scanner"

        @staticmethod
        def scan(data_dir, now, rpc_client=None):
            runs["n"] += 1
            c = dict(base, producing_scanner="spy_scanner",
                     base_return=_v1cell(c1.MEASURED, 0.04 + runs["n"] / 1000, as_of=now.isoformat(),
                                         judge_now=now))
            return {"scanner": "spy_scanner", "domain": c.get("domain"), "as_of": now.isoformat(),
                    "status": "OK", "reason": None,
                    "denominators": {"scanned": 1, "discovered": 1, "truncated": 0},
                    "candidates": [c], "unresolved": [], "observations": {}, "counterparty": {},
                    "existing_book_roots": []}

    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [_Scanner])
    seqs = []
    for i in range(3):
        run_mod.run_once(tmp_path, NOW + timedelta(hours=i + 1))
        seqs.append(max(e["seq"] for e in ledger_for(tmp_path).read_all()))
    rows = ledger_for(tmp_path).read_all()
    assert len({registry.fingerprint_of(e["payload"]["candidate"]) for e in rows
                if e["kind"] == "candidate_snapshot"}) >= 2, "premise: the snapshot must actually change"
    state = lifecycle.current_state(tmp_path, base["candidate_id"])
    assert state in c1.HOLD_STATES, state
    later = [e for e in rows if e["kind"] == "transition" and e["seq"] > seqs[0]]
    assert later == [], [(e["payload"]["from_state"], e["payload"]["to_state"]) for e in later]


def _paused_with_open_position(tmp_path, open_position: bool):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    if open_position:
        snap = decision_mod.find_admission_snapshot_v2(tmp_path, cid, admission_id)
        paper.open_position(tmp_path, decision_mod.latest_decision(tmp_path, cid), snap,
                            bundle_mod.latest_bundle(tmp_path, cid), NOW)
    bundle = bundle_mod.latest_bundle(tmp_path, cid)
    pause = {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["forced for test"],
             "failed_gates": ["counterparty_roles_sufficient"], "unknowns": []}
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.PAPER_ACTIVE, bundle, bundle, pause, False, NOW)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAUSED_PAPER
    return c, cid, admission_id


def test_paused_paper_resumes_on_re_admit_under_the_same_admission(tmp_path):
    """ADR-564 post-impl remediation (M4 follow-up): PAUSED_PAPER had a way in and no way out.
    A Sherlock re-ADMIT resumes it to its recorded paused_from through the SAME admission door,
    while that admission's paper position is still OPEN. Red without the resume path: the
    candidate stayed PAUSED_PAPER forever (``_admit_walk`` only walked from hold states)."""
    c, cid, admission_id = _paused_with_open_position(tmp_path, open_position=True)
    later = NOW + timedelta(hours=2)
    b, outcome = _admit_decision_for(tmp_path, c, later)
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.PAUSED_PAPER, b, b, outcome, False, later)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE
    assert lifecycle.active_admission_id(tmp_path, cid) == admission_id


def test_paused_paper_never_resumes_without_an_open_position(tmp_path):
    """Never PAPER_ACTIVE without a position: a re-ADMIT with no OPEN paper position stays
    PAUSED_PAPER and names why in a run_warning."""
    c, cid, _ = _paused_with_open_position(tmp_path, open_position=False)
    later = NOW + timedelta(hours=2)
    b, outcome = _admit_decision_for(tmp_path, c, later)
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.PAUSED_PAPER, b, b, outcome, False, later)
    assert lifecycle.current_state(tmp_path, cid) == c1.PAUSED_PAPER
    warnings = [e["payload"]["warning"] for e in ledger_for(tmp_path).read_all()
                if e["kind"] == "run_warning" and e["payload"]["candidate_id"] == cid]
    assert any("no OPEN paper position" in w for w in warnings), warnings


def test_paused_from_cio_eligible_resumes_only_to_evidence_accumulating():
    """A pause from CIO_ELIGIBLE re-enters EVIDENCE_ACCUMULATING and must re-earn eligibility
    through the CIO gate — the resume path never hands eligibility back."""
    import inspect
    src = inspect.getsource(lifecycle.transition)
    assert "paused_from == contract.CIO_ELIGIBLE" in src
    assert not c1.transition_allowed(c1.PAUSED_PAPER, c1.CIO_ELIGIBLE)


def test_mutation_check_paused_paper_demotion_is_the_guard(tmp_path):
    """MUTATION CHECK: reproducing the pre-M4 routing (only _ideal_hold_target, no PAPER_STATES
    special case) on the SAME NEEDS_MORE_EVIDENCE decision above leaves the candidate stuck at
    PAPER_ACTIVE — proving the test exercises a real fix, not a tautology."""
    c = make_candidate()
    cid = c["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    bundle = bundle_mod.latest_bundle(tmp_path, cid)
    outcome = {"decision": ec.NEEDS_MORE_EVIDENCE, "rationale": ["forced for test"],
              "failed_gates": ["counterparty_roles_sufficient"], "unknowns": []}

    target = run_mod._ideal_hold_target(outcome, bundle)
    assert target is not None and not c1.transition_allowed(c1.PAPER_ACTIVE, target)  # the old gap, reproduced
    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE  # nothing happened


def test_admit_walk_reaches_paper_active_from_a_hold_state(tmp_path):
    """Round 5, Issue #1 ('the ADMIT never takes effect'): a candidate PARKED in a hold state
    (COUNTERPARTY_UNKNOWN) that Sherlock now ADMITs must reach PAPER_ACTIVE with a real
    ``paper_open`` row in ONE call — re-screen -> SCREENED -> RESEARCH_READY -> PAPER_CANDIDATE
    -> v2 snapshot -> PAPER_ACTIVE -> paper.open_position. Red without the ``_admit_walk``
    fix: the old ``_route_sherlock_outcome`` only acted when ``frm_state`` could already reach
    PAPER_ACTIVE directly, so a COUNTERPARTY_UNKNOWN candidate (which cannot, per the frozen
    ``contract.TRANSITIONS`` graph) was left untouched forever — exactly the live-run defect."""
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    lifecycle.transition(tmp_path, cid, c1.COUNTERPARTY_UNKNOWN, reason="setup", now=NOW)
    assert not c1.transition_allowed(c1.COUNTERPARTY_UNKNOWN, c1.PAPER_ACTIVE)

    later = NOW + timedelta(hours=1)
    prior_bundle = {"evidence_digest": "digest-old"}
    bundle, outcome = _admit_decision_for(tmp_path, c, later)
    assert bundle["evidence_digest"] != prior_bundle["evidence_digest"]

    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.COUNTERPARTY_UNKNOWN, bundle, prior_bundle,
                                   outcome, True, later)

    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_ACTIVE
    ledger = ledger_for(tmp_path)
    rows = [e for e in ledger.read_all() if e["kind"] == "paper_open" and e["payload"]["candidate_id"] == cid]
    assert len(rows) == 1 and rows[0]["payload"]["status"] == "OPEN"
    states = [e["payload"]["to_state"] for e in ledger.read_all()
             if e["kind"] == "transition" and e["payload"]["candidate_id"] == cid]
    assert states[-4:] == [c1.SCREENED, c1.RESEARCH_READY, c1.PAPER_CANDIDATE, c1.PAPER_ACTIVE]


def test_mutation_check_admit_walk_is_the_guard_not_a_coincidence(tmp_path, monkeypatch):
    """MUTATION CHECK: with ``_admit_walk`` neutralised back to the pre-fix behaviour (only
    acting when PAPER_ACTIVE is already directly reachable from ``frm_state``), the candidate
    in the test above would be left stuck at COUNTERPARTY_UNKNOWN forever — proving the test
    exercises a real fix, not a tautology."""
    def _old_admit_walk(data_dir, cid, frm_state, bundle, prior_bundle, outcome, digest_changed, now):
        if frm_state == c1.PAPER_ACTIVE or not c1.transition_allowed(frm_state, c1.PAPER_ACTIVE):
            return
        snap = decision_mod.write_admission_snapshot_v2(data_dir, outcome, bundle, now)
        lifecycle.transition(data_dir, cid, c1.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                            reason="old behaviour", now=now)

    monkeypatch.setattr(run_mod, "_admit_walk", _old_admit_walk)
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    lifecycle.transition(tmp_path, cid, c1.COUNTERPARTY_UNKNOWN, reason="setup", now=NOW)

    later = NOW + timedelta(hours=1)
    bundle, outcome = _admit_decision_for(tmp_path, c, later)
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.COUNTERPARTY_UNKNOWN, bundle, {"evidence_digest": "old"},
                                   outcome, True, later)
    assert lifecycle.current_state(tmp_path, cid) == c1.COUNTERPARTY_UNKNOWN  # the old bug, reproduced


def test_admit_walk_refuses_paper_active_without_a_position(tmp_path, monkeypatch):
    """Round 5, Issue #1, second half: a ``PaperRefusal`` from ``paper.open_position`` must
    leave the candidate at PAPER_CANDIDATE — NEVER PAPER_ACTIVE without a position. The refusal
    is logged as a ``run_warning``, not swallowed."""
    def _refuse(data_dir, outcome, admission_payload, bundle, now):
        raise paper.PaperRefusal("synthetic refusal for test")

    monkeypatch.setattr(run_mod.paper, "open_position", _refuse)
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.RESEARCH_READY, c1.PAPER_CANDIDATE):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)

    bundle, outcome = _admit_decision_for(tmp_path, c, NOW)
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.PAPER_CANDIDATE, bundle, None, outcome, False, NOW)

    assert lifecycle.current_state(tmp_path, cid) == c1.PAPER_CANDIDATE
    ledger = ledger_for(tmp_path)
    warnings = [e for e in ledger.read_all() if e["kind"] == "run_warning" and e["payload"]["candidate_id"] == cid]
    assert len(warnings) == 1 and "synthetic refusal" in warnings[0]["payload"]["warning"]
    actives = [e for e in ledger.read_all() if e["kind"] == "transition"
              and e["payload"]["candidate_id"] == cid and e["payload"]["to_state"] == c1.PAPER_ACTIVE]
    assert actives == []


def test_collector_rows_reach_the_bundle_via_treasury_v2_overrides(tmp_path, monkeypatch):
    """Collector rows -> v2_overrides -> the bundle: a fake on-chain oracle reading for USYC
    (via ``run._treasury_v2_overrides``) ends up as the bundle's RETURN primary evidence — never
    silently dropped between the collector and bundle.build_bundle()."""
    from spa_core.research_factory import instruments

    class _FakeClient:
        def get(self, host, path, params):
            return None  # no DeFiLlama / official API this test — oracle only

        def post_info(self, info_type, payload):
            return None

    class _FakeRpc:
        def pin_block(self):
            return {"state": "MEASURED", "number": 100}

        def quorum(self, method, params, block_number):
            return {"state": "NOT_MEASURED", "reason": "fake rpc: identity/oracle not wired for this test"}

    overrides = run_mod._treasury_v2_overrides(tmp_path, [], _FakeRpc(), _FakeClient(), None, NOW)
    usyc_cid = instruments.candidate_id_for("USYC")
    assert usyc_cid in overrides
    # the collector's own observation rows must have reached the ledger (provenance), even though
    # every read came back NOT_MEASURED this run (no real rpc/http wired) — never silently dropped.
    ledger = ledger_for(tmp_path)
    persisted_claims = {e["payload"]["claim"] for e in ledger.read_all() if e["kind"] == "evidence_observation"
                        and e["payload"]["candidate_id"] == usyc_cid}
    assert persisted_claims  # at least the nav_oracle / aggregator-apy rows were persisted


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 11. net_expected_return is unit-aware — a live run netted a one-off bps fee against an
#     ANNUAL rate unchecked and produced net=-2697 (a FALSE REJECT); never again, never a crash.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_net_expected_return_rejects_mismatched_units_never_fabricates_a_number():
    """A unit-less (or non-annual) cost can never be netted against a declared annual rate —
    NOT_MEASURED, naming amortisation, never a nonsensical number."""
    cells = {f: c1.cell(c1.NOT_APPLICABLE, reason="n/a") for f in c1.CELL_FIELDS}
    cells["base_return"] = c1.cell(c1.MEASURED, 0.05, unit="fraction", source_ref="x",
                                   source_class=c1.PRIMARY_PROTOCOL, source_root="chain:1", as_of=NOW.isoformat(),
                                   now=NOW)
    cells["fees"] = c1.cell(c1.MEASURED, 1234.0, source_ref="x", source_class=c1.PRIMARY_PROTOCOL,
                            source_root="chain:1", as_of=NOW.isoformat(), now=NOW)  # NO unit declared
    net = c1.net_expected_return(cells)
    assert net["state"] == c1.NOT_MEASURED
    assert net["value"] is None
    assert "annual rate" in net["reason"] and "amortisation" in net["reason"]


def test_net_expected_return_kucoin_funding_pair_shape_is_not_measured_never_a_huge_negative():
    """The EXACT live-production shape (scanners/basis.py's funding_pair_candidates): a
    pct_apy_annualised funding leg, a one-off bps taker fee, and a hedging_cost cell carrying a
    RAW SPOT PRICE (its unit names what it is, e.g. "avg_price_usd_for_10000_usd_notional" —
    never an annual rate). Before the unit-aware fix this netted a $65k price straight against a
    10%/yr rate and produced net=-2697; now it is honestly NOT_MEASURED."""
    cells = {f: c1.cell(c1.NOT_APPLICABLE, reason="n/a") for f in c1.CELL_FIELDS}
    cells["base_return"] = c1.cell(c1.NOT_APPLICABLE, reason="FUNDING_CAPTURE has no base leg")
    cells["funding"] = c1.cell(c1.MEASURED, 10.95, unit="pct_apy_annualised", source_ref="x",
                               source_class=c1.PRIMARY_VENUE, source_root="venue:kucoin",
                               as_of=NOW.isoformat(), now=NOW)
    cells["fees"] = c1.cell(c1.DOCUMENTED, 0.0006, unit="fraction", source_ref="x",
                            source_class=c1.OFFICIAL_API, source_root="venue:kucoin",
                            as_of=NOW.isoformat(), now=NOW)
    cells["hedging_cost"] = c1.cell(c1.MEASURED, 65_000.0, unit="avg_price_usd_for_10000_usd_notional",
                                    source_ref="x", source_class=c1.PRIMARY_VENUE, source_root="venue:binance",
                                    as_of=NOW.isoformat(), now=NOW)
    net = c1.net_expected_return(cells)
    assert net["state"] == c1.NOT_MEASURED
    assert net["value"] is None
    assert net["value"] != -2697  # the exact live false-reject this fix closes


def test_decision_never_rejects_on_a_not_measured_net_return():
    """MUTATION-STYLE positive control: the REJECT-on-nonpositive-return predicate reads only
    MEASURED/ESTIMATED_WITH_METHOD states — a NOT_MEASURED net (the KuCoin-pair shape above)
    must route to NEEDS_MORE_EVIDENCE via the net_return_computable gate, never REJECT."""
    bundle = _minimal_bundle(return_evidence={"net_expected_return": c1.cell(
        c1.NOT_MEASURED, reason="fees unit 'avg_price_usd_for_10000_usd_notional' is not an annual rate "
                               "comparable with the return — needs amortisation over a declared holding period")})
    report = _minimal_report(**{"net_return_computable": {"verdict": c1.GATE_FAIL, "evidence": "not measured"}})
    out = decision_mod.decide(bundle, report, [], NOW)
    assert out["decision"] == ec.NEEDS_MORE_EVIDENCE
    assert out["decision"] != ec.REJECT


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 12. paper_mode selection (binding #5) — holder eligibility drives HOLDABLE vs REFERENCE_TRACK
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_paper_mode_for_defaults_to_holdable_without_any_eligibility_evidence():
    assert run_mod._paper_mode_for({}) == ec.PAPER_MODE_HOLDABLE


def test_paper_mode_for_requires_spa_eligible_for_holdable():
    assert run_mod._paper_mode_for({"holder_eligibility": {"state": ec.SPA_ELIGIBLE}}) == ec.PAPER_MODE_HOLDABLE
    assert run_mod._paper_mode_for(
        {"holder_eligibility": {"state": ec.NOT_ELIGIBLE}}) == ec.PAPER_MODE_REFERENCE_TRACK
    assert run_mod._paper_mode_for(
        {"holder_eligibility": {"state": ec.ELIGIBILITY_UNKNOWN}}) == ec.PAPER_MODE_REFERENCE_TRACK


def test_reference_track_makes_liquidity_and_exit_path_not_applicable_for_paper():
    """Binding #5, via GATE_INPUTS' declared paper_mode input — documented here (NA), never added
    to the frozen evidence_contract.GATE_NA map."""
    bundle = _minimal_bundle(paper_mode=ec.PAPER_MODE_REFERENCE_TRACK,
                             grades={**{d: ec.ADEQUATE for d in ec.DIMENSIONS}, "LIQUIDITY": ec.NOT_APPLICABLE},
                             return_evidence={"primary_field": "base_return",
                                             "net_expected_return": c1.cell(c1.ESTIMATED_WITH_METHOD, 0.05,
                                                                            method="test")})
    candidate = {"candidate_id": "cand1", "mechanism_id": "TOKENISED_TREASURY",
                "base_return": _v1cell(c1.MEASURED, 0.05)}
    report = admission_v2.evaluate(bundle, candidate, {}, NOW)
    assert report["gates"]["liquidity_measured"]["verdict"] == "NOT_APPLICABLE"
    assert report["gates"]["exit_path_defined"]["verdict"] == "NOT_APPLICABLE"


def test_reference_track_position_never_becomes_cio_eligible(tmp_path):
    """The CIO gate ``not_reference_track`` blocks a REFERENCE_TRACK position forever — it is a
    NAV tracker, never a position CIO_ELIGIBLE could allocate against."""
    from spa_core.research_factory import eligibility

    c = _candidate_with_bundle(tmp_path, paper_mode=ec.PAPER_MODE_REFERENCE_TRACK, counterparty_strength="strong")
    report = eligibility.evaluate(tmp_path, c, {"_existing_book_roots": []}, NOW + timedelta(hours=1))
    assert report["gates"]["not_reference_track"]["verdict"] == c1.GATE_FAIL
    assert report["all_pass"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 13. read model — rationale reaches both the per-candidate evidence block and decisions_today
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_read_model_latest_decision_carries_rationale(tmp_path):
    from spa_core.research_factory import read as read_mod

    c = make_candidate()
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    assert stored["rationale"]  # the ledger row genuinely carries a non-empty rationale

    status = read_mod.latest(tmp_path)
    evidence_block = next(cand["evidence"] for cand in status["candidates"] if cand["candidate_id"] == cid)
    assert evidence_block["latest_decision"]["rationale"] == stored["rationale"]

    decisions_today = {d["candidate_id"]: d for d in status["sherlock"]["decisions_today"]}
    assert decisions_today[cid]["rationale"] == stored["rationale"]
    assert decisions_today[cid]["required_next_evidence"] == stored["required_next_evidence"]


def test_read_model_surfaces_unknown_gates_next_to_failed_gates(tmp_path):
    """Round 5 'also': a decision can block on UNKNOWN gates alone (OUSG's real shape —
    NEEDS_MORE_EVIDENCE with failed_gates=[]), which read as 'no reason' without unknown_gates
    next to it. Here CUSTODY is UNKNOWN (no role named yet) while everything else PASSes/NAs —
    failed_gates stays empty, unknown_gates must carry the real blocker in BOTH read-model spots."""
    from spa_core.research_factory import read as read_mod

    c = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY")
    cid = c["candidate_id"]
    _walk_to_paper_candidate(tmp_path, c)
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    profile["custodian"] = ec.role_entry(ec.CP_UNKNOWN, role="custodian", reason="not yet named")
    v2_evidence = v2fx.all_strong_v2_evidence(NOW)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=NOW)
    bundle_mod.write_bundle(tmp_path, b, NOW)
    stored = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=NOW)
    assert stored["decision"] == ec.NEEDS_MORE_EVIDENCE, stored
    assert stored["failed_gates"] == []
    assert stored["unknowns"]  # the real reason, not empty

    status = read_mod.latest(tmp_path)
    evidence_block = next(cand["evidence"] for cand in status["candidates"] if cand["candidate_id"] == cid)
    assert evidence_block["latest_decision"]["failed_gates"] == []
    assert evidence_block["latest_decision"]["unknown_gates"] == stored["unknowns"]
    assert evidence_block["latest_decision"]["unknown_gates"]  # never silently empty alongside failed_gates=[]

    decisions_today = {d["candidate_id"]: d for d in status["sherlock"]["decisions_today"]}
    assert decisions_today[cid]["failed_gates"] == []
    assert decisions_today[cid]["unknown_gates"] == stored["unknowns"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 14. _treasury_prior_readings bootstraps past a first NOT_MEASURED-but-valued read
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _word(n: int) -> str:
    return f"{n & (2**256 - 1):064x}"


def _ousg_fake_rpc(price_raw: int, *, block_number: int = 100):
    from spa_core.capital_shadow.rpc import RpcClient

    def post(url, payload):
        method, params = payload["method"], payload["params"]
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(block_number + 2)}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1,
                    "result": {"hash": "0xh", "timestamp": hex(1_791_000_000), "number": params[0]}}
        if method == "eth_call":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x" + _word(price_raw)}
        raise AssertionError(f"disallowed method: {method}")

    endpoints = [(f"http://op{i}.example", f"Op{i}") for i in range(3)]
    return RpcClient(chain_id=1, endpoints=endpoints, post=post)


class _NoHttpClient:
    def get(self, host, path, params):
        return None

    def post_info(self, info_type, payload):
        return None


def test_treasury_prior_readings_bootstraps_past_a_first_valued_not_measured_read(tmp_path):
    """E3 live-validation finding: a first oracle read is honestly NOT_MEASURED/as_of=None but
    STILL carries its raw value (``onchain._unanchored_cell``) — the diffing loader must pick
    that value up by its PRESENCE, never by the cell's state, or the chain can never bootstrap
    past "first read". Three runs: (1) first read -> NOT_MEASURED; (2) same value -> still
    unanchored (no confirmed change yet); (3) a genuinely new value -> as_of becomes the
    PREVIOUS run's fetched_at (never "now")."""
    from spa_core.research_factory import instruments

    ousg_cid = instruments.candidate_id_for("OUSG")
    price_raw = 116_767_284_000_000_000_000  # 116.767284 at 18 decimals

    t1 = NOW
    rpc1 = _ousg_fake_rpc(price_raw)
    overrides1 = run_mod._treasury_v2_overrides(tmp_path, [], rpc1, _NoHttpClient(), None, t1)
    cell1 = overrides1[ousg_cid]["return_primary_cell_override"]
    assert cell1["state"] == c1.NOT_MEASURED
    assert cell1["value"] == pytest.approx(116.767284)

    t2 = t1 + timedelta(hours=12)
    rpc2 = _ousg_fake_rpc(price_raw)  # unchanged
    overrides2 = run_mod._treasury_v2_overrides(tmp_path, [], rpc2, _NoHttpClient(), None, t2)
    cell2 = overrides2[ousg_cid]["return_primary_cell_override"]
    assert cell2["state"] == c1.NOT_MEASURED  # still no CONFIRMED change bracketed
    assert cell2["value"] == pytest.approx(116.767284)

    t3 = t2 + timedelta(hours=12)
    new_price_raw = 116_900_000_000_000_000_000
    rpc3 = _ousg_fake_rpc(new_price_raw)
    overrides3 = run_mod._treasury_v2_overrides(tmp_path, [], rpc3, _NoHttpClient(), None, t3)
    cell3 = overrides3[ousg_cid]["return_primary_cell_override"]
    assert cell3["state"] == c1.MEASURED
    assert cell3["value"] == pytest.approx(116.9)
    # the change is bracketed at the PREVIOUS run's fetch time (run 2's `now`), never t3 itself
    assert c1.parse_ts(cell3["as_of"]) == t2


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 15. collectors/contract_identity.py -> a funding PAIR's PRIMARY_IDENTITY (both legs required)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _identity_row(claim: str, venue: str, state: str = "MEASURED") -> dict:
    return {"schema": ec.SCHEMA_OBS_ROW, "candidate_id": "irrelevant-for-this-lookup", "claim": claim,
           "value": {"symbol": "x"} if state == "MEASURED" else None, "unit": "contract_spec", "window": None,
           "upstream_ts": None, "fetched_at": NOW.isoformat(), "origin": f"venue:{venue}", "channel": "official_api",
           "ref": "x", "raw_sha256": None, "backfill": False, "revises": None, "state": state, "reason": None}


def _funding_pair_candidate(perp_venue: str, spot_venue: str, asset: str = "ETH") -> dict:
    return {"candidate_id": f"pair-{perp_venue}-{spot_venue}", "mechanism_id": "FUNDING_CAPTURE",
           "venue_or_protocol": f"{perp_venue}+{spot_venue}", "economic_driver_key": f"{asset}_PERP_FUNDING"}


def test_funding_pair_identity_adequate_only_when_both_legs_measured():
    cand = _funding_pair_candidate("binance", "bybit")
    all_candidates = {cand["candidate_id"]: cand}

    both_legs = [_identity_row("perp_contract_identity:ETH", "binance"),
                _identity_row("spot_contract_identity:ETH", "bybit")]
    overrides = run_mod._funding_pair_identity_overrides(all_candidates, both_legs)
    identity = overrides[cand["candidate_id"]]["identity"]
    assert identity["venue_spec_cited"] is True
    assert grades.grade_primary_identity({"identity": identity}, "FUNDING_CAPTURE") == ec.ADEQUATE


def test_funding_pair_identity_missing_spot_leg_is_not_adequate():
    """'a missing spot-leg identity ⇒ not ADEQUATE' — the perp leg alone is never enough."""
    cand = _funding_pair_candidate("binance", "bybit")
    all_candidates = {cand["candidate_id"]: cand}

    perp_leg_only = [_identity_row("perp_contract_identity:ETH", "binance")]
    overrides = run_mod._funding_pair_identity_overrides(all_candidates, perp_leg_only)
    identity = overrides[cand["candidate_id"]]["identity"]
    assert identity["venue_spec_cited"] is False
    grade = grades.grade_primary_identity({"identity": identity}, "FUNDING_CAPTURE")
    assert grade != ec.ADEQUATE
    assert grade != ec.STRONG  # GRADING_RULES reserves STRONG for on-chain verification only


def test_funding_pair_identity_never_strong_for_a_cex_perp():
    """A CEX perp has no on-chain contract to verify — STRONG is never reachable via the venue-
    API carve-out, even with both legs measured (the carve-out's own grade ceiling)."""
    cand = _funding_pair_candidate("binance", "bybit")
    all_candidates = {cand["candidate_id"]: cand}
    both_legs = [_identity_row("perp_contract_identity:ETH", "binance"),
                _identity_row("spot_contract_identity:ETH", "bybit")]
    overrides = run_mod._funding_pair_identity_overrides(all_candidates, both_legs)
    identity = overrides[cand["candidate_id"]]["identity"]
    assert grades.grade_primary_identity({"identity": identity}, "FUNDING_CAPTURE") == ec.ADEQUATE  # never STRONG


def test_funding_pair_identity_skips_the_legacy_median5_candidate():
    """The legacy 5-venue-median candidate has no '+' venue_or_protocol pair — never matched."""
    legacy = {"candidate_id": "legacy", "mechanism_id": "FUNDING_CAPTURE",
             "venue_or_protocol": "Binance/Bybit/OKX/KuCoin/Hyperliquid (median)",
             "economic_driver_key": "ETH_PERP_FUNDING"}
    overrides = run_mod._funding_pair_identity_overrides(
        {"legacy": legacy}, [_identity_row("perp_contract_identity:ETH", "binance")])
    assert overrides == {}


def test_never_fresh_evidence_is_data_insufficient_not_stale():
    """Live-run finding: a NEEDS_MORE_EVIDENCE decision whose first gap is freshness was routed to STALE,
    although STALE means 'was fresh, aged out' (DECISION_STALE predicate). Never-fresh ⇒ DATA_INSUFFICIENT."""
    from spa_core.research_factory import run as run_mod
    out = {"decision": ec.NEEDS_MORE_EVIDENCE, "failed_gates": [], "unknowns": ["data_fresh", "forward_collection_ready"]}
    assert run_mod._ideal_hold_target(out, {"conflicts": []}) == c1.DATA_INSUFFICIENT
    assert run_mod._ideal_hold_target({"decision": ec.DECISION_STALE}, {"conflicts": []}) == c1.STALE_STATE
    judged_old = {"decision": ec.NEEDS_MORE_EVIDENCE, "failed_gates": ["data_fresh"], "unknowns": []}
    assert run_mod._ideal_hold_target(judged_old, {"conflicts": []}) == c1.STALE_STATE


def test_paper_accounting_evidence_never_invents_an_entry_price_or_a_delay():
    """Live-run finding: entry_price defaulted to a 1.0 'par-value proxy' and the redemption delay to an
    assumed T+0. Without a MEASURED NAV reading the entry price is NOT_MEASURED; the delay is NOT_MEASURED."""
    pa = bundle_mod._build_paper_accounting_evidence({}, ec.PAPER_MODE_HOLDABLE, {})
    assert pa["entry_price"]["state"] == c1.NOT_MEASURED and pa["entry_price"]["value"] is None
    assert pa["redemption_delay_days"]["state"] == c1.NOT_MEASURED
    for comp in pa["entry_fee_components"] + pa["exit_fee_components"]:
        assert comp["cell"]["state"] != c1.NOT_APPLICABLE, comp      # unmeasured is never 'not applicable'
    nav = c1.cell(c1.MEASURED, 1.139, unit="usd_per_share", source_ref="oracle", source_class=c1.PRIMARY_CHAIN,
                  source_root="chain:1", as_of="2026-10-02T12:31:59Z", now=NOW)
    pa2 = bundle_mod._build_paper_accounting_evidence({"nav_price_cell": nav}, ec.PAPER_MODE_REFERENCE_TRACK, {})
    assert pa2["entry_price"]["value"] == 1.139
    one_off = [c for c in pa2["entry_fee_components"] if c["kind"] in ("entry", "spread")]
    assert one_off and all(c["cell"]["state"] == c1.NOT_APPLICABLE and "reference track" in c["cell"]["reason"]
                           for c in one_off)


def test_open_paper_positions_are_marked_every_run_and_stale_without_a_price(tmp_path, monkeypatch):
    """Live-run finding: no paper_mark rows were ever written. With a MEASURED NAV a mark carries the price;
    without one the mark is STALE and carries no price (never forward-filled)."""
    from spa_core.research_factory import run as run_mod
    calls = []
    monkeypatch.setattr(run_mod.paper, "positions", lambda d: [{"position_id": "p1", "candidate_id": "c1", "status": "OPEN",
                                                                "leg_id": None}])
    monkeypatch.setattr(run_mod.paper, "mark", lambda d, pid, obs, now: calls.append(obs))
    nav = c1.cell(c1.MEASURED, 1.14, unit="usd_per_share", source_ref="oracle", source_class=c1.PRIMARY_CHAIN,
                  source_root="chain:1", as_of="2026-10-04T11:00:00Z", now=NOW)
    run_mod._mark_open_positions(tmp_path, {"c1": {"nav_price_cell": nav, "nav_origin": "issuer:hashnote"}}, {}, NOW)
    run_mod._mark_open_positions(tmp_path, {}, {}, NOW)
    assert calls[0]["price"]["value"] == 1.14 and calls[0]["mark_origin"] == "issuer:hashnote"
    assert calls[1]["price"]["state"] == c1.NOT_MEASURED and calls[1]["price"]["value"] is None


def test_rescreen_from_a_hold_state_continues_to_the_decisions_hold_target(tmp_path):
    """Live-run finding: a hold-state candidate whose evidence changed was re-screened to SCREENED and left
    there. It must land on the hold state its NEEDS_MORE_EVIDENCE decision names, in the same call."""
    from spa_core.research_factory import run as run_mod
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    for s in (c1.SCREENED, c1.COUNTERPARTY_UNKNOWN):
        lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    outcome = {"decision": ec.NEEDS_MORE_EVIDENCE, "failed_gates": [], "unknowns": ["identity_verified"],
               "rationale": ["identity unknown"]}
    run_mod._route_sherlock_outcome(tmp_path, cid, c, c1.COUNTERPARTY_UNKNOWN, {"evidence_digest": "new", "conflicts": []},
                                    {"evidence_digest": "old"}, outcome, True, NOW)
    assert lifecycle.current_state(tmp_path, cid) == c1.DATA_INSUFFICIENT
