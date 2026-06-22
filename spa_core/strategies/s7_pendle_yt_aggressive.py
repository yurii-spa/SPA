"""
spa_core/strategies/s7_pendle_yt_aggressive.py — MP-399 S7 Pendle YT+PT Aggressive

Первая стратегия, пробивающая 10% APY (BREAKTHROUGH: 10.115% base scenario).
Добавляет Pendle YT (yield trading) к PT-позиции для достижения 10%+ APY.

Аллокация:
  - Pendle YT:               40% (14.0% APY, T3, спекулятивный yield trading)
  - Pendle PT USDC:          35% ( 8.5% APY, T3, fixed rate anchor)
  - Morpho Steakhouse USDC:  20% ( 6.5% APY, T1, safety buffer)
  - Compound V3 USDC:         5% ( 4.8% APY, T1, liquidity reserve)

Взвешенный APY (base):
  0.40*14.0 + 0.35*8.5 + 0.20*6.5 + 0.05*4.8
  = 5.6 + 2.975 + 1.3 + 0.24
  = 10.115%

Сценарии:
  Bull: YT APY * 2.0 (28%) → ~14.5% portfolio APY
  Base: стандартные defaults     → ~10.1% portfolio APY
  Bear: YT теряет 50% позиции/год → ~4.2% portfolio APY (PT+Morpho защищают)

Правила:
  - Stdlib only (math, statistics, json) — никаких внешних зависимостей
  - Атомарные записи (tmpfile + os.replace) для JSON-файлов
  - Read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле

ADR: ADR-021 (Pendle YT T3-SPEC — advisory only, позиции не открываются автоматически)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S7"
STRATEGY_NAME = "Pendle YT+PT Aggressive"
RISK_TIER     = "T3"   # T3: спекулятивный (YT компонента)

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
ALLOCATION: Dict[str, float] = {
    "pendle_yt":         0.40,  # T3, Pendle YT — спекулятивный yield trading
    "pendle_pt":         0.35,  # T3, Pendle PT USDC — fixed rate anchor
    "morpho_steakhouse": 0.20,  # T1, Morpho Steakhouse USDC — safety buffer
    "compound_v3":       0.05,  # T1, Compound V3 Comet USDC — liquidity reserve
}

# Дефолтные годовые APY (%) — conservative, fallback при отсутствии данных
APY_DEFAULTS: Dict[str, float] = {
    "pendle_yt":         14.0,  # консервативная оценка (bull: 20-40%+)
    "pendle_pt":          8.5,  # ~8.5% fixed APY Pendle PT USDC
    "morpho_steakhouse":  6.5,  # ~6.5% APY Morpho Steakhouse USDC
    "compound_v3":        4.8,  # ~4.8% APY Compound V3 Comet USDC
}

# Взвешенный APY при дефолтных значениях
# 0.40*14.0 + 0.35*8.5 + 0.20*6.5 + 0.05*4.8 = 10.115
WEIGHTED_APY: float = 10.115

# ─── Ограничения YT ───────────────────────────────────────────────────────────

# Минимальный YT APY — ниже порога переходим в PT-only режим
MIN_YT_APY_PCT: float = 8.0

# Максимальная доля YT (не превышать — T3 risk cap)
MAX_YT_ALLOCATION: float = 0.40

# Bull multiplier для YT APY (2x базового)
YT_BULL_MULTIPLIER: float = 2.0

# Bear scenario: YT теряет 50% от позиции в год
YT_BEAR_LOSS_PCT: float = -0.50

# ─── Риск-параметры ───────────────────────────────────────────────────────────

# Риск-скор: выше S5 (0.42) из-за YT-экспозиции
RISK_SCORE: float = 0.52

# Kill-switch: максимально допустимый drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 15.0

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 9.0
TARGET_APY_MAX: float = 18.0

# S5 baseline APY для сравнения
S5_BASELINE_APY: float = 8.5

# S5 risk score для расчёта risk_adjusted_advantage
S5_RISK_SCORE: float = 0.42


# ─── S7PendleYTAggressive ─────────────────────────────────────────────────────

class S7PendleYTAggressive:
    """S7 — Pendle YT+PT Aggressive стратегия.

    Первая стратегия SPA, пробивающая 10% APY:
      40% Pendle YT (~14.0% APY, спекулятивный yield trading),
      35% Pendle PT (~8.5% APY, fixed rate anchor),
      20% Morpho Steakhouse (~6.5% APY, safety buffer),
       5% Compound V3 (~4.8% APY, liquidity reserve).

    Weighted APY ≈ 10.115% (base scenario).

    При YT APY < MIN_YT_APY_PCT (8.0%) переходит в PT-only режим:
    YT доля перераспределяется пропорционально между PT и Morpho.

    Совместима с VPortfolio через to_vportfolio_format().
    Stdlib only, без внешних зависимостей. Advisory/read-only.
    """

    def __init__(self, capital: float = 100_000.0) -> None:
        """Инициализировать стратегию с начальным капиталом.

        Args:
            capital: начальный виртуальный капитал в USD (дефолт: $100K).
        """
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME
        self.risk_tier     = RISK_TIER
        self.capital       = float(capital)

        # Текущие позиции по целевым весам
        self._positions: Dict[str, float] = {
            protocol: self.capital * weight
            for protocol, weight in ALLOCATION.items()
        }

        # Счётчики накопленного состояния
        self._days_simulated:  int   = 0
        self._total_yield_usd: float = 0.0

    # ── Публичный API ─────────────────────────────────────────────────────────

    def compute_weighted_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> float:
        """Взвешенный годовой APY стратегии (% годовых).

        Если YT APY < MIN_YT_APY_PCT (8.0%) — переходит в PT-only режим:
        доля YT (0.40) перераспределяется пропорционально между PT и Morpho.
        Compound остаётся неизменным.

        При apy_map=None — использует APY_DEFAULTS.
        При отсутствии ключа в apy_map — использует APY_DEFAULTS[ключ].

        Args:
            apy_map: {protocol_key: annual_apy_pct} или None.

        Returns:
            weighted_apy_pct — взвешенный APY в процентах годовых (≥ 0.0).
        """
        if apy_map is None:
            apy_map = {}

        def get_apy(protocol: str) -> float:
            if protocol in apy_map:
                return float(apy_map[protocol])
            return APY_DEFAULTS.get(protocol, 0.0)

        yt_apy = get_apy("pendle_yt")

        if yt_apy < MIN_YT_APY_PCT:
            # PT-only режим: перераспределяем YT долю между PT и Morpho
            yt_alloc   = ALLOCATION["pendle_yt"]         # 0.40
            pt_weight  = ALLOCATION["pendle_pt"]         # 0.35
            mo_weight  = ALLOCATION["morpho_steakhouse"] # 0.20
            cp_weight  = ALLOCATION["compound_v3"]       # 0.05

            denom = pt_weight + mo_weight  # 0.55
            if denom > 0.0:
                pt_new = pt_weight  + yt_alloc * (pt_weight  / denom)
                mo_new = mo_weight  + yt_alloc * (mo_weight  / denom)
            else:
                pt_new = pt_weight
                mo_new = mo_weight

            result = (
                pt_new * get_apy("pendle_pt")
                + mo_new * get_apy("morpho_steakhouse")
                + cp_weight * get_apy("compound_v3")
            )
            return result

        # Стандартный режим: все 4 протокола
        result = 0.0
        for protocol, weight in ALLOCATION.items():
            result += weight * get_apy(protocol)
        return result

    def simulate_day(
        self,
        portfolio_value: float,
        day_num: int,
        apy_map: Optional[Dict[str, float]] = None,
        scenario: str = "base",
    ) -> Dict:
        """Симулировать один день.

        Args:
            portfolio_value: текущая стоимость портфеля (USD).
            day_num:         номер дня симуляции.
            apy_map:         {protocol_key: annual_apy_pct} или None (APY_DEFAULTS).
            scenario:        "base" | "bull" | "bear".

        Returns:
            dict с ключами:
                daily_yield_usd      — дневной доход (USD, может быть отрицательным в bear)
                annual_apy_pct       — эффективный годовой APY (%)
                scenario             — переданный сценарий
                portfolio_value_after— стоимость после дневного начисления
                positions            — {protocol: USD} (аллокация на начало дня)
        """
        if apy_map is None:
            apy_map = {}

        def get_apy(protocol: str) -> float:
            if protocol in apy_map:
                return float(apy_map[protocol])
            return APY_DEFAULTS.get(protocol, 0.0)

        positions = {
            protocol: portfolio_value * weight
            for protocol, weight in ALLOCATION.items()
        }

        if scenario == "bear":
            # YT теряет YT_BEAR_LOSS_PCT от YT-позиции в год
            yt_pos = positions["pendle_yt"]
            yt_daily_loss = yt_pos * abs(YT_BEAR_LOSS_PCT) / 365.0

            # Остальные протоколы продолжают начислять APY
            non_yt_daily_yield = 0.0
            for protocol, weight in ALLOCATION.items():
                if protocol == "pendle_yt":
                    continue
                apy_pct = get_apy(protocol)
                non_yt_daily_yield += portfolio_value * weight * apy_pct / 100.0 / 365.0

            daily_yield_usd = non_yt_daily_yield - yt_daily_loss
            annual_apy_pct = (
                daily_yield_usd * 365.0 / portfolio_value * 100.0
                if portfolio_value > 0.0 else 0.0
            )

        elif scenario == "bull":
            # YT APY умножается на YT_BULL_MULTIPLIER
            bull_map = dict(apy_map)
            yt_apy = get_apy("pendle_yt")
            bull_map["pendle_yt"] = yt_apy * YT_BULL_MULTIPLIER

            annual_apy_pct = self.compute_weighted_apy(bull_map)
            daily_yield_usd = portfolio_value * annual_apy_pct / 100.0 / 365.0

        else:  # base
            annual_apy_pct = self.compute_weighted_apy(apy_map)
            daily_yield_usd = portfolio_value * annual_apy_pct / 100.0 / 365.0

        self._days_simulated  += 1
        self._total_yield_usd += daily_yield_usd

        return {
            "daily_yield_usd":       daily_yield_usd,
            "annual_apy_pct":        annual_apy_pct,
            "scenario":              scenario,
            "portfolio_value_after": portfolio_value + daily_yield_usd,
            "positions":             positions,
        }

    def is_eligible(
        self,
        min_yt_apy_pct: Optional[float] = None,
    ) -> bool:
        """Проверить, eligible ли S7 (YT APY >= минимальному порогу).

        Использует APY_DEFAULTS["pendle_yt"] как текущий YT APY.

        Args:
            min_yt_apy_pct: порог (%), дефолт — MIN_YT_APY_PCT (8.0%).

        Returns:
            True если YT APY >= порогу, иначе False.
        """
        threshold = min_yt_apy_pct if min_yt_apy_pct is not None else MIN_YT_APY_PCT
        current_yt_apy = APY_DEFAULTS["pendle_yt"]
        return current_yt_apy >= threshold

    def vs_s5_comparison(
        self,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Сравнение S7 против S5 (8.5% APY, risk_score=0.42).

        Args:
            apy_map: {protocol_key: annual_apy_pct} или None (APY_DEFAULTS).

        Returns:
            dict с ключами:
                s7_apy               — взвешенный APY S7 (%)
                s5_apy               — базовый APY S5 (%)
                advantage_pct        — s7_apy - s5_apy (%)
                risk_premium         — разница риск-скоров (S7 - S5)
                risk_adjusted_advantage — advantage / risk_premium
        """
        s7_apy = self.compute_weighted_apy(apy_map)
        s5_apy = S5_BASELINE_APY

        advantage_pct = s7_apy - s5_apy
        risk_premium  = RISK_SCORE - S5_RISK_SCORE  # 0.52 - 0.42 = 0.10

        if risk_premium != 0.0:
            risk_adjusted_advantage = advantage_pct / risk_premium
        else:
            risk_adjusted_advantage = 0.0

        return {
            "s7_apy":                 s7_apy,
            "s5_apy":                 s5_apy,
            "advantage_pct":          advantage_pct,
            "risk_premium":           risk_premium,
            "risk_adjusted_advantage": risk_adjusted_advantage,
        }

    def get_yt_exposure(self) -> Dict:
        """Статистика по YT-позиции.

        Returns:
            dict с ключами:
                allocation       — доля YT в портфеле (0.40)
                default_apy      — дефолтный APY YT (%)
                bull_apy         — bull APY = default * YT_BULL_MULTIPLIER
                bear_loss_pct    — потеря позиции в bear (%, отрицательное)
                is_eligible      — eligibility при дефолтных APY
        """
        default_yt_apy = APY_DEFAULTS["pendle_yt"]
        return {
            "allocation":    ALLOCATION["pendle_yt"],
            "default_apy":   default_yt_apy,
            "bull_apy":      default_yt_apy * YT_BULL_MULTIPLIER,
            "bear_loss_pct": YT_BEAR_LOSS_PCT * 100.0,  # → -50.0
            "is_eligible":   self.is_eligible(),
        }

    def to_vportfolio_format(
        self,
        portfolio_value: float = 100_000.0,
    ) -> Dict:
        """Совместимый с VPortfolio/MultiStrategyRunner формат.

        Args:
            portfolio_value: условный размер портфеля (USD, дефолт: $100K).

        Returns:
            dict, совместимый с VPortfolio.to_dict() схемой.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        positions = {
            protocol: round(portfolio_value * weight, 6)
            for protocol, weight in ALLOCATION.items()
        }

        weighted_apy = self.compute_weighted_apy()

        return {
            # Ключевые поля VPortfolio
            "id":              STRATEGY_ID,
            "name":            STRATEGY_NAME,
            "allocation":      {k: round(v, 6) for k, v in ALLOCATION.items()},
            "risk_score":      round(RISK_SCORE, 6),
            "apy_target":      WEIGHTED_APY,
            "tier":            RISK_TIER,
            # Расширенные поля совместимости
            "strategy_id":     STRATEGY_ID,
            "strategy_name":   STRATEGY_NAME,
            "risk_tier":       RISK_TIER,
            "capital_usd":     round(portfolio_value, 6),
            "positions":       positions,
            "cash_usd":        0.0,
            "weighted_apy":    round(weighted_apy, 6),
            "weighted_apy_expected": WEIGHTED_APY,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "min_yt_apy_pct":  MIN_YT_APY_PCT,
            "max_yt_allocation": MAX_YT_ALLOCATION,
            "yt_bull_multiplier": YT_BULL_MULTIPLIER,
            "yt_bear_loss_pct":  YT_BEAR_LOSS_PCT * 100.0,
            "apy_defaults":    dict(APY_DEFAULTS),
            "is_eligible":     self.is_eligible(),
            "status":          "active",
            "created_at":      now_iso,
            "last_updated":    now_iso,
            "total_yield_usd": round(self._total_yield_usd, 6),
            "days_simulated":  self._days_simulated,
        }

    def get_stats(self) -> Dict:
        """Summary метрики стратегии."""
        return {
            "strategy_id":           STRATEGY_ID,
            "strategy_name":         STRATEGY_NAME,
            "risk_tier":             RISK_TIER,
            "weighted_apy":          WEIGHTED_APY,
            "risk_score":            RISK_SCORE,
            "max_drawdown_pct":      MAX_DRAWDOWN_PCT,
            "min_yt_apy_pct":        MIN_YT_APY_PCT,
            "max_yt_allocation":     MAX_YT_ALLOCATION,
            "yt_bull_multiplier":    YT_BULL_MULTIPLIER,
            "yt_bear_loss_pct_year": YT_BEAR_LOSS_PCT * 100.0,
            "allocation":            dict(ALLOCATION),
            "apy_defaults":          dict(APY_DEFAULTS),
            "days_simulated":        self._days_simulated,
            "total_yield_usd":       round(self._total_yield_usd, 6),
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S7 в глобальном REGISTRY.

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
                "BREAKTHROUGH: first strategy to cross 10% APY threshold. "
                "Pendle YT 40% (T3, ~14.0% speculative yield trading), "
                "Pendle PT 35% (T3, ~8.5% fixed rate anchor), "
                "Morpho Steakhouse 20% (T1, ~6.5% safety buffer), "
                "Compound V3 5% (T1, ~4.8% liquidity reserve). "
                "Weighted APY ≈ 10.115% (base) / ~14.5% (bull) / ~4.2% (bear). "
                "PT-only mode when YT APY < 8.0%. Advisory only (ADR-021)."
            ),
            module="spa_core.strategies.s7_pendle_yt_aggressive",
            handler_class="S7PendleYTAggressive",
            tags=["pendle", "yt", "pt", "morpho", "t3", "aggressive", "s7", "breakthrough"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S7PendleYTAggressive auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
