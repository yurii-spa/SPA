"""
MP-707: PortfolioConcentrationOptimizer
Advisory/read-only module. Pure stdlib. Atomic JSON writes via tmp+os.replace.

Recommends portfolio weight adjustments to reduce HHI concentration while
maintaining or improving yield targets.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Data path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
DATA_FILE = os.path.join(_REPO_ROOT, "data", "concentration_optimizer_log.json")

RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Position:
    name: str
    protocol: str
    chain: str
    current_weight: float   # 0.0–1.0; all positions should sum to 1.0
    apy: float              # current APY %
    risk_score: float       # 0–100
    max_weight: float       # hard cap per position (e.g. 0.4)


@dataclass
class OptimizationResult:
    positions: List[Position]

    # Current state
    current_hhi: float
    current_weighted_apy: float
    current_weighted_risk: float

    # Recommended state
    recommended_weights: Dict[str, float]
    recommended_hhi: float
    recommended_weighted_apy: float
    recommended_weighted_risk: float

    # Changes
    hhi_improvement: float       # current - recommended (positive = better)
    apy_change: float            # recommended_apy - current_apy

    rebalance_trades: List[dict]
    diversification_score: float  # (1 - recommended_hhi) * 100
    recommendation: str           # "WELL_DIVERSIFIED" | "REBALANCE_RECOMMENDED" | "CONCENTRATED_RISK"
    warnings: List[str]
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def calculate_hhi(weights: List[float]) -> float:
    """Herfindahl-Hirschman Index: sum(w^2). 0 = perfectly diversified, 1 = monopoly."""
    return sum(w * w for w in weights)


def calculate_weighted_avg(weights: List[float], values: List[float]) -> float:
    """Weighted average: sum(w * v)."""
    return sum(w * v for w, v in zip(weights, values))


def _renormalize(weights: List[float]) -> List[float]:
    """Scale weights so they sum to 1.0. Returns zeroes if total=0."""
    total = sum(weights)
    if total <= 0:
        n = len(weights)
        return [1.0 / n] * n if n > 0 else []
    return [w / total for w in weights]


def _apply_max_weight_cap(
    weights: List[float],
    max_weights: List[float],
    tol: float = 1e-12,
) -> List[float]:
    """
    Water-filling projection: distribute weight from over-capped positions
    proportionally to uncapped positions.  Stops when all weights ≤ max_weight.
    If constraints are infeasible (sum(max_weights) < 1.0) the result is
    renormalized proportionally without enforcing caps.
    """
    n = len(weights)
    if n == 0:
        return []

    # Feasibility guard: skip caps if they sum to less than 1.0
    if sum(max_weights) < 1.0 - tol:
        return _renormalize(list(weights))

    result = _renormalize(list(weights))

    for _ in range(n * 4 + 20):
        # Identify violators and uncapped
        excess = 0.0
        uncapped_indices = []
        for i in range(n):
            if result[i] > max_weights[i] + tol:
                excess += result[i] - max_weights[i]
                result[i] = max_weights[i]
            else:
                uncapped_indices.append(i)

        if excess <= tol:
            break  # no violation → done

        if not uncapped_indices:
            # All positions are at their caps — normalize to sum=1
            result = _renormalize(result)
            break

        # Distribute excess proportionally by current weight among uncapped
        uncapped_total = sum(result[i] for i in uncapped_indices)
        if uncapped_total < tol:
            # Fall back to equal distribution
            share = excess / len(uncapped_indices)
            for i in uncapped_indices:
                result[i] = min(result[i] + share, max_weights[i])
        else:
            for i in uncapped_indices:
                result[i] = min(
                    result[i] + excess * (result[i] / uncapped_total),
                    max_weights[i],
                )

    return result


def optimize(positions: List[Position]) -> OptimizationResult:
    """
    Compute recommended weights to reduce HHI while favouring higher APY positions.

    Algorithm (deterministic):
    1. Start with equal weights (1/N each), capped at p.max_weight
    2. Sort by APY desc; top 1/3 get +5% weight boost (up to max_weight),
       bottom 1/3 get -5% reduction, middle unchanged
    3. Renormalize to sum=1; re-apply max_weight cap; renormalize again
    """
    n = len(positions)
    if n == 0:
        return OptimizationResult(
            positions=[],
            current_hhi=0.0,
            current_weighted_apy=0.0,
            current_weighted_risk=0.0,
            recommended_weights={},
            recommended_hhi=0.0,
            recommended_weighted_apy=0.0,
            recommended_weighted_risk=0.0,
            hhi_improvement=0.0,
            apy_change=0.0,
            rebalance_trades=[],
            diversification_score=100.0,
            recommendation="WELL_DIVERSIFIED",
            warnings=[],
        )

    # ---------- Current state ----------
    current_weights = [p.current_weight for p in positions]
    apys = [p.apy for p in positions]
    risks = [p.risk_score for p in positions]
    max_weights = [p.max_weight for p in positions]

    current_hhi = calculate_hhi(current_weights)
    current_weighted_apy = calculate_weighted_avg(current_weights, apys)
    current_weighted_risk = calculate_weighted_avg(current_weights, risks)

    # ---------- Step 1: Equal weights capped ----------
    equal_w = 1.0 / n
    start_weights = [min(equal_w, mw) for mw in max_weights]
    start_weights = _renormalize(start_weights)

    # ---------- Step 2: APY-based tilt ----------
    sorted_by_apy = sorted(range(n), key=lambda i: apys[i], reverse=True)
    top_count = max(1, n // 3)
    bottom_count = max(1, n // 3)
    top_indices = set(sorted_by_apy[:top_count])
    bottom_indices = set(sorted_by_apy[n - bottom_count:])

    BOOST = 0.05
    tilted = list(start_weights)
    for i in range(n):
        if i in top_indices:
            tilted[i] = min(tilted[i] + BOOST, max_weights[i])
        elif i in bottom_indices:
            tilted[i] = max(tilted[i] - BOOST, 0.0)

    # ---------- Step 3: Apply max-weight projection ----------
    tilted = _renormalize(tilted)
    recommended_weights_list = _apply_max_weight_cap(tilted, max_weights)

    # ---------- Recommended metrics ----------
    recommended_hhi = calculate_hhi(recommended_weights_list)
    recommended_weighted_apy = calculate_weighted_avg(recommended_weights_list, apys)
    recommended_weighted_risk = calculate_weighted_avg(recommended_weights_list, risks)

    recommended_weights_dict = {
        p.name: recommended_weights_list[i] for i, p in enumerate(positions)
    }

    # ---------- Changes ----------
    hhi_improvement = current_hhi - recommended_hhi
    apy_change = recommended_weighted_apy - current_weighted_apy

    # ---------- Rebalance trades ----------
    rebalance_trades = []
    for i, p in enumerate(positions):
        from_w = p.current_weight
        to_w = recommended_weights_list[i]
        delta = to_w - from_w
        if delta > 1e-6:
            action = "INCREASE"
        elif delta < -1e-6:
            action = "DECREASE"
        else:
            action = "HOLD"
        rebalance_trades.append({
            "position": p.name,
            "action": action,
            "from_weight": from_w,
            "to_weight": to_w,
            "delta": delta,
        })

    # ---------- Diversification score ----------
    diversification_score = (1.0 - recommended_hhi) * 100.0

    # ---------- Recommendation ----------
    if recommended_hhi < 0.15:
        recommendation = "WELL_DIVERSIFIED"
    elif recommended_hhi < 0.25:
        recommendation = "REBALANCE_RECOMMENDED"
    else:
        recommendation = "CONCENTRATED_RISK"

    # ---------- Warnings ----------
    warnings: List[str] = []
    for name, w in recommended_weights_dict.items():
        if w > 0.35:
            warnings.append(f"high single position: {name}")
    if hhi_improvement < 0:
        warnings.append("optimization didn't improve HHI")
    if apy_change < -1.0:
        warnings.append("significant yield reduction")

    return OptimizationResult(
        positions=positions,
        current_hhi=current_hhi,
        current_weighted_apy=current_weighted_apy,
        current_weighted_risk=current_weighted_risk,
        recommended_weights=recommended_weights_dict,
        recommended_hhi=recommended_hhi,
        recommended_weighted_apy=recommended_weighted_apy,
        recommended_weighted_risk=recommended_weighted_risk,
        hhi_improvement=hhi_improvement,
        apy_change=apy_change,
        rebalance_trades=rebalance_trades,
        diversification_score=diversification_score,
        recommendation=recommendation,
        warnings=warnings,
    )


def explain_trades(result: OptimizationResult) -> str:
    """Return a human-readable summary of recommended rebalances."""
    if not result.rebalance_trades:
        return "No positions to rebalance."

    lines = [
        f"Recommended rebalances (current HHI={result.current_hhi:.4f} → {result.recommended_hhi:.4f}):",
        f"  Diversification score: {result.diversification_score:.1f}/100",
        f"  Recommendation: {result.recommendation}",
        f"  APY change: {result.apy_change:+.3f}%",
        "",
    ]
    for trade in result.rebalance_trades:
        pct_from = trade["from_weight"] * 100
        pct_to = trade["to_weight"] * 100
        delta = trade["delta"] * 100
        lines.append(
            f"  {trade['action']:8s}  {trade['position']:30s}  "
            f"{pct_from:6.2f}% → {pct_to:6.2f}%  (Δ{delta:+.2f}%)"
        )
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  ⚠ {w}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _position_to_dict(p: Position) -> dict:
    return {
        "name": p.name,
        "protocol": p.protocol,
        "chain": p.chain,
        "current_weight": p.current_weight,
        "apy": p.apy,
        "risk_score": p.risk_score,
        "max_weight": p.max_weight,
    }


def _result_to_dict(result: OptimizationResult) -> dict:
    return {
        "ts": time.time(),
        "positions": [_position_to_dict(p) for p in result.positions],
        "current_hhi": result.current_hhi,
        "current_weighted_apy": result.current_weighted_apy,
        "current_weighted_risk": result.current_weighted_risk,
        "recommended_weights": result.recommended_weights,
        "recommended_hhi": result.recommended_hhi,
        "recommended_weighted_apy": result.recommended_weighted_apy,
        "recommended_weighted_risk": result.recommended_weighted_risk,
        "hhi_improvement": result.hhi_improvement,
        "apy_change": result.apy_change,
        "rebalance_trades": result.rebalance_trades,
        "diversification_score": result.diversification_score,
        "recommendation": result.recommendation,
        "warnings": result.warnings,
        "saved_to": result.saved_to,
    }


def load_history(data_file: str = DATA_FILE) -> list:
    """Load the persisted ring-buffer log."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def save_results(
    result: OptimizationResult,
    data_file: str = DATA_FILE,
) -> OptimizationResult:
    """Append to ring-buffer (cap 100), atomic write. Mutates result.saved_to."""
    history = load_history(data_file)
    entry = _result_to_dict(result)
    history.append(entry)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    dir_name = os.path.dirname(data_file)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=dir_name, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(history, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, data_file)

    result.saved_to = data_file
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    positions = [
        Position(name="Aave_ETH",      protocol="Aave V3",   chain="ethereum", current_weight=0.60, apy=3.5,  risk_score=20, max_weight=0.40),
        Position(name="Compound_ETH",  protocol="Compound",  chain="ethereum", current_weight=0.20, apy=4.8,  risk_score=25, max_weight=0.40),
        Position(name="Morpho_ETH",    protocol="Morpho",    chain="ethereum", current_weight=0.10, apy=6.5,  risk_score=35, max_weight=0.35),
        Position(name="Yearn_ARB",     protocol="Yearn V3",  chain="arbitrum", current_weight=0.05, apy=5.2,  risk_score=40, max_weight=0.25),
        Position(name="Euler_BASE",    protocol="Euler V2",  chain="base",     current_weight=0.05, apy=5.8,  risk_score=45, max_weight=0.25),
    ]

    result = optimize(positions)
    print(explain_trades(result))
    save_results(result)
    print(f"\nSaved to: {result.saved_to}")
    sys.exit(0)
