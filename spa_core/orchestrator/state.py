"""
SPA Orchestrator — State (M4)

SPAState — TypedDict, описывающий состояние одной итерации оркестратора.
Передаётся между нодами графа (LangGraph-compatible).
"""
from __future__ import annotations

from typing import TypedDict


class SPAState(TypedDict, total=False):
    """
    Состояние одной итерации SPA оркестратора.

    LangGraph-compatible: каждая нода получает state и возвращает обновлённый state.
    """

    # ── Мета ──────────────────────────────────────────────────────────────────
    iteration:   int          # номер итерации (1-based)
    timestamp:   str          # ISO 8601 UTC — начало итерации
    strategy_id: str          # "paper-v1"

    # ── Данные рынка ──────────────────────────────────────────────────────────
    snapshots:   list[dict]   # из DataAgent (DeFiLlama APY/TVL)
    fetch_ok:    bool         # успешно ли получены данные

    # ── Мониторинг ────────────────────────────────────────────────────────────
    health:      dict         # результат HealthCheck.run()
    alerts:      list[dict]   # active alerts из MonitoringAgent
    is_blocked:  bool         # True = kill switch или CRITICAL alert

    # ── Стратегия ─────────────────────────────────────────────────────────────
    signals:     list[dict]   # recommendations из StrategyAgent
    reasoning:   str          # текстовое обоснование Strategy

    # ── Решения CEO ───────────────────────────────────────────────────────────
    decisions:   list[dict]   # trade decisions из CEOAgent

    # ── Исполнение ────────────────────────────────────────────────────────────
    execution_results: list[dict]  # результаты PaperTrader

    # ── Сообщения шины ────────────────────────────────────────────────────────
    published_ids: list[str]  # все message_id опубликованные в этой итерации

    # ── Ошибки ────────────────────────────────────────────────────────────────
    errors: list[str]         # некритические ошибки итерации


def initial_state(iteration: int = 1, strategy_id: str = "paper-v1") -> SPAState:
    """Начальное состояние для новой итерации."""
    from datetime import datetime, timezone
    return SPAState(
        iteration          = iteration,
        timestamp          = datetime.now(timezone.utc).isoformat(),
        strategy_id        = strategy_id,
        snapshots          = [],
        fetch_ok           = False,
        health             = {},
        alerts             = [],
        is_blocked         = False,
        signals            = [],
        reasoning          = "",
        decisions          = [],
        execution_results  = [],
        published_ids      = [],
        errors             = [],
    )
