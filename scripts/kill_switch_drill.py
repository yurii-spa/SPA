#!/usr/bin/env python3
"""Kill-switch drill script (MP-108).

Симулирует триггерные условия и верифицирует реакцию системы.

Drill 1: Simulate drawdown trigger — инжектирует фиктивную equity curve с просадкой -16%
Drill 2: Simulate manual trigger — создаёт kill_switch_active.json, проверяет обнаружение
Drill 3: Verify all-cash allocation — все протоколы = 0.0
Drill 4: Deactivate and verify clean state

Запуск: python3 scripts/kill_switch_drill.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# ── Добавляем корень репо в sys.path ──────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (
    DRAWDOWN_THRESHOLD_PCT,
    KillSwitchChecker,
    run_kill_switch_check,
)

# ── Цвета для вывода ──────────────────────────────────────────────────────────
_GREEN = "\033[32m"
_RED   = "\033[31m"
_CYAN  = "\033[36m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"


def _pass(msg: str) -> None:
    print(f"  {_GREEN}PASS{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")


def _header(title: str) -> None:
    print(f"\n{_CYAN}{_BOLD}{'─' * 60}{_RESET}")
    print(f"{_CYAN}{_BOLD}  {title}{_RESET}")
    print(f"{_CYAN}{'─' * 60}{_RESET}")


def _make_equity_curve(
    peak: float = 100_000.0,
    drawdown_pct: float = 0.0,
    days: int = 10,
) -> list[dict]:
    """Генерирует фиктивную equity curve с заданной просадкой."""
    result = []
    current = peak
    for i in range(days - 1):
        result.append({
            "date": f"2026-05-{i + 1:02d}",
            "close_equity": round(current, 2),
            "open_equity": round(current, 2),
        })
    # Последняя точка с просадкой
    final = round(peak * (1.0 - drawdown_pct / 100.0), 2)
    result.append({
        "date": f"2026-05-{days:02d}",
        "close_equity": final,
        "open_equity": round(current, 2),
    })
    return result


def run_drill() -> int:
    """Запускает все drill-сценарии. Возвращает 0 если все PASS, 1 если есть FAIL."""
    passed = 0
    failed = 0

    # Используем временную папку data для drill (не трогаем реальные данные)
    with tempfile.TemporaryDirectory(prefix="spa_kill_drill_") as tmpdir:
        tmp_data = Path(tmpdir)
        checker = KillSwitchChecker(data_dir=tmp_data)

        # ── Drill 1: Drawdown trigger ─────────────────────────────────────────
        _header(f"Drill 1: Drawdown trigger (>{DRAWDOWN_THRESHOLD_PCT}%)")

        # 1a: curve с просадкой -16% (должна сработать)
        curve_16pct = _make_equity_curve(peak=100_000.0, drawdown_pct=16.0, days=10)
        t, reason = checker.check_drawdown_trigger(curve_16pct)
        label = f"drawdown=16% → triggered={t}, reason: {reason}"
        if t:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 1b: curve с просадкой -14% (не должна сработать)
        curve_14pct = _make_equity_curve(peak=100_000.0, drawdown_pct=14.0, days=10)
        t, reason = checker.check_drawdown_trigger(curve_14pct)
        label = f"drawdown=14% → triggered={t} (expected False), reason: {reason}"
        if not t:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 1c: run_kill_switch_check с -16% equity curve
        status = run_kill_switch_check(equity_curve=curve_16pct, data_dir=tmp_data)
        label = f"run_kill_switch_check 16%: triggered={status['triggered']}"
        if status["triggered"]:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1
        # Деактивируем после теста
        checker.deactivate_kill_switch()

        # ── Drill 2: Manual trigger ───────────────────────────────────────────
        _header("Drill 2: Manual trigger (kill_switch_active.json)")

        # 2a: файл не существует → не срабатывает
        t, reason = checker.check_manual_trigger()
        label = f"no file → triggered={t} (expected False)"
        if not t:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 2b: создаём файл вручную
        active_path = tmp_data / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "drill test", "ts": "now"}), encoding="utf-8")

        t, reason = checker.check_manual_trigger()
        label = f"file present → triggered={t} (expected True), reason: {reason}"
        if t:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 2c: run_kill_switch_check при наличии файла → triggered
        status = run_kill_switch_check(equity_curve=[], data_dir=tmp_data)
        label = f"run_kill_switch_check with file: triggered={status['triggered']}"
        if status["triggered"]:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # ── Drill 3: All-cash allocation ──────────────────────────────────────
        _header("Drill 3: All-cash allocation")

        # Файл всё ещё активен из Drill 2
        status = run_kill_switch_check(equity_curve=[], data_dir=tmp_data)
        allocation = status.get("allocation", {})

        # 3a: все протоколы = 0.0
        protocols_zero = all(
            v == 0.0 for k, v in allocation.items() if k != "cash"
        )
        label = f"all protocols = 0.0: {protocols_zero}  allocation keys: {list(allocation.keys())}"
        if protocols_zero and allocation:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 3b: cash = 1.0
        cash_val = allocation.get("cash", -1)
        label = f"allocation['cash'] = {cash_val} (expected 1.0)"
        if cash_val == 1.0:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 3c: allocation содержит известные протоколы
        known = {"aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple"}
        has_known = bool(known & set(allocation.keys()))
        label = f"allocation contains known protocols: {has_known}  (keys: {sorted(allocation.keys())})"
        if has_known:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # ── Drill 4: Deactivate ───────────────────────────────────────────────
        _header("Drill 4: Deactivate and verify clean state")

        # 4a: деактивируем
        checker.deactivate_kill_switch()
        t, reason = checker.check_manual_trigger()
        label = f"after deactivate: triggered={t} (expected False)"
        if not t:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 4b: kill_switch_active.json удалён
        active_exists = active_path.exists()
        label = f"kill_switch_active.json removed: {not active_exists}"
        if not active_exists:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

        # 4c: повторная проверка → not triggered (нет файла, equity пуста)
        status = run_kill_switch_check(equity_curve=[], data_dir=tmp_data)
        label = f"after deactivate run_kill_switch_check: triggered={status['triggered']} (expected False)"
        if not status["triggered"]:
            _pass(label)
            passed += 1
        else:
            _fail(label)
            failed += 1

    # ── Итог ─────────────────────────────────────────────────────────────────
    _header("Результаты drill")
    total = passed + failed
    color = _GREEN if failed == 0 else _RED
    print(f"  {color}{_BOLD}{passed}/{total} PASS{_RESET}")
    if failed > 0:
        print(f"  {_RED}{failed} FAIL{_RESET}")
        return 1
    print(f"\n  {_GREEN}{_BOLD}Kill-switch drill PASSED ✅{_RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(run_drill())
