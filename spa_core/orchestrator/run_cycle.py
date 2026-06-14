#!/usr/bin/env python3
"""run_cycle.py — запускает один цикл оркестратора. Используется launchd / cron / вручную.

Примеры::

    python3 -m spa_core.orchestrator.run_cycle
    python3 -m spa_core.orchestrator.run_cycle --dry-run --verbose

Флаги:
    --dry-run   запускает адаптеры и печатает результат, НО НЕ пишет в файлы.
    --verbose   подробный вывод по каждому адаптеру.

STRICTLY READ-ONLY: только опрос read-only адаптеров, без execution/денег.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from spa_core.orchestrator.adapter_orchestrator import (
    OrchestratorResult,
    run_orchestrator,
)


def _fmt_summary_line(result: OrchestratorResult) -> str:
    """Однострочная сводка вида:
    ``[2026-06-09 17:44] OK 6/8 | health A (0.93) | best APY 7.3% Pendle | 1.2s``
    """
    s = result.summary
    oh = result.overall_health
    try:
        ts = datetime.fromisoformat(result.run_ts).astimezone()
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y-%m-%d %H:%M")

    best = s.get("best_apy")
    if best:
        best_str = f"best APY {best['apy_pct']:.2f}% {best['protocol']}"
    else:
        best_str = "best APY n/a"

    return (
        f"[{stamp}] OK {s.get('ok', 0)}/{s.get('total', 0)} | "
        f"health {oh.get('grade', 'F')} ({oh.get('score', 0.0):.2f}) | "
        f"{best_str} | {result.duration_sec:.1f}s"
    )


def _print_verbose(result: OrchestratorResult) -> None:
    """Подробная таблица по каждому адаптеру."""
    print("─" * 72)
    print(f"{'protocol':<16}{'tier':<6}{'status':<10}{'apy%':>8}{'health':>9}  error")
    print("─" * 72)
    for a in result.adapters:
        apy = a.get("apy_pct")
        apy_str = f"{apy:.2f}" if isinstance(apy, (int, float)) else "—"
        hs = a.get("health_score", 0.0)
        err = a.get("error") or ""
        print(
            f"{a.get('protocol', '?'):<16}{a.get('tier', '?'):<6}"
            f"{a.get('status', '?'):<10}{apy_str:>8}{hs:>9.2f}  {err}"
        )
    print("─" * 72)
    tvl = result.summary.get("total_tvl_usd", 0.0)
    print(f"total TVL: ${tvl:,.0f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_cycle",
        description="Запустить один цикл adapter-оркестратора (read-only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="запустить адаптеры и вывести результат, НЕ записывая файлы",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="подробный вывод по каждому адаптеру",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_orchestrator(write=not args.dry_run)

    if args.verbose:
        _print_verbose(result)

    print(_fmt_summary_line(result))
    if args.dry_run:
        print("(dry-run: файлы НЕ записаны)")

    # Exit code: 0 — все ok; 1 — есть упавшие адаптеры.
    return 0 if result.summary.get("error", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
