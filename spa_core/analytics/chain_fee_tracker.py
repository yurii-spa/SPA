"""
MP-662 ChainFeeTracker
======================
Track and compare transaction fees across different chains
(Ethereum, Arbitrum, Base, Optimism, Polygon).

Advisory / read-only analytics module.  Pure stdlib, no external deps.
Atomic writes (tmp + os.replace).  Ring-buffer cap: MAX_ENTRIES entries.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/chain_fee_log.json")
MAX_ENTRIES = 100

# Fee multipliers relative to Ethereum L1
CHAIN_FEE_MULTIPLIERS: Dict[str, float] = {
    "ethereum": 1.00,
    "arbitrum": 0.05,   # ~5% of ETH gas
    "base":     0.04,   # ~4% of ETH gas
    "optimism": 0.06,   # ~6% of ETH gas
    "polygon":  0.01,   # ~1% of ETH gas
}


@dataclass
class ChainFeeSnapshot:
    chain: str
    base_gas_price_gwei: float    # current gas price on this chain
    l1_gas_overhead_gwei: float   # L2 chains have L1 data cost (0 for L1)
    eth_price_usd: float
    # Cost for a standard DeFi interaction (200k gas units)
    standard_tx_cost_usd: float
    # Relative to Ethereum mainnet (1.0 = same, 0.05 = 5% of ETH cost)
    cost_ratio_vs_eth: float
    fee_tier: str                 # ULTRA_LOW(<$0.10) / LOW(<$1) / MEDIUM(<$5) / HIGH(≥$5)
    recommended: bool             # True if cost_ratio < 0.10 (L2 preferred)


@dataclass
class ChainFeeComparison:
    snapshots: List[ChainFeeSnapshot]
    cheapest_chain: str
    most_expensive_chain: str
    l2_savings_vs_eth_usd: float  # savings per tx vs Ethereum
    recommendation: str


class ChainFeeTracker:
    """Capture, compare and persist per-chain transaction fee snapshots."""

    STANDARD_GAS_UNITS = 200_000

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tx_cost_usd(
        self,
        gas_price_gwei: float,
        l1_overhead_gwei: float,
        eth_price_usd: float,
    ) -> float:
        """Standard-tx cost in USD for STANDARD_GAS_UNITS."""
        total_gwei = gas_price_gwei + l1_overhead_gwei
        cost_eth = self.STANDARD_GAS_UNITS * total_gwei * 1e-9
        return round(cost_eth * eth_price_usd, 4)

    def _fee_tier(self, cost_usd: float) -> str:
        """Classify fee tier by USD cost per standard tx."""
        if cost_usd < 0.10:
            return "ULTRA_LOW"
        if cost_usd < 1.00:
            return "LOW"
        if cost_usd < 5.00:
            return "MEDIUM"
        return "HIGH"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot_chain(
        self,
        chain: str,
        gas_price_gwei: float,
        l1_overhead_gwei: float,
        eth_price_usd: float,
    ) -> ChainFeeSnapshot:
        """
        Capture a fee snapshot for one chain.

        Parameters
        ----------
        chain              : chain identifier, e.g. "ethereum", "arbitrum"
        gas_price_gwei     : current base gas price on the chain (Gwei)
        l1_overhead_gwei   : L1 data overhead for L2s; 0 for L1 chains
        eth_price_usd      : ETH price in USD
        """
        cost = self._tx_cost_usd(gas_price_gwei, l1_overhead_gwei, eth_price_usd)
        # Use predefined multiplier; unknown chains default to 1.0 (like ETH)
        multiplier = CHAIN_FEE_MULTIPLIERS.get(chain.lower(), 1.0)
        ratio = round(multiplier, 4)

        return ChainFeeSnapshot(
            chain=chain,
            base_gas_price_gwei=round(gas_price_gwei, 2),
            l1_gas_overhead_gwei=round(l1_overhead_gwei, 4),
            eth_price_usd=round(eth_price_usd, 2),
            standard_tx_cost_usd=cost,
            cost_ratio_vs_eth=ratio,
            fee_tier=self._fee_tier(cost),
            recommended=ratio < 0.10,
        )

    def compare_chains(
        self, snapshots: List[ChainFeeSnapshot]
    ) -> ChainFeeComparison:
        """
        Compare multiple chain snapshots and recommend the cheapest option.
        """
        if not snapshots:
            return ChainFeeComparison(
                snapshots=[],
                cheapest_chain="",
                most_expensive_chain="",
                l2_savings_vs_eth_usd=0.0,
                recommendation="No chain data available",
            )

        cheapest = min(snapshots, key=lambda s: s.standard_tx_cost_usd)
        priciest = max(snapshots, key=lambda s: s.standard_tx_cost_usd)

        # Savings vs Ethereum; 0 when Ethereum is not in the snapshot list
        eth_snap: Optional[ChainFeeSnapshot] = next(
            (s for s in snapshots if s.chain.lower() == "ethereum"), None
        )
        savings = (
            round(eth_snap.standard_tx_cost_usd - cheapest.standard_tx_cost_usd, 4)
            if eth_snap
            else 0.0
        )

        rec = f"Use {cheapest.chain} — saves ${savings:.2f}/tx vs Ethereum"

        return ChainFeeComparison(
            snapshots=snapshots,
            cheapest_chain=cheapest.chain,
            most_expensive_chain=priciest.chain,
            l2_savings_vs_eth_usd=savings,
            recommendation=rec,
        )

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic write)
    # ------------------------------------------------------------------

    def save_snapshots(self, snapshots: List[ChainFeeSnapshot]) -> None:
        """Append snapshots to the ring-buffer log (MAX_ENTRIES cap)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        for s in snapshots:
            existing.append(
                {
                    "timestamp": time.time(),
                    "chain": s.chain,
                    "standard_tx_cost_usd": s.standard_tx_cost_usd,
                    "fee_tier": s.fee_tier,
                    "recommended": s.recommended,
                }
            )

        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return persisted log, or [] if file is missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
