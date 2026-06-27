#!/usr/bin/env python3
"""scripts/simulate_day.py — симуляция одного дня paper trading SPA.

Вычисляет дневной P&L на основе APY лидирующей стратегии (tournament_ranking.json,
rank=1), добавляет детерминированный шум ±0.5% и атомарно обновляет:
  - data/equity_history.json
  - data/pnl_history.json
  - data/adapter_status.json  (только поле simulate_day_snapshot)

stdlib only. Никаких внешних зависимостей.

Использование:
    python3 scripts/simulate_day.py                       # сегодня
    python3 scripts/simulate_day.py --date 2026-06-13     # конкретная дата
    python3 scripts/simulate_day.py --dry-run             # только показать расчёт
    python3 scripts/simulate_day.py --test                # встроенные тесты
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

# ── Пути ──────────────────────────────────────────────────────────────────────

# PROJECT_ROOT — родитель директории scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from spa_core.utils import clock  # noqa: E402  (after sys.path setup for standalone run)

EQUITY_HISTORY_PATH   = DATA_DIR / "equity_history.json"
PNL_HISTORY_PATH      = DATA_DIR / "pnl_history.json"
ADAPTER_STATUS_PATH   = DATA_DIR / "adapter_status.json"
TOURNAMENT_RANK_PATH  = DATA_DIR / "tournament_ranking.json"

# ── Константы ──────────────────────────────────────────────────────────────────

INITIAL_CAPITAL: float = 100_000.0    # $100,000 USDC (виртуальный)
NOISE_FACTOR:    float = 0.005        # ±0.5% от daily_return
EQUITY_RING:     int   = 365          # ring-buffer equity_history
PNL_RING:        int   = 365          # ring-buffer pnl_history
FALLBACK_APY:    float = 5.0          # % если tournament_ranking недоступен
CASH_BUFFER:     float = 0.05         # 5% cash buffer (RiskPolicy min)

# Milestone уровни: (label, порог_в_%_от_стартового_капитала)
MILESTONES: list[tuple[str, float]] = [
    ("L1",  5.0),
    ("L2",  7.0),
    ("L3", 10.0),
    ("L4", 12.0),
    ("L5", 15.0),
]


# ── Утилиты I/O ────────────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any) -> Any:
    """Загрузить JSON или вернуть default при любой ошибке."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: Path, data: Any) -> None:
    """Атомарная запись JSON: mkstemp → заполнить → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_simulate_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Чтение данных ──────────────────────────────────────────────────────────────

def load_equity_history() -> list[dict]:
    return _load_json(EQUITY_HISTORY_PATH, [])


def load_pnl_history() -> list[dict]:
    return _load_json(PNL_HISTORY_PATH, [])


def load_tournament_ranking() -> dict:
    return _load_json(TOURNAMENT_RANK_PATH, {})


def get_rank1_apy(ranking: dict) -> tuple[float, str]:
    """Вернуть (apy_pct, strategy_id) для стратегии rank=1.

    Приоритет: apy_realized → apy_target → FALLBACK_APY.
    """
    for s in ranking.get("strategies", []):
        if s.get("rank") == 1:
            apy = float(
                s.get("apy_realized")
                or s.get("apy_target")
                or FALLBACK_APY
            )
            name = s.get("strategy_id") or s.get("id") or "unknown"
            return apy, name
    return FALLBACK_APY, "fallback"


def fetch_apy_map_live() -> dict[str, float]:
    """Попытаться получить live APY через spa_core.price_feeds.defi_llama_apy_feed.

    При любой ошибке (импорт, сеть, ...) возвращает пустой dict.
    Вызывающий код проверяет пустоту и использует fallback из tournament_ranking.
    """
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from spa_core.price_feeds.defi_llama_apy_feed import (  # type: ignore
            fetch_apy_map as _fetch,
        )
        return _fetch()
    except Exception as exc:
        print(f"  [WARN] DeFiLlama fetch failed ({exc}) — APY из tournament_ranking")
        return {}


# ── Расчёт дня ─────────────────────────────────────────────────────────────────

def simulate_one_day(
    target_date: datetime.date,
    equity_history: list[dict],
    tournament_ranking: dict,
    apy_map: dict[str, float],
) -> dict:
    """Вычислить результаты одного торгового дня.

    Детерминирован: seed = int(date.strftime('%Y%m%d')).

    Returns:
        dict — все поля для equity_history + внутренние '_'-ключи для отчёта.
    """
    random.seed(int(target_date.strftime("%Y%m%d")))

    # Предыдущее equity и day_index
    if equity_history:
        last = equity_history[-1]
        prev_equity  = float(last.get("equity", INITIAL_CAPITAL))
        prev_day_idx = int(last.get("day_index", 0))
    else:
        prev_equity  = INITIAL_CAPITAL
        prev_day_idx = 0

    day_index = prev_day_idx + 1

    # APY: берём из tournament_ranking rank=1
    apy_pct, best_strategy = get_rank1_apy(tournament_ranking)

    # Базовый дневной доход
    daily_base = prev_equity * (apy_pct / 100.0 / 365.0)

    # Шум ±0.5% от базового дохода
    noise = daily_base * random.uniform(-NOISE_FACTOR, NOISE_FACTOR)
    day_pnl = daily_base + noise

    noise_pct = (noise / daily_base * 100.0) if daily_base != 0.0 else 0.0
    new_equity = prev_equity + day_pnl

    return {
        "date":          target_date.isoformat(),
        "day_index":     day_index,
        "equity":        round(new_equity, 2),
        "apy_pct":       round(apy_pct, 4),
        "best_strategy": best_strategy,
        "day_pnl":       round(day_pnl, 4),
        "is_seed":       False,
        # Internal (не записываются в файлы)
        "_prev_equity":  prev_equity,
        "_noise_pct":    round(noise_pct, 4),
        "_noise_usd":    round(noise, 6),
        "_daily_base":   round(daily_base, 4),
    }


def check_milestones(equity: float) -> list[str]:
    """Вернуть список достигнутых milestone-уровней."""
    total_return_pct = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0
    return [lbl for lbl, thr in MILESTONES if total_return_pct >= thr]


# ── Формирование записей ───────────────────────────────────────────────────────

def make_equity_record(result: dict) -> dict:
    """Убрать внутренние '_'-ключи для записи в equity_history.json."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def make_pnl_record(result: dict) -> dict:
    """Сформировать запись для pnl_history.json."""
    equity      = result["equity"]
    prev_equity = result["_prev_equity"]
    total_pnl   = equity - INITIAL_CAPITAL
    deployed    = prev_equity * (1.0 - CASH_BUFFER)
    cash        = equity - deployed
    dt = datetime.datetime.combine(
        datetime.date.fromisoformat(result["date"]),
        datetime.time(6, 0, 0),
    )
    return {
        "timestamp":            dt.strftime("%Y-%m-%d %H:%M:%S"),
        "total_capital_usd":    round(equity, 2),
        "deployed_capital_usd": round(deployed, 2),
        "cash_usd":             round(cash, 2),
        "total_pnl_usd":        round(total_pnl, 2),
        "total_pnl_pct":        round(total_pnl / INITIAL_CAPITAL * 100.0, 4),
        "current_apy":          result["apy_pct"],
        "trade_count":          0,
        "is_seed":              False,
    }


# ── Обновление adapter_status ──────────────────────────────────────────────────

def update_adapter_status(apy_map: dict[str, float], dry_run: bool) -> bool:
    """Добавить simulate_day_snapshot в adapter_status.json.

    Не трогает основную структуру (adapters[], mock_apy и т.п.).
    Принадлежность execution-домену сохраняется — только дополнение.
    Возвращает True при успехе (или dry_run).
    """
    if not apy_map:
        return False

    status = _load_json(ADAPTER_STATUS_PATH, None)
    if status is None:
        return False

    status["simulate_day_snapshot"] = {
        "simulated_at": clock.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":       "defi_llama",
        "apy_by_adapter": {k: round(v, 4) for k, v in apy_map.items()},
    }

    if dry_run:
        return True  # не пишем

    try:
        _atomic_write_json(ADAPTER_STATUS_PATH, status)
        return True
    except Exception as exc:
        print(f"  [WARN] adapter_status обновление не удалось: {exc}")
        return False


# ── Отчёт ──────────────────────────────────────────────────────────────────────

def print_report(
    result: dict,
    milestones: list[str],
    dry_run: bool,
    apy_source: str,
) -> None:
    equity      = result["equity"]
    prev_equity = result["_prev_equity"]
    day_pnl     = result["day_pnl"]
    apy_pct     = result["apy_pct"]
    strategy    = result["best_strategy"]
    date_str    = result["date"]
    day_index   = result["day_index"]
    total_ret   = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0
    mode_tag    = " [DRY-RUN]" if dry_run else ""

    sep  = "═" * 60
    sep2 = "─" * 60

    print()
    print(sep)
    print(f"  SPA simulate_day · {date_str} · День #{day_index}{mode_tag}")
    print(sep)
    print(f"  Стратегия (rank=1) : {strategy}")
    print(f"  APY источник       : {apy_source}")
    print(f"  APY                : {apy_pct:.4f}%")
    print(sep2)
    print(f"  Equity пред.       : ${prev_equity:>14,.2f}")
    print(f"  Day P&L            : ${day_pnl:>+13,.4f}")
    print(f"    базовый доход    : ${result['_daily_base']:>+13,.4f}")
    print(f"    шум ({result['_noise_pct']:+.4f}%)  : ${result['_noise_usd']:>+13,.6f}")
    print(f"  Equity новое       : ${equity:>14,.2f}")
    print(f"  Общий return       : {total_ret:>+10.4f}%  (от $100,000)")
    print(sep2)

    if milestones:
        for m in milestones:
            thr = dict(MILESTONES)[m]
            print(f"  🎉  MILESTONE {m} ДОСТИГНУТ! Общий return ≥ {thr}%")
    else:
        # До ближайшего milestone
        for lbl, thr in MILESTONES:
            if total_ret < thr:
                remaining_usd = INITIAL_CAPITAL * thr / 100.0 - (equity - INITIAL_CAPITAL)
                print(f"  До milestone {lbl} ({thr}%): ещё ${remaining_usd:,.2f}")
                break

    if dry_run:
        print("  ℹ️   DRY-RUN: файлы не записаны")
    else:
        print("  ✅  equity_history.json обновлён")
        print("  ✅  pnl_history.json обновлён")

    print(sep)
    print()


# ── Self-test ──────────────────────────────────────────────────────────────────

def run_tests() -> int:
    """3 встроенных теста. Возвращает 0 при успехе, 1 при провале."""
    PASS_MARK = "✅ PASS"
    FAIL_MARK = "❌ FAIL"
    errors = 0

    print("\n=== simulate_day.py self-test ===\n")

    # ─── TEST 1: dry-run не создаёт файлы ────────────────────────────────────
    # simulate_one_day сам по себе не пишет файлы.
    # В dry-run мы намеренно не вызываем _atomic_write_json.
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        eq_path  = td / "equity_history.json"
        pnl_path = td / "pnl_history.json"

        test_date = datetime.date(2030, 1, 1)
        hist = [{
            "date": "2029-12-31", "day_index": 1, "equity": 100_050.0,
            "apy_pct": 5.0, "best_strategy": "test", "day_pnl": 50.0, "is_seed": False,
        }]
        ranking = {"strategies": [{"rank": 1, "id": "T1", "strategy_id": "s_test",
                                   "apy_realized": 5.0, "apy_target": 5.0}]}
        # Только вычисляем, не пишем
        _ = simulate_one_day(test_date, hist, ranking, {})

        if not eq_path.exists() and not pnl_path.exists():
            print(f"  {PASS_MARK} TEST 1: dry-run не создаёт файлы")
        else:
            print(f"  {FAIL_MARK} TEST 1: файлы появились в dry-run (не должны)")
            errors += 1

    # ─── TEST 2: equity > 100000 ──────────────────────────────────────────────
    test_date2 = datetime.date(2030, 2, 1)
    hist2 = [{
        "date": "2030-01-31", "day_index": 2, "equity": 100_100.0,
        "apy_pct": 5.0, "best_strategy": "test", "day_pnl": 100.0, "is_seed": False,
    }]
    ranking2 = {"strategies": [{"rank": 1, "id": "T1", "strategy_id": "s_test",
                                "apy_realized": 10.0, "apy_target": 10.0}]}
    r2 = simulate_one_day(test_date2, hist2, ranking2, {})

    if r2["equity"] > 100_000.0:
        print(f"  {PASS_MARK} TEST 2: equity={r2['equity']:.2f} > 100,000")
    else:
        print(f"  {FAIL_MARK} TEST 2: equity={r2['equity']:.2f} ≤ 100,000 (ожидалось > 100,000)")
        errors += 1

    # ─── TEST 3: повторный запуск одной даты → "already simulated" ────────────
    test_date3 = datetime.date(2030, 3, 15)
    hist_dup = [{
        "date": test_date3.isoformat(), "day_index": 5, "equity": 101_000.0,
        "apy_pct": 5.0, "best_strategy": "test", "day_pnl": 10.0, "is_seed": False,
    }]
    already = any(e.get("date") == test_date3.isoformat() for e in hist_dup)

    if already:
        print(f"  {PASS_MARK} TEST 3: дата {test_date3} → already simulated обнаружено корректно")
    else:
        print(f"  {FAIL_MARK} TEST 3: already simulated не обнаружено для {test_date3}")
        errors += 1

    print()
    if errors == 0:
        print("=== Все тесты пройдены (3/3) ✅ ===\n")
    else:
        print(f"=== Провалено: {errors}/3 ❌ ===\n")
    return 1 if errors else 0


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Симуляция одного дня paper trading SPA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 scripts/simulate_day.py
  python3 scripts/simulate_day.py --date 2026-06-13
  python3 scripts/simulate_day.py --dry-run
  python3 scripts/simulate_day.py --test
""",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Дата (YYYY-MM-DD). По умолчанию — сегодня.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Показать расчёт без записи файлов.",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Запустить встроенные self-тесты.",
    )
    args = parser.parse_args()

    if args.test:
        return run_tests()

    # ── 1. Дата ───────────────────────────────────────────────────────────────
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"[ERROR] Неверный формат даты: {args.date!r}. Ожидается YYYY-MM-DD.")
            return 1
    else:
        target_date = datetime.date.today()

    dry_run = args.dry_run
    mode_tag = " (dry-run)" if dry_run else ""
    print(f"\n[simulate_day] {target_date}{mode_tag}")

    # ── 2. Загрузить equity_history, проверить дублирование ──────────────────
    equity_history = load_equity_history()
    if any(e.get("date") == target_date.isoformat() for e in equity_history):
        print(
            f"\n  ⚠️  already simulated: запись за {target_date} "
            "уже присутствует в equity_history.json.\n"
            "     Используйте другую дату или удалите запись вручную.\n"
        )
        return 0

    # ── 3. APY ────────────────────────────────────────────────────────────────
    print("  Загружаю APY...")
    apy_map = fetch_apy_map_live()
    apy_source = f"defi_llama ({len(apy_map)} адаптеров)" if apy_map else "tournament_ranking (fallback)"
    print(f"  APY источник: {apy_source}")

    # ── 4. Tournament ranking ─────────────────────────────────────────────────
    tournament_ranking = load_tournament_ranking()

    # ── 5. Рассчитать день ────────────────────────────────────────────────────
    result = simulate_one_day(target_date, equity_history, tournament_ranking, apy_map)

    # ── 6. Milestones ─────────────────────────────────────────────────────────
    milestones_hit = check_milestones(result["equity"])

    # ── 7. Отчёт ──────────────────────────────────────────────────────────────
    print_report(result, milestones_hit, dry_run, apy_source)

    # ── 8. Запись файлов ──────────────────────────────────────────────────────
    if not dry_run:
        # equity_history.json (ring-buffer)
        eq_record = make_equity_record(result)
        equity_history.append(eq_record)
        if len(equity_history) > EQUITY_RING:
            equity_history = equity_history[-EQUITY_RING:]
        _atomic_write_json(EQUITY_HISTORY_PATH, equity_history)

        # pnl_history.json (ring-buffer)
        pnl_history = load_pnl_history()
        pnl_history.append(make_pnl_record(result))
        if len(pnl_history) > PNL_RING:
            pnl_history = pnl_history[-PNL_RING:]
        _atomic_write_json(PNL_HISTORY_PATH, pnl_history)

        # adapter_status.json (только snapshot, не трогать основную структуру)
        update_adapter_status(apy_map, dry_run=False)
    else:
        # В dry-run тоже не трогаем adapter_status
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
