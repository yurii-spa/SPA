#!/usr/bin/env python3
"""scripts/backfill_evidence.py — заполнение 30-дневного окна paper trading SPA.

Последовательно вызывает simulate_day.py для каждой даты в диапазоне.
Пропускает уже симулированные дни, выводит прогресс и итоговую статистику.

stdlib only: subprocess, datetime, json, argparse, os, re, sys, pathlib.

Использование:
    python3 scripts/backfill_evidence.py --from 2026-06-13 --to 2026-06-20
    python3 scripts/backfill_evidence.py --days 7
    python3 scripts/backfill_evidence.py --dry-run --days 14
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Пути ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT        = Path(__file__).resolve().parent.parent
SIMULATE_DAY_SCRIPT = PROJECT_ROOT / "scripts" / "simulate_day.py"
EQUITY_HISTORY_PATH = PROJECT_ROOT / "data" / "equity_history.json"

INITIAL_CAPITAL: float = 100_000.0


# ── I/O ───────────────────────────────────────────────────────────────────────

def _load_equity_history() -> list[dict]:
    """Загрузить equity_history.json; при ошибке — пустой список."""
    try:
        with open(EQUITY_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _current_equity() -> float:
    """Последнее значение equity из equity_history.json."""
    history = _load_equity_history()
    if history:
        return float(history[-1].get("equity", INITIAL_CAPITAL))
    return INITIAL_CAPITAL


def _equity_for_date(date: datetime.date) -> float | None:
    """Equity-значение для конкретной даты из истории (или None если нет)."""
    history = _load_equity_history()
    for entry in history:
        if entry.get("date") == date.isoformat():
            return float(entry["equity"])
    return None


def _is_already_simulated(date: datetime.date) -> bool:
    """True если дата уже присутствует в equity_history.json."""
    history = _load_equity_history()
    return any(e.get("date") == date.isoformat() for e in history)


# ── Парсинг вывода simulate_day.py ────────────────────────────────────────────

_RE_EQUITY = re.compile(r"Equity\s+новое\s*:\s*\$([\d,]+\.\d+)")


def _parse_equity(output: str) -> float | None:
    """Извлечь equity из stdout simulate_day.py.

    Формат строки: «  Equity новое       : $100,030.50»
    """
    m = _RE_EQUITY.search(output)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _is_already_msg(output: str) -> bool:
    """True если simulate_day.py сообщил 'already simulated'."""
    return "already simulated" in output


# ── Вызов simulate_day.py ─────────────────────────────────────────────────────

def _run_simulate_day(
    date: datetime.date,
    dry_run: bool = False,
) -> tuple[bool, bool, float | None, str]:
    """Запустить simulate_day.py для одной даты.

    Returns:
        (success, already_simulated, equity_parsed, full_output)
        - success          — True если returncode == 0
        - already_simulated— True если день уже есть в истории
        - equity_parsed    — распарсенное equity из stdout (None если не удалось)
        - full_output      — объединённый stdout+stderr
    """
    cmd = [sys.executable, str(SIMULATE_DAY_SCRIPT), "--date", date.isoformat()]
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        msg = (
            f"[ERROR] Python-интерпретатор или скрипт не найден.\n"
            f"  Python: {sys.executable}\n"
            f"  Скрипт: {SIMULATE_DAY_SCRIPT}"
        )
        return False, False, None, msg
    except Exception as exc:  # noqa: BLE001
        return False, False, None, f"[ERROR] subprocess: {exc}"

    combined = proc.stdout + proc.stderr
    success         = proc.returncode == 0
    already_simul   = _is_already_msg(combined)
    equity_parsed   = _parse_equity(combined) if not dry_run else None
    return success, already_simul, equity_parsed, combined


# ── Построение списка дат ──────────────────────────────────────────────────────

def _build_dates(from_date: datetime.date, to_date: datetime.date) -> list[datetime.date]:
    dates: list[datetime.date] = []
    cur = from_date
    while cur <= to_date:
        dates.append(cur)
        cur += datetime.timedelta(days=1)
    return dates


# ── Форматирование ─────────────────────────────────────────────────────────────

_SEP  = "═" * 62
_SEP2 = "─" * 62


def _fmt_equity(equity: float) -> str:
    return f"${equity:,.2f}"


def _fmt_pnl(pnl: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return f"{sign}${pnl:,.2f}"


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Заполнение 30-дневного окна paper trading SPA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 scripts/backfill_evidence.py --from 2026-06-13 --to 2026-06-20
  python3 scripts/backfill_evidence.py --days 7
  python3 scripts/backfill_evidence.py --dry-run --days 14
  python3 scripts/backfill_evidence.py --dry-run --days 3
""",
    )
    parser.add_argument(
        "--from", dest="from_date", type=str, default=None,
        help="Начальная дата (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--to", dest="to_date", type=str, default=None,
        help="Конечная дата включительно (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Симулировать следующие N дней (начиная с завтра).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Показать список дат без запуска симуляции.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Выводить полный вывод simulate_day.py для каждого дня.",
    )
    args = parser.parse_args()

    today = datetime.date.today()

    # ── 1. Определить диапазон дат ────────────────────────────────────────────
    if args.days is not None:
        if args.days < 1:
            print("[ERROR] --days должен быть ≥ 1")
            return 1
        from_date = today + datetime.timedelta(days=1)
        to_date   = today + datetime.timedelta(days=args.days)

    elif args.from_date is not None:
        try:
            from_date = datetime.date.fromisoformat(args.from_date)
        except ValueError:
            print(f"[ERROR] Неверный формат --from: {args.from_date!r}. Ожидается YYYY-MM-DD.")
            return 1
        if args.to_date is not None:
            try:
                to_date = datetime.date.fromisoformat(args.to_date)
            except ValueError:
                print(f"[ERROR] Неверный формат --to: {args.to_date!r}. Ожидается YYYY-MM-DD.")
                return 1
        else:
            to_date = from_date  # один день

    else:
        parser.print_help()
        print("\n[ERROR] Укажите --from/--to или --days N.")
        return 1

    if from_date > to_date:
        print(f"[ERROR] --from ({from_date}) позже --to ({to_date}).")
        return 1

    dates = _build_dates(from_date, to_date)
    N = len(dates)

    # ── 2. Проверить наличие simulate_day.py ──────────────────────────────────
    if not SIMULATE_DAY_SCRIPT.exists():
        print(f"[ERROR] simulate_day.py не найден: {SIMULATE_DAY_SCRIPT}")
        print("        Убедитесь, что scripts/simulate_day.py существует.")
        return 1

    # ── 3. Шапка ──────────────────────────────────────────────────────────────
    mode_tag = "  [DRY-RUN]" if args.dry_run else ""
    print()
    print(_SEP)
    print(f"  SPA backfill_evidence{mode_tag}")
    print(f"  Диапазон : {from_date} → {to_date}  ({N} {'день' if N == 1 else 'дней'})")
    print(f"  Сегодня  : {today}")
    print(_SEP)

    # ── 4. DRY-RUN: только список дат ─────────────────────────────────────────
    if args.dry_run:
        print()
        print(f"  Даты для симуляции ({N}):")
        print()
        for i, d in enumerate(dates, 1):
            already = _is_already_simulated(d)
            eq_note = ""
            if already:
                eq = _equity_for_date(d)
                eq_note = f"  (уже есть, equity={_fmt_equity(eq)})" if eq else "  (уже есть)"
            print(f"    {i:>3}.  {d}{eq_note}")
        print()
        print(f"  DRY-RUN: ничего не запускается и не записывается.")
        print(_SEP)
        print()
        return 0

    # ── 5. Симуляция дней ─────────────────────────────────────────────────────
    initial_equity = _current_equity()

    days_added   = 0
    days_skipped = 0
    days_failed  = 0
    last_equity  = initial_equity

    for i, date in enumerate(dates, 1):
        success, already_simulated, equity_parsed, output = _run_simulate_day(date)

        if already_simulated:
            # День уже есть — пропускаем, берём equity из файла
            days_skipped += 1
            eq = _equity_for_date(date) or last_equity
            print(f"  День {i:>2}/{N}: {date}  ⏭️  пропущен (уже есть)  equity={_fmt_equity(eq)}")
            last_equity = eq

        elif success:
            days_added += 1
            # Предпочитаем распарсенное значение; fallback — перечитать файл
            eq = equity_parsed if equity_parsed is not None else _current_equity()
            last_equity = eq
            day_pnl = eq - (initial_equity if days_added == 1 else last_equity)
            # Для точного day_pnl лучше смотреть equity_history
            day_record_eq = _equity_for_date(date)
            if day_record_eq is not None:
                last_equity = day_record_eq
                eq = day_record_eq
            print(f"  День {i:>2}/{N}: {date}  ✅  equity={_fmt_equity(eq)}")
            if args.verbose:
                for line in output.splitlines():
                    stripped = line.strip()
                    if stripped:
                        print(f"         {stripped}")

        else:
            days_failed += 1
            print(f"  День {i:>2}/{N}: {date}  ❌  ОШИБКА (код {0})")
            # Всегда показываем ошибку, даже без --verbose
            for line in output.splitlines():
                stripped = line.strip()
                if stripped:
                    print(f"    {stripped}")

    # ── 6. Итоговая статистика ────────────────────────────────────────────────
    final_equity = _current_equity()
    total_pnl    = final_equity - INITIAL_CAPITAL
    period_pnl   = final_equity - initial_equity
    total_pnl_pct = total_pnl / INITIAL_CAPITAL * 100.0

    print()
    print(_SEP2)
    print(f"  Итоги backfill_evidence:")
    print(_SEP2)
    print(f"    Добавлено дней  : {days_added}")
    print(f"    Пропущено дней  : {days_skipped}")
    if days_failed > 0:
        print(f"    Ошибок          : {days_failed}  ⚠️")
    print(f"    Equity до       : {_fmt_equity(initial_equity)}")
    print(f"    Equity итог     : {_fmt_equity(final_equity)}")
    print(f"    P&L за период   : {_fmt_pnl(period_pnl)}")
    print(f"    Общий P&L       : {_fmt_pnl(total_pnl)}  ({total_pnl_pct:+.4f}%)")
    print(_SEP)
    print()

    return 0 if days_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
