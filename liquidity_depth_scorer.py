"""
MP-738: LiquidityDepthScorer
Advisory/read-only analytics module.
Scores the depth and quality of liquidity in DeFi protocols,
assessing how large a position can be exited without significant slippage.

CLI:
    python3 -m spa_core.analytics.liquidity_depth_scorer --check
    python3 -m spa_core.analytics.liquidity_depth_scorer --run
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from typing import List, Optional


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "liquidity_depth_log.json")
RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LiquidityDepthMetrics:
    protocol: str
    asset: str
    total_liquidity_usd: float

    # Depth tiers: max exit size without exceeding slippage threshold
    exit_1pct_slippage_usd: float   # 1% slippage capacity
    exit_3pct_slippage_usd: float   # 3% slippage capacity
    exit_5pct_slippage_usd: float   # 5% slippage capacity

    # Position size evaluation
    position_size_usd: float
    position_as_pct_of_liquidity: float   # position / liquidity * 100
    estimated_slippage_pct: float         # linear approx: position_pct / 20
    can_exit_under_1pct: bool             # estimated_slippage <= 1%
    can_exit_under_3pct: bool             # estimated_slippage <= 3%

    # Depth score 0–100
    depth_score: float
    depth_label: str   # "DEEP" | "ADEQUATE" | "SHALLOW"

    recommendation: str


@dataclass
class LiquidityDepthResult:
    metrics: List[LiquidityDepthMetrics]

    # Rankings
    deepest_protocol: str    # highest total_liquidity_usd
    shallowest_protocol: str # lowest total_liquidity_usd

    # Summary
    avg_depth_score: float
    pct_deep: float                    # % protocols with depth_label == "DEEP"

    total_liquid_capacity_usd: float   # sum of all exit_3pct_slippage_usd

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core math functions
# ---------------------------------------------------------------------------

def estimate_slippage(position_usd: float, total_liquidity_usd: float) -> float:
    """
    Linear slippage model: occupying X% of liquidity causes X/20 % slippage.
    Returns 100.0 when liquidity is 0 (infinite slippage proxy).
    """
    if total_liquidity_usd <= 0:
        return 100.0
    position_pct = position_usd / total_liquidity_usd * 100.0
    return position_pct / 20.0


def exit_capacity(total_liquidity_usd: float, max_slippage_pct: float) -> float:
    """
    How much can you exit for a given max slippage?
    Inverse of estimate_slippage: capacity = total * max_slippage_pct * 20 / 100
    Capped at total_liquidity_usd.
    """
    if total_liquidity_usd <= 0:
        return 0.0
    raw = total_liquidity_usd * max_slippage_pct * 20.0 / 100.0
    return min(raw, total_liquidity_usd)


def compute_depth_score(total_liquidity_usd: float) -> float:
    """
    Score 0–100 based on total liquidity.
    $1B  → 100
    $1M  → ~66.7
    $1K  → ~33.3
    $1   → 0
    """
    if total_liquidity_usd <= 0:
        return 0.0
    score = math.log10(max(1.0, total_liquidity_usd)) / math.log10(1e9) * 100.0
    return min(100.0, max(0.0, score))


def depth_label(score: float) -> str:
    """DEEP (>=80) | ADEQUATE (>=50) | SHALLOW (<50)"""
    if score >= 80.0:
        return "DEEP"
    elif score >= 50.0:
        return "ADEQUATE"
    else:
        return "SHALLOW"


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_position(
    protocol: str,
    asset: str,
    total_liquidity_usd: float,
    position_size_usd: float,
) -> LiquidityDepthMetrics:
    """Compute all liquidity depth metrics for a single position."""
    liq = max(0.0, total_liquidity_usd)
    pos = max(0.0, position_size_usd)

    e1 = exit_capacity(liq, 1.0)
    e3 = exit_capacity(liq, 3.0)
    e5 = exit_capacity(liq, 5.0)

    pos_pct = (pos / liq * 100.0) if liq > 0 else 100.0
    slip = estimate_slippage(pos, liq)
    can_1 = slip <= 1.0
    can_3 = slip <= 3.0

    score = compute_depth_score(liq)
    label = depth_label(score)

    if can_1:
        rec = "Safe to exit — well within liquidity depth."
    elif can_3:
        rec = f"Manageable exit — expect ~{slip:.1f}% slippage."
    else:
        rec = (
            f"WARNING: Large exit will cause significant slippage ({slip:.1f}%). "
            "Consider staged exits."
        )

    return LiquidityDepthMetrics(
        protocol=protocol,
        asset=asset,
        total_liquidity_usd=liq,
        exit_1pct_slippage_usd=e1,
        exit_3pct_slippage_usd=e3,
        exit_5pct_slippage_usd=e5,
        position_size_usd=pos,
        position_as_pct_of_liquidity=pos_pct,
        estimated_slippage_pct=slip,
        can_exit_under_1pct=can_1,
        can_exit_under_3pct=can_3,
        depth_score=score,
        depth_label=label,
        recommendation=rec,
    )


def analyze_portfolio(
    positions_data: List[dict],
    data_file: str = DEFAULT_DATA_FILE,
) -> LiquidityDepthResult:
    """
    Analyze liquidity depth across a portfolio of positions.

    positions_data: List[dict] with keys:
        protocol, asset, total_liquidity_usd, position_size_usd
    """
    metrics: List[LiquidityDepthMetrics] = []
    for p in positions_data:
        m = analyze_position(
            protocol=p["protocol"],
            asset=p["asset"],
            total_liquidity_usd=float(p["total_liquidity_usd"]),
            position_size_usd=float(p["position_size_usd"]),
        )
        metrics.append(m)

    if not metrics:
        return LiquidityDepthResult(
            metrics=[],
            deepest_protocol="N/A",
            shallowest_protocol="N/A",
            avg_depth_score=0.0,
            pct_deep=0.0,
            total_liquid_capacity_usd=0.0,
            recommendation_summary="No positions to analyze.",
            saved_to="",
        )

    deepest = max(metrics, key=lambda m: m.total_liquidity_usd).protocol
    shallowest = min(metrics, key=lambda m: m.total_liquidity_usd).protocol

    avg_score = sum(m.depth_score for m in metrics) / len(metrics)
    deep_count = sum(1 for m in metrics if m.depth_label == "DEEP")
    pct_deep = deep_count / len(metrics) * 100.0

    total_capacity = sum(m.exit_3pct_slippage_usd for m in metrics)

    # Recommendation summary
    if pct_deep >= 80.0:
        rec_summary = "Portfolio has deep liquidity. Exit risk is low across all positions."
    elif pct_deep >= 50.0:
        rec_summary = (
            "Mixed liquidity depth. Monitor shallow positions before large exits."
        )
    else:
        rec_summary = (
            "Significant liquidity risk. Most positions are in shallow liquidity pools. "
            "Consider staged exits and rebalancing toward deeper protocols."
        )

    return LiquidityDepthResult(
        metrics=metrics,
        deepest_protocol=deepest,
        shallowest_protocol=shallowest,
        avg_depth_score=round(avg_score, 4),
        pct_deep=round(pct_deep, 4),
        total_liquid_capacity_usd=round(total_capacity, 2),
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def load_history(data_file: str = DEFAULT_DATA_FILE) -> list:
    """Load history from JSON ring-buffer file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _result_to_dict(result: LiquidityDepthResult) -> dict:
    """Convert result to a JSON-serializable dict."""
    def _m(m: LiquidityDepthMetrics) -> dict:
        return asdict(m)

    return {
        "metrics": [_m(m) for m in result.metrics],
        "deepest_protocol": result.deepest_protocol,
        "shallowest_protocol": result.shallowest_protocol,
        "avg_depth_score": result.avg_depth_score,
        "pct_deep": result.pct_deep,
        "total_liquid_capacity_usd": result.total_liquid_capacity_usd,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(
    result: LiquidityDepthResult,
    data_file: str = DEFAULT_DATA_FILE,
) -> str:
    """Atomically append result to ring-buffer JSON file (cap 100)."""
    history = load_history(data_file)
    history.append(_result_to_dict(result))
    # Trim to ring-buffer cap
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(data_file), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(history, f, indent=2)
        os.replace(tmp_path, data_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    result.saved_to = data_file
    return data_file


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_POSITIONS = [
    {
        "protocol": "Aave V3",
        "asset": "USDC",
        "total_liquidity_usd": 2_000_000_000.0,
        "position_size_usd": 50_000.0,
    },
    {
        "protocol": "Compound V3",
        "asset": "USDC",
        "total_liquidity_usd": 500_000_000.0,
        "position_size_usd": 30_000.0,
    },
    {
        "protocol": "Morpho Steakhouse",
        "asset": "USDC",
        "total_liquidity_usd": 100_000_000.0,
        "position_size_usd": 20_000.0,
    },
]


def main() -> None:
    mode = "--check"
    data_file = DEFAULT_DATA_FILE
    args = sys.argv[1:]
    if "--run" in args:
        mode = "--run"
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_file = os.path.join(args[idx + 1], "liquidity_depth_log.json")

    result = analyze_portfolio(_SAMPLE_POSITIONS, data_file=data_file)

    print("=== MP-738 LiquidityDepthScorer ===")
    print(f"Protocols analyzed: {len(result.metrics)}")
    print(f"Deepest:    {result.deepest_protocol}")
    print(f"Shallowest: {result.shallowest_protocol}")
    print(f"Avg depth score: {result.avg_depth_score:.1f}")
    print(f"% DEEP protocols: {result.pct_deep:.1f}%")
    print(f"Total 3%-slippage capacity: ${result.total_liquid_capacity_usd:,.0f}")
    print(f"Summary: {result.recommendation_summary}")

    for m in result.metrics:
        print(
            f"  [{m.depth_label}] {m.protocol}/{m.asset} "
            f"liquidity=${m.total_liquidity_usd:,.0f} "
            f"score={m.depth_score:.1f} "
            f"slip={m.estimated_slippage_pct:.2f}%"
        )

    if mode == "--run":
        save_results(result, data_file)
        print(f"Saved → {result.saved_to}")


if __name__ == "__main__":
    main()
