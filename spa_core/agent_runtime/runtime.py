"""Agent runtime v1 — guard-обёртка запусков агентов (SPA-V421 / MP-301).

:class:`AgentRuntime` — каркас агентного слоя (MASTER_PLAN §2, Phase 3):

* загружает письменные мандаты (``mandates/*.json``);
* :meth:`check_permission` — проверка действия против forbidden-list мандата
  (нет мандата → нет допуска: deny-by-default);
* :meth:`run_agent` — guard-обёртка: мандат существует → деградация при
  недоступности LLM (``skip`` | ``deterministic-only``) → списание
  токен-бюджета → выполнение с перехватом исключений → структурированный
  результат + запись в журнал ``data/agent_runtime_log.json`` (атомарно,
  ротация: последние :data:`LOG_MAX_ENTRIES` записей).

КОНСТИТУЦИЯ (SPA-BL-011 / LLM_FORBIDDEN_AGENTS): в spa_core НЕТ ни одного
импорта LLM SDK — runtime лишь каркас. LLM-клиент и probe доступности
ИНЖЕКТИРУЮТСЯ снаружи как callable; по умолчанию (офлайн, без клиента) LLM
считается НЕДОСТУПНЫМ и срабатывает деградация. Pure stdlib, без сети.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union

from .budget import TokenBudgetTracker, _atomic_write_json
from .mandate import AgentMandate, DEFAULT_MANDATES_DIR, load_all_mandates

log = logging.getLogger("spa.agent_runtime.runtime")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = _PROJECT_ROOT / "data" / "agent_runtime_log.json"

SCHEMA_VERSION = 1
LOG_MAX_ENTRIES = 200

# Статусы структурированного результата run_agent
STATUS_OK = "ok"
STATUS_NO_MANDATE = "no_mandate"
STATUS_BUDGET_EXHAUSTED = "budget_exhausted"
STATUS_SKIPPED_DEGRADED = "skipped_degraded"
STATUS_ERROR = "error"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRuntime:
    """Каркас запуска агентов: мандаты + бюджеты + деградация + журнал.

    Параметры:

    * ``llm`` — инжектируемый LLM-callable (или None — офлайн). В spa_core
      никогда не создаётся: его подаёт внешний оркестратор.
    * ``llm_probe`` — callable → bool «LLM доступен?». По умолчанию
      ``llm is not None`` (без клиента — недоступен).
    * ``budget`` / ``mandates_dir`` / ``log_path`` — инжектируются для тестов.
    """

    def __init__(
        self,
        mandates_dir: Union[str, Path] = DEFAULT_MANDATES_DIR,
        log_path: Union[str, Path] = DEFAULT_LOG_PATH,
        llm: Optional[Callable[..., Any]] = None,
        llm_probe: Optional[Callable[[], bool]] = None,
        budget: Optional[TokenBudgetTracker] = None,
        usage_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self._mandates_dir = Path(mandates_dir)
        self._log_path = Path(log_path)
        self._llm = llm
        self._llm_probe = llm_probe or (lambda: self._llm is not None)
        self.mandates: Dict[str, AgentMandate] = {}
        self.load_mandates()
        if budget is not None:
            self.budget = budget
        else:
            kwargs = {"usage_path": usage_path} if usage_path is not None else {}
            self.budget = TokenBudgetTracker(self.mandates, **kwargs)

    # ── мандаты / допуски ─────────────────────────────────────────────────

    def load_mandates(self) -> Dict[str, AgentMandate]:
        """(Пере)загрузить мандаты из ``mandates_dir``."""
        self.mandates = load_all_mandates(self._mandates_dir)
        return self.mandates

    def llm_available(self) -> bool:
        """Доступен ли LLM (probe инжектирован; офлайн-дефолт — False)."""
        try:
            return bool(self._llm_probe())
        except Exception as exc:  # битый probe == недоступный LLM
            log.warning("llm_probe raised %s — treating LLM as unavailable", exc)
            return False

    def check_permission(self, agent: str, action: str) -> Tuple[bool, str]:
        """Допуск действия по мандату. Deny-by-default: нет мандата → запрет."""
        mandate = self.mandates.get(agent)
        if mandate is None:
            return False, f"no mandate for agent {agent!r} — denied by default"
        if action in mandate.forbidden_actions:
            return False, f"action {action!r} is in forbidden_actions of {agent!r}"
        return True, "ok"

    # ── guard-обёртка запуска ─────────────────────────────────────────────

    def run_agent(
        self,
        name: str,
        fn: Callable[..., Any],
        tokens: int = 0,
    ) -> Dict[str, Any]:
        """Запустить агента ``name`` через guard.

        ``fn(llm=...)`` получает инжектированный LLM-callable либо ``None``
        (деградация deterministic-only / агент без LLM). ``tokens`` —
        списываемая оценка расхода (0 для детерминированных путей).

        Возвращает структурированный результат::

            {"agent", "status", "result", "reason", "degraded",
             "tokens_charged", "ts"}
        """
        entry: Dict[str, Any] = {
            "agent": name,
            "status": STATUS_ERROR,
            "result": None,
            "reason": "",
            "degraded": False,
            "tokens_charged": 0,
            "ts": _utc_iso(),
        }

        mandate = self.mandates.get(name)
        if mandate is None:
            entry["status"] = STATUS_NO_MANDATE
            entry["reason"] = f"no mandate for agent {name!r}"
            return self._finish(entry)

        # Деградация: LLM требуется, но недоступен.
        if mandate.requires_llm and not self.llm_available():
            if mandate.degradation_mode == "skip":
                entry["status"] = STATUS_SKIPPED_DEGRADED
                entry["degraded"] = True
                entry["reason"] = "LLM unavailable — degradation_mode=skip"
                log.info("agent %s skipped: LLM unavailable (skip mode)", name)
                return self._finish(entry)
            # deterministic-only: выполняем fn без LLM, токены не списываем.
            entry["degraded"] = True
            entry["reason"] = "LLM unavailable — running deterministic-only (llm=None)"
            return self._finish(self._execute(entry, fn, llm=None))

        # Бюджет (списывается ДО вызова — превышение блокирует запуск).
        self.budget.start_run(name)
        ok, reason = self.budget.charge(name, tokens)
        if not ok:
            entry["status"] = STATUS_BUDGET_EXHAUSTED
            entry["reason"] = reason
            log.warning("agent %s blocked: %s", name, reason)
            return self._finish(entry)
        entry["tokens_charged"] = tokens

        llm = self._llm if mandate.requires_llm else None
        return self._finish(self._execute(entry, fn, llm=llm))

    def _execute(
        self, entry: Dict[str, Any], fn: Callable[..., Any], llm: Optional[Callable[..., Any]]
    ) -> Dict[str, Any]:
        """Вызвать fn(llm=...), перехватив любое исключение агента."""
        try:
            entry["result"] = fn(llm=llm)
            entry["status"] = STATUS_OK
            if not entry["reason"]:
                entry["reason"] = "ok"
        except Exception as exc:
            entry["status"] = STATUS_ERROR
            entry["result"] = None
            entry["reason"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=5)
            log.error("agent %s raised: %s", entry["agent"], entry["reason"])
        return entry

    # ── журнал запусков ───────────────────────────────────────────────────

    def _finish(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self._append_log(entry)
        return entry

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Дописать запись в журнал (атомарно, ротация LOG_MAX_ENTRIES)."""
        entries = []
        try:
            raw = json.loads(self._log_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
                entries = raw["entries"]
        except (OSError, json.JSONDecodeError):
            pass
        entries.append(entry)
        entries = entries[-LOG_MAX_ENTRIES:]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _utc_iso(),
            "max_entries": LOG_MAX_ENTRIES,
            "entries": entries,
        }
        try:
            _atomic_write_json(payload, self._log_path)
        except OSError as exc:  # журнал не должен валить запуск агента
            log.error("cannot write runtime log %s: %s", self._log_path, exc)
