"""
MP-769: YieldForecastEngine
============================
Advisory / read-only analytics module.

Provides simple statistical APY forecasts using:
    * Linear regression (OLS)
    * Exponential Moving Average (EMA, alpha=0.3)
    * Ensemble (0.4 * linear + 0.6 * EMA)

Outputs per-call:
    projected_apy          float  — ensemble forecast for horizon_days ahead
    projected_apy_linear   float  — linear-only forecast
    projected_apy_ema      float  — EMA-only forecast
    confidence             float  — R² of linear fit, clamped [0, 1]
    trend_direction        str    — "UP" | "STABLE" | "DOWN"
    forecast_range         dict   — {"min": float, "max": float}

Trend thresholds (slope per day, expressed as APY fraction):
    slope > +0.0001  → UP
    slope < -0.0001  → DOWN
    else             → STABLE

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Advisory only — never modifies risk/, execution/, allocator/, cycle_runner.
* Atomic writes: tmp + os.replace.
* Ring-buffer log capped at 100 entries: data/yield_forecast_log.json
* Deterministic: identical input → identical output.
* NOT imported by risk / execution / monitoring / allocator / cycle_runner.

Linear regression formulae (no numpy):
    n     = len(series)
    x_i   = index i (0-based)
    slope = (n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)
    intercept = (Σy − slope·Σx) / n
    predicted at day (n-1+horizon) = intercept + slope*(n-1+horizon)

R²   = 1 − SS_res / SS_tot
    SS_res = Σ(y_i − ŷ_i)²
    SS_tot = Σ(y_i − ȳ)²
    Degenerate case (SS_tot == 0, flat series) → R² = 1.0

EMA:
    ema_0 = series[0]
    ema_i = alpha * series[i] + (1-alpha) * ema_{i-1}
    Projection: ema_N (last value), extended by slope of EMA series over
    last min(7, n) points * horizon_days.

CLI
---
python3 -m spa_core.analytics.yield_forecast_engine --check
python3 -m spa_core.analytics.yield_forecast_engine --run
python3 -m spa_core.analytics.yield_forecast_engine --data-dir PATH

MP-769.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILE = "yield_forecast_log.json"
RING_BUFFER_CAP = 100

EMA_ALPHA: float = 0.3
LINEAR_WEIGHT: float = 0.4
EMA_WEIGHT: float = 0.6

TREND_UP_THRESHOLD: float = 1e-4    # +0.01% APY per day
TREND_DOWN_THRESHOLD: float = -1e-4  # -0.01% APY per day

TREND_UP = "UP"
TREND_STABLE = "STABLE"
TREND_DOWN = "DOWN"

_ADVISORY = (
    "YieldForecastEngine is advisory only. "
    "Statistical estimates — not financial advice."
)


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _linear_regression(series: List[float]) -> Tuple[float, float]:
    """Return (slope, intercept) of OLS linear fit over index 0..n-1.

    Uses the closed-form formula:
        slope     = (n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)
        intercept = (Σy − slope·Σx) / n

    For a single-element series: slope=0, intercept=series[0].
    """
    n = len(series)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return 0.0, series[0]

    sum_x = 0.0
    sum_y = 0.0
    sum_xy = 0.0
    sum_x2 = 0.0

    for i, y in enumerate(series):
        x = float(i)
        sum_x += x
        sum_y += y
        sum_xy += x * y
        sum_x2 += x * x

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0.0:
        # All x values identical (impossible for n>1 with 0-based index)
        return 0.0, sum_y / n

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


_EPSILON: float = 1e-15   # tolerance for near-zero variance (flat series)


def _r_squared(series: List[float], slope: float, intercept: float) -> float:
    """Compute R² of the linear fit.

    Returns 1.0 if series is constant (SS_tot ≈ 0) — flat APY is a perfect fit.
    Clamped to [0, 1].
    """
    n = len(series)
    if n < 2:
        return 1.0

    mean_y = sum(series) / n
    ss_tot = sum((y - mean_y) ** 2 for y in series)

    # Use tolerance instead of exact equality to handle floating-point
    # accumulation errors in flat series (e.g. [0.05]*20 can yield tiny ss_tot)
    if ss_tot < _EPSILON:
        return 1.0

    ss_res = sum(
        (y - (intercept + slope * i)) ** 2
        for i, y in enumerate(series)
    )
    r2 = 1.0 - ss_res / ss_tot
    # Clamp to [0, 1]
    return max(0.0, min(1.0, r2))


def _compute_ema_series(series: List[float], alpha: float = EMA_ALPHA) -> List[float]:
    """Return EMA series of same length as input.

    ema[0] = series[0]
    ema[i] = alpha * series[i] + (1 - alpha) * ema[i-1]
    """
    if not series:
        return []
    ema = [series[0]]
    for val in series[1:]:
        ema.append(alpha * val + (1.0 - alpha) * ema[-1])
    return ema


def _ema_trend_slope(ema_series: List[float], window: int = 7) -> float:
    """Estimate the trend slope of the EMA series over the last *window* points.

    Uses linear regression on the tail of the EMA series.
    Returns 0.0 for empty or single-element input.
    """
    tail = ema_series[-window:] if len(ema_series) >= window else ema_series
    slope, _ = _linear_regression(tail)
    return slope


def classify_trend(slope: float) -> str:
    """Classify trend direction from linear slope."""
    if slope > TREND_UP_THRESHOLD:
        return TREND_UP
    if slope < TREND_DOWN_THRESHOLD:
        return TREND_DOWN
    return TREND_STABLE


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ForecastResult:
    # Ensemble output
    projected_apy: float          # ensemble = 0.4*linear + 0.6*ema
    projected_apy_linear: float   # linear regression projection
    projected_apy_ema: float      # EMA projection

    confidence: float             # R² of linear fit, in [0, 1]
    trend_direction: str          # UP / STABLE / DOWN
    linear_slope: float           # slope (APY / day)

    forecast_range: Dict[str, float]   # {"min": ..., "max": ...}
    horizon_days: int
    series_length: int
    advisory: str
    computed_at: str              # ISO-8601 UTC

    def to_dict(self) -> dict:
        return {
            "computed_at": self.computed_at,
            "horizon_days": self.horizon_days,
            "series_length": self.series_length,
            "projected_apy": round(self.projected_apy, 6),
            "projected_apy_linear": round(self.projected_apy_linear, 6),
            "projected_apy_ema": round(self.projected_apy_ema, 6),
            "confidence": round(self.confidence, 6),
            "trend_direction": self.trend_direction,
            "linear_slope": round(self.linear_slope, 8),
            "forecast_range": {
                "min": round(self.forecast_range["min"], 6),
                "max": round(self.forecast_range["max"], 6),
            },
            "advisory": self.advisory,
        }


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class YieldForecastEngine(BaseAnalytics):
    """Statistical APY forecast engine.

    Usage::

        engine = YieldForecastEngine(data_dir="/abs/path/to/data")
        historical = [0.045, 0.046, 0.047, 0.048, 0.049]
        result = engine.ensemble_forecast(historical, forecast_days=7)
        engine.save(result)
    """

    OUTPUT_PATH = "data/yield_forecast_log.json"

    def __init__(self, data_dir: Optional[str] = None) -> None:
        _base = data_dir if data_dir else str(_DEFAULT_DATA_DIR)
        super().__init__(base_dir=_base)
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._log_path = self._data_dir / _LOG_FILE
        self._last_result: Optional[ForecastResult] = None

    def to_dict(self) -> dict:
        """Return last ensemble_forecast() result as JSON-serializable dict."""
        if self._last_result is None:
            return {}
        return self._last_result.to_dict()

    # ------------------------------------------------------------------
    # Core forecast methods
    # ------------------------------------------------------------------

    def linear_forecast(
        self,
        historical_apy_series: Sequence[float],
        forecast_days: int = 1,
    ) -> float:
        """Project APY using OLS linear regression.

        Returns the predicted value at index (len(series) - 1 + forecast_days).
        Returns series mean for empty or single-element series.
        """
        series = list(historical_apy_series)
        if not series:
            return 0.0
        if len(series) == 1:
            return series[0]

        slope, intercept = _linear_regression(series)
        projection_idx = float(len(series) - 1 + forecast_days)
        return intercept + slope * projection_idx

    def ema_forecast(
        self,
        historical_apy_series: Sequence[float],
        forecast_days: int = 1,
        alpha: float = EMA_ALPHA,
    ) -> float:
        """Project APY using EMA + EMA-trend extrapolation.

        EMA of the series is computed, then the trend slope of the EMA tail
        (last 7 points) is used to project forward.

        Returns 0.0 for empty series.
        Returns series[0] for single-element series.
        """
        series = list(historical_apy_series)
        if not series:
            return 0.0
        if len(series) == 1:
            return series[0]

        ema_series = _compute_ema_series(series, alpha=alpha)
        last_ema = ema_series[-1]

        # Extrapolate using EMA trend slope
        ema_slope = _ema_trend_slope(ema_series)
        return last_ema + ema_slope * forecast_days

    def ensemble_forecast(
        self,
        historical_apy_series: Sequence[float],
        forecast_days: int = 1,
    ) -> ForecastResult:
        """Weighted ensemble: 0.4 * linear + 0.6 * EMA.

        Also computes confidence (R²), trend_direction, and forecast_range.
        """
        series = list(historical_apy_series)
        n = len(series)

        if n == 0:
            result = ForecastResult(
                projected_apy=0.0,
                projected_apy_linear=0.0,
                projected_apy_ema=0.0,
                confidence=0.0,
                trend_direction=TREND_STABLE,
                linear_slope=0.0,
                forecast_range={"min": 0.0, "max": 0.0},
                horizon_days=forecast_days,
                series_length=0,
                advisory=_ADVISORY,
                computed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._last_result = result
            return result

        linear_proj = self.linear_forecast(series, forecast_days=forecast_days)
        ema_proj = self.ema_forecast(series, forecast_days=forecast_days)
        ensemble = LINEAR_WEIGHT * linear_proj + EMA_WEIGHT * ema_proj

        # Confidence = R² of the linear fit
        if n < 2:
            slope, intercept = 0.0, series[0]
            r2 = 1.0
        else:
            slope, intercept = _linear_regression(series)
            r2 = _r_squared(series, slope, intercept)

        confidence = max(0.0, min(1.0, r2))
        trend = classify_trend(slope)

        # Forecast range: [min(linear, ema), max(linear, ema)]
        fmin = min(linear_proj, ema_proj)
        fmax = max(linear_proj, ema_proj)

        result = ForecastResult(
            projected_apy=ensemble,
            projected_apy_linear=linear_proj,
            projected_apy_ema=ema_proj,
            confidence=confidence,
            trend_direction=trend,
            linear_slope=slope,
            forecast_range={"min": fmin, "max": fmax},
            horizon_days=forecast_days,
            series_length=n,
            advisory=_ADVISORY,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._last_result = result
        return result

    def forecast_confidence(
        self,
        historical_apy_series: Sequence[float],
    ) -> float:
        """Return R² of the linear fit for *historical_apy_series*.

        Returns 1.0 for flat or single-element series.
        Returns 0.0 for empty series.
        """
        series = list(historical_apy_series)
        if not series:
            return 0.0
        if len(series) < 2:
            return 1.0
        slope, intercept = _linear_regression(series)
        return max(0.0, min(1.0, _r_squared(series, slope, intercept)))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, result: ForecastResult) -> str:
        """Append *result* to ring-buffer log (cap 100). Atomic write.

        Returns absolute path of the log file.
        """
        log_path = str(self._log_path)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        existing: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(result.to_dict())

        if len(existing) > RING_BUFFER_CAP:
            existing = existing[-RING_BUFFER_CAP:]

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._data_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            os.replace(tmp_path, log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return log_path

    def load_history(self) -> List[dict]:
        """Load ring-buffer log from disk. Returns empty list on error."""
        log_path = str(self._log_path)
        if not os.path.exists(log_path):
            return []
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def linear_forecast(
    historical_apy_series: Sequence[float],
    forecast_days: int = 1,
    data_dir: Optional[str] = None,
) -> float:
    """Convenience wrapper: linear regression forecast."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.linear_forecast(historical_apy_series, forecast_days=forecast_days)


def ema_forecast(
    historical_apy_series: Sequence[float],
    forecast_days: int = 1,
    alpha: float = EMA_ALPHA,
    data_dir: Optional[str] = None,
) -> float:
    """Convenience wrapper: EMA forecast."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.ema_forecast(
        historical_apy_series, forecast_days=forecast_days, alpha=alpha
    )


def ensemble_forecast(
    historical_apy_series: Sequence[float],
    forecast_days: int = 1,
    data_dir: Optional[str] = None,
) -> ForecastResult:
    """Convenience wrapper: ensemble forecast."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.ensemble_forecast(historical_apy_series, forecast_days=forecast_days)


def forecast_confidence(
    historical_apy_series: Sequence[float],
    data_dir: Optional[str] = None,
) -> float:
    """Convenience wrapper: R² confidence."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.forecast_confidence(historical_apy_series)


def save_results(
    result: ForecastResult,
    data_dir: Optional[str] = None,
) -> str:
    """Convenience wrapper: save to ring-buffer log."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.save(result)


def load_history(data_dir: Optional[str] = None) -> List[dict]:
    """Convenience wrapper: load ring-buffer log."""
    engine = YieldForecastEngine(data_dir=data_dir)
    return engine.load_history()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_SERIES = [
    0.035, 0.036, 0.037, 0.038, 0.039,
    0.040, 0.041, 0.042, 0.043, 0.045,
    0.046, 0.047, 0.048, 0.049, 0.050,
    0.048, 0.047, 0.046, 0.047, 0.048,
    0.049, 0.050, 0.051, 0.052, 0.053,
    0.054, 0.055, 0.056, 0.057, 0.058,
]


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv or sys.argv[1:]

    run_mode = False
    data_dir: Optional[str] = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--run":
            run_mode = True
        elif arg == "--check":
            run_mode = False
        elif arg == "--data-dir" and i + 1 < len(argv):
            i += 1
            data_dir = argv[i]
        i += 1

    engine = YieldForecastEngine(data_dir=data_dir)
    result = engine.ensemble_forecast(_SAMPLE_SERIES, forecast_days=7)

    print("=" * 60)
    print("MP-769: YieldForecastEngine")
    print("=" * 60)
    print(f"Series length        : {result.series_length} days")
    print(f"Horizon              : {result.horizon_days} days")
    print(f"Projected APY (ens.) : {result.projected_apy * 100:.4f}%")
    print(f"Projected APY (lin.) : {result.projected_apy_linear * 100:.4f}%")
    print(f"Projected APY (EMA)  : {result.projected_apy_ema * 100:.4f}%")
    print(f"Confidence (R²)      : {result.confidence:.4f}")
    print(f"Trend Direction      : {result.trend_direction}")
    print(f"Linear Slope         : {result.linear_slope:.6f} APY/day")
    print(
        f"Forecast Range       : "
        f"[{result.forecast_range['min']*100:.4f}%, "
        f"{result.forecast_range['max']*100:.4f}%]"
    )

    if run_mode:
        path = engine.save(result)
        print(f"\n✅ Saved → {path}")
    else:
        print("\n(dry-run — use --run to write output)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
