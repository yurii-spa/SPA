"""L2 protocol adapters — Arbitrum and Base chains (MP-203).

Extends existing mainnet adapters to track the same protocols on L2 networks.
All adapters here are T2 (per-protocol cap 20%) and read-only / advisory —
they never touch capital.

Adapters included:
  AaveV3ArbitrumAdapter  — Aave V3 USDC on Arbitrum
  AaveV3BaseAdapter      — Aave V3 USDC on Base
  CompoundV3BaseAdapter  — Compound V3 (Comet) USDC on Base
  MorphoBlueBaseAdapter  — Morpho Blue USDC on Base

All use DeFiLlamaFeed.get_apy(project, symbol, chain) and follow the same
contract as the mainnet adapters: fetch() never raises, never mocks; apy=None
and status="error" when the feed is unavailable.

EXIT_LATENCY_HOURS = 0.0 for all (instant L2 lending — same-block withdrawals,
subject only to transient pool utilization).

Chain-limit rules enforced at portfolio level in spa_core/risk/chain_limits.py:
  single chain ≤ 70%, L2 combined ≤ 50%.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)


# ─── Base mix-in ─────────────────────────────────────────────────────────────

class _L2BaseAdapter(BaseAdapter):
    """Shared fetch() logic for all L2 adapters.

    Concrete subclasses set the class-level constants; _L2BaseAdapter wires
    them into a single generic fetch() implementation that:
      1. Calls DeFiLlamaFeed.get_apy / get_tvl with the chain parameter.
      2. Populates the ``chain`` key in the returned dict.
      3. Never raises, never returns a mock value.
    """

    PROTOCOL: str = "l2_base"
    DEFILLAMA_PROJECT: str = ""
    DEFILLAMA_SYMBOL: str = "USDC"
    DEFILLAMA_CHAIN: str = ""
    TIER: str = "T2"
    T2_CAP: float = 0.20
    RISK_SCORE: float = 0.35
    EXIT_LATENCY_HOURS: float = 0.0
    pool_id: str = "unknown"

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    def fetch(self) -> dict:
        """Return a flat status dict. Never raises, never mocks.

        Returns a dict with keys:
          pool_id, protocol, tier, chain (lowercase),
          apy (decimal or None), tvl (USD or None),
          status ("ok" | "error"), error, live_data, source, ts.
        """
        record: dict = {
            "pool_id": self.pool_id,
            "protocol": self.PROTOCOL,
            "tier": self.tier,
            "chain": self.DEFILLAMA_CHAIN.lower(),
            "apy": None,
            "tvl": None,
            "status": "error",
            "error": "live_feed_unavailable",
            "live_data": False,
            "source": "defillama",
            "ts": time.time(),
        }
        try:
            apy = self.feed.get_apy(
                self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN
            )
            tvl = self.feed.get_tvl(
                self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: live feed raised: %s", self.PROTOCOL, exc)
            record["error"] = f"{type(exc).__name__}: {exc}"
            return record

        record["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        if not isinstance(apy, (int, float)):
            logger.warning(
                "%s: DeFiLlama APY unavailable — reporting no live data", self.PROTOCOL
            )
            return record

        record["apy"] = float(apy)
        record["status"] = "ok"
        record["error"] = None
        record["live_data"] = True
        return record

    def get_apy(self) -> Optional[float]:
        """Return live APY as a decimal (e.g. 0.052), or None if no live data."""
        return self.fetch().get("apy")

    def get_yield_info(self) -> YieldInfo:
        """Return normalized YieldInfo for the orchestrator."""
        data = self.fetch()
        tvl = data.get("tvl")
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=data.get("apy"),
            tvl_usd=float(tvl) if isinstance(tvl, (int, float)) else None,
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )


# ─── Concrete L2 adapters ─────────────────────────────────────────────────────

class AaveV3ArbitrumAdapter(_L2BaseAdapter):
    """Read-only DeFiLlama feed for Aave V3 USDC on Arbitrum (T2).

    MP-203: first L2 anchor. Arbitrum has Aave V3 deployed with deep USDC
    liquidity. Classified T2 (vs T1 for the mainnet instance) because L2
    bridges introduce additional smart-contract and bridge risk vs Ethereum.
    """

    PROTOCOL = "aave_v3_arbitrum"
    DEFILLAMA_PROJECT = "aave-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Arbitrum"
    TIER = "T2"
    T2_CAP = 0.20
    RISK_SCORE = 0.28
    # Instant exit: Aave V3 USDC on Arbitrum settles same-block.
    EXIT_LATENCY_HOURS = 0.0

    pool_id = "aave-v3-usdc-arbitrum"


class AaveV3BaseAdapter(_L2BaseAdapter):
    """Read-only DeFiLlama feed for Aave V3 USDC on Base (T2).

    MP-203: Base (Coinbase L2) instance of the same Aave V3 market.
    """

    PROTOCOL = "aave_v3_base"
    DEFILLAMA_PROJECT = "aave-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Base"
    TIER = "T2"
    T2_CAP = 0.20
    RISK_SCORE = 0.28
    EXIT_LATENCY_HOURS = 0.0

    pool_id = "aave-v3-usdc-base"


class CompoundV3BaseAdapter(_L2BaseAdapter):
    """Read-only DeFiLlama feed for Compound V3 (Comet) USDC on Base (T2).

    MP-203: Compound V3 deployed the Comet USDC market on Base. Classified T2
    because the Base bridge introduces additional risk vs the mainnet instance.
    """

    PROTOCOL = "compound_v3_base"
    DEFILLAMA_PROJECT = "compound-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Base"
    TIER = "T2"
    T2_CAP = 0.20
    RISK_SCORE = 0.28
    EXIT_LATENCY_HOURS = 0.0

    pool_id = "compound-v3-usdc-base"


class MorphoBlueBaseAdapter(_L2BaseAdapter):
    """Read-only DeFiLlama feed for Morpho Blue USDC on Base (T2).

    MP-203: Morpho Blue markets exist on Base. Same T2 classification as the
    mainnet instance, with additional L2 bridge risk.
    """

    PROTOCOL = "morpho_blue_base"
    DEFILLAMA_PROJECT = "morpho-blue"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Base"
    TIER = "T2"
    T2_CAP = 0.20
    RISK_SCORE = 0.35
    EXIT_LATENCY_HOURS = 0.0

    pool_id = "morpho-blue-usdc-base"


# ─── L2 registry fragment ──────────────────────────────────────────────────────

#: Drop-in extension for ADAPTER_REGISTRY in spa_core/adapters/__init__.py.
#: Usage:
#:   from spa_core.adapters.l2_adapters import L2_ADAPTER_REGISTRY
#:   ADAPTER_REGISTRY.extend(L2_ADAPTER_REGISTRY)
L2_ADAPTER_REGISTRY = [
    ("aave_v3_arbitrum", "T2", AaveV3ArbitrumAdapter),
    ("aave_v3_base",     "T2", AaveV3BaseAdapter),
    ("compound_v3_base", "T2", CompoundV3BaseAdapter),
    ("morpho_blue_base", "T2", MorphoBlueBaseAdapter),
]

# end of file
