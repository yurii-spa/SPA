"""
spa_core/strategies/s5_pendle_enhanced.py — MP-396 S5 Pendle PT Enhanced

Агрессивная fixed-rate стратегия с максимальной долей Pendle PT.
Заполняет нишу между S2 (7.0%) и S8 (27.5% delta-neutral) — Pendle без рычага.

Аллокация:
  - Pendle PT USDC:         65% (10.0% fixed APY, T1, REST-only)
  - Morpho Steakhouse USDC: 25% (6.5%  APY, T1)
  - Compound V3 USDC:       10% (4.8%  APY, T1)

Weighted APY:
  0.65*10.0 + 0.25*6.5 + 0.10*4.8 = 6.5 + 1.625 + 0.48 = 8.605% ≈ 8.5%

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

STRATEGY_ID   = "S5"
STRATEGY_NAME = "Pendle PT Enhanced"
TIER_LIMIT    = "T1_ONLY"   # Pendle PT = T1, Morpho = T1, Compound = T1

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "pendle_pt":         0.65,   # T1, Pendle PT USDC — maximum fixed-rate
    "morpho_steakhouse": 0.25,   # T1, Morpho Steakhouse USDC vault — backstop
    "compound_v3":       0.10,   # T1, Compound V3 Comet USDC — ликвидность
}

# Целевой APY (%)
APY_TARGET_PCT: float = 8.5

# Минимальный Pendle APY — ниже этого порога стратегия не eligible
MIN_PENDLE_APY_PCT: float = 6.0

# Риск-скор стратегии (0..1): выше S1 (0.25), ниже S8 (0.60)
RISK_SCORE: float = 0.42

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Дефолтные годовые APY (%) — fallback при отсутствии данных в apy_map
FALLBACK_APY: Dict[str, float] = {
    "pendle_pt":         10.0,   # ~10.0% fixed APY Pendle PT USDC
    "morpho_steakhouse":  6.5,   # ~6.5%  APY Morpho Steakhouse USDC
    "compound_v3":        4.8,   # ~4.8%  APY Compound V3 Comet USDC
}

# Ожидаемый взвешенный APY при дефолтных значениях
WEIGHTED_APY_EXPECTED: float = 8.605  # 0.65*10.0 + 0.25*6.5 + 0.10*4.8

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 7.5
TARGET_APY_MAX: float = 12.0

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── S5PendleEnhanced ─────────────────────────────────────────────────────────

class S5PendleEnhanced:
    """S5 — Pendle PT Enhanced стратегия.

    Максимальная доля Pendle PT: 65% (T1, ~10.0% APY),
    25% Morpho Steakhouse USDC (T1, ~6.5% APY) — backstop,
    10% Compound V3 USDC (T1, ~4.8% APY) — ликвидность.
    Взвешенный APY ≈ 8.5% (target), ~8.605% (weighted).

    Совместима с VPortfolio через to_vportfolio_format().
    Stdlib only, без внешних зависимостей.
    """

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100K).
        """
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME
        self.tier          = TIER_LIMIT
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
            0.65 * pendle_apy + 0.25 * morpho_apy + 0.10 * compound_apy

        При pendle_pt APY < MIN_PENDLE_APY_PCT (6.0%) — Pendle не включается
        в расчёт (вклад = 0.0), стратегия переходит в S1-подобный режим
        (только Morpho + Compound с их весами; Pendle-вес даёт 0).

        При отсутствии ключа в apy_map — ключ пропускается (вклад = 0.0).
        Пустой apy_map → 0.0.

        Args:
            apy_map: {protocol_key: annual_apy_pct}

        Returns:
            weighted_apy_pct — взвешенный APY в процентах годовых (≥ 0.0)
        """
        result = 0.0
        for protocol, weight in ALLOCATION.items():
            if protocol not in apy_map:
                continue
            apy = apy_map[protocol]
            # Pendle блокируется ниже минимального порога
            if protocol == "pendle_pt" and apy < MIN_PENDLE_APY_PCT:
                continue
            result += weight * apy
        return result

    def simulate_day(
        self,
        apy_map: Dict[str, float],
        capital: float = 100_000.0,
    ) -> Dict:
        """Симулировать один день — дневной P&L на заданный капитал.

        Args:
            apy_map:  {protocol_key: annual_apy_pct}
            capital:  условный капитал для расчёта (не изменяет self.capital)

        Returns:
            dict с ключами:
                strategy_id         : "S5"
                daily_pnl           : дневной P&L в USD
                daily_return_pct    : дневная доходность (% от капитала)
                annual_apy_pct      : годовой APY стратегии
                allocation          : ALLOCATION
                capital             : капитал для расчёта
        """
        annual_apy = self.compute_weighted_apy(apy_map)
        daily_return_pct = annual_apy / 365.0
        daily_pnl = capital * daily_return_pct / 100.0

        # Обновляем внутреннее состояние экземпляра (реинвест)
        for protocol in list(self._positions.keys()):
            apy_pct = apy_map.get(protocol, 0.0)
            if protocol == "pendle_pt" and apy_pct < MIN_PENDLE_APY_PCT:
                apy_pct = 0.0
            if apy_pct <= 0.0:
                continue
            pos_usd = self._positions[protocol]
            yield_day = pos_usd * apy_pct / 100.0 / 365.0
            self._positions[protocol] = pos_usd + yield_day

        self._total_yield_usd += daily_pnl
        self._days_simulated  += 1

        self._equity_history.append({
            "day":           self._days_simulated,
            "equity":        round(self.current_equity, 6),
            "daily_pnl":     round(daily_pnl, 6),
            "annual_apy":    round(annual_apy, 4),
        })
        if len(self._equity_history) > _EQUITY_HISTORY_MAX:
            self._equity_history = self._equity_history[-_EQUITY_HISTORY_MAX:]

        return {
            "strategy_id":       STRATEGY_ID,
            "daily_pnl":         daily_pnl,
            "daily_return_pct":  daily_return_pct,
            "annual_apy_pct":    annual_apy,
            "allocation":        dict(ALLOCATION),
            "capital":           capital,
        }

    def is_eligible(self, apy_map: Dict[str, float]) -> bool:
        """Проверить, eligible ли S5 при текущих рыночных данных.

        Стратегия eligible если pendle_pt APY присутствует в apy_map
        и >= MIN_PENDLE_APY_PCT (6.0%).

        Args:
            apy_map: {protocol_key: annual_apy_pct}

        Returns:
            True если eligible, иначе False
        """
        pendle_apy = apy_map.get("pendle_pt", None)
        if pendle_apy is None:
            return False
        return pendle_apy >= MIN_PENDLE_APY_PCT

    def get_pendle_advantage(self, baseline_apy: float = 3.2) -> float:
        """Преимущество S5 по APY над заданным baseline.

        Args:
            baseline_apy: базовый APY (%) для сравнения (дефолт: S0 Aave 3.2%)

        Returns:
            APY_TARGET_PCT - baseline_apy (может быть отрицательным)
        """
        return APY_TARGET_PCT - baseline_apy

    def to_vportfolio_format(self) -> Dict:
        """Экспортировать в формат, совместимый с VPortfolio.

        Returns:
            dict с полями: id, name, allocation, risk_score,
                           apy_target, tier, + расширенные поля совместимости
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        total_return_pct = (
            (self.current_equity - self.capital) / self.capital * 100.0
            if self.capital > 0 else 0.0
        )
        return {
            # Ключевые поля VPortfolio
            "id":           STRATEGY_ID,
            "name":         STRATEGY_NAME,
            "allocation":   {k: round(v, 6) for k, v in ALLOCATION.items()},
            "risk_score":   round(RISK_SCORE, 6),
            "apy_target":   APY_TARGET_PCT,
            "tier":         TIER_LIMIT,
            # Расширенные поля совместимости
            "strategy_id":       STRATEGY_ID,
            "capital_usd":       round(self.capital, 6),
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
            "total_return_pct":  round(total_return_pct, 6),
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "min_pendle_apy":    MIN_PENDLE_APY_PCT,
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
        }

    def vs_s2_comparison(self, apy_map: Dict[str, float]) -> Dict:
        """Сравнить S5 с S2 (Pendle PT + Morpho Heavy) при текущих APY.

        S2 аллокация: pendle_pt=0.50, morpho_steakhouse=0.35, compound_v3=0.15

        Args:
            apy_map: {protocol_key: annual_apy_pct}

        Returns:
            dict с ключами:
                s5_apy   : взвешенный APY S5
                s2_apy   : взвешенный APY S2 (approx)
                gap_pct  : s5_apy - s2_apy
                winner   : "S5" если gap_pct > 0 иначе "S2"
        """
        s5_apy = self.compute_weighted_apy(apy_map)

        # S2 аллокация: 50% Pendle PT, 35% Morpho, 15% Compound
        s2_pendle = apy_map.get("pendle_pt", 10.0)
        s2_morpho = apy_map.get("morpho_steakhouse", 6.5)
        s2_compound = apy_map.get("compound_v3", 4.8)
        s2_apy = (
            0.50 * s2_pendle
            + 0.35 * s2_morpho
            + 0.15 * s2_compound
        )

        gap = s5_apy - s2_apy
        return {
            "s5_apy":  s5_apy,
            "s2_apy":  s2_apy,
            "gap_pct": gap,
            "winner":  "S5" if gap > 0 else "S2",
        }

    @property
    def current_equity(self) -> float:
        """Текущая совокупная стоимость позиций (USD)."""
        return sum(self._positions.values())

    def get_stats(self) -> Dict:
        """Summary метрики стратегии.

        Returns:
            dict со summary: strategy_id, name, tier, capital, equity,
            days_simulated, total_yield_usd, weighted_apy_expected,
            risk_score, allocation, apy_target, min_pendle_apy
        """
        return {
            "strategy_id":           STRATEGY_ID,
            "strategy_name":         STRATEGY_NAME,
            "tier":                  TIER_LIMIT,
            "capital_usd":           round(self.capital, 6),
            "current_equity":        round(self.current_equity, 6),
            "days_simulated":        self._days_simulated,
            "total_yield_usd":       round(self._total_yield_usd, 6),
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
            "apy_target_pct":        APY_TARGET_PCT,
            "risk_score":            RISK_SCORE,
            "max_drawdown_pct":      MAX_DRAWDOWN_PCT,
            "min_pendle_apy_pct":    MIN_PENDLE_APY_PCT,
            "allocation":            dict(ALLOCATION),
            "fallback_apy":          dict(FALLBACK_APY),
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S5 Pendle PT Enhanced в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Aggressive fixed-rate strategy: Pendle PT USDC 65% (T1, ~10.0%), "
                "Morpho Steakhouse USDC 25% (T1, ~6.5%) backstop, "
                "Compound V3 USDC 10% (T1, ~4.8%) liquidity. "
                "Weighted APY ≈ 8.5% (target) / 8.605% (calculated). "
                "Fills niche between S2 (7.0%) and S8 (27.5% delta-neutral). "
                "Eligible only when Pendle PT APY >= 6.0%."
            ),
            module="spa_core.strategies.s5_pendle_enhanced",
            handler_class="S5PendleEnhanced",
            tags=["pendle", "morpho", "t1", "fixed_rate", "s5", "aggressive"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S5PendleEnhanced auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
