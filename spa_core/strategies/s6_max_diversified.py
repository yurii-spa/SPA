"""
spa_core/strategies/s6_max_diversified.py — MP-397 S6 Max Diversified

Стратегия максимальной диверсификации по всем T1/T2 адаптерам с высоким APY.
Аллокация по 5 протоколам:

  pendle_pt          40%  — primary yield (~10.0% APY)
  morpho_steakhouse  30%  — T1 backstop (~6.5% APY)
  fluid_fusdc        15%  — T2 yield boost (~6.5% APY)
  compound_v3        10%  — liquidity buffer (~4.8% APY)
  aave_arbitrum       5%  — cross-chain diversification (~4.6% APY)

Weighted APY (дефолт):
  0.40×10.0 + 0.30×6.5 + 0.15×6.5 + 0.10×4.8 + 0.05×4.6
  = 4.0 + 1.95 + 0.975 + 0.48 + 0.23 = 7.635%

Diversity Score:
  1 - max(ALLOCATION.values()) = 1 - 0.40 = 0.60

T2 Exposure:
  fluid_fusdc = 15% ≤ MAX_T2_ALLOCATION (20%) — compliant (ADR-019)

Ключевые особенности:
  - 5 протоколов из разных категорий (T1/T2, cross-chain)
  - При отсутствии протокола в apy_map вес перераспределяется на morpho_steakhouse
  - Diversity score 0.60 (выше S2 с 50% pendle = менее диверсифицирован)
  - Risk score 0.35 — ниже S5 благодаря диверсификации

Совместимость:
  - compute_weighted_apy(apy_map)  → взвешенный APY
  - simulate_day(apy_map, capital) → ежедневный P&L snapshot
  - check_concentration(allocation) → проверка концентрации и T2-лимита
  - get_diversity_score()           → обратная концентрация
  - vs_baseline_improvement(...)   → сравнение с baseline
  - to_vportfolio_format()         → совместимый с VPortfolio dict
  - get_t2_exposure()              → суммарная доля T2 протоколов

Правила:
  - stdlib only, никаких внешних зависимостей
  - Read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - Атомарные записи при необходимости (tmp + os.replace)
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S6"
STRATEGY_NAME = "Max Diversified"
TIER          = "T1+T2"
DESCRIPTION   = (
    "Max Diversification strategy: Pendle PT 40% (T1, ~10.0% APY), "
    "Morpho Steakhouse 30% (T1, ~6.5% APY), "
    "Fluid fUSDC 15% (T2, ~6.5% APY), "
    "Compound V3 10% (T1, ~4.8% APY), "
    "Aave Arbitrum 5% (T1, ~4.6% APY). "
    "Weighted APY ≈ 7.635%, Diversity Score = 0.60."
)

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "pendle_pt":         0.40,  # T1, primary yield ~10.0% APY
    "morpho_steakhouse": 0.30,  # T1, backstop ~6.5% APY
    "fluid_fusdc":       0.15,  # T2, yield boost ~6.5% APY
    "compound_v3":       0.10,  # T1, liquidity buffer ~4.8% APY
    "aave_arbitrum":     0.05,  # T1, cross-chain diversification ~4.6% APY
}

# Число протоколов
PROTOCOL_COUNT: int = len(ALLOCATION)  # 5

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "pendle_pt":         10.0,  # Pendle PT ~10.0% APY
    "morpho_steakhouse":  6.5,  # Morpho Steakhouse ~6.5% APY
    "fluid_fusdc":        6.5,  # Fluid fUSDC ~6.5% APY
    "compound_v3":        4.8,  # Compound V3 ~4.8% APY
    "aave_arbitrum":      4.6,  # Aave Arbitrum ~4.6% APY
}

# APY target (консервативный, фактический weighted ≈ 7.635%)
APY_TARGET_PCT: float = 7.5

# Число протоколов (явная константа для совместимости)
# PROTOCOL_COUNT уже определён выше через len(ALLOCATION)

# Максимум на один протокол (для check_concentration)
MAX_SINGLE_PROTOCOL_PCT: float = 0.40  # 40%

# Risk score (ниже S5 благодаря диверсификации)
RISK_SCORE: float = 0.35

# T2-протоколы (ADR-019)
T2_PROTOCOLS: List[str] = ["fluid_fusdc"]

# Максимальная суммарная доля T2 (ADR-019)
MAX_T2_ALLOCATION: float = 0.20  # 20%

# Диапазон целевого APY
TARGET_APY_MIN: float = 6.5
TARGET_APY_MAX: float = 9.0

# Ожидаемый weighted APY при дефолтных значениях:
# 0.40*10.0 + 0.30*6.5 + 0.15*6.5 + 0.10*4.8 + 0.05*4.6
# = 4.0 + 1.95 + 0.975 + 0.48 + 0.23 = 7.635%
WEIGHTED_APY_EXPECTED: float = 7.635


# ─── Публичные функции ────────────────────────────────────────────────────────

def compute_weighted_apy(apy_map: dict) -> float:
    """Взвешенный годовой APY стратегии S6 (% годовых).

    Формула: sum(weight * apy for protocol, weight in ALLOCATION)

    Если протокол отсутствует в apy_map, его вес перераспределяется
    на morpho_steakhouse (fallback-якорь стратегии).

    При всех нулях возвращает 0.0.

    Args:
        apy_map: {protocol_key: annual_apy_pct}
                 Может быть пустым — используется FALLBACK_APY.

    Returns:
        weighted_apy_pct — взвешенный APY в процентах годовых (float).
    """
    result: float = 0.0
    redistributed_weight: float = 0.0

    for protocol, weight in ALLOCATION.items():
        if protocol in apy_map:
            result += weight * apy_map[protocol]
        else:
            redistributed_weight += weight

    # Перераспределяем вес отсутствующих протоколов на morpho_steakhouse
    if redistributed_weight > 0.0:
        morpho_apy = apy_map.get(
            "morpho_steakhouse",
            FALLBACK_APY.get("morpho_steakhouse", 6.5),
        )
        result += redistributed_weight * morpho_apy

    return result


def simulate_day(apy_map: dict, capital: float = 100_000.0) -> dict:
    """Симулировать один день — рассчитать дневной P&L.

    Использует compute_weighted_apy для получения годового APY,
    затем рассчитывает дневной доход:
        daily_return_pct = annual_apy / 365
        daily_pnl        = capital * daily_return_pct / 100

    Args:
        apy_map: {protocol_key: annual_apy_pct}
        capital: виртуальный капитал в USD (дефолт: $100K).

    Returns:
        dict с ключами:
            strategy_id      : "S6"
            daily_pnl        : дневная прибыль в USD
            daily_return_pct : дневная доходность в %
            annual_apy_pct   : годовой APY в %
            allocation       : dict весов ALLOCATION
            capital          : использованный капитал
            protocol_count   : число протоколов (5)
    """
    annual_apy = compute_weighted_apy(apy_map)
    daily_return_pct = annual_apy / 365.0
    daily_pnl = capital * daily_return_pct / 100.0

    return {
        "strategy_id":      STRATEGY_ID,
        "daily_pnl":        daily_pnl,
        "daily_return_pct": daily_return_pct,
        "annual_apy_pct":   annual_apy,
        "allocation":       dict(ALLOCATION),
        "capital":          capital,
        "protocol_count":   len(ALLOCATION),
    }


def check_concentration(allocation: Optional[Dict[str, float]] = None) -> dict:
    """Проверить концентрацию аллокации на соответствие лимитам.

    Проверяет два условия:
      1. Ни один протокол не превышает MAX_SINGLE_PROTOCOL_PCT (40%).
      2. Суммарная доля T2-протоколов ≤ MAX_T2_ALLOCATION (20%).

    Args:
        allocation: аллокация для проверки. При None используется ALLOCATION.

    Returns:
        dict с ключами:
            compliant         : True если все лимиты соблюдены
            violations        : список строк-нарушений (пустой при compliant)
            max_concentration : максимальная доля одного протокола
    """
    alloc = allocation if allocation is not None else ALLOCATION
    violations: List[str] = []

    # Проверка 1: ни один протокол > MAX_SINGLE_PROTOCOL_PCT
    for protocol, weight in alloc.items():
        if weight > MAX_SINGLE_PROTOCOL_PCT:
            violations.append(
                f"{protocol}: {weight:.2%} > MAX_SINGLE_PROTOCOL_PCT ({MAX_SINGLE_PROTOCOL_PCT:.2%})"
            )

    # Проверка 2: суммарная T2 ≤ MAX_T2_ALLOCATION
    t2_total = sum(alloc.get(p, 0.0) for p in T2_PROTOCOLS)
    if t2_total > MAX_T2_ALLOCATION:
        violations.append(
            f"T2 total: {t2_total:.2%} > MAX_T2_ALLOCATION ({MAX_T2_ALLOCATION:.2%})"
        )

    max_concentration = max(alloc.values()) if alloc else 0.0

    return {
        "compliant":         len(violations) == 0,
        "violations":        violations,
        "max_concentration": max_concentration,
    }


def get_diversity_score() -> float:
    """Мера диверсификации — обратная концентрации.

    Формула: 1 - max(ALLOCATION.values())
    Чем выше значение, тем лучше диверсифицирована стратегия.

    Для S6 (max = 0.40): 1 - 0.40 = 0.60

    Returns:
        diversity_score (float, диапазон 0..1)
    """
    return 1.0 - max(ALLOCATION.values())


def vs_baseline_improvement(baseline_apy: float = 3.2) -> dict:
    """Сравнить S6 с baseline (S0 Aave ~3.2% APY).

    Args:
        baseline_apy: APY baseline стратегии (дефолт: 3.2% = S0 Aave).

    Returns:
        dict с ключами:
            strategy        : "S6"
            baseline        : baseline_apy
            target          : APY_TARGET_PCT (7.5)
            improvement_pct : APY_TARGET_PCT - baseline_apy (4.3)
            multiplier      : APY_TARGET_PCT / baseline_apy (~2.34)
    """
    improvement_pct = APY_TARGET_PCT - baseline_apy
    multiplier = APY_TARGET_PCT / baseline_apy if baseline_apy > 0.0 else 0.0

    return {
        "strategy":        STRATEGY_ID,
        "baseline":        baseline_apy,
        "target":          APY_TARGET_PCT,
        "improvement_pct": improvement_pct,
        "multiplier":      multiplier,
    }


def to_vportfolio_format() -> dict:
    """Экспортировать S6 в формат, совместимый с VPortfolio.

    Returns:
        dict со стандартными ключами: id, name, allocation,
        risk_score, apy_target, protocol_count.
    """
    return {
        "id":             STRATEGY_ID,
        "name":           STRATEGY_NAME,
        "allocation":     dict(ALLOCATION),
        "risk_score":     RISK_SCORE,
        "apy_target":     APY_TARGET_PCT,
        "protocol_count": PROTOCOL_COUNT,
        "tier":           TIER,
        "description":    DESCRIPTION,
        "fallback_apy":   dict(FALLBACK_APY),
        "t2_protocols":   list(T2_PROTOCOLS),
        "diversity_score": get_diversity_score(),
        "max_single_protocol_pct": MAX_SINGLE_PROTOCOL_PCT,
        "max_t2_allocation":       MAX_T2_ALLOCATION,
    }


def get_t2_exposure() -> float:
    """Суммарная доля T2-протоколов в аллокации.

    Формула: sum(ALLOCATION[p] for p in T2_PROTOCOLS if p in ALLOCATION)
    Для S6: fluid_fusdc = 0.15

    Returns:
        t2_exposure (float) — суммарная доля T2 (ADR-019 limit: ≤ 20%).
    """
    return sum(ALLOCATION[p] for p in T2_PROTOCOLS if p in ALLOCATION)


# ─── Класс-обёртка S6MaxDiversified (handler_class для реестра) ───────────────

class S6MaxDiversified:
    """Class wrapper around the functional S6 Max Diversified module.

    Реестр (`StrategyMeta.handler_class`) и `multi_strategy_backtest.py`
    инстанцируют стратегию через `getattr(module, handler_class)()` — поэтому
    модулю нужен класс с этим именем. Логика остаётся в module-функциях;
    класс лишь делегирует к ним, сохраняя read-only / advisory контракт.

    Конструируется как `S6MaxDiversified()` (loader реестра) или
    `S6MaxDiversified(capital)` (standalone-проверки).
    """

    strategy_id = STRATEGY_ID

    def __init__(self, capital: float = 100_000.0) -> None:
        self.capital = float(capital)

    def get_allocation(self) -> Dict[str, float]:
        """Целевые веса по протоколам (копия ALLOCATION)."""
        return dict(ALLOCATION)

    def compute_weighted_apy(self, apy_map: Optional[dict] = None) -> float:
        """Взвешенный APY (делегирует module-функции)."""
        return compute_weighted_apy(apy_map or {})

    def simulate_day(self, apy_map: dict, capital: Optional[float] = None) -> dict:
        """Дневной P&L snapshot (делегирует module-функции)."""
        return simulate_day(apy_map, self.capital if capital is None else capital)

    def analyze(self, apy_map: Optional[dict] = None) -> dict:
        """Read-only сводка: strategy_id + целевая аллокация."""
        return {"strategy_id": self.strategy_id, "allocation": self.get_allocation()}


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S6 Max Diversified в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",   # T1+T2 — используем T2 как ближайший валидный тир
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=5.0,
            description=(
                "Max Diversification strategy: "
                "Pendle PT 40% (T1, ~10.0% APY), "
                "Morpho Steakhouse 30% (T1, ~6.5% APY), "
                "Fluid fUSDC 15% (T2, ~6.5% APY), "
                "Compound V3 10% (T1, ~4.8% APY), "
                "Aave Arbitrum 5% (T1, ~4.6% APY). "
                "Weighted APY ≈ 7.635%, Diversity Score = 0.60, Risk Score = 0.35."
            ),
            module="spa_core.strategies.s6_max_diversified",
            handler_class="S6MaxDiversified",
            tags=["pendle", "morpho", "fluid", "compound", "aave", "arbitrum",
                  "t1", "t2", "diversified", "max_diversified", "s6"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S6 Max Diversified auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
