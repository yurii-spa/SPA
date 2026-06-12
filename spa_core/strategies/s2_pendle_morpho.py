"""
spa_core/strategies/s2_pendle_morpho.py — MP-380 S2 Pendle PT + Morpho Heavy

Fixed-rate стратегия с фокусом на Pendle PT и Morpho Steakhouse.

Аллокация:
  - Pendle PT USDC:         50% (8.0% fixed APY, T2, REST-only, no-RPC)
  - Morpho Steakhouse USDC: 35% (6.5% APY, T1)
  - Compound V3 USDC:       15% (4.8% APY, T1)

Weighted APY:
  0.50*8.0 + 0.35*6.5 + 0.15*4.8 = 4.0 + 2.275 + 0.72 = 6.995% ≈ 7.0%

Риски:
  - pendle_maturity_risk: Pendle PT имеет дату погашения; rollover при экспирации
  - t2_liquidity_risk:    T2-компонента (50% Pendle PT) менее ликвидна, чем T1

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи при необходимости (mkstemp + os.replace)
  - Read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S2"
STRATEGY_NAME = "Pendle PT + Morpho Heavy"
TIER          = "T2"   # Pendle PT — T2, определяет tier всей стратегии

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "pendle_pt":         0.50,   # T2, Pendle PT USDC — fixed rate, REST-only
    "morpho_steakhouse": 0.35,   # T1, Morpho Steakhouse USDC vault
    "compound_v3":       0.15,   # T1, Compound V3 Comet USDC
}

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "pendle_pt":         8.0,    # ~8.0% fixed APY Pendle PT USDC
    "morpho_steakhouse": 6.5,    # ~6.5% APY Morpho Steakhouse USDC
    "compound_v3":       4.8,    # ~4.8% APY Compound V3 Comet USDC
}

# Ожидаемый взвешенный APY при дефолтных значениях
WEIGHTED_APY_EXPECTED: float = 7.0  # 0.50*8.0 + 0.35*6.5 + 0.15*4.8 ≈ 7.0%

# Флаги риска стратегии
RISK_FLAGS: List[str] = ["pendle_maturity_risk", "t2_liquidity_risk"]

# Диапазон целевого APY (%)
TARGET_APY_MIN = 6.5
TARGET_APY_MAX = 9.0

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX = 365


# ─── S2PendleMorpho ───────────────────────────────────────────────────────────

class S2PendleMorpho:
    """S2 — Pendle PT + Morpho Heavy стратегия.

    Fixed-rate фокус: 50% Pendle PT USDC (T2, REST-only, ~8.0% APY),
    35% Morpho Steakhouse USDC (T1, ~6.5% APY),
    15% Compound V3 USDC (T1, ~4.8% APY).
    Взвешенный APY ≈ 7.0%.

    Совместима с VPortfolio через to_vportfolio_format().
    Stdlib only, без внешних зависимостей.
    """

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100K).
                     Отрицательные и нулевые значения допускаются (paper trading).
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
            0.50 * pendle_apy + 0.35 * morpho_apy + 0.15 * compound_apy

        При дефолтных APY:
            0.50*8.0 + 0.35*6.5 + 0.15*4.8 = 4.0 + 2.275 + 0.72 = 6.995% ≈ 7.0%

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
            result += weight * apy
        return result

    def simulate_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулировать один день — начислить дневной yield на позиции.

        Для каждой позиции начисляется дневной yield по формуле:
            daily_yield = position_usd * apy_pct / 100 / 365

        При отсутствии протокола в apy_map используется FALLBACK_APY.
        Протоколы с APY ≤ 0 пропускаются.
        Yield реинвестируется (compound).

        Args:
            apy_map: {protocol_key: annual_apy_pct}
                     Может быть пустым — используются fallback.

        Returns:
            dict с ключами:
                daily_yield_usd: суммарный yield за день (USD)
                positions:       текущие значения позиций {protocol: usd}
                weighted_apy:    взвешенный APY сегодня (% годовых)
        """
        daily_yield_total = 0.0

        for protocol in list(self._positions.keys()):
            apy_pct = apy_map.get(protocol, FALLBACK_APY.get(protocol, 0.0))
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
            "strategy_id":       self.strategy_id,
            "capital_usd":       self.capital,
            "positions":         {k: round(v, 6) for k, v in self._positions.items()},
            "cash_usd":          0.0,
            "equity_history":    self._equity_history[-10:],
            "daily_returns":     [],
            "created_at":        now_iso,
            "last_updated":      now_iso,
            "total_yield_usd":   round(self._total_yield_usd, 6),
            "days_simulated":    self._days_simulated,
            "peak_equity":       round(self.current_equity, 6),
            "status":            "active",
            "current_equity":    round(self.current_equity, 6),
            "drawdown_pct":      0.0,
            "total_return_pct":  round(total_return_pct, 4),
            # S2-специфичные поля
            "tier":              self.tier,
            "allocation":        dict(ALLOCATION),
            "apy":               WEIGHTED_APY_EXPECTED,
            "risk_flags":        self.get_risk_flags(),
        }

    def get_risk_flags(self) -> List[str]:
        """Возвращает список флагов риска для стратегии.

        Returns:
            ['pendle_maturity_risk', 't2_liquidity_risk']
        """
        return list(RISK_FLAGS)

    def get_stats(self) -> Dict:
        """Summary метрики стратегии.

        Returns:
            dict со summary: strategy_id, name, tier, capital, equity,
            days_simulated, total_yield_usd, weighted_apy, risk_flags, allocation
        """
        return {
            "strategy_id":           self.strategy_id,
            "strategy_name":         self.strategy_name,
            "tier":                  self.tier,
            "capital_usd":           self.capital,
            "current_equity":        round(self.current_equity, 6),
            "days_simulated":        self._days_simulated,
            "total_yield_usd":       round(self._total_yield_usd, 6),
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
            "risk_flags":            self.get_risk_flags(),
            "allocation":            dict(ALLOCATION),
            "fallback_apy":          dict(FALLBACK_APY),
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S2 Pendle PT + Morpho Heavy в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=5.0,
            description=(
                "Fixed-rate strategy: Pendle PT USDC 50% (T2, REST-only, ~8.0%), "
                "Morpho Steakhouse USDC 35% (T1, ~6.5%), "
                "Compound V3 USDC 15% (T1, ~4.8%). "
                "Weighted APY ≈ 7.0%. "
                "Risks: pendle_maturity_risk, t2_liquidity_risk."
            ),
            module="spa_core.strategies.s2_pendle_morpho",
            handler_class="S2PendleMorpho",
            tags=["pendle", "morpho", "t2", "fixed_rate", "s2"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S2PendleMorpho auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
