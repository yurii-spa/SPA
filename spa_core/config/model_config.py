"""
SPA Model Routing Config
Defines which Claude model to use per task type.
- claude-opus-4-8: computations, code, paper trading cycles ($5/$25 per MTok)
- claude-fable-5: architect reviews, strategy analysis, risk assessments ($10/$50 per MTok)
"""

MODEL_CODE = "claude-opus-4-8"        # вычисления, код, цикл трейдинга
MODEL_ARCHITECT = "claude-fable-5"    # архитектура, анализ стратегий, ревью
MODEL_DEFAULT = "claude-opus-4-8"

TASK_MODEL_MAP = {
    # Computation / code tasks → Opus 4.8
    "paper_trading": MODEL_CODE,
    "allocator": MODEL_CODE,
    "analytics": MODEL_CODE,
    "reporting": MODEL_CODE,
    "stress_test": MODEL_CODE,
    "migration": MODEL_CODE,
    "telegram_bot": MODEL_CODE,
    # Architect / analysis tasks → Fable 5
    "architect": MODEL_ARCHITECT,
    "strategy_analysis": MODEL_ARCHITECT,
    "risk_assessment": MODEL_ARCHITECT,
    "governance": MODEL_ARCHITECT,
}

def get_model(task_type: str) -> str:
    """Return the appropriate Claude model ID for a given task type."""
    return TASK_MODEL_MAP.get(task_type, MODEL_DEFAULT)
