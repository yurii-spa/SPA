"""
spa_core/monitor/unified_gas_monitor.py

Unified gas monitor for all supported SPA chains.
Provides gas cost estimates for rebalancing operations across Ethereum and Base.

MP-1488 (v11.04): Unified gas monitor — Ethereum + Base
Sprint: v11.04
Stdlib only — no external dependencies.
Read-only / advisory — never modifies allocator, risk, or execution domain.
LLM FORBIDDEN in this module.

CLI:
    python3 -m spa_core.monitor.unified_gas_monitor --check   # print estimates (default)
    python3 -m spa_core.monitor.unified_gas_monitor --run     # + write to data/

Output: data/unified_gas_estimates.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gas-limit table per chain × operation type
# Each value is the gas units consumed by the operation.
# ---------------------------------------------------------------------------

GAS_LIMITS: Dict[str, Dict[str, int]] = {
    "ethereum": {
        "simple_swap":       150_000,
        "compound_deposit":  250_000,
        "aave_deposit":      300_000,
        "rebalance_full":    500_000,
        "morpho_deposit":    200_000,
        "erc20_approve":      50_000,
    },
    "base": {
        "simple_swap":       120_000,
        "aave_deposit":      220_000,
        "rebalance_full":    380_000,
        "morpho_deposit":    160_000,
        "moonwell_deposit":  180_000,
        "erc20_approve":      45_000,
    },
}

# Supported chains (lowercase)
SUPPORTED_CHAINS: List[str] = list(GAS_LIMITS.keys())

# Fallback gas prices (Gwei) when live fetch is unavailable.
_FALLBACK_GAS_PRICE_GWEI: Dict[str, float] = {
    "ethereum": 20.0,   # ~20 Gwei typical mainnet
    "base":     0.001,  # Base is extremely cheap (OP-stack)
}

# ETH price fallback (USD) used for USD conversion.
ETH_PRICE_USD: float = 3200.0

# Threshold below which a rebalance is considered "profitable" (USD).
PROFITABILITY_THRESHOLD_USD: float = 50.0

# Gwei → ETH conversion constant
_GWEI_PER_ETH: float = 1e9

# Annual rebalance frequency assumption (used for net-APY estimates).
REBALANCES_PER_YEAR: int = 52

# Output data file path (relative to base_dir)
OUTPUT_PATH = "data/unified_gas_estimates.json"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class UnifiedGasMonitor(BaseAnalytics):
    """Monitors and estimates gas costs across Ethereum and Base chains.

    Provides:
    - Per-operation gas cost estimates in ETH and USD
    - Profitability check for rebalance operations
    - Comparative summary across all supported chains
    - Annual gas cost estimate (for APY net-cost calculations)

    Usage::

        monitor = UnifiedGasMonitor(base_dir="/path/to/spa")
        result  = monitor.estimate_rebalance_cost("ethereum")
        summary = monitor.compare_all_chains()
        monitor.save(summary)
    """

    OUTPUT_PATH = OUTPUT_PATH
    SUPPORTED_CHAINS = SUPPORTED_CHAINS

    def __init__(
        self,
        base_dir: str = ".",
        eth_price_usd: float = ETH_PRICE_USD,
    ):
        super().__init__(base_dir)
        self.eth_price_usd = eth_price_usd
        self._data: Dict[str, Any] = {
            "chains": {},
            "comparison": [],
            "last_updated": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_rebalance_cost(self, chain: str = "ethereum") -> Dict[str, Any]:
        """Estimate gas cost for a full portfolio rebalance on *chain*.

        Args:
            chain: Lowercase chain name (``"ethereum"`` or ``"base"``).

        Returns:
            Dict with keys: ``chain``, ``gas_limit``, ``gas_price_gwei``,
            ``cost_eth``, ``cost_usd``, ``is_profitable``.

        Raises:
            ValueError: If *chain* is not in ``SUPPORTED_CHAINS``.
        """
        chain_lower = self._validate_chain(chain)
        gas_limit = GAS_LIMITS[chain_lower].get("rebalance_full", 500_000)
        gas_gwei = self._get_gas_price_gwei(chain_lower)
        cost_eth, cost_usd = self._calc_cost(gas_limit, gas_gwei)

        return {
            "chain":          chain_lower,
            "gas_limit":      gas_limit,
            "gas_price_gwei": gas_gwei,
            "cost_eth":       cost_eth,
            "cost_usd":       cost_usd,
            "is_profitable":  cost_usd < PROFITABILITY_THRESHOLD_USD,
        }

    def estimate_operation_cost(
        self,
        chain: str,
        operation: str,
        gas_price_gwei: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Estimate gas cost for a named operation on *chain*.

        Args:
            chain:           Lowercase chain name.
            operation:       Operation key, e.g. ``"aave_deposit"``.
            gas_price_gwei:  Override gas price; uses chain default if None.

        Returns:
            Dict with keys: ``chain``, ``operation``, ``gas_limit``,
            ``gas_price_gwei``, ``cost_eth``, ``cost_usd``.

        Raises:
            ValueError: If chain or operation is unknown.
        """
        chain_lower = self._validate_chain(chain)
        chain_ops = GAS_LIMITS[chain_lower]
        if operation not in chain_ops:
            raise ValueError(
                f"Unknown operation '{operation}' for chain '{chain_lower}'. "
                f"Valid: {sorted(chain_ops.keys())}"
            )
        gas_limit = chain_ops[operation]
        gwei = gas_price_gwei if gas_price_gwei is not None else self._get_gas_price_gwei(chain_lower)
        cost_eth, cost_usd = self._calc_cost(gas_limit, gwei)

        return {
            "chain":          chain_lower,
            "operation":      operation,
            "gas_limit":      gas_limit,
            "gas_price_gwei": gwei,
            "cost_eth":       cost_eth,
            "cost_usd":       cost_usd,
        }

    def annual_gas_cost_usd(
        self,
        chain: str,
        rebalances_per_year: int = REBALANCES_PER_YEAR,
    ) -> float:
        """Estimate total annual gas cost for rebalancing on *chain*.

        Args:
            chain:                Lowercase chain name.
            rebalances_per_year:  Number of rebalances per year.

        Returns:
            Annual gas cost in USD.
        """
        estimate = self.estimate_rebalance_cost(chain)
        return round(estimate["cost_usd"] * rebalances_per_year, 4)

    def compare_all_chains(self) -> Dict[str, Any]:
        """Generate a cost comparison across all supported chains.

        Returns:
            Dict with keys:
                ``chains`` — per-chain rebalance cost estimate,
                ``comparison`` — sorted list (cheapest first),
                ``cheapest_chain`` — chain with lowest USD cost,
                ``last_updated`` — UTC ISO timestamp.
        """
        chains_data: Dict[str, Any] = {}
        for chain in SUPPORTED_CHAINS:
            try:
                chains_data[chain] = self.estimate_rebalance_cost(chain)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gas estimate failed for '%s': %s", chain, exc)
                chains_data[chain] = {"error": str(exc)}

        comparison = sorted(
            [
                {
                    "chain":    chain,
                    "cost_usd": data.get("cost_usd", float("inf")),
                    "cost_eth": data.get("cost_eth", 0.0),
                }
                for chain, data in chains_data.items()
                if "error" not in data
            ],
            key=lambda x: x["cost_usd"],
        )

        cheapest = comparison[0]["chain"] if comparison else None

        self._data = {
            "chains":        chains_data,
            "comparison":    comparison,
            "cheapest_chain": cheapest,
            "last_updated":  datetime.now(timezone.utc).isoformat(),
        }
        return self._data

    def to_dict(self) -> Dict[str, Any]:
        """Return last computed data snapshot."""
        return self._data

    def supported_operations(self, chain: str) -> List[str]:
        """Return list of operation names supported on *chain*."""
        chain_lower = self._validate_chain(chain)
        return sorted(GAS_LIMITS[chain_lower].keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_chain(self, chain: str) -> str:
        """Validate chain name and return lowercase form.

        Raises:
            ValueError: If chain is not in SUPPORTED_CHAINS.
        """
        chain_lower = chain.lower()
        if chain_lower not in SUPPORTED_CHAINS:
            raise ValueError(
                f"Unsupported chain '{chain}'. Supported: {SUPPORTED_CHAINS}"
            )
        return chain_lower

    def _get_gas_price_gwei(self, chain: str) -> float:
        """Return gas price in Gwei for *chain* (fallback constant, no network call)."""
        return _FALLBACK_GAS_PRICE_GWEI.get(chain, 20.0)

    def _calc_cost(self, gas_limit: int, gas_gwei: float) -> Tuple[float, float]:
        """Convert gas_limit × gas_gwei into (cost_eth, cost_usd).

        Args:
            gas_limit: Gas units for the operation.
            gas_gwei:  Gas price in Gwei.

        Returns:
            Tuple of (cost_eth, cost_usd), both rounded to 8 decimal places.
        """
        cost_eth = gas_limit * gas_gwei / _GWEI_PER_ETH
        cost_usd = cost_eth * self.eth_price_usd
        return round(cost_eth, 8), round(cost_usd, 4)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run(write: bool = False, base_dir: str = ".") -> int:
    """Main CLI logic. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    monitor = UnifiedGasMonitor(base_dir=base_dir)
    data = monitor.compare_all_chains()

    print("\n=== Unified Gas Monitor — Ethereum + Base ===")
    for chain in SUPPORTED_CHAINS:
        info = data["chains"].get(chain, {})
        if "error" in info:
            print(f"\n  {chain.upper()}: ERROR — {info['error']}")
            continue
        print(f"\n  {chain.upper()}")
        print(f"    Gas limit (rebalance_full): {info['gas_limit']:,} units")
        print(f"    Gas price:                  {info['gas_price_gwei']} Gwei")
        print(f"    Cost (ETH):                 {info['cost_eth']:.8f} ETH")
        print(f"    Cost (USD):                 ${info['cost_usd']:.4f}")
        print(f"    Profitable (<${PROFITABILITY_THRESHOLD_USD}):        {info['is_profitable']}")

    print(f"\n  Cheapest chain: {data['cheapest_chain']}")
    print(f"  Last updated:   {data['last_updated']}")

    if write:
        path = monitor.save(data)
        print(f"\n  Saved → {path}")
    else:
        print("\n  (dry run — use --run to write)")

    return 0


if __name__ == "__main__":
    _mode = "--run" in sys.argv
    sys.exit(_run(write=_mode))
