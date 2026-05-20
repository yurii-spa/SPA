"""
SPA Orchestrator Runner — CLI (M4)

Использование:
    python runner.py              # одна итерация + вывод
    python runner.py --once       # одна итерация, тихий режим
    python runner.py --loop 300   # цикл каждые 5 минут
    python runner.py --json       # JSON output
    python runner.py --status     # только статус портфеля
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.graph import SPAOrchestrator


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="SPA Orchestrator Runner (M4)")
    parser.add_argument("--once",   action="store_true", help="Одна итерация и выход")
    parser.add_argument("--loop",   type=int, metavar="SECONDS",
                        help="Повторять каждые N секунд")
    parser.add_argument("--json",   action="store_true", help="JSON output")
    parser.add_argument("--status", action="store_true", help="Статус портфеля и выход")
    parser.add_argument("--db",     type=str, help="Путь к БД (по умолчанию spa.db)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    orch    = SPAOrchestrator(db_path=db_path)

    if args.status:
        _print_status(orch)
        return

    def run_once() -> None:
        state = orch.run_once()
        if args.json:
            print(json.dumps(state, indent=2, default=str))
        else:
            orch.print_state(state)

    if args.loop:
        print(f"SPA Orchestrator starting — loop every {args.loop}s (Ctrl+C to stop)")
        while True:
            try:
                run_once()
                time.sleep(args.loop)
            except KeyboardInterrupt:
                print("\nStopped by user.")
                break
    else:
        run_once()


def _print_status(orch: SPAOrchestrator) -> None:
    """Распечатать текущий статус портфеля без запуска агентов."""
    status = orch.trader.get_status()
    p      = status["portfolio"]
    pt     = status["paper_trading"]

    print(f"\n{'═'*60}")
    print(f"  SPA Portfolio Status")
    print(f"{'═'*60}")
    print(f"  Capital:   ${p['total_capital_usd']:>10,.2f}")
    print(f"  Deployed:  ${p['deployed_usd']:>10,.2f}  ({1-p['cash_pct']:.0%})")
    print(f"  Cash:      ${p['cash_usd']:>10,.2f}  ({p['cash_pct']:.0%})")
    pnl_sign = "+" if p["total_pnl_usd"] >= 0 else ""
    print(f"  PnL:       {pnl_sign}${p['total_pnl_usd']:>9.2f}")
    print(f"  Drawdown:  {p['total_drawdown_pct']:.2%}")
    weeks_left = pt['min_weeks_required'] - pt['weeks_elapsed']
    go_live_str = "✅ Go-Live eligible" if pt['go_live_ready'] else f"{weeks_left:.1f}w remaining"
    print(f"\n  Week {pt['weeks_elapsed']:.1f} / {pt['min_weeks_required']} | {go_live_str}")

    positions = status.get("positions", [])
    if positions:
        print(f"\n  Positions ({len(positions)}):")
        for pos in positions:
            print(f"    {pos['protocol_key']:<35} ${pos['amount_usd']:>8,.0f}  "
                  f"{pos['current_apy']:.2f}%  {pos['days_held']:.1f}d")

    bus_stats = orch.bus.stats()
    print(f"\n  Message Bus:")
    for topic, counts in bus_stats.items():
        pending = counts.get("pending", 0)
        acked   = counts.get("acked", 0)
        if pending or acked:
            print(f"    {topic:<20} pending={pending}  acked={acked}")

    print(f"\n{'═'*60}\n")


if __name__ == "__main__":
    main()
