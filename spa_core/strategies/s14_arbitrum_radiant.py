"""
spa_core/strategies/s14_arbitrum_radiant.py — MP-394 S14 Arbitrum Radiant Max

Arbitrum-dominant стратегия: Aave V3 Arbitrum (T1) + Radiant USDC Arbitrum (T2) +
Morpho Steakhouse Mainnet (T1). Фокус на Arbitrum L2 с максимизацией yield через
Radiant (Arbitrum-native money market) при сохранении T1-доминирующей аллокации.

Аллокация:
  - Aave V3 Arbitrum:         45%  (T1, Risk 0.22, APY ~4.6%, L2 anchor)
  - Radiant USDC (Arbitrum):  35%  (T2, Risk 0.42, APY ~8.0%, Arbitrum-native)
  - Morpho Steakhouse USDC:   20%  (T1, Risk 0.32, APY ~6.5%, mainnet backstop)

Weighted APY (дефолт):
  0.45*4.6 + 0.35*8.0 + 0.20*6.5
  = 2.07 + 2.80 + 1.30 = 6.17%

Blended Risk Score:
  0.45*0.22 + 0.35*0.42 + 0.20*0.32
  = 0.099 + 0.147 + 0.064 = 0.31

T1 доля: 45% (Aave Arb) + 20% (Morpho) = 65% → T1-dominant ✓
APY > 6% ✓

Ключевые особенности:
  - Radiant spike normalization: APY > RADIANT_SPIKE_THRESHOLD (20%) → RADIANT_APY_NORMALIZED (12%)
  - L2 gas advantage: ~$0.09/tx экономии vs mainnet ($0.01 L2 vs $0.10 mainnet)
  - Bridge risk flag: если Arbitrum аллокация > 70% → 'l2_bridge_risk'
  - Arbitrum share: 80% капитала на Arbitrum (Aave + Radiant) = L2-focused

Совместимость:
  - to_vportfolio_format() → dict, совместимый с VPortfolio
  - simulate_day(apy_map) → использует фактические APY, fallback на дефолты
  - compute_weighted_apy(apy_map) → взвешенный APY
  - get_gas_savings_estimate(n_txs) → оценка экономии газа (USD)
  - get_risk_flags() → список risk-флагов
  - get_l2_allocation_pct() → доля капитала на L2 (%)
  - get_stats() → сводная статистика

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи при необходимости (mkstemp + os.replace)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Arbitrum Phase 2 expansion)

Date: 2026-06-12
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S14"
STRATEGY_NAME = "S14 Arbitrum Radiant Max"
TIER          = "T1+T2"   # T1-доминирующая (65% T1: Aave Arb + Morpho)
DESCRIPTION   = (
    "Arbitrum-dominant strategy: Aave V3 Arbitrum (T1, L2 anchor) + "
    "Radiant USDC Arbitrum (T2, Arbitrum-native) + Morpho Steakhouse (T1, mainnet backstop)"
)

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "aave_arbitrum":     0.45,   # T1, Aave V3 Arbitrum, Risk 0.22, APY ~4.6%
    "radiant_arbitrum":  0.35,   # T2, Radiant USDC Arbitrum, Risk 0.42, APY ~8.0%
    "morpho_steakhouse": 0.20,   # T1, Morpho Steakhouse USDC, Risk 0.32, APY ~6.5%
}

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "aave_arbitrum":     4.6,   # ~4.6% APY Aave V3 Arbitrum (Arbitrum premium)
    "radiant_arbitrum":  8.0,   # ~8.0% APY Radiant USDC Arbitrum (natively incentivised)
    "morpho_steakhouse": 6.5,   # ~6.5% APY Morpho Steakhouse USDC
}

# Risk scores по протоколам
RISK_SCORES: Dict[str, float] = {
    "aave_arbitrum":     0.22,  # T1, L2 anchor, низкий риск
    "radiant_arbitrum":  0.42,  # T2, Arbitrum-native, bridge + protocol риск
    "morpho_steakhouse": 0.32,  # T1, mainnet vault, средне-низкий риск
}

# Ожидаемый взвешенный APY при дефолтных значениях
# 0.45*4.6 + 0.35*8.0 + 0.20*6.5 = 2.07 + 2.80 + 1.30 = 6.17%
WEIGHTED_APY_EXPECTED: float = 6.17

# Взвешенный Risk Score
# 0.45*0.22 + 0.35*0.42 + 0.20*0.32 = 0.099 + 0.147 + 0.064 = 0.31
RISK_BLENDED: float = 0.31

# Порог нормализации APY для Radiant (incentive спайки выше → нормализуются)
RADIANT_SPIKE_THRESHOLD: float = 20.0
RADIANT_APY_NORMALIZED:  float = 12.0

# L2 gas параметры (Arbitrum)
GAS_MAINNET_USD:   float = 0.10   # типичный газ на Ethereum mainnet
GAS_L2_USD:        float = 0.01   # типичный газ на Arbitrum
GAS_ADVANTAGE_USD: float = 0.09   # экономия за транзакцию

# Порог bridge-риска: если L2 аллокация превышает — добавляем флаг
L2_BRIDGE_RISK_THRESHOLD: float = 0.70   # 70% капитала на L2 → bridge_risk flag

# Доля капитала на L2 (Aave Arb + Radiant Arb)
L2_ALLOCATION_TOTAL: float = (
    ALLOCATION["aave_arbitrum"] + ALLOCATION["radiant_arbitrum"]
)  # 0.45 + 0.35 = 0.80

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 5.5
TARGET_APY_MAX: float = 8.5

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── S14ArbitrumRadiantMax ────────────────────────────────────────────────────

class S14ArbitrumRadiantMax:
    """S14 — Arbitrum-dominant стратегия: Aave Arb + Radiant + Morpho.

    Аллокация: 45% Aave V3 Arbitrum (T1, ~4.6% APY),
               35% Radiant USDC Arbitrum (T2, ~8.0% APY, spike normalization >20%→12%),
               20% Morpho Steakhouse USDC (T1, ~6.5% APY).
    Взвешенный APY ≈ 6.17%, Blended Risk ≈ 0.31.
    L2 аллокация: 80% (Arbitrum) — максимальная из T1+T2 стратегий.

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
            0.45 * aave_arbitrum_apy + 0.35 * radiant_apy + 0.20 * morpho_apy

        При дефолтных APY:
            0.45*4.6 + 0.35*8.0 + 0.20*6.5 = 2.07 + 2.80 + 1.30 = 6.17%

        Radiant: если APY > RADIANT_SPIKE_THRESHOLD (20%),
        нормализуется до RADIANT_APY_NORMALIZED (12%) перед расчётом.

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
            # Нормализация Radiant: incentive спайки >20% → 12%
            if protocol == "radiant_arbitrum" and apy > RADIANT_SPIKE_THRESHOLD:
                apy = RADIANT_APY_NORMALIZED
            result += weight * apy
        return result

    def simulate_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулировать один день — начислить дневной yield на позиции.

        Для каждой позиции начисляется дневной yield по формуле:
            daily_yield = position_usd * apy_pct / 100 / 365

        При отсутствии протокола в apy_map используется FALLBACK_APY.
        Radiant: APY > 20% нормализуется до 12%.
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
                l2_allocation_pct: доля L2 в портфеле (%)
        """
        daily_yield_total = 0.0

        for protocol in list(self._positions.keys()):
            apy_pct = apy_map.get(protocol, FALLBACK_APY.get(protocol, 0.0))
            # Нормализация Radiant
            if protocol == "radiant_arbitrum" and apy_pct > RADIANT_SPIKE_THRESHOLD:
                apy_pct = RADIANT_APY_NORMALIZED

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

        # Вычисляем weighted_apy и L2 долю для текущего снимка
        w_apy     = self.compute_weighted_apy(apy_map)
        l2_alloc  = self.get_l2_allocation_pct()

        # Добавляем точку в кольцевой буфер
        self._equity_history.append({
            "day":                self._days_simulated,
            "equity":             round(self.current_equity, 6),
            "daily_yield_usd":    round(daily_yield_total, 6),
            "weighted_apy":       round(w_apy, 4),
            "l2_allocation_pct":  round(l2_alloc, 2),
        })
        # Поддерживаем размер буфера не более _EQUITY_HISTORY_MAX
        if len(self._equity_history) > _EQUITY_HISTORY_MAX:
            self._equity_history = self._equity_history[-_EQUITY_HISTORY_MAX:]

        return {
            "daily_yield_usd":    daily_yield_total,
            "cumulative_pnl":     self._total_yield_usd,
            "positions":          dict(self._positions),
            "weighted_apy":       w_apy,
            "l2_allocation_pct":  l2_alloc,
        }

    @property
    def current_equity(self) -> float:
        """Текущая совокупная стоимость позиций (USD)."""
        return sum(self._positions.values())

    def get_l2_allocation_pct(self) -> float:
        """Доля портфеля, аллоцированная на Arbitrum L2 (%).

        Считает сумму позиций aave_arbitrum + radiant_arbitrum
        относительно текущей equity.

        Returns:
            Процент L2-аллокации (0..100). 0.0 если equity = 0.
        """
        equity = self.current_equity
        if equity <= 0.0:
            return 0.0
        l2_usd = (
            self._positions.get("aave_arbitrum", 0.0)
            + self._positions.get("radiant_arbitrum", 0.0)
        )
        return l2_usd / equity * 100.0

    def get_gas_savings_estimate(self, n_txs: int = 1) -> float:
        """Оценка экономии на газе за n_txs транзакций vs mainnet (USD).

        Формула:
            savings = n_txs * GAS_ADVANTAGE_USD ($0.09/tx)

        Args:
            n_txs: количество транзакций (дефолт: 1). При n_txs ≤ 0 возвращает 0.

        Returns:
            Экономия газа в USD.
        """
        if n_txs <= 0:
            return 0.0
        return float(n_txs) * GAS_ADVANTAGE_USD

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
            # S14-специфичные поля
            "tier":                 self.tier,
            "allocation":           dict(ALLOCATION),
            "apy":                  WEIGHTED_APY_EXPECTED,
            "risk_blended":         RISK_BLENDED,
            "risk_flags":           self.get_risk_flags(),
            "l2_allocation_pct":    round(self.get_l2_allocation_pct(), 2),
            "description":          DESCRIPTION,
        }

    def get_risk_flags(self) -> List[str]:
        """Возвращает список флагов риска для стратегии.

        Базовые флаги всегда присутствуют:
          - 'radiant_spike_normalization': Radiant APY > 20% нормализуется до 12%
          - 'l2_bridge_exposure': стратегия использует Arbitrum L2 (bridge риск)

        Динамический флаг при L2 аллокации > L2_BRIDGE_RISK_THRESHOLD (70%):
          - 'l2_bridge_risk': >70% капитала на L2 — повышенный bridge риск

        Returns:
            Список строковых флагов риска.
        """
        flags: List[str] = [
            "radiant_spike_normalization",
            "l2_bridge_exposure",
        ]
        l2_fraction = (
            ALLOCATION.get("aave_arbitrum", 0.0)
            + ALLOCATION.get("radiant_arbitrum", 0.0)
        )
        if l2_fraction > L2_BRIDGE_RISK_THRESHOLD:
            flags.append("l2_bridge_risk")
        return flags

    def get_stats(self) -> Dict:
        """Summary метрики стратегии.

        Returns:
            dict со summary: strategy_id, name, tier, capital, equity,
            days_simulated, total_yield_usd, weighted_apy, risk_blended,
            risk_scores, allocation, l2_allocation_pct, gas_savings_per_tx
        """
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            "strategy_id":            self.strategy_id,
            "strategy_name":          self.strategy_name,
            "tier":                   self.tier,
            "description":            DESCRIPTION,
            "capital_usd":            self.capital,
            "current_equity":         round(self.current_equity, 6),
            "days_simulated":         self._days_simulated,
            "total_yield_usd":        round(self._total_yield_usd, 6),
            "total_return_pct":       round(total_return_pct, 4),
            "weighted_apy_expected":  WEIGHTED_APY_EXPECTED,
            "risk_blended":           RISK_BLENDED,
            "risk_scores":            dict(RISK_SCORES),
            "risk_flags":             self.get_risk_flags(),
            "allocation":             dict(ALLOCATION),
            "fallback_apy":           dict(FALLBACK_APY),
            "l2_allocation_pct":      round(self.get_l2_allocation_pct(), 2),
            "gas_savings_per_tx_usd": GAS_ADVANTAGE_USD,
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S14 Arbitrum Radiant Max в глобальном REGISTRY.

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
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Arbitrum-dominant strategy: "
                "Aave V3 Arbitrum 45% (T1, Risk 0.22, ~4.6% APY, L2 anchor), "
                "Radiant USDC Arbitrum 35% (T2, Risk 0.42, ~8.0% APY, spike normalization >20%→12%), "
                "Morpho Steakhouse USDC 20% (T1, Risk 0.32, ~6.5% APY, mainnet backstop). "
                "Weighted APY ≈ 6.17%, Blended Risk ≈ 0.31. L2 allocation: 80%."
            ),
            module="spa_core.strategies.s14_arbitrum_radiant",
            handler_class="S14ArbitrumRadiantMax",
            tags=["arbitrum", "radiant", "l2", "aave", "morpho", "t1", "t2",
                  "multi_chain", "gas_efficient", "s14"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S14ArbitrumRadiantMax auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
