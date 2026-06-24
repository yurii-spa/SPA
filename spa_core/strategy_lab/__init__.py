"""
spa_core/strategy_lab — Strategy Lab: pluggable yield strategies run through ONE shared
backtest harness and ONE live paper-trading service, for honest risk-adjusted comparison.

PARALLEL MODEL: does not disturb the existing engines/strategies. Baselines (Engine A/B/C,
RWA floor) are WRAPPED in the same `Strategy` interface so they are part of the comparison,
not a separate world.

Design rules (inherited from the repo):
  - stdlib-only runtime, deterministic, atomic writes.
  - LLM FORBIDDEN in risk/kill logic.
  - Risk limits are NOT duplicated here — they come from spa_core.risk.policy (single source
    of truth). Strategy-specific thresholds (X/Y/Z/N) live in config.py + the JSON SSOT.
  - Data layer fail-CLOSED: bad/empty API schema -> raise + mark datapoint invalid, never a
    silent default. forward-fill only with an explicit limit, else a gap flag.

Keystone contract lives in base.py (Strategy ABC + dataclasses). Everything imports from there.
"""
# LLM_FORBIDDEN
from spa_core.strategy_lab.base import (  # noqa: F401
    Strategy,
    Position,
    MarketSnapshot,
    StrategyMetrics,
    KillResult,
    InvalidDataError,
)

__all__ = [
    "Strategy",
    "Position",
    "MarketSnapshot",
    "StrategyMetrics",
    "KillResult",
    "InvalidDataError",
]
