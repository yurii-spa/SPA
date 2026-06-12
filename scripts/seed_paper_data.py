"""
scripts/seed_paper_data.py — MP-SEED

Засеивает 7 дней исторических paper trading данных (2026-06-05 … 2026-06-11)
для тестирования аналитических модулей.

Обновляет три файла:
  data/equity_history.json     — 8 записей (7 seed + Day 0 = 2026-06-12)
  data/pnl_history.json        — prepend 7 исторических PnL-снапшотов
  data/apy_milestone_log.json  — расширяет daily_log и start_date

stdlib only, атомарные записи (tmp + os.replace).
Идемпотентен: повторный запуск не дублирует записи (проверка по date).

Запуск:
    python3 scripts/seed_paper_data.py
"""

import json
import os
import tempfile
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
DATA_DIR  = REPO_ROOT / "data"

EQUITY_HISTORY_PATH   = DATA_DIR / "equity_history.json"
PNL_HISTORY_PATH      = DATA_DIR / "pnl_history.json"
APY_MILESTONE_PATH    = DATA_DIR / "apy_milestone_log.json"

# Also read current equity from the main equity curve
EQUITY_CURVE_PATH     = DATA_DIR / "equity_curve_daily.json"

# ---------------------------------------------------------------------------
# Seed data: 7 days (2026-06-05 … 2026-06-11)
# Realistic flat/up curve: equity ~$100K ± 0.5%, APY 9.80-10.18%
# ---------------------------------------------------------------------------
SEED_DAYS = [
    # date           equity       apy_pct   day_pnl
    ("2026-06-05",  100000.00,   9.80,     26.85),
    ("2026-06-06",  100026.85,   9.87,     27.07),
    ("2026-06-07",  100053.92,   9.93,     27.21),
    ("2026-06-08",  100081.13,   9.99,     27.37),
    ("2026-06-09",  100108.50,  10.05,     27.56),
    ("2026-06-10",  100136.06,  10.12,     27.72),
    ("2026-06-11",  100163.78,  10.18,     27.89),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def atomic_write(path: Path, data) -> None:
    """Атомарная запись JSON: tmp + os.replace."""
    tmp_dir = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=tmp_dir, suffix=".tmp", delete=False
    ) as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        tmp_path = fh.name
    os.replace(tmp_path, path)


def read_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return default


def get_current_equity() -> tuple:
    """Читает последнюю equity из equity_curve_daily.json."""
    curve = read_json(EQUITY_CURVE_PATH, {})
    daily = curve.get("daily", [])
    if daily:
        last = daily[-1]
        return (
            last.get("date", "2026-06-12"),
            last.get("equity", 100026.06),
            last.get("apy_today", 10.115),
        )
    return ("2026-06-12", 100026.06, 10.115)


# ---------------------------------------------------------------------------
# Part 1: equity_history.json
# ---------------------------------------------------------------------------
def seed_equity_history() -> int:
    """Возвращает итоговое количество записей."""
    existing: list = read_json(EQUITY_HISTORY_PATH, [])

    # Определяем уже существующие даты
    existing_dates = {r["date"] for r in existing if isinstance(r, dict)}

    # Day 0 — текущая реальная equity (2026-06-12)
    day0_date, day0_equity, day0_apy = get_current_equity()
    day0_pnl = round(day0_equity * (day0_apy / 100) / 365, 2)
    day0_entry = {
        "date":          day0_date,
        "day_index":     8,
        "equity":        round(day0_equity, 2),
        "apy_pct":       round(day0_apy, 3),
        "best_strategy": "s7_pendle_yt",
        "day_pnl":       day0_pnl,
        "is_seed":       False,
    }

    # Seed entries (oldest → newest)
    seed_entries = []
    for idx, (date, equity, apy, day_pnl) in enumerate(SEED_DAYS, start=1):
        if date in existing_dates:
            continue  # идемпотентность
        seed_entries.append({
            "date":          date,
            "day_index":     idx,
            "equity":        equity,
            "apy_pct":       apy,
            "best_strategy": "s7_pendle_yt",
            "day_pnl":       day_pnl,
            "is_seed":       True,
        })

    # Собираем: seed_entries (старые) + day0 (если нет) + existing (без дублей)
    final = seed_entries[:]
    if day0_date not in existing_dates:
        final.append(day0_entry)
    # Добавляем существующие записи, которые не пересекаются с seed
    all_seed_dates = {e["date"] for e in final}
    for r in existing:
        if isinstance(r, dict) and r.get("date") not in all_seed_dates:
            final.append(r)

    # Сортируем по дате
    final.sort(key=lambda x: x.get("date", ""))

    atomic_write(EQUITY_HISTORY_PATH, final)
    return len(final)


# ---------------------------------------------------------------------------
# Part 2: pnl_history.json
# ---------------------------------------------------------------------------
def seed_pnl_history() -> int:
    """Добавляет 7 исторических PnL-снапшотов (если отсутствуют)."""
    existing: list = read_json(PNL_HISTORY_PATH, [])

    existing_ts = {r.get("timestamp", "") for r in existing if isinstance(r, dict)}

    new_entries = []
    cumulative_pnl = 0.0
    for date, equity, apy, day_pnl in SEED_DAYS:
        ts = f"{date} 06:00:00"
        if ts in existing_ts:
            continue  # идемпотентность
        cumulative_pnl += day_pnl
        new_entries.append({
            "timestamp":           ts,
            "total_capital_usd":   round(equity, 2),
            "deployed_capital_usd": round(equity * 0.95, 2),
            "cash_usd":            round(equity * 0.05, 2),
            "total_pnl_usd":       round(equity - 100000.0, 2),
            "total_pnl_pct":       round((equity - 100000.0) / 100000.0 * 100, 5),
            "current_apy":         apy,
            "trade_count":         0,
            "is_seed":             True,
        })

    if not new_entries:
        return len(existing)

    # Prepend (исторические записи — перед существующими)
    combined = new_entries + existing
    # Сортируем по timestamp
    combined.sort(key=lambda x: x.get("timestamp", ""))

    atomic_write(PNL_HISTORY_PATH, combined)
    return len(combined)


# ---------------------------------------------------------------------------
# Part 3: apy_milestone_log.json
# ---------------------------------------------------------------------------
def seed_apy_milestone_log() -> int:
    """Расширяет daily_log: добавляет 7 дней. Все L1/L2/L3 достигнуты с 2026-06-05."""
    existing: dict = read_json(APY_MILESTONE_PATH, {})

    daily_log: list = existing.get("daily_log", [])
    existing_dates = {e.get("date") for e in daily_log}

    new_entries = []
    for date, equity, apy, _ in SEED_DAYS:
        if date in existing_dates:
            continue
        new_entries.append({
            "date":       date,
            "apy_pct":    apy,
            "strategy_id": "S7",
            "is_seed":    True,
        })

    if not new_entries:
        return existing.get("days_recorded", len(daily_log))

    combined_log = new_entries + daily_log
    combined_log.sort(key=lambda x: x.get("date", ""))

    # Обновляем milestones: первая дата = 2026-06-05
    milestones = existing.get("milestones_reached", [])
    # Если L1/L2/L3 уже зарегистрированы с 2026-06-12, переставляем на 2026-06-05
    updated_milestones = []
    for m in milestones:
        m2 = dict(m)
        if m2.get("first_reached_date", "") > "2026-06-05":
            m2["first_reached_date"] = "2026-06-05"
        updated_milestones.append(m2)

    # Если milestones пустые — создаём
    if not updated_milestones:
        updated_milestones = [
            {"level": 1, "name": "Baseline beat",  "target_pct": 5.0,  "first_reached_date": "2026-06-05"},
            {"level": 2, "name": "Target entry",   "target_pct": 7.0,  "first_reached_date": "2026-06-05"},
            {"level": 3, "name": "Target mid",     "target_pct": 10.0, "first_reached_date": "2026-06-05"},
        ]

    result = dict(existing)
    result["start_date"]       = "2026-06-05"
    result["last_updated"]     = "2026-06-12"
    result["days_recorded"]    = len(combined_log)
    result["daily_log"]        = combined_log
    result["milestones_reached"] = updated_milestones

    atomic_write(APY_MILESTONE_PATH, result)
    return len(combined_log)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=== seed_paper_data.py ===")
    print(f"DATA_DIR: {DATA_DIR}")
    print()

    print("[1/3] equity_history.json ...")
    n_equity = seed_equity_history()
    print(f"      → {n_equity} записей")

    print("[2/3] pnl_history.json ...")
    n_pnl = seed_pnl_history()
    print(f"      → {n_pnl} записей")

    print("[3/3] apy_milestone_log.json ...")
    n_apy = seed_apy_milestone_log()
    print(f"      → {n_apy} daily_log записей")

    print()
    print("=== Готово ===")

    # Verification
    ok = True
    if n_equity != 8:
        print(f"❌ equity_history.json: ожидалось 8, получено {n_equity}")
        ok = False
    else:
        print(f"✓ equity_history.json: {n_equity} записей (7 seed + Day 0)")

    if n_pnl < 7:
        print(f"❌ pnl_history.json: менее 7 записей ({n_pnl})")
        ok = False
    else:
        print(f"✓ pnl_history.json: {n_pnl} записей")

    if n_apy < 7:
        print(f"❌ apy_milestone_log daily_log: менее 7 записей ({n_apy})")
        ok = False
    else:
        print(f"✓ apy_milestone_log daily_log: {n_apy} записей")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
