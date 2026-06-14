"""
MP-686: YieldCurveTracker
Track DeFi fixed-rate yield curves across maturities, detect inversions,
term premium changes, and compare against TradFi benchmarks.
Pure stdlib, read-only analytics, atomic JSON writes.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/yield_curve_log.json")
MAX_ENTRIES = 100

# TradFi benchmark rates (US Treasury approximations)
TRADFI_BENCHMARKS: Dict[int, float] = {
    30:   4.25,   # 30-day T-bill
    90:   4.50,   # 90-day T-bill
    180:  4.55,   # 6-month T-bill
    365:  4.40,   # 1-year T-note
    730:  4.20,   # 2-year T-note
    1825: 4.35,   # 5-year T-note
}


@dataclass
class YieldPoint:
    maturity_days: int    # e.g. 30, 90, 180, 365
    protocol: str         # "pendle", "notional", "element", "tradfi"
    asset: str
    yield_pct: float
    tvl_usd: float        # liquidity at this maturity


@dataclass
class YieldCurveReport:
    curve_id: str
    points: List[YieldPoint]
    is_inverted: bool
    term_premium_bps: float
    defi_vs_tradfi_spread_bps: float
    steepest_segment: Tuple[int, int]
    flattest_segment: Tuple[int, int]
    best_entry_point: int
    curve_shape: str
    interpretation: str


def _sort_points(points: List[YieldPoint]) -> List[YieldPoint]:
    """Return points sorted by maturity_days ascending."""
    return sorted(points, key=lambda p: p.maturity_days)


def _is_inverted(sorted_points: List[YieldPoint]) -> bool:
    """True if yield at shortest maturity > yield at longest maturity."""
    if len(sorted_points) < 2:
        return False
    return sorted_points[0].yield_pct > sorted_points[-1].yield_pct


def _term_premium_bps(sorted_points: List[YieldPoint]) -> float:
    """(longest_yield - shortest_yield) * 100, in basis points."""
    if len(sorted_points) < 2:
        return 0.0
    return (sorted_points[-1].yield_pct - sorted_points[0].yield_pct) * 100.0


def _nearest_tradfi(maturity_days: int) -> float:
    """Find the nearest TRADFI_BENCHMARKS maturity and return its rate."""
    best_mat = min(TRADFI_BENCHMARKS.keys(), key=lambda m: abs(m - maturity_days))
    return TRADFI_BENCHMARKS[best_mat]


def _defi_vs_tradfi_spread_bps(sorted_points: List[YieldPoint]) -> float:
    """
    For each DeFi (non-tradfi) point, compute spread vs nearest TradFi benchmark.
    Returns average spread in bps. Returns 0.0 if no DeFi points.
    """
    defi_points = [p for p in sorted_points if p.protocol.lower() != "tradfi"]
    if not defi_points:
        return 0.0
    spreads = []
    for p in defi_points:
        tradfi_yield = _nearest_tradfi(p.maturity_days)
        spread_bps = (p.yield_pct - tradfi_yield) * 100.0
        spreads.append(spread_bps)
    return sum(spreads) / len(spreads)


def _segment_slopes(sorted_points: List[YieldPoint]) -> List[Tuple[int, int, float]]:
    """
    Returns list of (maturity_a, maturity_b, slope) tuples.
    slope = (yield_b - yield_a) / (maturity_b - maturity_a) * 365
    (annualized per day).
    Requires >= 2 points.
    """
    if len(sorted_points) < 2:
        return []
    result = []
    for i in range(len(sorted_points) - 1):
        a = sorted_points[i]
        b = sorted_points[i + 1]
        day_diff = b.maturity_days - a.maturity_days
        if day_diff == 0:
            continue
        slope = (b.yield_pct - a.yield_pct) / day_diff * 365.0
        result.append((a.maturity_days, b.maturity_days, slope))
    return result


def _steepest_segment(slopes: List[Tuple[int, int, float]]) -> Tuple[int, int]:
    """(a, b) with max abs slope."""
    if not slopes:
        return (0, 0)
    seg = max(slopes, key=lambda s: abs(s[2]))
    return (seg[0], seg[1])


def _flattest_segment(slopes: List[Tuple[int, int, float]]) -> Tuple[int, int]:
    """(a, b) with min abs slope."""
    if not slopes:
        return (0, 0)
    seg = min(slopes, key=lambda s: abs(s[2]))
    return (seg[0], seg[1])


def _best_entry_point(sorted_points: List[YieldPoint]) -> int:
    """
    Maturity with highest yield among DeFi points with tvl_usd > 100_000.
    Returns 0 if no qualifying points.
    """
    qualifying = [
        p for p in sorted_points
        if p.protocol.lower() != "tradfi" and p.tvl_usd > 100_000
    ]
    if not qualifying:
        return 0
    best = max(qualifying, key=lambda p: p.yield_pct)
    return best.maturity_days


def _has_hump(sorted_points: List[YieldPoint]) -> bool:
    """True if any interior point has yield > both neighbors."""
    if len(sorted_points) < 3:
        return False
    for i in range(1, len(sorted_points) - 1):
        if (sorted_points[i].yield_pct > sorted_points[i - 1].yield_pct and
                sorted_points[i].yield_pct > sorted_points[i + 1].yield_pct):
            return True
    return False


def _curve_shape(inverted: bool, term_premium: float, sorted_points: List[YieldPoint]) -> str:
    """
    INVERTED / FLAT / HUMPED / NORMAL
    Priority: INVERTED > FLAT > HUMPED > NORMAL
    """
    if inverted:
        return "INVERTED"
    if abs(term_premium) < 20:
        return "FLAT"
    if _has_hump(sorted_points):
        return "HUMPED"
    return "NORMAL"


def _interpretation(shape: str) -> str:
    messages = {
        "INVERTED": "⚠️ Inverted curve — market expects rate cuts; prefer shorter durations",
        "FLAT":     "📋 Flat curve — little term premium; shorter duration preferred",
        "HUMPED":   "📋 Humped curve — medium-term offers best yield",
        "NORMAL":   "✅ Normal curve — term premium rewards longer duration",
    }
    return messages.get(shape, "")


def analyze_curve(curve_id: str, points: List[YieldPoint]) -> YieldCurveReport:
    """
    Analyze a set of yield points and return a YieldCurveReport.
    """
    sorted_pts = _sort_points(points)
    inverted = _is_inverted(sorted_pts)
    tp_bps = _term_premium_bps(sorted_pts)
    defi_spread = _defi_vs_tradfi_spread_bps(sorted_pts)
    slopes = _segment_slopes(sorted_pts)
    steepest = _steepest_segment(slopes)
    flattest = _flattest_segment(slopes)
    best_entry = _best_entry_point(sorted_pts)
    shape = _curve_shape(inverted, tp_bps, sorted_pts)
    interp = _interpretation(shape)

    return YieldCurveReport(
        curve_id=curve_id,
        points=sorted_pts,
        is_inverted=inverted,
        term_premium_bps=tp_bps,
        defi_vs_tradfi_spread_bps=defi_spread,
        steepest_segment=steepest,
        flattest_segment=flattest,
        best_entry_point=best_entry,
        curve_shape=shape,
        interpretation=interp,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _report_to_dict(report: YieldCurveReport) -> dict:
    return {
        "curve_id": report.curve_id,
        "timestamp": time.time(),
        "points": [
            {
                "maturity_days": p.maturity_days,
                "protocol": p.protocol,
                "asset": p.asset,
                "yield_pct": p.yield_pct,
                "tvl_usd": p.tvl_usd,
            }
            for p in report.points
        ],
        "is_inverted": report.is_inverted,
        "term_premium_bps": report.term_premium_bps,
        "defi_vs_tradfi_spread_bps": report.defi_vs_tradfi_spread_bps,
        "steepest_segment": list(report.steepest_segment),
        "flattest_segment": list(report.flattest_segment),
        "best_entry_point": report.best_entry_point,
        "curve_shape": report.curve_shape,
        "interpretation": report.interpretation,
    }


def save_results(report: YieldCurveReport, data_file: Path = DATA_FILE) -> None:
    """Append report to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(data_file)
    history.append(_report_to_dict(report))
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    os.replace(str(tmp), str(data_file))


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load ring-buffer history. Returns [] if file missing or invalid."""
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo_run() -> None:
    """Quick smoke-test with sample data."""
    pts = [
        YieldPoint(30,  "pendle", "USDC", 5.2,  2_000_000),
        YieldPoint(90,  "pendle", "USDC", 7.8,  1_500_000),
        YieldPoint(180, "pendle", "USDC", 9.1,  800_000),
        YieldPoint(365, "pendle", "USDC", 8.5,  300_000),
    ]
    report = analyze_curve("demo-curve-001", pts)
    print(f"Curve: {report.curve_id}")
    print(f"  Shape:       {report.curve_shape}")
    print(f"  Inverted:    {report.is_inverted}")
    print(f"  Term prem:   {report.term_premium_bps:.1f} bps")
    print(f"  DeFi-TradFi: {report.defi_vs_tradfi_spread_bps:.1f} bps")
    print(f"  Best entry:  {report.best_entry_point}d")
    print(f"  {report.interpretation}")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv or len(sys.argv) == 1:
        _demo_run()
    elif "--run" in sys.argv:
        # In production the caller would supply real data
        _demo_run()
        print("(no data written in demo mode)")
