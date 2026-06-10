"""
spa_core.shadow — MP-106 shadow strategies S0–S5 on the real paper track.

Six shadow strategies run in parallel with the real paper-trading cycle.
They are STRICTLY ADVISORY: each keeps its own virtual portfolio in
``data/shadow_portfolio.json`` and NEVER influences the real allocation,
the RiskPolicy gate or any trade in ``data/trades.json``.

Stdlib only. No execution/, no feed_health/, no risk agents, no network.

Note: this package is distinct from the older Sprint-A advisory framework in
``spa_core/strategies/`` (baseline/concentration/momentum/…): MP-106 tracks a
fixed S0–S5 panel against the *live* daily cycle, not a backtest screening.
"""

from .shadow_registry import STRATEGIES
from .shadow_allocator import compute_shadow_allocation
from .shadow_tracker import run_shadow_cycle, SHADOW_FILENAME

__all__ = [
    "STRATEGIES",
    "compute_shadow_allocation",
    "run_shadow_cycle",
    "SHADOW_FILENAME",
]
