"""
MP-710: YieldMomentumTracker
Tracks short-term yield momentum across DeFi pools to identify trending vs
fading opportunities. Advisory/read-only, pure stdlib, atomic JSON writes.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/yield_momentum_log.json")
MAX_ENTRIES = 100


@dataclass
class MomentumSnapshot:
    timestamp_iso: str
    apy: float


@dataclass
class MomentumReport:
    protocol: str
    pool: str
    snapshots: List[MomentumSnapshot]   # at least 2, oldest first

    # Moving averages
    ma7: float      # 7-period simple moving average (or all if fewer than 7)
    ma14: float     # 14-period simple moving average
    ma30: float     # 30-period simple moving average

    # Momentum indicators
    roc_7: float    # Rate of Change over last 7 periods (%)
    roc_30: float   # Rate of Change over 30 periods (%)
    trend_slope: float  # linear regression slope of last 14 APY values

    # Signals
    momentum_signal: str    # STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL
    trend_direction: str    # UPTREND | DOWNTREND | SIDEWAYS
    crossover_signal: str   # GOLDEN_CROSS | DEATH_CROSS | MIXED

    current_apy: float
    apy_percentile: float   # 0–100

    warnings: List[str]
    saved_to: str


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def simple_ma(values: List[float], period: int) -> float:
    """Average of last `period` values; if fewer, use all."""
    if not values:
        return 0.0
    window = values[-period:] if len(values) >= period else values
    return sum(window) / len(window)


def rate_of_change(values: List[float], period: int) -> float:
    """(last - values[-period-1]) / values[-period-1] * 100.
    Returns 0 if not enough data or denominator is 0."""
    if len(values) < period + 1:
        return 0.0
    base = values[-period - 1]
    if base == 0:
        return 0.0
    return (values[-1] - base) / base * 100.0


def linear_slope(values: List[float]) -> float:
    """Least-squares slope of values (use last 14 or all if fewer).
    slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²); returns 0 if denominator=0."""
    window = values[-14:] if len(values) >= 14 else values
    n = len(window)
    if n < 2:
        return 0.0
    xs = list(range(n))
    sum_x = sum(xs)
    sum_y = sum(window)
    sum_xy = sum(x * y for x, y in zip(xs, window))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def apy_percentile(current: float, all_apys: List[float]) -> float:
    """Percent of historical values <= current (0–100)."""
    if not all_apys:
        return 0.0
    count = sum(1 for a in all_apys if a <= current)
    return count / len(all_apys) * 100.0


# ---------------------------------------------------------------------------
# Signal derivation helpers
# ---------------------------------------------------------------------------

def _crossover_signal(ma7: float, ma14: float, ma30: float) -> str:
    if ma7 > ma14 > ma30:
        return "GOLDEN_CROSS"
    if ma7 < ma14 < ma30:
        return "DEATH_CROSS"
    return "MIXED"


def _trend_direction(slope: float) -> str:
    if slope > 0.1:
        return "UPTREND"
    if slope < -0.1:
        return "DOWNTREND"
    return "SIDEWAYS"


def _momentum_signal(roc_7: float, crossover: str, trend_dir: str) -> str:
    if roc_7 > 10 and crossover == "GOLDEN_CROSS":
        return "STRONG_BUY"
    if roc_7 > 3 or (crossover == "GOLDEN_CROSS" and trend_dir == "UPTREND"):
        return "BUY"
    if roc_7 < -10 and crossover == "DEATH_CROSS":
        return "STRONG_SELL"
    if roc_7 < -3 or (crossover == "DEATH_CROSS" and trend_dir == "DOWNTREND"):
        return "SELL"
    return "NEUTRAL"


def _build_warnings(roc_7: float, pct: float) -> List[str]:
    warnings: List[str] = []
    if pct < 20:
        warnings.append("APY near historical low")
    if pct > 80:
        warnings.append("APY near historical high (may revert)")
    if roc_7 > 30:
        warnings.append("extreme positive momentum (unsustainable?)")
    if roc_7 < -30:
        warnings.append("sharp decline")
    return warnings


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    pool: str,
    snapshots: List[MomentumSnapshot],
    data_file: Path = DATA_FILE,
) -> MomentumReport:
    """Compute a full MomentumReport from a list of MomentumSnapshot objects."""
    apys = [s.apy for s in snapshots]

    ma7_val = simple_ma(apys, 7)
    ma14_val = simple_ma(apys, 14)
    ma30_val = simple_ma(apys, 30)

    roc_7_val = rate_of_change(apys, 7)
    roc_30_val = rate_of_change(apys, 30)

    slope_window = apys[-14:] if len(apys) >= 14 else apys
    slope_val = linear_slope(slope_window)

    cross = _crossover_signal(ma7_val, ma14_val, ma30_val)
    trend_dir = _trend_direction(slope_val)
    signal = _momentum_signal(roc_7_val, cross, trend_dir)

    current = apys[-1] if apys else 0.0
    pct = apy_percentile(current, apys)

    warns = _build_warnings(roc_7_val, pct)

    return MomentumReport(
        protocol=protocol,
        pool=pool,
        snapshots=snapshots,
        ma7=ma7_val,
        ma14=ma14_val,
        ma30=ma30_val,
        roc_7=roc_7_val,
        roc_30=roc_30_val,
        trend_slope=slope_val,
        momentum_signal=signal,
        trend_direction=trend_dir,
        crossover_signal=cross,
        current_apy=current,
        apy_percentile=pct,
        warnings=warns,
        saved_to=str(data_file),
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_momentum(reports: List[MomentumReport]) -> List[MomentumReport]:
    """Return reports sorted by roc_7 descending (best momentum first)."""
    return sorted(reports, key=lambda r: r.roc_7, reverse=True)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _report_to_dict(report: MomentumReport) -> Dict[str, Any]:
    return {
        "protocol": report.protocol,
        "pool": report.pool,
        "snapshots": [{"timestamp_iso": s.timestamp_iso, "apy": s.apy}
                      for s in report.snapshots],
        "ma7": report.ma7,
        "ma14": report.ma14,
        "ma30": report.ma30,
        "roc_7": report.roc_7,
        "roc_30": report.roc_30,
        "trend_slope": report.trend_slope,
        "momentum_signal": report.momentum_signal,
        "trend_direction": report.trend_direction,
        "crossover_signal": report.crossover_signal,
        "current_apy": report.current_apy,
        "apy_percentile": report.apy_percentile,
        "warnings": report.warnings,
        "saved_to": report.saved_to,
        "_saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def save_results(report: MomentumReport, data_file: Path = DATA_FILE) -> None:
    """Append report to ring-buffer JSON file (max MAX_ENTRIES entries). Atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    existing: List[Dict[str, Any]] = []
    if data_file.exists():
        try:
            with open(data_file) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(_report_to_dict(report))
    # Ring-buffer: keep last MAX_ENTRIES
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = data_file.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> List[Dict[str, Any]]:
    """Load saved report history from JSON file."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Demo: generate a synthetic series and analyze it
    import math
    now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    snapshots = [
        MomentumSnapshot(
            timestamp_iso=f"2026-05-{i+1:02d}T00:00:00Z",
            apy=5.0 + math.sin(i / 3.0) * 2.0 + i * 0.05,
        )
        for i in range(30)
    ]

    report = analyze("Aave V3", "USDC", snapshots)
    print(f"Protocol : {report.protocol}")
    print(f"Pool     : {report.pool}")
    print(f"Signal   : {report.momentum_signal}")
    print(f"Trend    : {report.trend_direction}")
    print(f"Crossover: {report.crossover_signal}")
    print(f"MA7/14/30: {report.ma7:.2f} / {report.ma14:.2f} / {report.ma30:.2f}")
    print(f"ROC 7/30 : {report.roc_7:.2f}% / {report.roc_30:.2f}%")
    print(f"Slope    : {report.trend_slope:.4f}")
    print(f"Percentile: {report.apy_percentile:.1f}%")
    print(f"Warnings : {report.warnings}")
