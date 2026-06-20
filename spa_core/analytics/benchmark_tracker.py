"""Benchmark Tracker (MP-607).

Сравнивает доходность портфеля SPA с:
  1. T-Bill Rate (risk-free rate):     ~4.5%  (обновляется вручную)
  2. Simple USDC Hold:                 ~4.0%  (базовый Aave USDC mainnet)
  3. ETH Staking:                      ~3.5%  (liquid staking baseline, stETH)
  4. Best Available (best adapter):    dynamic из adapter_status.json

Вердикт:
  ALPHA+:    excess vs best_benchmark > 1.5%
  ALPHA:     excess vs best_benchmark > 0.3%
  BENCHMARK: |excess| <= 0.3%
  LAGGING:   excess < -0.3%

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.benchmark_tracker --check
    python3 -m spa_core.analytics.benchmark_tracker --run
    python3 -m spa_core.analytics.benchmark_tracker --run --data-dir /path/to/data

MP-607.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "benchmark_report.json"
RING_BUFFER_MAX = 30

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keys верхнего уровня adapter_status.json, которые не являются адаптерами
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode", "live_apy_enabled",
    "mev_protection", "adapters", "morpho_steakhouse", "base_gas_monitor",
})

# Verdict thresholds (excess return vs best benchmark, %)
_ALPHA_PLUS_THRESHOLD: float = 1.5
_ALPHA_THRESHOLD: float = 0.3
_BENCHMARK_THRESHOLD: float = 0.3  # |excess| <= this → BENCHMARK

# Assumed volatility for information ratio (simplified)
_ASSUMED_VOL: float = 1.0

# Default portfolio data when attribution file is missing
_DEFAULT_PORTFOLIO_APY: float = 5.0
_DEFAULT_PORTFOLIO_USD: float = 100_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float:
    """Coerce value to finite float; return 0.0 on any failure."""
    if isinstance(val, bool):
        return 0.0
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_apy_from_adapter(data: Dict[str, Any]) -> float:
    """Extract APY % from an adapter data dict.

    Tries: ``apy_pct`` → ``apy`` → first value from ``mock_apy[chain][asset]``.
    Returns 0.0 when nothing usable found.
    """
    for key in ("apy_pct", "apy"):
        val = data.get(key)
        if not isinstance(val, bool) and isinstance(val, (int, float)):
            f = float(val)
            if math.isfinite(f) and f > 0:
                return f
    mock = data.get("mock_apy")
    if isinstance(mock, dict):
        for chain_data in mock.values():
            if isinstance(chain_data, dict):
                for apy_val in chain_data.values():
                    if not isinstance(apy_val, bool) and isinstance(apy_val, (int, float)):
                        f = float(apy_val)
                        if math.isfinite(f) and f > 0:
                            return f
    return 0.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Comparison result for one benchmark.

    Attributes
    ----------
    name                : "T-Bill" / "USDC Hold" / "ETH Staking" / "Best Adapter"
    apy_pct             : Benchmark APY in %.
    portfolio_apy_pct   : Portfolio APY in %.
    excess_return_pct   : portfolio_apy - benchmark_apy.
    information_ratio   : excess_return / ASSUMED_VOL (simplified).
    outperforming       : True when excess_return_pct > 0.
    """

    name: str
    apy_pct: float
    portfolio_apy_pct: float
    excess_return_pct: float
    information_ratio: float
    outperforming: bool

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass
class BenchmarkReport:
    """Full benchmark comparison snapshot.

    Attributes
    ----------
    generated_at            : ISO-8601 UTC timestamp.
    portfolio_apy_pct       : Portfolio effective APY %.
    portfolio_allocated_usd : Total deployed capital USD.
    benchmarks              : List of BenchmarkResult (all 4).
    best_benchmark_name     : Benchmark with highest APY (hardest to beat).
    best_benchmark_apy      : That benchmark's APY %.
    overall_excess_return   : excess vs best_benchmark_apy.
    annual_alpha_usd        : overall_excess_return * portfolio_allocated / 100.
    outperforming_count     : How many benchmarks we beat (excess > 0).
    total_benchmarks        : Total number of benchmarks compared.
    verdict                 : "ALPHA+" / "ALPHA" / "BENCHMARK" / "LAGGING".
    """

    generated_at: str
    portfolio_apy_pct: float
    portfolio_allocated_usd: float
    benchmarks: List[BenchmarkResult] = field(default_factory=list)
    best_benchmark_name: str = ""
    best_benchmark_apy: float = 0.0
    overall_excess_return: float = 0.0
    annual_alpha_usd: float = 0.0
    outperforming_count: int = 0
    total_benchmarks: int = 0
    verdict: str = "BENCHMARK"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# BenchmarkTracker
# ---------------------------------------------------------------------------


class BenchmarkTracker:
    """Tracks portfolio performance vs benchmarks.

    Benchmarks compared:
      * T-Bill (4.50%) — US 3-month T-bill rate (risk-free)
      * USDC Hold (4.00%) — simple Aave USDC mainnet
      * ETH Staking (3.50%) — liquid staking (stETH baseline)
      * Best Adapter — dynamic: best single adapter APY from adapter_status.json

    Verdict thresholds (vs best_benchmark):
      ALPHA+:    excess > 1.5%
      ALPHA:     excess > 0.3%
      BENCHMARK: |excess| <= 0.3%
      LAGGING:   excess < -0.3%

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing data files. Defaults to repo ``data/``.
    """

    # Static benchmarks (update when market rates change)
    BENCHMARKS: Dict[str, float] = {
        "T-Bill": 4.50,       # US 3-month T-bill rate
        "USDC Hold": 4.00,    # simple Aave USDC mainnet
        "ETH Staking": 3.50,  # liquid staking (stETH)
    }

    ASSUMED_VOL: float = _ASSUMED_VOL

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_portfolio_data(self) -> Dict[str, Any]:
        """Load portfolio APY and allocated USD from yield_attribution_tracker.json.

        Reads ``latest.effective_apy_pct`` and ``latest.total_allocated_usd``.

        Returns
        -------
        dict
            ``{"effective_apy_pct": float, "total_allocated_usd": float}``

        Falls back to defaults (5.0%, $100,000) when file is missing or malformed.
        """
        path = self.data_dir / "yield_attribution_tracker.json"
        defaults = {
            "effective_apy_pct": _DEFAULT_PORTFOLIO_APY,
            "total_allocated_usd": _DEFAULT_PORTFOLIO_USD,
        }
        if not path.exists():
            return defaults
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return defaults
        if not isinstance(raw, dict):
            return defaults
        latest = raw.get("latest")
        if not isinstance(latest, dict):
            return defaults
        apy = _safe_float(latest.get("effective_apy_pct", 0))
        allocated = _safe_float(latest.get("total_allocated_usd", 0))
        if apy <= 0:
            apy = _DEFAULT_PORTFOLIO_APY
        if allocated <= 0:
            allocated = _DEFAULT_PORTFOLIO_USD
        return {
            "effective_apy_pct": round(apy, 4),
            "total_allocated_usd": round(allocated, 2),
        }

    def get_best_adapter_apy(self) -> float:
        """Get the best single adapter APY from adapter_status.json.

        Reads all adapters and returns the maximum APY, representing the
        "naive optimal strategy" — just deploy everything in the best adapter.

        Returns
        -------
        float
            Maximum adapter APY in %. Falls back to 5.0 if file is missing
            or no valid APY found.
        """
        path = self.data_dir / "adapter_status.json"
        fallback = 5.0
        if not path.exists():
            return fallback
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return fallback
        if not isinstance(raw, dict):
            return fallback

        apys: List[float] = []

        # Top-level protocol entries
        for key, val in raw.items():
            if key in _SKIP_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            apy = _extract_apy_from_adapter(val)
            if apy > 0:
                apys.append(apy)

        # "adapters" array
        adapters_list = raw.get("adapters")
        if isinstance(adapters_list, list):
            for item in adapters_list:
                if not isinstance(item, dict):
                    continue
                apy = _extract_apy_from_adapter(item)
                if apy > 0:
                    apys.append(apy)

        if not apys:
            return fallback
        return round(max(apys), 4)

    # -----------------------------------------------------------------------
    # Core computation
    # -----------------------------------------------------------------------

    def compute_benchmark(
        self,
        name: str,
        bench_apy: float,
        portfolio_apy: float,
    ) -> BenchmarkResult:
        """Compute comparison result for one benchmark.

        Parameters
        ----------
        name          : Benchmark name.
        bench_apy     : Benchmark APY %.
        portfolio_apy : Portfolio APY %.

        Returns
        -------
        BenchmarkResult
        """
        excess = round(portfolio_apy - bench_apy, 6)
        ir = round(excess / self.ASSUMED_VOL, 6)
        outperforming = excess > 0
        return BenchmarkResult(
            name=name,
            apy_pct=round(bench_apy, 4),
            portfolio_apy_pct=round(portfolio_apy, 4),
            excess_return_pct=excess,
            information_ratio=ir,
            outperforming=outperforming,
        )

    def _determine_verdict(self, excess_vs_best: float) -> str:
        """Determine verdict based on excess return vs best benchmark.

        Parameters
        ----------
        excess_vs_best : portfolio_apy - best_benchmark_apy

        Returns
        -------
        str
            "ALPHA+" / "ALPHA" / "BENCHMARK" / "LAGGING"
        """
        if excess_vs_best > _ALPHA_PLUS_THRESHOLD:
            return "ALPHA+"
        if excess_vs_best > _ALPHA_THRESHOLD:
            return "ALPHA"
        if excess_vs_best >= -_BENCHMARK_THRESHOLD:
            return "BENCHMARK"
        return "LAGGING"

    def generate_report(self) -> BenchmarkReport:
        """Generate a full benchmark comparison report.

        Reads portfolio data and adapter status, computes all 4 benchmarks,
        and determines the verdict.

        Returns
        -------
        BenchmarkReport
        """
        now = datetime.now(timezone.utc).isoformat()
        portfolio = self.load_portfolio_data()
        portfolio_apy = portfolio["effective_apy_pct"]
        portfolio_usd = portfolio["total_allocated_usd"]

        # Build all benchmarks
        results: List[BenchmarkResult] = []

        # Static benchmarks
        for bench_name, bench_apy in self.BENCHMARKS.items():
            results.append(self.compute_benchmark(bench_name, bench_apy, portfolio_apy))

        # Dynamic: Best Adapter
        best_adapter_apy = self.get_best_adapter_apy()
        results.append(
            self.compute_benchmark("Best Adapter", best_adapter_apy, portfolio_apy)
        )

        # Determine best benchmark (highest APY = hardest to beat)
        best_result = max(results, key=lambda r: r.apy_pct)
        best_name = best_result.name
        best_apy = best_result.apy_pct

        overall_excess = round(portfolio_apy - best_apy, 6)
        annual_alpha = round(overall_excess * portfolio_usd / 100.0, 2)
        outperforming_count = sum(1 for r in results if r.outperforming)
        verdict = self._determine_verdict(overall_excess)

        return BenchmarkReport(
            generated_at=now,
            portfolio_apy_pct=round(portfolio_apy, 4),
            portfolio_allocated_usd=round(portfolio_usd, 2),
            benchmarks=results,
            best_benchmark_name=best_name,
            best_benchmark_apy=round(best_apy, 4),
            overall_excess_return=overall_excess,
            annual_alpha_usd=annual_alpha,
            outperforming_count=outperforming_count,
            total_benchmarks=len(results),
            verdict=verdict,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Generate and atomically save the benchmark report.

        Maintains a ring-buffer of the last :data:`RING_BUFFER_MAX` (30)
        snapshots in ``data/benchmark_report.json``.

        Parameters
        ----------
        output_path : str, optional
            Full file path override. Defaults to ``{data_dir}/benchmark_report.json``.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if output_path is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.data_dir / OUTPUT_FILENAME
        else:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing snapshots for ring-buffer
        snapshots: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    old = existing.get("snapshots", [])
                    if isinstance(old, list):
                        snapshots = [s for s in old if isinstance(s, dict)]
            except (ValueError, OSError):
                pass

        report_dict = self.to_dict()
        snapshots.append(report_dict)
        snapshots = snapshots[-RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "benchmark_tracker",
            "last_updated": report_dict.get("generated_at", ""),
            "latest": report_dict,
            "snapshots": snapshots,
        }

        # Atomic write: tmp → os.replace
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(self) -> str:
        """Format a Telegram-ready benchmark summary message (≤1500 chars).

        Includes: verdict emoji, portfolio APY, and comparison vs each benchmark.

        Returns
        -------
        str
            Telegram-formatted message, max 1500 characters.
        """
        report = self.generate_report()

        verdict_emoji = {
            "ALPHA+": "🏆",
            "ALPHA":  "✅",
            "BENCHMARK": "➡️",
            "LAGGING": "⚠️",
        }.get(report.verdict, "📊")

        lines: List[str] = [
            f"{verdict_emoji} BenchmarkTracker — {report.verdict}",
            f"📊 Portfolio APY: {report.portfolio_apy_pct:.2f}%"
            f"  |  Capital: ${report.portfolio_allocated_usd:,.0f}",
            f"🎯 Alpha: {report.overall_excess_return:+.2f}% vs {report.best_benchmark_name}"
            f"  →  ${report.annual_alpha_usd:,.0f}/yr",
            f"✓ Outperforming: {report.outperforming_count}/{report.total_benchmarks} benchmarks",
            "",
        ]

        for r in report.benchmarks:
            sign = "+" if r.excess_return_pct >= 0 else ""
            flag = "✅" if r.outperforming else "❌"
            lines.append(
                f"  {flag} {r.name}: {r.apy_pct:.2f}%"
                f"  →  {sign}{r.excess_return_pct:.2f}%"
                f"  (IR={r.information_ratio:+.2f})"
            )

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the current benchmark report."""
        report = self.generate_report()
        return {
            "generated_at": report.generated_at,
            "portfolio_apy_pct": report.portfolio_apy_pct,
            "portfolio_allocated_usd": report.portfolio_allocated_usd,
            "best_benchmark_name": report.best_benchmark_name,
            "best_benchmark_apy": report.best_benchmark_apy,
            "overall_excess_return": report.overall_excess_return,
            "annual_alpha_usd": report.annual_alpha_usd,
            "outperforming_count": report.outperforming_count,
            "total_benchmarks": report.total_benchmarks,
            "verdict": report.verdict,
            "benchmarks": [
                {
                    "name": r.name,
                    "apy_pct": r.apy_pct,
                    "portfolio_apy_pct": r.portfolio_apy_pct,
                    "excess_return_pct": r.excess_return_pct,
                    "information_ratio": r.information_ratio,
                    "outperforming": r.outperforming,
                }
                for r in report.benchmarks
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Benchmark Tracker (MP-607) — portfolio alpha vs benchmarks."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print report without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/benchmark_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    tracker = BenchmarkTracker(data_path=args.data_dir)
    report = tracker.generate_report()

    verdict_emoji = {
        "ALPHA+": "🏆",
        "ALPHA":  "✅",
        "BENCHMARK": "➡️",
        "LAGGING": "⚠️",
    }.get(report.verdict, "📊")

    print(f"=== BenchmarkTracker Report (MP-607) ===")
    print(f"Generated:   {report.generated_at}")
    print(f"Portfolio:   APY={report.portfolio_apy_pct:.4f}%  "
          f"allocated=${report.portfolio_allocated_usd:,.2f}")
    print(f"Verdict:     {verdict_emoji} {report.verdict}")
    print(f"Best bench:  {report.best_benchmark_name} ({report.best_benchmark_apy:.2f}%)")
    print(f"Alpha:       {report.overall_excess_return:+.4f}%  "
          f"(${report.annual_alpha_usd:,.2f}/yr)")
    print(f"Beating:     {report.outperforming_count}/{report.total_benchmarks} benchmarks")
    print("")
    print("Benchmark breakdown:")
    for r in report.benchmarks:
        flag = "✅" if r.outperforming else "❌"
        sign = "+" if r.excess_return_pct >= 0 else ""
        print(
            f"  {flag} {r.name:<16s}  bench={r.apy_pct:>5.2f}%  "
            f"excess={sign}{r.excess_return_pct:>+6.4f}%  "
            f"IR={r.information_ratio:>+6.4f}"
        )

    if args.run:
        path = tracker.save_report()
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
