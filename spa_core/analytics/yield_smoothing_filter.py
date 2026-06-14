"""
MP-737: YieldSmoothingFilter
Applies smoothing filters (EMA, SMA, outlier rejection) to raw APY data to
produce stable yield estimates, filtering temporary spikes and noise.

Advisory/read-only. Pure stdlib only. Atomic JSON writes (tmp + os.replace).
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

DATA_FILE = Path("data/yield_smoothing_log.json")
MAX_ENTRIES = 100


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SmoothedYield:
    protocol: str
    asset: str

    raw_apy_series: List[float]

    sma_7: float     # simple moving average, window 7
    sma_14: float    # simple moving average, window 14
    ema_7: float     # exponential moving average, alpha=2/(7+1)
    ema_14: float    # exponential moving average, alpha=2/(14+1)

    cleaned_series: List[float]   # outliers replaced by median
    cleaned_avg: float            # mean of cleaned_series

    spike_count: int
    spike_indices: List[int]

    coefficient_of_variation: float  # std/mean*100 (lower = more stable)
    stability_label: str             # STABLE (<10%) | MODERATE (10-25%) | VOLATILE (>25%)

    recommended_yield: float   # ema_7 if spike_count > 2 else cleaned_avg
    confidence: str            # HIGH | MEDIUM | LOW


@dataclass
class YieldSmoothingResult:
    smoothed: List[SmoothedYield]

    most_stable_protocol: str
    most_volatile_protocol: str
    avg_spike_rate: float

    saved_to: str


# ──────────────────────────────────────────────────────────────────────────────
# Pure-computation helpers
# ──────────────────────────────────────────────────────────────────────────────

def compute_sma(series: List[float], window: int) -> float:
    """Simple moving average of the last `window` values. 0 if empty."""
    if not series:
        return 0.0
    window = max(1, window)
    subset = series[-window:]
    return sum(subset) / len(subset)


def compute_ema(series: List[float], window: int) -> float:
    """
    Exponential moving average with alpha = 2 / (window + 1).
    Starts with first value; iterates through the whole series.
    Returns 0 if empty.
    """
    if not series:
        return 0.0
    alpha = 2.0 / (window + 1)
    ema = series[0]
    for value in series[1:]:
        ema = alpha * value + (1.0 - alpha) * ema
    return ema


def _mean(series: List[float]) -> float:
    """Arithmetic mean; 0 if empty."""
    if not series:
        return 0.0
    return sum(series) / len(series)


def _std(series: List[float]) -> float:
    """Population standard deviation; 0 if fewer than 2 values."""
    if len(series) < 2:
        return 0.0
    mu = _mean(series)
    variance = sum((x - mu) ** 2 for x in series) / len(series)
    return math.sqrt(variance)


def _median(series: List[float]) -> float:
    """Median of series; 0 if empty."""
    if not series:
        return 0.0
    s = sorted(series)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def detect_outliers(series: List[float]) -> Tuple[List[int], List[float]]:
    """
    Flag data points more than 2 std devs from the mean as outliers.

    Returns:
        (outlier_indices, cleaned_series)
        cleaned_series replaces outliers with the median of the original series.
    """
    if not series:
        return [], []

    mu = _mean(series)
    sigma = _std(series)
    med = _median(series)

    indices: List[int] = []
    cleaned: List[float] = []

    for i, x in enumerate(series):
        if sigma > 0 and abs(x - mu) > 2.0 * sigma:
            indices.append(i)
            cleaned.append(med)
        else:
            cleaned.append(x)

    return indices, cleaned


def compute_cv(series: List[float]) -> float:
    """Coefficient of variation = std / mean * 100. Returns 0 if mean == 0."""
    mu = _mean(series)
    if mu == 0.0:
        return 0.0
    sigma = _std(series)
    return (sigma / abs(mu)) * 100.0


def _stability_label(cv: float) -> str:
    """STABLE (<10%) | MODERATE (10-25%) | VOLATILE (>25%)."""
    if cv < 10.0:
        return "STABLE"
    if cv <= 25.0:
        return "MODERATE"
    return "VOLATILE"


def _confidence(cv: float, spike_count: int) -> str:
    """HIGH if CV<10 and no spikes; LOW if CV>25 and spikes>2; else MEDIUM."""
    if cv < 10.0 and spike_count == 0:
        return "HIGH"
    if cv > 25.0 and spike_count > 2:
        return "LOW"
    return "MEDIUM"


def smooth_protocol(
    protocol: str,
    asset: str,
    raw_series: List[float],
) -> SmoothedYield:
    """Compute all smoothing metrics for a single protocol APY series."""
    sma7 = compute_sma(raw_series, 7)
    sma14 = compute_sma(raw_series, 14)
    ema7 = compute_ema(raw_series, 7)
    ema14 = compute_ema(raw_series, 14)

    spike_indices, cleaned = detect_outliers(raw_series)
    spike_count = len(spike_indices)
    cleaned_avg = _mean(cleaned)

    cv = compute_cv(raw_series)
    stab = _stability_label(cv)
    conf = _confidence(cv, spike_count)

    recommended = ema7 if spike_count > 2 else cleaned_avg

    return SmoothedYield(
        protocol=protocol,
        asset=asset,
        raw_apy_series=list(raw_series),
        sma_7=sma7,
        sma_14=sma14,
        ema_7=ema7,
        ema_14=ema14,
        cleaned_series=cleaned,
        cleaned_avg=cleaned_avg,
        spike_count=spike_count,
        spike_indices=spike_indices,
        coefficient_of_variation=cv,
        stability_label=stab,
        recommended_yield=recommended,
        confidence=conf,
    )


def smooth_all(protocol_data: List[dict]) -> "YieldSmoothingResult":
    """
    Smooth multiple protocols.

    Each dict in protocol_data must have: protocol, asset, apy_series (List[float]).
    Returns a YieldSmoothingResult.
    """
    smoothed = [
        smooth_protocol(
            protocol=d["protocol"],
            asset=d["asset"],
            raw_series=list(d["apy_series"]),
        )
        for d in protocol_data
    ]

    if smoothed:
        most_stable = min(smoothed, key=lambda s: s.coefficient_of_variation).protocol
        most_volatile = max(smoothed, key=lambda s: s.coefficient_of_variation).protocol
        avg_spike_rate = sum(s.spike_count for s in smoothed) / len(smoothed)
    else:
        most_stable = ""
        most_volatile = ""
        avg_spike_rate = 0.0

    return YieldSmoothingResult(
        smoothed=smoothed,
        most_stable_protocol=most_stable,
        most_volatile_protocol=most_volatile,
        avg_spike_rate=avg_spike_rate,
        saved_to=str(DATA_FILE),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Persistence (ring-buffer, atomic write)
# ──────────────────────────────────────────────────────────────────────────────

def _result_to_dict(result: YieldSmoothingResult) -> dict:
    """Serialise YieldSmoothingResult to a JSON-safe dict."""
    smoothed_list = []
    for s in result.smoothed:
        smoothed_list.append({
            "protocol": s.protocol,
            "asset": s.asset,
            "raw_apy_series": s.raw_apy_series,
            "sma_7": s.sma_7,
            "sma_14": s.sma_14,
            "ema_7": s.ema_7,
            "ema_14": s.ema_14,
            "cleaned_series": s.cleaned_series,
            "cleaned_avg": s.cleaned_avg,
            "spike_count": s.spike_count,
            "spike_indices": s.spike_indices,
            "coefficient_of_variation": s.coefficient_of_variation,
            "stability_label": s.stability_label,
            "recommended_yield": s.recommended_yield,
            "confidence": s.confidence,
        })
    return {
        "timestamp": time.time(),
        "smoothed": smoothed_list,
        "most_stable_protocol": result.most_stable_protocol,
        "most_volatile_protocol": result.most_volatile_protocol,
        "avg_spike_rate": result.avg_spike_rate,
        "saved_to": result.saved_to,
    }


def save_results(
    result: YieldSmoothingResult,
    data_file: Path = DATA_FILE,
) -> None:
    """Append result to ring-buffer JSON file (max MAX_ENTRIES). Atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    history = load_history(data_file)
    history.append(_result_to_dict(result))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]

    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load ring-buffer list from disk; returns [] if file missing or invalid."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        text = data_file.read_text().strip()
        if not text:
            return []
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return []


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry-point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-737 YieldSmoothingFilter")
    parser.add_argument("--check", action="store_true", default=True,
                        help="Compute and print; no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute + save to data file")
    parser.add_argument("--data-dir", default="data",
                        help="Directory for output JSON")
    args = parser.parse_args()

    sample = [
        {
            "protocol": "Aave V3",
            "asset": "USDC",
            "apy_series": [3.2, 3.5, 3.4, 3.6, 20.0, 3.3, 3.7, 3.5, 3.4, 3.6],
        },
        {
            "protocol": "Compound V3",
            "asset": "USDC",
            "apy_series": [4.8, 4.9, 4.7, 4.8, 4.9, 5.0, 4.8, 4.9, 4.7, 4.8],
        },
        {
            "protocol": "Morpho Steakhouse",
            "asset": "USDC",
            "apy_series": [6.0, 6.5, 7.2, 5.8, 40.0, 6.3, 6.8, 5.9, 6.1, 6.4],
        },
    ]

    result = smooth_all(sample)
    print(f"Most stable:   {result.most_stable_protocol}")
    print(f"Most volatile: {result.most_volatile_protocol}")
    print(f"Avg spike rate: {result.avg_spike_rate:.1f}")
    for s in result.smoothed:
        print(
            f"  [{s.stability_label}] {s.protocol}: "
            f"recommended={s.recommended_yield:.2f}%, CV={s.coefficient_of_variation:.1f}%, "
            f"spikes={s.spike_count}, conf={s.confidence}"
        )

    if args.run:
        out_file = Path(args.data_dir) / "yield_smoothing_log.json"
        result.saved_to = str(out_file)
        save_results(result, data_file=out_file)
        print(f"Saved → {out_file}")
