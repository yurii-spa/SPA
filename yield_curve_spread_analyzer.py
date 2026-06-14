"""
MP-732: YieldCurveSpreadAnalyzer

Advisory/read-only module. Analyzes yield spreads across different maturities
and risk tiers in the DeFi yield curve — comparing short-term vs long-term yields,
stable vs volatile yields, and identifying spread compression/widening signals.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import List, Optional
from statistics import mean

# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_curve_spread_log.json"
)
_DEFAULT_DATA_FILE = os.path.normpath(_DEFAULT_DATA_FILE)

_RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class YieldTenor:
    label: str          # "1W" | "1M" | "3M" | "6M" | "1Y"
    days: int           # 7, 30, 90, 180, 365
    apy: float
    protocol: str
    risk_score: float   # 0–100


@dataclass
class YieldSpread:
    label: str              # e.g. "1Y-1W" or "STABLE-RISKY"
    long_apy: float
    short_apy: float
    spread_bps: float       # (long_apy - short_apy) * 100 (basis points)
    spread_direction: str   # "NORMAL" | "INVERTED" | "FLAT"
    signal: str             # "STEEPENING" | "FLATTENING" | "STABLE"


@dataclass
class YieldCurveAnalysisResult:
    tenors: List[YieldTenor]
    spreads: List[YieldSpread]

    # Curve shape
    curve_shape: str        # "NORMAL" | "INVERTED" | "FLAT" | "HUMPED"
    steepness_bps: float    # (max_apy - min_apy) * 100

    # Risk premium analysis
    risk_premium_bps: float  # avg spread between high-risk (>70) and low-risk (<30) tenors

    # Signals
    inversion_count: int     # number of inverted spreads
    is_curve_inverted: bool  # majority spreads inverted

    # Recommendation
    optimal_tenor: str      # tenor with best risk-adjusted yield
    recommendation: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def compute_spread(long_tenor: YieldTenor, short_tenor: YieldTenor) -> YieldSpread:
    """Compute YieldSpread between two tenors."""
    spread_bps = (long_tenor.apy - short_tenor.apy) * 100

    if spread_bps > 5.0:
        direction = "NORMAL"
    elif spread_bps < -5.0:
        direction = "INVERTED"
    else:
        direction = "FLAT"

    abs_bps = abs(spread_bps)
    if abs_bps > 100.0:
        signal = "STEEPENING"
    elif abs_bps < 20.0:
        signal = "FLATTENING"
    else:
        signal = "STABLE"

    label = f"{long_tenor.label}-{short_tenor.label}"
    return YieldSpread(
        label=label,
        long_apy=long_tenor.apy,
        short_apy=short_tenor.apy,
        spread_bps=spread_bps,
        spread_direction=direction,
        signal=signal,
    )


def compute_curve_shape(tenors: List[YieldTenor]) -> str:
    """Determine overall curve shape from sorted tenors."""
    if len(tenors) <= 1:
        return "FLAT"

    # Sort by days ascending
    sorted_tenors = sorted(tenors, key=lambda t: t.days)
    apys = [t.apy for t in sorted_tenors]

    # Check monotonically increasing
    if all(apys[i] <= apys[i + 1] for i in range(len(apys) - 1)):
        return "NORMAL"

    # Check monotonically decreasing
    if all(apys[i] >= apys[i + 1] for i in range(len(apys) - 1)):
        return "INVERTED"

    # Check humped: peak in middle (not first, not last)
    max_val = max(apys)
    max_idx = apys.index(max_val)
    if 0 < max_idx < len(apys) - 1:
        return "HUMPED"

    return "FLAT"


def risk_adjusted_yield(tenor: YieldTenor) -> float:
    """Compute risk-adjusted yield: apy / (1 + risk_score/100)."""
    return tenor.apy / (1.0 + tenor.risk_score / 100.0)


def analyze(tenors: List[YieldTenor], data_file: Optional[str] = None) -> YieldCurveAnalysisResult:
    """
    Run full yield-curve spread analysis.

    Parameters
    ----------
    tenors : list of YieldTenor
    data_file : optional path override for saved_to

    Returns
    -------
    YieldCurveAnalysisResult (not saved — call save_results to persist)
    """
    if data_file is None:
        data_file = _DEFAULT_DATA_FILE

    # Build adjacent-tenor spreads (sorted by days asc)
    sorted_tenors = sorted(tenors, key=lambda t: t.days)
    spreads: List[YieldSpread] = []

    for i in range(len(sorted_tenors) - 1):
        short_t = sorted_tenors[i]
        long_t = sorted_tenors[i + 1]
        spreads.append(compute_spread(long_t, short_t))

    # Also build overall min-to-max spread if we have at least 2 tenors
    if len(sorted_tenors) >= 2:
        min_tenor = min(sorted_tenors, key=lambda t: t.apy)
        max_tenor = max(sorted_tenors, key=lambda t: t.apy)
        if min_tenor is not max_tenor:
            overall = compute_spread(max_tenor, min_tenor)
            overall_label = f"MAX({max_tenor.label})-MIN({min_tenor.label})"
            overall = YieldSpread(
                label=overall_label,
                long_apy=overall.long_apy,
                short_apy=overall.short_apy,
                spread_bps=overall.spread_bps,
                spread_direction=overall.spread_direction,
                signal=overall.signal,
            )
            spreads.append(overall)

    # Curve shape
    curve_shape = compute_curve_shape(tenors)

    # Steepness
    if tenors:
        max_apy = max(t.apy for t in tenors)
        min_apy = min(t.apy for t in tenors)
        steepness_bps = (max_apy - min_apy) * 100.0
    else:
        steepness_bps = 0.0

    # Risk premium: high-risk (>70) vs low-risk (<30)
    high_risk = [t for t in tenors if t.risk_score > 70]
    low_risk = [t for t in tenors if t.risk_score < 30]
    if high_risk and low_risk:
        risk_premium_bps = (mean(t.apy for t in high_risk) - mean(t.apy for t in low_risk)) * 100.0
    else:
        risk_premium_bps = 0.0

    # Count inverted spreads (only adjacent ones, not the overall spread)
    adjacent_spreads = spreads[:-1] if len(spreads) > 1 else spreads
    inversion_count = sum(1 for s in adjacent_spreads if s.spread_direction == "INVERTED")
    is_curve_inverted = (len(adjacent_spreads) > 0 and
                         inversion_count > len(adjacent_spreads) / 2)

    # Optimal tenor: best risk-adjusted yield
    if tenors:
        best = max(tenors, key=risk_adjusted_yield)
        optimal_tenor = best.label
    else:
        optimal_tenor = "N/A"

    # Recommendation
    recommendation = _build_recommendation(curve_shape, risk_premium_bps, is_curve_inverted, steepness_bps)

    return YieldCurveAnalysisResult(
        tenors=tenors,
        spreads=spreads,
        curve_shape=curve_shape,
        steepness_bps=steepness_bps,
        risk_premium_bps=risk_premium_bps,
        inversion_count=inversion_count,
        is_curve_inverted=is_curve_inverted,
        optimal_tenor=optimal_tenor,
        recommendation=recommendation,
        saved_to=data_file,
    )


def _build_recommendation(curve_shape: str, risk_premium_bps: float,
                           is_inverted: bool, steepness_bps: float) -> str:
    if is_inverted:
        return ("CAUTION: yield curve inverted — short-term yields exceed long-term; "
                "consider shorter durations to capture higher yields.")
    if curve_shape == "NORMAL" and steepness_bps > 200:
        return ("OPPORTUNITY: steep normal curve detected — longer-duration positions "
                "offer meaningful term premium; consider extending duration selectively.")
    if curve_shape == "HUMPED":
        return ("SELECTIVE: humped curve — medium-term tenors offer the best yield; "
                "avoid extremes of the curve.")
    if risk_premium_bps > 300:
        return ("HIGH RISK PREMIUM: significant spread between high-risk and low-risk "
                "protocols; ensure risk budget is not exceeded before chasing yield.")
    if steepness_bps < 50:
        return "FLAT CURVE: minimal yield differentiation across maturities; prioritise safety over yield."
    return "MONITOR: curve shape is within normal ranges; continue standard yield-optimisation strategy."


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _to_serialisable(obj):
    """Recursively convert dataclasses to dicts."""
    if hasattr(obj, '__dataclass_fields__'):
        d = {}
        for k, v in asdict(obj).items():
            d[k] = _to_serialisable(v)
        return d
    if isinstance(obj, list):
        return [_to_serialisable(i) for i in obj]
    return obj


def save_results(result: YieldCurveAnalysisResult, data_file: Optional[str] = None) -> str:
    """Append result to ring-buffer JSON log (cap 100). Atomic write. Returns file path."""
    if data_file is None:
        data_file = _DEFAULT_DATA_FILE

    history = load_history(data_file)
    history.append(_to_serialisable(result))

    # Ring-buffer cap
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(data_file), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp_path, data_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return data_file


def load_history(data_file: Optional[str] = None) -> list:
    """Load existing ring-buffer log. Returns empty list if file missing."""
    if data_file is None:
        data_file = _DEFAULT_DATA_FILE

    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo():
    """Quick self-test / demo with synthetic tenors."""
    tenors = [
        YieldTenor("1W",  7,   3.5,  "Aave",     risk_score=10),
        YieldTenor("1M",  30,  4.2,  "Compound", risk_score=15),
        YieldTenor("3M",  90,  5.1,  "Morpho",   risk_score=30),
        YieldTenor("6M",  180, 6.8,  "Euler",    risk_score=55),
        YieldTenor("1Y",  365, 8.3,  "Pendle",   risk_score=80),
    ]
    result = analyze(tenors)
    print(f"Curve shape   : {result.curve_shape}")
    print(f"Steepness     : {result.steepness_bps:.1f} bps")
    print(f"Risk premium  : {result.risk_premium_bps:.1f} bps")
    print(f"Inversions    : {result.inversion_count}")
    print(f"Is inverted   : {result.is_curve_inverted}")
    print(f"Optimal tenor : {result.optimal_tenor}")
    print(f"Spreads       : {[s.label for s in result.spreads]}")
    print(f"Recommendation: {result.recommendation}")


if __name__ == "__main__":
    _demo()
