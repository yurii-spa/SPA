"""Token budget tracking per-agent (SPA-V421 / MP-301).

:class:`TokenBudgetTracker` ведёт учёт расхода LLM-токенов per-run и per-day
для каждого агента против лимитов его мандата (:class:`AgentMandate`).
Состояние персистится в ``data/agent_token_usage.json`` атомарной записью
(tmp + ``os.replace`` — паттерн ``spa_core/adapter_sdk/registry.py``), daily
сбрасывается по смене даты UTC.

Pure stdlib, без сети, без LLM SDK. ``now_fn`` инжектируется для тестов
(детерминированная проверка daily reset без ожидания полуночи).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, Union

from spa_core.utils.atomic import atomic_save
from .mandate import AgentMandate

log = logging.getLogger("spa.agent_runtime.budget")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USAGE_PATH = _PROJECT_ROOT / "data" / "agent_token_usage.json"

SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write_json(obj: dict, out_path: Path) -> None:
    """Атомарная запись JSON через centralized atomic_save (MP-1452)."""
    atomic_save(obj, str(out_path))


class TokenBudgetTracker:
    """Учёт токенов per-run / per-day против бюджетов мандатов.

    Файл состояния::

        {
          "schema_version": 1,
          "date": "YYYY-MM-DD",          # UTC-день, к которому относится daily
          "agents": {
            "<name>": {"daily_used": int, "run_used": int, "runs_today": int}
          }
        }
    """

    def __init__(
        self,
        mandates: Dict[str, AgentMandate],
        usage_path: Union[str, Path] = DEFAULT_USAGE_PATH,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._mandates = dict(mandates)
        self._usage_path = Path(usage_path)
        self._now_fn = now_fn
        self._state = self._load_state()
        self._roll_date(persist=False)

    # ── состояние ─────────────────────────────────────────────────────────

    def _today(self) -> str:
        return self._now_fn().astimezone(timezone.utc).strftime("%Y-%m-%d")

    def _load_state(self) -> dict:
        try:
            raw = json.loads(self._usage_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("agents"), dict):
                return raw
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": SCHEMA_VERSION, "date": self._today(), "agents": {}}

    def _persist(self) -> None:
        _atomic_write_json(self._state, self._usage_path)

    def _roll_date(self, persist: bool = True) -> None:
        """Сброс daily-счётчиков при смене UTC-даты."""
        today = self._today()
        if self._state.get("date") != today:
            log.info("token budget daily reset: %s -> %s", self._state.get("date"), today)
            self._state["date"] = today
            self._state["agents"] = {}
            if persist:
                self._persist()

    def _agent_state(self, agent: str) -> dict:
        return self._state["agents"].setdefault(
            agent, {"daily_used": 0, "run_used": 0, "runs_today": 0}
        )

    # ── публичный API ─────────────────────────────────────────────────────

    def start_run(self, agent: str) -> None:
        """Начать новый запуск агента: обнулить per-run счётчик."""
        self._roll_date()
        st = self._agent_state(agent)
        st["run_used"] = 0
        st["runs_today"] = int(st.get("runs_today", 0)) + 1
        self._persist()

    def charge(self, agent: str, tokens: int) -> Tuple[bool, str]:
        """Списать ``tokens`` с бюджета агента.

        Возвращает ``(True, "ok")`` либо ``(False, причина)`` — при
        неизвестном агенте, некорректном количестве или исчерпании
        per-run / daily бюджета. При отказе НИЧЕГО не списывается.
        """
        self._roll_date()
        mandate = self._mandates.get(agent)
        if mandate is None:
            return False, f"no mandate for agent {agent!r}"
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            return False, f"invalid token amount: {tokens!r}"

        st = self._agent_state(agent)
        run_after = int(st.get("run_used", 0)) + tokens
        daily_after = int(st.get("daily_used", 0)) + tokens
        if run_after > mandate.token_budget_per_run:
            return False, (
                f"per-run budget exhausted for {agent!r}: "
                f"{run_after} > {mandate.token_budget_per_run}"
            )
        if daily_after > mandate.token_budget_daily:
            return False, (
                f"daily budget exhausted for {agent!r}: "
                f"{daily_after} > {mandate.token_budget_daily}"
            )

        st["run_used"] = run_after
        st["daily_used"] = daily_after
        self._persist()
        return True, "ok"

    def remaining(self, agent: str) -> Optional[Dict[str, int]]:
        """Остатки бюджета: ``{"run": int, "daily": int}``; None если мандата нет."""
        self._roll_date()
        mandate = self._mandates.get(agent)
        if mandate is None:
            return None
        st = self._agent_state(agent)
        return {
            "run": max(0, mandate.token_budget_per_run - int(st.get("run_used", 0))),
            "daily": max(0, mandate.token_budget_daily - int(st.get("daily_used", 0))),
        }

    def usage(self, agent: str) -> Dict[str, int]:
        """Текущий расход агента (нули, если агент ещё не запускался)."""
        self._roll_date()
        st = self._state["agents"].get(agent, {})
        return {
            "run_used": int(st.get("run_used", 0)),
            "daily_used": int(st.get("daily_used", 0)),
            "runs_today": int(st.get("runs_today", 0)),
        }
