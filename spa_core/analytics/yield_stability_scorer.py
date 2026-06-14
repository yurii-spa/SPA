"""
MP-745: YieldStabilityScorer

Advisory/read-only module. Scores how stable a protocol's yield has been
historically — using variance, range, regime count, and trend to produce a
0-100 stability score that helps rank protocols by yield reliability.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import math
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import List


# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "yield_stability_log.json"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class YieldStabilityScore:
    protocol: str
    asset: str
    apy_series: List[float]

    # Basic stats
    mean_apy: float
    std_apy: float
    min_apy: float
    max_apy: float
    apy_range: float  # max - min

    # Normalized metrics
    coefficient_of_variation: float  # std/mean*100 if mean>0 else 0

    # Stability score components (each 0-100)
    cv_score: float         # 100 - min(cv, 100)
    range_score: float      # 100 - min(range/mean*100, 100) if mean>0 else 0

    # Regime count: number of times yield crossed above/below mean
    regime_changes: int
    regime_score: float     # max(0, 100 - regime_changes * 5)

    # Overall score: 0.4*cv_score + 0.4*range_score + 0.2*regime_score
    stability_score: float

    stability_label: str  # HIGHLY_STABLE (>=80) | STABLE (60-80) | MODERATE (40-60) | UNSTABLE (<40)

    # Trend: is yield trending up (last half avg > first half avg)?
    is_yield_trending_up: bool
    trend_direction: str  # UP | DOWN | FLAT

    recommendation: str


@dataclass
class YieldStabilityResult:
    scores: List[YieldStabilityScore]

    most_stable_protocol: str
    least_stable_protocol: str
    avg_stability_score: float

    highly_stable_count: int  # score >= 80

    market_stability_label: str  # STABLE_MARKET (avg>=60) | MIXED_MARKET (40-60) | VOLATILE_MARKET (<40)

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mean(series: List[float]) -> float:
    if not series:
        return 0.0
    return sum(series) / len(series)


def _std(series: List[float]) -> float:
    """Population standard deviation."""
    if len(series) < 2:
        return 0.0
    m = _mean(series)
    variance = sum((x - m) ** 2 for x in series) / len(series)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def compute_cv(series: List[float]) -> float:
    """Coefficient of variation: std/mean*100 if mean>0 else 0."""
    if not series:
        return 0.0
    m = _mean(series)
    if m <= 0:
        return 0.0
    return _std(series) / m * 100.0


def compute_regime_changes(series: List[float], mean: float) -> int:
    """
    Count transitions across mean: iterate pairs (series[i], series[i+1]);
    count where one is < mean and next is >= mean, or vice versa.
    """
    if len(series) < 2:
        return 0
    changes = 0
    for i in range(len(series) - 1):
        a = series[i]
        b = series[i + 1]
        if (a < mean and b >= mean) or (a >= mean and b < mean):
            changes += 1
    return changes


def compute_trend_direction(series: List[float]) -> str:
    """
    Split in half; first_half_avg, second_half_avg.
    If second > first + 1% of first → UP.
    If second < first - 1% of first → DOWN.
    Else FLAT.
    """
    n = len(series)
    if n < 2:
        return "FLAT"
    mid = n // 2
    first_half = series[:mid]
    second_half = series[mid:]
    first_avg = _mean(first_half)
    second_avg = _mean(second_half)
    threshold = abs(first_avg) * 0.01
    if second_avg > first_avg + threshold:
        return "UP"
    elif second_avg < first_avg - threshold:
        return "DOWN"
    else:
        return "FLAT"


def _stability_label(score: float) -> str:
    if score >= 80:
        return "HIGHLY_STABLE"
    elif score >= 60:
        return "STABLE"
    elif score >= 40:
        return "MODERATE"
    else:
        return "UNSTABLE"


def _recommendation(label: str) -> str:
    if label == "HIGHLY_STABLE":
        return "Yield is highly consistent. Low variance makes this suitable for core allocation."
    elif label == "STABLE":
        return "Yield is relatively stable. Suitable for significant allocation."
    elif label == "MODERATE":
        return "Yield shows moderate variance. Consider partial allocation with monitoring."
    else:
        return "Yield is unstable. High variance warrants caution. Limit exposure."


def score_protocol(protocol: str, asset: str, apy_series: List[float]) -> YieldStabilityScore:
    """Score a single protocol's yield stability."""
    series = list(apy_series)

    mean_apy = _mean(series)
    std_apy = _std(series)
    min_apy = min(series) if series else 0.0
    max_apy = max(series) if series else 0.0
    apy_range = max_apy - min_apy

    cv = compute_cv(series)
    regime_chg = compute_regime_changes(series, mean_apy)
    trend_dir = compute_trend_direction(series)

    # Score components
    cv_score = max(0.0, 100.0 - min(cv, 100.0))
    if mean_apy > 0:
        range_score = max(0.0, 100.0 - min(apy_range / mean_apy * 100.0, 100.0))
    else:
        range_score = 0.0
    regime_score = max(0.0, 100.0 - regime_chg * 5.0)

    # Overall score (rounded to 2 dp)
    stability_score = round(0.4 * cv_score + 0.4 * range_score + 0.2 * regime_score, 2)
    label = _stability_label(stability_score)
    is_trending_up = trend_dir == "UP"
    recommendation = _recommendation(label)

    return YieldStabilityScore(
        protocol=protocol,
        asset=asset,
        apy_series=series,
        mean_apy=mean_apy,
        std_apy=std_apy,
        min_apy=min_apy,
        max_apy=max_apy,
        apy_range=apy_range,
        coefficient_of_variation=cv,
        cv_score=cv_score,
        range_score=range_score,
        regime_changes=regime_chg,
        regime_score=regime_score,
        stability_score=stability_score,
        stability_label=label,
        is_yield_trending_up=is_trending_up,
        trend_direction=trend_dir,
        recommendation=recommendation,
    )


def score_all(protocols_data: List[dict]) -> YieldStabilityResult:
    """
    Score all protocols.
    protocols_data: List[{protocol, asset, apy_series}]
    """
    scores = [
        score_protocol(pd["protocol"], pd["asset"], pd["apy_series"])
        for pd in protocols_data
    ]

    if not scores:
        return YieldStabilityResult(
            scores=[],
            most_stable_protocol="",
            least_stable_protocol="",
            avg_stability_score=0.0,
            highly_stable_count=0,
            market_stability_label="VOLATILE_MARKET",
            recommendation_summary="No protocols to analyze.",
            saved_to="",
        )

    most_stable = max(scores, key=lambda s: s.stability_score).protocol
    least_stable = min(scores, key=lambda s: s.stability_score).protocol
    avg_score = round(_mean([s.stability_score for s in scores]), 2)
    highly_stable_count = sum(1 for s in scores if s.stability_score >= 80)

    if avg_score >= 60:
        market_label = "STABLE_MARKET"
        rec_summary = "Market yields are broadly stable. Favorable conditions for allocation."
    elif avg_score >= 40:
        market_label = "MIXED_MARKET"
        rec_summary = "Mixed yield stability across protocols. Selective allocation advised."
    else:
        market_label = "VOLATILE_MARKET"
        rec_summary = "Market yields are volatile. Prioritize most stable protocols only."

    return YieldStabilityResult(
        scores=scores,
        most_stable_protocol=most_stable,
        least_stable_protocol=least_stable,
        avg_stability_score=avg_score,
        highly_stable_count=highly_stable_count,
        market_stability_label=market_label,
        recommendation_summary=rec_summary,
        saved_to="",
    )


def save_results(result: YieldStabilityResult, data_file: str = _DEFAULT_DATA_FILE) -> str:
    """Save result to ring-buffer JSON (max 100 entries). Returns saved_to path."""
    os.makedirs(os.path.dirname(data_file), exist_ok=True)

    history = load_history(data_file)
    entry = asdict(result)
    history.append(entry)

    # Ring-buffer cap 100
    if len(history) > 100:
        history = history[-100:]

    # Atomic write
    dir_ = os.path.dirname(data_file)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tf:
        json.dump(history, tf, indent=2)
        tmp_path = tf.name
    os.replace(tmp_path, data_file)

    return data_file


def load_history(data_file: str = _DEFAULT_DATA_FILE) -> list:
    """Load history from JSON file. Returns empty list on missing/corrupt file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-745 YieldStabilityScorer")
    parser.add_argument("--run", action="store_true", help="Run and save results")
    parser.add_argument("--check", action="store_true", help="Run without saving (default)")
    parser.add_argument("--data-dir", help="Override data directory")
    args = parser.parse_args()

    data_file = _DEFAULT_DATA_FILE
    if args.data_dir:
        data_file = os.path.join(args.data_dir, "yield_stability_log.json")

    sample = [
        {"protocol": "Aave V3",          "asset": "USDC", "apy_series": [3.4, 3.5, 3.6, 3.5, 3.4, 3.5, 3.6]},
        {"protocol": "Compound V3",       "asset": "USDC", "apy_series": [4.5, 5.2, 4.1, 6.0, 3.8, 5.5, 4.9]},
        {"protocol": "Morpho Steakhouse", "asset": "USDC", "apy_series": [6.0, 6.5, 6.2, 6.4, 6.1, 6.3, 6.5]},
    ]

    result = score_all(sample)
    print(f"Market Stability: {result.market_stability_label}")
    print(f"Avg Score:        {result.avg_stability_score:.2f}")
    print(f"Most Stable:      {result.most_stable_protocol}")
    print(f"Least Stable:     {result.least_stable_protocol}")
    print(f"Highly Stable:    {result.highly_stable_count}")
    for s in result.scores:
        print(f"  {s.protocol}: score={s.stability_score} label={s.stability_label} trend={s.trend_direction}")

    if args.run:
        result.saved_to = save_results(result, data_file)
        print(f"Saved to: {result.saved_to}")
