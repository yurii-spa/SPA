"""
APY Forecast Engine v2 (MP-637)
================================
Upgraded multi-model APY forecasting with ensemble predictions and confidence bands.

Models:
    LINEAR                  — OLS slope extrapolation
    EXPONENTIAL_SMOOTHING   — ALPHA-weighted exponential smoother + trend projection
    MOVING_AVERAGE          — simple window mean

Ensemble: arithmetic mean of all available model outputs.
Confidence bands: ±1.5 × stdev(model predictions), clamped [0%, 50%].
Confidence label:
    stdev < 0.005  → HIGH
    stdev < 0.015  → MEDIUM
    else           → LOW
    len(history) < 3 → LOW (LINEAR only)

Output ring-buffer (30 entries): data/apy_forecast_v2.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never modifies risk/, execution/, allocator/, cycle_runner.
* Atomic writes: tmp + os.replace.
* Deterministic: identical input → identical output.
* NOT imported by risk / execution / monitoring / allocator / cycle_runner.

CLI
---
``python3 -m spa_core.analytics.apy_forecast_v2 --check``
``python3 -m spa_core.analytics.apy_forecast_v2 --run``
``python3 -m spa_core.analytics.apy_forecast_v2 --data-dir PATH``

MP-637.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_FILE = "apy_forecast_v2.json"
_RING_BUFFER_MAX = 30

ALPHA: float = 0.3           # exponential smoothing factor
HORIZONS: list[int] = [1, 7, 30, 90]  # forecast days

_MIN_APY: float = 0.0
_MAX_APY: float = 0.50       # 50%

_HIGH_THRESHOLD: float = 0.005
_MEDIUM_THRESHOLD: float = 0.015

_ADVISORY = (
    "Forecasts are statistical estimates only. Not financial advice."
)


# ---------------------------------------------------------------------------
# Enumerations / Dataclasses
# ---------------------------------------------------------------------------

class ForecastModel(str, Enum):
    LINEAR = "LINEAR"
    EXPONENTIAL_SMOOTHING = "EXPONENTIAL_SMOOTHING"
    MOVING_AVERAGE = "MOVING_AVERAGE"


@dataclass
class ForecastPoint:
    horizon_days: int
    predicted_apy: float
    lower_bound: float
    upper_bound: float
    confidence: str            # "HIGH" | "MEDIUM" | "LOW"
    model_used: ForecastModel  # ensemble model tag

    def to_dict(self) -> dict:
        return {
            "horizon_days": self.horizon_days,
            "predicted_apy": round(self.predicted_apy, 6),
            "lower_bound": round(self.lower_bound, 6),
            "upper_bound": round(self.upper_bound, 6),
            "confidence": self.confidence,
            "model_used": self.model_used.value
            if isinstance(self.model_used, ForecastModel)
            else str(self.model_used),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastPoint":
        return cls(
            horizon_days=int(d["horizon_days"]),
            predicted_apy=float(d["predicted_apy"]),
            lower_bound=float(d["lower_bound"]),
            upper_bound=float(d["upper_bound"]),
            confidence=str(d["confidence"]),
            model_used=ForecastModel(d["model_used"]),
        )


# ---------------------------------------------------------------------------
# APYForecastV2
# ---------------------------------------------------------------------------

class APYForecastV2:
    """Multi-model APY forecasting engine (advisory only)."""

    ALPHA: float = ALPHA
    HORIZONS: list[int] = HORIZONS

    def __init__(self, data_dir: str | Path = _DEFAULT_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Internal model implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _linear_forecast(history: list[float], horizon: int) -> float:
        """OLS linear regression extrapolation.

        Computes slope & intercept over index positions 0…n-1, then
        predicts at position (n-1) + horizon.
        """
        n = len(history)
        if n == 0:
            return 0.0
        if n == 1:
            return max(_MIN_APY, min(_MAX_APY, history[0]))

        xs = list(range(n))
        sum_x = sum(xs)
        sum_y = sum(history)
        sum_xy = sum(x * y for x, y in zip(xs, history))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0.0:
            return max(_MIN_APY, min(_MAX_APY, sum_y / n))

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        predicted = intercept + slope * (n - 1 + horizon)
        return max(_MIN_APY, min(_MAX_APY, predicted))

    @classmethod
    def _exponential_smoothing(cls, history: list[float], horizon: int) -> float:
        """Exponential smoothing with linear trend projection.

        s[0] = history[0]
        s[i] = ALPHA * history[i] + (1 - ALPHA) * s[i-1]
        trend = (s[-1] - s[0]) / (len - 1)   (if len > 1)
        prediction = s[-1] + trend * horizon
        """
        n = len(history)
        if n == 0:
            return 0.0
        if n == 1:
            return max(_MIN_APY, min(_MAX_APY, history[0]))

        alpha = cls.ALPHA
        smoothed = [history[0]]
        for i in range(1, n):
            s = alpha * history[i] + (1.0 - alpha) * smoothed[-1]
            smoothed.append(s)

        slope = (smoothed[-1] - smoothed[0]) / (n - 1) if n > 1 else 0.0
        predicted = smoothed[-1] + slope * horizon
        return max(_MIN_APY, min(_MAX_APY, predicted))

    @staticmethod
    def _moving_average(history: list[float], window: int = 7) -> float:
        """Simple moving average of last `window` values."""
        if not history:
            return 0.0
        recent = history[-min(window, len(history)):]
        return max(_MIN_APY, min(_MAX_APY, sum(recent) / len(recent)))

    # ------------------------------------------------------------------
    # Ensemble forecast
    # ------------------------------------------------------------------

    def forecast_adapter(
        self,
        adapter_id: str,
        history: list[float],
    ) -> list[ForecastPoint]:
        """Produce ForecastPoints for each horizon in HORIZONS."""
        points: list[ForecastPoint] = []

        for horizon in self.HORIZONS:
            if len(history) < 3:
                # Degenerate case: single model, LOW confidence
                predicted = self._linear_forecast(history, horizon)
                lower = max(_MIN_APY, predicted - 0.02)
                upper = min(_MAX_APY, predicted + 0.02)
                points.append(
                    ForecastPoint(
                        horizon_days=horizon,
                        predicted_apy=predicted,
                        lower_bound=lower,
                        upper_bound=upper,
                        confidence="LOW",
                        model_used=ForecastModel.LINEAR,
                    )
                )
                continue

            # Run all 3 models
            preds = [
                self._linear_forecast(history, horizon),
                self._exponential_smoothing(history, horizon),
                self._moving_average(history),
            ]

            mean_pred = sum(preds) / len(preds)

            # Stdev of model disagreement
            variance = sum((p - mean_pred) ** 2 for p in preds) / len(preds)
            stdev = math.sqrt(variance)

            lower = max(_MIN_APY, mean_pred - 1.5 * stdev)
            upper = min(_MAX_APY, mean_pred + 1.5 * stdev)

            if stdev < _HIGH_THRESHOLD:
                confidence = "HIGH"
            elif stdev < _MEDIUM_THRESHOLD:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            points.append(
                ForecastPoint(
                    horizon_days=horizon,
                    predicted_apy=mean_pred,
                    lower_bound=lower,
                    upper_bound=upper,
                    confidence=confidence,
                    model_used=ForecastModel.EXPONENTIAL_SMOOTHING,  # ensemble tag
                )
            )

        return points

    # ------------------------------------------------------------------
    # Report generation & persistence
    # ------------------------------------------------------------------

    def generate_report(
        self,
        apy_map: dict[str, float],
        history_map: dict[str, list[float]],
    ) -> dict:
        """Generate a full forecast report for all adapters."""
        forecasts: dict[str, list[dict]] = {}

        for adapter_id, current_apy in apy_map.items():
            history = list(history_map.get(adapter_id, [current_apy]))
            if not history:
                history = [current_apy]
            points = self.forecast_adapter(adapter_id, history)
            forecasts[adapter_id] = [p.to_dict() for p in points]

        return {
            "forecasts": forecasts,
            "advisory": _ADVISORY,
            "generated_at": _now_iso(),
        }

    def save_report(self, report: dict) -> None:
        """Atomic ring-buffer write to data/apy_forecast_v2.json."""
        out_path = self._data_dir / _OUTPUT_FILE
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Load existing ring-buffer
        existing: list[dict] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(report)
        if len(existing) > _RING_BUFFER_MAX:
            existing = existing[-_RING_BUFFER_MAX:]

        _atomic_write(out_path, existing)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_synthetic_inputs() -> tuple[dict[str, float], dict[str, list[float]]]:
    """Return minimal synthetic APY / history for CLI demo."""
    import random
    rng = random.Random(42)

    adapters = {
        "aave_v3": 0.035,
        "compound_v3": 0.048,
        "morpho_steakhouse": 0.065,
    }
    history_map: dict[str, list[float]] = {}
    for aid, base in adapters.items():
        history_map[aid] = [
            max(0.0, base + rng.gauss(0, 0.003)) for _ in range(14)
        ]
    return adapters, history_map


def _load_live_data(data_dir: Path) -> tuple[dict[str, float], dict[str, list[float]]]:
    """Attempt to load APY data from existing data files; fall back to synthetic."""
    apy_map: dict[str, float] = {}
    history_map: dict[str, list[float]] = {}

    # Try yield_forecast.json for current snapshot
    yf_path = data_dir / "yield_forecast.json"
    if yf_path.exists():
        try:
            with open(yf_path, "r", encoding="utf-8") as fh:
                ring = json.load(fh)
            if isinstance(ring, list) and ring:
                latest = ring[-1]
                for adapter_id, info in latest.get("adapters", {}).items():
                    if isinstance(info, dict):
                        apy = info.get("current_apy")
                        if isinstance(apy, (int, float)):
                            apy_map[adapter_id] = float(apy)
                            # Build history from ring
                            hist = []
                            for entry in ring:
                                a_info = entry.get("adapters", {}).get(adapter_id, {})
                                v = a_info.get("current_apy")
                                if isinstance(v, (int, float)):
                                    hist.append(float(v))
                            history_map[adapter_id] = hist
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    if not apy_map:
        apy_map, history_map = _build_synthetic_inputs()

    return apy_map, history_map


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv

    data_dir = _DEFAULT_DATA_DIR
    do_run = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--run":
            do_run = True
        elif arg == "--check":
            do_run = False
        elif arg == "--data-dir" and i + 1 < len(args):
            i += 1
            data_dir = Path(args[i])
        i += 1

    engine = APYForecastV2(data_dir=data_dir)
    apy_map, history_map = _load_live_data(Path(data_dir))
    report = engine.generate_report(apy_map, history_map)

    print(json.dumps(report, indent=2))

    if do_run:
        engine.save_report(report)
        out = Path(data_dir) / _OUTPUT_FILE
        print(f"\n[apy_forecast_v2] Saved → {out}", file=sys.stderr)
    else:
        print("\n[apy_forecast_v2] --check mode: no file written.", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main()
