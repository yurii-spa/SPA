"""
spa_core/safety/

Central enforcement of the LIVE TRADING IS FORBIDDEN constraint.

Modules:
    live_trading_gate  — gate state machine (LOCKED by default)
    safeguard          — decorators for guarding trading functions

LLM_FORBIDDEN: this package is part of the safety domain.
"""

from spa_core.safety.live_trading_gate import LiveTradingGate, require_live_gate
from spa_core.safety.safeguard import (
    live_trading_forbidden,
    require_gate,
    research_only,
    is_research_only,
)

__all__ = [
    "LiveTradingGate",
    "require_live_gate",
    "live_trading_forbidden",
    "require_gate",
    "research_only",
    "is_research_only",
]
