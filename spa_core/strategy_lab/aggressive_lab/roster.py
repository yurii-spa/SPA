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

# ── PT mark-to-market convention ───────────────────────────────────────────────────────────────────
# A Pendle PT redeems 1:1 for its underlying at maturity, so its PRICE (in face units) is the
# discount factor implied by its market implied-yield: price = 1 / (1 + iy) ** τ, τ = years-to-mat.
# We mark a PT/synth book to this REAL discount: when the real implied-yield series SPIKES (the
# Oct-2025 USDe unwind, a depeg de-risk), the PT price DROPS → the book marks down on the real date.
# The path is the deep Pendle implied-yield history (real), so the dip is realized_backtest_series,
# never a stamped number. τ is a fixed modelling tenor (the discount's SENSITIVITY); the day-over-day
# MOVE that drives the mark comes entirely from the real implied-yield change.
_PT_MTM_TENOR_YEARS = 90.0 / 365.0


def _pt_price_from_iy(implied_yield: float, tenor_years: float = _PT_MTM_TENOR_YEARS) -> float:
    """PT discount price (face units) for a market implied yield. price = 1/(1+iy)^τ.
    Higher implied yield (stress) → lower price (mark-down). fail-CLOSED on a degenerate input."""
    base = 1.0 + float(implied_yield)
    if base <= 0.0 or tenor_years <= 0.0:
        raise InvalidDataError(f"PT mark: degenerate (1+iy)={base}, tau={tenor_years}")
    return base ** (-float(tenor_years))


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
    # When True, a MISSING accrual feed is an honest per-tick GAP (safe-hold, no advance) instead of a
    # permanent kill. Set True for books whose REAL feeds legitimately start later / are sparser than
    # the global replay window (the price/ratio/restaking history is shorter than the deep PT history)
    # — so the book simply waits for its data to start rather than dying day-1 in warmup.
    #
    # OWNER DECISION 2026-07-06: default is now SAFE-HOLD (pause), not kill. A transient DATA gap in the
    # accrual feed (e.g. the deep Pendle/sUSDe dataset lagging a few days, as it did 06-25→06-29) must
    # PAUSE the book (no advance, no fabricated accrual, resume when the data returns) — exactly like the
    # mark-feed gap path and like rates_desk — NOT permanently kill it. The "always-present" assumption
    # proved false (that very series went stale and killed every high-tier book). A GENUINE risk event
    # (liquidation / drawdown breach) is a SEPARATE kill mechanism and is unaffected by this flag.
    accrual_gap_is_safe_hold = True

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
        # ── MARK-TO-MARKET state ──────────────────────────────────────────────────────────────────
        # `_mtm` is the day's mark-to-market fractional move (price/ratio/funding path), SEPARATE from
        # yield accrual. `_mtm_source` is the HONEST provenance of TODAY's mark: "realized_backtest_
        # series" when a real per-day price/ratio/funding path drove it, None when the day was pure
        # accrual (no real mark path for this tick). The harness stamps these on each realized point so
        # a reader can always tell a REAL dated dip from smooth accrual. Subclasses fill _mark_to_
        # market_pct(); the base never fabricates a mark (a missing path → 0.0 mark, source None).
        self._mtm = 0.0
        self._mtm_source: Optional[str] = None
        self._cum_mtm = 0.0       # cumulative realized mark-to-market P&L fraction (audit)
        # previous-mark anchors for day-over-day MTM (set on first real datapoint seen)
        self._prev_pt_price: Optional[float] = None
        self._prev_ratio: Optional[float] = None

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
        self._mtm = 0.0
        self._mtm_source = None
        self._cum_mtm = 0.0
        self._prev_pt_price = None
        self._prev_ratio = None
        self._initialised = True

    # ── the per-tick advance ──────────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if not self._initialised:
            raise InvalidDataError(f"{self.id}.step before init")
        if self._killed:
            return  # safe-hold: a killed book stops accruing
        # reset today's mark provenance — set by _mark_to_market_pct ONLY when a real path drove it.
        self._mtm = 0.0
        self._mtm_source = None
        try:
            daily_accrual = self._daily_yield_pct(market)   # REAL-data yield-accrual fraction
        except InvalidDataError as exc:
            if self.accrual_gap_is_safe_hold:
                # honest GAP: this book's real feed legitimately hasn't started / is sparse for this
                # tick → safe-hold (no advance, no fabricated accrual), resume when the data returns.
                return
            # fail-CLOSED on the ACCRUAL feed: a book whose yield source is missing/stale cannot
            # honestly mark a return → it is KILLED (the documented contract; no fabricated accrual).
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return
        try:
            daily_mtm = self._mark_to_market_pct(market)    # REAL-path price/ratio mark-to-market
        except InvalidDataError:
            # fail-CLOSED on the MARK feed (a price/ratio path absent for THIS tick, e.g. before the
            # series starts or a hole): we do NOT advance the equity on a day we cannot mark — an
            # honest GAP (no fabricated accrual, no smooth-fake), NOT a permanent kill. The book
            # resumes marking when its real path returns. This is what keeps the realized curve honest
            # across the sparser price-feed days without either dying or faking a smooth carry.
            return
        # realized daily move = yield accrual + mark-to-market of the position through the real path.
        # The MTM is what makes the equity curve DIP on the real event dates (it can be negative);
        # accrual is the smooth carry. Both compound into the same equity (one honest realized track).
        self._mtm = daily_mtm
        self._cum_mtm += daily_mtm
        self._equity = round(self._equity * (1.0 + daily_accrual + daily_mtm), 2)
        self._days += 1

    # ── subclass hook: the REAL-data yield-accrual fraction for this tick (the smooth carry) ──────
    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        raise NotImplementedError

    # ── subclass hook: the REAL-PATH mark-to-market fraction for this tick (the dip mechanism) ────
    # Default: no mark (pure accrual book). A subclass overrides to mark its collateral/PT/LRT to its
    # REAL per-day price/ratio/funding path; it MUST set self._mtm_source = "realized_backtest_series"
    # on any day it returns a mark driven by a real path (and leave it None on a pure-accrual day).
    # fail-CLOSED: a required mark feed missing → raise InvalidDataError (the book then safe-holds),
    # never a fabricated mark.
    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        return 0.0

    # ── shared MTM helpers (day-over-day moves off REAL paths) ────────────────────────────────────
    def _pt_mtm(self, implied_yield: float) -> float:
        """Day-over-day fractional PT mark from the REAL implied-yield path. price = 1/(1+iy)^τ; the
        return is (price_today − price_prev)/price_prev. First datapoint → 0 (anchors, no move yet).
        Sets _mtm_source on a real (non-zero-anchor) day."""
        price = _pt_price_from_iy(implied_yield)
        if self._prev_pt_price is None:
            self._prev_pt_price = price
            return 0.0
        move = (price - self._prev_pt_price) / self._prev_pt_price if self._prev_pt_price else 0.0
        self._prev_pt_price = price
        self._mtm_source = "realized_backtest_series"   # driven by the REAL implied-yield series
        return move

    def _ratio_mtm(self, ratio: float) -> float:
        """Day-over-day fractional mark from a REAL collateral/ETH (or LRT/ETH) ratio path. This is
        the depeg residual the perp hedge does NOT cover. First datapoint anchors (0 move)."""
        if self._prev_ratio is None:
            self._prev_ratio = float(ratio)
            return 0.0
        move = (float(ratio) - self._prev_ratio) / self._prev_ratio if self._prev_ratio else 0.0
        self._prev_ratio = float(ratio)
        self._mtm_source = "realized_backtest_series"   # driven by the REAL price/ratio series
        return move

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
                "mtm_today_pct": round(self._mtm * 100.0, 6),
                "mtm_source": self._mtm_source,
                "cum_mtm_pct": round(self._cum_mtm * 100.0, 6),
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
        # carry-only accrual; the (signed) perp funding is the MARK (see _mark_to_market_pct).
        return susde_apy / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # FUNDING-FLIP mark: the short-perp leg RECEIVES funding when positive, PAYS when negative
        # (3 settlements/day). When the REAL funding path inverts (the Oct-2025 USDe unwind: funding
        # went deeply negative) the carry turns to BLEED → the equity DIPS on the real date. This is
        # the real per-day funding series, so it is a realized mark, not a stamped shock.
        funding = market.require("funding")                       # 8h median — REAL feed
        funding_day = funding * 3.0
        self._cum_funding += self._equity * funding_day
        self._mtm_source = "realized_backtest_series"
        return funding_day

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

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # DEPEG mark: an unhedged sUSDe holder marks to the sUSDe market price. The REAL per-day
        # signal we have is the PT-sUSDe implied-yield path (deep Pendle history): when sUSDe is
        # stressed (the Oct-2025 USDe unwind), the implied yield spikes and the PT discount widens →
        # a mark-DOWN on the real date. We mark off that real discount path day-over-day. If the PT
        # series is absent for a tick → no real path → no mark (0.0), honest gap (not a fake dip).
        try:
            pt_iy = market.require("defi_apy", "pendle_pt_susde")   # REAL implied-yield path
        except InvalidDataError:
            return 0.0    # no real mark path this tick → pure-accrual day (source stays None)
        return self._pt_mtm(pt_iy)


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

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # FUNDING-FLIP mark: a YT is a LEVERAGED LONG on future sUSDe carry. When the REAL perp-funding
        # path inverts (the Oct-2025 USDe unwind: funding went deeply negative as the carry trade
        # unwound), the carry the YT is long BLEEDS, amplified by the YT's leverage → the YT marks DOWN
        # on the real date. We mark off the real funding path × the YT leverage (a negative-funding day
        # is a magnified loss; a positive-funding day a magnified gain). The dip + date come entirely
        # from the real 5-venue funding series — not a stamped shock. Positive funding is NOT clipped to
        # zero (that would hide the upside); the whole real path drives the mark, bounded per-day.
        funding = market.require("funding")                       # REAL 5-venue median 8h funding
        lev = float(self._cfg.get("yt_leverage", 8.0))            # YT ≈ high-leverage carry exposure
        funding_day = funding * 3.0
        self._cum_funding += self._equity * funding_day
        self._mtm_source = "realized_backtest_series"
        mark = lev * funding_day
        # bound a single jagged daily print so no one day dominates (sign + real move still drive it).
        return max(-0.25, min(0.25, mark))


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

    def __init__(self) -> None:
        super().__init__()
        self._liquidated = False

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._liquidated = False

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        pt_apy = market.require("defi_apy", "pendle_pt_susde")    # REAL PT fixed implied yield
        lev = float(self._cfg.get("leverage", 3.0))
        borrow_apy = float(self._cfg.get("borrow_apy", 0.05))     # cost of the looped borrow leg
        # levered carry = PT_yield × leverage − borrow_cost × (leverage − 1)
        net_apy = pt_apy * lev - borrow_apy * (lev - 1.0)
        self._cum_cost += self._equity * (borrow_apy * (lev - 1.0) / _DAYS_PER_YEAR)
        return net_apy / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # LIQUIDATION mark: the loop holds L× PT exposure financed by a borrow leg, so a PT price move
        # marks the equity at L×. The PT price comes from the REAL implied-yield path (1/(1+iy)^τ):
        # when the implied yield spikes on the real event (Oct-2025 over-levered cascade), the PT marks
        # down and the LEVERED equity draws down hard. A levered loss exceeding the equity cushion is a
        # LIQUIDATION cliff: once cumulative levered MTM wipes the buffer, the book liquidates (a one-
        # way loss). The dip + its date are the real PT series, amplified by real leverage — not stamped.
        try:
            pt_iy = market.require("defi_apy", "pendle_pt_susde")
        except InvalidDataError:
            return 0.0
        lev = float(self._cfg.get("leverage", 3.0))
        pt_move = self._pt_mtm(pt_iy)        # real day-over-day PT price move (sets source)
        levered_move = pt_move * lev         # amplified by the real leverage (the liquidation tail)
        # liquidation cliff: a levered drawdown that breaches the maintenance buffer forces an exit at
        # a loss; model it as the equity cannot recover the wiped leverage (kill fires next tick).
        liq_buffer = float(self._cfg.get("liq_buffer_frac", -0.5 / lev))  # ~maintenance margin breach
        if levered_move <= liq_buffer:
            self._liquidated = True
        return levered_move

    def _kill(self, market: MarketSnapshot) -> tuple:
        if self._liquidated:
            return (True, "levered PT liquidated (maintenance-margin breach on real PT mark-down)")
        return (False, "")


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
    accrual_gap_is_safe_hold = True   # LRT restaking/ratio history is sparser/later than the PT window

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._lrt = str((config or {}).get("lrt_symbol", "eeth"))
        self._entry_ratio: Optional[float] = None

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        restaking = market.require("restaking_apy", self._lrt)   # REAL restaking APY
        ratio = market.require("lrt_ratio", self._lrt)
        if self._entry_ratio is None:
            self._entry_ratio = ratio
        # carry-only accrual; funding + the depeg residual are the MARK (see _mark_to_market_pct).
        return restaking / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # DEPEG mark (β≈0 residual): the short ETH-perp hedge removes ETH PRICE beta, but it does NOT
        # hedge the LRT↔ETH ratio — so when the LRT depegs (rsETH/ezETH Aug-2024, Apr-2026), the
        # ratio collapse marks the equity DOWN on the real date. We mark off the REAL lrt_eth_ratio
        # path day-over-day. The (signed) perp funding is also realized P&L (a flip = carry bleed).
        funding = market.require("funding")
        funding_day = funding * 3.0
        self._cum_funding += self._equity * funding_day
        self._mtm_source = "realized_backtest_series"
        ratio = market.require("lrt_ratio", self._lrt)            # REAL LRT/ETH ratio path
        depeg_move = self._ratio_mtm(ratio)                       # residual the hedge can't cover
        return funding_day + depeg_move

    def _kill(self, market: MarketSnapshot) -> tuple:
        # a missing ratio on this tick is a GAP, not a kill trigger — we cannot EVALUATE the depeg
        # kill without the mark feed, and a book that hasn't started (no entry ratio yet) must never
        # die in warmup. Skip the check this tick (the step() already safe-held the gap day).
        try:
            ratio = market.require("lrt_ratio", self._lrt)
        except InvalidDataError:
            return (False, "")
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
    accrual_gap_is_safe_hold = True   # LRT restaking + ETH price history sparser/later than PT window

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._lrt = str((config or {}).get("lrt_symbol", "eeth"))
        self._entry_eth: Optional[float] = None
        self._prev_eth: Optional[float] = None

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        restaking = market.require("restaking_apy", self._lrt)
        # carry-only accrual; the UNHEDGED ETH price move is the MARK (see _mark_to_market_pct).
        return restaking / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # DIRECTIONAL (β≈1) mark: NO hedge, so the equity moves 1:1 with the REAL ETH price path. An
        # ETH crash (Aug-2024) marks this book down hard on the real date — the honest tell that this
        # is market BETA, not yield. Driven by the real ETH price series → realized, not stamped.
        eth = market.require("eth_price")                        # REAL ETH price path
        if self._entry_eth is None:
            self._entry_eth = eth
            self._prev_eth = eth
            return 0.0
        prev = getattr(self, "_prev_eth", self._entry_eth)
        price_ret = (eth - prev) / prev if prev else 0.0
        self._prev_eth = eth
        self._mtm_source = "realized_backtest_series"
        return price_ret


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
    accrual_gap_is_safe_hold = True   # stETH staking/ratio history sparser/later than the PT window

    def __init__(self) -> None:
        super().__init__()
        self._liquidated = False

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._liquidated = False

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

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # LIQUIDATION mark: the loop holds L× wstETH collateral against an ETH borrow. The position is
        # exposed to the stETH↔ETH ratio (the depeg that breaches the 0.825-LTV liquidation threshold)
        # marked at L×. We mark off the REAL stETH/ETH ratio path day-over-day × leverage: an stETH
        # wobble at leverage near the threshold cascades. The dip + date are the real ratio series
        # (amplified by real leverage), not a stamped shock. No real ratio for a tick → no mark.
        try:
            ratio = market.require("lrt_ratio", "steth")          # REAL stETH/ETH ratio path
        except InvalidDataError:
            return 0.0    # no real mark path this tick → pure-accrual day
        lev = float(self._cfg.get("leverage", 2.0))
        ratio_move = self._ratio_mtm(ratio)                       # real day-over-day (sets source)
        levered_move = ratio_move * lev
        liq_buffer = float(self._cfg.get("liq_buffer_frac", -0.5 / lev))
        if levered_move <= liq_buffer:
            self._liquidated = True
        return levered_move

    def _kill(self, market: MarketSnapshot) -> tuple:
        if self._liquidated:
            return (True, "leverage loop liquidated (stETH/ETH ratio breach at leverage)")
        return (False, "")


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


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 9. ETH/STABLE LP (S78, #96) — DEX liquidity provision. Class C, shape impermanent_loss.
#    Yield SOURCE: real trading-fee APY on an ETH/stable pool (supplied via defi_apy["lp_eth_stable"]).
#    The position is 50% ETH, so it carries ETH DIRECTIONAL exposure + IMPERMANENT LOSS: a 50/50
#    constant-product LP's value scales as √(P/P_entry) of the deposit — it lags the upside (IL drag)
#    AND bleeds on the downside. The real, dated tail is an ETH crash. Fee is smooth carry; the √-mark
#    is the honest per-day IL/directional move on the REAL ETH price path (not a stamped shock).
#    VALIDATION-PENDING / refused-for-live until it clears the lifecycle + tail overlay like the rest.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class EthStableLP(_AggressiveBase):
    id = "lp_eth_stable"
    name = "ETH/stablecoin LP (S78): trading-fee APY + directional/IL tail"
    risk_class = "C"
    risk_shape = "il"
    yield_source = "DEX ETH/stable pool trading-fee APY; position is 50% ETH → directional + impermanent loss"
    headline_apy_pct = 18.0
    accrual_gap_is_safe_hold = True   # fee feed / price history may be sparse → pause, don't die

    def __init__(self) -> None:
        super().__init__()
        self._prev_eth: Optional[float] = None
        self._entry_eth: Optional[float] = None

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        # REAL trading-fee APY (harness-supplied from the live pool feed; fail-CLOSED if absent —
        # NO hardcoded fee yield). This is the LP's smooth carry leg.
        fee_apy = market.require("defi_apy", "lp_eth_stable")
        return fee_apy / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        # IMPERMANENT-LOSS + DIRECTIONAL mark. A 50/50 constant-product LP's value scales as
        # √(P/P_entry) of the deposit, so the daily LP value change on the REAL ETH price path is
        # √(P_today/P_prev) − 1: ~half the ETH move up (the IL drag vs holding) and a real, dated
        # DIP on an ETH crash — the honest tail, from the real price series, never a stamped number.
        import math as _m
        eth = market.require("eth_price")
        if self._entry_eth is None:
            self._entry_eth = eth
        if self._prev_eth is None:
            self._prev_eth = eth
            return 0.0
        prev = self._prev_eth
        self._prev_eth = eth
        self._mtm_source = "realized_backtest_series"
        return (_m.sqrt(eth / prev) - 1.0) if (prev and prev > 0) else 0.0

    def _kill(self, market: MarketSnapshot) -> tuple:
        # Tail kill: a deep LP-value drawdown from entry (ETH crash → LP bleed). Config-sourced,
        # no hardcode. LP value ratio = √(P/P_entry); a −25% default is a hostile directional/IL move.
        eth = market.require("eth_price")
        entry = self._entry_eth or eth
        lp_dd_pct = ((eth / entry) ** 0.5 - 1.0) * 100.0 if (entry and entry > 0) else 0.0
        thr = float(self._cfg.get("lp_drawdown_kill_pct", -25.0))
        if lp_dd_pct < thr:
            return (True, f"LP value {lp_dd_pct:.1f}% < {thr:.1f}% (ETH-crash / IL tail)")
        return (False, "")



# ──────────────────────────────────────────────────────────────────────────────────────────────────
# 10. LEVERED RESTAKING (S79, #96) — deeper-leverage staking loop. Class C, shape liquidation.
#     Yield SOURCE: real staking APY × 3× leverage − borrow cost. Deeper than LeverageLoop (2×): the
#     liquidation tail on the stETH/ETH ratio is amplified 3× — a small depeg cascades faster. Real
#     feed (restaking_apy["steth"] + lrt_ratio["steth"]); no real mark this tick → pure-accrual day.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class LeveredRestaking(_AggressiveBase):
    id = "levered_restaking"
    name = "Levered restaking (S79): 3\u00d7 staking loop"
    risk_class = "C"
    risk_shape = "liquidation"
    yield_source = "Staking APY \u00d7 3\u00d7 leverage \u2212 borrow cost (liquidation tail on the stETH/ETH ratio, amplified 3\u00d7)"
    headline_apy_pct = 11.0
    accrual_gap_is_safe_hold = True

    def __init__(self) -> None:
        super().__init__()
        self._liquidated = False

    def init(self, capital: float, config: dict) -> None:
        super().init(capital, config)
        self._liquidated = False

    def _daily_yield_pct(self, market: MarketSnapshot) -> float:
        try:
            staking = market.require("restaking_apy", "steth")
        except InvalidDataError:
            staking = market.require("defi_apy", "aave_v3_wsteth")
        lev = float(self._cfg.get("leverage", 3.0))
        borrow_apy = float(self._cfg.get("borrow_apy", 0.035))
        net_apy = staking * lev - borrow_apy * (lev - 1.0)
        self._cum_cost += self._equity * (borrow_apy * (lev - 1.0) / _DAYS_PER_YEAR)
        return net_apy / _DAYS_PER_YEAR

    def _mark_to_market_pct(self, market: MarketSnapshot) -> float:
        try:
            ratio = market.require("lrt_ratio", "steth")
        except InvalidDataError:
            return 0.0
        lev = float(self._cfg.get("leverage", 3.0))
        levered_move = self._ratio_mtm(ratio) * lev
        liq_buffer = float(self._cfg.get("liq_buffer_frac", -0.5 / lev))
        if levered_move <= liq_buffer:
            self._liquidated = True
        return levered_move

    def _kill(self, market: MarketSnapshot) -> tuple:
        if self._liquidated:
            return (True, "levered restaking liquidated (stETH/ETH ratio breach at 3x leverage)")
        return (False, "")


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
    EthStableLP,
    LeveredRestaking,
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
