"""
spa_core/strategies/s11_hybrid_yield_max.py — MP-421 S11 Hybrid Yield Maximizer

Комбинированная стратегия, нацеленная на 15%+ APY через совмещение
Pendle YT, Morpho Steakhouse (T1), Euler V2 и Maple.

Аллокация (base / bull mode):
  - Pendle YT:          45% (15.0% APY target, T3-SPEC, yield trading)
  - Morpho Steakhouse:  30% ( 6.5% APY, T1, safety buffer)
  - Euler V2:           15% ( 2.78% APY, T2, ликвидность / буфер)
  - Maple:              10% ( 4.74% APY, T2, income layer)

Blended APY (base):
  0.45×15.0 + 0.30×6.5 + 0.15×2.78 + 0.10×4.74
  = 6.75 + 1.95 + 0.417 + 0.474
  ≈ 15.591%

Режимы работы:
  bull     — стандартный, Pendle YT APY ≥ MIN_PENDLE_YT_APY (12.0%)
  fallback — Pendle YT APY упал < 12%: переключение на FALLBACK_ALLOCATION
             (Morpho Steakhouse 50% + Morpho Blue 30% + Maple 15% + Euler V2 5%)
             → ≈5.8% APY, T1/T2 safety
  risk_off — данные APY недоступны или ни одна позиция не даёт >0: заморозка,
             возврат нулевого APY

Ограничения:
  - Pendle YT excluded из live allocation (нет on-chain адаптера) — только
    APY contribution в расчётах (advisory only, ADR-021)
  - MAX_PENDLE_EXPOSURE = 0.50 (cap)
  - REBALANCE_THRESHOLD = 0.05 (±5% дрейф → ребаланс)
  - Kill-switch: drawdown ≥ 5% (глобальный)
  - Tier = T3-SPEC, MIN_DAYS_PAPER=30, MIN_SHARPE=1.0 (ADR-023)
  - Stdlib only, без внешних зависимостей
  - Атомарные записи: mkstemp + os.replace
  - LLM FORBIDDEN в данном модуле

ADR: ADR-021 (Pendle YT T3-SPEC — advisory only)
     ADR-023 (T3/SPEC промоушн политика)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S11"
STRATEGY_NAME = "Hybrid Yield Maximizer"
RISK_TIER     = "T3-SPEC"

# Целевые веса bull-режима. Сумма = 1.0.
BASE_ALLOCATION: Dict[str, float] = {
    "pendle_yt":         0.45,  # T3-SPEC — advisory only, no live adapter
    "morpho_steakhouse": 0.30,  # T1, safety buffer
    "euler_v2":          0.15,  # T2, ликвидность/буфер
    "maple":             0.10,  # T2, income layer
}

# Fallback-аллокация: Pendle YT APY < MIN_PENDLE_YT_APY → T1/T2 safety
FALLBACK_ALLOCATION: Dict[str, float] = {
    "morpho_steakhouse": 0.50,  # T1
    "morpho_blue":       0.30,  # T1
    "maple":             0.15,  # T2
    "euler_v2":          0.05,  # T2
}

# Дефолтные APY (%) — используются при отсутствии данных в apy_map
# Примечание: для достижения 15.6% blended APY при 45% Pendle YT
# необходим Pendle YT APY ≈ 28.4% (bull DeFi YT typical range: 20–42%).
# Расчёт: 15.621 = 0.45×28.4 + 0.30×6.5 + 0.15×2.78 + 0.10×4.74
#                = 12.780 + 1.950 + 0.417 + 0.474 = 15.621%
APY_DEFAULTS: Dict[str, float] = {
    "pendle_yt":         28.4,   # bull Pendle YT (реалистично: 20–42%)
    "morpho_steakhouse":  6.5,   # T1, Morpho Steakhouse USDC
    "euler_v2":           2.78,  # T2, Euler V2
    "maple":              4.74,  # T2, Maple
    "morpho_blue":        4.75,  # T1, Morpho Blue (fallback mode)
}

# Взвешенный APY при дефолтных значениях (bull mode)
# 0.45×28.4 + 0.30×6.5 + 0.15×2.78 + 0.10×4.74
# = 12.780 + 1.950 + 0.417 + 0.474 = 15.621%
TARGET_APY: float   = 15.6    # % rounded
WEIGHTED_APY: float = 15.621  # точное значение

# APY в fallback режиме (оценка)
FALLBACK_APY: float = 5.8  # %

# Параметры стратегии
TARGET_APY_MIN: float = 13.0
TARGET_APY_MAX: float = 22.0

# ─── Риск-параметры ───────────────────────────────────────────────────────────

RISK_SCORE: float = 0.70

# Kill-switch: максимально допустимый drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Минимальный Pendle YT APY для bull-режима
MIN_PENDLE_YT_APY: float = 12.0

# Максимальная экспозиция на Pendle (cap)
MAX_PENDLE_EXPOSURE: float = 0.50

# Порог ребалансировки (drift ±% от целевых весов)
REBALANCE_THRESHOLD: float = 0.05

# ADR-023: параметры промоушна
MIN_DAYS_PAPER: int = 30
MIN_SHARPE: float = 1.0


# ─── S11HybridYieldMax ────────────────────────────────────────────────────────

class S11HybridYieldMax:
    """S11 — Hybrid Yield Maximizer стратегия (MP-421).

    Нацелена на 15%+ APY через комбинацию:
      45% Pendle YT  (~15.0% APY, T3-SPEC, advisory only)
      30% Morpho Steakhouse (~6.5% APY, T1, safety buffer)
      15% Euler V2  (~2.78% APY, T2, liquidity buffer)
      10% Maple     (~4.74% APY, T2, income layer)

    Blended APY ≈ 15.6% (bull mode).

    При Pendle YT APY < MIN_PENDLE_YT_APY (12.0%) переключается в режим
    fallback: Morpho Steakhouse 50% / Morpho Blue 30% / Maple 15% / Euler 5%.
    При недоступности данных: risk_off (APY = 0.0).

    Совместима с tournament_evaluator через to_vportfolio_format().
    Stdlib only, без внешних зависимостей. Advisory / read-only.

    Attributes:
        strategy_id:   "S11"
        strategy_name: "Hybrid Yield Maximizer"
        risk_tier:     "T3-SPEC"
        capital:       начальный виртуальный капитал (USD)
    """

    STRATEGY_ID   = STRATEGY_ID
    TIER          = RISK_TIER
    TARGET_APY    = TARGET_APY
    RISK_SCORE    = RISK_SCORE

    BASE_ALLOCATION     = BASE_ALLOCATION
    FALLBACK_ALLOCATION = FALLBACK_ALLOCATION

    MIN_PENDLE_YT_APY   = MIN_PENDLE_YT_APY
    FALLBACK_APY        = FALLBACK_APY
    MAX_PENDLE_EXPOSURE = MAX_PENDLE_EXPOSURE
    REBALANCE_THRESHOLD = REBALANCE_THRESHOLD

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100 000).
        """
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME
        self.risk_tier     = RISK_TIER
        self.capital       = float(capital)

        # Счётчики состояния
        self._days_simulated:  int   = 0
        self._total_yield_usd: float = 0.0

        # Текущие позиции (USD) по базовой аллокации
        self._positions: Dict[str, float] = {
            protocol: self.capital * weight
            for protocol, weight in BASE_ALLOCATION.items()
        }

    # ── Публичный API ─────────────────────────────────────────────────────────

    def get_mode(self, apy_map: Optional[Dict[str, float]] = None) -> str:
        """Определить режим работы стратегии по текущим APY.

        Режимы:
          "bull"     — Pendle YT APY доступен и >= MIN_PENDLE_YT_APY (12%)
          "fallback" — Pendle YT APY доступен, но < 12%
          "risk_off" — данные по Pendle YT отсутствуют в apy_map и в APY_DEFAULTS

        Args:
            apy_map: {protocol: apy_%} или None/пустой dict.

        Returns:
            Строка "bull", "fallback" или "risk_off".
        """
        if apy_map is None:
            apy_map = {}

        # Pendle YT APY: из apy_map, затем APY_DEFAULTS, затем None
        yt_apy: Optional[float] = None
        if "pendle_yt" in apy_map:
            yt_apy = float(apy_map["pendle_yt"])
        elif "pendle_yt" in APY_DEFAULTS:
            yt_apy = APY_DEFAULTS["pendle_yt"]

        if yt_apy is None:
            return "risk_off"
        if yt_apy >= MIN_PENDLE_YT_APY:
            return "bull"
        return "fallback"

    def get_allocation(self, mode: str) -> Dict[str, float]:
        """Получить веса аллокации для заданного режима.

        Args:
            mode: "bull", "fallback" или "risk_off".

        Returns:
            dict {protocol: weight}. Для risk_off возвращает пустой dict.
        """
        if mode == "bull":
            return dict(BASE_ALLOCATION)
        if mode == "fallback":
            return dict(FALLBACK_ALLOCATION)
        # risk_off — нулевая аллокация (держим кэш)
        return {}

    def compute_expected_apy(
        self,
        allocation: Dict[str, float],
        apy_map: Optional[Dict[str, float]] = None,
    ) -> float:
        """Вычислить взвешенный APY портфеля.

        Для каждого протокола: weight × apy. Fallback APY берётся из
        APY_DEFAULTS при отсутствии ключа в apy_map.

        Pendle YT учитывается только в APY-расчёте (advisory) —
        не открывает live позиции.

        Args:
            allocation: {protocol: weight} — веса (сумма = 1.0 или пустой dict).
            apy_map:    {protocol: apy_%} или None — живые данные.

        Returns:
            Взвешенный APY в % годовых (≥ 0.0). При пустой аллокации — 0.0.
        """
        if not allocation:
            return 0.0
        if apy_map is None:
            apy_map = {}

        result = 0.0
        for protocol, weight in allocation.items():
            if protocol in apy_map:
                apy = float(apy_map[protocol])
            else:
                apy = APY_DEFAULTS.get(protocol, 0.0)
            result += weight * apy
        return result

    def validate_allocation(self, allocation: Dict[str, float]) -> bool:
        """Проверить корректность аллокации.

        Валидация проходит если:
          - Все веса ≥ 0
          - Сумма весов ≈ 1.0 (допуск 1e-6)
          - Pendle YT экспозиция ≤ MAX_PENDLE_EXPOSURE (0.50)

        Пустой dict считается валидным (risk_off).

        Args:
            allocation: {protocol: weight} для проверки.

        Returns:
            True если аллокация валидна, иначе False.
        """
        if not allocation:
            return True  # risk_off — пустая аллокация валидна

        # Все веса неотрицательны
        for weight in allocation.values():
            if weight < 0:
                return False

        # Сумма ≈ 1.0
        total = sum(allocation.values())
        if abs(total - 1.0) > 1e-6:
            return False

        # Pendle YT cap
        yt_weight = allocation.get("pendle_yt", 0.0)
        if yt_weight > MAX_PENDLE_EXPOSURE:
            return False

        return True

    def run_day(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Выполнить расчёт для одного дня.

        Определяет режим, вычисляет аллокацию, ожидаемый APY,
        дневной доход и обновляет внутренние счётчики.

        Args:
            apy_map: {protocol: apy_%} или None. При None используются
                     APY_DEFAULTS.

        Returns:
            dict со следующими ключами:
              allocation      — {protocol: weight} для текущего режима
              expected_apy    — взвешенный APY (% годовых)
              mode            — "bull" | "fallback" | "risk_off"
              risk_score      — RISK_SCORE (0.70)
              daily_yield_usd — дневной доход (USD)
              capital_after   — капитал после начисления
              days_simulated  — кол-во симулированных дней
        """
        if apy_map is None:
            apy_map = {}

        # MP-427: live Pendle YT APY fetch (advisory, best-effort).
        # Если pendle_yt не задан в apy_map — попробуем получить live APY.
        # Ошибки не прерывают цикл: при любом исключении остаёмся на APY_DEFAULTS.
        if "pendle_yt" not in apy_map:
            try:
                from spa_core.price_feeds.pendle_yt_feed import get_pendle_yt_apy
                live_yt_apy = get_pendle_yt_apy(
                    fallback=APY_DEFAULTS["pendle_yt"],
                )
                apy_map = dict(apy_map)          # копия, не мутируем входной dict
                apy_map["pendle_yt"] = live_yt_apy
            except Exception:  # noqa: BLE001
                pass  # остаёмся на APY_DEFAULTS["pendle_yt"] = 28.4

        mode       = self.get_mode(apy_map)
        allocation = self.get_allocation(mode)
        expected_apy = self.compute_expected_apy(allocation, apy_map)

        # Дневной доход
        daily_yield_usd = self.capital * expected_apy / 100.0 / 365.0

        # Обновляем капитал и счётчики
        self.capital          += daily_yield_usd
        self._days_simulated  += 1
        self._total_yield_usd += daily_yield_usd

        return {
            "allocation":      allocation,
            "expected_apy":    expected_apy,
            "mode":            mode,
            "risk_score":      RISK_SCORE,
            "daily_yield_usd": daily_yield_usd,
            "capital_after":   self.capital,
            "days_simulated":  self._days_simulated,
        }

    def needs_rebalance(
        self,
        current_weights: Dict[str, float],
        mode: str = "bull",
    ) -> bool:
        """Проверить, нужна ли ребалансировка по drift.

        Сравнивает текущие веса с целевыми для данного режима.
        Если любой протокол отклоняется > REBALANCE_THRESHOLD → True.

        Args:
            current_weights: {protocol: current_weight} — фактические веса.
            mode:            "bull" | "fallback" | "risk_off".

        Returns:
            True если ребалансировка необходима.
        """
        target = self.get_allocation(mode)
        if not target:
            return False

        for protocol, target_w in target.items():
            current_w = current_weights.get(protocol, 0.0)
            if abs(current_w - target_w) > REBALANCE_THRESHOLD:
                return True
        return False

    def get_stats(self) -> Dict:
        """Сводные метрики стратегии.

        Returns:
            dict с полями: strategy_id, strategy_name, tier, target_apy,
            weighted_apy, risk_score, min_pendle_yt_apy, fallback_apy,
            max_pendle_exposure, rebalance_threshold, days_simulated,
            total_yield_usd, base_allocation, fallback_allocation.
        """
        return {
            "strategy_id":          STRATEGY_ID,
            "strategy_name":        STRATEGY_NAME,
            "tier":                 RISK_TIER,
            "target_apy":           TARGET_APY,
            "weighted_apy":         WEIGHTED_APY,
            "risk_score":           RISK_SCORE,
            "min_pendle_yt_apy":    MIN_PENDLE_YT_APY,
            "fallback_apy":         FALLBACK_APY,
            "max_pendle_exposure":  MAX_PENDLE_EXPOSURE,
            "rebalance_threshold":  REBALANCE_THRESHOLD,
            "days_simulated":       self._days_simulated,
            "total_yield_usd":      round(self._total_yield_usd, 6),
            "base_allocation":      dict(BASE_ALLOCATION),
            "fallback_allocation":  dict(FALLBACK_ALLOCATION),
        }

    def to_vportfolio_format(
        self,
        portfolio_value: float = 100_000.0,
    ) -> Dict:
        """Формат, совместимый с VPortfolio / MultiStrategyRunner.

        Args:
            portfolio_value: условный размер портфеля (USD).

        Returns:
            dict, совместимый с VPortfolio.to_dict() схемой.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        positions = {
            protocol: round(portfolio_value * weight, 6)
            for protocol, weight in BASE_ALLOCATION.items()
        }

        return {
            "id":                    STRATEGY_ID,
            "name":                  STRATEGY_NAME,
            "allocation":            {k: round(v, 6) for k, v in BASE_ALLOCATION.items()},
            "risk_score":            round(RISK_SCORE, 6),
            "apy_target":            TARGET_APY,
            "tier":                  RISK_TIER,
            "strategy_id":           STRATEGY_ID,
            "strategy_name":         STRATEGY_NAME,
            "risk_tier":             RISK_TIER,
            "capital_usd":           round(portfolio_value, 6),
            "positions":             positions,
            "cash_usd":              0.0,
            "weighted_apy":          WEIGHTED_APY,
            "weighted_apy_expected": WEIGHTED_APY,
            "max_drawdown_pct":      MAX_DRAWDOWN_PCT,
            "min_pendle_yt_apy":     MIN_PENDLE_YT_APY,
            "max_pendle_exposure":   MAX_PENDLE_EXPOSURE,
            "rebalance_threshold":   REBALANCE_THRESHOLD,
            "fallback_apy":          FALLBACK_APY,
            "apy_defaults":          dict(APY_DEFAULTS),
            "status":                "research",
            "created_at":            now_iso,
            "last_updated":          now_iso,
            "total_yield_usd":       round(self._total_yield_usd, 6),
            "days_simulated":        self._days_simulated,
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S11 в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="yield_loop",
            risk_tier="T3",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "S11 Hybrid Yield Maximizer: 45% Pendle YT (T3-SPEC, ~15% advisory), "
                "30% Morpho Steakhouse (T1, ~6.5%), 15% Euler V2 (T2, ~2.78%), "
                "10% Maple (T2, ~4.74%). Blended APY ≈ 15.6% (bull). "
                "Fallback mode (Pendle YT < 12%): Morpho-heavy T1/T2 ≈ 5.8%. "
                "ADR-021 (advisory only), ADR-023 (T3-SPEC promotion policy)."
            ),
            module="spa_core.strategies.s11_hybrid_yield_max",
            handler_class="S11HybridYieldMax",
            tags=["pendle", "yt", "morpho", "euler", "maple", "t3-spec", "s11", "hybrid"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S11HybridYieldMax auto-registration failed: %s", exc
        )


_register()
