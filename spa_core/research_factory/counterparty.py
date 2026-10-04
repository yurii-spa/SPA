"""spa_core/research_factory/counterparty.py — WP-A05, review #9. NO blended rating.

A summary is counts + named concerns only (``contract.CP_SUMMARY_FIELDS``). A role or dimension
with no observation is UNKNOWN; UNKNOWN never counts as safe.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from typing import Optional

from spa_core.research_factory import contract


def summarize(candidate: dict) -> dict:
    mech = contract.MECHANISMS.get(candidate.get("mechanism_id")) or {}
    required = set(mech.get("required_roles", ()))
    cp = candidate.get("counterparty") or {}
    roles = cp.get("roles") or {}
    dims = cp.get("dimensions") or {}

    roles_named, roles_unknown = [], []
    for role in contract.COUNTERPARTY_ROLES:
        state = (roles.get(role) or {}).get("state", contract.CP_UNKNOWN)
        if state in (contract.CP_OBSERVED, contract.CP_DOCUMENTED):
            roles_named.append(role)
        elif state == contract.CP_NOT_APPLICABLE:
            continue
        else:
            roles_unknown.append(role)
    required_missing = sorted(required - set(roles_named))

    dims_observed, dims_documented, dims_unknown, concerns = [], [], [], []
    for dim in contract.COUNTERPARTY_DIMENSIONS:
        state = (dims.get(dim) or {}).get("state", contract.CP_UNKNOWN)
        if state == contract.CP_OBSERVED:
            dims_observed.append(dim)
        elif state == contract.CP_DOCUMENTED:
            dims_documented.append(dim)
        elif state == contract.CP_NOT_APPLICABLE:
            continue
        else:
            dims_unknown.append(dim)
        if dim == "historical_incidents" and state in (contract.CP_OBSERVED, contract.CP_DOCUMENTED):
            concerns.append("historical_incidents on record")

    summary = {
        "roles_named": sorted(roles_named), "roles_unknown": sorted(roles_unknown),
        "required_roles_missing": required_missing, "dimensions_observed": sorted(dims_observed),
        "dimensions_documented": sorted(dims_documented), "dimensions_unknown": sorted(dims_unknown),
        "concerns": concerns,
    }
    assert set(summary) == set(contract.CP_SUMMARY_FIELDS)
    return summary


def credit_bar_passes(candidate: dict) -> tuple[bool, str]:
    """Review #9's CIO credit bar: for ``CREDIT_LIKE_MECHANISMS``,
    ``reserve_transparency``/``redemption_restrictions`` must each be >= DOCUMENTED from a
    non-ISSUER_CLAIM source, with at least one of the two OBSERVED. Non-credit mechanisms pass
    trivially (the bar does not apply)."""
    mech_id = candidate.get("mechanism_id")
    if mech_id not in contract.CREDIT_LIKE_MECHANISMS:
        return True, "credit bar not applicable to this mechanism"
    cp = candidate.get("counterparty") or {}
    dims = cp.get("dimensions") or {}
    any_observed = False
    for dim in contract.CIO_CREDIT_DIMENSIONS:
        d = dims.get(dim) or {}
        state = d.get("state", contract.CP_UNKNOWN)
        if state not in (contract.CP_OBSERVED, contract.CP_DOCUMENTED):
            return False, f"{dim} is {state!r}, needs >= DOCUMENTED"
        if d.get("source_class") == contract.ISSUER_CLAIM:
            return False, f"{dim} sourced only from ISSUER_CLAIM"
        if state == contract.CP_OBSERVED:
            any_observed = True
    if not any_observed:
        return False, "neither reserve_transparency nor redemption_restrictions is OBSERVED"
    return True, "credit bar satisfied"
