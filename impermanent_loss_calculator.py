# spa_core/analytics/impermanent_loss_calculator.py
# MP-659 — ImpermanentLossCalculator (pure stdlib, advisory/read-only)
# IL formula for constant-product AMM (Uniswap V2):
#   IL = 2*sqrt(k) / (1 + k) - 1   where k = current_price / entry_price

from dataclasses import dataclass
from typing import List, Optional
import json
import math
import os
import time
from pathlib import Path

DATA_FILE = Path("data/impermanent_loss_log.json")
MAX_ENTRIES = 100


@dataclass
class LPPosition:
    pool_id: str
    token_a: str            # e.g. "ETH"
    token_b: str            # e.g. "USDC"
    entry_price: float      # price of token_a in terms of token_b at entry
    current_price: float    # current price of token_a in terms of token_b
    capital_usd: float      # USD value at entry
    fees_earned_usd: float  # cumulative fees since entry


@dataclass
class ILResult:
    pool_id: str
    token_a: str
    token_b: str
    entry_price: float
    current_price: float
    price_ratio: float          # current / entry
    il_pct: float               # impermanent loss as % (negative = loss)
    il_usd: float               # IL in dollar terms
    fees_earned_usd: float
    net_pnl_usd: float          # fees - IL (fees + il_usd, since il_usd is negative)
    net_pnl_pct: float          # net_pnl / capital
    hold_value_usd: float       # value if just held (not provided LP)
    lp_value_usd: float         # current LP position value
    breakeven_fees_usd: float   # fees needed to break even on IL
    verdict: str                # PROFITABLE / BREAKEVEN / LOSING
    severity: str               # NONE(<0.1%) / MILD(<1%) / MODERATE(<5%) / SEVERE(≥5%)


class ImpermanentLossCalculator:
    """
    IL formula for constant-product AMM:
        IL = 2*sqrt(k) / (1 + k) - 1
        where k = current_price / entry_price (price ratio)
    IL is always <= 0 (loss vs holding).
    LP value relative to hold = 2*sqrt(k)/(1+k)
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _il_ratio(self, price_ratio: float) -> float:
        """IL = 2*sqrt(k)/(1+k) - 1. Returns negative value (loss)."""
        if price_ratio <= 0:
            return -1.0  # total loss
        k = price_ratio
        return 2.0 * math.sqrt(k) / (1.0 + k) - 1.0

    def _severity(self, il_pct: float) -> str:
        """il_pct is negative (loss). abs value used."""
        abs_il = abs(il_pct)
        if abs_il < 0.001:
            return "NONE"
        if abs_il < 0.01:
            return "MILD"
        if abs_il < 0.05:
            return "MODERATE"
        return "SEVERE"

    def _verdict(self, net_pnl_usd: float) -> str:
        if net_pnl_usd > 1.0:
            return "PROFITABLE"
        if net_pnl_usd > -1.0:
            return "BREAKEVEN"
        return "LOSING"

    def calculate(self, pos: LPPosition) -> ILResult:
        k = pos.current_price / pos.entry_price if pos.entry_price > 0 else 0.0
        il_ratio = self._il_ratio(k)
        il_pct = round(il_ratio, 6)

        # hold_value_usd: 50/50 portfolio revalued at new price
        # Start: 50% in token_a, 50% in token_b (by USD value at entry)
        # If price ratio = k, hold_value relative to entry = (k + 1) / 2
        hold_value_usd = round(pos.capital_usd * (k + 1) / 2, 4)
        lp_value_usd = round(hold_value_usd * (1.0 + il_ratio), 4)
        il_usd = round(lp_value_usd - hold_value_usd, 4)
        net_pnl_usd = round(pos.fees_earned_usd + il_usd, 4)
        net_pnl_pct = round(net_pnl_usd / pos.capital_usd, 6) if pos.capital_usd > 0 else 0.0
        breakeven_fees = round(-il_usd, 4) if il_usd < 0 else 0.0

        return ILResult(
            pool_id=pos.pool_id,
            token_a=pos.token_a,
            token_b=pos.token_b,
            entry_price=round(pos.entry_price, 6),
            current_price=round(pos.current_price, 6),
            price_ratio=round(k, 6),
            il_pct=il_pct,
            il_usd=il_usd,
            fees_earned_usd=round(pos.fees_earned_usd, 4),
            net_pnl_usd=net_pnl_usd,
            net_pnl_pct=net_pnl_pct,
            hold_value_usd=hold_value_usd,
            lp_value_usd=lp_value_usd,
            breakeven_fees_usd=breakeven_fees,
            verdict=self._verdict(net_pnl_usd),
            severity=self._severity(il_pct),
        )

    def calculate_batch(self, positions: List[LPPosition]) -> List[ILResult]:
        return [self.calculate(p) for p in positions]

    def worst_il(self, results: List[ILResult]) -> Optional[ILResult]:
        if not results:
            return None
        return min(results, key=lambda r: r.il_usd)

    def total_net_pnl(self, results: List[ILResult]) -> float:
        return round(sum(r.net_pnl_usd for r in results), 4)

    def save_results(self, results: List[ILResult]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append({
                "timestamp": time.time(),
                "pool_id": r.pool_id,
                "il_pct": r.il_pct,
                "severity": r.severity,
                "net_pnl_usd": r.net_pnl_usd,
                "verdict": r.verdict,
            })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
