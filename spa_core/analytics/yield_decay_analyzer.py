"""
Yield Decay Analyzer (MP-761)
==============================

Analyzes how DeFi yields decay over time as capital flows in and rates
normalize. Detects yield decay patterns, predicts future APY trends, and
flags when current high yields are likely temporary.

Design constraints:
* Pure stdlib only — no numpy/scipy/requests/pandas.
* Atomic writes: tmp + os.replace (POSIX-safe).
* Advisory / read-only analytics — never modifies allocator/risk/execution.
* Deterministic: identical input → identical output.
* Ring-buffer JSON: MAX_ENTRIES = 100.

CLI:
    python3 -m spa_core.analytics.yield_decay_analyzer --check  (default)
    python3 -m spa_core.analytics.yield_decay_analyzer --run    (+ atomic save)
    python3 -m spa_core.analytics.yield_decay_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ENTRIES = 100
DEFAULT_FLOOR_APY = 2.0

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "yield_decay_log.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DecayAnalysis:
    protocol: str
    asset: str
    apy_series: List[float]     # historical APY snapshots (oldest first)

    # Basic decay metrics
    first_apy: float            # apy_series[0]
    latest_apy: float           # apy_series[-1]
    peak_apy: float             # max(apy_series)

    # Decay from peak
    decay_from_peak_pct: float  # (peak - latest) / peak * 100 if peak > 0 else 0

    # Trend half-averages
    first_half_avg: float
    second_half_avg: float
    trend_direction: str        # DECAYING | STABLE | GROWING

    # Decay velocity: average APY change per period (positive = decaying)
    decay_velocity: float

    # Estimated periods until APY hits floor_apy
    floor_apy: float            # default 2.0%
    periods_to_floor: float     # float("inf") if stable/growing

    # Inflation detection
    is_likely_inflated: bool    # peak>3*latest OR (peak>20 AND decay>50%)

    decay_label: str            # STABLE | MILD_DECAY | MODERATE_DECAY | SEVERE_DECAY
    recommendation: str


@dataclass
class DecayResult:
    analyses: List[DecayAnalysis] = field(default_factory=list)

    most_stable_protocol: str = ""    # min decay_from_peak_pct
    most_decayed_protocol: str = ""   # max decay_from_peak_pct

    avg_decay_from_peak_pct: float = 0.0

    inflated_count: int = 0           # is_likely_inflated=True

    market_decay_label: str = ""      # STABLE_MARKET | NORMALIZING | DECLINING
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_half_avgs(series: List[float]) -> Tuple[float, float]:
    """Split series into two halves and return (first_avg, second_avg)."""
    n = len(series)
    mid = n // 2
    if mid == 0:
        # Single element — both halves are the same
        first_half = series[:1]
        second_half = series[-1:]
    else:
        first_half = series[:mid]
        second_half = series[mid:]
    return _mean(first_half), _mean(second_half)


def trend_direction(first_avg: float, second_avg: float) -> str:
    """DECAYING if second < first*0.9; GROWING if second > first*1.1; else STABLE."""
    if first_avg == 0:
        return "STABLE"
    if second_avg < first_avg * 0.9:
        return "DECAYING"
    if second_avg > first_avg * 1.1:
        return "GROWING"
    return "STABLE"


def decay_velocity(series: List[float]) -> float:
    """Average APY change per period. Positive = decaying, negative = growing."""
    if len(series) <= 1:
        return 0.0
    return (series[0] - series[-1]) / (len(series) - 1)


def periods_to_floor(latest: float, velocity: float, floor: float = DEFAULT_FLOOR_APY) -> float:
    """Estimated periods until latest APY hits floor_apy.
    Returns inf if stable/growing or already at/below floor."""
    if velocity <= 0 or latest <= floor:
        return float("inf")
    return (latest - floor) / velocity


def _decay_label_from_pct(decay_from_peak_pct: float) -> str:
    """STABLE | MILD_DECAY (0-20%) | MODERATE_DECAY (20-50%) | SEVERE_DECAY (>50%)."""
    if decay_from_peak_pct <= 0:
        return "STABLE"
    if decay_from_peak_pct < 20.0:
        return "MILD_DECAY"
    if decay_from_peak_pct <= 50.0:
        return "MODERATE_DECAY"
    return "SEVERE_DECAY"


def _is_likely_inflated(peak_apy: float, latest_apy: float, decay_pct: float) -> bool:
    """True if (peak > 3*latest and latest > 0) OR (peak > 20 and decay > 50%)."""
    cond1 = (latest_apy > 0) and (peak_apy > 3 * latest_apy)
    cond2 = (peak_apy > 20.0) and (decay_pct > 50.0)
    return cond1 or cond2


def _recommendation_for_label(label: str) -> str:
    mapping = {
        "SEVERE_DECAY": "Significant yield decay detected. Consider rotating to higher-yield alternatives.",
        "MODERATE_DECAY": "Moderate decay. Monitor and prepare rotation strategy.",
        "MILD_DECAY": "Mild decay. Current yield still competitive.",
        "STABLE": "Yield stable. No action required.",
    }
    return mapping.get(label, "No recommendation available.")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    asset: str,
    apy_series: List[float],
    floor_apy: float = DEFAULT_FLOOR_APY,
) -> DecayAnalysis:
    """Analyze yield decay for a single protocol/asset."""
    if not apy_series:
        apy_series = [0.0]

    first_apy = apy_series[0]
    latest_apy = apy_series[-1]
    peak_apy = max(apy_series)

    decay_from_peak = (
        (peak_apy - latest_apy) / peak_apy * 100.0
        if peak_apy > 0 else 0.0
    )

    first_avg, second_avg = compute_half_avgs(apy_series)
    trend = trend_direction(first_avg, second_avg)
    vel = decay_velocity(apy_series)
    ptf = periods_to_floor(latest_apy, vel, floor=floor_apy)

    inflated = _is_likely_inflated(peak_apy, latest_apy, decay_from_peak)
    label = _decay_label_from_pct(decay_from_peak)
    recommendation = _recommendation_for_label(label)

    return DecayAnalysis(
        protocol=protocol,
        asset=asset,
        apy_series=list(apy_series),
        first_apy=first_apy,
        latest_apy=latest_apy,
        peak_apy=peak_apy,
        decay_from_peak_pct=decay_from_peak,
        first_half_avg=first_avg,
        second_half_avg=second_avg,
        trend_direction=trend,
        decay_velocity=vel,
        floor_apy=floor_apy,
        periods_to_floor=ptf,
        is_likely_inflated=inflated,
        decay_label=label,
        recommendation=recommendation,
    )


def analyze_market(
    protocols_data: List[Dict],
    floor_apy: float = DEFAULT_FLOOR_APY,
) -> DecayResult:
    """Analyze multiple protocols and summarise market-level decay.

    protocols_data: list of dicts with keys: protocol, asset, apy_series
    """
    analyses: List[DecayAnalysis] = []
    for item in protocols_data:
        a = analyze(
            protocol=item.get("protocol", "unknown"),
            asset=item.get("asset", "unknown"),
            apy_series=item.get("apy_series", [0.0]),
            floor_apy=floor_apy,
        )
        analyses.append(a)

    if not analyses:
        return DecayResult(
            market_decay_label="STABLE_MARKET",
            recommendation_summary="No data.",
            saved_to="",
        )

    most_stable = min(analyses, key=lambda a: a.decay_from_peak_pct)
    most_decayed = max(analyses, key=lambda a: a.decay_from_peak_pct)
    avg_decay = _mean([a.decay_from_peak_pct for a in analyses])
    inflated_count = sum(1 for a in analyses if a.is_likely_inflated)

    # Market label
    if avg_decay < 10.0:
        market_label = "STABLE_MARKET"
        market_rec = "Market yields are stable overall."
    elif avg_decay <= 30.0:
        market_label = "NORMALIZING"
        market_rec = "Yields normalizing across market. Monitor for further compression."
    else:
        market_label = "DECLINING"
        market_rec = "Broad yield decline detected. Review portfolio allocation."

    return DecayResult(
        analyses=analyses,
        most_stable_protocol=most_stable.protocol,
        most_decayed_protocol=most_decayed.protocol,
        avg_decay_from_peak_pct=avg_decay,
        inflated_count=inflated_count,
        market_decay_label=market_label,
        recommendation_summary=market_rec,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=_json_default)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _json_default(obj):
    if isinstance(obj, float) and math.isinf(obj):
        return "Infinity"
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _analysis_to_dict(a: DecayAnalysis) -> dict:
    return {
        "protocol": a.protocol,
        "asset": a.asset,
        "apy_series": a.apy_series,
        "first_apy": a.first_apy,
        "latest_apy": a.latest_apy,
        "peak_apy": a.peak_apy,
        "decay_from_peak_pct": a.decay_from_peak_pct,
        "first_half_avg": a.first_half_avg,
        "second_half_avg": a.second_half_avg,
        "trend_direction": a.trend_direction,
        "decay_velocity": a.decay_velocity,
        "floor_apy": a.floor_apy,
        "periods_to_floor": a.periods_to_floor if not math.isinf(a.periods_to_floor) else "Infinity",
        "is_likely_inflated": a.is_likely_inflated,
        "decay_label": a.decay_label,
        "recommendation": a.recommendation,
    }


def _result_to_dict(result: DecayResult) -> dict:
    return {
        "analyses": [_analysis_to_dict(a) for a in result.analyses],
        "most_stable_protocol": result.most_stable_protocol,
        "most_decayed_protocol": result.most_decayed_protocol,
        "avg_decay_from_peak_pct": result.avg_decay_from_peak_pct,
        "inflated_count": result.inflated_count,
        "market_decay_label": result.market_decay_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(result: DecayResult, data_dir: Optional[Path] = None) -> DecayResult:
    """Append result to ring-buffer JSON (cap MAX_ENTRIES). Returns updated result."""
    path = (data_dir / DATA_FILE.name) if data_dir else DATA_FILE
    existing: list = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    entry = _result_to_dict(result)
    entry["saved_to"] = str(path)
    existing.append(entry)
    # Ring-buffer
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    _atomic_write(path, existing)
    result.saved_to = str(path)
    return result


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load saved decay analysis history."""
    path = (data_dir / DATA_FILE.name) if data_dir else DATA_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEMO_PROTOCOLS = [
    {
        "protocol": "aave_v3",
        "asset": "USDC",
        "apy_series": [8.0, 7.5, 7.0, 6.5, 6.2, 5.8, 5.5, 5.2, 4.9, 4.5],
    },
    {
        "protocol": "compound_v3",
        "asset": "USDC",
        "apy_series": [6.0, 5.8, 5.7, 5.6, 5.5, 5.4, 5.3, 5.2, 5.1, 5.0],
    },
    {
        "protocol": "morpho",
        "asset": "USDC",
        "apy_series": [25.0, 20.0, 15.0, 10.0, 8.0, 7.0, 6.5, 6.0, 5.5, 5.0],
    },
]


def _print_result(result: DecayResult) -> None:
    print(f"\n{'='*65}")
    print("YIELD DECAY ANALYSIS — MP-761")
    print(f"{'='*65}")
    for a in result.analyses:
        ptf_str = f"{a.periods_to_floor:.1f}" if not math.isinf(a.periods_to_floor) else "∞"
        print(
            f"  {a.protocol:<20} {a.decay_label:<18} "
            f"decay={a.decay_from_peak_pct:5.1f}%  "
            f"trend={a.trend_direction}  "
            f"floors_in={ptf_str}  "
            f"inflated={a.is_likely_inflated}"
        )
    print(f"\nMost stable  : {result.most_stable_protocol}")
    print(f"Most decayed : {result.most_decayed_protocol}")
    print(f"Avg decay    : {result.avg_decay_from_peak_pct:.1f}%")
    print(f"Inflated     : {result.inflated_count}")
    print(f"Market label : {result.market_decay_label}")
    print(f"Summary      : {result.recommendation_summary}")
    if result.saved_to:
        print(f"\nSaved to: {result.saved_to}")


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Yield Decay Analyzer MP-761")
    parser.add_argument("--check", action="store_true", default=False,
                        help="Compute and print without saving (default)")
    parser.add_argument("--run", action="store_true", default=False,
                        help="Compute and save to data file")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Override data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else None

    result = analyze_market(_DEMO_PROTOCOLS)
    _print_result(result)

    if args.run:
        result = save_results(result, data_dir=data_dir)
        print(f"\nSaved to: {result.saved_to}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
