"""
MP-718: TimeWeightedReturnCalculator
Compute the True Time-Weighted Return (TWR) of a strategy by geometrically linking
per-sub-period returns. TWR neutralises the distorting effect of the *timing* of
external cash flows (deposits / withdrawals), measuring pure investment skill rather
than the luck of when capital arrived. Also derives the geometric mean per-period
return, an annualized TWR, and best / worst sub-period statistics, then classifies
the performance tier. Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/twr_log.json")
MAX_ENTRIES = 100

# Default number of sub-periods per year used for annualization (1 => none).
DEFAULT_PERIODS_PER_YEAR = 1

# Annualized TWR performance tiers (fractions).
TWR_STRONG = 0.10
TWR_MODERATE = 0.03
TWR_FLAT = 0.0
# < 0 => NEGATIVE


@dataclass
class TWRReport:
    num_periods: int
    cumulative_twr: float            # fraction (factor - 1)
    annualized_twr: float            # fraction
    geometric_mean_return: float     # per-period, fraction
    best_period_return: float        # fraction
    worst_period_return: float       # fraction
    positive_period_ratio: float     # fraction of sub-periods with r > 0
    periods_per_year: int
    performance_tier: str            # STRONG/MODERATE/FLAT/NEGATIVE/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class TimeWeightedReturnCalculator:
    """
    Computes the True Time-Weighted Return from a list of per-sub-period returns.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(annualized_twr: float) -> str:
        if annualized_twr >= TWR_STRONG:
            return "STRONG"
        if annualized_twr >= TWR_MODERATE:
            return "MODERATE"
        if annualized_twr >= TWR_FLAT:
            return "FLAT"
        return "NEGATIVE"

    @staticmethod
    def _build_advisory(
        tier: str,
        annualized_twr: float,
        total_loss: bool,
        positive_period_ratio: float,
    ) -> List[str]:
        out: List[str] = []
        if total_loss:
            out.append("Total loss in at least one sub-period")
        if tier == "STRONG":
            out.append(
                f"Strong time-weighted performance (annualized TWR {annualized_twr * 100:.2f}%)"
            )
        elif tier == "MODERATE":
            out.append(
                f"Moderate time-weighted performance (annualized TWR {annualized_twr * 100:.2f}%)"
            )
        elif tier == "FLAT":
            out.append(
                "Flat time-weighted performance — returns barely positive over the window"
            )
        else:
            out.append(
                "Negative time-weighted performance — geometric linking yielded a loss "
                "independent of cash-flow timing"
            )
        if positive_period_ratio < 0.5 and not total_loss:
            out.append(
                "Majority of sub-periods were non-positive — return consistency is weak"
            )
        return out

    def subreturns_from_navs(
        self,
        navs: List[float],
        flows: Optional[List[float]] = None,
    ) -> List[float]:
        """
        Derive per-sub-period returns from a series of Net Asset Values (NAVs).

        Cash-flow convention: **end-of-period external net inflow**.
        For a NAV series of length ``k`` there are ``k - 1`` sub-periods. The
        external net inflow ``flow_i`` (positive = deposit, negative = withdrawal)
        for sub-period ``i`` is assumed to land *at the end* of that sub-period, so
        the NAV at the close of the period (``navs[i+1]``) already includes it. The
        investment-only return for the period therefore strips the flow back out::

            r_i = (navs[i+1] - flow_i) / navs[i] - 1

        ``flows`` (if provided) must have length ``len(navs) - 1`` — one entry per
        sub-period. When ``flows`` is None every flow defaults to 0.0.

        Guards:
        * A NAV series with fewer than 2 points yields ``[]`` (no sub-periods).
        * A non-positive opening NAV (``navs[i] <= 0``) makes the period return
          undefined; for such a period we emit ``0.0`` (treated as flat) rather
          than dividing by zero. This keeps the geometric chain well-defined and
          is documented behaviour rather than a silent skip.
        """
        if len(navs) < 2:
            return []
        n_periods = len(navs) - 1
        if flows is None:
            flows = [0.0] * n_periods
        out: List[float] = []
        for i in range(n_periods):
            opening = navs[i]
            flow_i = flows[i] if i < len(flows) else 0.0
            if opening <= 0:
                # Undefined return for a non-positive opening NAV — treat as flat.
                out.append(0.0)
                continue
            r_i = (navs[i + 1] - flow_i) / opening - 1.0
            out.append(r_i)
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        subperiod_returns: List[float],
        periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
    ) -> TWRReport:
        """Compute a TWRReport by geometrically linking per-sub-period returns."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ppy = periods_per_year if periods_per_year and periods_per_year > 0 else 1

        n = len(subperiod_returns)
        if n == 0:
            return TWRReport(
                num_periods=0,
                cumulative_twr=0.0,
                annualized_twr=0.0,
                geometric_mean_return=0.0,
                best_period_return=0.0,
                worst_period_return=0.0,
                positive_period_ratio=0.0,
                periods_per_year=ppy,
                performance_tier="UNKNOWN",
                advisory=["Need at least 1 sub-period return to compute TWR"],
                generated_at=generated_at,
            )

        # Geometric linking: factor = product of (1 + r).
        factor = 1.0
        total_loss = False
        for r in subperiod_returns:
            growth = 1.0 + r
            if growth <= 0:
                total_loss = True
            factor *= growth

        best = max(subperiod_returns)
        worst = min(subperiod_returns)
        positives = sum(1 for r in subperiod_returns if r > 0)
        positive_period_ratio = positives / n

        if total_loss:
            # A wipe-out in any sub-period drives cumulative value to (at most) zero;
            # we report a full loss and undefined-but-clamped geometric/annual figures.
            cumulative_twr = -1.0
            geometric_mean_return = -1.0
            annualized_twr = -1.0
        else:
            cumulative_twr = factor - 1.0
            geometric_mean_return = factor ** (1.0 / n) - 1.0
            annualized_twr = factor ** (ppy / n) - 1.0

        tier = self._classify(annualized_twr)
        advisory = self._build_advisory(
            tier, annualized_twr, total_loss, positive_period_ratio
        )

        return TWRReport(
            num_periods=n,
            cumulative_twr=round(cumulative_twr, 6),
            annualized_twr=round(annualized_twr, 6),
            geometric_mean_return=round(geometric_mean_return, 6),
            best_period_return=round(best, 6),
            worst_period_return=round(worst, 6),
            positive_period_ratio=round(positive_period_ratio, 6),
            periods_per_year=ppy,
            performance_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: TWRReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_periods": report.num_periods,
            "cumulative_twr": report.cumulative_twr,
            "annualized_twr": report.annualized_twr,
            "geometric_mean_return": report.geometric_mean_return,
            "best_period_return": report.best_period_return,
            "worst_period_return": report.worst_period_return,
            "positive_period_ratio": report.positive_period_ratio,
            "periods_per_year": report.periods_per_year,
            "performance_tier": report.performance_tier,
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
    calc = TimeWeightedReturnCalculator()
    # Monthly sub-period returns (fractions).
    subperiod_returns = [0.02, -0.01, 0.015, 0.008, -0.005, 0.012]
    report = calc.analyze(subperiod_returns, periods_per_year=12)
    print(f"Sub-periods:          {report.num_periods}")
    print(f"Cumulative TWR:       {report.cumulative_twr * 100:.3f}%")
    print(f"Annualized TWR:       {report.annualized_twr * 100:.3f}%")
    print(f"Geometric mean:       {report.geometric_mean_return * 100:.3f}% / period")
    print(f"Best period:          {report.best_period_return * 100:.3f}%")
    print(f"Worst period:         {report.worst_period_return * 100:.3f}%")
    print(f"Positive period ratio:{report.positive_period_ratio:.3f}")
    print(f"Periods per year:     {report.periods_per_year}")
    print(f"Performance tier:     {report.performance_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
