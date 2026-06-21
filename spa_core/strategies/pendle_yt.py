"""
spa_core/strategies/pendle_yt.py — S10: Pendle YT Speculation Strategy
========================================================================

Strategy S10 — Leveraged yield speculation via Pendle YT (Yield Token) tokens.
Risk Tier : T3  (only paper trading; requires ADR + Owner approval for live)
Type      : yt_speculation
Target APY: 14–42% net (base / bull scenarios)
Max DD    : 30% (full YT premium loss if bear scenario)

YT (Yield Token) Mechanics
===========================
In Pendle Finance a bond is split into:
  PT (Principal Token) — redeems par at maturity
  YT (Yield Token)    — captures ALL yield accrued by the underlying until maturity

YT pricing:
  YT_price ≈ yt_price_pct × notional   (default 25%, i.e. 25 cents per $1 notional)

Because YT captures all accrual but costs only yt_price_pct:
  effective_leverage ≈ YT_LEVERAGE_MULTIPLIER = 3.5x
  (slightly less than 1/0.25 = 4x due to AMM fees and market discount)

Entry gate — 25% cushion above implied yield:
  current_apy > implied_yield_annual × (1 + min_apy_cushion)
  default: current_apy > 0.08 × 1.25 = 0.10  (10%)

P&L formula:
  daily_pnl = (current_apy − implied_yield) × leverage × capital_deployed / 365
  where capital_deployed = capital × max_capital_pct

Gross APY = implied_yield + (current_apy − implied_yield) × leverage
Net APY   = (current_apy − implied_yield) × leverage  (excess × leverage)

Scenario analysis (implied=8%, leverage=3.5, exit at 60% of 182 days = 109 days):
  Bull (apy=20%): gross 50%, net 42%, pnl ≈ 42% × capital × 0.30 × 109/365
  Base (apy=12%): gross 22%, net 14%, pnl ≈ 14% × capital × 0.30 × 109/365
  Bear (apy= 6%): YT → 0, max loss = yt_price_pct × capital_deployed = 25% × 30% × capital

Exit conditions:
  1. days_held ≥ PENDLE_MATURITY_DAYS × exit_at_maturity_pct  (60% of 182d = 109d)
  2. current_apy < implied_yield_annual  (yield below implied → YT worthless)

⚠️  PAPER TRADING ONLY. Requires ADR + Owner approval for live capital.
    LLM_FORBIDDEN: risk / execution / monitoring domains.
    stdlib only — no external dependencies.
    Read-only / advisory — never modifies allocator/risk/execution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ─── Module-level constants ───────────────────────────────────────────────────

#: Standard Pendle maturity window (6 months ≈ 182 days).
PENDLE_MATURITY_DAYS: int = 182

#: Effective YT leverage at yt_price_pct=25%.
#: Slightly less than 1/0.25=4.0 due to AMM fees and market discount.
YT_LEVERAGE_MULTIPLIER: float = 3.5


# ─── Config ───────────────────────────────────────────────────────────────────

@dataclass
class PendleYTConfig:
    """Configuration parameters for the Pendle YT Speculation strategy.

    Attributes:
        max_capital_pct:       Maximum fraction of portfolio capital to deploy (0..1).
        min_apy_cushion:       Required APY margin above implied yield (0..1).
                               Entry is gated unless current_apy > implied × (1 + cushion).
        implied_yield_annual:  Market-implied annual yield embedded in the PT price (0..1).
                               Represents the "cost" of the YT position (break-even).
        yt_price_pct:          Cost of YT as a fraction of notional (0..1).
                               Default 0.25 → YT costs 25 cents per $1 of notional exposure.
        exit_at_maturity_pct:  Fraction of maturity at which to exit early (0..1).
                               Default 0.60 → exit at day 109 of 182 (60%).
    """
    max_capital_pct: float = 0.30        # max 30% of portfolio
    min_apy_cushion: float = 0.25        # 25% cushion above implied
    implied_yield_annual: float = 0.08   # 8% implied (market embedded)
    yt_price_pct: float = 0.25           # YT = 25% of notional
    exit_at_maturity_pct: float = 0.60   # exit at 60% of maturity

    def __post_init__(self) -> None:
        if not 0.0 < self.max_capital_pct <= 1.0:
            raise ValueError(f"max_capital_pct must be in (0, 1], got {self.max_capital_pct}")
        if self.min_apy_cushion < 0.0:
            raise ValueError(f"min_apy_cushion must be >= 0, got {self.min_apy_cushion}")
        if self.implied_yield_annual < 0.0:
            raise ValueError(f"implied_yield_annual must be >= 0, got {self.implied_yield_annual}")
        if not 0.0 < self.yt_price_pct < 1.0:
            raise ValueError(f"yt_price_pct must be in (0, 1), got {self.yt_price_pct}")
        if not 0.0 < self.exit_at_maturity_pct <= 1.0:
            raise ValueError(f"exit_at_maturity_pct must be in (0, 1], got {self.exit_at_maturity_pct}")


# ─── Strategy ─────────────────────────────────────────────────────────────────

@dataclass
class PendleYTStrategy:
    """Pendle YT Speculation Strategy — S10.

    Tracks a single YT position over its lifetime (up to exit_at_maturity_pct
    of PENDLE_MATURITY_DAYS days). Simulates daily P&L accumulation based on
    the live APY feed vs the implied yield.

    Usage:
        strategy = PendleYTStrategy(capital=100_000.0)
        strategy.current_apy = 0.15   # 15% from live feed (decimal)
        if strategy.entry_gate():
            strategy.is_active = True
        for day in range(...):
            state = strategy.simulate_day(apy=live_apy)

    Attributes:
        capital:           Total portfolio capital in USD.
        config:            Strategy parameters (PendleYTConfig).
        current_apy:       Current live APY as decimal (e.g. 0.15 for 15%).
        days_held:         Number of days the YT position has been held.
        is_active:         Whether the position is currently open.
        accumulated_yield: Total P&L accrued since position open (USD).
    """
    capital: float
    config: PendleYTConfig = field(default_factory=PendleYTConfig)
    current_apy: float = 0.0
    days_held: int = 0
    is_active: bool = False
    accumulated_yield: float = 0.0

    # ── Validation ────────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if self.capital < 0:
            raise ValueError(f"capital must be >= 0, got {self.capital}")

    # ── Derived read-only helpers ─────────────────────────────────────────────

    @property
    def capital_deployed(self) -> float:
        """Capital actually deployed into the YT position (USD)."""
        return self.capital * self.config.max_capital_pct

    @property
    def exit_day_threshold(self) -> int:
        """Day at which the position should be closed (60% of maturity)."""
        return math.floor(PENDLE_MATURITY_DAYS * self.config.exit_at_maturity_pct)

    # ── Core strategy methods ─────────────────────────────────────────────────

    def entry_gate(self) -> bool:
        """Check if entry conditions are met.

        Returns True iff:
            current_apy > implied_yield_annual × (1 + min_apy_cushion)

        Example with defaults:
            implied = 8%, cushion = 25% → threshold = 10%
            Entry allowed only if current_apy > 10%.
        """
        threshold = self.config.implied_yield_annual * (1.0 + self.config.min_apy_cushion)
        return self.current_apy > threshold

    def daily_pnl(self) -> float:
        """Compute P&L for one day.

        Formula:
            pnl = max(0, current_apy − implied_yield) × leverage × capital_deployed / 365

        When current_apy > implied_yield: YT captures the leveraged excess.
        When current_apy ≤ implied_yield: YT is worthless — no daily gain
          (the ultimate max loss scenario is captured in scenario_analysis).

        Returns:
            USD P&L for the day (≥ 0). Negative outcome (YT → 0) is not
            modelled daily; it manifests as zero accumulation in the bear scenario.
        """
        if not self.is_active:
            return 0.0
        excess_apy = self.current_apy - self.config.implied_yield_annual
        if excess_apy <= 0.0:
            return 0.0
        return excess_apy * YT_LEVERAGE_MULTIPLIER * self.capital_deployed / 365.0

    def simulate_day(self, apy: float) -> dict:
        """Advance the strategy by one day.

        Updates current_apy, increments days_held (if active), accumulates
        daily P&L, checks exit conditions, and returns a state snapshot.

        Args:
            apy: Live annual APY for the day as decimal (e.g. 0.12 for 12%).

        Returns:
            dict with keys:
              day              – current days_held after this step
              apy              – the apy passed in
              is_active        – position open after this step
              daily_pnl        – USD P&L for this day
              accumulated_yield– total USD yield so far
              exited           – True if position was closed on this step
        """
        self.current_apy = apy
        pnl = 0.0
        did_exit = False

        if self.is_active:
            self.days_held += 1
            pnl = self.daily_pnl()
            self.accumulated_yield += pnl

            if self.should_exit():
                did_exit = True
                self.is_active = False

        return {
            "day": self.days_held,
            "apy": apy,
            "is_active": self.is_active,
            "daily_pnl": round(pnl, 8),
            "accumulated_yield": round(self.accumulated_yield, 8),
            "exited": did_exit,
        }

    def should_exit(self) -> bool:
        """True if the position should be closed.

        Exit conditions (either triggers exit):
          1. days_held ≥ exit_day_threshold  (60% of PENDLE_MATURITY_DAYS)
          2. current_apy < implied_yield_annual  (below break-even → YT → 0)
        """
        if self.days_held >= self.exit_day_threshold:
            return True
        if self.current_apy < self.config.implied_yield_annual:
            return True
        return False

    def net_apy_annualized(self) -> float:
        """Annualized net APY based on accumulated yield and days held.

        Formula:
            net_apy = (accumulated_yield / capital_deployed) × (365 / days_held)

        Returns 0.0 if no days have been simulated or capital_deployed is zero.
        """
        if self.days_held <= 0 or self.capital_deployed <= 0.0:
            return 0.0
        return (self.accumulated_yield / self.capital_deployed) * (365.0 / self.days_held)

    def scenario_analysis(self) -> dict:
        """Three-scenario forward analysis (Bull / Base / Bear).

        Scenarios evaluated at fixed APYs:
          Bull  apy=20%: gross 50%, net 42%
          Base  apy=12%: gross 22%, net 14%
          Bear  apy= 6%: below implied → YT → 0, max loss = yt_price_pct × capital_deployed

        Returns:
            dict[str, dict] with keys 'bull', 'base', 'bear'.
            Each sub-dict has:
              apy            – scenario APY (decimal)
              gross_apy      – gross APY on capital_deployed (decimal)
              net_apy        – net APY on capital_deployed (decimal)
              pnl_usd        – total P&L over holding period (USD)
              verdict        – 'profit' or 'max_loss'
              holding_days   – expected holding duration
        """
        implied = self.config.implied_yield_annual
        cap = self.capital_deployed
        holding_days = float(self.exit_day_threshold)

        result: dict = {}

        for name, apy in (("bull", 0.20), ("base", 0.12), ("bear", 0.06)):
            if apy > implied:
                excess = apy - implied
                gross_apy = implied + excess * YT_LEVERAGE_MULTIPLIER
                net_apy = excess * YT_LEVERAGE_MULTIPLIER
                # Total P&L = net_apy × capital_deployed × (holding_days / 365)
                pnl_usd = net_apy * cap * (holding_days / 365.0)
                result[name] = {
                    "apy": apy,
                    "gross_apy": round(gross_apy, 6),
                    "net_apy": round(net_apy, 6),
                    "pnl_usd": round(pnl_usd, 2),
                    "verdict": "profit",
                    "holding_days": int(holding_days),
                }
            else:
                # Bear: YT expires worthless — full YT premium lost
                max_loss_usd = -(self.config.yt_price_pct * cap)
                result[name] = {
                    "apy": apy,
                    "gross_apy": 0.0,
                    "net_apy": round(-(self.config.yt_price_pct), 6),
                    "pnl_usd": round(max_loss_usd, 2),
                    "verdict": "max_loss",
                    "holding_days": int(holding_days),
                }

        return result

    def to_vportfolio_format(self) -> dict:
        """Return a VPortfolio-compatible daily state snapshot.

        Compatible with the VPortfolio.to_dict() schema used by
        VPortfolioManager — can be merged into the portfolios section of
        data/vportfolios.json.

        Returns:
            dict with strategy metadata and current position state.
        """
        return {
            "strategy_id": "S10",
            "strategy_name": "Pendle YT Speculation",
            "tier": "T3",
            "risk_level": "HIGH",
            "is_active": self.is_active,
            "capital_total": round(self.capital, 2),
            "capital_deployed": round(self.capital_deployed, 2),
            "capital_deployed_pct": self.config.max_capital_pct,
            "current_apy": round(self.current_apy, 8),
            "days_held": self.days_held,
            "exit_day_threshold": self.exit_day_threshold,
            "accumulated_yield": round(self.accumulated_yield, 8),
            "net_apy_annualized": round(self.net_apy_annualized(), 8),
            "entry_gate_open": self.entry_gate(),
            "should_exit_now": self.should_exit() if self.is_active else False,
            "implied_yield_annual": self.config.implied_yield_annual,
            "yt_price_pct": self.config.yt_price_pct,
            "max_capital_pct": self.config.max_capital_pct,
            "min_apy_cushion": self.config.min_apy_cushion,
            "exit_at_maturity_pct": self.config.exit_at_maturity_pct,
            "leverage_multiplier": YT_LEVERAGE_MULTIPLIER,
            "maturity_days_total": PENDLE_MATURITY_DAYS,
        }


# ─── Module-level factory ─────────────────────────────────────────────────────

def make_strategy(capital: float, **config_overrides) -> PendleYTStrategy:
    """Convenience factory — create a PendleYTStrategy with optional config overrides.

    Args:
        capital:          Total portfolio capital (USD).
        **config_overrides: Any PendleYTConfig field can be overridden by name.

    Returns:
        PendleYTStrategy ready for simulation.
    """
    cfg = PendleYTConfig(**config_overrides) if config_overrides else PendleYTConfig()
    return PendleYTStrategy(capital=capital, config=cfg)


# ─── Авто-регистрация в StrategyRegistry ─────────────────────────────────────

def _register_s10() -> None:
    """Авто-регистрация S10 в spa_core/strategies/strategy_registry.py REGISTRY.

    ADR-021: Pendle YT T3-SPEC — advisory only, позиции не открываются автоматически.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta, VALID_TYPES
        # Pendle YT — leveraged yield speculation; closest valid type is yield_loop
        if "yt_speculation" not in VALID_TYPES:
            VALID_TYPES.add("yt_speculation")
        REGISTRY.register(StrategyMeta(
            id="s10_pendle_yt",
            name="S10 — Pendle YT Speculation",
            type="yt_speculation",
            risk_tier="T3",
            target_apy_min=14.0,
            target_apy_max=42.0,
            max_drawdown_pct=30.0,
            description=(
                "Leveraged yield speculation via Pendle YT tokens (T3, high-risk). "
                "Entry: current_apy > implied_yield × 1.25 (default 10%). "
                "Max allocation 30%; YT leverage ≈ 3.5×. "
                "ADR-021: advisory only — paper trading until Owner approval."
            ),
            module="spa_core.strategies.pendle_yt",
            handler_class="PendleYTStrategy",
            tags=["pendle", "yt", "speculation", "leverage", "t3", "advisory", "paper_only"],
            enabled=True,
        ))
    except Exception as _exc:
        import logging
        logging.getLogger(__name__).warning("S10 auto-registration failed: %s", _exc)


_register_s10()
