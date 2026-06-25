"""
spa_core/strategy_lab/strategies/btc_neutral.py — BTC Neutral (market-neutral BTC funding carry).

STRATEGY (delta-neutral to BTC, beta ≈ 0):
    Long a SAFE wrapped-BTC spot leg (tBTC/cbBTC) + a short BTC-perp leg sized to the spot
    (hedge_ratio ≈ 1). The BTC price move in the spot leg is cancelled by the short perp, so
    equity barely moves on a BTC swing (beta ≈ 0 to BTC). The surviving residual is the
    wrapper/BTC ratio drift (wrapper depeg) — which for a SAFE wrapper (tBTC decentralized /
    cbBTC regulated) is small by construction.

    Income = BTC perp FUNDING (the carry) + a small wrapped-BTC LENDING FLOOR (~0–1.2% — honest:
    BTC is rarely borrowed on-chain, so the floor is structurally low; see
    docs/RESEARCH_EXPANSION_2026-06-25.md §1 + spa_core/adapters/btc_lending.py). The funding
    carry is the primary driver; the lending floor is a small additive accrual on the spot.

WHY tBTC/cbBTC, NOT WBTC
    The real risk in BTC-DeFi is the WRAPPER (bridge/custody/governance), not the APY. We hold
    only the two SAFE wrappers and AVOID WBTC (governance overhang) and LBTC-restaking (points-
    driven bridge leverage). The wrapper-depeg kill is the explicit guard for the residual risk.

ACCOUNTING (per tick = one day) — identical mechanics to EthLstNeutral / Variant N:
  - wrapped-BTC spot value (USD) = wrapper_qty * btc_price * wrapper_ratio (carries BTC price
    AND the wrapper/BTC ratio).
  - Short perp price P&L over the tick = -(btc_price_new - btc_price_old) * perp_qty (pure BTC).
  - Net BTC-price exposure ≈ 0; the residual is the wrapper/BTC ratio drift (depeg).

FUNDING-SIGN CONVENTION
  A SHORT perp RECEIVES funding when funding_rate is POSITIVE (longs pay shorts), PAYS when
  NEGATIVE. Per settlement: pnl += funding_rate * perp_notional. Funding settles
  `funding_settles_per_day` times per tick. Cumulative funding tracked for funding_drag.

KILL CONDITIONS (FAIL-CLOSED — REUSE the depeg-median-smoothing pattern from eth_lst_neutral)
  (a) funding_rate continuously below `funding_kill_threshold` (X) for ≥ `funding_kill_hours` (N);
  (b) wrapper depeg: btc_wrapper_ratio dropped > `wrapper_depeg_kill_pct` (Y)% below the entry
      ratio, MEASURED ON A SMOOTHED, PERSISTENT signal (`depeg_median_window` trailing-median
      ticks + `depeg_persist_ticks` consecutive breaching ticks). A 1-day DeFiLlama daily-
      granularity timestamp-misalignment artifact (a lone ratio spike up/down) does NOT trip the
      kill; a REAL sustained depeg does. Same root + remedy as eth_lst_neutral (see that file +
      memory note "historical-apy-axis-misaligned");
  (c) any required market datapoint invalid → triggered=True (never silently continue).

mandate = "neutral", is_advisory = True. stdlib-only, deterministic. LLM FORBIDDEN.
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

_HOURS_PER_DAY = 24.0

# Conservative defaults for the depeg-signal smoothing/persistence (used only when a config omits
# the keys) — must still let a real sustained depeg through while rejecting a 1-day artifact.
_DEFAULT_DEPEG_MEDIAN_WINDOW = 3
_DEFAULT_DEPEG_PERSIST_TICKS = 2


def _trailing_median(values: List[float]) -> float:
    """Deterministic median of the (already short) trailing window. Empty → 0.0."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


class BtcNeutral(Strategy):
    """BTC Neutral — long wrapped-BTC spot (tBTC/cbBTC) + short BTC perp (β ≈ 0 to BTC).

    Market-neutral BTC funding carry: collect the BTC perp funding with the BTC price hedged out,
    on a SAFE wrapper, plus a small honest lending floor."""

    id = "btc_neutral"
    name = "BTC Neutral (market-neutral BTC funding carry: tBTC/cbBTC + BTC perp short)"
    is_advisory = True
    mandate = "neutral"

    def __init__(self) -> None:
        # config-sourced thresholds (filled in init(); never hardcoded)
        self._wrapper_symbol: str = ""
        self._hedge_ratio: float = 0.0
        self._funding_kill_threshold: float = 0.0
        self._funding_kill_hours: float = 0.0
        self._wrapper_depeg_kill_pct: float = 0.0
        self._depeg_median_window: int = _DEFAULT_DEPEG_MEDIAN_WINDOW
        self._depeg_persist_ticks: int = _DEFAULT_DEPEG_PERSIST_TICKS
        self._funding_settles_per_day: int = 0
        self._gas_usd: float = 0.0
        self._slippage_bps: float = 0.0
        self._rebalance_bps: float = 0.0

        # book state
        self._capital: float = 0.0
        self._equity: float = 0.0
        self._cash: float = 0.0  # accrued funding/lending/costs (USD), not price-exposed

        # wrapped-BTC spot leg
        self._wrapper_qty: float = 0.0
        self._entry_btc: float = 0.0       # BTC price at entry
        self._entry_ratio: float = 0.0     # wrapper/BTC ratio at entry (the "peg" reference)

        # short BTC perp leg
        self._perp_qty: float = 0.0
        self._perp_notional_entry: float = 0.0
        self._mark_btc: float = 0.0        # last BTC price the perp was marked at

        # running trackers
        self._cum_funding: float = 0.0     # cumulative funding P&L (USD); + = received
        self._cum_lending: float = 0.0     # cumulative lending-floor accrual (USD)
        self._perp_pnl: float = 0.0        # cumulative short-perp PRICE P&L (USD)
        self._sub_threshold_hours: float = 0.0
        self._ratio_window: List[float] = []
        self._depeg_streak: int = 0
        self._initialised = False
        self._killed = False
        self._kill_reason = ""

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        if config is None:
            raise InvalidDataError("btc_neutral: config block is required")
        self._capital = float(capital)
        if self._capital <= 0:
            raise InvalidDataError(f"btc_neutral: capital must be positive, got {capital!r}")

        self._wrapper_symbol = str(config["wrapper_symbol"])
        self._hedge_ratio = float(config["hedge_ratio"])
        self._funding_kill_threshold = float(config["funding_kill_threshold"])
        self._funding_kill_hours = float(config["funding_kill_hours"])
        self._wrapper_depeg_kill_pct = float(config["wrapper_depeg_kill_pct"])
        self._depeg_median_window = max(
            1, int(config.get("depeg_median_window", _DEFAULT_DEPEG_MEDIAN_WINDOW))
        )
        self._depeg_persist_ticks = max(
            1, int(config.get("depeg_persist_ticks", _DEFAULT_DEPEG_PERSIST_TICKS))
        )

        self._funding_settles_per_day = int(config["funding_settles_per_day"])
        self._gas_usd = float(config["gas_usd_per_rebalance"])
        self._slippage_bps = float(config["slippage_bps"])
        self._rebalance_bps = float(config["rebalance_bps"])

        self._equity = self._capital
        self._cash = 0.0
        self._initialised = True
        # Legs open lazily on the first step() once we have a real BTC price + wrapper ratio.

    def _open_legs(self, btc_price: float, ratio: float) -> None:
        wrapper_unit_price = btc_price * ratio  # USD per wrapper unit
        self._wrapper_qty = self._capital / wrapper_unit_price
        self._entry_btc = btc_price
        self._entry_ratio = ratio

        self._perp_notional_entry = self._capital * self._hedge_ratio
        self._perp_qty = self._perp_notional_entry / btc_price  # BTC units shorted
        self._mark_btc = btc_price

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if not self._initialised:
            raise InvalidDataError("BtcNeutral.step before init")
        if self._killed:
            return  # safe-hold

        # Required datapoints — fail-CLOSED. lending floor is OPTIONAL (0% is a legitimate read).
        try:
            btc_price = market.require("btc_price")
            ratio = market.require("btc_wrapper_ratio", self._wrapper_symbol)
            funding = market.require("btc_funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return
        lending_apy, has_lending = market.get_btc_lending_apy(self._wrapper_symbol)

        first_tick = self._wrapper_qty == 0.0
        if first_tick:
            self._open_legs(btc_price, ratio)

        spot_value = self._wrapper_qty * btc_price * ratio

        # 1) small honest lending floor on the spot notional (decimal annual / 365). Optional.
        if has_lending and lending_apy:
            lending_usd = spot_value * (float(lending_apy) / 365.0)
            self._cash += lending_usd
            self._cum_lending += lending_usd

        # 2) perp funding — a SHORT RECEIVES funding when funding_rate is POSITIVE.
        per_settle = funding * self._perp_notional_entry
        tick_funding = per_settle * self._funding_settles_per_day
        self._cash += tick_funding
        self._cum_funding += tick_funding

        # 3) mark-to-market the short perp INCREMENTALLY vs the last mark (pure BTC move).
        if not first_tick:
            self._perp_pnl += -(btc_price - self._mark_btc) * self._perp_qty
        self._mark_btc = btc_price

        # 4) rebalance the hedge if spot/perp notional drift exceeds the band (charge cost).
        target = spot_value * self._hedge_ratio
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
            self._perp_qty = target / btc_price

        # equity invariant: spot value (BTC price + depeg) + short-perp price P&L (pure BTC,
        # cancels the spot's BTC-price move) + cash (funding+lending−costs). β to BTC ≈ 0.
        self._equity = round(spot_value + self._perp_pnl + self._cash, 2)

    # ── inspection ───────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        if not self._initialised or self._wrapper_qty == 0.0:
            return [Position(asset="cash", kind="cash", notional_usd=round(self._capital, 2))]
        return [
            Position(
                asset=self._wrapper_symbol,
                kind="spot",  # SAFE wrapped-BTC spot (tBTC/cbBTC)
                notional_usd=round(self._wrapper_qty * self._mark_btc * self._entry_ratio, 2),
                qty=self._wrapper_qty,
                entry_price=self._entry_btc * self._entry_ratio,
                meta={"entry_ratio": self._entry_ratio, "kind_detail": "wrapped_btc"},
            ),
            Position(
                asset="btc_perp",
                kind="perp_short",
                notional_usd=round(self._perp_notional_entry, 2),
                qty=self._perp_qty,
                entry_price=self._entry_btc,
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
            ratio = market.require("btc_wrapper_ratio", self._wrapper_symbol)
            funding = market.require("btc_funding")
        except InvalidDataError as exc:
            self._killed = True
            self._kill_reason = f"fail-closed: {exc}"
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (a) funding continuously sub-threshold for ≥ N hours (each tick = a full day).
        hours_this_tick = _HOURS_PER_DAY if self._funding_settles_per_day > 0 else 0.0
        if funding < self._funding_kill_threshold:
            self._sub_threshold_hours += hours_this_tick
        else:
            self._sub_threshold_hours = 0.0
        if self._sub_threshold_hours >= self._funding_kill_hours:
            self._killed = True
            self._kill_reason = (
                f"BTC funding < {self._funding_kill_threshold} for "
                f"{self._sub_threshold_hours:.0f}h ≥ {self._funding_kill_hours:.0f}h"
            )
            return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        # (b) wrapper depeg vs entry/peg ratio — SMOOTHED + PERSISTENT (rejects 1-day artifacts).
        self._ratio_window.append(ratio)
        if len(self._ratio_window) > self._depeg_median_window:
            self._ratio_window = self._ratio_window[-self._depeg_median_window :]
        if self._entry_ratio > 0:
            smoothed = _trailing_median(self._ratio_window)
            drop_pct = (self._entry_ratio - smoothed) / self._entry_ratio * 100.0
            if drop_pct > self._wrapper_depeg_kill_pct:
                self._depeg_streak += 1
            else:
                self._depeg_streak = 0
            if self._depeg_streak >= self._depeg_persist_ticks:
                self._killed = True
                self._kill_reason = (
                    f"BTC wrapper depeg {drop_pct:.2f}% > {self._wrapper_depeg_kill_pct:.2f}% "
                    f"for {self._depeg_streak} ticks ≥ {self._depeg_persist_ticks} "
                    f"(entry ratio {self._entry_ratio:.5f} → median {smoothed:.5f})"
                )
                return KillResult(triggered=True, reason=self._kill_reason, ts=ts)

        return KillResult(triggered=False, reason="", ts=ts)

    # ── metrics (live partials) ─────────────────────────────────────────────────────────────
    def metrics(self) -> StrategyMetrics:
        net_pnl = self._equity - self._capital if self._capital else 0.0
        net_apy_pct: Optional[float] = None
        funding_drag_pct: Optional[float] = None
        if self._capital:
            net_apy_pct = round(net_pnl / self._capital * 100.0, 4)
            funding_drag_pct = round(self._cum_funding / self._capital * 100.0, 4)
        return StrategyMetrics(
            net_apy_pct=net_apy_pct,
            beta_to_eth=0.0,                 # neutral; β to BTC is also ≈ 0 by construction
            funding_drag_pct=funding_drag_pct,
            extra={
                "cum_funding_usd": round(self._cum_funding, 2),
                "cum_lending_usd": round(self._cum_lending, 2),
                "cash_usd": round(self._cash, 2),
                "equity_usd": round(self._equity, 2),
                "sub_threshold_hours": self._sub_threshold_hours,
                "depeg_streak": self._depeg_streak,
                "killed": self._killed,
                "kill_reason": self._kill_reason,
                "wrapper_symbol": self._wrapper_symbol,
                "beta_to_btc": 0.0,
            },
        )
