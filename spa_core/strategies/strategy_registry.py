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
    """
    import importlib
    _modules = [
        "strategies.s1_conservative_lending",
        "strategies.s2_lp_stable",
        "strategies.s3_yield_loop",
        "strategies.emode_looping",          # S9 — Aave E-Mode USDC Looping
        "spa_core.strategies.s1_t1t2_balanced",  # MP-358 — S1 T1+T2 Balanced (6-8% APY)
        "spa_core.strategies.s7_pendle_yt_aggressive",  # MP-399 — S7 Pendle YT+PT Aggressive (10.115% APY)
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
