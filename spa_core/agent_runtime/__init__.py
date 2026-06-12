"""Agent runtime v1 (SPA-V421 / MP-301) — мандаты, токен-бюджеты,
forbidden-lists, деградация при недоступности LLM.

Каркас агентного слоя Phase 3 (MASTER_PLAN §2). LLM SDK здесь НЕ
импортируются (конституция LLM_FORBIDDEN_AGENTS / llm_forbidden_lint):
LLM-клиент инжектируется снаружи как callable.
"""
from .mandate import (
    LLM_FORBIDDEN_AGENTS,
    VALID_DEGRADATION_MODES,
    DEFAULT_MANDATES_DIR,
    AgentMandate,
    load_all_mandates,
    load_mandate_file,
    save_mandate,
)
from .budget import DEFAULT_USAGE_PATH, TokenBudgetTracker
from .runtime import (
    DEFAULT_LOG_PATH,
    LOG_MAX_ENTRIES,
    STATUS_BUDGET_EXHAUSTED,
    STATUS_ERROR,
    STATUS_NO_MANDATE,
    STATUS_OK,
    STATUS_SKIPPED_DEGRADED,
    AgentRuntime,
)

__all__ = [
    "LLM_FORBIDDEN_AGENTS",
    "VALID_DEGRADATION_MODES",
    "DEFAULT_MANDATES_DIR",
    "AgentMandate",
    "load_all_mandates",
    "load_mandate_file",
    "save_mandate",
    "DEFAULT_USAGE_PATH",
    "TokenBudgetTracker",
    "DEFAULT_LOG_PATH",
    "LOG_MAX_ENTRIES",
    "STATUS_BUDGET_EXHAUSTED",
    "STATUS_ERROR",
    "STATUS_NO_MANDATE",
    "STATUS_OK",
    "STATUS_SKIPPED_DEGRADED",
    "AgentRuntime",
]
