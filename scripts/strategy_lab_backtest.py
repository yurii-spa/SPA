#!/usr/bin/env python3
"""
scripts/strategy_lab_backtest.py — the ONE-COMMAND Strategy Lab backtest CLI.

Runs ALL strategies (Variant N, Variant D + the 4 baselines) through the SAME shared backtest
(same start capital, same window, same data), prints the comparative report to stdout, and
writes the result JSON (+ optional markdown report).

Usage:
    python3 scripts/strategy_lab_backtest.py
    python3 scripts/strategy_lab_backtest.py --refresh
    python3 scripts/strategy_lab_backtest.py --out data/strategy_lab_backtest.json --md report.md

Flags:
    --refresh           force MarketData.refresh() (re-fetch live feeds) before running.
    --out PATH          where to write the result JSON (default data/strategy_lab_backtest.json).
    --md PATH           also write the markdown comparative report to PATH.

stdlib only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the repo root is importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategy_lab.backtest import DEFAULT_OUT, run_backtest, write_result  # noqa: E402
from spa_core.strategy_lab.report import comparative_report, write_report  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Strategy Lab shared backtest (one command).")
    parser.add_argument(
        "--refresh", action="store_true",
        help="force MarketData.refresh() (re-fetch live feeds) before running",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT),
        help="result JSON output path (default: data/strategy_lab_backtest.json)",
    )
    parser.add_argument(
        "--md", default=None,
        help="optional path to also write the markdown comparative report",
    )
    args = parser.parse_args(argv)

    if args.refresh:
        # Refresh the unified market-data cache from the live feeds (needs network).
        from spa_core.strategy_lab.data.market_data import MarketData
        print("[strategy_lab_backtest] refreshing market data from live feeds…", file=sys.stderr)
        MarketData().refresh()

    result = run_backtest()

    report = comparative_report(result)
    print(report)

    out_path = write_result(result, Path(args.out))
    print(f"\n[strategy_lab_backtest] wrote result JSON → {out_path}", file=sys.stderr)

    if args.md:
        md_path = write_report(result, args.md)
        print(f"[strategy_lab_backtest] wrote markdown report → {md_path}", file=sys.stderr)

    # Non-zero exit if the window under-tested the variants (loud, scriptable signal).
    warnings = result.get("window_warnings") or []
    if warnings:
        print(
            f"[strategy_lab_backtest] WARNING: {len(warnings)} window warning(s) — "
            "see report.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
