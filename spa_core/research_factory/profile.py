"""spa_core/research_factory/profile.py — CounterpartyProfile v2 builder (ADR-564 review #2/#3/#4).

Builds the per-role v2 profile (``evidence_contract.role_entry``) for a candidate's mechanism from
CURATED facts (``registry_loader.facts_for``) plus the scanner's OWN on-chain/API citations for a
role (``extra_citations`` — never a second door for doc/filing facts, which enter ONLY through the
curated fact registry per the frozen contract). Also carries the v1 -> v2 role migration
(``evidence_contract.migrate_v1_role`` names the TARGET state; this module re-validates it against
v2's bar, as the ADR's binding review #2 requires of the caller).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory._common import iso as _iso

#: a profile is {role: role_entry-dict} for every evidence_contract.ROLES member
PROFILE_FIELDS = tuple(ec.ROLES)

_SAFE_SUFFIX_RE = re.compile(r"[^a-z0-9_\-.]")


def required_roles(mechanism_id: str) -> tuple:
    mech = c1.MECHANISMS.get(mechanism_id) or {}
    return tuple(mech.get("required_roles", ()))


def _sanitize_origin_suffix(identity: str) -> str:
    cleaned = _SAFE_SUFFIX_RE.sub("", identity.strip().lower().replace(" ", "_"))
    return cleaned or "unknown"


def _fact_citation(fact: dict) -> dict:
    return ec.citation(origin=fact["origin"], channel=fact["channel"], ref=fact["ref"],
                        retrieved_at=fact["retrieved_at"], quote=fact.get("quote"),
                        claim_type=fact.get("claim_type"))


def build_role(role: str, mechanism_id: str, facts_for_role: list, *, issuer_group: Optional[str],
              registry: dict, extra_citations: Optional[list] = None) -> dict:
    """One role's v2 entry, built ONLY from curated facts for THIS role plus the scanner's own
    on-chain/API citations (``extra_citations``). An inferred link (``claim_type="inferred_link"``)
    is UNKNOWN with its reason — never DOCUMENTED, however confident the inference (review #3)."""
    if role not in required_roles(mechanism_id):
        return ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="not required by this mechanism")

    citations = [_fact_citation(f) for f in facts_for_role] + list(extra_citations or [])
    if not citations:
        return ec.role_entry(ec.CP_UNKNOWN, role=role, reason="no curated fact or on-chain/API hint on record")

    identity = None
    for f in facts_for_role:
        if f.get("value"):
            identity = str(f["value"])
            break

    inferred = any(f.get("claim_type") == "inferred_link" for f in facts_for_role)
    if inferred:
        return ec.role_entry(ec.CP_UNKNOWN, role=role, identity=identity, citations=citations,
                             reason="inferred link — not a direct binding")

    if identity is None:
        return ec.role_entry(ec.CP_UNKNOWN, role=role, reason="no identity named for this role")

    for state in (ec.CP_OBSERVED, ec.CP_DOCUMENTED):
        try:
            return ec.role_entry(state, role=role, identity=identity, citations=citations,
                                 issuer_group=issuer_group, registry=registry)
        except ValueError:
            continue
    return ec.role_entry(ec.CP_IDENTIFIED, role=role, identity=identity, citations=citations)


def build_profile(mechanism_id: str, facts: list, *, issuer_group: Optional[str], registry: dict,
                  scanner_hints: Optional[dict] = None) -> dict:
    """``facts`` — curated facts ALREADY filtered to this candidate (``registry_loader.facts_for``).
    ``scanner_hints`` — ``{role: [citation, ...]}`` of the scanner's own on-chain/API citations."""
    hints = scanner_hints or {}
    out = {}
    for role in ec.ROLES:
        role_facts = [f for f in facts if f.get("role") == role]
        out[role] = build_role(role, mechanism_id, role_facts, issuer_group=issuer_group,
                               registry=registry, extra_citations=hints.get(role))
    assert set(out) == set(ec.ROLES)
    return out


def evidence_ceiling(profile: dict, mechanism_id: str) -> str:
    """ISSUER_ASSERTED / THIRD_PARTY_DOCUMENTED / OBSERVED over the REQUIRED roles only (review
    #4) — a role the mechanism does not even call for cannot drag the ceiling down. No required
    role at all ⇒ OBSERVED (there is nothing issuer-asserted to worry about)."""
    req = required_roles(mechanism_id)
    worst = ec.CEILING_OBSERVED
    for role in req:
        state = (profile.get(role) or {}).get("state")
        if state in (ec.CP_UNKNOWN, ec.CP_IDENTIFIED):
            return ec.CEILING_ISSUER_ASSERTED
        if state == ec.CP_DOCUMENTED and worst != ec.CEILING_ISSUER_ASSERTED:
            worst = ec.CEILING_THIRD_PARTY_DOCUMENTED
    return worst


def issuer_asserted_roles(profile: dict, mechanism_id: str) -> list:
    req = required_roles(mechanism_id)
    return sorted(r for r in req if (profile.get(r) or {}).get("state") in (ec.CP_UNKNOWN, ec.CP_IDENTIFIED))


def migrate_role_from_v1(role: str, mechanism_id: str, v1_role_entry: dict, *, now: datetime,
                         issuer_group: Optional[str] = None, registry: Optional[dict] = None) -> dict:
    """ADR-560 v1 ``candidate['counterparty']['roles'][role]`` -> a v2 role entry (review #2).
    ``evidence_contract.migrate_v1_role`` names the TARGET state (IDENTIFIED/DOCUMENTED/OBSERVED-
    passthrough/UNKNOWN); this function ALWAYS floors a DOCUMENTED/OBSERVED target to IDENTIFIED
    (post-implementation review LOW, 2026-10-04 — v1 never recorded a real quote at all, so a
    PRIOR version of this function synthesised a citation whose ``quote`` was literally the
    ``identity`` string itself: ``role_entry``'s "quote names the identity" check
    [identity.lower() in quote.lower()] is then TRIVIALLY true no matter what the identity is —
    not independent review, a tautology that happened to usually fail closed only because the
    synthesised ``agent:<identity>`` origin usually wasn't registered; whenever it coincidentally
    WAS [e.g. an identity that sanitises to a real registered origin like "securitize"], this
    self-quoting citation alone would wrongly grant DOCUMENTED]. v1's data model has no
    independent document and no real quote to offer — IDENTIFIED (issuer-asserted, unverified)
    is the ONLY honest floor for a v1-migrated role, never DOCUMENTED, regardless of registry
    content."""
    if role not in required_roles(mechanism_id):
        return ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="not required by this mechanism")

    v1_entry = v1_role_entry or {}
    v1_state = v1_entry.get("state", c1.CP_UNKNOWN)
    if v1_state == c1.CP_NOT_APPLICABLE:
        return ec.role_entry(ec.CP_NOT_APPLICABLE, role=role, reason="v1 role was NOT_APPLICABLE")

    identity = v1_entry.get("name")
    source_class = v1_entry.get("source_class")
    source_ref = v1_entry.get("source_ref") or "v1-migration"
    has_non_issuer_citation = source_class not in (None, c1.ISSUER_CLAIM)
    target = ec.migrate_v1_role(v1_state, has_non_issuer_citation)

    if target in (ec.CP_UNKNOWN, ec.CP_NOT_APPLICABLE) or identity is None:
        return ec.role_entry(ec.CP_UNKNOWN, role=role,
                             reason=f"migrated from v1 state {v1_state!r} (no usable identity)")

    retrieved_at = _iso(now)
    origin = f"issuer:{_sanitize_origin_suffix(identity)}"
    synthetic = ec.citation(origin=origin, channel=ec.CHANNEL_OFFICIAL_API, ref=source_ref,
                            retrieved_at=retrieved_at)
    return ec.role_entry(ec.CP_IDENTIFIED, role=role, identity=identity, citations=[synthetic])


def migrate_profile_from_v1(v1_counterparty: dict, mechanism_id: str, *, now: datetime,
                            issuer_group: Optional[str] = None, registry: Optional[dict] = None) -> dict:
    v1_roles = (v1_counterparty or {}).get("roles") or {}
    out = {role: migrate_role_from_v1(role, mechanism_id, v1_roles.get(role) or {}, now=now,
                                      issuer_group=issuer_group, registry=registry)
          for role in ec.ROLES}
    assert set(out) == set(ec.ROLES)
    return out
