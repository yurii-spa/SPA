"""Yearn V3 adapter (T2 tier)."""
from __future__ import annotations

import logging
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed

logger = logging.getLogger(__name__)


class YearnV3Adapter(BaseAdapter):
    PROTOCOL = "yearn_v3"
    MOCK_APY = 0.072
    DEFILLAMA_PROJECT = "yearn-finance"
    DEFILLAMA_SYMBOL = "USDC"

    def __init__(self, asset: str = "USDC", feed: Optional[DeFiLlamaFeed] = None):
        super().__init__(asset)
        self.tier = "T2"
        self.feed = feed if feed is not None else DeFiLlamaFeed()

    def get_apy(self) -> float:
        live = self.feed.get_apy(self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL)
        if isinstance(live, (int, float)):
            return float(live)
        logger.warning(
            "%s: DeFiLlama APY unavailable, falling back to MOCK_APY=%s",
            self.PROTOCOL,
            self.MOCK_APY,
        )
        return self.MOCK_APY

    def get_yield_info(self) -> YieldInfo:
        tvl = self.feed.get_tvl(self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL)
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy(),
            tvl_usd=float(tvl) if isinstance(tvl, (int, float)) else 0.0,
            tier=self.tier,
            risk_score=0.30,
        )

    # end of class
