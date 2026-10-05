"""spa_core/research_factory/bundle.py — CandidateEvidenceBundle builder (ADR-564 review #4/#11).

Builds a ``BUNDLE_FIELDS`` dict from the v1 candidate, the v2 profile (``profile.build_profile``),
the per-candidate ``v2_evidence`` (documented in ``grades.py``), the curated facts, and the
per-dimension grades (``grades.grade_all``). Content-addressed ``evidence_digest`` — stored on the
ledger as kind ``evidence_bundle``, keyed ``(candidate_id, evidence_digest)``, so re-recording
UNCHANGED evidence is idempotent (the ledger's own keyed duplicate-write guard, the same discipline
``registry.py`` uses for candidate snapshots).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import grades as grades_mod
from spa_core.research_factory import profile as profile_mod
from spa_core.research_factory._common import iso as _iso
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import DuplicateKey

#: timestamps of WHEN evidence was pulled/recorded, never of WHAT it says — excluded from the
#: content digest so re-recording the SAME substantive evidence at a later run stays idempotent
#: (evidence_cutoff defaults to this run's `now` when no v2_evidence override names one, so
#: leaving it IN the digest made every single run "change" every bundle — found by the
#: integration acceptance run: evidence_bundle/admission_decision rows doubled on a same-data
#: rerun one hour later).
_VOLATILE_KEYS = ("as_of", "recorded_at", "generated_at", "retrieved_at", "fetched_at", "evidence_cutoff")

#: integration amendment (2026-10-04): E2's paper.py is the only consumer of
#: ``paper_accounting_evidence`` and froze its OWN internal shape
#: (``evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS`` / ``FEE_COMPONENT_FIELDS`` /
#: ``FEE_COMPONENT_KINDS``) — found by FM2-27 actually running bundle.py's output through
#: paper.open_position(). This module builds exactly THAT shape now; ``net_expected_return``
#: (this package's own admission/decision concern, never E2's) moved to ``return_evidence``.


def _fee_component(kind: str, cell: dict) -> dict:
    unit = cell.get("unit") if isinstance(cell, dict) and cell.get("unit") in ("usd", "bps", "fraction") else "usd"
    return {"kind": kind, "cell": cell, "unit": unit,
           "effective_from": cell.get("as_of") if isinstance(cell, dict) else None,
           "subject_to_change": None, "one_off": kind in ("entry", "exit")}


def _na_cell(reason: str) -> dict:
    return c1.cell(c1.NOT_APPLICABLE, reason=reason)


def _cost_component_cell(cost_components: dict, kind: str) -> dict:
    cell = cost_components.get(kind)
    if isinstance(cell, dict) and cell.get("state") in c1.VALUED_STATES + (c1.NOT_APPLICABLE,):
        return cell
    # live-run finding: an UNMEASURED fee was labelled NOT_APPLICABLE ("not measured") — missing-as-NA.
    # A fee with no evidence is NOT_MEASURED, which paper.open_position refuses (never a silent 0).
    return c1.cell(c1.NOT_MEASURED, reason=f"{kind} fee not measured for this candidate")


_ONE_OFF_KINDS = ("entry", "exit", "spread")


def _reference_track_component(comp: dict) -> dict:
    """A REFERENCE_TRACK tracks NAV and holds no position: one-off subscription/redemption costs are never
    incurred. They stay visible (the cited cell is kept under ``cited``) but are NOT netted."""
    if comp.get("kind") in _ONE_OFF_KINDS or comp.get("one_off") is True:
        out = dict(comp)
        out["cited"] = comp.get("cell")
        out["cell"] = _na_cell("reference track holds no position — one-off cost not incurred (shown, not netted)")
        return out
    return comp


def _build_paper_accounting_evidence(v2_evidence: dict, paper_mode: str, registry: dict) -> dict:
    """``evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS`` — E2's frozen shape for
    ``paper.open_position``/``mark``/``close``. ``v2_evidence["paper_accounting"]`` (optional) may
    override any field, including a two-leg ``{"legs": {leg_id: <this shape>}}`` for a funding
    pair; everything not overridden gets an honest default (NOT_APPLICABLE/ESTIMATED_WITH_METHOD
    placeholder, never a silent 0 presented as measured)."""
    pa = v2_evidence.get("paper_accounting") or {}
    if isinstance(pa.get("legs"), dict):
        return {"legs": pa["legs"]}

    # live-run finding: the entry price defaulted to a 1.0 "par-value proxy" and the redemption delay to an
    # assumed T+0 — invented values on the paper ledger. The entry price is the MEASURED NAV reading of THIS
    # run (on-chain oracle / official API), else NOT_MEASURED (paper.open_position then refuses).
    entry_price = pa.get("entry_price")
    if not (isinstance(entry_price, dict) and entry_price.get("state") in c1.VALUED_STATES):
        nav = v2_evidence.get("nav_price_cell")
        if isinstance(nav, dict) and nav.get("state") == c1.MEASURED and isinstance(nav.get("value"), (int, float)):
            entry_price = nav
        else:
            entry_price = c1.cell(c1.NOT_MEASURED, reason="no MEASURED NAV/price reading for this candidate this run")

    cost = v2_evidence.get("cost_components") or {}
    hinted_entry = pa.get("entry_fee_components")
    hinted_exit = pa.get("exit_fee_components")
    if isinstance(hinted_entry, list) and hinted_entry:
        entry_components = [dict(x) for x in hinted_entry if isinstance(x, dict)]
    else:
        entry_components = [_fee_component(k, _cost_component_cell(cost, k)) for k in ("entry", "management", "spread")]
    if isinstance(hinted_exit, list) and hinted_exit:
        exit_components = [dict(x) for x in hinted_exit if isinstance(x, dict)]
    else:
        exit_components = [_fee_component(k, _cost_component_cell(cost, k)) for k in ("exit", "performance")]
    if paper_mode != ec.PAPER_MODE_HOLDABLE:
        entry_components = [_reference_track_component(x) for x in entry_components]

    if paper_mode == ec.PAPER_MODE_HOLDABLE:
        delay_cell = pa.get("redemption_delay_days")
        if not (isinstance(delay_cell, dict) and delay_cell.get("state") in c1.VALUED_STATES + (c1.NOT_APPLICABLE,)):
            delay_cell = c1.cell(c1.NOT_MEASURED, reason="no redemption delay documented — never assumed T+0")
    else:
        delay_cell = _na_cell("REFERENCE_TRACK candidates have no exit-liquidity claim")

    return_origin_group = pa.get("return_origin_group")  # the hint's own group, when supplied, wins
    if return_origin_group is None:
        primary_origin = v2_evidence.get("return_primary_origin")
        if primary_origin:
            groups = ec.origin_groups([{"origin": primary_origin}], registry)
            return_origin_group = groups[0] if groups else None

    return {
        "entry_price": entry_price, "entry_fee_components": entry_components,
        "exit_fee_components": exit_components if paper_mode == ec.PAPER_MODE_HOLDABLE else [],
        "redemption_delay_days": delay_cell,
        "price_is_net_of_performance_fee": pa.get("price_is_net_of_performance_fee"),
        "performance_fee_rate": pa.get("performance_fee_rate"), "leverage": pa.get("leverage"),
        "maintenance_margin_rate": pa.get("maintenance_margin_rate"),
        "collateral_yield_rate": pa.get("collateral_yield_rate"),
        "fee_source": pa.get("fee_source"), "holding_period_days_declared": pa.get("holding_period_days_declared"),
        "return_origin_group": return_origin_group,
    }


def _strip_volatile(value):
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def _evidence_digest(bundle_without_digest: dict) -> str:
    return c1.digest(_strip_volatile(bundle_without_digest))


def build_bundle(candidate: dict, *, profile: dict, v2_evidence: dict, facts: list, paper_mode: str,
                 registry: dict, now: datetime, mechanism_id: Optional[str] = None,
                 exposure_family: Optional[str] = None) -> dict:
    mechanism_id = mechanism_id or candidate.get("mechanism_id")
    exposure_family = exposure_family or candidate.get("exposure_key")
    # H2 (post-implementation review, 2026-10-04): built ONCE, here, so grade_cost sees the exact
    # same per-leg fee-component shape paper.py will actually open a position against — never a
    # second, independently-derived view of the same evidence (the bug this fix closes: COST used
    # to see only v2_evidence["cost_components"], which a funding PAIR's v1 cells never carry a
    # per-leg taker fee into at all).
    paper_accounting_evidence = _build_paper_accounting_evidence(v2_evidence, paper_mode, registry)
    grades = grades_mod.grade_all(candidate, mechanism_id, profile, v2_evidence, paper_mode, now,
                                  registry=registry, paper_accounting_evidence=paper_accounting_evidence)

    primary_field = grades_mod.primary_return_field(mechanism_id)
    sections = {
        "identity_evidence": dict(v2_evidence.get("identity") or {}),
        "return_evidence": {
            "primary_field": primary_field,
            # the GRADED cell (grades.grade_return's own override, when present — e.g. an
            # on-chain oracle reading, ADR-564 decision #5) — never net_expected_return's own v1
            # cell, which stays on the candidate's declared ANNUAL rate (see grades.grade_return's
            # docstring for why the two must never be the same substitution).
            "primary_cell": (v2_evidence.get("return_primary_cell_override")
                            if isinstance(v2_evidence.get("return_primary_cell_override"), dict)
                            else candidate.get(primary_field)),
            "cross_checks": v2_evidence.get("return_cross_checks") or [],
            "family": v2_evidence.get("return_family"),
            "last_change_at": v2_evidence.get("return_last_change_at"),
            "primary_origin": v2_evidence.get("return_primary_origin"),
            # this package's own admission/decision concern (net of COST) — never E2's
            # paper_accounting_evidence, whose shape is frozen to paper.py's own fields.
            # paper_mode/holding_period_days make a ONE-OFF cost unit mode-aware (ADR-564 Round 5
            # Issue #2): REFERENCE_TRACK skips it (not netted — no position to apply it against);
            # HOLDABLE amortises it over the declared holding period, read straight off the SAME
            # hint _build_paper_accounting_evidence reads below (never a second source of truth).
            "net_expected_return": c1.net_expected_return(
                candidate, paper_mode=paper_mode,
                holding_period_days=(v2_evidence.get("paper_accounting") or {}).get(
                    "holding_period_days_declared")),
        },
        "cost_evidence": dict(v2_evidence.get("cost_components") or {}),
        "liquidity_evidence": {"cell": candidate.get("liquidity"),
                              "eligible_path_measured": v2_evidence.get("liquidity_eligible_path_measured")},
        "counterparty_evidence": profile,
        "redemption_evidence": dict(v2_evidence.get("redemption") or {}),
        "custody_evidence": {"profile_entry": profile.get("custodian")},
        "contract_evidence": {"reader_verified": v2_evidence.get("contract_reader_verified")},
        "market_evidence": dict(v2_evidence.get("market") or {}),
        "paper_accounting_evidence": paper_accounting_evidence,
        "forward_series_evidence": dict(v2_evidence.get("forward_series") or {}),
        "reserves_evidence": dict(v2_evidence.get("reserves") or {}),
        "legal_evidence": dict(v2_evidence.get("legal") or {}),
        "holder_eligibility_evidence": dict(v2_evidence.get("holder_eligibility") or {}),
    }
    assert set(sections) == set(ec.EVIDENCE_SECTIONS)

    # independent_root_count/origin_groups answer ONE question — "how many independent affiliation
    # groups corroborate the RETURN claim" (both consumers, admission_v2._source_independence_sufficient
    # and eligibility.py's min_origins_cio, read it against MIN_GROUPS_PAPER["return"]/MIN_GROUPS_CIO
    # ["return"], nothing else). Round 5 Issue #3 (live-validation finding, 2026-10-04): this used to
    # ALSO fold in every required-ROLE fact (issuer/custodian/redemption_agent/legal_entity, via
    # profile_mod.required_roles) regardless of whether that fact says anything about the return number
    # at all — for USYC that pulled in the custodian fact (origin custodian:marex, group "marex", a real
    # independent party for CUSTODY) and inflated independent_root_count to 2, when the return claim
    # itself (on-chain oracle + USYC's own API, both origin issuer:hashnote/group "circle"; DeFiLlama is
    # aggregator: and contributes nothing per ec.origin_groups) has exactly ONE corroborating group. CIO's
    # own gate (MIN_GROUPS_CIO["return"]=2) would then wrongly PASS on an issuer-only return claim — the
    # exact circularity ADR-564 review #2 exists to catch. Scoped to return evidence only now.
    primary_origin = v2_evidence.get("return_primary_origin")
    # tail of ADR-564: a `chain:` return reading is a witness only where the contract computes the return
    return_citation_origins = ([{"origin": primary_origin,
                                 "claim_type": ec.return_claim_type(primary_origin, mechanism_id)}]
                               if primary_origin else []) + \
        [{"origin": cc.get("origin"), "claim_type": ec.return_claim_type(cc.get("origin"), mechanism_id)}
         for cc in v2_evidence.get("return_cross_checks") or [] if cc.get("origin")]
    origin_groups_list = sorted(set(ec.origin_groups(return_citation_origins, registry)))

    source_roots = sorted({r.get("source_root") for r in (candidate.get("source_refs") or [])
                          if r.get("source_root")})

    conflicts = sorted(d for d, g in grades.items() if g == ec.CONFLICTED)
    stale_evidence = sorted(d for d, g in grades.items() if g == ec.STALE)
    unknowns = sorted(d for d, g in grades.items() if g == ec.UNKNOWN)
    blocking_gaps = []
    for dim, grade in grades.items():
        floor = ec.PAPER_MIN_GRADE.get(dim)
        if floor is None or grade == ec.NOT_APPLICABLE:
            continue
        if ec.GRADE_ORDER.get(grade, 0) < ec.GRADE_ORDER.get(floor, 0):
            blocking_gaps.append(dim)
    blocking_gaps.sort()

    ceiling = profile_mod.evidence_ceiling(profile, mechanism_id)
    asserted_roles = profile_mod.issuer_asserted_roles(profile, mechanism_id)

    issuer_citations = (profile.get("issuer") or {}).get("citations") or []
    issuer_groups = set(ec.origin_groups(issuer_citations, registry))
    return_groups = set(origin_groups_list)
    circularity = []
    if issuer_groups and return_groups and (issuer_groups & return_groups):
        circularity.append("return evidence shares an origin group with the issuer — "
                           "the issuer's own posted oracle/API is the only channel for its own return claim")

    bundle = {
        "schema_version": ec.SCHEMA_BUNDLE, "candidate_id": candidate.get("candidate_id"),
        "exposure_key": candidate.get("exposure_key"), "exposure_family": exposure_family,
        "mechanism_id": mechanism_id, "generated_at": _iso(now),
        "evidence_cutoff": v2_evidence.get("evidence_cutoff") or _iso(now),
        **sections,
        "source_roots": source_roots, "origin_groups": origin_groups_list,
        "independent_root_count": len(origin_groups_list), "conflicts": conflicts,
        "stale_evidence": stale_evidence, "unknowns": unknowns, "blocking_gaps": blocking_gaps,
        "grades": grades, "paper_mode": paper_mode, "evidence_ceiling": ceiling,
        "issuer_asserted_roles": asserted_roles, "circularity_concerns": circularity,
        "evidence_digest": None,
    }
    assert set(bundle) == set(ec.BUNDLE_FIELDS)
    digest_input = {k: v for k, v in bundle.items() if k not in ("evidence_digest", "generated_at")}
    bundle["evidence_digest"] = _evidence_digest(digest_input)
    return bundle


def write_bundle(data_dir: Path, bundle: dict, now: datetime) -> dict:
    ledger = ledger_for(data_dir)
    at = _iso(now)
    key = ["evidence_bundle", bundle["candidate_id"], bundle["evidence_digest"]]
    try:
        return ledger.append("evidence_bundle", key, bundle, at)
    except DuplicateKey as dup:
        return dup.existing


def all_bundles(data_dir: Path, candidate_id: str) -> list:
    """Every recorded bundle payload for this candidate, oldest first."""
    ledger = ledger_for(data_dir)
    rows = [e for e in ledger.read_all() if e.get("kind") == "evidence_bundle"
           and (e.get("payload") or {}).get("candidate_id") == candidate_id]
    rows.sort(key=lambda e: e["seq"])
    return [r.get("payload") or {} for r in rows]


def latest_bundle(data_dir: Path, candidate_id: str) -> Optional[dict]:
    rows = all_bundles(data_dir, candidate_id)
    return rows[-1] if rows else None


def find_bundle(data_dir: Path, candidate_id: str, evidence_digest: str) -> Optional[dict]:
    for b in all_bundles(data_dir, candidate_id):
        if b.get("evidence_digest") == evidence_digest:
            return b
    return None
