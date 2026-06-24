"""
spa_core/strategy_lab/strategies/variant_n.py — Variant N (neutral / market-neutral restaking).

STRATEGY (delta-neutral to ETH, beta ≈ 0):
    LRT spot leg (eETH/ezETH) + a short ETH-perp leg sized to the spot.
    Income = restaking yield + points + (±) perp funding.
    ETH price exposure is hedged out by the short; the residual exposure is the LRT↔ETH
    depeg (the LRT/ETH ratio drifting away from its entry/peg value).

ACCOUNTING (per tick = one day)
  - LRT spot value (USD) = lrt_qty * eth_price * lrt_eth_ratio
        i.e. the LRT is priced as (ETH price) × (LRT/ETH ratio). So it moves with BOTH the
        ETH price AND the ratio (depeg).
  - Short perp P&L over the tick = -(eth_price_new - eth_price_old) * perp_qty
        The perp tracks PURE ETH (no LRT ratio). perp_qty = perp_notional_entry / entry_eth.
  - Net effect: the ETH-price move in the spot leg is (near-)cancelled by the perp leg when
    hedge_ratio ≈ 1, so equity barely moves on an ETH swing (beta ≈ 0). What survives is the
    ratio drift — the depeg — which the perp does NOT hedge. That is the intended residual.

FUNDING-SIGN CONVENTION
  A SHORT perp RECEIVES funding when funding_rate is POSITIVE (longs pay shorts) and PAYS
  when it is NEGATIVE. Per settlement: pnl += funding_rate * perp_notional. Funding settles
  `funding_settles_per_day` times per tick. Cumulative funding is tracked for funding_drag.

KILL CONDITIONS (FAIL-CLOSED)
  (a) funding_rate continuously below `funding_kill_threshold` (X) for ≥ `funding_kill_hours`
      (N) — consecutive sub-threshold time is accumulated across ticks (8h per settlement).
  (b) LRT depeg: lrt_eth_ratio dropped > `lrt_depeg_kill_pct` (Y)% below the entry ratio.
  (c) any required market datapoint invalid → triggered=True (never silently continue).

stdlib-only, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import List, Optional

from spa_core.strategy_lab.base import (
    InvalidDataError,
    KillResult,
    MarketSnapshot,
    Position,
    Strategy,
    StrategyMetrics,
)

# Hours represented by ONE perp funding settlement (24h day / settlements-per-day).
_HOURS_PER_DAY = 24.0


class VariantN(Strategy):
    """Variant N — neutral/market-neutral restaking (delta-neutral LRT + short ETH perp)."""

    id = "variant_n"
    name = "Neutral Restaking (delta-neutral LRT + perp short)"
    is_advisory = True
    mandate = "neutral"

    def __init__(self) -> None:
        # config-sourced thresholds (filled in init(); never hardcoded)
        self._lrt_symbol: str = ""
        self._hedge_ratio: float = 0.0
        self._funding_kill_threshold: float = 0.0
        self._funding_kill_hours: float = 0.0
        self._lrt_depeg_kill_pct: float = 0.0
        self._points_apy: float = 0.0
        self._funding_settles_per_day: int = 0
        self._gas_usd: float = 0.0
        self._slippage_bps: float = 0.0
        self._rebalance_bps: float = 0.0  # drift band before a hedge rebalance is forced

        # book state
        self._capital: float = 0.0
        self._equity: float = 0.0
        self._cash: float = 0.0  # accrued income/funding/costs (USD), not price-exposed

        # LRT spot leg
        self._lrt_qty: float = 0.0          # units of LRT held
        self._lrt_entry_eth: float = 0.0    # ETH price at entry
        self._lrt_entry_ratio: float = 0.0  # LRT/ETH ratio at entry (the "peg" reference)

        # short ETH perp leg
        self._perp_qty: float = 0.0         # ETH units shorted (positive magnitude)
        self._perp_notional_entry: float = 0.0
        self._mark_eth: float = 0.0         # last ETH price the perp was marked at

        # running trackers
        self._cum_funding: float = 0.0      # cumulative funding P&L (USD); + = received
        self._perp_pnl: float = 0.0         # cumulative short-perp PRICE P&L (USD), realized+marked
        self._sub_threshold_hours: float = 0.0  # consecutive hours funding < kill threshold
        self._initialised = False
        self._killed = False
        self._kill_reason = ""

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        self._capital = float(capital)

        self._lrt_symbol = str(config["lrt_symbol"])
        self._hedge_ratio = float(config["hedge_ratio"])
        self._funding_kill_threshold = float(config["funding_kill_threshold"])
        self._funding_kill_hours = float(config["funding_kill_hours"])
        self._lrt_depeg_kill_pct = float(config["lrt_depeg_kill_pct"])
        self._points_apy = float(config["points_apy_assumption"])

        # global-block params (cost + funding cadence) — passed through the same config dict
        self._funding_settles_per_day = int(config["funding_settles_per_day"])
        self._gas_usd = float(config["gas_usd_per_rebalance"])
        self._slippage_bps = float(config["slippage_bps"])
        self._rebalance_bps = float(config["rebalance_bps"])

        self._equity = self._capital
        self._cash = 0.0
        self._initialised = True
        # Legs are opened lazily on the first step() once we have an ETH price + ratio,
        # so entry references are real market values (no fabricated entry price).

    def _open_legs(self, eth_price: float, ratio: float) -> None:
        """Open the LRT spot + short ETH perp legs from the first valid market tick."""
        lrt_notional = self._capital
        lrt_unit_price = eth_price * ratio  # USD per LRT unit
        self._lrt_qty = lrt_notional / lrt_unit_price
        self._lrt_entry_eth = eth_price
        self._lrt_entry_ratio = ratio

        self._perp_notional_entry = self._capital * self._hedge_ratio
        self._perp_qty = self._perp_notional_entry / eth_price  # ETH units shorted
        self._mark_eth = eth_price

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if not self._initialised:
            raise InvalidDataError("VariantN.step before init")
        if self._killed:
            return  # safe-hold: once killed we stop trading/accruing

        # Required datapoints — fail-CLOSED. A missing one is a safe-hold (kill), no fabrication.
        try:
            eth_price = market.require("eth_price")
            ratio = market.require("lrt_ratio", self._lrt_symbol)
            restaking_apy = market.require("restaking_apy", self._lrt_symbol)
            funding = market.require("funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return

        first_tick = self._lrt_qty == 0.0
        if first_tick:
            self._open_legs(eth_price, ratio)

        # 1) restaking yield on the CURRENT LRT notional (daily fraction of decimal annual APY).
        lrt_value = self._lrt_qty * eth_price * ratio
        self._cash += lrt_value * (restaking_apy / 365.0)

        # 2) points accrual on the LRT notional.
        self._cash += lrt_value * (self._points_apy / 365.0)

        # 3) perp funding — settle N times this tick on the current perp notional. A SHORT
        #    RECEIVES funding when funding_rate is POSITIVE, PAYS when negative.
        per_settle = funding * self._perp_notional_entry
        tick_funding = per_settle * self._funding_settles_per_day
        self._cash += tick_funding
        self._cum_funding += tick_funding

        # 4) mark-to-market the short perp INCREMENTALLY vs the last mark (pure ETH move). This
        #    keeps perp P&L correct across rebalances (which change perp_qty). `_perp_pnl`
        #    holds price P&L only; `_cash` holds income/funding/costs only — no double count.
        if not first_tick:
            self._perp_pnl += -(eth_price - self._mark_eth) * self._perp_qty
        self._mark_eth = eth_price

        # 5) rebalance the hedge if spot/perp notional drift exceeds the band (charge cost).
        #    Done AFTER marking at the new price, so the realized P&L up to here is locked in.
        target = lrt_value * self._hedge_ratio
        band = self._perp_notional_entry * (self._rebalance_bps / 10_000.0)
        if (
            not first_tick
            and self._perp_notional_entry > 0
            and abs(target - self._perp_notional_entry) > band
        ):
            delta = abs(target - self._perp_notional_entry)
            cost = self._gas_usd + delta * (self._slippage_bps / 10_000.0)
            self._cash -= cost
            self._perp_notional_entry = target
            self._perp_qty = target / eth_price

        # equity invariant: LRT spot value (carries ETH price + depeg) + cumulative short-perp
        # price P&L (pure ETH, cancels the spot's ETH-price move) + cash (income+funding−costs).
        # Net ETH-price exposure ≈ 0; the surviving residual is the LRT/ETH ratio drift (depeg).
        self._equity = round(lrt_value + self._perp_pnl + self._cash, 2)

    # ── inspection ───────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        if not self._initialised or self._lrt_qty == 0.0:
            return [Position(asset="cash", kind="cash", notional_usd=round(self._capital, 2))]
        lrt_value = self._lrt_qty * self._mark_eth * self._lrt_entry_ratio
        return [
            Position(
                asset=self._lrt_symbol,
                kind="lrt",
                notional_usd=round(self._lrt_qty * self._mark_eth * self._lrt_entry_ratio, 2),
                qty=self._lrt_qty,
                entry_price=self._lrt_entry_eth * self._lrt_entry_ratio,
                meta={"entry_ratio": self._lrt_entry_ratio},
            ),
            Position(
                asset="eth_perp",
                kind="perp_short",
                notional_usd=round(self._perp_notional_entry, 2),
                qty=self._perp_qty,
                entry_price=self._lrt_entry_eth,
                meta={"cum_funding_usd": round(self._cum_funding, 2)},
            ),
        ]

    def equity(self) -> float:
        return round(self._equity, 2)

    # ── kill check (FAIL-CLOSED) ───────────────────────────────────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        ts = getattr(market, "date", "")
        if self._killed:
            return KillResult(triggered=True, reason=self._kill_reason or "killed", ts=ts)

        # (c) required datapoints — fail-closed on any invalid one.
        try:
            ratio = market.require("lrt_ratio", self._lrt_symbol)
            funding = market.require("funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (a) funding continuously sub-threshold for ≥ N hours.
        #     Each tick contributes `funding_settles_per_day` settlements; the per-tick funding
        #     value is one 8h rate, so a sub-threshold tick adds 24h (the whole day) of
        #     sub-threshold funding. We track consecutive sub-threshold time across ticks.
        if self._funding_settles_per_day > 0:
            hours_this_tick = _HOURS_PER_DAY  # a full day's worth of this funding observation
        else:
            hours_this_tick = 0.0
        if funding < self._funding_kill_threshold:
            self._sub_threshold_hours += hours_this_tick
        else:
            self._sub_threshold_hours = 0.0  # streak resets when funding recovers
        if self._sub_threshold_hours >= self._funding_kill_hours:
            self._killed = True
            self._kill_reason = (
                f"funding < {self._funding_kill_threshold} for "
                f"{self._sub_threshold_hours:.0f}h ≥ {self._funding_kill_hours:.0f}h"
            )
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (b) LRT depeg vs entry/peg ratio.
        if self._lrt_entry_ratio > 0:
            drop_pct = (self._lrt_entry_ratio - ratio) / self._lrt_entry_ratio * 100.0
            if drop_pct > self._lrt_depeg_kill_pct:
                self._killed = True
                self._kill_reason = (
                    f"LRT depeg {drop_pct:.2f}% > {self._lrt_depeg_kill_pct:.2f}% "
                    f"(entry ratio {self._lrt_entry_ratio:.5f} → {ratio:.5f})"
                )
                return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        return KillResult(triggered=False, reason="", ts=ts)

    # ── metrics (live partials) ─────────────────────────────────────────────────────────────
    def metrics(self) -> StrategyMetrics:
        net_pnl = self._equity - self._capital if self._capital else 0.0
        net_apy_pct: Optional[float] = None
        funding_drag_pct: Optional[float] = None
        if self._capital:
            # simple point-in-time net return (full annualised set computed by metrics.py)
            net_apy_pct = round(net_pnl / self._capital * 100.0, 4)
            funding_drag_pct = round(self._cum_funding / self._capital * 100.0, 4)
        return StrategyMetrics(
            net_apy_pct=net_apy_pct,
            beta_to_eth=0.0,                 # delta-neutral by construction
            funding_drag_pct=funding_drag_pct,
            extra={
                "cum_funding_usd": round(self._cum_funding, 2),
                "cash_usd": round(self._cash, 2),
                "equity_usd": round(self._equity, 2),
                "sub_threshold_hours": self._sub_threshold_hours,
                "killed": self._killed,
                "kill_reason": self._kill_reason,
            },
        )
