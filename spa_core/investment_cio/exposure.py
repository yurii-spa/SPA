"""Investment CIO — WP-S01 cross-sleeve exposure facts (ADR-554 WP-A05).

Look-through overlap facts over the sleeves :mod:`spa_core.investment_cio.sleeves` built:
which protocols are held by more than one sleeve, which factor (a peg, a credit name, a
smart-contract/oracle pair) shows up in which sleeves, per-sleeve leverage, and — read-only,
never enforced here — the RiskPolicy concentration caps. When ``weights`` is given, also the
weighted look-through share per protocol (``Σ wᵢ·shareᵢ``), honest about the cells it could
not sum because a share is itself not measured.

Pure function of its inputs; writes nothing; imports nothing execution/paper/risk/governance/
investment_os related.

# LLM_FORBIDDEN — a read-only aggregation over already-measured cells.
"""
from __future__ import annotations

from typing import Optional

from spa_core.adapters.tier_map import tier_of
from spa_core.investment_cio import contract

#: RiskPolicy v1.0 concentration caps (spa_core/risk/policy.py) — read-only reference,
#: never imported and never enforced from here (invariant: the CIO package imports
#: nothing from spa_core.risk; this constant is a documented literal, not a live read).
RISK_POLICY_CAPS_REFERENCE = {
    "T1": 0.40,
    "T2": 0.20,
    "source": "spa_core/risk/policy.py (read-only reference; not imported, no enforcement here)",
}


def build(sleeves: dict, weights: Optional[dict] = None) -> dict:
    """Cross-sleeve exposure facts. ``weights`` (sleeve_id -> weight) is optional; without it
    every weighted figure is reported NOT_MEASURED rather than assuming an equal split.

    ADR-554 finding 8: a sleeve absent from ``weights`` is NOT an unmeasured input — it is a
    sleeve the caller chose not to allocate to, so its contribution is 0, not NOT_MEASURED (a
    missing weight must never poison the whole protocol's cap read). What genuinely cannot be
    checked — a multi-protocol bucket with no per-protocol split, an UNKNOWN/T3 tier, or a share
    cell that is itself not measured — is named in ``unchecked_protocols`` instead, and rolled up
    into the top-level ``protocol_cap_state`` (MEASURED only when that list is empty, else
    PARTIAL).

    ADR-554 finding N5: concentration CAPS are about capital actually deployed to a protocol.
    ``cash`` is a buffer, not a protocol position, so it never contributes a protocol/cap entry
    at all. And when ``weights`` IS given, a sleeve allocated 0 (or absent, per finding 8 => 0)
    holds no capital under that recommendation, so it cannot contribute a cap-relevant protocol
    either — otherwise a permanently-zero-weight observe-only sleeve (trading_research,
    market_neutral_basis) could keep ``protocol_cap_state`` stuck at PARTIAL forever. Without
    ``weights`` there is no allocation to filter by, so every (non-cash) sleeve is still listed,
    descriptively, exactly as before."""
    protocol_sleeves: dict[str, set] = {}
    protocol_tier: dict[str, str] = {}
    protocol_shares: dict[str, dict] = {}
    unchecked_protocols: list[dict] = []

    for sid, sleeve in sleeves.items():
        if sid == "cash":
            continue  # not a protocol position; never a cap-contributing holder
        if weights is not None:
            w = weights.get(sid)
            if not (isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0):
                continue  # not actually allocated to under this recommendation => no cap exposure
        for item in (sleeve or {}).get("composition") or []:
            proto = item.get("protocol")
            if proto is None:
                continue
            protocol_sleeves.setdefault(proto, set()).add(sid)
            tier = item.get("tier") or tier_of(proto) or "UNKNOWN"
            protocol_tier[proto] = tier
            share_cell = item.get("share")
            share_val = contract.value_of(share_cell)
            protocol_shares.setdefault(proto, {})[sid] = share_val
            if tier in ("UNKNOWN", "T3"):
                unchecked_protocols.append({"protocol": proto, "sleeve_id": sid, "reason": f"tier={tier}"})
            if share_val is None:
                reason = (share_cell.get("reason") if isinstance(share_cell, dict) else None) or \
                          "share not measured"
                unchecked_protocols.append({"protocol": proto, "sleeve_id": sid, "reason": reason})

    shared_protocols = {p: sorted(s) for p, s in protocol_sleeves.items() if len(s) > 1}

    factor_to_sleeves: dict[str, list] = {}
    for sid, sleeve in sleeves.items():
        for f in (sleeve or {}).get("factors") or []:
            factor_to_sleeves.setdefault(f, []).append(sid)
    for f in factor_to_sleeves:
        factor_to_sleeves[f] = sorted(factor_to_sleeves[f])

    leverage_per_sleeve = {sid: contract.value_of((sleeve or {}).get("leverage"))
                           for sid, sleeve in sleeves.items()}
    gross_exposure_per_sleeve = {sid: contract.value_of((sleeve or {}).get("gross_exposure_over_nav"))
                                for sid, sleeve in sleeves.items()}

    protocol_overlap = []
    for proto, sids in sorted(protocol_sleeves.items()):
        shares = protocol_shares.get(proto, {})
        if weights is None:
            weighted = contract.absent(contract.NOT_MEASURED,
                                        reason="no weights supplied; overlap is look-through only")
        else:
            total = 0.0
            any_unmeasured_share = False
            used = []
            for sid in sorted(sids):
                w = weights.get(sid)
                if w is None:
                    w = 0.0  # absent weight = sleeve not allocated to; it contributes 0, not UNKNOWN
                s = shares.get(sid)
                if s is None:
                    any_unmeasured_share = True  # a genuine data gap: named in unchecked_protocols
                    continue
                total += w * s
                used.append(sid)
            if any_unmeasured_share:
                weighted = contract.absent(contract.NOT_MEASURED,
                                            reason="at least one holder's share is not measured; "
                                                   "see unchecked_protocols")
            else:
                weighted = contract.measured(round(total, 6), unit="weighted_share_of_portfolio",
                                              source="investment_cio.exposure (Σ wᵢ·shareᵢ)", as_of=None,
                                              note=f"weights x shares for {used}")
        protocol_overlap.append({
            "protocol": proto,
            "tier": protocol_tier.get(proto, "UNKNOWN"),
            "held_by": sorted(sids),
            "weighted_share": weighted,
        })

    protocol_cap_state = "MEASURED" if not unchecked_protocols else "PARTIAL"

    return {
        "shared_protocols": shared_protocols,
        "factor_to_sleeves": factor_to_sleeves,
        "leverage_per_sleeve": leverage_per_sleeve,
        "gross_exposure_per_sleeve": gross_exposure_per_sleeve,
        "protocol_overlap": protocol_overlap,
        "unchecked_protocols": unchecked_protocols,
        "protocol_cap_state": protocol_cap_state,
        "risk_policy_caps_reference": dict(RISK_POLICY_CAPS_REFERENCE),
        "weights_used": dict(weights) if weights else None,
    }
