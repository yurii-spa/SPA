"""
SPA Strategies package.

Contains the strategy registry and all named strategies:
  - strategy_registry.py  : central registry for all strategy metadata
  - s1_conservative_lending.py : T1 lending only, ~4-6% APY
  - s2_lp_stable.py            : LP stablecoin pairs (Curve/Uniswap v3), ~8-12% APY
  - s3_yield_loop.py           : borrow-loop on Aave, ~15-25% APY (T3, high risk)

Sprint A / v3.90 — Multi-Strategy Shadow Framework (advisory-only):
  - base.py / vportfolio.py    : Strategy Protocol, risk guard, VirtualPortfolio
  - baseline / concentration / momentum / risk_parity / kelly / yield_spread
  - runner.py / comparator.py  : fan-out runner + Sortino leaderboard

  Shadow strategies are ADVISORY ONLY. None can become an active allocation
  without an explicit, separately-approved ADR (see docs/ADR-strategy-shadow.md).
  Nothing in this framework imports execution/, feed_health/ or the risk agents.
"""

from .base import (
    Strategy,
    apply_risk_policy,
    active_pools,
    tier_map,
    normalize,
    pool_apy_history,
    MAX_CONCENTRATION_T1,
    MAX_CONCENTRATION_T2,
)
from .vportfolio import VirtualPortfolio, EQUITY_CURVE_MAX
from .baseline import BaselineStrategy
from .concentration import ConcentrationStrategy
from .momentum import APYMomentumStrategy
from .risk_parity import RiskParityPlusStrategy
from .kelly import HalfKellyStrategy
from .yield_spread import YieldSpreadStrategy

#: Canonical registry of shadow strategies (S0..S5), in stable display order.
STRATEGY_REGISTRY = [
    BaselineStrategy(),
    ConcentrationStrategy(),
    APYMomentumStrategy(),
    RiskParityPlusStrategy(),
    HalfKellyStrategy(),
    YieldSpreadStrategy(),
]

__all__ = [
    "Strategy",
    "apply_risk_policy",
    "active_pools",
    "tier_map",
    "normalize",
    "pool_apy_history",
    "MAX_CONCENTRATION_T1",
    "MAX_CONCENTRATION_T2",
    "VirtualPortfolio",
    "EQUITY_CURVE_MAX",
    "BaselineStrategy",
    "ConcentrationStrategy",
    "APYMomentumStrategy",
    "RiskParityPlusStrategy",
    "HalfKellyStrategy",
    "YieldSpreadStrategy",
    "STRATEGY_REGISTRY",
]
