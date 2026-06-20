"""
spa_core/paper_trading/strategy_registry.py — SPA Multi-Strategy Tournament Registry

StrategyConfig dataclass + STRATEGY_REGISTRY с 10 предопределёнными стратегиями S0-S9
для параллельного paper-trading турнира.

Протоколы (из ADAPTER_REGISTRY):
  T1: aave_v3, compound_v3
  T2: morpho_blue, yearn_v3, euler_v2, maple
  watch: sky_susds (0% до подтверждённого GSM Pause Delay ≥ 48h)
  external: pendle_pt (не в registry, placeholder — 0 при отсутствии)

Правила:
  - Per-protocol T1 cap 40%, T2 cap 20%
  - T2 total cap 35%
  - Cash buffer ≥ 5%
  - Все стратегии соблюдают RiskPolicy v1.0 при прогоне через cycle
  - sky_susds / pendle_pt могут быть недоступны — в simulate_day игнорируются
    если нет в apy_data; аллокация перераспределяется пропорционально.

Статусы:
  "active"   — участвует в турнире
  "paused"   — временно приостановлена
  "killed"   — убита TournamentEvaluator (drawdown / Sharpe < threshold)
  "promoted" — лучшая стратегия, выбранная для shadow live
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

# ─── StrategyConfig ────────────────────────────────────────────────────────────

@dataclass
class StrategyConfig:
    """Конфигурация одной торговой стратегии в турнире.

    Attributes:
        id: уникальный строковый идентификатор (e.g. "S0", "S1", …)
        name: человекочитаемое имя
        description: краткое описание логики и цели
        allocations: целевые веса по протоколам; сумма ≤ 1.0
                     (остаток → cash).  Ключи — protocol_key из ADAPTER_REGISTRY
                     или watchlist-протоколы ("sky_susds", "pendle_pt").
        tier: основная тир-характеристика стратегии ("T1", "T1+T2", "T2")
        target_apy_min: минимальная ожидаемая годовая доходность (%)
        target_apy_max: максимальная ожидаемая годовая доходность (%)
        kill_drawdown_pct: порог просадки для kill-решения (0..1).
                           None → использовать глобальный дефолт (0.05).
        status: "active" | "paused" | "killed" | "promoted"
    """
    id: str
    name: str
    description: str
    allocations: Dict[str, float]  # protocol_key -> fraction [0, 1]
    tier: str
    target_apy_min: float
    target_apy_max: float
    kill_drawdown_pct: Optional[float] = None   # None → дефолт 5%
    status: str = "active"
    # S8+ расширение: gate condition и класс стратегии
    gate_condition: Optional[Callable[[Dict[str, float]], bool]] = field(
        default=None, repr=False, compare=False
    )
    """callable(apy_map) -> bool — проверяет, должна ли стратегия быть активна.
    apy_map: {protocol_key: apy_decimal}. None → всегда активна."""
    strategy_class: Optional[str] = None
    """Строковое имя implementing класса (e.g. 'DeltaNeutralSUSDeStrategy')."""

    def __post_init__(self) -> None:
        alloc_sum = sum(self.allocations.values())
        if alloc_sum < 0:
            raise ValueError(f"Strategy {self.id}: allocations sum is negative")
        if alloc_sum > 1.0 + 1e-9:
            raise ValueError(
                f"Strategy {self.id}: allocations sum {alloc_sum:.4f} > 1.0"
            )
        if self.status not in {"active", "paused", "killed", "promoted"}:
            raise ValueError(
                f"Strategy {self.id}: invalid status '{self.status}'"
            )

    @property
    def cash_pct(self) -> float:
        """Процент кэша (остаток после всех аллокаций)."""
        return max(0.0, 1.0 - sum(self.allocations.values()))

    def effective_allocations(
        self, available_protocols: set
    ) -> Dict[str, float]:
        """Нормализованные аллокации только по доступным протоколам.

        Протоколы из self.allocations, отсутствующие в available_protocols,
        исключаются, и их веса пропорционально перераспределяются между
        доступными. Если ни одного доступного протокола нет — возвращает {}.

        Args:
            available_protocols: множество protocol_key с живыми данными.
        """
        active = {
            k: v for k, v in self.allocations.items()
            if k in available_protocols and v > 0
        }
        if not active:
            return {}
        total = sum(active.values())
        if total <= 0:
            return {}
        # scale так, чтобы сумма не превышала исходную сумму аллокаций
        orig_sum = sum(self.allocations.values())
        factor = orig_sum / total if total > 0 else 1.0
        return {k: v * factor for k, v in active.items()}


# ─── Предопределённые стратегии ────────────────────────────────────────────────

# S0 — Conservative T1
# Baseline: только T1-протоколы, стабильность > доходность.
# Target APY: ~3.2% (Aave + Compound/Morpho, минимальный риск).
# Sky/sUSDS пока 0% по FORBIDDEN-правилу (GSM Pause Delay < 48h не подтверждён).
S0_CONSERVATIVE_T1 = StrategyConfig(
    id="S0",
    name="Conservative T1",
    description=(
        "T1-only: Aave V3 50%, Morpho Blue 30%, Cash 20%. "
        "Baseline stability, minimal T2 exposure. "
        "Target ~3.2% APY. Sky/sUSDS placeholder 0%."
    ),
    allocations={
        "aave_v3":    0.50,
        "morpho_blue": 0.30,
        # sky_susds: 0% до подтверждения (FORBIDDEN по текущему правилу)
    },
    tier="T1",
    target_apy_min=2.0,
    target_apy_max=4.5,
    kill_drawdown_pct=0.05,
)

# S1 — Balanced T1+T2
# Диверсификация между T1 и T2, умеренная доходность.
S1_BALANCED = StrategyConfig(
    id="S1",
    name="Balanced T1+T2",
    description=(
        "Balanced: Aave 30%, Morpho 20%, YearnV3 25%, EulerV2 20%, Cash 5%. "
        "Mix of T1 safety and T2 yield. Target ~6-7% APY."
    ),
    allocations={
        "aave_v3":    0.30,
        "morpho_blue": 0.20,
        "yearn_v3":   0.25,
        "euler_v2":   0.20,
    },
    tier="T1+T2",
    target_apy_min=5.0,
    target_apy_max=8.0,
    kill_drawdown_pct=0.05,
)

# S2 — Morpho-Heavy (Steakhouse focus)
# Концентрация в Morpho Blue + якорный Aave
S2_MORPHO_HEAVY = StrategyConfig(
    id="S2",
    name="Morpho-Heavy",
    description=(
        "Morpho Blue 60%, Aave V3 20%, Cash 20%. "
        "Concentration on Morpho Steakhouse vaults. Target ~6.5% APY."
    ),
    allocations={
        "morpho_blue": 0.60,
        "aave_v3":    0.20,
    },
    tier="T1+T2",
    target_apy_min=5.0,
    target_apy_max=8.0,
    kill_drawdown_pct=0.05,
)

# S3 — Pendle Rotation (PT-sUSDe placeholder)
# Pendle PT недоступен напрямую в ADAPTER_REGISTRY; при simulate_day
# его аллокация перераспределяется на Morpho+Aave.
S3_PENDLE_ROTATION = StrategyConfig(
    id="S3",
    name="Pendle Rotation",
    description=(
        "PT-sUSDe 40% (placeholder→fallback cash), Morpho 30%, Aave 30%. "
        "Targets high fixed-yield Pendle PTs; fallback to Morpho/Aave. "
        "Target ~8-12% APY when Pendle live."
    ),
    allocations={
        "pendle_pt":   0.40,   # external; fallback → cash
        "morpho_blue": 0.30,
        "aave_v3":    0.25,
    },
    tier="T2",
    target_apy_min=5.0,
    target_apy_max=12.0,
    kill_drawdown_pct=0.07,
)

# S4 — T2-Max
# Максимизация T2 доходности с диверсификацией
S4_T2_MAX = StrategyConfig(
    id="S4",
    name="T2-Max",
    description=(
        "YearnV3 35%, EulerV2 35%, Morpho 25%, Cash 5%. "
        "Max T2 yield with diversification. Target ~7-9% APY."
    ),
    allocations={
        "yearn_v3":    0.35,
        "euler_v2":    0.35,
        "morpho_blue": 0.25,
    },
    tier="T2",
    target_apy_min=6.0,
    target_apy_max=10.0,
    kill_drawdown_pct=0.06,
)

# S5 — RWA Focus (Sky/sUSDS placeholder)
# Sky/sUSDS — watchlist, 0% до подтверждения; используется Maple как RWA-proxy
S5_RWA_FOCUS = StrategyConfig(
    id="S5",
    name="RWA Focus",
    description=(
        "Sky/sUSDS 50% (placeholder→fallback cash), Morpho 30%, Aave 20%. "
        "RWA-backed yield focus. Sky at 0% until GSM Pause Delay ≥ 48h confirmed. "
        "Target ~5-7% APY."
    ),
    allocations={
        "sky_susds":   0.50,   # watchlist; fallback → cash
        "morpho_blue": 0.30,
        "aave_v3":    0.15,
    },
    tier="T1+T2",
    target_apy_min=3.0,
    target_apy_max=8.0,
    kill_drawdown_pct=0.05,
)

# S6 — Aggressive T2
# Высокодоходная T2 стратегия, максимальный риск
S6_AGGRESSIVE_T2 = StrategyConfig(
    id="S6",
    name="Aggressive T2",
    description=(
        "YearnV3 40%, EulerV2 30%, Morpho 25%, Cash 5%. "
        "High T2 concentration, maximum yield chase. Target ~9-11% APY."
    ),
    allocations={
        "yearn_v3":    0.40,
        "euler_v2":    0.30,
        "morpho_blue": 0.25,
    },
    tier="T2",
    target_apy_min=7.0,
    target_apy_max=12.0,
    kill_drawdown_pct=0.08,
)

# S7 — Diversified Max (equal weight)
# Равновесная диверсификация по всем 6 адаптерам
S7_DIVERSIFIED_MAX = StrategyConfig(
    id="S7",
    name="Diversified Max",
    description=(
        "Equal weight: Aave 16.7%, Compound 16.7%, Morpho 16.7%, "
        "Yearn 16.7%, Euler 16.7%, Maple 11.7%, Cash 5%. "
        "Maximum diversification across all adapters. Target ~6-8% APY."
    ),
    allocations={
        "aave_v3":     0.167,
        "compound_v3": 0.167,
        "morpho_blue": 0.167,
        "yearn_v3":    0.167,
        "euler_v2":    0.167,
        "maple":       0.117,
    },
    tier="T1+T2",
    target_apy_min=5.0,
    target_apy_max=9.0,
    kill_drawdown_pct=0.05,
)

# S8 — Delta-Neutral sUSDe Funding Harvest (MP-157)
# Механика: long sUSDe (staking yield) + short ETH perp (funding rate) = delta-neutral.
# Gate: sUSDe APY >= 12% AND funding >= 0% AND market_regime == "bull".
# Bear/neutral → inactive → 0% loss. Max 20% portfolio.
# Аллокации внутри S8: 50% susde_spot + 50% perp_short_hedge (notional).
S8_DELTA_NEUTRAL_SUSDE = StrategyConfig(
    id="S8",
    name="Delta-Neutral sUSDe Funding Harvest",
    description=(
        "S8: Delta-neutral sUSDe funding harvest. "
        "Long sUSDe (staking yield 12-22%) + Short ETH perp (funding rate 0-12%). "
        "Active only in bull market: sUSDe APY >= 12% AND funding >= 0%. "
        "Bear/neutral: strategy inactive → 0% loss, capital → T1 safe harbor. "
        "Target APY: 13-24% bull market. Max 20% portfolio cap. "
        "PAPER SIMULATION ONLY via DeltaNeutralSUSDeStrategy."
    ),
    allocations={
        "susde_spot":       0.50,   # long sUSDe position (ERC-4626)
        "perp_short_hedge": 0.50,   # short ETH perp notional hedge
    },
    tier="T2",
    target_apy_min=0.0,   # 0% in bear (strategy inactive)
    target_apy_max=24.0,  # 24% in bull
    kill_drawdown_pct=0.05,
    status="active",
    gate_condition=lambda apy_map: apy_map.get("susde", 0.0) >= 0.12,
    strategy_class="DeltaNeutralSUSDeStrategy",
)

# S9 — E-Mode Looping (Aave E-Mode USDC → borrow USDE/DAI → reinvest Pendle/Morpho)
# Leverage ~2x. Net APY = supply_apy + ltv*(reinvest_apy - borrow_apy) ≈ 6.8-9%.
# aave_emode: collateral 50%, morpho_blue: reinvest 30%, pendle_pt: reinvest 20%.
# HF monitoring: warn<1.5, emergency<1.2 → auto-deleverage to 60% LTV.
# pendle_pt может быть недоступен → effective_allocations перераспределит на morpho.
# Sky/sUSDS 0% по FORBIDDEN-правилу (GSM Pause Delay < 48h не подтверждён).
S9_EMODE_LOOPING = StrategyConfig(
    id="S9",
    name="E-Mode Looping",
    description=(
        "Aave E-Mode USDC looping (2x leverage): deposit USDC → "
        "borrow USDE/DAI at 82% LTV → reinvest in Pendle/Morpho. "
        "Net APY = supply_apy + 0.82*(reinvest - borrow) ≈ 6.8-9%. "
        "HF monitoring: warn<1.5, emergency<1.2 → auto-deleverage. "
        "Allocations: aave_v3 50% (collateral), morpho_blue 30%, pendle_pt 20%. "
        "PAPER TRADING ONLY until ADR + Owner approval."
    ),
    allocations={
        "aave_v3":     0.50,   # supply-side collateral
        "morpho_blue": 0.30,   # reinvest destination
        "pendle_pt":   0.20,   # reinvest destination (may be unavailable)
    },
    tier="T3",
    target_apy_min=6.0,
    target_apy_max=9.0,
    kill_drawdown_pct=0.05,
    status="active",
)


# S10 — Pendle YT Speculation (leveraged yield upside via YT tokens)
# YT (Yield Token) captures leveraged APY upside vs implied yield embedded in PT.
# Entry gate: current_apy > implied_yield_annual × 1.25 (25% cushion).
# Max allocation: 30% of capital (T3 high-risk, paper trading only).
# Exit: at 60% of maturity OR if apy drops below implied_yield.
# Bull (apy=20%): gross 50%, net 42%; Base (apy=12%): gross 22%, net 14%.
# Bear (apy=6%): YT → 0, max loss = -yt_price_pct × capital_deployed = -7.5% portfolio.
# Full strategy logic: spa_core/strategies/pendle_yt.py (PendleYTStrategy).
S10_PENDLE_YT = StrategyConfig(
    id="S10",
    name="Pendle YT Speculation",
    description=(
        "Leveraged yield speculation via Pendle YT tokens (T3, high-risk). "
        "Entry: current_apy > implied_yield × 1.25 (default threshold 10%). "
        "Max allocation 30% of capital; YT leverage ≈ 3.5×. "
        "Exit at 60% maturity (day 109) or apy < implied_yield (8%). "
        "Bull (20% APY): gross 50%, net 42%. Base (12%): gross 22%, net 14%. "
        "Bear (6%): YT → 0, max loss = -7.5% of portfolio. "
        "PAPER TRADING ONLY until ADR + Owner approval."
    ),
    allocations={
        "pendle_yt": 0.30,   # YT position, max 30% capital (T3 high-risk)
    },
    tier="T3",
    target_apy_min=14.0,     # base scenario net APY %
    target_apy_max=42.0,     # bull scenario net APY %
    kill_drawdown_pct=0.30,  # 30% drawdown = full YT premium loss (bear case)
    status="active",
    strategy_class="PendleYTStrategy",
)


# S22 — Ethena Yield Maximizer (high-APY synthetic dollar; MP high-yield expansion)
# 40% sUSDe (T3) + 30% Sky sUSDS (spark_susds T1) + 30% Aave V3 (T1).
# Kill switch: ethena_depeg → T1 safe harbor (see strategies/s22_ethena_yield_max.py).
# sUSDe target 40% exceeds RiskPolicy T3_CAP 10% — gate clips; paper/advisory only.
S22_ETHENA_YIELD_MAX = StrategyConfig(
    id="S22",
    name="Ethena Yield Maximizer",
    description=(
        "sUSDe 40% (T3, ~12% APY) + Sky sUSDS 30% (T1) + Aave V3 30% (T1). "
        "Target 8-12% APY. Kill switch: ethena_depeg → T1 safe harbor. "
        "T3 40% > T3_CAP 10% — gate clips; paper only. "
        "Logic: EthenaYieldMaxStrategy."
    ),
    allocations={
        "susde":       0.40,   # Ethena sUSDe (T3)
        "spark_susds": 0.30,   # Sky/Spark sUSDS (T1)
        "aave_v3":     0.30,   # Aave V3 (T1)
    },
    tier="T3",
    target_apy_min=6.0,
    target_apy_max=14.0,
    kill_drawdown_pct=0.05,
    status="active",
    strategy_class="EthenaYieldMaxStrategy",
)

# S23 — Pendle PT Fixed Rate (fixed YTM via principal tokens; lower variance)
# 50% Pendle PT (T2, fixed ~7%) + 30% Sky sUSDS (T1) + 20% Aave V3 (T1).
# pendle_pt may be unavailable → effective_allocations redistributes to T1;
# the strategy class itself uses a 7% mock rate for paper simulation.
S23_PENDLE_PT_FIXED = StrategyConfig(
    id="S23",
    name="Pendle PT Fixed Rate",
    description=(
        "Pendle PT 50% (T2, fixed YTM ~7%) + Sky sUSDS 30% (T1) + Aave 20% (T1). "
        "Target 6-9% locked, lower variance. Mock 7% PT when live data absent. "
        "Logic: PendlePTFixedStrategy."
    ),
    allocations={
        "pendle_pt":   0.50,   # Pendle PT (external; fallback → cash/T1)
        "spark_susds": 0.30,   # Sky/Spark sUSDS (T1)
        "aave_v3":     0.20,   # Aave V3 (T1)
    },
    tier="T2",
    target_apy_min=5.0,
    target_apy_max=9.0,
    kill_drawdown_pct=0.05,
    status="active",
    strategy_class="PendlePTFixedStrategy",
)

# S24 — Base Chain Maximizer (Coinbase Base L2, read-only cross-chain)
# 40% Morpho Blue Base + 30% Aave V3 Base + 30% Moonwell Base (all T2).
# ADR-025 Phase 2 gated (Base capital ~2026-08-01); APY feeds always read-only.
S24_BASE_CHAIN_MAX = StrategyConfig(
    id="S24",
    name="Base Chain Maximizer",
    description=(
        "Morpho Blue Base 40% + Aave V3 Base 30% + Moonwell Base 30% (all T2). "
        "Target 4-9% APY, Coinbase Base L2, read-only. ADR-025 Phase 2 gated. "
        "Logic: BaseChainMaxStrategy."
    ),
    allocations={
        "morpho_blue_base": 0.40,   # Base T2 primary
        "aave_v3_base":     0.30,   # Base T2 anchor
        "moonwell_base":    0.30,   # Base T2 third leg (Aerodrome substitute)
    },
    tier="T2",
    target_apy_min=4.0,
    target_apy_max=9.0,
    kill_drawdown_pct=0.05,
    status="active",
    strategy_class="BaseChainMaxStrategy",
)

# S25 — Yield Ladder (barbell: 60% ultra-safe T1 + 40% dynamic best T2)
# Fixed: Sky sUSDS 30% + Aave 30%. Dynamic 40% → highest-APY of
# {susde, yearn_v3, euler_v2, maple} re-selected each cycle. Allocation here
# lists the default sleeve winner (susde); the strategy class rotates live.
S25_YIELD_LADDER = StrategyConfig(
    id="S25",
    name="Yield Ladder",
    description=(
        "Barbell: Sky sUSDS 30% + Aave 30% (T1 base) + 40% dynamic best T2 "
        "from {Ethena, Yearn, Euler, Maple}, rotated each cycle. Target 5-12%. "
        "Logic: YieldLadderStrategy (select_best_t2)."
    ),
    allocations={
        "spark_susds": 0.30,   # T1 ultra-safe base
        "aave_v3":     0.30,   # T1 ultra-safe base
        "susde":       0.40,   # dynamic T2/T3 sleeve (default winner; rotates live)
    },
    tier="T2",
    target_apy_min=5.0,
    target_apy_max=12.0,
    kill_drawdown_pct=0.05,
    status="active",
    strategy_class="YieldLadderStrategy",
)


# ─── Реестр стратегий ──────────────────────────────────────────────────────────

STRATEGY_REGISTRY: Dict[str, StrategyConfig] = {
    s.id: s for s in [
        S0_CONSERVATIVE_T1,
        S1_BALANCED,
        S2_MORPHO_HEAVY,
        S3_PENDLE_ROTATION,
        S4_T2_MAX,
        S5_RWA_FOCUS,
        S6_AGGRESSIVE_T2,
        S7_DIVERSIFIED_MAX,
        S8_DELTA_NEUTRAL_SUSDE,  # S8 — Delta-Neutral sUSDe Funding Harvest (MP-157)
        S9_EMODE_LOOPING,        # S9 — Aave E-Mode USDC Looping (MP-155)
        S10_PENDLE_YT,           # S10 — Pendle YT Speculation (MP-160)
        S22_ETHENA_YIELD_MAX,    # S22 — Ethena Yield Maximizer (high-APY expansion)
        S23_PENDLE_PT_FIXED,     # S23 — Pendle PT Fixed Rate
        S24_BASE_CHAIN_MAX,      # S24 — Base Chain Maximizer
        S25_YIELD_LADDER,        # S25 — Yield Ladder barbell
    ]
}

# Упорядоченный список id для стабильного обхода
STRATEGY_IDS: list = list(STRATEGY_REGISTRY.keys())


def get_strategy(strategy_id: str) -> StrategyConfig:
    """Получить стратегию по id. KeyError если не найдена."""
    return STRATEGY_REGISTRY[strategy_id]


def active_strategies() -> list:
    """Список StrategyConfig со статусом 'active' или 'promoted'."""
    return [
        s for s in STRATEGY_REGISTRY.values()
        if s.status in {"active", "promoted"}
    ]


def set_strategy_status(strategy_id: str, status: str) -> None:
    """Обновить статус стратегии в реестре (in-memory).

    Изменение in-memory; не персистентно — реестр перезагружается при
    следующем импорте. Персистентность — через VPortfolioManager.save().
    """
    valid = {"active", "paused", "killed", "promoted"}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid}")
    if strategy_id not in STRATEGY_REGISTRY:
        raise KeyError(f"Strategy '{strategy_id}' not in STRATEGY_REGISTRY")
    STRATEGY_REGISTRY[strategy_id].status = status
