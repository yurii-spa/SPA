"""
MP-763: ApyVolatilityForecaster
Compute realized (sample stdev) and EWMA volatility of an APY time-series, derive a
coefficient of variation, a simple symmetric forecast band around the latest
observation, and a trend reading. Classifies a stability tier and emits advisory
guidance.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass, field
from typing import List
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/apy_volatility_log.json")
MAX_ENTRIES = 100

DEFAULT_EWMA_LAMBDA = 0.94
DEFAULT_BAND_K = 2.0

# Coefficient-of-variation stability tiers.
CV_STABLE = 0.10
CV_MODERATE = 0.25
CV_VOLATILE = 0.50
# >= 0.50 => HIGHLY_VOLATILE

# Threshold below which realized volatility is treated as exactly zero
# (guards against floating-point dust on a constant series).
_ZERO_EPS = 1e-12


@dataclass
class ApyVolatilityReport:
    num_observations: int
    mean: float
    realized_volatility: float           # sample (n-1) stdev
    ewma_volatility: float               # sqrt of final EWMA variance
    latest: float
    coefficient_of_variation: float
    forecast_low: float
    forecast_high: float
    trend: float                         # latest - first
    stability_tier: str                  # STABLE/MODERATE/VOLATILE/...
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class ApyVolatilityForecaster:
    """
    Computes realized + EWMA volatility and a forecast band for an APY series.
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
    def _ewma_volatility(xs: List[float], mean: float, lam: float) -> float:
        """
        Exponentially-weighted moving-average volatility of deviations from the mean.
        Seeds variance at 0 and iterates var = lam*var + (1-lam)*(x-mean)**2.
        Returns sqrt of the final variance.
        """
        var = 0.0
        for x in xs:
            var = lam * var + (1.0 - lam) * (x - mean) ** 2
        return math.sqrt(var)

    @staticmethod
    def _clamp_lambda(lam: float) -> float:
        """Clamp lambda into the open interval (0, 1); default on out-of-range."""
        if not (0.0 < lam < 1.0):
            return DEFAULT_EWMA_LAMBDA
        return lam

    @staticmethod
    def _classify(cv: float) -> str:
        if cv < CV_STABLE:
            return "STABLE"
        if cv < CV_MODERATE:
            return "MODERATE"
        if cv < CV_VOLATILE:
            return "VOLATILE"
        return "HIGHLY_VOLATILE"

    @staticmethod
    def _build_advisory(
        tier: str,
        ewma_vol: float,
        realized_vol: float,
        trend: float,
    ) -> List[str]:
        out: List[str] = []
        if tier == "STABLE":
            out.append("Stable APY — low dispersion relative to the mean")
        elif tier == "MODERATE":
            out.append("Moderate APY variability — dispersion is noticeable but contained")
        elif tier == "VOLATILE":
            out.append("Volatile APY — dispersion is high relative to the mean")
        else:
            out.append(
                "Highly volatile APY — dispersion is very large relative to the mean"
            )
        if ewma_vol > realized_vol:
            out.append(
                "Recent (EWMA) volatility exceeds full-sample realized volatility — "
                "variability is rising"
            )
        elif ewma_vol < realized_vol:
            out.append(
                "Recent (EWMA) volatility is below full-sample realized volatility — "
                "variability is easing"
            )
        else:
            out.append(
                "Recent (EWMA) volatility matches full-sample realized volatility"
            )
        if trend > 0:
            out.append("Trend is upward — latest observation exceeds the first")
        elif trend < 0:
            out.append("Trend is downward — latest observation is below the first")
        else:
            out.append("Trend is flat — latest observation equals the first")
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        apy_series: List[float],
        ewma_lambda: float = DEFAULT_EWMA_LAMBDA,
        band_k: float = DEFAULT_BAND_K,
    ) -> ApyVolatilityReport:
        """Compute an ApyVolatilityReport from an APY time-series."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if len(apy_series) < 2:
            return ApyVolatilityReport(
                num_observations=len(apy_series),
                mean=round(self._mean(apy_series), 6),
                realized_volatility=0.0,
                ewma_volatility=0.0,
                latest=round(apy_series[-1], 6) if apy_series else 0.0,
                coefficient_of_variation=0.0,
                forecast_low=0.0,
                forecast_high=0.0,
                trend=0.0,
                stability_tier="UNKNOWN",
                advisory=["Need at least 2 observations"],
                generated_at=generated_at,
            )

        lam = self._clamp_lambda(ewma_lambda)
        mean = self._mean(apy_series)
        realized_vol = self._sample_stdev(apy_series, mean)
        if realized_vol < _ZERO_EPS:
            realized_vol = 0.0
        ewma_vol = self._ewma_volatility(apy_series, mean, lam)
        if ewma_vol < _ZERO_EPS:
            ewma_vol = 0.0

        latest = apy_series[-1]
        cv = realized_vol / abs(mean) if mean != 0 else 0.0

        forecast_low = latest - band_k * ewma_vol
        forecast_high = latest + band_k * ewma_vol
        trend = latest - apy_series[0]

        tier = self._classify(cv)
        advisory = self._build_advisory(tier, ewma_vol, realized_vol, trend)

        return ApyVolatilityReport(
            num_observations=len(apy_series),
            mean=round(mean, 6),
            realized_volatility=round(realized_vol, 6),
            ewma_volatility=round(ewma_vol, 6),
            latest=round(latest, 6),
            coefficient_of_variation=round(cv, 6),
            forecast_low=round(forecast_low, 6),
            forecast_high=round(forecast_high, 6),
            trend=round(trend, 6),
            stability_tier=tier,
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: ApyVolatilityReport, data_file: Path = DATA_FILE
    ) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "num_observations": report.num_observations,
            "mean": report.mean,
            "realized_volatility": report.realized_volatility,
            "ewma_volatility": report.ewma_volatility,
            "latest": report.latest,
            "coefficient_of_variation": report.coefficient_of_variation,
            "forecast_low": report.forecast_low,
            "forecast_high": report.forecast_high,
            "trend": report.trend,
            "stability_tier": report.stability_tier,
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
    forecaster = ApyVolatilityForecaster()
    apy_series = [0.052, 0.048, 0.055, 0.061, 0.058, 0.050, 0.047, 0.053]
    report = forecaster.analyze(apy_series)
    print(f"Observations:         {report.num_observations}")
    print(f"Mean APY:             {report.mean * 100:.3f}%")
    print(f"Realized volatility:  {report.realized_volatility * 100:.4f}%")
    print(f"EWMA volatility:      {report.ewma_volatility * 100:.4f}%")
    print(f"Latest APY:           {report.latest * 100:.3f}%")
    print(f"Coeff. of variation:  {report.coefficient_of_variation:.4f}")
    print(f"Forecast band:        [{report.forecast_low * 100:.3f}%, "
          f"{report.forecast_high * 100:.3f}%]")
    print(f"Trend:                {report.trend * 100:+.3f}%")
    print(f"Stability tier:       {report.stability_tier}")
    for line in report.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()
