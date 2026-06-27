"""
Pendle PT Allocation Strategy for SPA Paper Trading.

Fixed-rate positions: enter at discount, hold to maturity (or until APY compression).

Key difference from lending pools
----------------------------------
- Position is NOT liquid the same way — model as locked until maturity
- APY is fixed at entry — doesn't change daily (unlike Aave variable APY)
- Exit: either hold to maturity OR sell PT back to pool (at market price)

Paper trading simulation
-------------------------
- Entry: buy PT at current implied APY
- Exit: simulate holding to maturity (APY = fixed at entry)
- Track: days_to_maturity, entry_apy, current_value

Integration with engine.py
----------------------------
After T1 allocation, engine calls:
    pt = PendleFetcher().get_best_pt()
    if pt:
        size = pendle_allocation_size(capital, pt["apy"])
        if size > 0:
            # open position with asset="PT-STABLE", special="fixed_rate"

ADR reference: ADR_002_pendle_pt_integration.md (PROPOSED)
Status: PAPER TRADING ONLY — awaiting owner approval before any live allocation.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class PendlePosition:
    """
    Represents a single Pendle PT position in the paper trading portfolio.

    Attributes:
        pool_id:          DeFiLlama pool UUID (for API lookups)
        symbol:           Human-readable PT symbol, e.g. "PT-USDC-26DEC2026"
        chain:            "arbitrum" or "ethereum"
        amount_usd:       Capital deployed (USD notional at entry)
        entry_apy:        Fixed APY locked at entry (annualised %)
        entry_date:       ISO date string YYYY-MM-DD of position open
        maturity_date:    ISO date string YYYY-MM-DD of PT maturity, or None
        days_to_maturity: Days until maturity at entry time (default 90)
    """

    pool_id: str
    symbol: str
    chain: str
    amount_usd: float
    entry_apy: float            # APY locked at entry (%)
    entry_date: str             # YYYY-MM-DD
    maturity_date: Optional[str] = None   # YYYY-MM-DD or None if unparseable
    days_to_maturity: int = 90  # assumed 90d when maturity not parseable

    # ── Computed properties ────────────────────────────────────────────────

    @property
    def days_held(self) -> int:
        """Calendar days since position was opened."""
        try:
            entry = datetime.date.fromisoformat(self.entry_date)
            return max(0, (datetime.date.today() - entry).days)
        except (ValueError, TypeError):
            return 0

    @property
    def accrued_return_usd(self) -> float:
        """
        Accrued return from fixed APY since entry.
        Uses simple interest (daily accrual): amount × (apy/100/365) × days_held
        """
        daily_rate = self.entry_apy / 100.0 / 365.0
        return self.amount_usd * daily_rate * self.days_held

    @property
    def current_value_usd(self) -> float:
        """Current value = principal + accrued interest."""
        return self.amount_usd + self.accrued_return_usd

    @property
    def days_remaining(self) -> Optional[int]:
        """Days until maturity from today, or None if unknown."""
        if self.maturity_date is None:
            return None
        try:
            mat = datetime.date.fromisoformat(self.maturity_date)
            return max(0, (mat - datetime.date.today()).days)
        except (ValueError, TypeError):
            return None

    @property
    def is_near_maturity(self) -> bool:
        """True if within 14 days of maturity (liquidity risk zone)."""
        remaining = self.days_remaining
        return remaining is not None and remaining <= 14

    @property
    def expected_total_return_usd(self) -> float:
        """
        Expected return if held to full maturity.
        Simple interest over the full days_to_maturity period.
        """
        daily_rate = self.entry_apy / 100.0 / 365.0
        return self.amount_usd * daily_rate * self.days_to_maturity

    def to_dict(self) -> dict:
        """Serialize to dict (compatible with engine position format)."""
        return {
            "pool_id":              self.pool_id,
            "symbol":               self.symbol,
            "chain":                self.chain,
            "amount_usd":           round(self.amount_usd, 2),
            "entry_apy":            round(self.entry_apy, 4),
            "entry_date":           self.entry_date,
            "maturity_date":        self.maturity_date,
            "days_to_maturity":     self.days_to_maturity,
            "days_held":            self.days_held,
            "days_remaining":       self.days_remaining,
            "accrued_return_usd":   round(self.accrued_return_usd, 4),
            "current_value_usd":    round(self.current_value_usd, 4),
            "is_near_maturity":     self.is_near_maturity,
            "protocol":             "Pendle PT",
            "tier":                 "T2",
            "asset":                "PT-STABLE",
            "special":              "fixed_rate",
        }


def pendle_allocation_size(
    capital: float,
    current_apy: float,
    t1_baseline_apy: float = 4.0,
    max_t2_pct: float = 0.20,
    min_premium: float = 2.0,
) -> float:
    """
    Compute how much capital to allocate to a Pendle PT position.

    Logic
    ------
    Pendle premium = pendle_apy - t1_baseline_apy
    - If premium < min_premium (default 2%): return 0 — not worth T2 risk
    - Otherwise: scale allocation proportionally to premium, capped at T2 limit

    Scaling formula:
        raw_pct = min(premium / (2 × min_premium) × max_t2_pct, max_t2_pct)

    Examples at defaults (capital=$100K, baseline=4%, max_t2=20%, min_prem=2%):
        APY=6.0% → premium=2.0% → raw_pct=10.0% → $10,000
        APY=7.0% → premium=3.0% → raw_pct=15.0% → $15,000
        APY=8.0% → premium=4.0% → raw_pct=20.0% → $20,000 (cap)
        APY=12.0% → premium=8.0% → raw_pct=20.0% → $20,000 (cap)

    Args:
        capital:         Total portfolio capital in USD
        current_apy:     Current Pendle PT APY (%)
        t1_baseline_apy: Blended T1 pool APY baseline (default 4%)
        max_t2_pct:      Maximum T2 allocation as fraction of capital (default 0.20)
        min_premium:     Minimum APY premium required over T1 baseline (default 2%)

    Returns:
        Dollar amount to allocate (0.0 if premium insufficient).
    """
    premium = current_apy - t1_baseline_apy

    if premium < min_premium:
        log.debug(
            f"pendle_allocation_size: premium {premium:.2f}% < min {min_premium:.2f}% — skip"
        )
        return 0.0

    # Scale: at min_premium → 50% of T2 cap; at 2×min_premium → 100% of T2 cap
    scale = min(premium / (2.0 * min_premium), 1.0)
    raw_pct = scale * max_t2_pct
    allocation = round(capital * raw_pct, 2)

    log.info(
        f"pendle_allocation_size: APY={current_apy:.2f}%, premium={premium:.2f}%, "
        f"scale={scale:.2f}, pct={raw_pct:.1%}, amount=${allocation:,.2f}"
    )
    return allocation


def build_pendle_position(
    pool: dict,
    amount_usd: float,
    entry_date: Optional[str] = None,
) -> PendlePosition:
    """
    Construct a PendlePosition from a PendleFetcher pool dict.

    Args:
        pool:        Pool dict returned by PendleFetcher.fetch_pt_pools()
        amount_usd:  Capital to deploy
        entry_date:  ISO date string (defaults to today)

    Returns:
        PendlePosition ready for paper tracking
    """
    today = datetime.date.today().isoformat()
    return PendlePosition(
        pool_id=pool.get("pool_id") or "unknown",
        symbol=pool.get("symbol") or "PT-STABLE",
        chain=pool.get("chain", "arbitrum"),
        amount_usd=amount_usd,
        entry_apy=pool.get("apy", 0.0),
        entry_date=entry_date or today,
        maturity_date=pool.get("maturity_date"),
        days_to_maturity=pool.get("days_to_maturity") or 90,
    )
