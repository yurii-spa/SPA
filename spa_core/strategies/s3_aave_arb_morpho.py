"""
spa_core/strategies/s3_aave_arb_morpho.py — MP-381 S3 Aave Arbitrum L2 + Morpho

L2-focused стратегия: Aave V3 Arbitrum + Morpho Steakhouse + Aave Mainnet baseline.

Аллокация (L2 gas efficiency focus):
  - Aave V3 Arbitrum:        55%  (~4.1% APY, T1, chainId 42161, gas $0.09)
  - Morpho Steakhouse USDC:  30%  (~6.5% APY, T1)
  - Aave V3 Mainnet:         15%  (~3.2% APY, T1, baseline)

Weighted APY (дефолт):
  0.55*4.1 + 0.30*6.5 + 0.15*3.2
  = 2.255 + 1.95 + 0.48 = 4.685% ≈ 4.7%

Ключевые особенности:
  - L2 gas savings: ~$0.09 per tx vs mainnet $2-5
  - Только T1 протоколы — максимальная надёжность
  - Multi-chain: Arbitrum L2 + Ethereum mainnet
  - get_gas_savings_estimate(n_txs) — оценка экономии на газе

Совместимость:
  - to_vportfolio_format() → dict, совместимый с VPortfolio.from_dict()
  - simulate_day(apy_map) → использует фактические APY, fallback на дефолты
  - compute_weighted_apy(apy_map) → взвешенный APY
  - get_gas_savings_estimate(n_txs) → экономия газа USD
  - get_risk_flags() → список risk-флагов
  - get_stats() → сводная статистика

Правила:
  - stdlib only, no external deps
  - Атомарные записи при необходимости
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S3"
STRATEGY_NAME = "Aave Arbitrum L2 + Morpho"
TIER          = "T1"   # все позиции — T1

# Целевые веса по протоколам (доли 0..1, сумма = 1.0)
ALLOCATION: Dict[str, float] = {
    "aave_arbitrum":    0.55,   # T1, Aave V3 Arbitrum, chainId 42161
    "morpho_steakhouse": 0.30,  # T1, Morpho Steakhouse USDC vault
    "aave_mainnet":     0.15,   # T1, Aave V3 Mainnet (baseline)
}

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "aave_arbitrum":    4.1,   # ~4.1% APY Aave V3 Arbitrum
    "morpho_steakhouse": 6.5,  # ~6.5% APY Morpho Steakhouse USDC
    "aave_mainnet":     3.2,   # ~3.2% APY Aave V3 Mainnet baseline
}

# Ожидаемый взвешенный APY при дефолтных данных (%)
WEIGHTED_APY_EXPECTED = 4.7

# L2 экономия на газе за одну транзакцию (USD) vs mainnet ~$2-5
GAS_SAVINGS_PER_TX_USD = 0.09

# Risk-флаги стратегии
RISK_FLAGS: List[str] = ["l2_bridge_risk", "multi_chain_complexity"]

# Диапазон целевого APY (%)
TARGET_APY_MIN = 4.0
TARGET_APY_MAX = 7.0

# Порог drawdown для kill-сигнала (доля 0..1 = 5%)
KILL_DRAWDOWN_PCT = 0.05

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX = 365


# ─── S3AaveArbMorpho ──────────────────────────────────────────────────────────

class S3AaveArbMorpho:
    """S3 L2-focused стратегия: Aave Arbitrum 55% + Morpho 30% + Aave Mainnet 15%.

    Симулирует накопление yield на бумажных позициях.
    Использует фактические APY из apy_map, fallback на FALLBACK_APY.
    Совместима с VPortfolio через to_vportfolio_format().

    Не зависит от внешних библиотек — только stdlib.
    """

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100K)
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

        # Накопленное состояние
        self._days_simulated:  int   = 0
        self._total_yield_usd: float = 0.0

        # Кольцевой буфер истории equity (не более 365 точек)
        self._equity_history: List[Dict] = []

    # ── Публичный API ─────────────────────────────────────────────────────────

    def compute_weighted_apy(self, apy_map: Dict[str, float]) -> float:
        """Взвешенный годовой APY стратегии (% годовых).

        Формула:
            0.55 * aave_arbitrum_apy
            + 0.30 * morpho_steakhouse_apy
            + 0.15 * aave_mainnet_apy

        При дефолтных APY:
            0.55*4.1 + 0.30*6.5 + 0.15*3.2 = 2.255 + 1.95 + 0.48 = 4.685%

        Args:
            apy_map: {protocol_key: annual_apy_pct}
                     При отсутствии ключа используется FALLBACK_APY.

        Returns:
            weighted_apy_pct — взвешенный APY в процентах годовых
        """
        arb_apy    = apy_map.get("aave_arbitrum",    FALLBACK_APY["aave_arbitrum"])
        morpho_apy = apy_map.get("morpho_steakhouse", FALLBACK_APY["morpho_steakhouse"])
        main_apy   = apy_map.get("aave_mainnet",     FALLBACK_APY["aave_mainnet"])
        return (
            ALLOCATION["aave_arbitrum"]    * arb_apy
            + ALLOCATION["morpho_steakhouse"] * morpho_apy
            + ALLOCATION["aave_mainnet"]    * main_apy
        )

    def simulate_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулировать один день — начислить дневной yield на позиции.

        Для каждой позиции начисляется дневной yield по формуле:
            daily_yield = position_usd * apy_pct / 100 / 365

        При отсутствии протокола в apy_map используется FALLBACK_APY.
        Протоколы с APY ≤ 0 пропускаются.

        Args:
            apy_map: {protocol_key: annual_apy_pct} — живые APY данные.
                     Например: {"aave_arbitrum": 4.1, "morpho_steakhouse": 6.5,
                                "aave_mainnet": 3.2}
                     Может быть пустым — используются FALLBACK_APY.

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

            pos_usd      = self._positions[protocol]
            daily_yield  = pos_usd * apy_pct / 100.0 / 365.0
            # Реинвестируем yield в позицию (compound)
            self._positions[protocol] = pos_usd + daily_yield
            daily_yield_total += daily_yield

        self._total_yield_usd += daily_yield_total
        self._days_simulated  += 1

        w_apy = self.compute_weighted_apy(apy_map)

        self._equity_history.append({
            "day":             self._days_simulated,
            "equity":          round(self.current_equity, 6),
            "daily_yield_usd": round(daily_yield_total, 6),
            "weighted_apy":    round(w_apy, 4),
        })
        # Поддерживаем кольцевой буфер
        if len(self._equity_history) > _EQUITY_HISTORY_MAX:
            self._equity_history = self._equity_history[-_EQUITY_HISTORY_MAX:]

        return {
            "daily_yield_usd": daily_yield_total,
            "positions":       dict(self._positions),
            "weighted_apy":    w_apy,
        }

    def to_vportfolio_format(self) -> Dict:
        """Экспортировать состояние в формат, совместимый с VPortfolio.

        Возвращаемый dict содержит все стандартные поля VPortfolio для
        интеграции со стандартной инфраструктурой paper trading.

        Returns:
            dict со всеми полями VPortfolio:
                strategy_id, capital_usd, positions, cash_usd,
                equity_history, daily_returns, created_at, last_updated,
                total_yield_usd, days_simulated, peak_equity, status,
                current_equity, drawdown_pct, total_return_pct,
                tier, gas_savings_per_tx_usd, risk_flags
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
            "days_simulated":       self._days_simulated,
            "peak_equity":          round(self.current_equity, 6),
            "status":               "active",
            "current_equity":       round(self.current_equity, 6),
            "drawdown_pct":         0.0,
            "total_return_pct":     round(total_return_pct, 4),
            # S3-специфичные поля
            "tier":                 self.tier,
            "gas_savings_per_tx_usd": GAS_SAVINGS_PER_TX_USD,
            "risk_flags":           list(RISK_FLAGS),
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
        }

    def get_gas_savings_estimate(self, n_txs: int) -> float:
        """Оценить экономию на газе за n_txs транзакций vs mainnet.

        Использует константу GAS_SAVINGS_PER_TX_USD (= $0.09 per tx on Arbitrum
        vs mainnet ~$2-5). При отрицательном n_txs возвращает 0.0.

        Args:
            n_txs: количество транзакций (целое число ≥ 0).
                   Отрицательные значения трактуются как 0.

        Returns:
            Оценочная экономия на газе в USD.
        """
        if n_txs <= 0:
            return 0.0
        return float(n_txs) * GAS_SAVINGS_PER_TX_USD

    def get_risk_flags(self) -> List[str]:
        """Вернуть список risk-флагов стратегии.

        Returns:
            ['l2_bridge_risk', 'multi_chain_complexity']
        """
        return list(RISK_FLAGS)

    def get_stats(self) -> Dict:
        """Сводная статистика стратегии (read-only snapshot).

        Returns:
            dict с ключами:
                strategy_id, strategy_name, tier, capital_usd,
                current_equity, total_yield_usd, days_simulated,
                total_return_pct, weighted_apy_expected,
                gas_savings_per_tx_usd, risk_flags, allocation
        """
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            "strategy_id":             self.strategy_id,
            "strategy_name":           self.strategy_name,
            "tier":                    self.tier,
            "capital_usd":             self.capital,
            "current_equity":          round(self.current_equity, 6),
            "total_yield_usd":         round(self._total_yield_usd, 6),
            "days_simulated":          self._days_simulated,
            "total_return_pct":        round(total_return_pct, 4),
            "weighted_apy_expected":   WEIGHTED_APY_EXPECTED,
            "gas_savings_per_tx_usd":  GAS_SAVINGS_PER_TX_USD,
            "risk_flags":              list(RISK_FLAGS),
            "allocation":              dict(ALLOCATION),
        }

    @property
    def current_equity(self) -> float:
        """Текущая совокупная стоимость позиций (USD)."""
        return sum(self._positions.values())


# ─── Авто-регистрация в реестре strategies/ ───────────────────────────────────

def _register() -> None:
    """Зарегистрировать S3 в глобальном REGISTRY."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=5.0,
            description=(
                "L2-focused all-T1 strategy: Aave V3 Arbitrum 55% (~4.1% APY, gas $0.09), "
                "Morpho Steakhouse USDC 30% (~6.5% APY), "
                "Aave V3 Mainnet 15% (~3.2% APY baseline). "
                "Weighted APY ≈ 4.7%. Risk flags: l2_bridge_risk, multi_chain_complexity."
            ),
            module="spa_core.strategies.s3_aave_arb_morpho",
            handler_class="S3AaveArbMorpho",
            tags=["l2", "arbitrum", "morpho", "lending", "t1", "s3", "gas_efficient"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S3AaveArbMorpho auto-registration failed: %s", exc
        )


_register()
