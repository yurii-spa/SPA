"""Morpho Blue adapter (T2 tier) — SPA-V326."""
from __future__ import annotations

from .base_adapter import BaseAdapter, YieldInfo


class MorphoBlueAdapter(BaseAdapter):
    PROTOCOL = "morpho_blue"
    MOCK_APY = 0.083

    def __init__(self, asset: str = "USDC"):
        super().__init__(asset)
        self.tier = "T2"

    def get_apy(self) -> float:
        return self.MOCK_APY

    def get_yield_info(self) -> YieldInfo:
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy(),
            tvl_usd=0.0,
            tier=self.tier,
            risk_score=0.35,
        )

    # end of class
