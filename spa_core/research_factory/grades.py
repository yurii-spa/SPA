"""spa_core/research_factory/grades.py — deterministic per-dimension grades (ADR-564 review #6/#7/#12).

Reads TWO kinds of input, never a third:

1. the v1 CANDIDATE dict (``contract.CANDIDATE_FIELDS``) — RETURN/COST/LIQUIDITY reuse its
   existing cells (``base_return``/``funding``, ``fees``/``gas``/``hedging_cost``, ``liquidity``)
   exactly as v1 produced them; a funding-primary mechanism (``FUNDING_PRIMARY_MECHANISMS``) reads
   ``funding`` as its RETURN primary leg (the same split ``admission._provenance_primary_field``
   already makes for v1).
2. a ``v2_evidence`` dict — this package's own addition, carrying exactly what v1 never had. Its
   shape is documented at each ``grade_*`` function below; ``bundle.py`` is the only other reader.

Plus the v2 ``profile`` (``profile.build_profile`` output) for COUNTERPARTY/REDEMPTION/CUSTODY.

No average exists anywhere (contract-level invariant, repeated here): each dimension stands alone.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec

#: mechanisms whose PRIMARY return driver is the funding leg, not base_return (mirrors
#: admission.py's v1 split for the same two mechanisms).
FUNDING_PRIMARY_MECHANISMS = ("FUNDING_CAPTURE", "SPOT_PERP_BASIS")


def primary_return_field(mechanism_id: str) -> str:
    return "funding" if mechanism_id in FUNDING_PRIMARY_MECHANISMS else "base_return"


# ── frozen-value / calendar freshness (review #6) — the ONE place this rule is executable ───────
def business_days_between(start: datetime, end: datetime) -> int:
    """Whole calendar days strictly between ``start`` and ``end`` that are NOT Saturday/Sunday — a
    simple Mon-Fri business-day count (no holiday calendar; that refinement is not part of this
    ADR). ``end <= start`` ⇒ 0."""
    if end <= start:
        return 0
    span_days = (end.date() - start.date()).days
    return sum(1 for i in range(1, span_days + 1) if (start.date() + timedelta(days=i)).weekday() < 5)


def freshness_verdict(family: str, last_change_at: Optional[datetime], now: datetime) -> str:
    """``evidence_contract.ADEQUATE`` (fresh) or ``evidence_contract.STALE``; ``UNKNOWN`` when
    ``last_change_at`` is ``None`` (never guessed as fresh). ``family`` keys
    ``evidence_contract.FRESHNESS``; an unknown family falls back to ``"rate"``."""
    if last_change_at is None:
        return ec.UNKNOWN
    rule = ec.FRESHNESS.get(family) or ec.FRESHNESS["rate"]
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    start = last_change_at if last_change_at.tzinfo else last_change_at.replace(tzinfo=timezone.utc)
    age_h = (now_aware - start).total_seconds() / 3600.0
    if age_h < 0:
        return ec.UNKNOWN  # a last-change time in the future cannot be judged fresh or stale
    if "max_unchanged_business_days" in rule and business_days_between(start, now_aware) \
            > rule["max_unchanged_business_days"]:
        return ec.STALE
    return ec.STALE if age_h > rule["max_age_h"] else ec.ADEQUATE


def _group_of(origin: Optional[str], registry: dict) -> Optional[str]:
    if not origin:
        return None
    groups = ec.origin_groups([{"origin": origin}], registry)
    return groups[0] if groups else None


# ── PRIMARY_IDENTITY ── v2_evidence["identity"] = {"on_chain_verified", "address_cited",
#    "venue_spec_cited", "mismatch"} ──────────────────────────────────────────────────────────
def grade_primary_identity(v2_evidence: dict, mechanism_id: Optional[str] = None) -> str:
    """GRADING_RULES: "STRONG = on-chain name/symbol/decimals at a block AND a matching cited
    official address; ADEQUATE = on-chain verified; WEAK = cited only; perp: venue contract spec
    from the venue API". A CEX perp has no on-chain contract at all, so STRONG is never
    reachable for it (that grade is reserved for on-chain verification) — but a CONFIRMED venue
    contract spec (``identity["venue_spec_cited"]`` — e.g. a funding PAIR's BOTH legs collected
    via ``collectors.contract_identity``, coordinator live-validation finding #3) IS that
    mechanism's own equivalent of "verified", and clears ADEQUATE for it specifically."""
    identity = v2_evidence.get("identity") or {}
    if identity.get("mismatch"):
        return ec.CONFLICTED
    if identity.get("on_chain_verified") and identity.get("address_cited"):
        return ec.STRONG
    if identity.get("on_chain_verified"):
        return ec.ADEQUATE
    if mechanism_id in FUNDING_PRIMARY_MECHANISMS and identity.get("venue_spec_cited"):
        return ec.ADEQUATE
    if identity.get("address_cited") or identity.get("venue_spec_cited"):
        return ec.WEAK
    return ec.UNKNOWN


# ── RETURN ── v2_evidence["return_family"], ["return_last_change_at"], ["return_primary_origin"],
#    ["return_cross_checks": [{"origin","value"}]] ───────────────────────────────────────────────
def grade_return(candidate: dict, mechanism_id: str, v2_evidence: dict, now: datetime,
                 registry: Optional[dict] = None) -> str:
    """``v2_evidence["return_primary_cell_override"]`` (a ``contract.cell``), when present,
    grades RETURN instead of the v1 candidate's own ``base_return``/``funding`` cell — e.g. a
    NAV-reader instrument's ON-CHAIN ORACLE reading (ADR-564 decision #5), never the v1 cell a
    DeFiLlama aggregator join produced. This override is for GRADING only: it never touches
    ``contract.net_expected_return()``, which nets COSTS against the v1 cell's own declared
    ANNUAL RATE — an oracle's raw NAV/price reading is not a rate and must never be substituted
    there (found by the integration acceptance run: swapping the v1 cell itself made
    net_expected_return honestly NOT_MEASURED once it became unit-aware, a real regression)."""
    registry = registry or {}
    field = primary_return_field(mechanism_id)
    override = v2_evidence.get("return_primary_cell_override")
    primary = override if isinstance(override, dict) else (candidate.get(field) or {})
    state = primary.get("state")
    if state == c1.CONFLICTED:
        return ec.CONFLICTED
    if state == c1.STALE:
        return ec.STALE

    family = v2_evidence.get("return_family") or "rate"
    last_change = c1.parse_ts(v2_evidence.get("return_last_change_at"))
    if freshness_verdict(family, last_change, now) == ec.STALE:
        return ec.STALE

    if state not in c1.VALUED_STATES or c1.measured_value_of(primary) is None:
        return ec.WEAK if state in c1.VALUED_STATES else ec.UNKNOWN
    if primary.get("source_class") not in c1.PRIMARY_CLASSES:
        return ec.WEAK  # aggregator-only — never ADEQUATE for RETURN

    primary_origin = v2_evidence.get("return_primary_origin")
    primary_group = _group_of(primary_origin, registry)
    cross = v2_evidence.get("return_cross_checks") or []
    # post-implementation review H5 (2026-10-04): a cross-check origin that is ITSELF ungrouped
    # (missing, an aggregator/model relay, or simply unregistered — ec.origin_group's own fail-
    # closed None) must NEVER count as independent just because `None != primary_group` reads as
    # "different". None is "cannot be judged a source at all", not a group of its own; comparing
    # it against a REAL primary_group used to upgrade RETURN to STRONG on nothing but an
    # unregistered name or a DeFiLlama relay.
    if primary_group is None:
        # re-review H5 residual: an ungrouped primary (unregistered, or a `chain:` read of a posted
        # value) is independent of NOTHING — any registered cross-check, the poster's own API
        # included, would otherwise read as "different" and upgrade RETURN to STRONG
        return ec.ADEQUATE
    independent = [cc for cc in cross
                  if (g := _group_of(cc.get("origin"), registry)) is not None and g != primary_group]
    if not independent:
        return ec.ADEQUATE

    primary_value = primary.get("value")
    for cc in independent:
        other = cc.get("value")
        if not isinstance(primary_value, (int, float)) or not isinstance(other, (int, float)):
            continue
        if family == "funding_settlement":
            if abs(primary_value - other) * 1e4 > ec.FUNDING_SAME_VENUE_BAND_BPS_8H:
                return ec.CONFLICTED
        else:
            denom = max(abs(primary_value), abs(other), 1e-12)
            if abs(primary_value - other) / denom > c1.CONFLICT_TOLERANCE_REL:
                return ec.CONFLICTED
    return ec.STRONG


# ── COST ── v2_evidence["cost_components"] = {kind: cell} (evidence_contract.FEE_COMPONENT_KINDS;
#    each a contract.cell(...) dict — the SAME cells bundle.py turns into E2's fee_component rows,
#    so a grade and the actual accounted amount never disagree about what "measured" meant) ──────
def grade_cost(v2_evidence: dict, paper_accounting_evidence: Optional[dict] = None) -> str:
    """H2 (post-implementation review, 2026-10-04): ``v2_evidence["cost_components"]`` alone is
    NOT every cost a candidate carries — a funding PAIR's v1 ``fees``/``gas`` cells are
    NOT_APPLICABLE by construction (the per-leg taker fees are ONE-OFF, never an annual rate,
    see ``scanners/basis.py``), so the old cost_components-only read let a pair with NO measured
    fee on EITHER leg (a spot leg has no official fee source cited for ANY venue; a perp leg on
    binance/bybit/okx has none either) grade ADEQUATE purely because the one component that
    happened to BE measured was the hedging-cost slippage cell — fees were never looked at.

    ``paper_accounting_evidence`` (``bundle._build_paper_accounting_evidence``'s own output — the
    SAME frozen shape this candidate's paper account will actually use, never a second,
    independently-derived source of truth) is now ALSO read: every ``entry_fee_components`` and
    ``exit_fee_components`` cell, on EVERY leg (the two-leg ``{"legs": {leg_id: <shape>}}`` form
    used by a funding pair, or the single-leg form used by everything else). A component whose
    cell is not MEASURED/DOCUMENTED (and not NOT_APPLICABLE) blocks ADEQUATE exactly like an old
    cost_components entry did; CONFLICTED still wins outright. A two-leg candidate whose leg names
    NO applicable component at all (an empty/missing list on that leg, after dropping
    NOT_APPLICABLE) is WEAK on its own — an unlisted fee is not a zero fee, and silence on one
    leg must never be read as "nothing to report" (single-leg candidates are not held to this:
    every real scanner always populates at least a default component list for them)."""
    components = v2_evidence.get("cost_components") or {}
    states = [cell.get("state") for cell in components.values()
             if isinstance(cell, dict) and cell.get("state") != c1.NOT_APPLICABLE]

    pae = paper_accounting_evidence or {}
    legs = pae.get("legs") if isinstance(pae.get("legs"), dict) else None
    leg_blocks = list(legs.values()) if legs else ([pae] if pae else [])
    fee_states = []
    any_empty_leg = False
    for leg in leg_blocks:
        if not isinstance(leg, dict):
            continue
        leg_fee_states = []
        for key in ("entry_fee_components", "exit_fee_components"):
            for comp in (leg.get(key) or []):
                if not isinstance(comp, dict):
                    continue
                cell = comp.get("cell")
                state = cell.get("state") if isinstance(cell, dict) else None
                if state == c1.NOT_APPLICABLE:
                    continue
                leg_fee_states.append(state)
        if legs is not None and not leg_fee_states:
            any_empty_leg = True
        fee_states.extend(leg_fee_states)

    if not components and not fee_states and not any_empty_leg:
        return ec.UNKNOWN
    all_states = states + fee_states
    if any(s == c1.CONFLICTED for s in all_states):
        return ec.CONFLICTED
    if any_empty_leg:
        return ec.WEAK  # an unlisted fee on a leg is not a zero fee
    if not all_states:
        return ec.ADEQUATE  # every applicable component (both sources) is NOT_APPLICABLE
    if all(s in (c1.MEASURED, c1.DOCUMENTED) for s in all_states):
        return ec.ADEQUATE
    return ec.WEAK  # any undisclosed (NOT_MEASURED/other) component blocks


# ── LIQUIDITY ── v2_evidence["liquidity_eligible_path_measured"]: bool ───────────────────────────
def grade_liquidity(candidate: dict, v2_evidence: dict, paper_mode: str) -> str:
    if paper_mode == ec.PAPER_MODE_REFERENCE_TRACK:
        return ec.NOT_APPLICABLE  # review #5: a tracked-only instrument has no exit of its own
    liquidity = candidate.get("liquidity") or {}
    if liquidity.get("state") == c1.NOT_APPLICABLE:
        return ec.NOT_APPLICABLE
    value = c1.value_of(liquidity)
    if value is None:
        return ec.UNKNOWN
    return ec.ADEQUATE if v2_evidence.get("liquidity_eligible_path_measured") else ec.WEAK


# ── COUNTERPARTY ── reads the v2 profile over the mechanism's required roles ─────────────────────
def grade_counterparty(profile: dict, required: tuple) -> str:
    if not required:
        return ec.NOT_APPLICABLE
    strengths = [ec.CP_STRENGTH.get((profile.get(r) or {}).get("state"), 0) for r in required]
    if any(s == 0 for s in strengths):
        return ec.UNKNOWN
    if all(s >= ec.CP_STRENGTH[ec.CP_DOCUMENTED] for s in strengths):
        return ec.STRONG
    return ec.ADEQUATE


# ── REDEMPTION ── v2_evidence["redemption"] = {"terms_cited", "caveats_complete"} ────────────────
def grade_redemption(mechanism_id: str, profile: dict, v2_evidence: dict) -> str:
    if mechanism_id in ec.DIMENSION_NA.get("REDEMPTION", ()):
        return ec.NOT_APPLICABLE
    agent_state = (profile.get("redemption_agent") or {}).get("state", ec.CP_UNKNOWN)
    if agent_state == ec.CP_UNKNOWN:
        return ec.UNKNOWN
    redemption = v2_evidence.get("redemption") or {}
    if not redemption.get("terms_cited"):
        return ec.UNKNOWN
    return ec.ADEQUATE if redemption.get("caveats_complete") else ec.WEAK


# ── CUSTODY ── reads the v2 profile's "custodian" role ───────────────────────────────────────────
def grade_custody(profile: dict) -> str:
    entry = profile.get("custodian") or {}
    state = entry.get("state", ec.CP_UNKNOWN)
    if state == ec.CP_NOT_APPLICABLE:
        return ec.NOT_APPLICABLE
    strength = ec.CP_STRENGTH.get(state, 0)
    if strength == 0:
        return ec.UNKNOWN
    return ec.STRONG if strength >= ec.CP_STRENGTH[ec.CP_DOCUMENTED] else ec.ADEQUATE


# ── CONTRACT ── v2_evidence["contract_reader_verified"]: bool ────────────────────────────────────
def grade_contract(mechanism_id: str, v2_evidence: dict) -> str:
    if mechanism_id in ec.DIMENSION_NA.get("CONTRACT", ()):
        return ec.NOT_APPLICABLE
    return ec.ADEQUATE if v2_evidence.get("contract_reader_verified") else ec.UNKNOWN


# ── FORWARD_SERIES ── v2_evidence["forward_series"] = {"collector_exists","last_change_at","family"}
def grade_forward_series(v2_evidence: dict, now: datetime) -> str:
    forward_series = v2_evidence.get("forward_series") or {}
    if not forward_series.get("collector_exists"):
        return ec.UNKNOWN
    last_change = c1.parse_ts(forward_series.get("last_change_at"))
    family = forward_series.get("family") or "rate"
    return freshness_verdict(family, last_change, now)


# ── RESERVES ── v2_evidence["reserves"] = {"attested","auditor_group","issuer_group"} ────────────
def grade_reserves(mechanism_id: str, v2_evidence: dict) -> str:
    if mechanism_id in ec.DIMENSION_NA.get("RESERVES", ()):
        return ec.NOT_APPLICABLE
    reserves = v2_evidence.get("reserves") or {}
    if not reserves.get("attested"):
        return ec.UNKNOWN
    auditor_group, issuer_group = reserves.get("auditor_group"), reserves.get("issuer_group")
    if auditor_group and issuer_group and auditor_group != issuer_group:
        return ec.STRONG
    return ec.ADEQUATE


# ── LEGAL ── v2_evidence["legal"] = {"entity","jurisdiction","exemption","documented"} ───────────
def grade_legal(v2_evidence: dict) -> str:
    legal = v2_evidence.get("legal") or {}
    if legal.get("entity") and legal.get("jurisdiction") and legal.get("exemption") and legal.get("documented"):
        return ec.ADEQUATE
    return ec.UNKNOWN


# ── HOLDER_ELIGIBILITY ── v2_evidence["holder_eligibility"] = {"state"} ──────────────────────────
def grade_holder_eligibility(v2_evidence: dict) -> str:
    """GRADING_RULES: "ADEQUATE = SPA_ELIGIBLE documented; WEAK = requirements known, SPA
    NOT_ELIGIBLE; UNKNOWN = requirements unknown". A bare state assertion with no RECORDED
    requirement (KYC/investor_class/jurisdiction/minimum_usd — ``evidence_contract.
    ELIGIBILITY_REQUIREMENTS``) behind it is not "documented"/"known" — UNKNOWN, never assumed."""
    holder = v2_evidence.get("holder_eligibility") or {}
    state = holder.get("state")
    requirements = holder.get("requirements")
    has_recorded_requirement = isinstance(requirements, dict) and any(
        requirements.get(r) is not None for r in ec.ELIGIBILITY_REQUIREMENTS)
    if state == ec.SPA_ELIGIBLE and has_recorded_requirement:
        return ec.ADEQUATE
    if state == ec.NOT_ELIGIBLE and has_recorded_requirement:
        return ec.WEAK
    return ec.UNKNOWN


def grade_all(candidate: dict, mechanism_id: str, profile: dict, v2_evidence: dict, paper_mode: str,
             now: datetime, registry: Optional[dict] = None,
             paper_accounting_evidence: Optional[dict] = None) -> dict:
    """``paper_accounting_evidence`` — ``bundle._build_paper_accounting_evidence``'s own output for
    this SAME candidate, forwarded to :func:`grade_cost` only (see its docstring, H2); every other
    dimension is unaffected and keeps reading ``v2_evidence``/``candidate``/``profile`` exactly as
    before."""
    required = tuple(c1.MECHANISMS.get(mechanism_id, {}).get("required_roles", ()))
    out = {
        "PRIMARY_IDENTITY": grade_primary_identity(v2_evidence, mechanism_id),
        "RETURN": grade_return(candidate, mechanism_id, v2_evidence, now, registry=registry),
        "COST": grade_cost(v2_evidence, paper_accounting_evidence),
        "LIQUIDITY": grade_liquidity(candidate, v2_evidence, paper_mode),
        "COUNTERPARTY": grade_counterparty(profile, required),
        "REDEMPTION": grade_redemption(mechanism_id, profile, v2_evidence),
        "CUSTODY": grade_custody(profile),
        "CONTRACT": grade_contract(mechanism_id, v2_evidence),
        "FORWARD_SERIES": grade_forward_series(v2_evidence, now),
        "RESERVES": grade_reserves(mechanism_id, v2_evidence),
        "LEGAL": grade_legal(v2_evidence),
        "HOLDER_ELIGIBILITY": grade_holder_eligibility(v2_evidence),
    }
    assert set(out) == set(ec.DIMENSIONS)
    for dim, grade in out.items():
        assert grade in ec.GRADES, f"{dim} produced an unknown grade {grade!r}"
    return out
