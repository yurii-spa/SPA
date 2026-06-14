"""
MP-734: YieldBreakevenCalculator
Decide whether a position's yield justifies the entry+exit transaction costs, and
after how many days it breaks even. Computes the effective compounded annual yield,
daily yield in USD, breakeven horizon (days), cost as a fraction of position size,
and (when an intended hold is supplied) net profit and cost-amortized net APY over
that hold. Classifies the trade as PROFITABLE / MARGINAL / UNPROFITABLE / UNKNOWN.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_breakeven_log.json")
MAX_ENTRIES = 100

# Default reward APY (fraction) applied on top of the base/gross APY.
DEFAULT_REWARD_APY = 0.0
# Default compounding periods per year (daily compounding).
DEFAULT_COMPOUNDING_PER_YEAR = 365

# Absolute breakeven-day thresholds used when no intended hold is supplied.
BREAKEVEN_DAYS_PROFITABLE = 30.0
BREAKEVEN_DAYS_MARGINAL = 90.0

# Relative thresholds (fraction of the intended hold) used when a hold is supplied.
BREAKEVEN_FRACTION_PROFITABLE = 0.5   # breakeven within half the hold => PROFITABLE
BREAKEVEN_FRACTION_MARGINAL = 1.0     # breakeven within the full hold  => MARGINAL

# Flag transaction cost when it exceeds this fraction of the position (1%).
HIGH_COST_PCT_THRESHOLD = 0.01


@dataclass
class BreakevenReport:
    position_size_usd: float
    entry_cost_usd: float
    exit_cost_usd: float
    total_cost_usd: float
    gross_apy: float                 # fraction
    reward_apy: float                # fraction
    gross_apy_total: float           # fraction (gross + reward)
    compounding_per_year: int
    effective_annual_yield: float    # fraction, after compounding
    daily_yield_usd: float
    breakeven_days: Optional[float]  # None when undefined (non-positive daily yield)
    cost_as_pct_of_position: float   # fraction
    intended_hold_days: Optional[float]
    net_profit_usd: Optional[float]  # over the intended hold (None if no hold)
    net_apy: Optional[float]         # cost-amortized over the hold (None if no hold)
    verdict_tier: str                # PROFITABLE/MARGINAL/UNPROFITABLE/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class YieldBreakevenCalculator:
    """
    Computes the breakeven horizon and net-of-cost economics of holding a yield
    position. Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_annual_yield(apy_total: float, compounding_per_year: int) -> float:
        """
        Effective annual yield given a nominal APY and a compounding frequency:
        (1 + apy/n)**n - 1. With n <= 1 (or non-positive) this reduces to apy.
        """
        n = compounding_per_year
        if n is None or n <= 1:
            return apy_total
        return (1.0 + apy_total / n) ** n - 1.0

    @staticmethod
    def _daily_yield_usd(position_size_usd: float, effective_annual: float) -> float:
        """USD earned per day from the effective annual yield (365-day year)."""
        return position_size_usd * effective_annual / 365.0

    @staticmethod
    def _breakeven_days(total_cost_usd: float, daily_yield_usd: float) -> Optional[float]:
        """Days for accumulated yield to cover total cost. None if yield <= 0."""
        if daily_yield_usd <= 0.0:
            return None
        return total_cost_usd / daily_yield_usd

    @staticmethod
    def _classify(
        breakeven_days: Optional[float],
        intended_hold_days: Optional[float],
    ) -> str:
        """
        Tier the trade. With an intended hold, compare the breakeven horizon to
        fractions of that hold; without one, use absolute day thresholds.
        """
        if breakeven_days is None:
            return "UNKNOWN"
        if intended_hold_days is not None and intended_hold_days > 0:
            if breakeven_days <= BREAKEVEN_FRACTION_PROFITABLE * intended_hold_days:
                return "PROFITABLE"
            if breakeven_days <= BREAKEVEN_FRACTION_MARGINAL * intended_hold_days:
                return "MARGINAL"
            return "UNPROFITABLE"
        if breakeven_days <= BREAKEVEN_DAYS_PROFITABLE:
            return "PROFITABLE"
        if breakeven_days <= BREAKEVEN_DAYS_MARGINAL:
            return "MARGINAL"
        return "UNPROFITABLE"

    @staticmethod
    def _build_advisory(
        tier: str,
        breakeven_days: Optional[float],
        intended_hold_days: Optional[float],
        cost_as_pct_of_position: float,
        net_profit_usd: Optional[float],
        net_apy: Optional[float],
    ) -> List[str]:
        out: List[str] = []
        if tier == "PROFITABLE":
            if intended_hold_days is not None:
                out.append(
                    f"Profitable: breaks even in {breakeven_days:.2f} days, well within "
                    f"the intended {intended_hold_days:.2f}-day hold"
                )
            else:
                out.append(
                    f"Profitable: breaks even in {breakeven_days:.2f} days "
                    f"(<= {BREAKEVEN_DAYS_PROFITABLE:.0f}-day fast-payback threshold)"
                )
        elif tier == "MARGINAL":
            if intended_hold_days is not None:
                out.append(
                    f"Marginal: breaks even in {breakeven_days:.2f} days, only just inside "
                    f"the intended {intended_hold_days:.2f}-day hold — little safety margin"
                )
            else:
                out.append(
                    f"Marginal: breaks even in {breakeven_days:.2f} days "
                    f"(payback between {BREAKEVEN_DAYS_PROFITABLE:.0f} and "
                    f"{BREAKEVEN_DAYS_MARGINAL:.0f} days)"
                )
        elif tier == "UNPROFITABLE":
            if intended_hold_days is not None:
                out.append(
                    f"Unprofitable for this hold: breaks even in {breakeven_days:.2f} days, "
                    f"beyond the intended {intended_hold_days:.2f}-day hold"
                )
            else:
                out.append(
                    f"Unprofitable: breaks even only after {breakeven_days:.2f} days "
                    f"(> {BREAKEVEN_DAYS_MARGINAL:.0f}-day slow-payback threshold)"
                )
        else:
            out.append(
                "Breakeven undefined — daily yield is non-positive, so transaction "
                "costs are never recovered from yield"
            )
        if cost_as_pct_of_position > HIGH_COST_PCT_THRESHOLD:
            out.append(
                f"High transaction cost: {cost_as_pct_of_position * 100:.3f}% of position "
                f"(> {HIGH_COST_PCT_THRESHOLD * 100:.1f}% guideline) — cost drag is material"
            )
        if net_profit_usd is not None and net_profit_usd < 0.0:
            out.append(
                f"Net loss over the intended hold: {net_profit_usd:.2f} USD — yield does not "
                "cover entry+exit costs within the planned horizon"
            )
        if net_apy is not None and net_apy < 0.0:
            out.append(
                "Cost-amortized net APY is negative — costs spread over the hold outweigh "
                "the gross yield"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        position_size_usd: float = 10000.0,
        entry_cost_usd: float = 15.0,
        exit_cost_usd: float = 15.0,
        gross_apy: float = 0.12,
        reward_apy: float = DEFAULT_REWARD_APY,
        intended_hold_days: Optional[float] = None,
        compounding_per_year: int = DEFAULT_COMPOUNDING_PER_YEAR,
    ) -> BreakevenReport:
        """Compute a BreakevenReport for a single yield position."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        total_cost_usd = entry_cost_usd + exit_cost_usd
        gross_apy_total = gross_apy + reward_apy

        # Guard degenerate inputs: a non-positive position cannot be analyzed.
        if position_size_usd <= 0.0:
            return BreakevenReport(
                position_size_usd=round(position_size_usd, 6),
                entry_cost_usd=round(entry_cost_usd, 6),
                exit_cost_usd=round(exit_cost_usd, 6),
                total_cost_usd=round(total_cost_usd, 6),
                gross_apy=round(gross_apy, 6),
                reward_apy=round(reward_apy, 6),
                gross_apy_total=round(gross_apy_total, 6),
                compounding_per_year=compounding_per_year,
                effective_annual_yield=0.0,
                daily_yield_usd=0.0,
                breakeven_days=None,
                cost_as_pct_of_position=0.0,
                intended_hold_days=intended_hold_days,
                net_profit_usd=None,
                net_apy=None,
                verdict_tier="UNKNOWN",
                advisory=["Position size must be positive to compute breakeven economics"],
                generated_at=generated_at,
            )

        effective_annual = self._effective_annual_yield(
            gross_apy_total, compounding_per_year
        )
        daily_yield_usd = self._daily_yield_usd(position_size_usd, effective_annual)
        breakeven_days = self._breakeven_days(total_cost_usd, daily_yield_usd)
        cost_as_pct_of_position = total_cost_usd / position_size_usd

        net_profit_usd: Optional[float] = None
        net_apy: Optional[float] = None
        if intended_hold_days is not None and intended_hold_days > 0:
            net_profit_usd = daily_yield_usd * intended_hold_days - total_cost_usd
            net_apy = effective_annual - cost_as_pct_of_position * (
                365.0 / intended_hold_days
            )

        tier = self._classify(breakeven_days, intended_hold_days)
        advisory = self._build_advisory(
            tier,
            breakeven_days,
            intended_hold_days,
            cost_as_pct_of_position,
            net_profit_usd,
            net_apy,
        )

        return BreakevenReport(
            position_size_usd=round(position_size_usd, 6),
            entry_cost_usd=round(entry_cost_usd, 6),
            exit_cost_usd=round(exit_cost_usd, 6),
            total_cost_usd=round(total_cost_usd, 6),
            gross_apy=round(gross_apy, 6),
            reward_apy=round(reward_apy, 6),
            gross_apy_total=round(gross_apy_total, 6),
            compounding_per_year=compounding_per_year,
            effective_annual_yield=round(effective_annual, 6),
            daily_yield_usd=round(daily_yield_usd, 6),
            breakeven_days=(round(breakeven_days, 6) if breakeven_days is not None else None),
            cost_as_pct_of_position=round(cost_as_pct_of_position, 6),
            intended_hold_days=intended_hold_days,
            net_profit_usd=(round(net_profit_usd, 6) if net_profit_usd is not None else None),
            net_apy=(round(net_apy, 6) if net_apy is not None else None),
            verdict_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: BreakevenReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "position_size_usd": report.position_size_usd,
            "total_cost_usd": report.total_cost_usd,
            "gross_apy_total": report.gross_apy_total,
            "effective_annual_yield": report.effective_annual_yield,
            "daily_yield_usd": report.daily_yield_usd,
            "breakeven_days": report.breakeven_days,
            "cost_as_pct_of_position": report.cost_as_pct_of_position,
            "intended_hold_days": report.intended_hold_days,
            "net_profit_usd": report.net_profit_usd,
            "net_apy": report.net_apy,
            "verdict_tier": report.verdict_tier,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load history from ring-buffer JSON. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    calc = YieldBreakevenCalculator()
    report = calc.analyze(
        position_size_usd=10000.0,
        entry_cost_usd=20.0,
        exit_cost_usd=18.0,
        gross_apy=0.14,
        reward_apy=0.02,
        intended_hold_days=60.0,
        compounding_per_year=365,
    )
    print(f"Position size:        ${report.position_size_usd:,.2f}")
    print(f"Total cost:           ${report.total_cost_usd:,.2f}")
    print(f"Gross APY (total):    {report.gross_apy_total * 100:.3f}%")
    print(f"Effective annual:     {report.effective_annual_yield * 100:.3f}%")
    print(f"Daily yield:          ${report.daily_yield_usd:,.4f}")
    bd = report.breakeven_days
    print(f"Breakeven days:       {bd:.3f}" if bd is not None else "Breakeven days:       undefined")
    print(f"Cost as % of pos:     {report.cost_as_pct_of_position * 100:.4f}%")
    if report.net_profit_usd is not None:
        print(f"Net profit (hold):    ${report.net_profit_usd:,.2f}")
        print(f"Net APY (amortized):  {report.net_apy * 100:.3f}%")
    print(f"Verdict tier:         {report.verdict_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
