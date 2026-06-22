#!/usr/bin/env python3
"""Run allocation tuner and print suggestion (MP-207).

Usage:
    python3 scripts/run_tuner.py
    python3 scripts/run_tuner.py --no-save
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path when run directly
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.tuner.allocation_tuner import run_allocation_tuner


def main() -> int:
    parser = argparse.ArgumentParser(description="SPA Allocation Tuner (MP-207)")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Не сохранять результат в data/tuner_suggestion.json",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=500,
        help="Число кандидатов для grid search (по умолчанию 500)",
    )
    args = parser.parse_args()

    print("SPA Allocation Tuner (MP-207)")
    print("=" * 50)
    print(f"Grid search: {args.candidates} кандидатов")
    print()

    try:
        result = run_allocation_tuner(save=not args.no_save)
    except Exception as e:
        print(f"ОШИБКА тюнера: {e}", file=sys.stderr)
        return 1

    print("Оптимальная аллокация:")
    if result.protocol_breakdown:
        for p in result.protocol_breakdown:
            bar = "█" * int(p["weight_pct"] / 2)
            print(f"  {p['id']:<20} {p['weight_pct']:>5.1f}%  {bar}  @ {p['apy']:.2f}% APY  [{p['tier']}]")
    else:
        print("  (нет eligible протоколов — all-cash)")

    print()
    total_w = sum(p["weight"] for p in result.protocol_breakdown)
    cash_pct = (1.0 - total_w) * 100
    print(f"  {'CASH':<20} {cash_pct:>5.1f}%  @ 0.00% APY")
    print()
    print(f"Ожидаемый APY:    {result.expected_apy:.4f}%")
    print(f"Sharpe (оценка):  {result.expected_sharpe:.4f}")
    print(f"Backtest {result.backtest_days}д:    {result.backtest_return:.4f}% total return")
    print(f"Objective score:  {result.objective_score:.6f}")
    print()

    if result.improvements:
        print("Улучшения vs текущей аллокации:")
        for imp in result.improvements:
            print(f"  • {imp}")
    else:
        print("Улучшения: нет данных о текущей аллокации")

    if not args.no_save:
        print()
        print("✓ Сохранено в data/tuner_suggestion.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
