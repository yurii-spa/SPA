"""
spa_core/analytics/chain_allocator.py

Optimizes capital allocation between Ethereum and Base chains.
Considers APY differential, gas costs, bridge costs, and risk constraints.

MP-1489 (v11.05): Chain allocation optimizer — Ethereum/Base
Sprint: v11.05
Stdlib only — no external dependencies.
Read-only / advisory — never modifies allocator, risk, or execution domain.
LLM FORBIDDEN in this module.

CLI:
    python3 -m spa_core.analytics.chain_allocator --check   # print advisory (default)
    python3 -m spa_core.analytics.chain_allocator --run     # + write to data/

Output: data/chain_allocation_advisory.json
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from spa_core.base import BaseAnalytics
from spa_core.utils.errors import AllocationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_PATH = "data/chain_allocation_advisory.json"

# Approximate one-way bridge cost Ethereum → Base (USD).
BRIDGE_COST_USD: float = 5.0

# Minimum capital per chain to make deployment worthwhile (USD).
MIN_ALLOCATION_USD: float = 1_000.0

# APY edge required for Base to justify bridge overhead (percentage points).
BASE_ADVANTAGE_THRESHOLD: float = 0.005   # 0.5 pp

# Default annual rebalance count for gas amortization.
DEFAULT_REBALANCES_PER_YEAR: int = 52

# Supported chains (order matters for output consistency)
SUPPORTED_CHAINS = ["ethereum", "base"]

# Default allocations used when APY signals are roughly equal.
_BALANCED_SPLIT: Dict[str, float] = {"ethereum": 0.6, "base": 0.4}
# Allocations when Ethereum dominates.
_ETH_DOMINANT_SPLIT: Dict[str, float] = {"ethereum": 0.9, "base": 0.1}
# Allocations when Base dominates.
_BASE_DOMINANT_SPLIT: Dict[str, float] = {"ethereum": 0.2, "base": 0.8}


# ---------------------------------------------------------------------------
# Pure allocation logic (no I/O, fully testable)
# ---------------------------------------------------------------------------

def compute_allocation(
    total_capital: float,
    eth_best_apy: float,
    base_best_apy: float,
    eth_gas_usd: float = 50.0,
    base_gas_usd: float = 1.0,
    rebalances_per_year: int = DEFAULT_REBALANCES_PER_YEAR,
    bridge_cost_usd: float = BRIDGE_COST_USD,
    min_allocation_usd: float = MIN_ALLOCATION_USD,
    base_advantage_threshold: float = BASE_ADVANTAGE_THRESHOLD,
) -> Dict[str, float]:
    """Compute optimal chain split as fractions summing to 1.0.

    The algorithm:
    1. If ``total_capital`` is too small to split meaningfully, go all-in on
       whichever chain has higher gross APY.
    2. Compute net APY after amortizing annual gas and bridge costs:
       ``net_apy = gross_apy − (gas_usd × rebalances_per_year) / capital``
       Base also deducts a one-time bridge cost amortized over 1 year.
    3. If Base net APY exceeds Ethereum net APY by ≥ *base_advantage_threshold*,
       recommend a Base-heavy split; if Ethereum dominates, recommend an
       Ethereum-heavy split; otherwise use the balanced default.

    Args:
        total_capital:           Total capital in USD.
        eth_best_apy:            Best gross APY on Ethereum (percentage points, e.g. 6.5).
        base_best_apy:           Best gross APY on Base (percentage points).
        eth_gas_usd:             Gas cost per rebalance on Ethereum (USD).
        base_gas_usd:            Gas cost per rebalance on Base (USD).
        rebalances_per_year:     Number of rebalances per year.
        bridge_cost_usd:         One-way bridge cost Eth → Base (USD).
        min_allocation_usd:      Minimum per-chain allocation to justify splitting.
        base_advantage_threshold: Min net-APY edge for Base to justify bridge.

    Returns:
        Dict ``{chain: fraction}`` where fractions sum to 1.0.

    Raises:
        AllocationError: If ``total_capital`` is negative or NaN.
    """
    if total_capital < 0 or total_capital != total_capital:  # NaN check
        raise AllocationError(
            f"total_capital must be non-negative, got {total_capital}"
        )

    # Edge case: too small to split
    if total_capital < min_allocation_usd * 2:
        if eth_best_apy >= base_best_apy:
            return {"ethereum": 1.0, "base": 0.0}
        return {"ethereum": 0.0, "base": 1.0}

    # Net APY after annual gas cost amortization
    annual_eth_gas = eth_gas_usd * rebalances_per_year
    annual_base_gas = base_gas_usd * rebalances_per_year

    # Avoid division-by-zero for zero capital (already handled above, but be safe)
    cap = max(total_capital, 1.0)
    eth_net = eth_best_apy - (annual_eth_gas / cap) * 100.0
    # Base: also deduct bridge cost amortized over 1 year
    base_net = base_best_apy - (annual_base_gas / cap) * 100.0 - (bridge_cost_usd / cap) * 100.0

    if base_net > eth_net + base_advantage_threshold:
        return dict(_BASE_DOMINANT_SPLIT)
    elif eth_net > base_net + base_advantage_threshold:
        return dict(_ETH_DOMINANT_SPLIT)
    else:
        return dict(_BALANCED_SPLIT)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ChainAllocator(BaseAnalytics):
    """Determines optimal capital split between Ethereum and Base.

    Advisory-only: returns recommended fractions; never touches actual capital.

    Usage::

        allocator = ChainAllocator(base_dir="/path/to/spa")
        result = allocator.optimize(
            total_capital=100_000,
            eth_best_apy=6.5,
            base_best_apy=7.2,
        )
        allocator.save(result)
    """

    OUTPUT_PATH = OUTPUT_PATH
    SUPPORTED_CHAINS = SUPPORTED_CHAINS

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir)
        self._data: Dict[str, Any] = {
            "allocation": {},
            "advisory":   "",
            "inputs":     {},
            "last_updated": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        total_capital: float,
        eth_best_apy: float,
        base_best_apy: float,
        eth_gas_usd: float = 50.0,
        base_gas_usd: float = 1.0,
        rebalances_per_year: int = DEFAULT_REBALANCES_PER_YEAR,
        bridge_cost_usd: float = BRIDGE_COST_USD,
    ) -> Dict[str, Any]:
        """Compute and record the optimal chain allocation.

        Delegates maths to :func:`compute_allocation` and wraps the result
        with context (inputs, advisory text, timestamp).

        Args:
            total_capital:        Total capital in USD.
            eth_best_apy:         Best Ethereum APY (%).
            base_best_apy:        Best Base APY (%).
            eth_gas_usd:          Gas per rebalance on Ethereum (USD).
            base_gas_usd:         Gas per rebalance on Base (USD).
            rebalances_per_year:  Annual rebalances for gas amortization.
            bridge_cost_usd:      Bridge cost Eth → Base (USD).

        Returns:
            Dict with keys: ``allocation``, ``advisory``, ``inputs``,
            ``last_updated``.

        Raises:
            AllocationError: Propagated from :func:`compute_allocation`.
        """
        allocation = compute_allocation(
            total_capital=total_capital,
            eth_best_apy=eth_best_apy,
            base_best_apy=base_best_apy,
            eth_gas_usd=eth_gas_usd,
            base_gas_usd=base_gas_usd,
            rebalances_per_year=rebalances_per_year,
            bridge_cost_usd=bridge_cost_usd,
        )

        advisory = self._build_advisory(allocation, eth_best_apy, base_best_apy)

        self._data = {
            "allocation": allocation,
            "advisory":   advisory,
            "inputs": {
                "total_capital":        total_capital,
                "eth_best_apy":         eth_best_apy,
                "base_best_apy":        base_best_apy,
                "eth_gas_usd":          eth_gas_usd,
                "base_gas_usd":         base_gas_usd,
                "rebalances_per_year":  rebalances_per_year,
                "bridge_cost_usd":      bridge_cost_usd,
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        return self._data

    def to_dict(self) -> Dict[str, Any]:
        """Return last computed data snapshot."""
        return self._data

    def allocation_usd(self, total_capital: float) -> Dict[str, float]:
        """Convert last computed fractional allocation into USD amounts.

        Args:
            total_capital: Total portfolio capital in USD.

        Returns:
            Dict ``{chain: usd_amount}``.

        Raises:
            AllocationError: If ``optimize()`` has not been called yet.
        """
        alloc = self._data.get("allocation")
        if not alloc:
            raise AllocationError(
                "No allocation computed yet. Call optimize() first."
            )
        return {chain: round(frac * total_capital, 2) for chain, frac in alloc.items()}

    def is_bridge_justified(
        self,
        total_capital: float,
        eth_best_apy: float,
        base_best_apy: float,
        eth_gas_usd: float = 50.0,
        base_gas_usd: float = 1.0,
    ) -> bool:
        """Return True if deploying capital to Base is net-positive vs Ethereum.

        Quick predicate without storing state.

        Args:
            total_capital:  Total portfolio USD.
            eth_best_apy:   Ethereum best APY (%).
            base_best_apy:  Base best APY (%).
            eth_gas_usd:    Ethereum gas per rebalance (USD).
            base_gas_usd:   Base gas per rebalance (USD).

        Returns:
            True if Base net APY > Ethereum net APY.
        """
        alloc = compute_allocation(
            total_capital=total_capital,
            eth_best_apy=eth_best_apy,
            base_best_apy=base_best_apy,
            eth_gas_usd=eth_gas_usd,
            base_gas_usd=base_gas_usd,
        )
        return alloc.get("base", 0.0) > alloc.get("ethereum", 1.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_advisory(
        allocation: Dict[str, float],
        eth_apy: float,
        base_apy: float,
    ) -> str:
        eth_frac = allocation.get("ethereum", 0.0)
        base_frac = allocation.get("base", 0.0)

        if eth_frac == 1.0:
            return (
                f"All-in Ethereum ({eth_apy:.2f}% APY). Capital too small to split "
                "or Ethereum dominates after gas/bridge costs."
            )
        if base_frac == 1.0:
            return (
                f"All-in Base ({base_apy:.2f}% APY). Capital too small to split "
                "or Base dominates after gas/bridge costs."
            )
        if base_frac >= 0.7:
            return (
                f"Base-dominant split {int(base_frac*100)}% Base / {int(eth_frac*100)}% Ethereum. "
                f"Base APY ({base_apy:.2f}%) exceeds Ethereum ({eth_apy:.2f}%) "
                "net of gas+bridge costs."
            )
        if eth_frac >= 0.7:
            return (
                f"Ethereum-dominant split {int(eth_frac*100)}% Ethereum / {int(base_frac*100)}% Base. "
                f"Ethereum APY ({eth_apy:.2f}%) leads after cost adjustment."
            )
        return (
            f"Balanced split {int(eth_frac*100)}% Ethereum / {int(base_frac*100)}% Base. "
            f"APY difference (Eth {eth_apy:.2f}% vs Base {base_apy:.2f}%) is below threshold."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run(write: bool = False, base_dir: str = ".") -> int:
    """Main CLI logic. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Example inputs matching typical SPA scenario
    DEMO_CAPITAL = 100_000.0
    DEMO_ETH_APY = 6.5
    DEMO_BASE_APY = 7.2

    allocator = ChainAllocator(base_dir=base_dir)
    result = allocator.optimize(
        total_capital=DEMO_CAPITAL,
        eth_best_apy=DEMO_ETH_APY,
        base_best_apy=DEMO_BASE_APY,
    )

    print("\n=== Chain Allocation Optimizer (advisory) ===")
    print(f"  Total capital:  ${DEMO_CAPITAL:,.0f}")
    print(f"  Ethereum APY:   {DEMO_ETH_APY}%")
    print(f"  Base APY:       {DEMO_BASE_APY}%")
    print()
    print("  Recommended allocation:")
    for chain, frac in result["allocation"].items():
        usd = frac * DEMO_CAPITAL
        print(f"    {chain.upper():10s}  {frac*100:.0f}%   ${usd:,.0f}")
    print()
    print(f"  Advisory: {result['advisory']}")
    print(f"  Last updated: {result['last_updated']}")

    usd_amounts = allocator.allocation_usd(DEMO_CAPITAL)
    print(f"\n  USD breakdown: {usd_amounts}")

    if write:
        path = allocator.save(result)
        print(f"\n  Saved → {path}")
    else:
        print("\n  (dry run — use --run to write)")

    return 0


if __name__ == "__main__":
    _mode = "--run" in sys.argv
    sys.exit(_run(write=_mode))
