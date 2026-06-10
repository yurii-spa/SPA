"""Yearn V3 adapter (T2 tier) — read-only, live DeFiLlama feed only.

SPA-V398: no mock APY. When the live DeFiLlama feed is unavailable this adapter
reports ``status="error"`` / ``apy=None`` — an honest "no live data" signal — and
never substitutes a hard-coded value.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)


class YearnV3Adapter(BaseAdapter):
    PROTOCOL = "yearn_v3"
    DEFILLAMA_PROJECT = "yearn-finance"
    DEFILLAMA_SYMBOL = "USDC"
    RISK_SCORE = 0.30

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = "T2"
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    def fetch(self) -> dict:
        """Return a flat status dict from the live feed. Never raises, never mocks.

        ``apy`` is a **decimal** (e.g. 0.072 == 7.2%) to match the SPA adapter
        convention (the orchestrator converts to a percentage). On any failure
        ``status="error"``, ``apy=None`` and ``live_data=False``.
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
        try:
            apy = self.feed.get_apy(self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL)
            tvl = self.feed.get_tvl(self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL)
        except Exception as exc:  # noqa: BLE001 - graceful: feed errors are honest errors.
            logger.warning("%s: live feed raised: %s", self.PROTOCOL, exc)
            record["error"] = f"{type(exc).__name__}: {exc}"
            return record

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
        )

    # end of class
