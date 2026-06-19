"""Aave V3 adapter (T1 tier) — read-only T1 anchor, live DeFiLlama feed only.

SPA-V405: introduced as the **T1 anchor** that closes the structural 20% cash
drag in the allocator. Four T2 adapters capped at 20% each can only deploy 80%
of capital; a T1 protocol capped at 40% gives the allocator headroom to fill the
remainder instead of parking it in 0%-yield cash.

Like the other live adapters (SPA-V398), this reports ``status="error"`` /
``apy=None`` whenever the DeFiLlama feed is unavailable — it **never** returns a
mock value. ``get_yield_info().apy`` is a decimal (e.g. ``0.052`` == 5.2%); the
orchestrator converts it to a percentage.

This module is strictly read-only / advisory: it never touches capital and is
NOT imported by ``execution/``, ``feed_health/`` or the deterministic risk
agents.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from spa_core.utils.errors import safe_call

logger = logging.getLogger(__name__)


class AaveV3Adapter(BaseAdapter):
    """Read-only DeFiLlama feed for the Aave V3 USDC market on Ethereum (T1)."""

    PROTOCOL = "aave_v3"
    DEFILLAMA_PROJECT = "aave-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Ethereum"
    RISK_SCORE = 0.20  # T1 anchor — lowest-risk whitelisted protocol.

    # SPA-V412: instant exit. Aave V3 USDC is a liquid supply position —
    # withdrawals settle in the same block (subject only to transient pool
    # utilization), so the declared exit latency is 0h.
    EXIT_LATENCY_HOURS = 0.0

    TIER = "T1"
    T1_CAP = 0.40  # max 40% of portfolio in this single T1 protocol.

    # Stable identifier used by downstream consumers / dashboards.
    pool_id = "aave-v3-usdc-ethereum"

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = self.TIER
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    def fetch(self) -> dict:
        """Return a flat status dict from the live feed. Never raises, never mocks.

        ``apy`` is a **decimal** (orchestrator converts to a percentage). On any
        failure ``status="error"``, ``apy=None`` and ``live_data=False``.
        """
        record: dict = {
            "pool_id": self.pool_id,
            "protocol": self.PROTOCOL,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "status": "error",
            "error": "live_feed_unavailable",
            "live_data": False,
            "source": "defillama",
            "ts": time.time(),
        }
        apy = safe_call(
            self.feed.get_apy,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=True, logger_name=f"spa.{self.PROTOCOL}",
        )
        tvl = safe_call(
            self.feed.get_tvl,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=False,
        )

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
        """Return the live APY as a decimal, or ``None`` if no live data."""
        return self.fetch().get("apy")

    def get_yield_info(self) -> YieldInfo:
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

    # end of class
