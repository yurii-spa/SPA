"""
MP-783: RewardEmissionDecayTracker
Project the decay of reward-token emissions and the sustainability of the
emission-driven slice of APY. Given a historical emission series, derives the
average geometric decay factor per period, the implied half-life, a forward
projection of future emissions, and classifies the sustainability tier.

Decay factor `f` is the average geometric step from the first to the last
observation: f = (current / initial) ** (1 / (n - 1)).
  decay_pct_per_period = 1 - f
  half_life_periods    = ln(0.5) / ln(f)   (only when 0 < f < 1)

Trend thresholds (on the decay factor f):
  DECAYING   f < 0.98     (shrinking ~2%+ per period)
  STABLE     0.98 <= f <= 1.02
  GROWING    f > 1.02

Sustainability tiers (how durable the emission contribution looks):
  HIGH     STABLE/GROWING trend, or a long half-life (>= HIGH_HALF_LIFE periods)
  MEDIUM   moderate decay (MEDIUM_HALF_LIFE <= half_life < HIGH_HALF_LIFE)
  LOW      fast decay (half_life < MEDIUM_HALF_LIFE periods)
  UNKNOWN  fewer than 2 points, or non-positive / un-analyzable input

Pure stdlib only. Advisory/read-only — never modifies allocator, risk, or
execution domains. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/reward_emission_decay_log.json")
MAX_ENTRIES = 100

# Trend thresholds on the per-period decay factor.
DECAYING_FACTOR = 0.98   # f < this => DECAYING
GROWING_FACTOR = 1.02    # f > this => GROWING
# in between => STABLE

# Sustainability half-life thresholds, in periods.
HIGH_HALF_LIFE = 24.0     # half-life >= this (or stable/growing) => HIGH
MEDIUM_HALF_LIFE = 6.0    # half-life >= this and < HIGH => MEDIUM; below => LOW

# Floating-point dust guard.
_ZERO_EPS = 1e-12


@dataclass
class EmissionDecayReport:
    num_points: int
    current_emission: float
    initial_emission: float
    period_decay_rate: Optional[float]        # geometric factor f per period
    decay_pct_per_period: Optional[float]     # 1 - f
    half_life_periods: Optional[float]
    projected_emissions: List[float]
    cumulative_projected: float
    periods_ahead: int
    trend: str                                # DECAYING/STABLE/GROWING/UNKNOWN
    sustainability_tier: str                  # HIGH/MEDIUM/LOW/UNKNOWN
    label: str = ""
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class RewardEmissionDecayTracker:
    """
    Projects reward-emission decay and classifies emission-APY sustainability.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_trend(factor: Optional[float]) -> str:
        if factor is None:
            return "UNKNOWN"
        if factor < DECAYING_FACTOR:
            return "DECAYING"
        if factor > GROWING_FACTOR:
            return "GROWING"
        return "STABLE"

    @staticmethod
    def _classify_sustainability(
        trend: str, half_life_periods: Optional[float]
    ) -> str:
        if trend == "UNKNOWN":
            return "UNKNOWN"
        # Stable or growing emissions are durable; half-life is None there.
        if trend in ("STABLE", "GROWING"):
            return "HIGH"
        # DECAYING -> grade by half-life.
        if half_life_periods is None:
            return "HIGH"
        if half_life_periods >= HIGH_HALF_LIFE:
            return "HIGH"
        if half_life_periods >= MEDIUM_HALF_LIFE:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _build_advisory(
        trend: str,
        sustainability_tier: str,
        half_life_periods: Optional[float],
        decay_pct_per_period: Optional[float],
    ) -> List[str]:
        out: List[str] = []
        if sustainability_tier == "HIGH":
            out.append(
                "Emission contribution looks sustainable — slow or no decay in the "
                "reward stream"
            )
        elif sustainability_tier == "MEDIUM":
            out.append(
                "Emission contribution is moderately decaying — the emission slice of "
                "APY will erode over time"
            )
        elif sustainability_tier == "LOW":
            out.append(
                "Emission contribution is decaying fast — the emission slice of APY is "
                "unstable and short-lived"
            )
        else:
            out.append("Emission series not analyzable — sustainability tier is unknown")

        if trend == "DECAYING" and decay_pct_per_period is not None:
            out.append(
                f"Emissions shrinking ~{decay_pct_per_period * 100:.2f}% per period"
                + (
                    f" (half-life ~{half_life_periods:.1f} periods)"
                    if half_life_periods is not None
                    else ""
                )
                + " — do not rely on the current emission APY persisting"
            )
        if trend == "GROWING":
            out.append(
                "Emissions are growing — note that rising emissions are often temporary "
                "incentives and may revert"
            )
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        emission_series: List[float],
        periods_ahead: int = 12,
        label: str = "",
    ) -> EmissionDecayReport:
        """Build an EmissionDecayReport from a historical emission series."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        n = len(emission_series) if emission_series else 0
        pa = periods_ahead if periods_ahead and periods_ahead > 0 else 0

        # Guard: need at least 2 points to infer a decay factor.
        if n < 2:
            return EmissionDecayReport(
                num_points=n,
                current_emission=(float(emission_series[-1]) if n else 0.0),
                initial_emission=(float(emission_series[0]) if n else 0.0),
                period_decay_rate=None,
                decay_pct_per_period=None,
                half_life_periods=None,
                projected_emissions=[],
                cumulative_projected=0.0,
                periods_ahead=pa,
                trend="UNKNOWN",
                sustainability_tier="UNKNOWN",
                label=label,
                advisory=["Need at least 2 emission points to infer decay"],
                generated_at=generated_at,
            )

        initial_emission = float(emission_series[0])
        current_emission = float(emission_series[-1])

        # Guard: non-positive endpoints make a geometric factor undefined.
        if initial_emission <= 0 or current_emission <= 0:
            return EmissionDecayReport(
                num_points=n,
                current_emission=round(current_emission, 8),
                initial_emission=round(initial_emission, 8),
                period_decay_rate=None,
                decay_pct_per_period=None,
                half_life_periods=None,
                projected_emissions=[],
                cumulative_projected=0.0,
                periods_ahead=pa,
                trend="UNKNOWN",
                sustainability_tier="UNKNOWN",
                label=label,
                advisory=[
                    "Emission endpoints must be positive to infer a geometric decay factor"
                ],
                generated_at=generated_at,
            )

        # Average geometric decay factor over the (n-1) steps.
        factor = (current_emission / initial_emission) ** (1.0 / (n - 1))
        decay_pct_per_period = 1.0 - factor

        # Half-life only meaningful for genuine decay (0 < factor < 1).
        if 0.0 < factor < 1.0 and abs(math.log(factor)) > _ZERO_EPS:
            half_life_periods: Optional[float] = math.log(0.5) / math.log(factor)
        else:
            half_life_periods = None

        # Forward projection: current * factor**k for k = 1..pa.
        projected_emissions = [
            round(current_emission * (factor ** k), 8) for k in range(1, pa + 1)
        ]
        cumulative_projected = sum(projected_emissions)

        trend = self._classify_trend(factor)
        sustainability_tier = self._classify_sustainability(trend, half_life_periods)
        advisory = self._build_advisory(
            trend, sustainability_tier, half_life_periods, decay_pct_per_period
        )

        return EmissionDecayReport(
            num_points=n,
            current_emission=round(current_emission, 8),
            initial_emission=round(initial_emission, 8),
            period_decay_rate=round(factor, 8),
            decay_pct_per_period=round(decay_pct_per_period, 8),
            half_life_periods=(
                round(half_life_periods, 6) if half_life_periods is not None else None
            ),
            projected_emissions=projected_emissions,
            cumulative_projected=round(cumulative_projected, 8),
            periods_ahead=pa,
            trend=trend,
            sustainability_tier=sustainability_tier,
            label=label,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: EmissionDecayReport, data_file: Path = DATA_FILE
    ) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "label": report.label,
            "num_points": report.num_points,
            "current_emission": report.current_emission,
            "initial_emission": report.initial_emission,
            "period_decay_rate": report.period_decay_rate,
            "decay_pct_per_period": report.decay_pct_per_period,
            "half_life_periods": report.half_life_periods,
            "projected_emissions": report.projected_emissions,
            "cumulative_projected": report.cumulative_projected,
            "periods_ahead": report.periods_ahead,
            "trend": report.trend,
            "sustainability_tier": report.sustainability_tier,
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
    tracker = RewardEmissionDecayTracker()
    # Reward-token emissions per epoch, gently decaying.
    series = [1000.0, 960.0, 925.0, 890.0, 855.0, 820.0]
    report = tracker.analyze(series, periods_ahead=12, label="reward-emission-demo")
    print(f"Label:                 {report.label}")
    print(f"Points:                {report.num_points}")
    print(f"Initial emission:      {report.initial_emission}")
    print(f"Current emission:      {report.current_emission}")
    print(f"Decay factor / period: {report.period_decay_rate}")
    print(f"Decay % / period:      {report.decay_pct_per_period}")
    print(f"Half-life (periods):   {report.half_life_periods}")
    print(f"Cumulative projected:  {report.cumulative_projected}")
    print(f"Trend:                 {report.trend}")
    print(f"Sustainability tier:   {report.sustainability_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
