"""
SPA Milestone Phase 4 Gate Checker (MP-213)

Верифицирует готовность к Phase 4 (live-пилот) по 5 критериям:
  1. adapters_count >= 15
  2. track_days >= 60
  3. avg_apy_7d >= 5.5%
  4. stress_test_passed == True
  5. backtest_completed == True

Только читает данные, не записывает.
Fail-safe: при отсутствии файла возвращает failed=True для критерия.

CLI:
    python3 -m spa_core.milestone.milestone_v2
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

# ─── Пути к данным ────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_DATA_DIR = os.path.join(_REPO_ROOT, "data")


def _data_path(filename: str) -> str:
    return os.path.join(_DATA_DIR, filename)


def _load_json(path: str) -> Optional[dict]:
    """Загрузить JSON-файл; вернуть None при ошибке."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─── Вычисление критериев ─────────────────────────────────────────────────────

def _count_adapters() -> int:
    """
    Посчитать число адаптеров.
    Пробуем adapter_sdk_status.json (приоритет), затем adapter_orchestrator_status.json.
    Возвращаем максимум из обоих источников.
    """
    sdk_count = 0
    orch_count = 0

    sdk_data = _load_json(_data_path("adapter_sdk_status.json"))
    if sdk_data:
        adapters = sdk_data.get("adapters", [])
        if isinstance(adapters, list):
            sdk_count = len(adapters)
        elif isinstance(adapters, dict):
            sdk_count = len(adapters)
        # Может быть поле counts
        sdk_count = max(sdk_count, sdk_data.get("adapters_count", 0))

    orch_data = _load_json(_data_path("adapter_orchestrator_status.json"))
    if orch_data:
        adapters = orch_data.get("adapters", [])
        if isinstance(adapters, list):
            orch_count = len(adapters)
        elif isinstance(adapters, dict):
            orch_count = len(adapters)
        orch_count = max(orch_count, orch_data.get("adapters_count", 0))

    return max(sdk_count, orch_count)


def _count_track_days() -> int:
    """
    Посчитать количество дней реального трека из equity_curve_daily.json.
    Используем len(data["daily"]) или data["summary"]["num_days"].
    """
    data = _load_json(_data_path("equity_curve_daily.json"))
    if data is None:
        return 0

    # Приоритет: explicit num_days из summary
    summary = data.get("summary", {})
    if isinstance(summary, dict) and "num_days" in summary:
        num_days = summary["num_days"]
        if isinstance(num_days, int) and num_days > 0:
            return num_days

    # Fallback: len(daily)
    daily = data.get("daily", [])
    if isinstance(daily, list):
        return len(daily)

    return 0


def _compute_avg_apy_7d() -> float:
    """
    Скользящее 7-дневное среднее APY из equity_curve_daily.json.
    Берём последние ≤7 записей и усредняем поле apy_today.
    Если данных нет — возвращаем 0.0.
    """
    data = _load_json(_data_path("equity_curve_daily.json"))
    if data is None:
        return 0.0

    daily = data.get("daily", [])
    if not isinstance(daily, list) or not daily:
        return 0.0

    window = daily[-7:]
    apys = []
    for entry in window:
        if isinstance(entry, dict):
            apy = entry.get("apy_today")
            if isinstance(apy, (int, float)) and apy > 0:
                apys.append(float(apy))

    if not apys:
        return 0.0

    return round(sum(apys) / len(apys), 4)


def _check_stress_test() -> bool:
    """
    Проверить, был ли успешно запущен стресс-тест.
    Читает stress_engine_results.json; возвращает False если файл отсутствует.
    """
    path = _data_path("stress_engine_results.json")
    if not os.path.exists(path):
        return False
    data = _load_json(path)
    if data is None:
        return False

    # Ищем поле passed / all_passed / status / overall_status
    for key in ["passed", "all_passed", "stress_passed"]:
        val = data.get(key)
        if isinstance(val, bool):
            return val

    # Если есть статус OK/pass
    status = data.get("status", "")
    if isinstance(status, str) and status.lower() in ("passed", "ok", "success"):
        return True

    # Если есть список сценариев, проверяем что все прошли
    scenarios = data.get("scenarios", {})
    if isinstance(scenarios, dict) and scenarios:
        return all(
            v.get("passed", False) if isinstance(v, dict) else False
            for v in scenarios.values()
        )

    return False


def _check_backtest_completed() -> bool:
    """Проверить наличие файла с результатами исторического бэктеста."""
    path = _data_path("backtest_results_historical.json")
    return os.path.exists(path)


# ─── Главная функция ──────────────────────────────────────────────────────────

def check_milestone_phase4() -> dict:
    """
    Проверить готовность к Phase 4 gate.

    Returns:
        {
            "milestone": "phase4_gate",
            "criteria": {
                "adapters_15plus": {"passed": bool, "value": int, "required": 15},
                "track_60days":    {"passed": bool, "value": int, "required": 60},
                "apy_5_5pct":      {"passed": bool, "value": float, "required": 5.5},
                "stress_test":     {"passed": bool},
                "backtest_done":   {"passed": bool},
            },
            "all_passed": bool,
            "ready_for_phase4": bool,
            "checked_at": "ISO-8601",
            "notes": str,
        }
    """
    adapters_count = _count_adapters()
    track_days = _count_track_days()
    avg_apy_7d = _compute_avg_apy_7d()
    stress_passed = _check_stress_test()
    backtest_done = _check_backtest_completed()

    adapters_ok = adapters_count >= 15
    track_ok = track_days >= 60
    apy_ok = avg_apy_7d >= 5.5
    all_passed = adapters_ok and track_ok and apy_ok and stress_passed and backtest_done

    # Полезные заметки для пользователя
    notes_parts = []
    if not adapters_ok:
        notes_parts.append(f"Need {15 - adapters_count} more adapters (have {adapters_count})")
    if not track_ok:
        notes_parts.append(f"Need {60 - track_days} more track days (have {track_days})")
    if not apy_ok:
        notes_parts.append(f"APY {avg_apy_7d:.2f}% < required 5.5% (7d avg)")
    if not stress_passed:
        notes_parts.append("Stress test not completed (run spa_core/stress engine)")
    if not backtest_done:
        notes_parts.append("Historical backtest not run (run spa_core.backtest.historical_backtest)")
    notes = "; ".join(notes_parts) if notes_parts else "All criteria met — ready for Phase 4"

    return {
        "milestone": "phase4_gate",
        "criteria": {
            "adapters_15plus": {
                "passed": adapters_ok,
                "value": adapters_count,
                "required": 15,
            },
            "track_60days": {
                "passed": track_ok,
                "value": track_days,
                "required": 60,
            },
            "apy_5_5pct": {
                "passed": apy_ok,
                "value": avg_apy_7d,
                "required": 5.5,
            },
            "stress_test": {
                "passed": stress_passed,
            },
            "backtest_done": {
                "passed": backtest_done,
            },
        },
        "all_passed": all_passed,
        "ready_for_phase4": all_passed,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = check_milestone_phase4()
    criteria = result["criteria"]

    print("=" * 60)
    print("SPA Milestone Phase 4 Gate Check")
    print(f"Checked at: {result['checked_at']}")
    print("=" * 60)

    def _tick(passed: bool) -> str:
        return "✅" if passed else "❌"

    print(f"{_tick(criteria['adapters_15plus']['passed'])} "
          f"Adapters ≥ 15:  "
          f"{criteria['adapters_15plus']['value']} / {criteria['adapters_15plus']['required']}")

    print(f"{_tick(criteria['track_60days']['passed'])} "
          f"Track ≥ 60 days: "
          f"{criteria['track_60days']['value']} / {criteria['track_60days']['required']}")

    print(f"{_tick(criteria['apy_5_5pct']['passed'])} "
          f"APY ≥ 5.5% (7d avg): "
          f"{criteria['apy_5_5pct']['value']:.2f}% / {criteria['apy_5_5pct']['required']}%")

    print(f"{_tick(criteria['stress_test']['passed'])} "
          f"Stress test passed")

    print(f"{_tick(criteria['backtest_done']['passed'])} "
          f"Historical backtest done")

    print("=" * 60)
    status = "READY FOR PHASE 4 ✅" if result["all_passed"] else "NOT READY ❌"
    print(f"Status: {status}")
    print(f"Notes:  {result['notes']}")
