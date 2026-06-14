"""
Strategy S8 — Delta-Neutral sUSDe Funding Harvest
==================================================

Risk Tier : T2  (умеренный риск; только bull market; cap 20%)
Type      : delta_neutral
Target APY: 13–24% (bull) / 0% (bear — inactive)
Max DD    : ~0% (по дизайну delta-neutral)

Механика (LEVERAGE_STRATEGIES.md §1):
  Long sUSDe (earns staking yield = stETH yield + ETH perp funding) +
  Short USDC perpetual (earns additional funding rate) =
  delta-neutral позиция, захватывающая funding spread.

  sUSDe yield = stETH staking yield (~4%) + ETH perp short funding rate
  Bull market (funding > 0):  sUSDe APY = 15–25%
  Bear market (funding < 0):  стратегия неактивна → 0% loss, 0% gain
  Neutral (APY < gate):       стратегия неактивна → капитал → T1 safe harbor

  Добавочный слой SPA — Basis Trade Overlay:
    Поверх sUSDe открывается SHORT ETH perp (GMX v2 / Gains / Vertex).
    Когда рынок в contango → long pays short → SPA получает funding.
    Net ETH delta = 0.0 (sUSDe already hedged via Ethena + GMX short).

Gate conditions (ВСЕ AND):
  - sUSDe APY ≥ 12% (strong staking yield)
  - funding_rate_annual ≥ 0% (perp premium, not discount)
  - market_regime = "bull"

P&L (LEVERAGE_STRATEGIES.md §1.2):
  Bull:        sUSDe 22% + GMX funding 3% - gas/friction 1% = 24% net
  Base:        sUSDe 15% + GMX funding 1% - gas/friction 1% = 15% net
  Bear:        strategy inactive → 0% for S8 position

Риски:
  - Ethena smart contract: cap 20% портфеля
  - sUSDe depeg: auto-exit при 0.5% deviation
  - Funding turns negative: immediate deactivation → T1 rotation
  - Counterparty (GMX): hedge position only, not main capital

Ограничения:
  - Max 20% от общего капитала (per LEVERAGE_STRATEGIES.md)
  - Pure paper simulation — все операции виртуальные
  - LLM FORBIDDEN в execution/risk — этот модуль ADVISORY ONLY
  - Stdlib только: нет внешних зависимостей

Usage:
    from spa_core.strategies.delta_neutral_susde import DeltaNeutralSUSDeStrategy

    s = DeltaNeutralSUSDeStrategy(capital=100_000)
    if s.is_active(susde_apy=0.18, funding_rate_annual=0.12):
        net = s.net_yield(susde_apy=0.18, funding_rate_annual=0.12)
        result = s.simulate_day(0.18, 0.12, "bull")
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID = "s8_delta_neutral_susde"
STRATEGY_VERSION = "1.0"

# Gate thresholds (fraction form: 0.12 = 12%)
SUSDE_APY_GATE: float = 0.12           # sUSDe APY ≥ 12% required
FUNDING_RATE_GATE: float = 0.0         # funding ≥ 0% required

# Cost model
PERP_BORROW_RATE_DEFAULT: float = 0.02    # 2%/year default perp margin cost
EXECUTION_FRICTION: float = 0.005         # 0.5%/year gas + slippage proxy
TOTAL_COST_DEFAULT: float = PERP_BORROW_RATE_DEFAULT + EXECUTION_FRICTION  # 2.5%/year

# Position limits
MAX_CAPITAL_PCT: float = 0.20          # max 20% of portfolio in S8
MIN_CAPITAL_USD: float = 10_000.0      # minimum viable position size

# Allocations (within S8 position): 50% spot sUSDe, 50% notional short hedge
INTERNAL_ALLOC_SUSDE: float = 0.50
INTERNAL_ALLOC_PERP: float = 0.50

# Scenario synthetic data parameters (fraction form)
_SCENARIOS = {
    "bull_2024": {
        "susde_apy_mean": 0.18,
        "susde_apy_std": 0.02,
        "funding_rate_mean": 0.12,
        "funding_rate_std": 0.04,
        "regime": "bull",
        "description": "ETH bull 2024: avg sUSDe 18% + avg funding 12% = 30% gross",
    },
    "base_case": {
        "susde_apy_mean": 0.15,
        "susde_apy_std": 0.02,
        "funding_rate_mean": 0.03,
        "funding_rate_std": 0.02,
        "regime": "bull",
        "description": "Base case: sUSDe 15% + funding 3% = 18% gross",
    },
    "neutral_sideways": {
        "susde_apy_mean": 0.08,
        "susde_apy_std": 0.01,
        "funding_rate_mean": 0.03,
        "funding_rate_std": 0.01,
        "regime": "neutral",
        "description": "Neutral: sUSDe 8% below gate → strategy inactive",
    },
    "bear_2022": {
        "susde_apy_mean": 0.05,
        "susde_apy_std": 0.01,
        "funding_rate_mean": -0.06,
        "funding_rate_std": 0.02,
        "regime": "bear",
        "description": "Bear 2022: funding negative → strategy inactive → 0% loss",
    },
}

# Risk metrics constants
_COUNTERPARTY_RISK_LEVELS = {"low", "medium", "high"}
_LIQUIDITY_LEVELS = {"low", "medium", "high"}


# ─── VPortfolio-совместимый формат ────────────────────────────────────────────

@dataclass
class VPortfolioEntry:
    """Описание S8 позиции в VPortfolio-совместимом формате."""
    strategy_id: str
    protocol_id: str
    allocations: dict
    active: bool
    net_yield_annual: float
    gross_yield_annual: float
    capital_deployed: float
    max_capital_pct: float
    metadata: dict = field(default_factory=dict)


# ─── Основной класс стратегии ──────────────────────────────────────────────────

class DeltaNeutralSUSDeStrategy:
    """
    S8 Delta-Neutral sUSDe Funding Harvest — paper simulation.

    Стратегия захватывает funding spread через delta-neutral позицию:
      - Long sUSDe (earns staking + embedded funding)
      - Short ETH perp (earns additional funding rate)

    Все расчёты ведутся в decimal form (0.12 = 12% APY).

    Attributes:
        capital: total portfolio capital in USD
        max_capital_pct: max fraction of capital allocated to S8 (default 0.20)
        max_capital_usd: absolute cap in USD (max_capital_pct * capital)
    """

    def __init__(
        self,
        capital: float,
        max_capital_pct: float = MAX_CAPITAL_PCT,
        rng_seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            capital: total portfolio USD value
            max_capital_pct: max fraction for S8 strategy (0.20 = 20%)
            rng_seed: optional seed for reproducible scenario simulation
        """
        if capital <= 0:
            raise ValueError(f"capital must be positive, got {capital}")
        if not (0 < max_capital_pct <= 1.0):
            raise ValueError(
                f"max_capital_pct must be in (0, 1], got {max_capital_pct}"
            )

        self.capital: float = float(capital)
        self.max_capital_pct: float = float(max_capital_pct)
        self.max_capital_usd: float = self.capital * self.max_capital_pct
        self._rng: random.Random = random.Random(rng_seed)

        # State tracking
        self._active: bool = False
        self._days_in_bull: int = 0         # consecutive days funding > 0
        self._cumulative_yield_usd: float = 0.0
        self._days_active: int = 0
        self._days_inactive: int = 0

    # ─── Gate / activation ────────────────────────────────────────────────────

    def is_active(
        self,
        susde_apy: float,
        funding_rate_annual: float,
        market_regime: str = "bull",
    ) -> bool:
        """
        Проверить gate conditions для активации стратегии.

        Все условия AND (из LEVERAGE_STRATEGIES.md §1.3 Entry Conditions):
          - sUSDe APY ≥ 12%
          - funding_rate_annual ≥ 0% (perp premium, not discount)
          - market_regime == "bull"

        Args:
            susde_apy: annualised sUSDe APY (decimal: 0.18 = 18%)
            funding_rate_annual: annualised perp funding rate (decimal; can be negative)
            market_regime: "bull" | "bear" | "neutral"

        Returns:
            True если все gate conditions выполнены.
        """
        if market_regime != "bull":
            return False
        if susde_apy < SUSDE_APY_GATE:
            return False
        if funding_rate_annual < FUNDING_RATE_GATE:
            return False
        return True

    def gate_details(
        self,
        susde_apy: float,
        funding_rate_annual: float,
        market_regime: str = "bull",
    ) -> dict:
        """
        Детальный отчёт по gate conditions.

        Returns:
            dict с ключами: active, failed_gates, passed_gates, blockers
        """
        gates = {
            "susde_apy_gate": {
                "required": SUSDE_APY_GATE,
                "actual": susde_apy,
                "passed": susde_apy >= SUSDE_APY_GATE,
            },
            "funding_rate_gate": {
                "required": FUNDING_RATE_GATE,
                "actual": funding_rate_annual,
                "passed": funding_rate_annual >= FUNDING_RATE_GATE,
            },
            "market_regime_gate": {
                "required": "bull",
                "actual": market_regime,
                "passed": market_regime == "bull",
            },
        }
        passed = [k for k, v in gates.items() if v["passed"]]
        failed = [k for k, v in gates.items() if not v["passed"]]
        return {
            "active": len(failed) == 0,
            "gates": gates,
            "passed_gates": passed,
            "failed_gates": failed,
            "blockers": failed,
        }

    # ─── Yield calculations ───────────────────────────────────────────────────

    def gross_yield(
        self,
        susde_apy: float,
        funding_rate_annual: float,
    ) -> float:
        """
        Валовый годовой yield от стратегии (без вычета издержек).

        gross = susde_apy + funding_rate_annual

        Примеры:
          susde_apy=0.18, funding=0.06 → gross=0.24 (24%)
          susde_apy=0.22, funding=0.12 → gross=0.34 (34%)

        Args:
            susde_apy: sUSDe staking + embedded funding APY (decimal)
            funding_rate_annual: GMX/perp short funding rate, annual (decimal)

        Returns:
            gross annual yield as fraction (0.24 = 24%)
        """
        return susde_apy + funding_rate_annual

    def net_yield(
        self,
        susde_apy: float,
        funding_rate_annual: float,
        perp_borrow_rate: float = PERP_BORROW_RATE_DEFAULT,
    ) -> float:
        """
        Чистый годовой yield после вычета стоимости хеджа и исполнения.

        net = gross - perp_borrow_rate - execution_friction
            = susde_apy + funding_rate_annual - perp_borrow_rate - 0.005

        Примеры:
          susde_apy=0.18, funding=0.12, borrow=0.02 → net=0.275 (27.5%)
          susde_apy=0.22, funding=0.06, borrow=0.02 → net=0.255 (25.5%)

        Args:
            susde_apy: sUSDe APY (decimal)
            funding_rate_annual: perp funding rate, annual (decimal)
            perp_borrow_rate: cost of perp margin/borrow (decimal, default 0.02)

        Returns:
            net annual yield as fraction; can be negative in extreme bear.
        """
        gross = self.gross_yield(susde_apy, funding_rate_annual)
        return gross - perp_borrow_rate - EXECUTION_FRICTION

    def daily_yield_usd(
        self,
        susde_apy: float,
        funding_rate_annual: float,
        perp_borrow_rate: float = PERP_BORROW_RATE_DEFAULT,
        capital_deployed: Optional[float] = None,
    ) -> float:
        """
        Дневной yield в USD.

        Args:
            capital_deployed: USD в стратегии (None → max_capital_usd)
        """
        cap = capital_deployed if capital_deployed is not None else self.max_capital_usd
        net = self.net_yield(susde_apy, funding_rate_annual, perp_borrow_rate)
        return cap * net / 365.0

    # ─── simulate_day ─────────────────────────────────────────────────────────

    def simulate_day(
        self,
        susde_apy: float,
        funding_rate_annual: float,
        market_regime: str,
        perp_borrow_rate: float = PERP_BORROW_RATE_DEFAULT,
        capital_deployed: Optional[float] = None,
    ) -> dict:
        """
        Симуляция одного торгового дня.

        При bear (funding < 0) или neutral (APY < gate):
          - no positions → daily_return_pct = 0.0, yield_usd = 0.0
          - NOT теряем деньги (delta-neutral design)
          - capital ротируется в T1 safe harbor (вне этого модуля)

        При bull (все gate conditions met):
          - accrue daily yield = net_yield / 365
          - return positive daily_return_pct

        Args:
            susde_apy: current sUSDe APY (decimal)
            funding_rate_annual: current annualised funding rate (decimal)
            market_regime: "bull" | "bear" | "neutral"
            perp_borrow_rate: perp margin cost (decimal, default 0.02)
            capital_deployed: USD deployed; None → max_capital_usd

        Returns:
            dict: {
                active, daily_return_pct, yield_usd,
                gross_yield_annual, net_yield_annual,
                capital_deployed, market_regime,
                gate_passed, reason
            }
        """
        cap = capital_deployed if capital_deployed is not None else self.max_capital_usd
        active = self.is_active(susde_apy, funding_rate_annual, market_regime)

        if active:
            net = self.net_yield(susde_apy, funding_rate_annual, perp_borrow_rate)
            gross = self.gross_yield(susde_apy, funding_rate_annual)
            daily_return_pct = net / 365.0
            yield_usd = cap * daily_return_pct
            self._cumulative_yield_usd += yield_usd
            self._days_active += 1
            self._active = True
            reason = "all_gates_passed"
        else:
            net = 0.0
            gross = 0.0
            daily_return_pct = 0.0
            yield_usd = 0.0
            self._days_inactive += 1
            self._active = False
            # Determine reason
            if market_regime == "bear":
                reason = "bear_market_inactive"
            elif funding_rate_annual < FUNDING_RATE_GATE:
                reason = "funding_negative_inactive"
            elif susde_apy < SUSDE_APY_GATE:
                reason = "susde_apy_below_gate"
            else:
                reason = "neutral_inactive"

        return {
            "active": active,
            "daily_return_pct": daily_return_pct,
            "yield_usd": yield_usd,
            "gross_yield_annual": gross,
            "net_yield_annual": net,
            "capital_deployed": cap,
            "market_regime": market_regime,
            "gate_passed": active,
            "reason": reason,
            "susde_apy": susde_apy,
            "funding_rate_annual": funding_rate_annual,
            "perp_borrow_rate": perp_borrow_rate,
        }

    # ─── simulate_historical_scenario ─────────────────────────────────────────

    def simulate_historical_scenario(
        self,
        days: int,
        scenario: str,
        perp_borrow_rate: float = PERP_BORROW_RATE_DEFAULT,
        capital_deployed: Optional[float] = None,
    ) -> dict:
        """
        Симуляция исторического сценария за N дней.

        Генерирует синтетические дневные APY/funding данные по нормальному
        распределению с параметрами каждого сценария. Детерминирован при
        rng_seed != None.

        Сценарии (LEVERAGE_STRATEGIES.md + реальные данные):
          "bull_2024":       ETH bull 2024, avg sUSDe 18% + funding 12% = 30% gross
          "base_case":       Умеренный бычий, sUSDe 15% + funding 3%
          "neutral_sideways": Нейтральный, sUSDe 8% ниже gate → inactive
          "bear_2022":       Bear 2022, funding отрицательный → inactive → 0% потерь

        Args:
            days: количество симулируемых дней
            scenario: ключ сценария (см. выше)
            perp_borrow_rate: стоимость перп-маржи
            capital_deployed: USD в позиции; None → max_capital_usd

        Returns:
            dict: {
                scenario, days, description,
                active_days, inactive_days, active_pct,
                total_yield_usd, total_return_pct,
                annualized_return_pct, net_yield_on_active_days,
                avg_susde_apy, avg_funding_rate, avg_net_yield,
                daily_returns, max_daily_yield, min_daily_yield,
                max_drawdown_pct, sharpe_estimate,
                gate_trigger_counts, risk_metrics
            }
        """
        if days <= 0:
            raise ValueError(f"days must be positive, got {days}")
        if scenario not in _SCENARIOS:
            valid = list(_SCENARIOS.keys())
            raise ValueError(
                f"Unknown scenario '{scenario}'. Valid: {valid}"
            )

        cap = capital_deployed if capital_deployed is not None else self.max_capital_usd
        params = _SCENARIOS[scenario]
        regime = params["regime"]

        daily_returns: list[float] = []
        susde_apys: list[float] = []
        funding_rates: list[float] = []
        active_days = 0
        inactive_days = 0
        total_yield_usd = 0.0
        gate_triggers: dict[str, int] = {
            "bear_market_inactive": 0,
            "funding_negative_inactive": 0,
            "susde_apy_below_gate": 0,
            "neutral_inactive": 0,
        }

        for _ in range(days):
            # Synthetic daily APY (clipped to realistic bounds)
            susde = self._rng.gauss(
                params["susde_apy_mean"],
                params["susde_apy_std"],
            )
            susde = max(0.0, min(0.50, susde))  # 0..50%

            funding = self._rng.gauss(
                params["funding_rate_mean"],
                params["funding_rate_std"],
            )
            funding = max(-0.30, min(0.60, funding))  # -30%..60%

            day_result = self.simulate_day(
                susde_apy=susde,
                funding_rate_annual=funding,
                market_regime=regime,
                perp_borrow_rate=perp_borrow_rate,
                capital_deployed=cap,
            )

            daily_returns.append(day_result["daily_return_pct"])
            susde_apys.append(susde)
            funding_rates.append(funding)
            total_yield_usd += day_result["yield_usd"]

            if day_result["active"]:
                active_days += 1
            else:
                inactive_days += 1
                reason = day_result["reason"]
                if reason in gate_triggers:
                    gate_triggers[reason] += 1

        # Aggregates
        active_pct = active_days / days if days > 0 else 0.0
        avg_susde = sum(susde_apys) / len(susde_apys) if susde_apys else 0.0
        avg_funding = sum(funding_rates) / len(funding_rates) if funding_rates else 0.0

        total_return_pct = sum(daily_returns)
        annualized_return_pct = total_return_pct * (365.0 / days) if days > 0 else 0.0

        # Net yield on active days only
        active_returns = [r for r in daily_returns if r > 0]
        net_yield_on_active = (
            (sum(active_returns) / len(active_returns)) * 365.0
            if active_returns
            else 0.0
        )
        avg_net_yield = (
            sum(r * 365.0 for r in daily_returns) / len(daily_returns)
            if daily_returns
            else 0.0
        )

        # Max drawdown (equity curve)
        peak = cap
        equity = cap
        max_dd = 0.0
        for r in daily_returns:
            equity += cap * r
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        # Sharpe estimate (annualized, rf=0)
        if len(daily_returns) > 1:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_r / std_r * math.sqrt(365.0)) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "scenario": scenario,
            "days": days,
            "description": params["description"],
            "regime": regime,
            "active_days": active_days,
            "inactive_days": inactive_days,
            "active_pct": active_pct,
            "total_yield_usd": total_yield_usd,
            "total_return_pct": total_return_pct,
            "annualized_return_pct": annualized_return_pct,
            "net_yield_on_active_days": net_yield_on_active,
            "avg_susde_apy": avg_susde,
            "avg_funding_rate": avg_funding,
            "avg_net_yield": avg_net_yield,
            "daily_returns": daily_returns,
            "max_daily_yield": max(daily_returns) if daily_returns else 0.0,
            "min_daily_yield": min(daily_returns) if daily_returns else 0.0,
            "max_drawdown_pct": max_dd,
            "sharpe_estimate": sharpe,
            "gate_trigger_counts": gate_triggers,
            "risk_metrics": self.risk_metrics(
                avg_net_yield=avg_net_yield,
                scenario=scenario,
            ),
            "capital_deployed": cap,
            "perp_borrow_rate": perp_borrow_rate,
        }

    # ─── VPortfolio format ─────────────────────────────────────────────────────

    def to_vportfolio_format(
        self,
        susde_apy: float = 0.18,
        funding_rate_annual: float = 0.06,
        market_regime: str = "bull",
    ) -> dict:
        """
        Конвертация в VPortfolio-совместимый формат.

        Returns dict совместимый с spa_core/paper_trading/vportfolio.py
        для интеграции в Multi-Strategy Tournament.

        Args:
            susde_apy: текущий sUSDe APY для расчёта yield (decimal)
            funding_rate_annual: текущий funding rate (decimal)
            market_regime: текущий рыночный режим

        Returns:
            dict с полями protocol_id, strategy_id, allocations,
            target_apy_min, target_apy_max, active, etc.
        """
        active = self.is_active(susde_apy, funding_rate_annual, market_regime)
        net = self.net_yield(susde_apy, funding_rate_annual) if active else 0.0
        gross = self.gross_yield(susde_apy, funding_rate_annual) if active else 0.0

        return {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "protocol_id": "susde_delta_neutral",
            "allocations": {
                "susde_spot": INTERNAL_ALLOC_SUSDE,
                "perp_short_hedge": INTERNAL_ALLOC_PERP,
            },
            "target_apy_min": 0.13,
            "target_apy_max": 0.24,
            "capital": self.capital,
            "max_capital_pct": self.max_capital_pct,
            "max_capital_usd": self.max_capital_usd,
            "active": active,
            "net_yield_annual": net,
            "gross_yield_annual": gross,
            "market_regime": market_regime,
            "susde_apy": susde_apy,
            "funding_rate_annual": funding_rate_annual,
            "gate_condition": {
                "susde_apy_min": SUSDE_APY_GATE,
                "funding_rate_min": FUNDING_RATE_GATE,
                "required_regime": "bull",
            },
            "metadata": {
                "strategy_class": "DeltaNeutralSUSDeStrategy",
                "type": "delta_neutral",
                "tier": "T2",
                "description": (
                    "Delta-neutral sUSDe funding harvest: "
                    "long sUSDe (staking yield) + short perp (funding rate). "
                    "Active only in bull market when sUSDe APY >= 12%."
                ),
            },
        }

    # ─── risk_metrics ──────────────────────────────────────────────────────────

    def risk_metrics(
        self,
        avg_net_yield: Optional[float] = None,
        scenario: Optional[str] = None,
    ) -> dict:
        """
        Оценка риск-метрик стратегии S8.

        Метрики основаны на конструкции delta-neutral и исторических данных
        из LEVERAGE_STRATEGIES.md §1.4.

        Args:
            avg_net_yield: средний net yield для расчёта Sharpe (decimal/year)
            scenario: сценарий для контекстного отчёта

        Returns:
            dict: {
                max_drawdown_historical, volatility_profile,
                counterparty_risk, liquidity,
                sharpe_estimate, sortino_estimate,
                key_risks, mitigations
            }
        """
        # Sharpe estimate: высокий в bull (низкая vol, stable income)
        if avg_net_yield is not None and avg_net_yield > 0:
            # Funding rate vol ~ 2-4%/year annualised; assume 3%
            _est_vol = 0.03
            sharpe = avg_net_yield / _est_vol if _est_vol > 0 else 0.0
        elif scenario == "bull_2024":
            sharpe = 3.2
        elif scenario == "base_case":
            sharpe = 2.1
        else:
            sharpe = 0.0

        # Sortino (bear ~= 0 downside → high sortino in bull)
        sortino = sharpe * 1.4 if sharpe > 0 else 0.0

        # Risk probabilities from LEVERAGE_STRATEGIES.md §1.4
        key_risks = [
            {
                "risk": "Ethena smart contract exploit",
                "probability_annual_pct": 4.0,
                "magnitude": "Full position loss",
                "mitigation": "Cap 20% portfolio; monitor Ethena governance",
            },
            {
                "risk": "sUSDe temporary depeg (< 24h)",
                "probability_annual_pct": 12.0,
                "magnitude": "–0.5% to –3%",
                "mitigation": "Auto-exit at 0.5% depeg; Chainlink oracle",
            },
            {
                "risk": "sUSDe severe depeg (bank run)",
                "probability_annual_pct": 1.5,
                "magnitude": "–10% to –30%",
                "mitigation": "$500M TVL floor; exit at first signal",
            },
            {
                "risk": "Funding turns negative (bear market)",
                "probability_annual_pct": 50.0,
                "magnitude": "Strategy deactivates → 0% S8 return",
                "mitigation": "Immediate deactivation; rotate to T1",
            },
            {
                "risk": "GMX perp liquidation on hedge",
                "probability_annual_pct": 1.0,
                "magnitude": "–margin only (up to –$3K per $30K)",
                "mitigation": "10× leverage max; 4h monitoring",
            },
            {
                "risk": "GMX / perp smart contract",
                "probability_annual_pct": 2.5,
                "magnitude": "Hedge position only (not main capital)",
                "mitigation": "Hedge position only, not main capital",
            },
        ]

        return {
            "max_drawdown_historical_pct": 0.0,  # delta-neutral by design
            "expected_drawdown_bear_pct": 0.0,   # inactive in bear → no loss
            "volatility_profile": "low",
            "volatility_driver": "funding_rate_fluctuation",
            "counterparty_risk": "medium",
            "counterparty_risk_note": "Centralized perp (GMX/Gains) + Ethena protocol",
            "liquidity": "high",
            "liquidity_note": "sUSDe ERC-4626 liquid; perp position size small",
            "sharpe_estimate": round(sharpe, 2),
            "sortino_estimate": round(sortino, 2),
            "max_apy_bull_pct": 32.0,
            "min_apy_bear_pct": 0.0,
            "break_even_susde_apy_pct": 3.0,
            "key_risks": key_risks,
            "strategy_id": STRATEGY_ID,
            "scenario": scenario or "general",
        }

    # ─── Convenience helpers ───────────────────────────────────────────────────

    def position_sizing(
        self,
        spread_net: float,
        funding_threshold_full: float = 0.15,
        funding_threshold_reduced: float = 0.10,
        funding_threshold_hold: float = 0.06,
    ) -> dict:
        """
        Размер позиции по матрице порогов (LEVERAGE_STRATEGIES.md §1.3).

        Args:
            spread_net: net spread = sUSDe APY + GMX funding - total_costs (decimal)
            funding_threshold_full: порог для полной позиции (default 0.15 = 15%)
            funding_threshold_reduced: порог для уменьшенной позиции (0.10)
            funding_threshold_hold: порог для удержания без добавления (0.06)

        Returns:
            dict: {action, capital_pct, capital_usd, threshold_used}
        """
        if spread_net >= funding_threshold_full:
            action = "full_position"
            capital_pct = self.max_capital_pct
        elif spread_net >= funding_threshold_reduced:
            action = "reduced_position"
            capital_pct = self.max_capital_pct * 0.65  # ~15-20K on $30K allocation
        elif spread_net >= funding_threshold_hold:
            action = "hold_no_add"
            capital_pct = self.max_capital_pct * 0.50
        elif spread_net < 0:
            action = "immediate_exit"
            capital_pct = 0.0
        else:
            action = "wind_down_24h"
            capital_pct = 0.0

        return {
            "action": action,
            "capital_pct": capital_pct,
            "capital_usd": self.capital * capital_pct,
            "spread_net": spread_net,
            "threshold_used": (
                funding_threshold_full if spread_net >= funding_threshold_full
                else funding_threshold_reduced if spread_net >= funding_threshold_reduced
                else funding_threshold_hold if spread_net >= funding_threshold_hold
                else 0.0
            ),
        }

    def check_exit_conditions(
        self,
        susde_apy: float,
        funding_negative_days: int = 0,
        susde_depeg_pct: float = 0.0,
        portfolio_drawdown_pct: float = 0.0,
        spread_net: float = 1.0,
    ) -> dict:
        """
        Проверка exit conditions (OR — любое выполнено → закрыть позицию).

        Exit triggers из LEVERAGE_STRATEGIES.md §1.3:
          - sUSDe 48h APY < 8%
          - GMX funding negative 3+ days
          - sUSDe depeg > 0.5%
          - Portfolio drawdown >= 5% (SPA kill-switch)
          - Net spread < 6%

        Args:
            susde_apy: текущий sUSDe APY (decimal)
            funding_negative_days: consecutive days funding was negative
            susde_depeg_pct: abs(sUSDe price - 1.0) in decimal (0.005 = 0.5%)
            portfolio_drawdown_pct: portfolio drawdown (decimal)
            spread_net: net spread sUSDe + funding - costs (decimal)

        Returns:
            dict: {should_exit, triggered_conditions, details}
        """
        conditions = {
            "susde_apy_below_8pct": susde_apy < 0.08,
            "funding_negative_3days": funding_negative_days >= 3,
            "susde_depeg_above_50bps": susde_depeg_pct > 0.005,
            "portfolio_drawdown_5pct": portfolio_drawdown_pct >= 0.05,
            "spread_below_6pct": spread_net < 0.06,
        }
        triggered = [k for k, v in conditions.items() if v]
        return {
            "should_exit": len(triggered) > 0,
            "triggered_conditions": triggered,
            "details": conditions,
            "priority": "HIGH" if triggered else "NONE",
        }

    def reset_state(self) -> None:
        """Сброс внутреннего состояния для новой симуляции."""
        self._active = False
        self._days_in_bull = 0
        self._cumulative_yield_usd = 0.0
        self._days_active = 0
        self._days_inactive = 0
        self._rng = random.Random(None)

    # ─── dunder ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"DeltaNeutralSUSDeStrategy("
            f"capital={self.capital:,.0f}, "
            f"max_pct={self.max_capital_pct:.0%}, "
            f"max_usd={self.max_capital_usd:,.0f})"
        )


# ─── Регистрация в strategies/strategy_registry.py ────────────────────────────
# Импорт trigger side-effect: REGISTRY.register(S8_META)

def _register_s8() -> None:
    """Регистрация S8 в глобальном StrategyRegistry (advisory)."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta, VALID_TYPES
        # Extend VALID_TYPES with delta_neutral if needed
        if "delta_neutral" not in VALID_TYPES:
            VALID_TYPES.add("delta_neutral")
        s8_meta = StrategyMeta(
            id=STRATEGY_ID,
            name="Delta-Neutral sUSDe Funding Harvest",
            type="delta_neutral",
            risk_tier="T2",
            target_apy_min=0.0,   # 0% in bear (inactive)
            target_apy_max=24.0,  # 24% in bull
            max_drawdown_pct=2.0,
            description=(
                "S8: Delta-neutral sUSDe funding harvest. "
                "Long sUSDe (staking yield) + Short ETH perp (funding rate). "
                "Active only in bull market: sUSDe APY >= 12% AND funding >= 0%. "
                "Max 20% portfolio cap."
            ),
            module="spa_core.strategies.delta_neutral_susde",
            handler_class="DeltaNeutralSUSDeStrategy",
            tags=["delta_neutral", "funding_harvest", "susde", "bull_only", "paper"],
            enabled=True,
        )
        REGISTRY.register(s8_meta)
    except Exception:
        pass  # Advisory only — registry failure must not break imports


_register_s8()
