#!/usr/bin/env python3
"""SPA Kill-Switch Engine (MP-108).

Механизм экстренной остановки paper-trading: при срабатывании любого триггера
переводит все позиции в Cash (allocation = {"cash": 1.0, все протоколы: 0.0}).

Триггеры:
1. drawdown_trigger  — просадка equity > 15% от максимума за последние 30 дней
2. red_flags_trigger — более 5 активных красных флагов в data/red_flags.json
3. manual_trigger    — файл data/kill_switch_active.json существует (создаётся вручную)
4. sharpe_trigger    — Sharpe < -1.0 (из data/analytics_summary.json), но только
                       при наличии ≥30 дней данных (малая выборка → артефакт)

Правила:
* LLM FORBIDDEN — детерминированная логика, никаких внешних вызовов.
* Stdlib only. Atomic writes (tmp + os.replace).
* Активация автоматическая; деактивация только через deactivate_kill_switch() вручную.
* approved=False от kill-switch не может быть переопределён агентом.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.kill_switch")

# ─── Constants ────────────────────────────────────────────────────────────────

DRAWDOWN_THRESHOLD_PCT = 15.0   # % просадки от 30-дневного максимума
RED_FLAGS_THRESHOLD = 5          # количество красных флагов для срабатывания
SHARPE_THRESHOLD = -1.0          # порог Sharpe ratio
LOOKBACK_DAYS = 30               # окно для drawdown/Sharpe
MIN_DAYS_FOR_SHARPE = 30         # минимум дней данных, чтобы Sharpe считался надёжным
                                 # сигналом для kill-switch (малая выборка → деление
                                 # на ~0 волатильность даёт артефактный Sharpe)

KILL_SWITCH_ACTIVE_FILENAME = "kill_switch_active.json"
KILL_SWITCH_STATUS_FILENAME = "kill_switch_status.json"
RED_FLAGS_FILENAME = "red_flags.json"
ANALYTICS_FILENAME = "analytics_summary.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"

# Fallback список протоколов, если adapter_status.json недоступен
_KNOWN_PROTOCOLS = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple", "sky_susds"]


# ─── Atomic IO helpers ────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default: Any = None) -> Any:
    """Читает JSON защищённо; при ошибке возвращает default (никогда не бросает)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


# ─── KillSwitchChecker ────────────────────────────────────────────────────────


class KillSwitchChecker:
    """Проверяет все 4 триггера kill-switch.

    Parameters
    ----------
    data_dir : путь к папке data/ (по умолчанию <repo>/data)
    """

    def __init__(self, data_dir: str | os.PathLike | None = None) -> None:
        if data_dir is None:
            # По умолчанию: <repo>/data (два уровня вверх от этого файла)
            self.data_dir = Path(__file__).resolve().parents[2] / "data"
        else:
            self.data_dir = Path(data_dir)

    # ── Trigger 1: drawdown ───────────────────────────────────────────────────

    def check_drawdown_trigger(self, equity_curve: list[dict]) -> tuple[bool, str]:
        """Просадка equity > DRAWDOWN_THRESHOLD_PCT% от максимума за 30 дней.

        Parameters
        ----------
        equity_curve : список дневных баров {"date": "...", "close_equity": float, ...}

        Returns
        -------
        (triggered, reason)
        """
        if not equity_curve or not isinstance(equity_curve, list):
            return False, "no equity data"

        # Берём последние 30 точек
        window = equity_curve[-LOOKBACK_DAYS:]
        if not window:
            return False, "empty equity window"

        try:
            closes = [float(bar.get("close_equity") or bar.get("equity") or 0.0)
                      for bar in window]
        except (TypeError, ValueError):
            return False, "invalid equity data"

        closes = [c for c in closes if c > 0]
        if len(closes) < 2:
            return False, "insufficient equity data"

        peak = max(closes)
        current = closes[-1]

        if peak <= 0:
            return False, "peak equity is zero"

        drawdown_pct = (peak - current) / peak * 100.0

        if drawdown_pct > DRAWDOWN_THRESHOLD_PCT:
            reason = (
                f"drawdown {drawdown_pct:.2f}% > {DRAWDOWN_THRESHOLD_PCT}% threshold "
                f"(peak={peak:.2f}, current={current:.2f}, window={len(window)}d)"
            )
            log.warning("KILL SWITCH drawdown trigger: %s", reason)
            return True, reason

        return False, f"drawdown {drawdown_pct:.2f}% ≤ {DRAWDOWN_THRESHOLD_PCT}%"

    # ── Trigger 2: red flags ──────────────────────────────────────────────────

    def check_red_flags_trigger(self) -> tuple[bool, str]:
        """Более RED_FLAGS_THRESHOLD красных флагов в data/red_flags.json.

        Returns
        -------
        (triggered, reason)
        """
        doc = _read_json(self.data_dir / RED_FLAGS_FILENAME, {})
        if not isinstance(doc, dict):
            return False, "red_flags.json missing or invalid"

        flags = doc.get("red_flags")
        if not isinstance(flags, list):
            return False, "no red_flags list in file"

        count = len(flags)

        if count > RED_FLAGS_THRESHOLD:
            reason = (
                f"red_flags count {count} > {RED_FLAGS_THRESHOLD} threshold "
                f"(from {RED_FLAGS_FILENAME})"
            )
            log.warning("KILL SWITCH red_flags trigger: %s", reason)
            return True, reason

        return False, f"red_flags count {count} ≤ {RED_FLAGS_THRESHOLD}"

    # ── Trigger 3: manual ────────────────────────────────────────────────────

    def check_manual_trigger(self) -> tuple[bool, str]:
        """Файл data/kill_switch_active.json существует (создаётся вручную).

        Returns
        -------
        (triggered, reason)
        """
        active_path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if active_path.exists():
            doc = _read_json(active_path, {})
            # Явный active=False означает деактивацию (для сред, где файл нельзя
            # удалить — overwrite вместо unlink). Триггер не срабатывает.
            if isinstance(doc, dict) and doc.get("active") is False:
                return False, (
                    f"{KILL_SWITCH_ACTIVE_FILENAME} present but active=False "
                    f"(reason: {doc.get('reason') or 'deactivated'})"
                )
            manual_reason = ""
            if isinstance(doc, dict):
                manual_reason = str(doc.get("reason") or "")
            reason = f"manual trigger active (file: {KILL_SWITCH_ACTIVE_FILENAME}"
            if manual_reason:
                reason += f", reason: {manual_reason}"
            reason += ")"
            log.warning("KILL SWITCH manual trigger: %s", reason)
            return True, reason

        return False, f"{KILL_SWITCH_ACTIVE_FILENAME} not found"

    # ── Trigger 4: Sharpe ────────────────────────────────────────────────────

    def check_sharpe_trigger(self) -> tuple[bool, str]:
        """Sharpe < SHARPE_THRESHOLD за 30 дней из data/analytics_summary.json.

        Returns
        -------
        (triggered, reason)
        """
        doc = _read_json(self.data_dir / ANALYTICS_FILENAME, {})
        if not isinstance(doc, dict):
            return False, f"{ANALYTICS_FILENAME} missing or invalid"

        metrics = doc.get("metrics")
        if not isinstance(metrics, dict):
            return False, "no metrics in analytics_summary"

        sharpe = metrics.get("sharpe")
        if sharpe is None:
            return False, "sharpe not in analytics_summary"

        try:
            sharpe_val = float(sharpe)
        except (TypeError, ValueError):
            return False, f"invalid sharpe value: {sharpe}"

        # Малая выборка → волатильность ≈ 0 → Sharpe artefactно зашкаливает
        # (наблюдали sharpe -61 на 5 днях). Требуем минимум MIN_DAYS_FOR_SHARPE
        # дней данных, иначе Sharpe не считается надёжным сигналом для kill-switch.
        num_days = doc.get("num_days")
        if num_days is None:
            num_days = metrics.get("num_days", 0)
        try:
            num_days = float(num_days) if num_days is not None else 0
        except (TypeError, ValueError):
            num_days = 0
        if num_days < MIN_DAYS_FOR_SHARPE:
            return False, (
                f"sharpe {sharpe_val:.4f} — insufficient data "
                f"({num_days:.0f} days < {MIN_DAYS_FOR_SHARPE} required)"
            )

        if sharpe_val < SHARPE_THRESHOLD:
            reason = (
                f"sharpe {sharpe_val:.4f} < {SHARPE_THRESHOLD} threshold "
                f"(from {ANALYTICS_FILENAME}, {num_days} days)"
            )
            log.warning("KILL SWITCH sharpe trigger: %s", reason)
            return True, reason

        return False, f"sharpe {sharpe_val:.4f} ≥ {SHARPE_THRESHOLD}"

    # ── Main check ────────────────────────────────────────────────────────────

    def is_kill_switch_active(
        self, equity_curve: list[dict] | None = None
    ) -> tuple[bool, str]:
        """Проверяет все триггеры, возвращает (active, reason) для первого сработавшего.

        Порядок проверки: manual → drawdown → red_flags → sharpe.

        Parameters
        ----------
        equity_curve : список дневных баров; если None — будет прочитан из файла.

        Returns
        -------
        (triggered: bool, reason: str)
        """
        # Порядок: сначала manual (мгновенная остановка), потом метрические
        for check_fn, needs_curve in [
            (self._check_manual_wrap, False),
            (self._check_drawdown_wrap, True),
            (self._check_red_flags_wrap, False),
            (self._check_sharpe_wrap, False),
        ]:
            if needs_curve:
                triggered, reason = check_fn(equity_curve)
            else:
                triggered, reason = check_fn(None)
            if triggered:
                return True, reason

        return False, "all triggers clear"

    def _check_manual_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_manual_trigger()

    def _check_drawdown_wrap(self, equity_curve: list[dict] | None) -> tuple[bool, str]:
        if equity_curve is None:
            # Читаем из файла
            equity_doc = _read_json(
                self.data_dir / "equity_curve_daily.json", {}
            )
            if isinstance(equity_doc, dict):
                equity_curve = equity_doc.get("daily") or []
            else:
                equity_curve = []
        return self.check_drawdown_trigger(equity_curve)

    def _check_red_flags_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_red_flags_trigger()

    def _check_sharpe_wrap(self, _curve: Any) -> tuple[bool, str]:
        return self.check_sharpe_trigger()

    # ── State management ──────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str) -> None:
        """Записывает data/kill_switch_active.json атомарно с reason + timestamp.

        Используется для программной активации. При ручной — файл создаётся вручную.
        """
        doc = {
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "source": "kill_switch_checker",
        }
        path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        _atomic_write_json(path, doc)
        log.critical("KILL SWITCH ACTIVATED: %s → %s", reason, path)

    def deactivate_kill_switch(self) -> None:
        """Удаляет data/kill_switch_active.json (деактивация kill-switch)."""
        path = self.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if path.exists():
            path.unlink()
            log.info("Kill switch deactivated: %s removed", path)
        else:
            log.info("Kill switch already inactive (file not found)")

    # ── Allocation ────────────────────────────────────────────────────────────

    def get_kill_switch_allocation(self) -> dict[str, float]:
        """Возвращает all-cash аллокацию: {"cash": 1.0, все протоколы: 0.0}.

        Пытается прочитать список протоколов из data/adapter_status.json;
        при отсутствии использует _KNOWN_PROTOCOLS.
        """
        protocols: list[str] = []

        # Попытка 1: adapter_status.json (execution-домен)
        adapter_status = _read_json(self.data_dir / ADAPTER_STATUS_FILENAME, None)
        if isinstance(adapter_status, dict):
            adapters_list = adapter_status.get("adapters") or []
            if isinstance(adapters_list, list):
                for entry in adapters_list:
                    if isinstance(entry, dict) and entry.get("protocol"):
                        protocols.append(str(entry["protocol"]))

        # Попытка 2: adapter_orchestrator_status.json
        if not protocols:
            orch_status = _read_json(
                self.data_dir / "adapter_orchestrator_status.json", None
            )
            if isinstance(orch_status, dict):
                adapters_list = orch_status.get("adapters") or []
                if isinstance(adapters_list, list):
                    for entry in adapters_list:
                        if isinstance(entry, dict) and entry.get("protocol"):
                            protocols.append(str(entry["protocol"]))

        # Fallback на известный список
        if not protocols:
            protocols = list(_KNOWN_PROTOCOLS)

        allocation: dict[str, float] = {"cash": 1.0}
        for p in protocols:
            allocation[p] = 0.0
        return allocation


# ─── Public entry point ───────────────────────────────────────────────────────


def run_kill_switch_check(
    equity_curve: list[dict] | None = None,
    data_dir: str | os.PathLike | None = None,
) -> dict:
    """Точка входа для cycle_runner.

    Проверяет все триггеры. При срабатывании:
    - Активирует kill-switch (создаёт kill_switch_active.json)
    - Записывает data/kill_switch_status.json

    Если не сработал и ранее был активен — **НЕ деактивирует** (ручная деактивация).

    Returns
    -------
    dict с ключами:
        triggered   : bool
        reason      : str
        allocation  : dict (all-cash при triggered=True, иначе {})
        ts          : str (ISO timestamp)
    """
    checker = KillSwitchChecker(data_dir=data_dir)
    now_ts = datetime.now(timezone.utc).isoformat()

    triggered, reason = checker.is_kill_switch_active(equity_curve=equity_curve)

    allocation: dict[str, float] = {}
    if triggered:
        allocation = checker.get_kill_switch_allocation()
        # Активируем (или обновляем) kill_switch_active.json только если он ещё не стоит
        active_path = checker.data_dir / KILL_SWITCH_ACTIVE_FILENAME
        if not active_path.exists():
            checker.activate_kill_switch(reason)
        # Пишем kill_switch_status.json
        status_doc = {
            "generated_at": now_ts,
            "triggered": True,
            "reason": reason,
            "allocation": allocation,
        }
        try:
            _atomic_write_json(checker.data_dir / KILL_SWITCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("Failed to write kill_switch_status.json: %s", exc)
    else:
        # Пишем статус "не активен"
        status_doc = {
            "generated_at": now_ts,
            "triggered": False,
            "reason": reason,
            "allocation": {},
        }
        try:
            _atomic_write_json(checker.data_dir / KILL_SWITCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("Failed to write kill_switch_status.json: %s", exc)

    return {
        "triggered": triggered,
        "reason": reason,
        "allocation": allocation,
        "ts": now_ts,
    }
