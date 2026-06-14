"""
MP-691: APYPredictionInterval
Compute statistical prediction intervals for future APY values using
historical data. Provides confidence bands for planning purposes.

Pure stdlib, read-only advisory module.
"""
from dataclasses import dataclass
from typing import List, Optional
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/apy_prediction_log.json")
MAX_ENTRIES = 100

# Normal distribution z-scores
Z_80 = 1.282
Z_95 = 1.960


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class APYHistoricalData:
    protocol: str
    apy_series: List[float]   # historical APY values (e.g. daily observations)
    forecast_horizon: int     # how many periods forward to predict


@dataclass
class APYPrediction:
    protocol: str
    current_apy: float        # last value in series
    mean_apy: float
    std_apy: float
    forecast_mean: float      # simple forecast = historical mean (naive model)
    lower_80: float           # 80% prediction interval lower bound
    upper_80: float           # 80% prediction interval upper bound
    lower_95: float           # 95% prediction interval lower bound
    upper_95: float           # 95% prediction interval upper bound
    trend: str                # RISING / FALLING / FLAT
    confidence: str           # HIGH / MEDIUM / LOW
    interpretation: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _population_std(values: List[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _trend(series: List[float]) -> str:
    """
    Determine trend based on last 7 vs prior 7.
    If len < 14: FLAT.
    """
    if len(series) < 14:
        return "FLAT"
    last7 = series[-7:]
    prior7 = series[-14:-7]
    last7_mean = _mean(last7)
    prior7_mean = _mean(prior7)
    if prior7_mean == 0:
        return "FLAT"
    if last7_mean > prior7_mean * 1.05:
        return "RISING"
    if last7_mean < prior7_mean * 0.95:
        return "FALLING"
    return "FLAT"


def _confidence(series: List[float]) -> str:
    n = len(series)
    if n >= 30:
        return "HIGH"
    if n >= 7:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Core: predict
# ---------------------------------------------------------------------------

def predict(data: APYHistoricalData) -> APYPrediction:
    """Compute APYPrediction from APYHistoricalData."""
    series = data.apy_series

    if not series:
        # Graceful empty-series handling
        return APYPrediction(
            protocol=data.protocol,
            current_apy=0.0,
            mean_apy=0.0,
            std_apy=0.0,
            forecast_mean=0.0,
            lower_80=0.0,
            upper_80=0.0,
            lower_95=0.0,
            upper_95=0.0,
            trend="FLAT",
            confidence="LOW",
            interpretation=(
                f"Protocol {data.protocol}: expected APY 0.00% "
                f"(80%CI: 0.00–0.00%). Trend: FLAT. Confidence: LOW."
            ),
        )

    current_apy = series[-1]
    mean_apy = _mean(series)
    std_apy = _population_std(series)
    forecast_mean = mean_apy  # naive mean-reversion model

    lower_80 = max(0.0, forecast_mean - Z_80 * std_apy)
    upper_80 = forecast_mean + Z_80 * std_apy
    lower_95 = max(0.0, forecast_mean - Z_95 * std_apy)
    upper_95 = forecast_mean + Z_95 * std_apy

    trend = _trend(series)
    confidence = _confidence(series)

    interpretation = (
        f"Protocol {data.protocol}: expected APY {forecast_mean:.2f}% "
        f"(80%CI: {lower_80:.2f}–{upper_80:.2f}%). "
        f"Trend: {trend}. Confidence: {confidence}."
    )

    return APYPrediction(
        protocol=data.protocol,
        current_apy=current_apy,
        mean_apy=mean_apy,
        std_apy=std_apy,
        forecast_mean=forecast_mean,
        lower_80=lower_80,
        upper_80=upper_80,
        lower_95=lower_95,
        upper_95=upper_95,
        trend=trend,
        confidence=confidence,
        interpretation=interpretation,
    )


def predict_batch(data_list: List[APYHistoricalData]) -> List[APYPrediction]:
    """Predict for a list of APYHistoricalData objects."""
    return [predict(d) for d in data_list]


def compare_protocols(predictions: List[APYPrediction]) -> List[APYPrediction]:
    """Return predictions sorted by forecast_mean descending."""
    return sorted(predictions, key=lambda p: p.forecast_mean, reverse=True)


# ---------------------------------------------------------------------------
# Persistence: ring-buffer JSON
# ---------------------------------------------------------------------------

def _prediction_to_dict(pred: APYPrediction) -> dict:
    return {
        "protocol": pred.protocol,
        "current_apy": pred.current_apy,
        "mean_apy": pred.mean_apy,
        "std_apy": pred.std_apy,
        "forecast_mean": pred.forecast_mean,
        "lower_80": pred.lower_80,
        "upper_80": pred.upper_80,
        "lower_95": pred.lower_95,
        "upper_95": pred.upper_95,
        "trend": pred.trend,
        "confidence": pred.confidence,
        "interpretation": pred.interpretation,
        "saved_at": time.time(),
    }


def save_results(predictions: List[APYPrediction], data_file: Path = DATA_FILE) -> None:
    """Append predictions to ring-buffer JSON file (atomic write)."""
    history = load_history(data_file)
    for pred in predictions:
        history.append(_prediction_to_dict(pred))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    data_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load history from JSON file; return [] if missing or corrupt."""
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-691 APYPredictionInterval")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute and write to data file")
    parser.add_argument("--data-dir", default="data", help="Override data directory")
    args = parser.parse_args()

    df = Path(args.data_dir) / "apy_prediction_log.json"

    demo = APYHistoricalData(protocol="demo", apy_series=[], forecast_horizon=7)
    pred = predict(demo)
    print(json.dumps(_prediction_to_dict(pred), indent=2))

    if args.run:
        save_results([pred], data_file=df)
        print(f"Saved to {df}")
