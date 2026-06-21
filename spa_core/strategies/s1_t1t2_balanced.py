"""
spa_core/strategies/s1_t1t2_balanced.py — MP-358 S1 T1+T2 Balanced Strategy

Сбалансированная T1+T2 стратегия с целевым APY 6-8%.

Аллокация:
  - 40% T1: Aave V3        (~4.2% APY дефолт — надёжный якорный протокол)
  - 40% T2: Morpho Blue    (~6.5% APY дефолт — Steakhouse USDC vault)
  - 20% T2: Compound V3   (~4.8% APY дефолт — Comet USDC lending)

Формула weighted_apy:
  0.40 * aave_apy + 0.40 * morpho_apy + 0.20 * compound_apy

При дефолтных APY:
  0.40*4.2 + 0.40*6.5 + 0.20*4.8 = 1.68 + 2.60 + 0.96 = 5.24%

Риск: LOW — T1 якорь обеспечивает стабильность, T2 диверсифицирован
      по двум независимым протоколам (Morpho + Compound).

Совместимость:
  - to_vportfolio_format() → dict, совместимый с VPortfolio.from_dict()
    (spa_core.paper_trading.vportfolio)
  - simulate_day(apy_map) → использует фактические APY, fallback на дефолты

Правила:
  - stdlib only, no external deps
  - Атомарные записи (при необходимости)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "s1_t1t2_balanced"
STRATEGY_NAME = "S1 T1+T2 Balanced"

# Уровень риска стратегии (информационный)
STRATEGY_RISK_LEVEL = "LOW"

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
# VPortfolio применяет ≥5% cash buffer через _initialize_positions.
TARGET_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,   # T1, Aave V3 USDC — надёжный якорь
    "morpho_blue": 0.40,   # T2, Morpho Steakhouse USDC vault
    "compound_v3": 0.20,   # T2, Compound V3 Comet USDC
}

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
DEFAULT_APY: Dict[str, float] = {
    "aave_v3":     4.2,    # ~4.2% APY Aave V3 USDC
    "morpho_blue": 6.5,    # ~6.5% APY Morpho Steakhouse
    "compound_v3": 4.8,    # ~4.8% APY Compound V3 Comet
}

# Диапазон целевого APY (%)
TARGET_APY_MIN = 6.0
TARGET_APY_MAX = 8.0

# Порог drawdown для kill-сигнала (доля 0..1 = 5%)
KILL_DRAWDOWN_PCT = 0.05

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX = 365


# ─── S1T1T2BalancedStrategy ───────────────────────────────────────────────────

class S1T1T2BalancedStrategy(BaseAnalytics):
    """S1 сбалансированная стратегия T1+T2 (Aave 40% + Morpho 40% + Compound 20%).

    Симулирует накопление yield на бумажных позициях.
    Использует фактические APY из apy_map, fallback на DEFAULT_APY.
    Совместима с VPortfolio через to_vportfolio_format().

    Не зависит от внешних библиотек — только stdlib.

    BaseAnalytics:
        OUTPUT_PATH = "data/strategies/s1_t1t2_balanced_state.json"
        to_dict()   → to_vportfolio_format()
        save()      → атомарная запись состояния
        load()      → загрузка из JSON
    """

    OUTPUT_PATH = "data/strategies/s1_t1t2_balanced_state.json"

    def __init__(self, capital: float = 100_000.0, base_dir: str = ".") -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital:  начальный виртуальный капитал в USD (дефолт: $100K)
            base_dir: корневой каталог для save()/load() (дефолт: ".")
        """
        super().__init__(base_dir)
        self.strategy_id   = STRATEGY_ID
        self.risk_level    = STRATEGY_RISK_LEVEL
        self.capital       = float(capital)

        # Инициализируем позиции по целевым весам от начального капитала
        self._positions: Dict[str, float] = {
            protocol: self.capital * weight
            for protocol, weight in TARGET_WEIGHTS.items()
        }

        # Счётчики накопленного состояния
        self._days_simulated: int   = 0
        self._total_yield_usd: float = 0.0

        # Кольцевой буфер истории equity (не более 365 точек)
        self._equity_history: List[Dict] = []

    # ── Публичный API ─────────────────────────────────────────────────────────

    def simulate_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулировать один день — начислить дневной yield на позиции.

        Для каждой позиции начисляется дневной yield по формуле:
            daily_yield = position_usd * apy_pct / 100 / 365

        При отсутствии протокола в apy_map используется дефолтный APY
        из DEFAULT_APY. Протоколы с APY ≤ 0 пропускаются.

        Args:
            apy_map: {protocol_key: annual_apy_pct} — живые APY данные.
                     Например: {"aave_v3": 4.2, "morpho_blue": 6.8, "compound_v3": 5.1}
                     Может быть пустым — используются дефолты.

        Returns:
            dict с ключами:
                daily_yield_usd: суммарный yield за день (USD)
                positions:       текущие значения позиций {protocol: usd}
                weighted_apy:    взвешенный APY сегодня (% годовых)
        """
        daily_yield_total = 0.0

        # Начисляем yield по каждой позиции
        for protocol in list(self._positions.keys()):
            # Фактический APY из карты, fallback на дефолт; ноль пропускаем
            apy_pct = apy_map.get(protocol, DEFAULT_APY.get(protocol, 0.0))
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
            "positions":       dict(self._positions),
            "weighted_apy":    w_apy,
        }

    def compute_weighted_apy(self, apy_map: Dict[str, float]) -> float:
        """Взвешенный годовой APY стратегии (% годовых).

        Формула:
            0.40 * aave_apy + 0.40 * morpho_apy + 0.20 * compound_apy

        При дефолтных APY:
            0.40*4.2 + 0.40*6.5 + 0.20*4.8 = 1.68 + 2.60 + 0.96 = 5.24%

        Args:
            apy_map: {protocol_key: annual_apy_pct}
                     При отсутствии ключа используется DEFAULT_APY.

        Returns:
            weighted_apy_pct — взвешенный APY в процентах годовых
        """
        t1_apy       = apy_map.get("aave_v3",     DEFAULT_APY["aave_v3"])
        morpho_apy   = apy_map.get("morpho_blue",  DEFAULT_APY["morpho_blue"])
        compound_apy = apy_map.get("compound_v3",  DEFAULT_APY["compound_v3"])
        return (
            TARGET_WEIGHTS["aave_v3"]     * t1_apy
            + TARGET_WEIGHTS["morpho_blue"]  * morpho_apy
            + TARGET_WEIGHTS["compound_v3"]  * compound_apy
        )

    def get_allocation(self) -> Dict[str, float]:
        """Целевые веса по протоколам (копия TARGET_WEIGHTS)."""
        return dict(TARGET_WEIGHTS)

    def analyze(self, apy_map: Optional[Dict[str, float]] = None) -> Dict:
        """Реализация абстрактного контракта BaseAnalytics.analyze().

        Read-only сводка стратегии: идентификатор, целевая аллокация и
        взвешенный APY на переданных (или дефолтных) данных. Ничего не
        мутирует и не пишет на диск.

        Args:
            apy_map: {protocol_key: annual_apy_pct}; None → DEFAULT_APY.

        Returns:
            dict: strategy_id, allocation, weighted_apy.
        """
        return {
            "strategy_id":  self.strategy_id,
            "allocation":   self.get_allocation(),
            "weighted_apy": self.compute_weighted_apy(apy_map or {}),
        }

    @property
    def current_equity(self) -> float:
        """Текущая совокупная стоимость позиций (USD). Не включает cash."""
        return sum(self._positions.values())

    def to_dict(self) -> Dict:
        """Сериализовать текущее состояние стратегии в dict (BaseAnalytics API).

        Делегирует в to_vportfolio_format() — формат, совместимый с VPortfolio.
        Используется через save() и load() из BaseAnalytics.
        """
        return self.to_vportfolio_format()

    def to_vportfolio_format(self) -> Dict:
        """Экспортировать состояние в формат, совместимый с VPortfolio.

        Возвращаемый dict можно передать в VPortfolio.from_dict() для
        интеграции со стандартной инфраструктурой paper trading.

        Returns:
            dict со всеми полями VPortfolio (strategy_id, capital_usd,
            positions, cash_usd, equity_history, daily_returns, …)
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        # Суммарная доходность с начала (%)
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            "strategy_id":    self.strategy_id,
            "capital_usd":    self.capital,
            "positions":      {k: round(v, 6) for k, v in self._positions.items()},
            "cash_usd":       0.0,   # S1 полностью инвестирована (cash в VPortfolio отдельно)
            # Последние 10 точек истории (для read-only интеграции)
            "equity_history": self._equity_history[-10:],
            "daily_returns":  [],    # в standalone-режиме не вычисляем
            "created_at":     now_iso,
            "last_updated":   now_iso,
            "total_yield_usd":  round(self._total_yield_usd, 6),
            "days_simulated":   self._days_simulated,
            "peak_equity":      round(self.current_equity, 6),   # упрощение: max = current
            "status":           "active",
            # Производные поля (вычислены при экспорте для удобства dashboard)
            "current_equity":   round(self.current_equity, 6),
            "drawdown_pct":     0.0,
            "total_return_pct": round(total_return_pct, 4),
        }


# ─── Авто-регистрация в реестре strategies/ ───────────────────────────────────

def _register() -> None:
    """Зарегистрировать S1 T1+T2 Balanced в глобальном REGISTRY (strategies/).

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",        # смешанный T1+T2, классифицируем как T2 (есть T2-доля)
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=5.0,  # kill threshold 5% (KILL_DRAWDOWN_PCT * 100)
            description=(
                "T1+T2 balanced: Aave V3 40% (T1, ~4.2%), "
                "Morpho Steakhouse 40% (T2, ~6.5%), "
                "Compound V3 20% (T2, ~4.8%). "
                "Weighted APY = 0.4*aave + 0.4*morpho + 0.2*compound. "
                "Default weighted APY ≈ 5.24%. Target range 6-8%. Risk: LOW."
            ),
            module="spa_core.strategies.s1_t1t2_balanced",
            handler_class="S1T1T2BalancedStrategy",
            tags=["balanced", "lending", "t1", "t2", "s1"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S1T1T2BalancedStrategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
