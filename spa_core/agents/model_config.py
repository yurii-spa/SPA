"""
SPA Agent Model Configuration.

Centralises all LLM model assignments so they can be changed in one place
without touching individual agent files.

Design notes:
  - CEO / Trader / Strategy agents use Claude Sonnet 4.6 (best reasoning).
  - Data / Monitoring / Report agents use Claude Haiku (fast + cheap).
  - Risk and Execution agents MUST be deterministic: LLM is forbidden for
    any decision that triggers a trade or a kill-switch.
  - When Gemini Flash / Flash-Lite become available via the Anthropic SDK or
    a compatible wrapper, swap the "data" and "strategy" values here — no
    other code changes required.

Lookup convention:
    key = agent_name.lower().replace("agent", "").strip()
    e.g. "TraderAgent" → "trader", "DataAgent" → "data"
"""
from __future__ import annotations

# ─── Per-agent model assignments ─────────────────────────────────────────────

AGENT_MODELS: dict[str, str] = {
    # High-reasoning agents — use Sonnet for quality
    "ceo":      "claude-sonnet-4-6",
    "trader":   "claude-sonnet-4-6",
    "strategy": "claude-sonnet-4-6",

    # Data / monitoring / reporting — Haiku is fast enough and cheaper
    # TODO: swap to "gemini-flash-lite" / "gemini-flash" when available
    "data":       "claude-haiku-4-5-20251001",
    "monitoring": "claude-haiku-4-5-20251001",
    "report":     "claude-haiku-4-5-20251001",

    # Risk — deterministic only; model listed for audit completeness but
    # MUST NOT be used for actual risk decisions (see LLM_FORBIDDEN_AGENTS)
    "risk": "claude-haiku-4-5-20251001",
}

# Default model when an agent key is not found in AGENT_MODELS
DEFAULT_MODEL: str = "claude-haiku-4-5-20251001"

# ─── Agents forbidden from LLM-based decisions ───────────────────────────────
# Risk and Execution agents are fully deterministic. Any code path that would
# call an LLM for a decision in these agents is a policy violation.

LLM_FORBIDDEN_AGENTS: set[str] = {"risk", "execution"}


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
