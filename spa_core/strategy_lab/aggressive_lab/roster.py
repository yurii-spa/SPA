"""
spa_core/strategy_lab/aggressive_lab/roster.py — the AGGRESSIVE STRATEGY ROSTER.

Eight high-yield (10–15%+) strategies the conservative RiskPolicy REFUSES, wrapped as pluggable
Strategy-ABC entrants so the shared real-data harness can paper-trade + backtest every one of them
the SAME way. Each entrant declares, honestly and up front:

  • its real yield SOURCE   — WHERE the return actually comes from (which live feed it accrues on),
  • its risk SHAPE          — the dominant tail mechanism (funding_flip / depeg / liquidation /
                              il / incentive_decay) the headline yield is COMPENSATION for,
  • its RiskClass (A/B/C/D) — alpha / beta / risk-compensation / incentive (see __init__.RiskClass).

These map to the real roster found in the investigation:
  sUSDe/Ethena delta-neutral (S71 ~11%), sUSDe-heavy spot (S22/S25 ~9%), Pendle YT sUSDe (~14%),
  Pendle PT levered, LRT-neutral (variant_n), ETH-directional (variant_d), leverage loop (S73
  aave_v3_wsteth 2x), points farming (S77).

ACCRUAL — REAL DATA, NEVER MOCK (the whole point):
  Every entrant accrues on fields the harness fills from LIVE feeds:
    • defi_apy["susde"]            — Ethena sUSDe staking APY (DeFiLlama),
    • defi_apy["pendle_yt_susde"]  — Pendle YT-sUSDe implied yield (the leveraged-yield leg),
    • defi_apy["pendle_pt_susde"]  — Pendle PT-sUSDe fixed implied yield,
    • restaking_apy[<lrt>]         — LRT restaking APY,
    • funding_rate_8h              — the 5-venue median ETH-perp funding (carry / hedge cost),
    • eth_price_usd / lrt_eth_ratio — for the directional + depeg books,
    • defi_apy["points"]           — modelled points/incentive APY (decays; flagged class D).
  A required field missing on a tick → the entrant FAILS CLOSED (no fabricated accrual; the harness
  records an honest gap). NO hardcoded 12% — feed a stale feed and the book does NOT advance.

ISOLATION: these books are pure virtual notionals (default $100k each) accrued only into
data/aggressive_lab/<id>/. They run OUTSIDE the RiskPolicy gate ON PURPOSE and can never touch the
go-live track (enforced by isolation.py at the IO layer).

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN (no LLM in risk/kill).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict, List, Optional

from spa_core.strategy_lab.base import (
    InvalidDataError,
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)

# Risk-class values mirror aggressive_lab.RiskClass (A alpha / B beta / C risk-comp / D incentive).
_DAYS_PER_YEAR = 365.0


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Base: an aggressive paper-book entrant. Subclasses set identity + implement _daily_yield_pct() and
# _kill(market). The base handles capital, daily compounding accrual, costs, and the fail-closed
# kill plumbing — every entrant accrues the SAME honest way (so the comparison is apples-to-apples).
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class _AggressiveBase(Strategy):
    is_advisory = True            # ALWAYS — this lab never goes live on its own
    outside_riskpolicy = True     # the defining property: it runs OUTSIDE the RiskPolicy gate

    # subclass identity / honesty declarations (set as class attrs)
    id = "aggressive_base"
    name = "Aggressive base"
    mandate = "aggressive"
    risk_class = "C"              # most aggressive books are C (risk-compensation)
    risk_shape = "funding_flip"   # dominant tail mechanism
    yield_source = "unspecified"  # human-readable WHERE the return comes from
    headline_apy_pct = 0.0        # the advertised headline (for the scorecard; realized may differ)

    def __init__(self) -> None:
        self._capital = 0.0
        self._equity = 0.0
        self._cfg: dict = {}
        self._days = 0
        self._killed = False
        self._kill_reason = ""
        self._cum_cost = 0.0      # cumulative modelled cost (slippage/funding paid/gas)
        self._cum_funding = 0.0   # cumulative funding P&L (+received / −paid), where modelled
        # honest off-code flag: a basis/hedge leg whose CEX side is not buildable in-code.
        self.hedge_leg_buildable = True
        self._initialised = False

    # ── lifecycle ───────────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = float(capital)
        self._equity = float(capital)
        self._cfg = dict(config or {})
        self._days = 0
        self._killed = False
        self._kill_reason = ""
        self._cum_cost = 0.0
        self._cum_funding = 0.0
        self._initialised = True

    # ── the per-tick advance ──────────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if not self._initialised:
            raise InvalidDataError(f"{self.id}.step before init")
        if self._killed:
            return  # safe-hold: a killed book stops accruing
        try:
            daily_pct = self._daily_yield_pct(market)  # REAL-data net daily return fraction
        except InvalidDataError as exc:
            # fail-CLOSED: missing/stale required feed → no fabricated accrual; safe-hold this tick.
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return
        self._equity = round(self._equity * (1.0 + daily_pct), 2)
        self._days += 1

    # ── subclass hook: the REAL-data net daily return fraction for this tick ──────────────────────
    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        raise NotImplementedError

    # ── inspection ──────────────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        return [Position(asset=self.id, kind="aggressive", notional_usd=round(self._equity, 2))]

    def equity(self) -> float:
        return round(self._equity, 2)

    def metrics(self) -> StrategyMetrics:
        net = (self._equity - self._capital) if self._capital else 0.0
        apy = round(net / self._capital * 100.0, 4) if self._capital else None
        return StrategyMetrics(
            net_apy_pct=apy,
            funding_drag_pct=(round(self._cum_funding / self._capital * 100.0, 4)
                              if self._capital else None),
            extra={
                "equity_usd": round(self._equity, 2),
                "cum_cost_usd": round(self._cum_cost, 2),
                "cum_funding_usd": round(self._cum_funding, 2),
                "killed": self._killed,
                "kill_reason": self._kill_reason,
                "risk_class": self.risk_class,
                "risk_shape": self.risk_shape,
                "yield_source": self.yield_source,
                "hedge_leg_buildable": self.hedge_leg_buildable,
                "outside_riskpolicy": True,
                "is_advisory": True,
            },
        )

    # ── kill (FAIL-CLOSED) ──────────────────────────────────────────────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        ts = getattr(market, "date", "")
        if self._killed:
            return KillResult(triggered=True, reason=self._kill_reason or "killed", ts=ts)
        try:
            killed, reason = self._kill(market)
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)
        if killed:
            self._killed = True
            self._kill_reason = reason
            return KillResult(triggered=True, reason=reason, ts=ts)
        return KillResult(triggered=False, reason="", ts=ts)

    def _kill(self, market: MarketSnapshot) -> tuple:
        """(triggered, reason). Default: no extra kill beyond the fail-closed step guard."""
        return (False, "")

    # ── the honest self-description (fed into meta.json) ──────────────────────────────────────────
    def describe(self) -> dict:
        return {
            "strategy_id": self.id,
            "name": self.name,
            "risk_class": self.risk_class,
            "risk_shape": self.risk_shape,
            "yield_source": self.yield_source,
            "headline_apy_pct": self.headline_apy_pct,
            "hedge_leg_buildable": self.hedge_leg_buildable,
            "is_advisory": True,
            "outside_riskpolicy": True,
        }


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 1. sUSDe / Ethena DELTA-NEUTRAL (S71, ~11%) — long sUSDe + short ETH perp.
#    Yield SOURCE: sUSDe staking APY (real funding carry captured by Ethena) ± perp funding.
#    Risk SHAPE: funding_flip — when perp funding flips persistently negative the carry inverts
#    (the canonical Ethena Oct-2025 unwind). Class C (the yield IS the risk premium).
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class SusdeDeltaNeutral(_AggressiveBase):
    id = "susde_dn"
    name = "sUSDe delta-neutral (S71): long sUSDe + short ETH perp"
    risk_class = "C"
    risk_shape = "funding_flip"
    yield_source = "Ethena sUSDe staking APY (funding carry) ± ETH-perp funding"
    headline_apy_pct = 11.0

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        susde_apy = market.require("defi_apy", "susde")          # decimal annual — REAL feed
        funding = market.require("funding")                       # 8h median — REAL feed
        # The short-perp leg RECEIVES funding when positive, PAYS when negative. 3 settlements/day.
        funding_day = funding * 3.0
        self._cum_funding += self._equity * funding_day
        # Net daily = sUSDe carry + the (signed) daily perp funding on the hedged notional.
        return (susde_apy / _DAYS_PER_YEAR) + funding_day

    def _kill(self, market: MarketSnapshot) -> tuple:
        funding = market.require("funding")
        # config-sourced funding-flip kill (no hardcode); default −0.0003/8h sustained is hostile.
        thr = float(self._cfg.get("funding_kill_8h", -0.0003))
        if funding < thr:
            return (True, f"funding {funding:.5f} < {thr:.5f} (funding-flip tail)")
        return (False, "")


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 2. sUSDe-HEAVY SPOT (S22/S25, ~9%) — just hold sUSDe (no hedge). Class C, shape depeg.
#    Yield SOURCE: sUSDe staking APY. No perp leg → keeps the full carry but bears the USDe peg risk.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class SusdeSpot(_AggressiveBase):
    id = "susde_spot"
    name = "sUSDe spot (S22/S25): unhedged sUSDe hold"
    risk_class = "C"
    risk_shape = "depeg"
    yield_source = "Ethena sUSDe staking APY (unhedged)"
    headline_apy_pct = 9.0

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        susde_apy = market.require("defi_apy", "susde")
        return susde_apy / _DAYS_PER_YEAR


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 3. Pendle YT-sUSDe (~14%) — buy the YT (the leveraged yield token). Class C, shape funding_flip.
#    Yield SOURCE: the Pendle YT-sUSDe implied yield (a LEVERAGED claim on sUSDe's yield to maturity);
#    YT decays to ZERO at maturity, so the realized return is yield − theta. Fat headline, fat tail.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class PendleYtSusde(_AggressiveBase):
    id = "pendle_yt_susde"
    name = "Pendle YT-sUSDe (~14%): leveraged sUSDe yield token"
    risk_class = "C"
    risk_shape = "funding_flip"
    yield_source = "Pendle YT-sUSDe implied yield (leveraged claim on sUSDe yield, decays to 0)"
    headline_apy_pct = 14.0

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        yt_apy = market.require("defi_apy", "pendle_yt_susde")    # REAL Pendle YT implied yield
        return yt_apy / _DAYS_PER_YEAR


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 4. Pendle PT LEVERED (~15%) — loop PT-sUSDe at L× via lending. Class C, shape liquidation.
#    Yield SOURCE: PT fixed implied yield × leverage − borrow cost. The leverage is the tail: a PT
#    price wobble + the borrow leg = a liquidation cascade (the Oct-2025 over-levered-USDe pattern).
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class PendlePtLevered(_AggressiveBase):
    id = "pendle_pt_levered"
    name = "Pendle PT-sUSDe levered loop (~15%)"
    risk_class = "C"
    risk_shape = "liquidation"
    yield_source = "Pendle PT-sUSDe fixed implied yield × leverage − borrow cost"
    headline_apy_pct = 15.0

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        pt_apy = market.require("defi_apy", "pendle_pt_susde")    # REAL PT fixed implied yield
        lev = float(self._cfg.get("leverage", 3.0))
        borrow_apy = float(self._cfg.get("borrow_apy", 0.05))     # cost of the looped borrow leg
        # levered carry = PT_yield × leverage − borrow_cost × (leverage − 1)
        net_apy = pt_apy * lev - borrow_apy * (lev - 1.0)
        self._cum_cost += self._equity * (borrow_apy * (lev - 1.0) / _DAYS_PER_YEAR)
        return net_apy / _DAYS_PER_YEAR


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 5. LRT-NEUTRAL (variant_n) — LRT spot + short ETH perp, β≈0. Class C, shape depeg.
#    Yield SOURCE: LRT restaking APY ± perp funding. The hedge removes ETH-price beta; the residual
#    is the LRT↔ETH depeg (which the perp does NOT hedge) — the Aug-2024 / Apr-2026 depeg tail.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class LrtNeutral(_AggressiveBase):
    id = "lrt_neutral"
    name = "LRT delta-neutral (variant_n): LRT spot + short ETH perp"
    risk_class = "C"
    risk_shape = "depeg"
    yield_source = "LRT restaking APY ± ETH-perp funding (β≈0; residual = LRT depeg)"
    headline_apy_pct = 6.0

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._lrt = str((config or {}).get("lrt_symbol", "eeth"))
        self._entry_ratio: Optional[float] = None

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        restaking = market.require("restaking_apy", self._lrt)   # REAL restaking APY
        funding = market.require("funding")
        ratio = market.require("lrt_ratio", self._lrt)
        if self._entry_ratio is None:
            self._entry_ratio = ratio
        funding_day = funding * 3.0
        self._cum_funding += self._equity * funding_day
        return (restaking / _DAYS_PER_YEAR) + funding_day

    def _kill(self, market: MarketSnapshot) -> tuple:
        ratio = market.require("lrt_ratio", self._lrt)
        if self._entry_ratio:
            drop = (self._entry_ratio - ratio) / self._entry_ratio * 100.0
            thr = float(self._cfg.get("depeg_kill_pct", 5.0))
            if drop > thr:
                return (True, f"LRT depeg {drop:.2f}% > {thr:.2f}% (depeg tail)")
        return (False, "")


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 6. ETH-DIRECTIONAL (variant_d) — pure LRT, NO hedge, β≈1. Class B (beta — NOT alpha).
#    Yield SOURCE: LRT restaking APY, but equity moves with ETH price (the honest flag: this is
#    directional market exposure dressed up as 'yield'). Shape depeg + market beta.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class EthDirectional(_AggressiveBase):
    id = "eth_directional"
    name = "ETH-directional restaking (variant_d): unhedged LRT, β≈1"
    risk_class = "B"
    risk_shape = "depeg"
    yield_source = "LRT restaking APY + UNHEDGED ETH price exposure (directional beta)"
    headline_apy_pct = 4.0

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._lrt = str((config or {}).get("lrt_symbol", "eeth"))
        self._entry_eth: Optional[float] = None

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        restaking = market.require("restaking_apy", self._lrt)
        eth = market.require("eth_price")
        if self._entry_eth is None:
            self._entry_eth = eth
            return restaking / _DAYS_PER_YEAR
        # directional: the daily equity move IS the ETH price move + the day's restaking accrual.
        prev = getattr(self, "_prev_eth", self._entry_eth)
        price_ret = (eth - prev) / prev if prev else 0.0
        self._prev_eth = eth
        return price_ret + (restaking / _DAYS_PER_YEAR)


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 7. LEVERAGE LOOP (S73, aave_v3_wstETH 2×) — loop wstETH at L×. Class C, shape liquidation.
#    Yield SOURCE: wstETH staking APY × leverage − borrow cost. Tail: an stETH wobble at leverage
#    near the liquidation threshold (0.825 LTV) cascades.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class LeverageLoop(_AggressiveBase):
    id = "leverage_loop"
    name = "Leverage loop (S73): wstETH 2× on Aave v3"
    risk_class = "C"
    risk_shape = "liquidation"
    yield_source = "wstETH staking APY × leverage − borrow cost (liquidation tail at 0.825 LTV)"
    headline_apy_pct = 7.5

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        # wstETH staking yield comes through restaking_apy["steth"] (plain-staking) or defi_apy.
        try:
            staking = market.require("restaking_apy", "steth")
        except InvalidDataError:
            staking = market.require("defi_apy", "aave_v3_wsteth")
        lev = float(self._cfg.get("leverage", 2.0))
        borrow_apy = float(self._cfg.get("borrow_apy", 0.035))
        net_apy = staking * lev - borrow_apy * (lev - 1.0)
        self._cum_cost += self._equity * (borrow_apy * (lev - 1.0) / _DAYS_PER_YEAR)
        return net_apy / _DAYS_PER_YEAR


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 8. POINTS FARM (S77) — chase emissions/points. Class D (incentive — DECAYS; not durable edge).
#    Yield SOURCE: modelled points/incentive APY (real where a feed exists; flagged D because it is
#    token emissions that decay, NOT a structural edge). Shape incentive_decay.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class PointsFarm(_AggressiveBase):
    id = "points_farm"
    name = "Points / incentive farm (S77)"
    risk_class = "D"
    risk_shape = "incentive_decay"
    yield_source = "Token emissions / points / airdrop incentives (DECAYS — not a durable edge)"
    headline_apy_pct = 14.0

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        # The points APY is supplied via defi_apy["points"] (the harness models it from the real
        # incentive feed where available). fail-CLOSED if absent — no hardcoded farm yield.
        points_apy = market.require("defi_apy", "points")
        return points_apy / _DAYS_PER_YEAR


# ── the roster registry (deterministic order) ──────────────────────────────────────────────────────
ROSTER_CLASSES = (
    SusdeDeltaNeutral,
    SusdeSpot,
    PendleYtSusde,
    PendlePtLevered,
    LrtNeutral,
    EthDirectional,
    LeverageLoop,
    PointsFarm,
)


def build_roster(config: Optional[Dict[str, dict]] = None,
                 notional_usd: float = 100_000.0) -> Dict[str, _AggressiveBase]:
    """{id: initialized strategy} for the whole aggressive roster. Each gets a comparable virtual
    notional (default $100k) and its per-strategy config block (config[id], or {} if absent)."""
    cfg = config or {}
    out: Dict[str, _AggressiveBase] = {}
    for cls in ROSTER_CLASSES:
        strat = cls()
        block = cfg.get(cls.id, {})
        cap = float(block.get("capital_usd", notional_usd)) if isinstance(block, dict) else notional_usd
        strat.init(cap, block if isinstance(block, dict) else {})
        out[cls.id] = strat
    return out


def roster_ids() -> List[str]:
    return [c.id for c in ROSTER_CLASSES]
