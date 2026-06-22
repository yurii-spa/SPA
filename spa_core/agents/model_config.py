"""
SPA Agent Model Configuration.

Centralises all LLM model assignments so they can be changed in one place
without touching individual agent files.

Design notes:
  - Architect agent uses Claude Fable 5 (best reasoning for design decisions).
  - CEO / Trader / Strategy / Data / Report agents use Opus 4.8.
  - Risk, Execution and Monitoring agents MUST be deterministic: LLM is
    forbidden for any decision that triggers a trade or a kill-switch, or
    that sits on the feed-health / monitoring path (project constitution,
    see spa_core/agent_runtime/mandate.py and spa_core/ci/llm_forbidden_lint.py).

Lookup convention:
    key = agent_name.lower().replace("agent", "").strip()
    e.g. "TraderAgent" → "trader", "DataAgent" → "data"
"""
from __future__ import annotations

# ─── Per-agent model assignments ─────────────────────────────────────────────

AGENT_MODELS: dict[str, str] = {
    # Architect — Fable 5 for senior design, ADRs, sprint planning
    "architect": "claude-fable-5",

    # General reasoning agents — Opus 4.8
    "ceo":        "claude-opus-4-8",
    "trader":     "claude-opus-4-8",
    "strategy":   "claude-opus-4-8",
    "data":       "claude-opus-4-8",
    "report":     "claude-opus-4-8",

    # Deterministic-only agents — models listed for audit completeness but
    # MUST NOT be used for actual decisions (see LLM_FORBIDDEN_AGENTS below).
    "risk":       "claude-opus-4-8",
    "monitoring": "claude-opus-4-8",
}

# Default model when an agent key is not found in AGENT_MODELS
DEFAULT_MODEL: str = "claude-opus-4-8"

# ─── Agents forbidden from LLM-based decisions ───────────────────────────────
# Risk, Execution and Monitoring agents are fully deterministic. Any code path
# that would call an LLM for a decision in these agents is a policy violation.
# This set is the project constitution — it MUST stay in sync with
# spa_core/agent_runtime/mandate.py and spa_core/ci/llm_forbidden_lint.py.

LLM_FORBIDDEN_AGENTS: set[str] = {"risk", "execution", "monitoring"}


# ─── Helper ──────────────────────────────────────────────────────────────────

def get_model_for_agent(agent_name: str) -> str:
    """
    Return the configured model string for a given agent name.

    Normalisation: strips "Agent" suffix and lowercases.
    Examples:
        "TraderAgent"  → AGENT_MODELS["trader"]
        "DataAgent"    → AGENT_MODELS["data"]
        "ceo"          → AGENT_MODELS["ceo"]
        "UnknownAgent" → DEFAULT_MODEL
    """
    key = agent_name.lower().replace("agent", "").strip()
    return AGENT_MODELS.get(key, DEFAULT_MODEL)


def is_llm_forbidden(agent_name: str) -> bool:
    """
    Return True if this agent must never use an LLM for decisions.
    """
    key = agent_name.lower().replace("agent", "").strip()
    return key in LLM_FORBIDDEN_AGENTS
