"""
MP-657: FundingRateMonitor
Track perpetual futures funding rates to detect carry trade
opportunities vs yield strategies.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
"""

from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/funding_rate_log.json")
MAX_ENTRIES = 100

# Funding rate thresholds (annualized %)
THRESHOLDS = {
    "EXTREME_POSITIVE": 0.50,   # >50% annual → very bullish, premium
    "HIGH_POSITIVE":    0.20,   # >20% annual → bullish
    "NEUTRAL_UPPER":    0.05,   # >5%
    "NEUTRAL_LOWER":   -0.05,   # >-5%
    "HIGH_NEGATIVE":   -0.20,   # >-20%
    # below -20% → extreme negative (bearish)
}


@dataclass
class FundingRateSnapshot:
    asset: str                   # e.g. "ETH", "BTC"
    exchange: str                # e.g. "Binance", "dYdX"
    funding_rate_8h: float       # raw 8-hour funding rate (decimal, e.g. 0.0001 = 0.01%)
    funding_rate_annual: float   # annualized: rate_8h * 3 * 365
    regime: str                  # EXTREME_POSITIVE / BULLISH / NEUTRAL / BEARISH / EXTREME_NEGATIVE
    carry_opportunity: bool       # True if annualized rate > 10% (worth basis trade)
    carry_vs_spa_bps: float      # (funding_rate_annual - spa_apy) * 10000
    advisory: str


class FundingRateMonitor:
    """
    Monitor perpetual futures funding rates and flag carry trade opportunities.

    spa_reference_apy — SPA's baseline annualised yield (decimal, e.g. 0.10 = 10%)
    used to compute carry_vs_spa_bps.
    """

    def __init__(
        self,
        data_file: Path = DATA_FILE,
        spa_reference_apy: float = 0.10,
    ):
        self.data_file = data_file
        self.spa_reference_apy = spa_reference_apy

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _annualize(self, rate_8h: float) -> float:
        """8h rate → annualised: rate * 3 * 365."""
        return round(rate_8h * 3 * 365, 6)

    def _regime(self, annual: float) -> str:
        """Classify annualised funding rate into a named regime."""
        if annual >= THRESHOLDS["EXTREME_POSITIVE"]:
            return "EXTREME_POSITIVE"
        if annual >= THRESHOLDS["HIGH_POSITIVE"]:
            return "BULLISH"
        if annual >= THRESHOLDS["NEUTRAL_LOWER"]:
            return "NEUTRAL"
        if annual >= THRESHOLDS["HIGH_NEGATIVE"]:
            return "BEARISH"
        return "EXTREME_NEGATIVE"

    def _carry_opportunity(self, annual: float) -> bool:
        """True if annualised funding rate > 10% (attractive for basis trade)."""
        return annual > 0.10

    def _advisory(self, regime: str, carry: bool, carry_vs_spa: float) -> str:
        """Generate human-readable advisory string."""
        base = {
            "EXTREME_POSITIVE": "⚡ Extreme premium — basis trade very attractive",
            "BULLISH":          "📈 Positive funding — consider basis hedge",
            "NEUTRAL":          "➡️ Neutral funding — no carry signal",
            "BEARISH":          "📉 Negative funding — longs paid, shorts pay",
            "EXTREME_NEGATIVE": "⚡ Extreme discount — inverse carry opportunity",
        }[regime]
        if carry and carry_vs_spa > 0:
            return f"{base}. Funding beats SPA by {carry_vs_spa:.0f}bps"
        return base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        asset: str,
        exchange: str,
        rate_8h: float,
    ) -> FundingRateSnapshot:
        """
        Analyse a single 8-hour funding rate sample and return a snapshot.
        """
        annual = self._annualize(rate_8h)
        regime = self._regime(annual)
        carry = self._carry_opportunity(annual)
        carry_vs_spa = round((annual - self.spa_reference_apy) * 10000, 2)
        return FundingRateSnapshot(
            asset=asset,
            exchange=exchange,
            funding_rate_8h=round(rate_8h, 8),
            funding_rate_annual=annual,
            regime=regime,
            carry_opportunity=carry,
            carry_vs_spa_bps=carry_vs_spa,
            advisory=self._advisory(regime, carry, carry_vs_spa),
        )

    def best_carry(
        self,
        snapshots: List[FundingRateSnapshot],
    ) -> Optional[FundingRateSnapshot]:
        """Return snapshot with highest annualised funding rate; None if empty."""
        if not snapshots:
            return None
        return max(snapshots, key=lambda s: s.funding_rate_annual)

    def carry_opportunities(
        self,
        snapshots: List[FundingRateSnapshot],
    ) -> List[FundingRateSnapshot]:
        """Return only snapshots where carry_opportunity is True."""
        return [s for s in snapshots if s.carry_opportunity]

    def save_snapshots(self, snapshots: List[FundingRateSnapshot]) -> None:
        """
        Append snapshots to the ring-buffer JSON log (max MAX_ENTRIES).
        Uses atomic write: tmp + os.replace.
        """
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for s in snapshots:
            existing.append({
                "timestamp": time.time(),
                "asset": s.asset,
                "exchange": s.exchange,
                "funding_rate_annual": s.funding_rate_annual,
                "regime": s.regime,
                "carry_opportunity": s.carry_opportunity,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved ring-buffer log; returns [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
