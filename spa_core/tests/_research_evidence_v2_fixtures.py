"""spa_core/tests/_research_evidence_v2_fixtures.py — shared v2 admission helper (ADR-564).

ADR-560's test suites (``test_research_factory_core/rework/rework2.py``) each had a local
``_admit_to_paper_active`` helper that called ``admission.write_admission_snapshot`` directly to
get a candidate to PAPER_ACTIVE. ADR-564 binding #1 makes that call always raise
(``admission.V1AdmissionSuperseded``) — getting a test candidate to PAPER_ACTIVE now means a real
Sherlock ADMIT_TO_PAPER decision. This module builds the MAXIMAL (all-STRONG) evidence a candidate
CAN have, for tests whose subject is lifecycle/forward/eligibility/registry behaviour, not
evidence grading itself (that is ``test_research_evidence_core.py``'s job).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spa_core.research_factory import bundle as bundle_mod
from spa_core.research_factory import contract
from spa_core.research_factory import decision as decision_mod
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import lifecycle, registry


def _iso(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: post-implementation review H5/H6 (2026-10-04): ``evidence_contract.origin_group`` now fails
#: CLOSED on an unregistered origin (returns None, never a group of its own) — an empty
#: ``registry={}`` used to let "chain:1" count as its own independent group ("unregistered:chain:1"),
#: it no longer does. Every origin this fixture's "all-STRONG" evidence cites needs a REAL
#: registry entry or ``source_independence_sufficient`` (and anything else reading
#: ``independent_root_count``) honestly fails — which is correct, but defeats the point of an
#: "all-STRONG" fixture for tests whose subject is lifecycle/forward/eligibility, not grading.
DEFAULT_REGISTRY = {
    "chain:1": {"group": "onchain_test"},
    "issuer:test": {"group": "issuer_test"},
    "issuer:other": {"group": "issuer_other"},
    "auditor:test": {"group": "auditor_test"},
}


def all_strong_profile(mechanism_id: str) -> dict:
    required = contract.MECHANISMS[mechanism_id]["required_roles"]
    out = {}
    for role in ec.ROLES:
        if role not in required:
            out[role] = ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="not required by this mechanism")
            continue
        cit = ec.citation(origin="chain:1", channel=ec.CHANNEL_ON_CHAIN, ref="chain:1:0x00:bytecode",
                          retrieved_at="2026-01-01T00:00:00Z", claim_type="bytecode")
        out[role] = ec.role_entry(ec.CP_OBSERVED, role=role, identity="Test Co", citations=[cit])
    return out


def all_strong_v2_evidence(now: datetime) -> dict:
    # re-review H5 residual: a `chain:` origin is a witness only to CHAIN_NATIVE_CLAIMS — a rate read
    # off an oracle is its poster's claim — so the return's primary origin here is the issuer, the
    # same single group this fixture always intended (was "chain:1", which no longer counts).
    now_iso = _iso(now)
    return {
        "identity": {"on_chain_verified": True, "address_cited": True},
        "return_family": "rate", "return_last_change_at": now_iso, "return_primary_origin": "issuer:test",
        "return_cross_checks": [],
        "cost_components": {"entry": contract.MEASURED},
        "liquidity_eligible_path_measured": True,
        "redemption": {"terms_cited": True, "caveats_complete": True},
        "contract_reader_verified": True,
        "forward_series": {"collector_exists": True, "last_change_at": now_iso, "family": "rate"},
        "reserves": {"attested": True, "auditor_group": "auditor:test", "issuer_group": "issuer:other"},
        "legal": {"entity": True, "jurisdiction": True, "exemption": True, "documented": True},
        # a bare state assertion is not "documented" — grade_holder_eligibility needs a RECORDED
        # requirement (evidence_contract.ELIGIBILITY_REQUIREMENTS) behind it.
        "holder_eligibility": {"state": ec.SPA_ELIGIBLE, "requirements": {"kyc": False}},
        # a MEASURED NAV reading — the paper entry price/mark source. bundle.py no longer invents a 1.0
        # par-value default (live-run finding), so an all-STRONG fixture must carry a real reading.
        "nav_price_cell": contract.cell(contract.MEASURED, 1.0, unit="usd_per_share", source_ref="fixture-oracle",
                                        source_class=contract.PRIMARY_CHAIN, source_root="chain:1",
                                        as_of=now_iso, now=now),
        "nav_origin": "issuer:test",
        # fee components as CELLS (paper accounting refuses an unmeasured fee — never a silent 0); an
        # all-STRONG fixture measures them at 0
        "paper_accounting": {
            "entry_fee_components": [{"kind": "entry", "unit": "fraction_one_off", "one_off": True,
                                      "effective_from": now_iso, "subject_to_change": False,
                                      "cell": contract.cell(contract.MEASURED, 0.0, unit="fraction_one_off",
                                                            source_ref="fixture-fees", source_class=contract.OFFICIAL_API,
                                                            source_root="issuer:test", as_of=now_iso, now=now)}],
            "exit_fee_components": [{"kind": "exit", "unit": "fraction_one_off", "one_off": True,
                                     "effective_from": now_iso, "subject_to_change": False,
                                     "cell": contract.cell(contract.MEASURED, 0.0, unit="fraction_one_off",
                                                           source_ref="fixture-fees", source_class=contract.OFFICIAL_API,
                                                           source_root="issuer:test", as_of=now_iso, now=now)}],
            "redemption_delay_days": contract.cell(contract.MEASURED, 0.0, unit="days", source_ref="fixture-terms",
                                                   source_class=contract.OFFICIAL_API, source_root="issuer:test",
                                                   as_of=now_iso, now=now),
        },
    }


def v2_admission_id_for(data_dir: Path, candidate: dict, now: datetime,
                        *, paper_mode: str = ec.PAPER_MODE_HOLDABLE, registry: dict = None) -> str:
    """Builds an all-STRONG bundle for ``candidate``, runs a real Sherlock decision over it, and
    writes the ``paper-admission/2`` snapshot. Returns the v2 admission_id. Asserts the decision
    was ADMIT_TO_PAPER — a test relying on this helper is testing something OTHER than evidence
    grading, so a non-ADMIT outcome here is this helper failing its own job, not a legitimate
    test result. ``registry`` defaults to ``DEFAULT_REGISTRY`` (post-review H5/H6: an empty
    registry now fails closed on every origin this fixture cites — see that constant)."""
    mechanism_id = candidate["mechanism_id"]
    profile = all_strong_profile(mechanism_id)
    v2_evidence = all_strong_v2_evidence(now)
    b = bundle_mod.build_bundle(candidate, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=paper_mode, registry=DEFAULT_REGISTRY if registry is None else registry,
                               now=now)
    bundle_mod.write_bundle(data_dir, b, now)
    outcome = decision_mod.decide_and_record(data_dir, b, candidate, extra={}, now=now)
    assert outcome["decision"] == ec.ADMIT_TO_PAPER, outcome
    snap = decision_mod.write_admission_snapshot_v2(data_dir, outcome, b, now)
    return snap["payload"]["admission_id"]


def admit_to_paper_active_v2(data_dir: Path, candidate: dict, now: datetime = None) -> str:
    """Walks a valid candidate all the way to PAPER_ACTIVE via the REAL v2 gated path: registers
    it, drives it through SCREENED/RESEARCH_READY/PAPER_CANDIDATE, then admits it with an
    all-STRONG evidence bundle + a real Sherlock ADMIT_TO_PAPER decision + the v2 admission
    snapshot ``lifecycle.py`` now requires (ADR-564 binding #1). Drop-in replacement for the
    pre-ADR-564 ``_admit_to_paper_active(data_dir, candidate, now)`` helper — same signature,
    same return type (the admission_id string used as ``gate_ref``)."""
    cid = candidate["candidate_id"]
    registry.upsert(data_dir, candidate, now)
    for state in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(data_dir, cid, state, reason="setup", now=now)
    admission_id = v2_admission_id_for(data_dir, candidate, now)
    lifecycle.transition(data_dir, cid, contract.PAPER_ACTIVE, gate_ref=admission_id, reason="setup", now=now)
    return admission_id


# ── re-review H6 (2026-10-04): registry_loader fact-review test helpers ─────────────────────────
#: registry_loader.load_facts() now binds a reviewed_by stamp to the fact's exact CONTENT hash
#: (evidence_contract.fact_content_sha256) and to a committed registry/fact_reviews/*.json record
#: — a fixture fact with a bare reviewed_by string, and no record behind it, is no longer usable.
#: These two helpers exist so a test fixture can get back into that usable state without hand
#: -computing hashes: stamp the fact with its own real hash, then write a record that names it.

def stamped_fact(row: dict) -> dict:
    """Returns a COPY of ``row`` with ``fact_sha256`` set to its own real content hash
    (``evidence_contract.fact_content_sha256``) — the H6 binding requires this to equal what the
    loader recomputes, same as a real curated fact in ``registry/facts.jsonl``. Content hashing
    excludes ``fact_sha256``/``reviewed_by`` themselves, so this is safe to call before OR after
    deciding ``reviewed_by`` — stamping never depends on who reviewed it, only on what the fact
    actually says."""
    row = dict(row)
    row["fact_sha256"] = ec.fact_content_sha256(row)
    return row


def write_fact_review(reviews_base_dir: Path, reviewer: str, entries, *,
                      reviewed_at: str = "2026-10-04T00:00:00Z", verdict: str = "CONFIRMED") -> Path:
    """Writes ``<reviews_base_dir>/fact_reviews/<reviewer-slug>.json``, a ``fact-review/1`` record
    (``evidence_contract.SCHEMA_FACT_REVIEW``) that :func:`registry_loader.load_fact_reviews` (and
    through it ``load_facts``) will read — ``reviews_base_dir`` is the SAME directory the fixture
    passes as the facts file's parent (``registry_loader.default_fact_reviews_dir`` looks at
    ``facts_path.parent / "fact_reviews"``), typically a test's ``tmp_path``.

    ``entries``: an iterable of either ``(fact_id, fact_sha256)`` pairs (verdict defaults to
    ``CONFIRMED``) or dicts with explicit overrides (``fact_id``, ``fact_sha256``, and optionally
    ``verdict``/``method``/``evidence``/``issue``) — a test proving a REJECTED/UNVERIFIABLE
    verdict refuses the fact needs the dict form. Overwrites any existing record for this exact
    ``reviewer`` in this directory (callers that need several reviewers, or several fact_ids under
    one reviewer, pass them all in one call)."""
    facts = []
    for e in entries:
        if isinstance(e, dict):
            facts.append({"fact_id": e["fact_id"], "fact_sha256": e["fact_sha256"],
                         "verdict": e.get("verdict", verdict), "method": e.get("method", "test fixture"),
                         "evidence": e.get("evidence", "test fixture"), "issue": e.get("issue")})
        else:
            fact_id, fact_sha256 = e
            facts.append({"fact_id": fact_id, "fact_sha256": fact_sha256, "verdict": verdict,
                         "method": "test fixture", "evidence": "test fixture", "issue": None})
    doc = {"schema": ec.SCHEMA_FACT_REVIEW, "reviewer": reviewer, "reviewed_at": reviewed_at, "facts": facts}
    reviews_dir = reviews_base_dir / "fact_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", reviewer).strip("-").lower() or "reviewer"
    out = reviews_dir / f"{slug}.json"
    out.write_text(json.dumps(doc), encoding="utf-8")
    return out
