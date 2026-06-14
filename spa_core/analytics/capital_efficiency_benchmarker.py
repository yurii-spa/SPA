"""
MP-741: CapitalEfficiencyBenchmarker
Benchmarks capital efficiency across DeFi strategies —
measuring how effectively deployed capital generates yield
relative to locked capital, comparing utilization rates
and yield-per-dollar metrics.

Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RING_BUFFER_CAP = 100
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = "capital_efficiency_log.json"

LABEL_EXCELLENT = "EXCELLENT"
LABEL_GOOD = "GOOD"
LABEL_ADEQUATE = "ADEQUATE"
LABEL_POOR = "POOR"

RECOMMENDATIONS = {
    LABEL_EXCELLENT: "Top-tier efficiency — maintain allocation.",
    LABEL_GOOD: "Above-average — consider modest increase.",
    LABEL_ADEQUATE: "Room to improve — review fee structure.",
    LABEL_POOR: "Underperforming peers — consider reallocation.",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EfficiencyMetrics:
    strategy_name: str
    protocol: str

    capital_deployed_usd: float   # actively earning yield
    capital_locked_usd: float     # deployed + any collateral/margin locked

    gross_apy: float
    fee_apy: float                # protocol fees (subtract from gross)
    net_apy: float                # gross - fee_apy

    # Efficiency metrics
    capital_utilization: float         # deployed / locked * 100
    yield_per_1000_usd: float          # net_apy / 100 * 1000 (annual $ per $1000 deployed)
    effective_yield_on_locked: float   # net_apy * capital_utilization / 100 (yield on total locked)

    # Benchmarks vs peer average
    apy_vs_peer_avg: float             # net_apy - peer_avg_apy
    efficiency_vs_peer_avg: float      # effective_yield - peer_avg_effective_yield

    # Ranking
    efficiency_score: float            # 0-100 composite
    efficiency_label: str              # EXCELLENT / GOOD / ADEQUATE / POOR

    recommendation: str


@dataclass
class EfficiencyBenchmarkResult:
    strategies: List[EfficiencyMetrics] = field(default_factory=list)

    peer_avg_apy: float = 0.0
    peer_avg_effective_yield: float = 0.0
    peer_avg_utilization: float = 0.0

    top_strategy: str = ""      # highest efficiency_score
    bottom_strategy: str = ""   # lowest efficiency_score

    # Distribution
    excellent_count: int = 0
    poor_count: int = 0

    benchmark_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def compute_effective_yield(net_apy: float, utilization: float) -> float:
    """Yield on total locked capital: net_apy * utilization / 100."""
    return net_apy * utilization / 100


def compute_yield_per_1000(net_apy: float) -> float:
    """Annual $ per $1,000 deployed: net_apy / 100 * 1000."""
    return net_apy / 100 * 1000


def rank_strategies(metrics_list: List[EfficiencyMetrics], key_fn: Callable) -> Dict[str, int]:
    """
    Rank strategies by key_fn (descending — highest = rank 1).
    Returns {strategy_name: rank}.
    """
    sorted_by_key = sorted(metrics_list, key=key_fn, reverse=True)
    return {m.strategy_name: i + 1 for i, m in enumerate(sorted_by_key)}


def compute_efficiency_score(apy_rank: int, util_rank: int, n_strategies: int) -> float:
    """
    Composite score 0-100:
      50% from yield rank + 50% from utilization rank.
      Higher rank number = worse → flip to score.

    Formula: ((n - apy_rank) + (n - util_rank)) / (2 * (n - 1)) * 100
    Edge: n==1 → 100.
    """
    if n_strategies <= 1:
        return 100.0
    return ((n_strategies - apy_rank) + (n_strategies - util_rank)) / (2 * (n_strategies - 1)) * 100


def efficiency_label_from_score(score: float) -> str:
    """EXCELLENT >=80 | GOOD >=60 | ADEQUATE >=40 | POOR <40."""
    if score >= 80.0:
        return LABEL_EXCELLENT
    elif score >= 60.0:
        return LABEL_GOOD
    elif score >= 40.0:
        return LABEL_ADEQUATE
    else:
        return LABEL_POOR


def benchmark(strategies_data: List[dict]) -> EfficiencyBenchmarkResult:
    """
    Benchmark capital efficiency across strategies.

    strategies_data: List[dict] with keys:
        {strategy_name, protocol, capital_deployed_usd,
         capital_locked_usd, gross_apy, fee_apy}
    """
    n = len(strategies_data)

    # --- Pass 1: compute basic per-strategy metrics ---
    partials = []
    for s in strategies_data:
        net_apy = s["gross_apy"] - s["fee_apy"]
        locked = s["capital_locked_usd"]
        capital_utilization = (
            s["capital_deployed_usd"] / locked * 100 if locked > 0 else 0.0
        )
        effective_yield = compute_effective_yield(net_apy, capital_utilization)
        yield_per_k = compute_yield_per_1000(net_apy)
        partials.append(
            {
                "strategy_name": s["strategy_name"],
                "protocol": s["protocol"],
                "capital_deployed_usd": s["capital_deployed_usd"],
                "capital_locked_usd": locked,
                "gross_apy": s["gross_apy"],
                "fee_apy": s["fee_apy"],
                "net_apy": net_apy,
                "capital_utilization": capital_utilization,
                "yield_per_1000_usd": yield_per_k,
                "effective_yield_on_locked": effective_yield,
            }
        )

    # --- Peer averages ---
    peer_avg_apy = sum(p["net_apy"] for p in partials) / n if n > 0 else 0.0
    peer_avg_effective_yield = (
        sum(p["effective_yield_on_locked"] for p in partials) / n if n > 0 else 0.0
    )
    peer_avg_utilization = (
        sum(p["capital_utilization"] for p in partials) / n if n > 0 else 0.0
    )

    # --- Build preliminary EfficiencyMetrics (no rank/score yet) ---
    prelim: List[EfficiencyMetrics] = []
    for p in partials:
        prelim.append(
            EfficiencyMetrics(
                strategy_name=p["strategy_name"],
                protocol=p["protocol"],
                capital_deployed_usd=p["capital_deployed_usd"],
                capital_locked_usd=p["capital_locked_usd"],
                gross_apy=p["gross_apy"],
                fee_apy=p["fee_apy"],
                net_apy=p["net_apy"],
                capital_utilization=p["capital_utilization"],
                yield_per_1000_usd=p["yield_per_1000_usd"],
                effective_yield_on_locked=p["effective_yield_on_locked"],
                apy_vs_peer_avg=p["net_apy"] - peer_avg_apy,
                efficiency_vs_peer_avg=p["effective_yield_on_locked"] - peer_avg_effective_yield,
                efficiency_score=0.0,        # filled in below
                efficiency_label="",         # filled in below
                recommendation="",           # filled in below
            )
        )

    # --- Rankings ---
    apy_ranks = rank_strategies(prelim, key_fn=lambda m: m.net_apy)
    util_ranks = rank_strategies(prelim, key_fn=lambda m: m.effective_yield_on_locked)

    # --- Final metrics with scores ---
    final: List[EfficiencyMetrics] = []
    for m in prelim:
        score = compute_efficiency_score(
            apy_ranks[m.strategy_name],
            util_ranks[m.strategy_name],
            n,
        )
        label = efficiency_label_from_score(score)
        m.efficiency_score = score
        m.efficiency_label = label
        m.recommendation = RECOMMENDATIONS[label]
        final.append(m)

    # --- Result-level aggregates ---
    top = max(final, key=lambda m: m.efficiency_score)
    bottom = min(final, key=lambda m: m.efficiency_score)
    excellent_count = sum(1 for m in final if m.efficiency_label == LABEL_EXCELLENT)
    poor_count = sum(1 for m in final if m.efficiency_label == LABEL_POOR)

    benchmark_summary = (
        f"{n} strategies benchmarked; top: {top.strategy_name} "
        f"(score {top.efficiency_score:.0f}); "
        f"excellent: {excellent_count}, poor: {poor_count}."
    )

    return EfficiencyBenchmarkResult(
        strategies=final,
        peer_avg_apy=peer_avg_apy,
        peer_avg_effective_yield=peer_avg_effective_yield,
        peer_avg_utilization=peer_avg_utilization,
        top_strategy=top.strategy_name,
        bottom_strategy=bottom.strategy_name,
        excellent_count=excellent_count,
        poor_count=poor_count,
        benchmark_summary=benchmark_summary,
    )


def compare_to_benchmark(
    strategy: EfficiencyMetrics,
    benchmark_apy: float,
    benchmark_effective: float,
) -> dict:
    """Return delta dict comparing strategy against external benchmark."""
    return {
        "strategy_name": strategy.strategy_name,
        "delta_apy": strategy.net_apy - benchmark_apy,
        "delta_effective_yield": strategy.effective_yield_on_locked - benchmark_effective,
        "outperforms_apy": strategy.net_apy > benchmark_apy,
        "outperforms_effective": strategy.effective_yield_on_locked > benchmark_effective,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _log_path(data_dir: Optional[str] = None) -> str:
    base = data_dir or DEFAULT_DATA_DIR
    return os.path.join(base, LOG_FILE)


def _result_to_dict(result: EfficiencyBenchmarkResult) -> dict:
    def metrics_to_dict(m: EfficiencyMetrics) -> dict:
        return {
            "strategy_name": m.strategy_name,
            "protocol": m.protocol,
            "capital_deployed_usd": m.capital_deployed_usd,
            "capital_locked_usd": m.capital_locked_usd,
            "gross_apy": m.gross_apy,
            "fee_apy": m.fee_apy,
            "net_apy": m.net_apy,
            "capital_utilization": m.capital_utilization,
            "yield_per_1000_usd": m.yield_per_1000_usd,
            "effective_yield_on_locked": m.effective_yield_on_locked,
            "apy_vs_peer_avg": m.apy_vs_peer_avg,
            "efficiency_vs_peer_avg": m.efficiency_vs_peer_avg,
            "efficiency_score": m.efficiency_score,
            "efficiency_label": m.efficiency_label,
            "recommendation": m.recommendation,
        }

    return {
        "timestamp": time.time(),
        "strategies": [metrics_to_dict(m) for m in result.strategies],
        "peer_avg_apy": result.peer_avg_apy,
        "peer_avg_effective_yield": result.peer_avg_effective_yield,
        "peer_avg_utilization": result.peer_avg_utilization,
        "top_strategy": result.top_strategy,
        "bottom_strategy": result.bottom_strategy,
        "excellent_count": result.excellent_count,
        "poor_count": result.poor_count,
        "benchmark_summary": result.benchmark_summary,
        "saved_to": result.saved_to,
    }


def save_results(result: EfficiencyBenchmarkResult, data_dir: Optional[str] = None) -> str:
    """Append result to ring-buffer log (cap=100). Returns path written."""
    path = _log_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    history = load_history(data_dir)
    history.append(_result_to_dict(result))
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp, path)

    result.saved_to = path
    return path


def load_history(data_dir: Optional[str] = None) -> list:
    """Load efficiency log. Returns empty list if file missing/corrupt."""
    path = _log_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, IOError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _demo_run() -> None:
    """Quick smoke-test with demo data."""
    strategies_data = [
        {
            "strategy_name": "Aave USDC Lending",
            "protocol": "Aave V3",
            "capital_deployed_usd": 50_000,
            "capital_locked_usd": 50_000,
            "gross_apy": 5.0,
            "fee_apy": 0.1,
        },
        {
            "strategy_name": "E-Mode Looping",
            "protocol": "Aave V3",
            "capital_deployed_usd": 150_000,
            "capital_locked_usd": 200_000,
            "gross_apy": 6.5,
            "fee_apy": 0.5,
        },
        {
            "strategy_name": "Delta Neutral sUSDe",
            "protocol": "Ethena",
            "capital_deployed_usd": 80_000,
            "capital_locked_usd": 100_000,
            "gross_apy": 28.0,
            "fee_apy": 0.5,
        },
    ]

    result = benchmark(strategies_data)
    print(f"Peer Avg APY         : {result.peer_avg_apy:.2f}%")
    print(f"Top Strategy         : {result.top_strategy}")
    print(f"Bottom Strategy      : {result.bottom_strategy}")
    print(f"Excellent/Poor Count : {result.excellent_count}/{result.poor_count}")
    print(f"Summary              : {result.benchmark_summary}")
    for m in result.strategies:
        print(
            f"  {m.strategy_name}: net={m.net_apy:.1f}% util={m.capital_utilization:.0f}% "
            f"score={m.efficiency_score:.0f} [{m.efficiency_label}]"
        )


if __name__ == "__main__":
    import sys

    if "--run" in sys.argv:
        data_dir = None
        if "--data-dir" in sys.argv:
            idx = sys.argv.index("--data-dir")
            data_dir = sys.argv[idx + 1]
        result = benchmark([])
        save_results(result, data_dir)
        print(f"Saved to {result.saved_to}")
    else:
        _demo_run()
