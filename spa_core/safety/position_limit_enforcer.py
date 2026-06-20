"""
spa_core/safety/position_limit_enforcer.py

Enforces position limits for SPA portfolio allocations.
Prevents over-concentration in any single adapter or chain.

MP-1500 (v11.16) — stdlib only, no external dependencies, LLM FORBIDDEN.
approved=False from RiskPolicy cannot be overridden.

Limits (see LIMITS dict):
  - single_adapter_max: 40%  — no one adapter may exceed this weight
  - single_tier_max:    70%  — no single tier (T1/T2/T3) may exceed this
  - single_chain_max:   85%  — no single chain may exceed this
  - t3_max:             10%  — max weight in Tier-3 (experimental) adapters
  - unverified_max:      5%  — max weight in unverified adapters

Usage:
    from spa_core.safety.position_limit_enforcer import PositionLimitEnforcer

    enforcer = PositionLimitEnforcer()
    violations = enforcer.check({"aave_v3": 0.45, "compound_v3": 0.55})
    # → ["aave_v3 weight 45.0% > 40% limit"]

    enforcer.enforce(allocation)   # raises AllocationError on violation
"""
from __future__ import annotations

from spa_core.utils.errors import AllocationError

__all__ = ["PositionLimitEnforcer", "LIMITS"]

LIMITS: dict = {
    "single_adapter_max": 0.40,   # max 40% in single adapter
    "single_tier_max": 0.70,      # max 70% in single tier
    "single_chain_max": 0.85,     # max 85% in single chain
    "t3_max": 0.10,               # max 10% in Tier 3 (experimental)
    "unverified_max": 0.05,       # max 5% in unverified adapters
}

# Known adapter metadata for tier/chain checks.
# Format: adapter_id → {"tier": "T1"|"T2"|"T3", "chain": str, "verified": bool}
# Extend as new adapters are onboarded.
ADAPTER_META: dict = {
    "aave_v3": {"tier": "T1", "chain": "ethereum", "verified": True},
    "compound_v3": {"tier": "T1", "chain": "ethereum", "verified": True},
    "morpho_steakhouse": {"tier": "T1", "chain": "ethereum", "verified": True},
    "morpho_blue": {"tier": "T2", "chain": "ethereum", "verified": True},
    "yearn_v3": {"tier": "T2", "chain": "ethereum", "verified": True},
    "euler_v2": {"tier": "T2", "chain": "ethereum", "verified": True},
    "maple": {"tier": "T2", "chain": "ethereum", "verified": True},
    "aave_v3_arbitrum": {"tier": "T1", "chain": "arbitrum", "verified": True},
    "pendle_pt": {"tier": "T3", "chain": "ethereum", "verified": True},
    "pendle_yt": {"tier": "T3", "chain": "ethereum", "verified": True},
}


class PositionLimitEnforcer:
    """
    Validates proposed allocations against all SPA position limits.

    Allocation dict: {adapter_id: weight_fraction}
    Weights must sum to 1.0 (±0.001 tolerance).

    check() returns a list of violation strings (empty → all clear).
    enforce() raises AllocationError if any violation found.
    """

    def __init__(self, adapter_meta: dict | None = None) -> None:
        """
        Args:
            adapter_meta: Optional override for adapter metadata (tier/chain/verified).
                          Defaults to the module-level ADAPTER_META dict.
        """
        self._meta = adapter_meta if adapter_meta is not None else ADAPTER_META

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, allocation: dict) -> list:
        """
        Checks allocation dict against all position limits.

        Args:
            allocation: dict mapping adapter_id → fractional weight (0.0–1.0).
                        Weights should sum to 1.0.

        Returns:
            List of violation strings. Empty list means all limits satisfied.
        """
        violations: list = []

        if not allocation:
            return violations

        total = sum(allocation.values())

        # 1. Sum check
        if abs(total - 1.0) > 0.001:
            violations.append(
                f"Allocation sum {total:.4f} != 1.0 (tolerance 0.001)"
            )

        # 2. Single-adapter cap
        for adapter, weight in allocation.items():
            if weight > LIMITS["single_adapter_max"]:
                violations.append(
                    f"{adapter} weight {weight:.1%} > "
                    f"{LIMITS['single_adapter_max']:.0%} single-adapter limit"
                )

        # 3. Tier aggregation
        tier_weights: dict = {}
        t3_total = 0.0
        for adapter, weight in allocation.items():
            meta = self._meta.get(adapter, {})
            tier = meta.get("tier", "unknown")
            tier_weights[tier] = tier_weights.get(tier, 0.0) + weight
            if tier == "T3":
                t3_total += weight

        for tier, tw in tier_weights.items():
            if tw > LIMITS["single_tier_max"]:
                violations.append(
                    f"Tier {tier} total weight {tw:.1%} > "
                    f"{LIMITS['single_tier_max']:.0%} tier limit"
                )

        if t3_total > LIMITS["t3_max"]:
            violations.append(
                f"T3 total {t3_total:.1%} > {LIMITS['t3_max']:.0%} T3 limit"
            )

        # 4. Chain aggregation
        chain_weights: dict = {}
        for adapter, weight in allocation.items():
            meta = self._meta.get(adapter, {})
            chain = meta.get("chain", "unknown")
            chain_weights[chain] = chain_weights.get(chain, 0.0) + weight

        for chain, cw in chain_weights.items():
            if cw > LIMITS["single_chain_max"]:
                violations.append(
                    f"Chain '{chain}' total weight {cw:.1%} > "
                    f"{LIMITS['single_chain_max']:.0%} chain limit"
                )

        # 5. Unverified adapter cap
        unverified_total = sum(
            w
            for adapter, w in allocation.items()
            if not self._meta.get(adapter, {}).get("verified", False)
        )
        if unverified_total > LIMITS["unverified_max"]:
            violations.append(
                f"Unverified adapter total {unverified_total:.1%} > "
                f"{LIMITS['unverified_max']:.0%} unverified limit"
            )

        return violations

    def enforce(self, allocation: dict) -> dict:
        """
        Like check() but raises AllocationError on any violation.

        Args:
            allocation: dict mapping adapter_id → fractional weight.

        Returns:
            The same allocation dict (unchanged) if all limits satisfied.

        Raises:
            AllocationError: If any position limit is violated.
                             code="POSITION_LIMIT_BREACH"
        """
        violations = self.check(allocation)
        if violations:
            raise AllocationError(
                f"Position limits violated: {'; '.join(violations)}",
                code="POSITION_LIMIT_BREACH",
            )
        return allocation

    def limits_summary(self) -> dict:
        """Returns a copy of the active LIMITS dict."""
        return dict(LIMITS)
