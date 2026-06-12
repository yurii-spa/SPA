"""Chain concentration limit enforcer (MP-203).

Standalone, deterministic, stdlib-only. No LLM calls. No external imports.

Provides two public functions:

  get_default_chain_map() -> dict
      Returns the canonical protocol_id → chain mapping for all known adapters
      (mainnet + L2).

  check_chain_limits(allocation, chain_map) -> dict
      Validates that the given allocation does not breach per-chain or L2-total
      concentration limits. Warn-only integration in policy.py — violations
      are surfaced as warnings, they do NOT block trades.

Rules enforced:
  - single chain:  allocation on any one chain ≤ 70% of portfolio
  - L2 combined:   allocation on arbitrum + base combined ≤ 50% of portfolio

Both thresholds mirror the values in RiskConfig (max_single_chain_allocation
and max_l2_total_allocation) so the standalone module stays in sync.

Typical call pattern in policy.py (warn-only):
    from spa_core.risk.chain_limits import check_chain_limits, get_default_chain_map
    result = check_chain_limits(allocation_dict, get_default_chain_map())
    for v in result["violations"]:
        warnings.append(f"CHAIN_LIMIT_WARN (MP-203): {v}")
"""
from __future__ import annotations

from typing import Optional

# Chains considered L2 for the combined L2 cap.
_L2_CHAINS: frozenset = frozenset({"arbitrum", "base"})

# Must match RiskConfig values (paper-period constants; change via ADR only).
_MAX_SINGLE_CHAIN_FRAC: float = 0.70   # 70%
_MAX_L2_TOTAL_FRAC: float = 0.50       # 50%


def get_default_chain_map() -> dict:
    """Return the canonical protocol_id → chain (lowercase) mapping.

    Covers all adapters registered in ADAPTER_REGISTRY and L2_ADAPTER_REGISTRY.
    The chain value matches the canonical lowercase name used in Position.chain
    and in RiskPolicy chain checks.
    """
    return {
        # ── Ethereum mainnet adapters ─────────────────────────────────────────
        "aave_v3":      "ethereum",
        "compound_v3":  "ethereum",
        "morpho_blue":  "ethereum",
        "yearn_v3":     "ethereum",
        "euler_v2":     "ethereum",
        "maple":        "ethereum",
        # ── L2 adapters (MP-203) ──────────────────────────────────────────────
        "aave_v3_arbitrum":  "arbitrum",
        "aave_v3_base":      "base",
        "compound_v3_base":  "base",
        "morpho_blue_base":  "base",
    }


def check_chain_limits(
    allocation: dict,
    chain_map: Optional[dict] = None,
) -> dict:
    """Validate chain concentration limits against the given allocation.

    Args:
        allocation: {protocol_id: weight_fraction} where weight_fraction is
            a float in [0, 1] representing the fraction of total portfolio
            capital deployed in that protocol. The sum of values should be
            ≤ 1 (the remainder is cash).  Values < 0 are silently ignored.
        chain_map: {protocol_id: chain_name (lowercase)}.
            Protocols absent from chain_map are assigned to chain "unknown"
            and still counted toward that chain's total. Pass None to use
            get_default_chain_map().

    Returns:
        {
            "ok": bool — True when no limits are breached,
            "violations": list[str] — human-readable breach descriptions,
            "l2_total_pct": float — combined L2 fraction (0..1),
            "chain_breakdown": {chain: fraction} — per-chain totals,
        }

    The function never raises. All arithmetic is pure Python.
    """
    if chain_map is None:
        chain_map = get_default_chain_map()

    # ── Build per-chain breakdown ─────────────────────────────────────────────
    chain_breakdown: dict = {}
    for protocol_id, weight in (allocation or {}).items():
        if not isinstance(weight, (int, float)) or weight < 0:
            continue
        chain = str(chain_map.get(protocol_id, "unknown")).lower()
        chain_breakdown[chain] = chain_breakdown.get(chain, 0.0) + float(weight)

    # ── L2 combined ───────────────────────────────────────────────────────────
    l2_total = sum(v for k, v in chain_breakdown.items() if k in _L2_CHAINS)

    # ── Violations ───────────────────────────────────────────────────────────
    violations: list = []

    for chain, frac in sorted(chain_breakdown.items()):
        if frac > _MAX_SINGLE_CHAIN_FRAC:
            violations.append(
                f"Chain '{chain}' allocation {frac:.1%} exceeds "
                f"single-chain limit {_MAX_SINGLE_CHAIN_FRAC:.0%}"
            )

    if l2_total > _MAX_L2_TOTAL_FRAC:
        violations.append(
            f"L2 combined allocation {l2_total:.1%} exceeds "
            f"L2 total limit {_MAX_L2_TOTAL_FRAC:.0%}"
        )

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "l2_total_pct": round(l2_total, 6),
        "chain_breakdown": {k: round(v, 6) for k, v in chain_breakdown.items()},
    }


# end of file
