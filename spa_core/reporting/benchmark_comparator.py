#!/usr/bin/env python3
"""Benchmark comparison (MP-1236) → ``data/benchmark_comparison.json``.

Compares the SPA paper track against fixed-APY reference benchmarks and reports,
per benchmark: annualised alpha, the information ratio (when a daily excess
series exists), and a frequentist estimate of how many track days are needed for
SPA's outperformance to be statistically significant at one-sided 95%.

Benchmarks (constant-APY proxies; a flat APY → constant daily return = apy/365 %):
* US T-Bills            — 5.0%  (risk-free baseline)
* ETH staking (stETH)   — 3.5%
* AAVE conservative     — 3.8%  (single-protocol)
* SPA target           — SPA's own annualised paper APY (alpha 0 by construction)

Statistical significance: one-sided t-style test of H0 ``mean daily excess ≤ 0``.
With sample mean ``m`` and stdev ``s`` of the daily excess series, the days
needed for ``t = m / (s/√N) ≥ 1.645`` is ``N = (1.645·s/m)²`` (m>0). If ``m ≤ 0``
SPA does not currently beat the benchmark → ``None`` (never, on current data).

Pure stdlib, offline, READ-ONLY, exit 0 always (no tracebacks). LLM FORBIDDEN.

CLI::

    python3 -m spa_core.reporting.benchmark_comparator --check   # default, no write
    python3 -m spa_core.reporting.benchmark_comparator --run     # atomic write
    python3 -m spa_core.reporting.benchmark_comparator --run --data-dir DIR
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.reporting._perf_common import (
    AAVE_CONSERVATIVE_APY_PCT,
    ANNUALIZATION_DAYS,
    DISCLAIMER,
    STETH_APY_PCT,
    TBILL_APY_PCT,
    annualize_return_pct,
    atomic_write_json,
    content_fingerprint,
    daily_returns_pct,
    load_equity_curve,
    now_iso,
    read_json,
    real_track_bars,
    rebuild_curve,
    rnd,
)

Z_95_ONE_SIDED = 1.645  # one-sided 95% normal critical value


def _compare_one(
    name: str,
    bench_apy_pct: float,
    spa_returns: List[float],
    spa_annual: Optional[float],
) -> Dict[str, Any]:
    """Alpha, information ratio and days-to-significance vs one fixed-APY benchmark."""
    alpha = None if spa_annual is None else spa_annual - bench_apy_pct
    bench_daily = bench_apy_pct / ANNUALIZATION_DAYS  # % per day (flat benchmark)
    excess = [r - bench_daily for r in spa_returns]
    n = len(excess)

    info_ratio = None
    days_to_significance = None
    additional_days_needed = None
    significant_now = False

    if n >= 2:
        m = statistics.fmean(excess)
        s = statistics.pstdev(excess)
        if s > 0:
            info_ratio = m / s * math.sqrt(ANNUALIZATION_DAYS)  # annualised IR
            if m > 0:
                t_now = m / (s / math.sqrt(n))
                significant_now = t_now >= Z_95_ONE_SIDED
                need = (Z_95_ONE_SIDED * s / m) ** 2
                days_to_significance = int(math.ceil(need))
                additional_days_needed = max(0, days_to_significance - n)
        elif m > 0:
            # Zero-variance excess that is strictly positive → already certain.
            significant_now = True
            days_to_significance = n
            additional_days_needed = 0

    return {
        "benchmark": name,
        "benchmark_apy_pct": bench_apy_pct,
        "spa_annualized_return_pct": rnd(spa_annual, 4),
        "alpha_pct": rnd(alpha, 4),
        "information_ratio": rnd(info_ratio, 4),
        "significant_at_95_now": significant_now,
        "days_to_95_significance": days_to_significance,
        "additional_days_needed": additional_days_needed,
        "excess_days_observed": n,
    }


def build_comparison(data_dir: str | Path = "data") -> Dict[str, Any]:
    """Assemble the benchmark comparison doc. Never raises on bad/empty inputs."""
    daily = load_equity_curve(data_dir)
    curve = rebuild_curve(real_track_bars(daily))
    spa_returns = daily_returns_pct(curve)
    spa_annual = annualize_return_pct(spa_returns)
    notes: List[str] = []
    if not daily:
        notes.append("equity_curve_daily.json missing/empty — comparison is a stub.")
    notes.append(
        "Days-to-significance is a frequentist projection assuming the observed "
        "daily-excess mean/variance persist; not a guarantee."
    )

    benchmarks = [
        ("US T-Bills", TBILL_APY_PCT),
        ("ETH staking (stETH)", STETH_APY_PCT),
        ("AAVE conservative", AAVE_CONSERVATIVE_APY_PCT),
        ("SPA target", rnd(spa_annual, 4) if spa_annual is not None else 0.0),
    ]
    comparisons = [
        _compare_one(name, float(apy), spa_returns, spa_annual)
        for name, apy in benchmarks
    ]

    return {
        "meta": {
            "generated_at": now_iso(),
            "module": "benchmark_comparator",
            "mp": "MP-1236",
            "advisory_only": True,
            "is_demo": False,
            "confidence_level": "95% (one-sided)",
            "annualization_days": ANNUALIZATION_DAYS,
            "track_days": len(curve),
            "return_days": len(spa_returns),
            "track_start": curve[0]["date"] if curve else None,
            "track_end": curve[-1]["date"] if curve else None,
            "source_files": ["equity_curve_daily.json"],
            "disclaimer": DISCLAIMER,
        },
        "spa_annualized_return_pct": rnd(spa_annual, 4),
        "comparisons": comparisons,
        "notes": notes,
    }


def write_comparison(doc: dict, data_dir: str | Path = "data") -> Dict[str, Any]:
    """Idempotent atomic write to ``data/benchmark_comparison.json``."""
    path = Path(data_dir) / "benchmark_comparison.json"
    existing = read_json(path, default=None)
    if isinstance(existing, dict) and content_fingerprint(existing) == content_fingerprint(doc):
        return {"changed": False, "path": str(path)}
    atomic_write_json(path, doc)
    return {"changed": True, "path": str(path)}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SPA benchmark comparison (read-only).")
    p.add_argument("--run", action="store_true", help="write data/benchmark_comparison.json")
    p.add_argument("--check", action="store_true", help="compute + print, no write (default)")
    p.add_argument("--data-dir", default="data", help="directory of data/*.json (default: data)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print("ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                  file=sys.stderr)
        return 0
    try:
        doc = build_comparison(data_dir=args.data_dir)
        if args.run:
            outcome = write_comparison(doc, data_dir=args.data_dir)
            print(f"benchmark_comparator: spa_apy={doc['spa_annualized_return_pct']}% "
                  f"benchmarks={len(doc['comparisons'])} — "
                  f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                  f"{outcome['path']}")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: never traceback, exit 0
        print(f"benchmark_comparator: ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
