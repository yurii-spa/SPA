"""
MP-766: FeeDragCalculator
Computes cumulative fee drag on yield over time: management fees, performance
fees, gas costs, and swap fees. Tracks net yield after fees, fee_drag_pct,
fee_efficiency_score (0-100, higher = less drag). Compares gross vs net APY
and computes the break-even holding period.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import math
import os
import time
from pathlib import Path

DATA_FILE = Path("data/fee_drag_log.json")
MAX_ENTRIES = 100

_ZERO_EPS = 1e-12


@dataclass
class FeeSpec:
    """Fee parameters for a single calculate_drag call."""
    management_fee_bps: float = 0.0   # annual, basis points (100 bps = 1 %)
    performance_fee_pct: float = 0.0  # % of gross yield (e.g. 20.0 = 20 %)
    gas_cost_usd: float = 0.0         # one-time gas cost in USD
    swap_fee_bps: float = 0.0         # one-time swap fee, basis points on capital


@dataclass
class FeeDragReport:
    """Result of a fee drag calculation."""
    gross_apy: float            # % per year (input)
    capital_usd: float          # USD (input)
    holding_days: int           # days (input)
    fees: FeeSpec               # fee parameters (input)

    gross_yield_usd: float      # USD earned before fees over holding_days
    management_fee_usd: float   # time-proportional management fee cost
    performance_fee_usd: float  # performance fee cost (% of gross yield)
    gas_cost_usd: float         # one-time gas cost (copied from fees)
    swap_fee_usd: float         # one-time swap fee USD
    total_fees_usd: float       # sum of all fee components

    net_yield_after_fees: float  # gross_yield - total_fees (may be negative)
    gross_apy_display: float     # same as gross_apy (for symmetry)
    net_apy: float               # effective APY after all fees
    fee_drag_pct: float          # what % of gross yield is eaten by fees (0-100)
    fee_efficiency_score: float  # 100 - fee_drag_pct clamped to [0, 100]
    break_even_days: Optional[float]  # days needed to cover fixed costs; None if impossible

    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class FeeDragCalculator:
    """
    Computes how fees erode yield for a given holding period and capital.
    Advisory only — never modifies allocator, risk, or execution domains.

    Usage::

        calc = FeeDragCalculator()
        fees = FeeSpec(management_fee_bps=50, performance_fee_pct=20,
                       gas_cost_usd=15.0, swap_fee_bps=30)
        report = calc.calculate_drag(gross_apy=5.0, fees=fees,
                                      capital_usd=10_000, holding_days=90)
        print(report.net_apy, report.break_even_days)
    """

    def __init__(self) -> None:
        self._last_report: Optional[FeeDragReport] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _annual_fraction(bps: float) -> float:
        """Convert basis points to a plain fraction (e.g. 100 bps → 0.01)."""
        return bps / 10_000.0

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _compute_break_even_days(
        capital_usd: float,
        gross_apy: float,
        perf_pct: float,
        mgmt_bps: float,
        fixed_costs_usd: float,
    ) -> Optional[float]:
        """
        Compute days at which net yield = 0 (covering fixed costs).

        Per day:
          gross_yield_rate = capital * (gross_apy/100) / 365
          mgmt_rate        = capital * (mgmt_bps/10000) / 365
          perf_rate        = gross_yield_rate * (perf_pct/100)
          net_daily        = gross_yield_rate - mgmt_rate - perf_rate

        break_even_days = fixed_costs / net_daily
        Returns None when net_daily <= 0 (impossible) or inputs invalid.
        """
        if capital_usd <= 0 or gross_apy <= 0:
            return None
        daily_gross = capital_usd * (gross_apy / 100.0) / 365.0
        daily_mgmt = capital_usd * (mgmt_bps / 10_000.0) / 365.0
        daily_perf = daily_gross * (perf_pct / 100.0)
        net_daily = daily_gross - daily_mgmt - daily_perf
        if net_daily <= _ZERO_EPS:
            return None  # fees exceed or match gross yield — never break even
        if fixed_costs_usd <= 0:
            return 0.0   # already profitable on day 1
        return fixed_costs_usd / net_daily

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_drag(
        self,
        gross_apy: float,
        fees: FeeSpec,
        capital_usd: float,
        holding_days: int,
    ) -> FeeDragReport:
        """
        Calculate fee drag and net yield for the given parameters.

        Parameters
        ----------
        gross_apy     : gross annual yield in % (e.g. 5.0 = 5 %)
        fees          : FeeSpec instance with all fee parameters
        capital_usd   : invested capital in USD
        holding_days  : investment duration in days (must be >= 1)

        Returns
        -------
        FeeDragReport with all computed fields populated.
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Guard: sensible defaults for degenerate inputs
        safe_capital = max(0.0, capital_usd)
        safe_days = max(1, int(holding_days))
        safe_gross_apy = max(0.0, gross_apy)
        time_fraction = safe_days / 365.0

        # --- Gross yield ---
        gross_yield_usd = safe_capital * (safe_gross_apy / 100.0) * time_fraction

        # --- Fee components ---
        management_fee_usd = (
            safe_capital
            * self._annual_fraction(fees.management_fee_bps)
            * time_fraction
        )
        performance_fee_usd = gross_yield_usd * (fees.performance_fee_pct / 100.0)
        gas_cost_usd = max(0.0, fees.gas_cost_usd)
        swap_fee_usd = safe_capital * self._annual_fraction(fees.swap_fee_bps)

        total_fees_usd = (
            management_fee_usd + performance_fee_usd + gas_cost_usd + swap_fee_usd
        )

        # --- Net yield ---
        net_yield_after_fees = gross_yield_usd - total_fees_usd

        # --- Net APY ---
        if safe_capital > _ZERO_EPS and safe_days > 0:
            net_apy = (net_yield_after_fees / safe_capital) / time_fraction * 100.0
        else:
            net_apy = 0.0

        # --- Fee drag % (proportion of gross yield consumed by fees) ---
        if gross_yield_usd > _ZERO_EPS:
            fee_drag_raw = (total_fees_usd / gross_yield_usd) * 100.0
        elif total_fees_usd > _ZERO_EPS:
            fee_drag_raw = 100.0  # fees present but no gross yield
        else:
            fee_drag_raw = 0.0   # both zero
        fee_drag_pct = self._clamp(fee_drag_raw, 0.0, 100.0)

        # --- Efficiency score ---
        fee_efficiency_score = self._clamp(100.0 - fee_drag_pct, 0.0, 100.0)

        # --- Break-even ---
        fixed_costs_usd = gas_cost_usd + swap_fee_usd
        break_even_days = self._compute_break_even_days(
            capital_usd=safe_capital,
            gross_apy=safe_gross_apy,
            perf_pct=fees.performance_fee_pct,
            mgmt_bps=fees.management_fee_bps,
            fixed_costs_usd=fixed_costs_usd,
        )

        # --- Advisory ---
        advisory = self._build_advisory(
            gross_apy=safe_gross_apy,
            net_apy=net_apy,
            fee_drag_pct=fee_drag_pct,
            fee_efficiency_score=fee_efficiency_score,
            break_even_days=break_even_days,
            holding_days=safe_days,
            net_yield_after_fees=net_yield_after_fees,
        )

        report = FeeDragReport(
            gross_apy=round(safe_gross_apy, 6),
            capital_usd=round(safe_capital, 2),
            holding_days=safe_days,
            fees=fees,
            gross_yield_usd=round(gross_yield_usd, 6),
            management_fee_usd=round(management_fee_usd, 6),
            performance_fee_usd=round(performance_fee_usd, 6),
            gas_cost_usd=round(gas_cost_usd, 6),
            swap_fee_usd=round(swap_fee_usd, 6),
            total_fees_usd=round(total_fees_usd, 6),
            net_yield_after_fees=round(net_yield_after_fees, 6),
            gross_apy_display=round(safe_gross_apy, 6),
            net_apy=round(net_apy, 6),
            fee_drag_pct=round(fee_drag_pct, 4),
            fee_efficiency_score=round(fee_efficiency_score, 4),
            break_even_days=round(break_even_days, 2) if break_even_days is not None else None,
            advisory=advisory,
            generated_at=generated_at,
        )

        self._last_report = report
        return report

    def get_net_apy(self) -> float:
        """Return net APY from the most recent calculate_drag call, or 0.0."""
        if self._last_report is None:
            return 0.0
        return self._last_report.net_apy

    def get_break_even_days(self) -> Optional[float]:
        """Return break-even holding period (days) from the most recent call, or None."""
        if self._last_report is None:
            return None
        return self._last_report.break_even_days

    # ------------------------------------------------------------------
    # Advisory text
    # ------------------------------------------------------------------

    @staticmethod
    def _build_advisory(
        gross_apy: float,
        net_apy: float,
        fee_drag_pct: float,
        fee_efficiency_score: float,
        break_even_days: Optional[float],
        holding_days: int,
        net_yield_after_fees: float,
    ) -> List[str]:
        out: List[str] = []

        if fee_drag_pct >= 100.0:
            out.append(
                "Fees consume 100 % or more of gross yield — position is loss-making after costs"
            )
        elif fee_drag_pct > 50.0:
            out.append(
                f"High fee drag: {fee_drag_pct:.1f} % of gross yield is consumed by fees"
            )
        elif fee_drag_pct > 20.0:
            out.append(
                f"Moderate fee drag: {fee_drag_pct:.1f} % of gross yield lost to fees"
            )
        else:
            out.append(
                f"Low fee drag: only {fee_drag_pct:.1f} % of gross yield consumed by fees"
            )

        if gross_apy > 0:
            apy_delta = gross_apy - net_apy
            out.append(
                f"Gross APY {gross_apy:.2f} % → Net APY {net_apy:.2f} %"
                f" (drag of {apy_delta:.2f} pp)"
            )

        if net_yield_after_fees < 0:
            out.append("Net yield is negative — total fees exceed gross returns")

        if break_even_days is not None:
            if break_even_days <= 0:
                out.append("Break-even achieved immediately (no significant fixed costs)")
            elif break_even_days > holding_days:
                out.append(
                    f"Break-even requires {break_even_days:.1f} days but holding"
                    f" period is only {holding_days} days — position does not recoup fixed costs"
                )
            else:
                out.append(
                    f"Break-even after {break_even_days:.1f} days"
                    f" (within {holding_days}-day holding period)"
                )
        else:
            out.append(
                "Break-even impossible — proportional fees match or exceed gross yield"
            )

        if fee_efficiency_score >= 80:
            out.append(f"Fee efficiency score: {fee_efficiency_score:.1f}/100 — EFFICIENT")
        elif fee_efficiency_score >= 50:
            out.append(f"Fee efficiency score: {fee_efficiency_score:.1f}/100 — MODERATE")
        else:
            out.append(f"Fee efficiency score: {fee_efficiency_score:.1f}/100 — POOR")

        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: FeeDragReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to the ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gross_apy": report.gross_apy,
            "net_apy": report.net_apy,
            "capital_usd": report.capital_usd,
            "holding_days": report.holding_days,
            "gross_yield_usd": report.gross_yield_usd,
            "total_fees_usd": report.total_fees_usd,
            "net_yield_after_fees": report.net_yield_after_fees,
            "fee_drag_pct": report.fee_drag_pct,
            "fee_efficiency_score": report.fee_efficiency_score,
            "break_even_days": report.break_even_days,
            "management_fee_usd": report.management_fee_usd,
            "performance_fee_usd": report.performance_fee_usd,
            "gas_cost_usd": report.gas_cost_usd,
            "swap_fee_usd": report.swap_fee_usd,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load ring-buffer history. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI / demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    calc = FeeDragCalculator()
    fees = FeeSpec(
        management_fee_bps=50,       # 0.50 % per year
        performance_fee_pct=20.0,    # 20 % of profit
        gas_cost_usd=15.0,           # $15 one-time
        swap_fee_bps=30,             # 0.30 % one-time on capital
    )
    report = calc.calculate_drag(
        gross_apy=5.0,
        fees=fees,
        capital_usd=10_000.0,
        holding_days=90,
    )
    print(f"Gross APY:            {report.gross_apy:.2f} %")
    print(f"Net APY:              {report.net_apy:.4f} %")
    print(f"Gross yield:          ${report.gross_yield_usd:.4f}")
    print(f"Total fees:           ${report.total_fees_usd:.4f}")
    print(f"Net yield:            ${report.net_yield_after_fees:.4f}")
    print(f"Fee drag:             {report.fee_drag_pct:.2f} %")
    print(f"Efficiency score:     {report.fee_efficiency_score:.1f}/100")
    print(f"Break-even days:      {report.break_even_days}")
    for line in report.advisory:
        print(f"  - {line}")
    print()
    print(f"get_net_apy()         → {calc.get_net_apy():.4f} %")
    print(f"get_break_even_days() → {calc.get_break_even_days()}")


if __name__ == "__main__":
    _demo()
