"""Euler V2 adapter (T2 tier) — read-only, live DeFiLlama feed only.

SPA-V398: no mock APY. When the live DeFiLlama feed is unavailable this adapter
reports ``status="error"`` / ``apy=None`` and never substitutes a hard-coded value.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from spa_core.utils.errors import safe_call

logger = logging.getLogger(__name__)


class EulerV2Adapter(BaseAdapter):
    PROTOCOL = "euler_v2"
    DEFILLAMA_PROJECT = "euler-v2"
    DEFILLAMA_SYMBOL = "USDC"
    RISK_SCORE = 0.40

    # SPA-V412: instant exit. Euler V2 USDC supply is a liquid lending position —
    # withdrawals settle same-block subject only to transient vault utilization,
    # so the declared exit latency is 0h.
    EXIT_LATENCY_HOURS = 0.0

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = "T2"
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    def fetch(self) -> dict:
        """Return a flat status dict from the live feed. Never raises, never mocks.

        ``apy`` is a **decimal** (orchestrator converts to a percentage). On any
        failure ``status="error"``, ``apy=None`` and ``live_data=False``.
        """
        record: dict = {
            "pool_id": self.PROTOCOL,
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
            self.feed.get_apy, self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL,
            default=None, log_error=True, logger_name=f"spa.{self.PROTOCOL}",
        )
        tvl = safe_call(
            self.feed.get_tvl, self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL,
            default=None, log_error=False,
        )

        record["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        if not isinstance(apy, (int, float)):
            logger.warning("%s: DeFiLlama APY unavailable — reporting no live data", self.PROTOCOL)
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
