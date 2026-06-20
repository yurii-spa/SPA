"""Performance Benchmark Tracker (MP-693) — Multi-Benchmark Comparison Engine.

Tracks portfolio performance against five standard DeFi / TradFi benchmarks:

    ETH_STAKING    : 3.50%  annual (ETH proof-of-stake yield)
    US_TREASURY_1Y : 4.40%  annual (1-year T-note)
    USDC_SAVINGS   : 5.00%  annual (Circle / Coinbase savings rate)
    DEFI_INDEX     : 6.50%  annual (hypothetical DeFi broad market index)
    RISK_FREE      : 3.00%  annual (minimum acceptable return)

For each benchmark the module computes an apples-to-apples period return by
scaling the annual rate by actual days: ``period_return = annual_rate * days / 365``.

Outperformance is expressed in basis-points (bps):
    outperformance_bps = (portfolio_period_return - benchmark_period_return) * 100

Performance tiers:
    ELITE         : beats all 5 benchmarks
    STRONG        : beats ≥ 4
    ADEQUATE      : beats ≥ 3
    WEAK          : beats ≥ 2
    UNDERPERFORMING : beats ≤ 1

Design constraints
------------------
* Pure stdlib — no external deps (no numpy / scipy / pandas / requests).
* Advisory / read-only analytics — never touches allocator / risk / execution.
* Atomic writes: tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Ring-buffer cap: MAX_ENTRIES = 100.

Public API
----------
``PerformanceBenchmarkTracker(data_dir="data")``

    track(portfolio_id, periods)       → PerformanceTrackingReport
    track_batch(items)                 → List[PerformanceTrackingReport]
    save_results(report)               → None  (atomic ring-buffer write)
    load_history()                     → List[dict]

Data file: data/benchmark_tracker_log.json  (ring-buffer, max 100 entries)

MP-693.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

DATA_FILENAME = "benchmark_tracker_log.json"
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Standard DeFi benchmarks (annual %)
# ---------------------------------------------------------------------------

BENCHMARKS: Dict[str, float] = {
    "ETH_STAKING":    3.50,   # ETH proof-of-stake yield %
    "US_TREASURY_1Y": 4.40,   # 1-year T-note %
    "USDC_SAVINGS":   5.00,   # Circle/Coinbase savings rate %
    "DEFI_INDEX":     6.50,   # hypothetical DeFi broad market index %
    "RISK_FREE":      3.00,   # minimum acceptable return %
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PerformancePeriod:
    """A single discrete measurement period (e.g. one quarter)."""

    period_label: str          # human label, e.g. "2025-Q1"
    portfolio_return_pct: float
    days_in_period: int


@dataclass
class BenchmarkComparison:
    """Portfolio vs one benchmark for a given total period."""

    benchmark_name: str
    benchmark_return_pct: float   # period-adjusted benchmark return
    portfolio_return_pct: float   # total portfolio return over period
    outperformance_bps: float     # (portfolio - benchmark) * 100
    is_outperforming: bool
    rank: int                     # 1 = highest outperformance


@dataclass
class PerformanceTrackingReport:
    """Full multi-benchmark tracking report for one portfolio."""

    portfolio_id: str
    total_return_pct: float
    annualized_return_pct: float       # annualized over total days
    comparisons: List[BenchmarkComparison]  # sorted by outperformance_bps desc
    beating_count: int                 # how many benchmarks beaten
    losing_count: int                  # how many benchmarks lost to
    best_relative_benchmark: str       # benchmark where outperformance is highest
    worst_relative_benchmark: str      # benchmark where underperformance is worst
    performance_tier: str              # ELITE / STRONG / ADEQUATE / WEAK / UNDERPERFORMING
    narrative: str
    generated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------


def annualized_return(total_return_pct: float, total_days: int) -> float:
    """Annualize a total return over *total_days*.

    Formula: ((1 + total_return/100) ** (365 / total_days) - 1) * 100

    Edge case: if total_days <= 0, returns total_return unchanged.
    """
    if total_days <= 0:
        return total_return_pct
    base = 1.0 + total_return_pct / 100.0
    # Guard against negative base (deep loss)
    if base <= 0:
        return -100.0
    return (base ** (365.0 / total_days) - 1.0) * 100.0


def benchmark_period_return(annual_rate_pct: float, total_days: int) -> float:
    """Scale an annual benchmark rate to a *total_days* period.

    Simple linear scaling: annual_rate * days / 365

    Edge case: if total_days <= 0, returns 0.
    """
    if total_days <= 0:
        return 0.0
    return annual_rate_pct * total_days / 365.0


def outperformance_bps(portfolio_return_pct: float, benchmark_return_pct: float) -> float:
    """Return outperformance in basis-points.

    outperformance_bps = (portfolio - benchmark) * 100
    """
    return (portfolio_return_pct - benchmark_return_pct) * 100.0


def _performance_tier(beating_count: int) -> str:
    """Classify portfolio performance tier based on number of beaten benchmarks."""
    n_benchmarks = len(BENCHMARKS)  # 5
    if beating_count >= n_benchmarks:
        return "ELITE"
    if beating_count >= 4:
        return "STRONG"
    if beating_count >= 3:
        return "ADEQUATE"
    if beating_count >= 2:
        return "WEAK"
    return "UNDERPERFORMING"


# ---------------------------------------------------------------------------
# Main tracker class
# ---------------------------------------------------------------------------


class PerformanceBenchmarkTracker:
    """Multi-benchmark performance tracker for DeFi yield portfolios.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory where ``benchmark_tracker_log.json`` is written.
        Defaults to ``<repo_root>/data``.
    """

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_file = self._data_dir / DATA_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(
        self,
        portfolio_id: str,
        periods: List[PerformancePeriod],
    ) -> PerformanceTrackingReport:
        """Compute multi-benchmark comparison for a list of performance periods.

        Parameters
        ----------
        portfolio_id : str
            Caller-supplied portfolio identifier.
        periods : list[PerformancePeriod]
            One entry per measurement period (returns are summed).

        Returns
        -------
        PerformanceTrackingReport

        Raises
        ------
        ValueError
            If ``periods`` is empty.
        """
        if not periods:
            raise ValueError("periods must contain at least one PerformancePeriod")

        total_return = sum(p.portfolio_return_pct for p in periods)
        total_days = sum(p.days_in_period for p in periods)

        ann_return = annualized_return(total_return, total_days)

        comparisons: List[BenchmarkComparison] = []
        for bname, annual_rate in BENCHMARKS.items():
            bperiod_ret = benchmark_period_return(annual_rate, total_days)
            bps = outperformance_bps(total_return, bperiod_ret)
            comparisons.append(
                BenchmarkComparison(
                    benchmark_name=bname,
                    benchmark_return_pct=bperiod_ret,
                    portfolio_return_pct=total_return,
                    outperformance_bps=bps,
                    is_outperforming=bps > 0,
                    rank=0,  # filled below
                )
            )

        # Sort by outperformance descending, then assign ranks
        comparisons.sort(key=lambda c: c.outperformance_bps, reverse=True)
        for i, comp in enumerate(comparisons):
            comp.rank = i + 1

        beating_count = sum(1 for c in comparisons if c.is_outperforming)
        losing_count = len(comparisons) - beating_count

        best_rel = comparisons[0].benchmark_name    # highest outperformance
        worst_rel = comparisons[-1].benchmark_name  # lowest outperformance

        tier = _performance_tier(beating_count)

        best_bps = comparisons[0].outperformance_bps
        narrative = (
            f"Portfolio {portfolio_id} returned {total_return:.2f}% "
            f"({ann_return:.2f}% ann.). "
            f"Beats {beating_count}/{len(BENCHMARKS)} benchmarks. "
            f"Best vs {best_rel}: +{best_bps:.0f}bps. "
            f"Assessment: {tier}."
        )

        return PerformanceTrackingReport(
            portfolio_id=portfolio_id,
            total_return_pct=total_return,
            annualized_return_pct=ann_return,
            comparisons=comparisons,
            beating_count=beating_count,
            losing_count=losing_count,
            best_relative_benchmark=best_rel,
            worst_relative_benchmark=worst_rel,
            performance_tier=tier,
            narrative=narrative,
        )

    def track_batch(
        self,
        items: List[Tuple[str, List[PerformancePeriod]]],
    ) -> List[PerformanceTrackingReport]:
        """Track multiple portfolios in one call.

        Parameters
        ----------
        items : list of (portfolio_id, periods) tuples

        Returns
        -------
        list[PerformanceTrackingReport]
            Empty list if *items* is empty.
        """
        return [self.track(pid, periods) for pid, periods in items]

    def save_results(self, report: PerformanceTrackingReport) -> None:
        """Persist report to ring-buffer JSON (max MAX_ENTRIES).

        Uses atomic tmp + os.replace write pattern.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        history = self.load_history()

        entry = asdict(report)
        history.append(entry)

        if len(history) > MAX_ENTRIES:
            history = history[-MAX_ENTRIES:]

        _atomic_write(self._data_file, history)

    def load_history(self) -> List[dict]:
        """Load ring-buffer history from disk.

        Returns empty list if file is missing or corrupt.
        """
        if not self._data_file.exists():
            return []
        try:
            with self._data_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: object) -> None:
    """Write *payload* to *path* atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(payload, str(path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_demo_periods() -> List[PerformancePeriod]:
    """Return representative demo periods for CLI smoke-test."""
    return [
        PerformancePeriod("2026-Q1", portfolio_return_pct=2.10, days_in_period=90),
        PerformancePeriod("2026-Q2", portfolio_return_pct=2.30, days_in_period=91),
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MP-693 Performance Benchmark Tracker")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run",   action="store_true", help="Compute and write to data/")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_dir = args.data_dir or str(_DEFAULT_DATA_DIR)
    tracker = PerformanceBenchmarkTracker(data_dir=data_dir)
    periods = _build_demo_periods()
    report = tracker.track("demo_portfolio", periods)

    print(report.narrative)
    print(f"  Annualized return: {report.annualized_return_pct:.2f}%")
    print(f"  Tier: {report.performance_tier}")
    for c in report.comparisons:
        sign = "+" if c.outperformance_bps >= 0 else ""
        print(f"  [{c.rank}] vs {c.benchmark_name}: {sign}{c.outperformance_bps:.1f}bps")

    if args.run:
        tracker.save_results(report)
        print(f"  ✓ Saved to {tracker._data_file}")

    sys.exit(0)
