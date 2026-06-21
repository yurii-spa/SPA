"""
SPA Strategy Registry
=====================

Центральный реестр всех торговых стратегий с метаданными.

Каждая стратегия описывается через StrategyMeta:
  - id            : уникальный идентификатор (str)
  - name          : человекочитаемое название
  - type          : тип стратегии (lending / lp / yield_loop / wrapped)
  - risk_tier     : риск-уровень (T1 / T2 / T3)
  - target_apy_min: нижняя граница целевого APY (%)
  - target_apy_max: верхняя граница целевого APY (%)
  - max_drawdown_pct: максимально допустимый drawdown (%)
  - description   : краткое описание стратегии
  - module        : Python-модуль с реализацией
  - handler_class : имя класса стратегии в модуле

Методы реестра:
  register(meta)           — добавить стратегию
  get(strategy_id)         — получить по ID (или None)
  get_all()                — все стратегии (dict id → StrategyMeta)
  get_by_tier(tier)        — фильтр по риск-уровню
  get_by_type(stype)       — фильтр по типу
  as_list()                — все стратегии как список

Usage:
    from strategies.strategy_registry import REGISTRY

    all_strats = REGISTRY.get_all()
    t1_strats  = REGISTRY.get_by_tier("T1")
    lp_strats  = REGISTRY.get_by_type("lp")
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from spa_core.utils.errors import RegistryError


# ─── Strategy types ───────────────────────────────────────────────────────────

VALID_TYPES      = {"lending", "lp", "yield_loop", "wrapped"}
VALID_RISK_TIERS = {"T1", "T2", "T3"}


# ─── StrategyMeta dataclass ───────────────────────────────────────────────────

@dataclass
class StrategyMeta:
    """
    Metadata descriptor for a single trading strategy.

    Fields:
        id              : Unique strategy identifier, e.g. "s1_conservative_lending"
        name            : Human-readable name
        type            : One of: lending | lp | yield_loop | wrapped
        risk_tier       : Risk bucket: T1 (conservative), T2 (moderate), T3 (aggressive)
        target_apy_min  : Low end of expected APY range (%)
        target_apy_max  : High end of expected APY range (%)
        max_drawdown_pct: Acceptable max drawdown threshold (%) — strategy self-exits if breached
        description     : Short plain-English description
        module          : Python dotted path to the strategy implementation module
        handler_class   : Class name inside `module` that implements run()/backtest()
        tags            : Optional list of string tags for grouping
        enabled         : Whether the strategy is active (False = skip in backtests & agent)
    """
    id:               str
    name:             str
    type:             str
    risk_tier:        str
    target_apy_min:   float
    target_apy_max:   float
    max_drawdown_pct: float
    description:      str
    module:           str
    handler_class:    str
    tags:             list[str] = field(default_factory=list)
    enabled:          bool = True

    def __post_init__(self) -> None:
        if self.type not in VALID_TYPES:
            raise ValueError(f"Invalid strategy type '{self.type}'. Must be one of {VALID_TYPES}")
        if self.risk_tier not in VALID_RISK_TIERS:
            raise ValueError(f"Invalid risk tier '{self.risk_tier}'. Must be one of {VALID_RISK_TIERS}")
        if self.target_apy_min >= self.target_apy_max:
            raise ValueError("target_apy_min must be < target_apy_max")

    def to_dict(self) -> dict:
        """Serialize to plain dict (for JSON output)."""
        return asdict(self)

    @property
    def apy_midpoint(self) -> float:
        """Midpoint of the target APY range."""
        return (self.target_apy_min + self.target_apy_max) / 2.0


# ─── Registry ─────────────────────────────────────────────────────────────────

class StrategyRegistry:
    """
    Central registry for all SPA trading strategies.

    Thread-safety note: this is a simple in-process registry; no locking needed
    because all registrations happen at import time before any concurrent reads.
    """

    def __init__(self) -> None:
        self._store: dict[str, StrategyMeta] = {}

    # ── Mutation ──────────────────────────────────────────────────────────────

    def register(self, meta: StrategyMeta) -> None:
        """
        Register a strategy. Raises ValueError if the ID is already registered
        with different metadata (idempotent re-registration of the same object is OK).
        """
        if meta.id in self._store and self._store[meta.id] is not meta:
            existing = self._store[meta.id]
            if existing.to_dict() != meta.to_dict():
                raise RegistryError(
                    f"Strategy '{meta.id}' is already registered with different metadata. "
                    f"Use a unique ID or update the existing registration.",
                    code="STRATEGY_DUPLICATE_ID",
                )
        self._store[meta.id] = meta

    def unregister(self, strategy_id: str) -> None:
        """Remove a strategy from the registry (mainly for tests)."""
        self._store.pop(strategy_id, None)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get(self, strategy_id: str) -> Optional[StrategyMeta]:
        """Return strategy by ID, or None if not found."""
        return self._store.get(strategy_id)

    def get_all(self, enabled_only: bool = True) -> dict[str, StrategyMeta]:
        """
        Return all registered strategies.

        Args:
            enabled_only: If True (default), skip disabled strategies.
        """
        if enabled_only:
            return {k: v for k, v in self._store.items() if v.enabled}
        return dict(self._store)

    def as_list(self, enabled_only: bool = True) -> list[StrategyMeta]:
        """Return all strategies as a list, sorted by risk_tier then target_apy_min."""
        tier_order = {"T1": 0, "T2": 1, "T3": 2}
        strats = list(self.get_all(enabled_only=enabled_only).values())
        return sorted(strats, key=lambda s: (tier_order.get(s.risk_tier, 9), s.target_apy_min))

    def get_by_tier(self, tier: str, enabled_only: bool = True) -> list[StrategyMeta]:
        """
        Return all strategies in a given risk tier.

        Args:
            tier: "T1", "T2", or "T3"
            enabled_only: Skip disabled strategies if True.
        """
        return [
            s for s in self.as_list(enabled_only=enabled_only)
            if s.risk_tier == tier
        ]

    def get_by_type(self, stype: str, enabled_only: bool = True) -> list[StrategyMeta]:
        """
        Return all strategies of a given type.

        Args:
            stype: "lending", "lp", "yield_loop", or "wrapped"
            enabled_only: Skip disabled strategies if True.
        """
        return [
            s for s in self.as_list(enabled_only=enabled_only)
            if s.type == stype
        ]

    def summary(self) -> list[dict]:
        """Return a lightweight summary list suitable for JSON serialisation."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "risk_tier": s.risk_tier,
                "target_apy_range": f"{s.target_apy_min}–{s.target_apy_max}%",
                "max_drawdown_pct": s.max_drawdown_pct,
                "enabled": s.enabled,
                "tags": s.tags,
            }
            for s in self.as_list(enabled_only=False)
        ]

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"StrategyRegistry({len(self._store)} strategies)"


# ─── Global singleton ─────────────────────────────────────────────────────────
# All strategy modules import this and call REGISTRY.register(...)

REGISTRY = StrategyRegistry()


# ─── Built-in registrations (imported here to trigger side-effects) ───────────

def _load_builtin_strategies() -> None:
    """
    Import all built-in strategy modules so they self-register on first import.
    Errors in individual modules are caught so a broken strategy doesn't prevent
    others from loading.

    All paths use `spa_core.strategies.<module>` — correct package prefix.
    Modules that use legacy `strategies.*` paths are fixed to use spa_core prefix.
    """
    import importlib
    _modules = [
        # S1 variants
        "spa_core.strategies.s1_conservative_lending",   # S1 Conservative Lending (T1)
        "spa_core.strategies.s1_t1t2_balanced",          # S1 T1+T2 Balanced (MP-358)
        # S2 variants
        "spa_core.strategies.s2_lp_stable",              # S2 LP Stablecoin Pairs (T2)
        "spa_core.strategies.s2_pendle_morpho",          # S2 Pendle+Morpho (T2)
        # S3 variants
        "spa_core.strategies.s3_yield_loop",             # S3 Yield Loop (T3)
        "spa_core.strategies.s3_aave_arb_morpho",        # S3 Aave+Arb+Morpho (T1)
        # S4–S7
        "spa_core.strategies.s4_spark_fluid_conservative",  # S4 Spark+Fluid Conservative (T2)
        "spa_core.strategies.s5_pendle_enhanced",        # S5 Pendle Enhanced (T1)
        "spa_core.strategies.s6_max_diversified",        # S6 Max Diversified (T2)
        "spa_core.strategies.s7_pendle_yt_aggressive",   # S7 Pendle YT+PT Aggressive (MP-399)
        # S8–S10
        "spa_core.strategies.delta_neutral_susde",       # S8 Delta-Neutral sUSDe (T2)
        "spa_core.strategies.emode_looping",             # S9 Aave E-Mode USDC Looping (T3)
        "spa_core.strategies.pendle_yt",                 # S10 Pendle YT Speculation (T3)
        # S11–S21
        "spa_core.strategies.s11_hybrid_yield_max",      # S11 Hybrid Yield Max (T3)
        "spa_core.strategies.s12_base_layer_yield",      # S12 Base Layer Yield (T3)
        "spa_core.strategies.s13_multi_chain_arb",       # S13 Multi-Chain Yield Arb (T2)
        "spa_core.strategies.s14_arbitrum_radiant",      # S14 Arbitrum Radiant Max (T2)
        "spa_core.strategies.s15_multichain_l2",         # S15 MultiChain L2 Yield (T1)
        "spa_core.strategies.s16_stablecoin_ladder",     # S16 Stablecoin Ladder (T2)
        "spa_core.strategies.s17_polygon_yield",         # S17 Polygon Yield (T1)
        "spa_core.strategies.s18_high_yield_t2",         # S18 High Yield T2 (T2)
        "spa_core.strategies.s19_balanced_l2",           # S19 Balanced L2 (T1)
        "spa_core.strategies.s20_anticrisis_research",   # S20 Anti-Crisis Research (T3)
        "spa_core.strategies.s20_curve_convex",          # S20 Curve+Convex (T2/T3)
        "spa_core.strategies.s21_aave_loop",             # S21 Aave Loop (T2/T3)
        # S22–S25: high-APY expansion (2026-06-21)
        "spa_core.strategies.s22_ethena_yield_max",      # S22 Ethena Yield Maximizer (T3)
        "spa_core.strategies.s23_pendle_pt_fixed",       # S23 Pendle PT Fixed Rate (T2)
        "spa_core.strategies.s24_base_chain_max",        # S24 Base Chain Maximizer (T3)
        "spa_core.strategies.s25_yield_ladder",          # S25 Yield Ladder barbell (T2)
        # S26–S30: exotic / advanced strategies (2026-06-21)
        "spa_core.strategies.s26_volatility_harvester",  # S26 Volatility Harvester (T2)
        "spa_core.strategies.s27_stablecoin_carry",      # S27 Stablecoin Carry (T1)
        "spa_core.strategies.s28_momentum_yield",        # S28 Momentum Yield (T2)
        "spa_core.strategies.s29_barbell_plus",          # S29 Barbell Plus (T2)
        "spa_core.strategies.s30_all_weather",           # S30 All-Weather DeFi (T2)
        # S31–S32: regime-defensive expansion (2026-06-21)
        "spa_core.strategies.s31_bear_market_hedge",     # S31 Bear Market Hedge (T1, regime-aware)
        "spa_core.strategies.s32_market_neutral",        # S32 Market Neutral (T2, 50/45/5 weekly)
        # S34–S37: Arbitrum-focused expansion (2026-06-21)
        "spa_core.strategies.s34_arbitrum_yield",         # S34 Arbitrum Yield (T2, sequencer rotation)
        "spa_core.strategies.s35_gmx_carry",              # S35 GMX Stablecoin Carry (T2, GLP gate >8%)
        "spa_core.strategies.s36_cross_chain_optimizer",  # S36 Cross-Chain Optimizer (T2, weekly tilt)
        "spa_core.strategies.s37_radiant_concentrated",   # S37 Radiant Concentrated (T2, 50% Radiant)
        # S38–S39: Morpho max-allocation (MP-1247, 2026-06-21)
        "spa_core.strategies.s38_morpho_max",            # S38 Morpho Max (T2, policy-compliant, ~3.95%)
        "spa_core.strategies.s39_morpho_max_plus",       # S39 Morpho Max+ (T2, RESEARCH-only, cap-raise)
        # S41: Base+Op AMM stable-LP yield (MP v12.51, 2026-06-21)
        "spa_core.strategies.s41_amm_stable_yield",      # S41 Base+Op AMM Stable Yield (T2, AMM LP)
        # S45: Mean-Reversion Yield (MP v12.62, 2026-06-21)
        "spa_core.strategies.s45_mean_reversion",        # S45 Mean-Reversion Yield (T2, contrarian deviation tilt)
        # S46–S50: income-generation batch (2026-06-21)
        "spa_core.strategies.s46_safe_harbor",           # S46 Stable-Only Safe Harbor (T1, 100% T1, lowest risk)
        "spa_core.strategies.s47_monthly_income",        # S47 Monthly Income Optimizer (T1, predictability-weighted)
        "spa_core.strategies.s48_utilization_aware",     # S48 Utilization-Aware (T2, Aave-APY regime proxy)
        "spa_core.strategies.s49_diversified_max",       # S49 Diversified Maximum (T2, 7 venues, no single >20%)
        "spa_core.strategies.s50_tournament_champion",   # S50 Tournament Champion (T2, meta — copies leader weights)
        # S44: Yield Spike Harvester (MP v12.61, 2026-06-21)
        "spa_core.strategies.s44_spike_harvester",       # S44 Yield Spike Harvester (T3, transient APY-spike concentration)
        # S51–S55: advanced edge-case strategies (v1.267, 2026-06-21)
        "spa_core.strategies.s51_protocol_lifecycle",      # S51 Protocol Lifecycle Manager (T1, age-discount + young-cap)
        "spa_core.strategies.s52_tvl_momentum",            # S52 TVL Momentum (T2, ±5% tilt vs 6m avg TVL)
        "spa_core.strategies.s53_correlated_risk_reducer", # S53 Correlated Risk Reducer (T2, collapse |corr|>0.9 pairs)
        "spa_core.strategies.s54_daily_yield_maximizer",   # S54 Daily Yield Maximizer (T2, 80/20 chase of yesterday top-3)
        "spa_core.strategies.s55_max_sharpe_portfolio",    # S55 Maximum Sharpe Portfolio (T1, optimizer fixed weights, sky-gated)
        # s21_cashflow_research is RESEARCH_ONLY (risk_tier="RESEARCH" not valid) — skipped
    ]
    for module_path in _modules:
        try:
            importlib.import_module(module_path)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not auto-load strategy module '%s': %s", module_path, exc
            )


_load_builtin_strategies()
