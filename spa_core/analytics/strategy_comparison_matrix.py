"""
StrategyComparisonMatrix (SPA-V597 / MP-721) — advisory / read-only.

Compares multiple DeFi strategies across a standardised set of dimensions to
produce a normalised ranking and recommendation matrix.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/strategy_comparison_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

CLI
---
  python3 -m spa_core.analytics.strategy_comparison_matrix --check
  python3 -m spa_core.analytics.strategy_comparison_matrix --run
  python3 -m spa_core.analytics.strategy_comparison_matrix --run --data-dir PATH
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "strategy_comparison_log.json"
_RING_BUFFER_MAX = 100

# Ordered dimension list (determines iteration order)
_DIMENSIONS: List[str] = [
    "YIELD",
    "SAFETY",
    "SUSTAINABILITY",
    "LIQUIDITY",
    "ACCESSIBILITY",
]

# Dimension weights — must sum to 1.0
_WEIGHTS: Dict[str, float] = {
    "YIELD": 0.30,
    "SAFETY": 0.25,
    "SUSTAINABILITY": 0.20,
    "LIQUIDITY": 0.15,
    "ACCESSIBILITY": 0.10,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StrategyProfile:
    name: str
    apy: float                    # gross APY %
    real_yield_ratio: float       # 0–1 (from RealYieldExtractor)
    risk_score: float             # 0–100
    sustainability_index: float   # 0–100 (from YieldSustainabilityIndex)
    liquidity_usd: float          # exit liquidity in USD
    min_capital_usd: float        # minimum viable position in USD
    lock_period_days: int


@dataclass
class DimensionScore:
    dimension: str               # YIELD | SAFETY | SUSTAINABILITY | LIQUIDITY | ACCESSIBILITY
    raw_value: float
    normalized_score: float      # 0–100, higher = better
    weight: float
    weighted_score: float        # normalized_score * weight


@dataclass
class StrategyComparison:
    strategies: List[StrategyProfile]

    # Per-strategy dimension scores: {name: [DimensionScore, ...]}
    dimension_scores: Dict[str, List[DimensionScore]] = field(default_factory=dict)

    # Composite score per strategy: {name: float}
    composite_scores: Dict[str, float] = field(default_factory=dict)

    # Strategy names ordered best → worst by composite
    ranked_strategies: List[str] = field(default_factory=list)

    # Best strategy in each dimension
    best_yield: str = ""
    best_safety: str = ""
    best_sustainability: str = ""
    best_liquidity: str = ""
    best_accessibility: str = ""

    # Recommendations
    best_overall: str = ""           # highest composite score
    best_risk_adjusted: str = ""     # max(apy / max(risk_score, 0.1))
    best_for_small_capital: str = "" # lowest min_capital with composite > 50

    saved_to: str = ""


# ---------------------------------------------------------------------------
# Raw-value extraction
# ---------------------------------------------------------------------------

def _raw_value(profile: StrategyProfile, dimension: str) -> float:
    """Return the raw (un-normalised) value for *profile* in *dimension*.

    Higher raw value always means better for that dimension (i.e., SAFETY
    is already inverted here).
    """
    if dimension == "YIELD":
        return profile.apy

    if dimension == "SAFETY":
        # Lower risk_score is better → invert
        return 100.0 - profile.risk_score

    if dimension == "SUSTAINABILITY":
        return profile.sustainability_index

    if dimension == "LIQUIDITY":
        # Log scale to normalise large differences in liquidity
        return math.log10(max(profile.liquidity_usd, 1.0))

    if dimension == "ACCESSIBILITY":
        # Lower capital requirement and shorter lock → more accessible
        # min(50, capital/1000) caps the capital penalty at 50 points
        # min(50, lock/3) caps the lock penalty at 50 points (90-day lock = max penalty)
        raw = (
            100.0
            - min(50.0, profile.min_capital_usd / 1000.0)
            - min(50.0, profile.lock_period_days / 3.0)
        )
        return max(0.0, raw)

    raise ValueError(f"Unknown dimension: {dimension!r}")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalize(values: List[float]) -> List[float]:
    """Normalise *values* to the [0, 100] range.

    If all values are identical, every element maps to 50 (neutral midpoint).
    Otherwise applies min-max scaling: (v - min) / (max - min) * 100.
    """
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return [50.0] * len(values)
    span = mx - mn
    return [(v - mn) / span * 100.0 for v in values]


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_strategies(strategies: List[StrategyProfile]) -> StrategyComparison:
    """Score and rank *strategies* across all five dimensions.

    Parameters
    ----------
    strategies : list of StrategyProfile
        At least one strategy required.

    Returns
    -------
    StrategyComparison
    """
    if not strategies:
        raise ValueError("score_strategies requires at least one strategy")

    names = [s.name for s in strategies]

    # 1. Compute raw values per dimension (one list per dim, ordered by strategy)
    raw_per_dim: Dict[str, List[float]] = {
        dim: [_raw_value(s, dim) for s in strategies]
        for dim in _DIMENSIONS
    }

    # 2. Normalise each dimension independently
    norm_per_dim: Dict[str, List[float]] = {
        dim: _normalize(raw_per_dim[dim])
        for dim in _DIMENSIONS
    }

    # 3. Build DimensionScore objects for each strategy
    dimension_scores: Dict[str, List[DimensionScore]] = {}
    for i, s in enumerate(strategies):
        ds_list: List[DimensionScore] = []
        for dim in _DIMENSIONS:
            w = _WEIGHTS[dim]
            raw = raw_per_dim[dim][i]
            norm = norm_per_dim[dim][i]
            ds_list.append(DimensionScore(
                dimension=dim,
                raw_value=raw,
                normalized_score=norm,
                weight=w,
                weighted_score=norm * w,
            ))
        dimension_scores[s.name] = ds_list

    # 4. Composite score = sum of weighted dimension scores
    composite_scores: Dict[str, float] = {
        s.name: sum(ds.weighted_score for ds in dimension_scores[s.name])
        for s in strategies
    }

    # 5. Rank strategies by composite score descending
    ranked_strategies = sorted(names, key=lambda n: composite_scores[n], reverse=True)

    # 6. Best in each dimension = strategy with highest *normalised* score
    def _best_in(dim: str) -> str:
        norms = norm_per_dim[dim]
        best_i = max(range(len(strategies)), key=lambda i: norms[i])
        return strategies[best_i].name

    best_yield = _best_in("YIELD")
    best_safety = _best_in("SAFETY")
    best_sustainability = _best_in("SUSTAINABILITY")
    best_liquidity = _best_in("LIQUIDITY")
    best_accessibility = _best_in("ACCESSIBILITY")

    # 7. best_overall = highest composite (first in ranked list)
    best_overall = ranked_strategies[0]

    # 8. best_risk_adjusted = max(apy / max(risk_score, 0.1))
    best_risk_adjusted = max(
        strategies,
        key=lambda s: s.apy / max(s.risk_score, 0.1),
    ).name

    # 9. best_for_small_capital = lowest min_capital among strategies with composite > 50
    eligible = [s for s in strategies if composite_scores[s.name] > 50.0]
    if eligible:
        best_for_small_capital = min(eligible, key=lambda s: s.min_capital_usd).name
    else:
        # Fallback: return the strategy with highest composite score
        best_for_small_capital = ranked_strategies[0]

    return StrategyComparison(
        strategies=strategies,
        dimension_scores=dimension_scores,
        composite_scores=composite_scores,
        ranked_strategies=ranked_strategies,
        best_yield=best_yield,
        best_safety=best_safety,
        best_sustainability=best_sustainability,
        best_liquidity=best_liquidity,
        best_accessibility=best_accessibility,
        best_overall=best_overall,
        best_risk_adjusted=best_risk_adjusted,
        best_for_small_capital=best_for_small_capital,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer JSON, max 100 entries, atomic write)
# ---------------------------------------------------------------------------

def _dim_score_to_dict(ds: DimensionScore) -> dict:
    return {
        "dimension": ds.dimension,
        "raw_value": ds.raw_value,
        "normalized_score": ds.normalized_score,
        "weight": ds.weight,
        "weighted_score": ds.weighted_score,
    }


def _profile_to_dict(s: StrategyProfile) -> dict:
    return {
        "name": s.name,
        "apy": s.apy,
        "real_yield_ratio": s.real_yield_ratio,
        "risk_score": s.risk_score,
        "sustainability_index": s.sustainability_index,
        "liquidity_usd": s.liquidity_usd,
        "min_capital_usd": s.min_capital_usd,
        "lock_period_days": s.lock_period_days,
    }


def _comparison_to_dict(comparison: StrategyComparison) -> dict:
    return {
        "strategies": [_profile_to_dict(s) for s in comparison.strategies],
        "dimension_scores": {
            name: [_dim_score_to_dict(ds) for ds in dsl]
            for name, dsl in comparison.dimension_scores.items()
        },
        "composite_scores": comparison.composite_scores,
        "ranked_strategies": comparison.ranked_strategies,
        "best_yield": comparison.best_yield,
        "best_safety": comparison.best_safety,
        "best_sustainability": comparison.best_sustainability,
        "best_liquidity": comparison.best_liquidity,
        "best_accessibility": comparison.best_accessibility,
        "best_overall": comparison.best_overall,
        "best_risk_adjusted": comparison.best_risk_adjusted,
        "best_for_small_capital": comparison.best_for_small_capital,
        "saved_to": comparison.saved_to,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def save_results(
    comparison: StrategyComparison,
    data_dir: Optional[Path] = None,
) -> str:
    """Persist *comparison* to the ring-buffer JSON log.  Returns file path."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    log_path = data_dir / _LOG_FILENAME

    # Load existing entries
    if log_path.exists():
        try:
            existing: list = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    else:
        existing = []

    # Append new entry
    existing.append(_comparison_to_dict(comparison))

    # Trim to ring-buffer cap
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    # Atomic write: tmp → os.replace
    atomic_save(existing, str(log_path))
    comparison.saved_to = str(log_path)
    return str(log_path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Return all saved comparisons from the ring-buffer JSON."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_path = Path(data_dir) / _LOG_FILENAME
    if not log_path.exists():
        return []
    try:
        return json.loads(log_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo_strategies() -> List[StrategyProfile]:
    return [
        StrategyProfile(
            name="Aave V3 USDC",
            apy=3.5,
            real_yield_ratio=0.95,
            risk_score=15.0,
            sustainability_index=80.0,
            liquidity_usd=500_000_000.0,
            min_capital_usd=100.0,
            lock_period_days=0,
        ),
        StrategyProfile(
            name="Morpho Steakhouse",
            apy=6.5,
            real_yield_ratio=0.85,
            risk_score=25.0,
            sustainability_index=70.0,
            liquidity_usd=50_000_000.0,
            min_capital_usd=1_000.0,
            lock_period_days=0,
        ),
        StrategyProfile(
            name="Delta-Neutral sUSDe",
            apy=27.5,
            real_yield_ratio=0.60,
            risk_score=60.0,
            sustainability_index=45.0,
            liquidity_usd=10_000_000.0,
            min_capital_usd=10_000.0,
            lock_period_days=7,
        ),
    ]


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    run = "--run" in argv
    data_dir_arg: Optional[Path] = None
    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir_arg = Path(argv[idx + 1])

    comparison = score_strategies(_demo_strategies())

    print("StrategyComparisonMatrix")
    print(f"  ranked_strategies   : {comparison.ranked_strategies}")
    print(f"  best_overall        : {comparison.best_overall}")
    print(f"  best_risk_adjusted  : {comparison.best_risk_adjusted}")
    print(f"  best_for_small_cap  : {comparison.best_for_small_capital}")
    print(f"  best_yield          : {comparison.best_yield}")
    print(f"  best_safety         : {comparison.best_safety}")
    print(f"  best_sustainability : {comparison.best_sustainability}")
    print(f"  best_liquidity      : {comparison.best_liquidity}")
    print(f"  best_accessibility  : {comparison.best_accessibility}")
    print()
    print("  Composite scores:")
    for name in comparison.ranked_strategies:
        score = comparison.composite_scores[name]
        print(f"    {name:<30}: {score:.2f}")

    if run:
        path = save_results(comparison, data_dir=data_dir_arg)
        print(f"\n  Saved to: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
