#!/usr/bin/env python3
"""
scripts/strategy_lab_paper.py — the ONE-COMMAND CLI for the Strategy-Lab live paper service.

Modes:
  python3 scripts/strategy_lab_paper.py            single tick (launchd cron-style invocation)
  python3 scripts/strategy_lab_paper.py --loop     long-lived daemon, ticks every --interval s
  python3 scripts/strategy_lab_paper.py --loop --interval 1800
  python3 scripts/strategy_lab_paper.py --status   print the status table (no tick advance)
  python3 scripts/strategy_lab_paper.py --weekly    build + print the weekly comparison report

RESTART-SURVIVAL: every start (single tick OR loop) constructs a PaperService, which reloads
each strategy's persisted state from disk — a relaunch continues the book, never zeroes it.

stdlib only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make `spa_core` importable when invoked as a bare script (launchd / cron).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategy_lab.paper import PaperService  # noqa: E402

log = logging.getLogger("spa.strategy_lab.paper.cli")


def _print_status(status: dict) -> None:
    print(f"Strategy Lab — paper service status   ({status.get('generated_at', '?')})")
    print(f"  date={status.get('date')}  gap={status.get('gap')}"
          + (f"  reason={status.get('gap_reason')}" if status.get("gap") else ""))
    print(f"  {'id':<12} {'equity_usd':>14} {'net_apy%':>10} {'killed':>7}  last_tick")
    print("  " + "-" * 64)
    for sid, s in sorted(status.get("strategies", {}).items()):
        apy = s.get("net_apy_pct")
        apy_str = f"{apy:>10.4f}" if isinstance(apy, (int, float)) else f"{'n/a':>10}"
        print(f"  {sid:<12} {s.get('equity_usd', 0.0):>14,.2f} {apy_str} "
              f"{str(bool(s.get('killed'))):>7}  {s.get('last_tick')}")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Strategy-Lab live paper-trading service")
    parser.add_argument("--loop", action="store_true", help="run as a long-lived daemon")
    parser.add_argument("--interval", type=int, default=3600,
                        help="seconds between ticks in --loop mode (default 3600)")
    parser.add_argument("--status", action="store_true", help="print status and exit (no tick)")
    parser.add_argument("--weekly", action="store_true", help="build+print weekly report and exit")
    args = parser.parse_args(argv)

    # Restart-survival happens here: building the service reloads persisted state from disk.
    svc = PaperService()

    if args.status:
        _print_status(svc.status())
        return 0

    if args.weekly:
        md = svc.weekly_report(send_telegram=False)
        if md is None:
            print("(weekly report unavailable — report module not built yet)")
        else:
            print(md)
        return 0

    if args.loop:
        log.info("Strategy-Lab paper daemon starting (interval=%ds)", args.interval)
        while True:
            try:
                status = svc.tick()
                log.info("tick complete: date=%s gap=%s strategies=%d",
                         status.get("date"), status.get("gap"), status.get("n_strategies"))
            except Exception as exc:  # noqa: BLE001 — daemon must survive a tick error
                log.error("tick raised (continuing loop): %s", exc)
            time.sleep(max(1, args.interval))

    # Default: a single tick (the launchd cron-style invocation).
    status = svc.tick()
    log.info("single tick complete: date=%s gap=%s strategies=%d",
             status.get("date"), status.get("gap"), status.get("n_strategies"))
    _print_status(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
