"""
MP-672: LiquidityPoolDepthAnalyzer
Analyze liquidity pool depth to estimate price impact of trades and LP fee capture potential.

Advisory/read-only — never modifies allocator, risk, or execution domains.
Pure stdlib only. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/pool_depth_log.json")
MAX_ENTRIES = 100


@dataclass
class PoolDepthProfile:
    pool_id: str
    pool_type: str           # "CONSTANT_PRODUCT", "STABLE_SWAP", "CONCENTRATED"
    tvl_usd: float
    volume_24h_usd: float    # recent trading volume
    trade_size_usd: float    # hypothetical trade to analyze
    tick_spacing: Optional[float]   # for concentrated liquidity (None = not applicable)
    active_liquidity_pct: float     # 0-100: % of TVL in active range (concentrated only, else 100)


@dataclass
class PoolDepthReport:
    pool_id: str
    pool_type: str
    price_impact_pct: float       # estimated price impact for trade_size
    fee_apy_estimate_pct: float   # estimated APY from fees based on volume/TVL
    depth_score: float            # 0.0–1.0 (1.0 = very deep, low impact)
    depth_rating: str             # DEEP / ADEQUATE / SHALLOW / VERY_SHALLOW
    liquidity_quality: str        # EXCELLENT / GOOD / FAIR / POOR
    recommendations: List[str]


class LiquidityPoolDepthAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _price_impact_pct(self, p: PoolDepthProfile) -> float:
        """Estimate price impact for trade_size against this pool."""
        if p.pool_type == "CONSTANT_PRODUCT":
            impact = (p.trade_size_usd / p.tvl_usd) * 100 * 2
        elif p.pool_type == "STABLE_SWAP":
            impact = (p.trade_size_usd / p.tvl_usd) * 100 * 0.1
        elif p.pool_type == "CONCENTRATED":
            effective_tvl = p.tvl_usd * (p.active_liquidity_pct / 100)
            if effective_tvl <= 0:
                return 100.0
            impact = (p.trade_size_usd / effective_tvl) * 100 * 2
        else:
            # Unknown pool type — fall back to constant product formula
            impact = (p.trade_size_usd / p.tvl_usd) * 100 * 2
        return min(100.0, impact)

    def _fee_apy_estimate_pct(self, p: PoolDepthProfile) -> float:
        """Estimate annual fee APY assuming 0.3% fee tier."""
        if p.tvl_usd <= 0:
            return 0.0
        apy = (p.volume_24h_usd * 365 * 0.003) / p.tvl_usd * 100
        return min(999.0, apy)

    def _depth_score(self, price_impact_pct: float) -> float:
        """Score 0.0–1.0: 10% impact → 0.0, 0% impact → 1.0."""
        return max(0.0, min(1.0, 1.0 - (price_impact_pct / 10.0)))

    def _depth_rating(self, depth_score: float) -> str:
        """Categorise depth from score."""
        if depth_score >= 0.8:
            return "DEEP"
        elif depth_score >= 0.5:
            return "ADEQUATE"
        elif depth_score >= 0.2:
            return "SHALLOW"
        else:
            return "VERY_SHALLOW"

    def _liquidity_quality(self, depth_rating: str, fee_apy: float) -> str:
        """Combine depth quality with fee yield potential."""
        if fee_apy > 5.0 and depth_rating in ("DEEP", "ADEQUATE"):
            return "EXCELLENT"
        elif fee_apy > 2.0 and depth_rating in ("DEEP", "ADEQUATE", "SHALLOW"):
            return "GOOD"
        elif fee_apy > 0.0:
            return "FAIR"
        else:
            return "POOR"

    def _recommendations(
        self,
        p: PoolDepthProfile,
        price_impact_pct: float,
        depth_rating: str,
        fee_apy: float,
    ) -> List[str]:
        """Generate actionable recommendations."""
        recs: List[str] = []
        if price_impact_pct > 2.0:
            recs.append(
                f"⚠️ High price impact {price_impact_pct:.1f}% — split trade or use aggregator"
            )
        elif price_impact_pct > 0.5:
            recs.append(
                "📋 Moderate price impact — consider splitting large trades"
            )
        if p.pool_type == "CONSTANT_PRODUCT" and p.tvl_usd < 1_000_000:
            recs.append("⚠️ Low TVL pool — liquidity risk")
        if p.active_liquidity_pct < 50:
            recs.append(
                f"⚠️ Concentrated LP: only {p.active_liquidity_pct:.0f}% active — high rebalancing risk"
            )
        if fee_apy > 20:
            recs.append(
                f"💰 High fee APY {fee_apy:.1f}% — attractive LP opportunity but verify volume sustainability"
            )
        if depth_rating in ("SHALLOW", "VERY_SHALLOW"):
            recs.append("🚨 Shallow pool — execution quality poor for this trade size")
        return recs

    def analyze(self, p: PoolDepthProfile) -> PoolDepthReport:
        price_impact = self._price_impact_pct(p)
        fee_apy = self._fee_apy_estimate_pct(p)
        depth_score = self._depth_score(price_impact)
        depth_rating = self._depth_rating(depth_score)
        liquidity_quality = self._liquidity_quality(depth_rating, fee_apy)
        recs = self._recommendations(p, price_impact, depth_rating, fee_apy)
        return PoolDepthReport(
            pool_id=p.pool_id,
            pool_type=p.pool_type,
            price_impact_pct=price_impact,
            fee_apy_estimate_pct=fee_apy,
            depth_score=depth_score,
            depth_rating=depth_rating,
            liquidity_quality=liquidity_quality,
            recommendations=recs,
        )

    def analyze_batch(self, profiles: List[PoolDepthProfile]) -> List[PoolDepthReport]:
        return [self.analyze(p) for p in profiles]

    def save_results(self, results: List[PoolDepthReport]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append(
                {
                    "timestamp": time.time(),
                    "pool_id": r.pool_id,
                    "pool_type": r.pool_type,
                    "price_impact_pct": r.price_impact_pct,
                    "fee_apy_estimate_pct": r.fee_apy_estimate_pct,
                    "depth_score": r.depth_score,
                    "depth_rating": r.depth_rating,
                    "liquidity_quality": r.liquidity_quality,
                }
            )
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
