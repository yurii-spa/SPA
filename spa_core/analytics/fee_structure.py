"""
spa_core/analytics/fee_structure.py

SPA fee structure definition and calculator.
MP-1425 (v10.41) — stdlib only, read-only analytics, LLM FORBIDDEN.

Fee schedule:
  Management fee : 1.0% per annum on AUM (accrued daily)
  Performance fee: 10.0% on profits above high-water mark
  Minimum AUM    : $10,000 USDC per investor
  Redemption     : 30-day notice, quarterly windows

Used by:
  - GoLiveReadinessReport.assess_financial()
  - Family fund investor portal (advisory / display only)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

MANAGEMENT_FEE_PCT: float = 1.0       # % per annum
PERFORMANCE_FEE_PCT: float = 10.0     # % above HWM
MIN_INVESTOR_AUM_USD: float = 10_000.0
REDEMPTION_NOTICE_DAYS: int = 30
REDEMPTION_WINDOW: str = "quarterly"  # Jan/Apr/Jul/Oct first business day


# ── FeeStructure dataclass ────────────────────────────────────────────────────

@dataclass
class FeeStructure:
    """Immutable fee schedule for SPA fund."""

    management_fee_pct: float = MANAGEMENT_FEE_PCT
    performance_fee_pct: float = PERFORMANCE_FEE_PCT
    min_investor_aum_usd: float = MIN_INVESTOR_AUM_USD
    redemption_notice_days: int = REDEMPTION_NOTICE_DAYS
    redemption_window: str = REDEMPTION_WINDOW

    # ── derived helpers ───────────────────────────────────────────────────────

    @property
    def daily_mgmt_rate(self) -> float:
        """Daily management fee accrual rate (1% / 365)."""
        return self.management_fee_pct / 100.0 / 365.0

    def management_fee_usd(self, aum_usd: float, days: int = 1) -> float:
        """Management fee for `days` days on AUM (USD)."""
        return aum_usd * self.daily_mgmt_rate * days

    def performance_fee_usd(self, profit_above_hwm_usd: float) -> float:
        """Performance fee on profit above high-water mark (USD)."""
        if profit_above_hwm_usd <= 0:
            return 0.0
        return profit_above_hwm_usd * (self.performance_fee_pct / 100.0)

    def annual_fee_drag_pct(self, return_pct: float) -> float:
        """Estimated total fee drag (management + performance) for a given gross return %."""
        mgmt = self.management_fee_pct
        perf = max(0.0, return_pct - mgmt) * (self.performance_fee_pct / 100.0)
        return round(mgmt + perf, 4)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "management_fee_pct": self.management_fee_pct,
            "performance_fee_pct": self.performance_fee_pct,
            "min_investor_aum_usd": self.min_investor_aum_usd,
            "redemption_notice_days": self.redemption_notice_days,
            "redemption_window": self.redemption_window,
            "daily_mgmt_rate": self.daily_mgmt_rate,
        }

    def summary(self) -> str:
        return (
            f"Management: {self.management_fee_pct}% p.a. | "
            f"Performance: {self.performance_fee_pct}% above HWM | "
            f"Min AUM: ${self.min_investor_aum_usd:,.0f} | "
            f"Redemption: {self.redemption_notice_days}d notice, {self.redemption_window}"
        )


# ── module-level singleton ────────────────────────────────────────────────────

DEFAULT_FEE_STRUCTURE = FeeStructure()


def get_fee_structure() -> FeeStructure:
    """Return the current SPA fee structure (singleton)."""
    return DEFAULT_FEE_STRUCTURE


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import json

    fs = get_fee_structure()
    print("# SPA Fee Structure")
    print()
    print(fs.summary())
    print()
    print(json.dumps(fs.to_dict(), indent=2))


if __name__ == "__main__":
    main()
