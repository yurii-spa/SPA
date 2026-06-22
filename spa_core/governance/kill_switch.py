#!/usr/bin/env python3
"""SPA Kill-Switch Engine (MP-108).

Механизм экстренной остановки paper-trading: при срабатывании любого триггера
переводит все позиции в Cash (allocation = {"cash": 1.0, все протоколы: 0.0}).

Триггеры:
1. drawdown_trigger  — просадка equity ≥ 5% от максимума за последние 30 дней
                       (основной трек; ADR-023). Для альтернативных более рисковых
                       стратегий порог конфигурируется до 15% (DRAWDOWN_ALT_MAX_PCT).
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

DRAWDOWN_THRESHOLD_PCT = 5.0    # % просадки от 30-дневного максимума — основной трек
                                # (ADR-023; единый источник = RiskConfig.max_drawdown_stop).
DRAWDOWN_ALT_MAX_PCT = 15.0     # верхняя граница порога для альтернативных более
                                # рисковых стратегий (тестовый режим, ADR-023).
RED_FLAGS_THRESHOLD = 5          # количество красных флагов для срабатывания
SHARPE_THRESHOLD = -1.0          # порог Sharpe ratio (нормальный период, ≥60 дней)
LOOKBACK_DAYS = 30               # окно для drawdown/Sharpe
MIN_DAYS_FOR_SHARPE = 30         # минимум дней данных, чтобы Sharpe считался надёжным
                                 # сигналом для kill-switch (малая выборка → деление
                                 # на ~0 волатильность даёт артефактный Sharpe)

# Early-period grace: в первые SHARPE_EARLY_PERIOD_DAYS дней трека Sharpe
# может быть отрицательным из-за малой выборки или раскачки — используем
# мягкий порог SHARPE_EARLY_THRESHOLD вместо SHARPE_THRESHOLD.
# Значения читаются из risk_policy.json; ниже — compile-time дефолты.
SHARPE_EARLY_PERIOD_DAYS = 60   # первые N дней → early period
SHARPE_EARLY_THRESHOLD = -2.0   # мягкий порог в early period

KILL_SWITCH_ACTIVE_FILENAME = "kill_switch_active.json"
KILL_SWITCH_STATUS_FILENAME = "kill_switch_status.json"
RED_FLAGS_FILENAME = "red_flags.json"
ANALYTICS_FILENAME = "analytics_summary.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"

# Fallback список протоколов, если adapter_status.json недоступен
_KNOWN_PROTOCOLS = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple", "sky_susds"]


# ─── Atomic IO helpers ────────────────────────────────────────────────────────


def _load_sharpe_policy(data_dir: Path) -> dict[str, float]:
    """Читает Sharpe-параметры из data/risk_policy.json; fallback → compile-time дефолты.

    Возвращает dict с ключами:
        kill_threshold     — нормальный порог (≥ early_period_days)
        early_period_days  — длина grace-периода (дней)
        early_threshold    — мягкий порог в early period
    """
    policy = _read_json(data_dir / "risk_policy.json", {})
    if not isinstance(policy, dict):
        policy = {}
    return {
        "kill_threshold": float(policy.get("SHARPE_KILL_THRESHOLD", SHARPE_THRESHOLD)),
        "early_period_days": float(policy.get("SHARPE_EARLY_PERIOD_DAYS", SHARPE_EARLY_PERIOD_DAYS)),
        "early_threshold": float(policy.get("SHARPE_EARLY_THRESHOLD", SHARPE_EARLY_THRESHOLD)),
    }


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

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        drawdown_threshold_pct: float | None = None,
    ) -> None:
        if data_dir is None:
            # По умолчанию: <repo>/data (два уровня вверх от этого файла)
            self.data_dir = Path(__file__).resolve().parents[2] / "data"
        else:
            self.data_dir = Path(data_dir)

        # Drawdown-порог. Приоритет: явный аргумент → data/risk_policy.json
        # (DRAWDOWN_KILL_THRESHOLD_PCT) → compile-time дефолт (5% основного трека).
        # Клампится в [0, DRAWDOWN_ALT_MAX_PCT]: альт-стратегии могут поднять до 15%,
        # но не выше. Никакой агент не может ослабить порог сверх этой границы.
        if drawdown_threshold_pct is None:
            policy = _read_json(self.data_dir / "risk_policy.json", {})
            if not isinstance(policy, dict):
                policy = {}
            drawdown_threshold_pct = float(
                policy.get("DRAWDOWN_KILL_THRESHOLD_PCT", DRAWDOWN_THRESHOLD_PCT)
            )
        self.drawdown_threshold_pct = max(
            0.0, min(float(drawdown_threshold_pct), DRAWDOWN_ALT_MAX_PCT)
        )

    # ── Trigger 1: drawdown ───────────────────────────────────────────────────

    def check_drawdown_trigger(self, equity_curve: list[dict]) -> tuple[bool, str]:
        """Просадка equity ≥ self.drawdown_threshold_pct% от максимума за 30 дней.

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
        threshold = self.drawdown_threshold_pct

        if drawdown_pct >= threshold:
            reason = (
                f"drawdown {drawdown_pct:.2f}% ≥ {threshold}% threshold "
                f"(peak={peak:.2f}, current={current:.2f}, window={len(window)}d)"
            )
            log.warning("KILL SWITCH drawdown trigger: %s", reason)
            return True, reason

        return False, f"drawdown {drawdown_pct:.2f}% < {threshold}%"

    # ── Trigger 2: red flags ──────────────────────────────────────────────────

    def check_red_flags_trigger(self) -> tuple[bool, str]:
        """Более RED_FLAGS_THRESHOLD живых красных флагов в data/red_flags.json.

        Bootstrap/fallback данные игнорируются:
        - Если doc.fallback_used=true ИЛИ doc.sources=["bootstrap"] →
          все флаги считаются ненастоящими и kill_switch НЕ срабатывает.
        - Отдельные флаги с f["bootstrap"]=True также исключаются из счётчика.
        Поведение настраивается через data/risk_policy.json:
          RED_FLAGS_IGNORE_BOOTSTRAP (bool, default True)
          RED_FLAGS_THRESHOLD        (int,  default 5)

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

        # Читаем параметры из risk_policy.json (с fallback на compile-time defaults)
        policy = _read_json(self.data_dir / "risk_policy.json", {})
        if not isinstance(policy, dict):
            policy = {}
        ignore_bootstrap: bool = bool(policy.get("RED_FLAGS_IGNORE_BOOTSTRAP", True))
        threshold: int = int(policy.get("RED_FLAGS_THRESHOLD", RED_FLAGS_THRESHOLD))

        if ignore_bootstrap:
            # Документ-уровень: fallback_used=true или sources=["bootstrap"]
            # означает, что все данные — дефолты/заглушки, а не живые.
            doc_fallback = bool(doc.get("fallback_used", False))
            doc_sources = doc.get("sources", [])
            doc_is_bootstrap = (
                isinstance(doc_sources, list) and doc_sources == ["bootstrap"]
            )
            if doc_fallback or doc_is_bootstrap:
                log.warning(
                    "red_flags: source=bootstrap / fallback_used=%s — "
                    "ignoring all %d flags for kill_switch (non-live data)",
                    doc_fallback,
                    len(flags),
                )
                return False, (
                    f"red_flags: {len(flags)} flags ignored "
                    f"(fallback_used={doc_fallback}, sources={doc_sources})"
                )

            # Флаг-уровень: исключаем флаги с явным признаком bootstrap
            live_flags = [f for f in flags if not f.get("bootstrap", False)]
        else:
            live_flags = flags

        count = len(live_flags)

        if count > threshold:
            reason = (
                f"red_flags count {count} > {threshold} threshold "
                f"(from {RED_FLAGS_FILENAME})"
            )
            log.warning("KILL SWITCH red_flags trigger: %s", reason)
            return True, reason

        return False, f"red_flags count {count} ≤ {threshold}"

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
        """Sharpe < threshold за 30+ дней из data/analytics_summary.json.

        Логика порогов (Variant A + B, ADR-ref risk_policy.json):
        - rf=0% (стейблкоин портфель): Sharpe рассчитывается в analytics_runner
          с RISK_FREE_RATE=0.0 — benchmark «держать USDC», не Treasury bills.
        - Early-period grace: если num_days < SHARPE_EARLY_PERIOD_DAYS (60),
          используется мягкий порог SHARPE_EARLY_THRESHOLD (-2.0) вместо
          нормального SHARPE_THRESHOLD (-1.0).

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

        # Читаем Sharpe-параметры из risk_policy.json (Variant A+B).
        sp = _load_sharpe_policy(self.data_dir)
        kill_threshold = sp["kill_threshold"]
        early_period_days = sp["early_period_days"]
        early_threshold = sp["early_threshold"]

        # Определяем применимый порог в зависимости от периода трека.
        if num_days < early_period_days:
            effective_threshold = early_threshold
            period_label = (
                f"early_period ({num_days:.0f}d < {early_period_days:.0f}d grace, "
                f"threshold={early_threshold})"
            )
        else:
            effective_threshold = kill_threshold
            period_label = (
                f"normal_period ({num_days:.0f}d ≥ {early_period_days:.0f}d, "
                f"threshold={kill_threshold})"
            )

        if sharpe_val < effective_threshold:
            reason = (
                f"sharpe {sharpe_val:.4f} < {effective_threshold} "
                f"[{period_label}] (from {ANALYTICS_FILENAME})"
            )
            log.warning("KILL SWITCH sharpe trigger: %s", reason)
            return True, reason

        return False, (
            f"sharpe {sharpe_val:.4f} ≥ {effective_threshold} [{period_label}]"
        )

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
    drawdown_threshold_pct: float | None = None,
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
    checker = KillSwitchChecker(
        data_dir=data_dir, drawdown_threshold_pct=drawdown_threshold_pct
    )
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
