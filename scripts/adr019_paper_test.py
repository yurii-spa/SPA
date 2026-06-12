#!/usr/bin/env python3
"""
ADR-019 Paper Test — проверка 14-дневного paper test для T2 cap 35%→50%.

ADR-019 предлагает поднять лимит T2 total cap с 35% до 50%.
Для активации требуется 14-дневный paper test с T2 allocation ≥ 35%.

Использование:
    python3 scripts/adr019_paper_test.py
    python3 scripts/adr019_paper_test.py --trades data/trades.json \\
        --portfolio data/portfolio_state.json

Exit codes:
    0 — paper test пройден (14+ дней с T2 ≥ 35%)
    1 — тест не пройден или T2 ещё не достиг порога
    2 — ошибка чтения файлов
"""

import json
import sys
import os
import argparse
from datetime import datetime, timezone

# ── Константы ADR-019 ───────────────────────────────────────────────────────

# Протоколы Tier-2 согласно RiskPolicy v1.0
T2_PROTOCOLS: frozenset = frozenset({'morpho_blue', 'yearn_v3', 'euler_v2', 'maple'})

# Порог T2 для активации ADR-019 (35%)
ADR019_T2_THRESHOLD: float = 0.35

# Требуемая длительность paper test в днях
ADR019_REQUIRED_DAYS: int = 14

# Минимальное количество трейдов с T2 ≥ порога для валидации
ADR019_MIN_TRADES: int = 3


# ── Чистые функции (тестируются напрямую) ──────────────────────────────────

def compute_t2_fraction(allocation: dict, capital: float) -> float:
    """
    Вычисляет долю T2-протоколов в аллокации относительно общего капитала.

    allocation: {protocol_key: usd_amount, ...}
    capital: общий капитал в USD (знаменатель)

    Возвращает значение от 0.0 до 1.0.
    """
    if not capital or capital <= 0:
        return 0.0
    t2_usd = sum(v for k, v in allocation.items() if k in T2_PROTOCOLS)
    return t2_usd / capital


def find_trades_above_threshold(trades: list, threshold: float = ADR019_T2_THRESHOLD) -> list:
    """
    Фильтрует трейды, где T2 allocation ≥ threshold.

    Возвращает список dict с полями:
        trade_id, ts, t2_fraction (float)
    """
    result = []
    for trade in trades:
        capital = trade.get('capital', 0)
        allocation = trade.get('to_allocation', {})
        t2_frac = compute_t2_fraction(allocation, capital)
        if t2_frac >= threshold:
            result.append({
                'trade_id': trade.get('trade_id', '?'),
                'ts': trade.get('ts', ''),
                't2_fraction': t2_frac,
            })
    return result


def get_t2_from_portfolio_state(portfolio_data: dict) -> tuple:
    """
    Вычисляет текущий T2% из portfolio_state.json или current_positions.json.

    Поддерживает два формата:
    1. portfolio_state.json — positions: список dict с 'actual_usd'
    2. current_positions.json — positions: dict {protocol: usd}

    Возвращает (t2_fraction: float, denominator_usd: float).
    """
    # Формат portfolio_state.json: positions — список объектов
    positions_raw = portfolio_data.get('positions', [])

    if isinstance(positions_raw, list) and positions_raw:
        total = portfolio_data.get('total_actual_usd', 0)
        if not total:
            # Вычисляем total из суммы позиций
            total = sum(p.get('actual_usd', 0) for p in positions_raw if isinstance(p, dict))
        t2_usd = sum(
            p.get('actual_usd', 0)
            for p in positions_raw
            if isinstance(p, dict) and p.get('protocol') in T2_PROTOCOLS
        )
        denom = total if total > 0 else 1.0
        return t2_usd / denom, total

    # Формат current_positions.json: positions — словарь {protocol: usd}
    if isinstance(positions_raw, dict) and positions_raw:
        # Знаменатель: capital_usd из файла или сумма позиций
        capital = portfolio_data.get('capital_usd', 0)
        if not capital:
            capital = sum(positions_raw.values())
        t2_usd = sum(v for k, v in positions_raw.items() if k in T2_PROTOCOLS)
        denom = capital if capital > 0 else 1.0
        return t2_usd / denom, capital

    return 0.0, 0.0


def parse_ts(ts_str: str) -> datetime:
    """
    Парсит ISO-8601 timestamp.
    Поддерживает суффикс 'Z' (UTC) и числовые смещения (+HH:MM).
    """
    # fromisoformat в Python 3.11+ понимает 'Z', но для совместимости:
    normalized = ts_str.replace('Z', '+00:00')
    return datetime.fromisoformat(normalized)


def count_days_since_first_activation(
    trades_above: list,
    now: datetime | None = None,
) -> int:
    """
    Считает количество полных дней с первого трейда с T2 ≥ порога до now.

    Если список пустой — возвращает 0.
    now по умолчанию — текущее UTC-время.
    """
    if not trades_above:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)

    # Берём самый ранний трейд по timestamp
    sorted_trades = sorted(trades_above, key=lambda t: t['ts'])
    first_ts = parse_ts(sorted_trades[0]['ts'])

    # Приводим now к aware, если нужно
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta = now - first_ts
    return max(0, delta.days)


def check(
    trades_data: list,
    portfolio_data: dict,
    now: datetime | None = None,
) -> dict:
    """
    Основная логика проверки ADR-019 (без файлового I/O).

    Параметры:
        trades_data:    список трейдов из trades.json
        portfolio_data: содержимое portfolio_state.json или current_positions.json
        now:            текущее время (UTC); None → datetime.now(timezone.utc)

    Возвращает dict:
        activated (bool)          — T2 current > 35%
        days_complete (int)       — дней с первого трейда с T2 ≥ 35%
        t2_current_pct (float)    — текущий T2 в процентах
        trades_above_threshold (int)
        ready (bool)              — True если 14+ дней И ≥ 3 трейда выше порога
        message (str)             — строка для вывода
        exit_code (int)           — 0 = готов, 1 = ещё не готов
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Шаг 1: найти трейды с T2 ≥ 35% в trades.json
    trades_above = find_trades_above_threshold(trades_data, ADR019_T2_THRESHOLD)

    # Шаг 2: текущий T2 из portfolio_data
    t2_current, _ = get_t2_from_portfolio_state(portfolio_data)

    # Fallback: если portfolio_data пустой — берём из последнего трейда
    if t2_current == 0.0 and trades_data:
        last = trades_data[-1]
        t2_current = compute_t2_fraction(
            last.get('to_allocation', {}),
            last.get('capital', 0),
        )

    # Шаг 3: проверяем, достиг ли T2 порога
    if t2_current <= ADR019_T2_THRESHOLD:
        msg = (
            f"ADR-019 NOT YET ACTIVATED (T2 floor not reached). "
            f"T2 current: {t2_current * 100:.1f}% "
            f"(need >{ADR019_T2_THRESHOLD * 100:.0f}%)"
        )
        return {
            'activated': False,
            'days_complete': 0,
            't2_current_pct': round(t2_current * 100, 2),
            'trades_above_threshold': len(trades_above),
            'ready': False,
            'message': msg,
            'exit_code': 1,
        }

    # Шаг 4: T2 ≥ 35% — считаем дни с первого такого трейда
    days = count_days_since_first_activation(trades_above, now)
    ready = (days >= ADR019_REQUIRED_DAYS) and (len(trades_above) >= ADR019_MIN_TRADES)

    # Шаг 5: формируем отчёт
    msg = (
        f"ADR-019 PAPER TEST: {days}/{ADR019_REQUIRED_DAYS} days complete. "
        f"T2 current: {t2_current * 100:.1f}%. "
        f"Trades above threshold: {len(trades_above)}/{ADR019_MIN_TRADES}."
    )
    if ready:
        msg += " READY — 14-day paper test passed."
    else:
        missing_days = max(0, ADR019_REQUIRED_DAYS - days)
        msg += f" Waiting {missing_days} more day(s)."

    return {
        'activated': True,
        'days_complete': days,
        't2_current_pct': round(t2_current * 100, 2),
        'trades_above_threshold': len(trades_above),
        'ready': ready,
        'message': msg,
        'exit_code': 0 if ready else 1,
    }


# ── Файловый I/O ────────────────────────────────────────────────────────────

def run_check(
    trades_path: str,
    portfolio_path: str,
    now: datetime | None = None,
) -> dict:
    """
    Читает JSON-файлы и вызывает check().

    Кидает FileNotFoundError, json.JSONDecodeError при ошибках I/O.
    """
    with open(trades_path) as f:
        trades_data = json.load(f)

    portfolio_data: dict = {}
    if os.path.exists(portfolio_path):
        with open(portfolio_path) as f:
            portfolio_data = json.load(f)

    return check(trades_data, portfolio_data, now)


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='ADR-019 14-day paper test check',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--trades',
        default='data/trades.json',
        help='Путь к trades.json (default: data/trades.json)',
    )
    parser.add_argument(
        '--portfolio',
        default='data/portfolio_state.json',
        help='Путь к portfolio_state.json (default: data/portfolio_state.json)',
    )
    args = parser.parse_args()

    try:
        result = run_check(args.trades, args.portfolio)
    except FileNotFoundError as e:
        print(f"ERROR: файл не найден: {e}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: невалидный JSON: {e}", file=sys.stderr)
        sys.exit(2)

    print(result['message'])
    sys.exit(result['exit_code'])


if __name__ == '__main__':
    main()
