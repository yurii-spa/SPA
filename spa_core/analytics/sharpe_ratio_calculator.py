"""
MP-705: SharpeRatioCalculator
Compute risk-adjusted return metrics for a series of periodic returns: mean return,
volatility (sample stdev), downside deviation, the Sharpe ratio and the Sortino
ratio, with optional annualization. Classifies the risk-adjusted performance tier.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/sharpe_ratio_log.json")
MAX_ENTRIES = 100

# Default per-period risk-free rate (fraction, e.g. 0.0 means none applied).
DEFAULT_RISK_FREE_PER_PERIOD = 0.0
# Default annualization factor (e.g. 12 for monthly, 365 for daily, 1 for none).
DEFAULT_PERIODS_PER_YEAR = 1

# Annualized Sharpe performance tiers.
SHARPE_EXCELLENT = 2.0
SHARPE_GOOD = 1.0
SHARPE_ACCEPTABLE = 0.0
# < 0 => POOR

# Threshold below which volatility/downside-deviation is treated as exactly zero
# (guards against floating-point dust on constant return series).
_ZERO_EPS = 1e-12


@dataclass
class SharpeReport:
    num_returns: int
    mean_return: float               # per-period, fraction
    volatility: float                # per-period sample stdev, fraction
    downside_deviation: float        # per-period, fraction
    risk_free_per_period: float
    periods_per_year: int
    sharpe_ratio: float              # per-period
    sortino_ratio: float             # per-period
    annualized_sharpe: float
    annualized_sortino: float
    annualized_return: float         # fraction
    performance_tier: str            # EXCELLENT/GOOD/ACCEPTABLE/POOR/UNKNOWN
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class SharpeRatioCalculator:
    """
    Computes Sharpe / Sortino style risk-adjusted return metrics.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    @staticmethod
    def _sample_stdev(xs: List[float], mean: float) -> float:
        """Sample (n-1) standard deviation. 0.0 for fewer than 2 points."""
        if len(xs) < 2:
            return 0.0
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        return math.sqrt(var)

    @staticmethod
    def _downside_deviation(xs: List[float], target: float) -> float:
        """
        Downside deviation relative to a target (here the risk-free rate).
        Root-mean-square of negative excess returns, averaged over all periods.
        """
        if not xs:
            return 0.0
        sq = [min(0.0, x - target) ** 2 for x in xs]
        return math.sqrt(sum(sq) / len(xs))

    @staticmethod
    def _classify(annualized_sharpe: float) -> str:
        if annualized_sharpe >= SHARPE_EXCELLENT:
            return "EXCELLENT"
        if annualized_sharpe >= SHARPE_GOOD:
            return "GOOD"
        if annualized_sharpe >= SHARPE_ACCEPTABLE:
            return "ACCEPTABLE"
        return "POOR"

    @staticmethod
    def _build_advisory(
        tier: str,
        annualized_sharpe: float,
        volatility: float,
        sortino: float,
        sharpe: float,
    ) -> List[str]:
        out: List[str] = []
        if tier == "EXCELLENT":
            out.append(
                f"Excellent risk-adjusted return (annualized Sharpe {annualized_sharpe:.2f})"
            )
        elif tier == "GOOD":
            out.append(
                f"Good risk-adjusted return (annualized Sharpe {annualized_sharpe:.2f})"
            )
        elif tier == "ACCEPTABLE":
            out.append(
                "Acceptable but unremarkable risk-adjusted return — return barely "
                "exceeds the risk-free rate per unit of risk"
            )
        else:
            out.append(
                "Poor risk-adjusted return — returns did not compensate for volatility "
                "above the risk-free rate"
            )
        if volatility == 0.0:
            out.append("Zero volatility in sample — Sharpe/Sortino undefined, reported as 0.0")
        if sortino > sharpe and sortino != 0.0:
            out.append(
                "Sortino exceeds Sharpe — most volatility is upside; downside risk is "
                "comparatively contained"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        returns: List[float],
        risk_free_per_period: float = DEFAULT_RISK_FREE_PER_PERIOD,
        periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
    ) -> SharpeReport:
        """Compute a SharpeReport from a series of per-period returns (fractions)."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ppy = periods_per_year if periods_per_year and periods_per_year > 0 else 1

        if len(returns) < 2:
            return SharpeReport(
                num_returns=len(returns),
                mean_return=round(self._mean(returns), 6),
                volatility=0.0,
                downside_deviation=0.0,
                risk_free_per_period=risk_free_per_period,
                periods_per_year=ppy,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                annualized_sharpe=0.0,
                annualized_sortino=0.0,
                annualized_return=0.0,
                performance_tier="UNKNOWN",
                advisory=["Need at least 2 returns to compute risk-adjusted metrics"],
                generated_at=generated_at,
            )

        mean = self._mean(returns)
        vol = self._sample_stdev(returns, mean)
        dd = self._downside_deviation(returns, risk_free_per_period)
        # Collapse floating-point dust to exact zero so a constant series is not
        # mistaken for having (tiny) volatility, which would explode the ratios.
        if vol < _ZERO_EPS:
            vol = 0.0
        if dd < _ZERO_EPS:
            dd = 0.0
        excess = mean - risk_free_per_period

        sharpe = excess / vol if vol > 0 else 0.0
        sortino = excess / dd if dd > 0 else 0.0

        ann_factor = math.sqrt(ppy)
        annualized_sharpe = sharpe * ann_factor
        annualized_sortino = sortino * ann_factor
        annualized_return = mean * ppy

        tier = self._classify(annualized_sharpe)
        advisory = self._build_advisory(tier, annualized_sharpe, vol, sortino, sharpe)

        return SharpeReport(
            num_returns=len(returns),
            mean_return=round(mean, 6),
            volatility=round(vol, 6),
            downside_deviation=round(dd, 6),
            risk_free_per_period=risk_free_per_period,
            periods_per_year=ppy,
            sharpe_ratio=round(sharpe, 6),
            sortino_ratio=round(sortino, 6),
            annualized_sharpe=round(annualized_sharpe, 6),
            annualized_sortino=round(annualized_sortino, 6),
            annualized_return=round(annualized_return, 6),
            performance_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: SharpeReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_returns": report.num_returns,
            "mean_return": report.mean_return,
            "volatility": report.volatility,
            "downside_deviation": report.downside_deviation,
            "sharpe_ratio": report.sharpe_ratio,
            "sortino_ratio": report.sortino_ratio,
            "annualized_sharpe": report.annualized_sharpe,
            "annualized_sortino": report.annualized_sortino,
            "annualized_return": report.annualized_return,
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
    calc = SharpeRatioCalculator()
    # Monthly returns (fractions).
    returns = [0.012, 0.008, -0.004, 0.015, 0.006, 0.010, -0.002, 0.009]
    report = calc.analyze(returns, risk_free_per_period=0.003, periods_per_year=12)
    print(f"Returns:              {report.num_returns}")
    print(f"Mean return:          {report.mean_return * 100:.3f}% / period")
    print(f"Volatility:           {report.volatility * 100:.3f}% / period")
    print(f"Downside deviation:   {report.downside_deviation * 100:.3f}% / period")
    print(f"Sharpe (period):      {report.sharpe_ratio:.3f}")
    print(f"Sortino (period):     {report.sortino_ratio:.3f}")
    print(f"Annualized Sharpe:    {report.annualized_sharpe:.3f}")
    print(f"Annualized Sortino:   {report.annualized_sortino:.3f}")
    print(f"Performance tier:     {report.performance_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
