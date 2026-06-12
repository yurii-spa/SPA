"""
spa_core/strategies/s4_spark_fluid_conservative.py — MP-391 S4 Conservative Spark+Fluid

Capital-preservation стратегия: Spark sUSDS (T1, low risk) + Fluid fUSDC (T2) +
Morpho Steakhouse (T1). Фокус на сохранении капитала при умеренной доходности.

Аллокация:
  - Spark sUSDS:             60% (T1, Risk 0.28, APY ~5.5%, GSM gate 48h)
  - Fluid fUSDC:             25% (T2, Risk 0.38, APY ~6.5%, spike normalization >15%→9%)
  - Morpho Steakhouse USDC:  15% (T1, Risk 0.32, APY ~6.5%)

Weighted APY (дефолт):
  0.60*5.5 + 0.25*6.5 + 0.15*6.5
  = 3.3 + 1.625 + 0.975 = 5.9%

Blended Risk Score:
  0.60*0.28 + 0.25*0.38 + 0.15*0.32
  = 0.168 + 0.095 + 0.048 = 0.311 ≈ 0.31

Ключевые особенности:
  - GSM gate: Spark sUSDS использует GSM Pause Delay ≥ 48h; предупреждение при gsm_hours < 48
  - Fluid spike normalization: APY > 15% нормализуется до 9% (сглаживание пиков)
  - Все протоколы: T1 (60% Spark) + T2 (25% Fluid) + T1 (15% Morpho)
  - Самый консервативный Risk Score среди S1–S4

Совместимость:
  - to_vportfolio_format() → dict, совместимый с VPortfolio
  - simulate_day(apy_map) → использует фактические APY, fallback на дефолты
  - compute_weighted_apy(apy_map) → взвешенный APY
  - get_risk_flags(gsm_hours) → список risk-флагов + GSM gate warning
  - get_stats() → сводная статистика

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи при необходимости (mkstemp + os.replace)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S4"
STRATEGY_NAME = "S4 Conservative Spark+Fluid"
TIER          = "T1+T2"   # T1-доминирующая (60% Spark T1 + 15% Morpho T1 + 25% Fluid T2)
DESCRIPTION   = (
    "Capital-preservation strategy: Spark sUSDS (T1, low risk) + "
    "Fluid fUSDC (T2) + Morpho Steakhouse (T1)"
)

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "spark_susds":       0.60,   # T1, Spark sUSDS, Risk 0.28, APY ~5.5%
    "fluid_fusdc":       0.25,   # T2, Fluid fUSDC, Risk 0.38, APY ~6.5%
    "morpho_steakhouse": 0.15,   # T1, Morpho Steakhouse USDC, Risk 0.32, APY ~6.5%
}

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "spark_susds":       5.5,   # ~5.5% APY Spark sUSDS
    "fluid_fusdc":       6.5,   # ~6.5% APY Fluid fUSDC (нормализованный)
    "morpho_steakhouse": 6.5,   # ~6.5% APY Morpho Steakhouse USDC
}

# Risk scores по протоколам
RISK_SCORES: Dict[str, float] = {
    "spark_susds":       0.28,  # T1, низкий риск, GSM gate
    "fluid_fusdc":       0.38,  # T2, средний риск, spike normalization
    "morpho_steakhouse": 0.32,  # T1, низкий-средний риск
}

# Ожидаемый взвешенный APY при дефолтных значениях
# 0.60*5.5 + 0.25*6.5 + 0.15*6.5 = 3.3 + 1.625 + 0.975 = 5.9%
WEIGHTED_APY_EXPECTED: float = 5.9

# Взвешенный Risk Score
# 0.60*0.28 + 0.25*0.38 + 0.15*0.32 = 0.168 + 0.095 + 0.048 = 0.311
RISK_BLENDED: float = 0.31

# GSM Pause Delay threshold для Spark sUSDS (часы)
GSM_PAUSE_DELAY_THRESHOLD_H: float = 48.0

# Порог нормализации APY для Fluid fUSDC (спайки выше → нормализуются)
FLUID_APY_SPIKE_THRESHOLD: float = 15.0
FLUID_APY_NORMALIZED:      float = 9.0

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 5.0
TARGET_APY_MAX: float = 7.5

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── S4ConservativeSparkFluid ─────────────────────────────────────────────────

class S4ConservativeSparkFluid:
    """S4 — Capital-preservation стратегия: Spark+Fluid+Morpho.

    Аллокация: 60% Spark sUSDS (T1, ~5.5% APY, GSM gate 48h),
               25% Fluid fUSDC (T2, ~6.5% APY, spike normalization),
               15% Morpho Steakhouse (T1, ~6.5% APY).
    Взвешенный APY ≈ 5.9%, Blended Risk ≈ 0.31.

    Совместима с VPortfolio через to_vportfolio_format().
    Stdlib only, без внешних зависимостей.
    """

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100K).
                     Нулевые значения допускаются (paper trading).
        """
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME
        self.tier          = TIER
        self.capital       = float(capital)

        # Инициализируем позиции по целевым весам от начального капитала
        self._positions: Dict[str, float] = {
            protocol: self.capital * weight
            for protocol, weight in ALLOCATION.items()
        }

        # Счётчики накопленного состояния
        self._days_simulated:  int   = 0
        self._total_yield_usd: float = 0.0

        # Кольцевой буфер истории equity (не более 365 точек)
        self._equity_history: List[Dict] = []

    # ── Публичный API ─────────────────────────────────────────────────────────

    def compute_weighted_apy(self, apy_map: Dict[str, float]) -> float:
        """Взвешенный годовой APY стратегии (% годовых).

        Формула:
            0.60 * spark_apy + 0.25 * fluid_apy + 0.15 * morpho_apy

        При дефолтных APY:
            0.60*5.5 + 0.25*6.5 + 0.15*6.5 = 3.3 + 1.625 + 0.975 = 5.9%

        Fluid fUSDC: если APY > FLUID_APY_SPIKE_THRESHOLD (15%),
        нормализуется до FLUID_APY_NORMALIZED (9%) перед расчётом.

        Args:
            apy_map: {protocol_key: annual_apy_pct}
                     При отсутствии ключа используется FALLBACK_APY.
                     Может быть пустым — все значения из fallback.

        Returns:
            weighted_apy_pct — взвешенный APY в процентах годовых
        """
        result = 0.0
        for protocol, weight in ALLOCATION.items():
            apy = apy_map.get(protocol, FALLBACK_APY.get(protocol, 0.0))
            # Нормализация Fluid fUSDC: спайки >15% → 9%
            if protocol == "fluid_fusdc" and apy > FLUID_APY_SPIKE_THRESHOLD:
                apy = FLUID_APY_NORMALIZED
            result += weight * apy
        return result

    def simulate_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулировать один день — начислить дневной yield на позиции.

        Для каждой позиции начисляется дневной yield по формуле:
            daily_yield = position_usd * apy_pct / 100 / 365

        При отсутствии протокола в apy_map используется FALLBACK_APY.
        Fluid fUSDC: APY > 15% нормализуется до 9%.
        Протоколы с APY ≤ 0 пропускаются.
        Yield реинвестируется (compound).

        Args:
            apy_map: {protocol_key: annual_apy_pct}
                     Может быть пустым — используются fallback.

        Returns:
            dict с ключами:
                daily_yield_usd: суммарный yield за день (USD)
                cumulative_pnl:  накопленный PnL = total_yield_usd (USD)
                positions:       текущие значения позиций {protocol: usd}
                weighted_apy:    взвешенный APY сегодня (% годовых)
        """
        daily_yield_total = 0.0

        for protocol in list(self._positions.keys()):
            apy_pct = apy_map.get(protocol, FALLBACK_APY.get(protocol, 0.0))
            # Нормализация Fluid fUSDC
            if protocol == "fluid_fusdc" and apy_pct > FLUID_APY_SPIKE_THRESHOLD:
                apy_pct = FLUID_APY_NORMALIZED

            if apy_pct <= 0.0:
                continue

            pos_usd = self._positions[protocol]
            # Дневной yield: pos * APY% / 100 / 365
            daily_yield = pos_usd * apy_pct / 100.0 / 365.0
            # Реинвестируем yield в позицию (compound)
            self._positions[protocol] = pos_usd + daily_yield
            daily_yield_total += daily_yield

        # Обновляем накопленные счётчики
        self._total_yield_usd += daily_yield_total
        self._days_simulated  += 1

        # Вычисляем weighted_apy для текущего снимка
        w_apy = self.compute_weighted_apy(apy_map)

        # Добавляем точку в кольцевой буфер
        self._equity_history.append({
            "day":             self._days_simulated,
            "equity":          round(self.current_equity, 6),
            "daily_yield_usd": round(daily_yield_total, 6),
            "weighted_apy":    round(w_apy, 4),
        })
        # Поддерживаем размер буфера не более _EQUITY_HISTORY_MAX
        if len(self._equity_history) > _EQUITY_HISTORY_MAX:
            self._equity_history = self._equity_history[-_EQUITY_HISTORY_MAX:]

        return {
            "daily_yield_usd": daily_yield_total,
            "cumulative_pnl":  self._total_yield_usd,
            "positions":       dict(self._positions),
            "weighted_apy":    w_apy,
        }

    @property
    def current_equity(self) -> float:
        """Текущая совокупная стоимость позиций (USD)."""
        return sum(self._positions.values())

    def to_vportfolio_format(self) -> Dict:
        """Экспортировать состояние в формат, совместимый с VPortfolio.

        Returns:
            dict со всеми полями VPortfolio: strategy_id, capital_usd,
            positions, cash_usd, equity_history, allocation, apy, tier, …
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            "strategy_id":          self.strategy_id,
            "strategy_name":        self.strategy_name,
            "capital_usd":          self.capital,
            "positions":            {k: round(v, 6) for k, v in self._positions.items()},
            "cash_usd":             0.0,
            "equity_history":       self._equity_history[-10:],
            "daily_returns":        [],
            "created_at":           now_iso,
            "last_updated":         now_iso,
            "total_yield_usd":      round(self._total_yield_usd, 6),
            "cumulative_pnl":       round(self._total_yield_usd, 6),
            "days_simulated":       self._days_simulated,
            "peak_equity":          round(self.current_equity, 6),
            "status":               "active",
            "current_equity":       round(self.current_equity, 6),
            "drawdown_pct":         0.0,
            "total_return_pct":     round(total_return_pct, 4),
            # S4-специфичные поля
            "tier":                 self.tier,
            "allocation":           dict(ALLOCATION),
            "apy":                  WEIGHTED_APY_EXPECTED,
            "risk_blended":         RISK_BLENDED,
            "risk_flags":           self.get_risk_flags(),
            "description":          DESCRIPTION,
        }

    def get_risk_flags(self, gsm_hours: float = 48.0) -> List[str]:
        """Возвращает список флагов риска для стратегии.

        Базовые флаги всегда присутствуют:
          - 'fluid_spike_normalization': Fluid APY > 15% нормализуется до 9%

        GSM gate флаг добавляется если gsm_hours < GSM_PAUSE_DELAY_THRESHOLD_H (48h):
          - 'gsm_gate_warning': Spark sUSDS GSM Pause Delay < 48h — аллокация заморожена

        Args:
            gsm_hours: текущее значение GSM Pause Delay (часы).
                       По умолчанию 48.0 (gate пройден, без предупреждения).

        Returns:
            Список строковых флагов риска.
        """
        flags: List[str] = ["fluid_spike_normalization"]
        if gsm_hours < GSM_PAUSE_DELAY_THRESHOLD_H:
            flags.append("gsm_gate_warning")
        return flags

    def get_stats(self) -> Dict:
        """Summary метрики стратегии.

        Returns:
            dict со summary: strategy_id, name, tier, capital, equity,
            days_simulated, total_yield_usd, weighted_apy, risk_blended,
            risk_scores, allocation
        """
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            "strategy_id":           self.strategy_id,
            "strategy_name":         self.strategy_name,
            "tier":                  self.tier,
            "description":           DESCRIPTION,
            "capital_usd":           self.capital,
            "current_equity":        round(self.current_equity, 6),
            "days_simulated":        self._days_simulated,
            "total_yield_usd":       round(self._total_yield_usd, 6),
            "total_return_pct":      round(total_return_pct, 4),
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
            "risk_blended":          RISK_BLENDED,
            "risk_scores":           dict(RISK_SCORES),
            "risk_flags":            self.get_risk_flags(),
            "allocation":            dict(ALLOCATION),
            "fallback_apy":          dict(FALLBACK_APY),
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S4 Conservative Spark+Fluid в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    REGISTRY.risk_tier использует 'T2' (ближайший валидный тир для T1+T2 стратегии).
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",   # T1+T2 не валиден; используем T2 как компромисс
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=5.0,
            description=(
                "Capital-preservation strategy: "
                "Spark sUSDS 60% (T1, Risk 0.28, ~5.5% APY, GSM gate 48h), "
                "Fluid fUSDC 25% (T2, Risk 0.38, ~6.5% APY, spike normalization >15%→9%), "
                "Morpho Steakhouse USDC 15% (T1, Risk 0.32, ~6.5% APY). "
                "Weighted APY ≈ 5.9%, Blended Risk ≈ 0.31."
            ),
            module="spa_core.strategies.s4_spark_fluid_conservative",
            handler_class="S4ConservativeSparkFluid",
            tags=["spark", "fluid", "morpho", "t1", "t2", "conservative",
                  "capital_preservation", "gsm_gate", "s4"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S4ConservativeSparkFluid auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
