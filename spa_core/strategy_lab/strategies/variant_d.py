"""
spa_core/strategy_lab/strategies/variant_d.py — Variant D: Directional Restaking.

A pure long-LRT (eETH/ezETH) sleeve with NO hedge. Income comes from three sources:
  1. restaking yield   (restaking_apy[lrt_symbol] / 365, accrued daily on notional),
  2. points            (optional points_apy_assumption / 365, if configured),
  3. ETH price movement (full upside AND downside — beta ≈ 1 to ETH via the LRT).

This is an ISOLATED directional sleeve that lives OUTSIDE the stablecoin mandate:
  mandate = "directional", is_advisory = True, paper-only, SEPARATE from the go-live track.

Mark-to-market accounting (the core idea):
  - init() buys a single LRT spot leg: qty0 = capital / entry_price.
  - Each step() marks the leg to the new LRT price (equity = qty * price → full ETH beta),
    then reinvests the day's restaking + points yield by buying more LRT qty at that price.
    Because yield is reinvested into qty, equity() stays = qty * current_price at all times
    (a single self-consistent leg, no separate cash drift to reconcile).

Kill logic is FAIL-CLOSED: a drawdown from the high-water-mark equity beyond drawdown_kill_pct
fires the kill; ANY missing/invalid required datapoint also fires the kill (safe state), never a
silent continue.

stdlib only, deterministic. LLM FORBIDDEN — no model calls anywhere in this file.
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


class VariantD(Strategy):
    """Directional restaking: long LRT, unhedged, beta ≈ 1 to ETH."""

    id = "variant_d"
    name = "Directional Restaking (long LRT, unhedged)"
    is_advisory = True
    mandate = "directional"

    def __init__(self) -> None:
        self._symbol: str = ""
        self._drawdown_kill_pct: float = 0.0       # Z (percent)
        self._points_apy: float = 0.0              # optional, decimal annual
        self._qty: float = 0.0                     # LRT units held
        self._entry_price: Optional[float] = None  # entry LRT price (for the Position leg)
        self._price: Optional[float] = None        # last marked LRT price
        self._peak_equity: float = 0.0             # high-water mark for drawdown kill
        self._killed: bool = False
        self._cum_restaking_usd: float = 0.0       # diagnostics: yield accrued to date
        self._cum_points_usd: float = 0.0
        self._pending_capital: float = 0.0         # capital awaiting deferred-entry leg open

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        """Open a single LRT spot leg with the full capital. Thresholds come from `config`
        (the SSOT variant_d block) — never hardcoded. Fail-CLOSED on a missing entry price."""
        if config is None:
            raise InvalidDataError("variant_d: config block is required")
        symbol = config.get("lrt_symbol")
        if not symbol:
            raise InvalidDataError("variant_d: config missing 'lrt_symbol'")
        if "drawdown_kill_pct" not in config:
            raise InvalidDataError("variant_d: config missing 'drawdown_kill_pct'")

        self._symbol = symbol
        self._drawdown_kill_pct = float(config["drawdown_kill_pct"])
        # points are OPTIONAL for this variant; accrue only if configured (else 0).
        pa = config.get("points_apy_assumption")
        self._points_apy = float(pa) if pa is not None else 0.0

        if capital <= 0:
            raise InvalidDataError(f"variant_d: capital must be positive, got {capital!r}")

        # The entry price must come from a real, valid market snapshot. The harness sets the
        # first market via init? No — init only has capital+config. We therefore require the
        # caller to have provided the entry price via config OR we defer to the first step().
        # The lab contract gives init() no market, so we record a deferred-entry sentinel and
        # establish the leg on the first step() at that day's LRT price.
        entry = config.get("entry_price")
        if entry is not None:
            ep = float(entry)
            if ep <= 0:
                raise InvalidDataError(f"variant_d: entry_price must be positive, got {ep!r}")
            self._entry_price = ep
            self._price = ep
            self._qty = capital / ep
            self._peak_equity = self.equity()
        else:
            # deferred: stash capital, establish leg on first step() at the live LRT price.
            self._entry_price = None
            self._price = None
            self._qty = 0.0
            self._pending_capital = float(capital)
            self._peak_equity = 0.0

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        """Advance one day. Fail-CLOSED: required datapoints missing → InvalidDataError
        (the harness/kill_check treat that as a kill, never a silent skip)."""
        if self._killed:
            return

        # Required: a valid LRT price for this symbol (the directional driver).
        price = market.require("lrt_price", self._symbol)

        # Establish the leg on first valid price if entry was deferred.
        if self._entry_price is None:
            self._entry_price = price
            self._qty = self._pending_capital / price
            self._price = price
            self._peak_equity = self._qty * price
            # fall through to accrue this day's yield too (full first day).

        # 1) Restaking yield — required datapoint, fail-closed if invalid.
        restaking_apy = market.require("restaking_apy", self._symbol)

        # 3) Mark-to-market FIRST: equity moves with the LRT price (full ETH beta).
        #    Recompute notional from the standing qty at the new price.
        self._price = price
        notional_marked = self._qty * price

        # 1+2) Accrue daily yield (restaking + optional points) on the marked notional, and
        #      reinvest it into more LRT qty at the current price (keeps the single leg
        #      self-consistent: equity == qty * price).
        daily_restaking = restaking_apy / 365.0
        restaking_usd = notional_marked * daily_restaking
        self._cum_restaking_usd += restaking_usd

        points_usd = 0.0
        if self._points_apy:
            daily_points = self._points_apy / 365.0
            points_usd = notional_marked * daily_points
            self._cum_points_usd += points_usd

        total_yield_usd = restaking_usd + points_usd
        if total_yield_usd:
            self._qty += total_yield_usd / price  # reinvest at current price

        # 4) Update the high-water mark for the drawdown kill.
        eq = self._qty * price
        if eq > self._peak_equity:
            self._peak_equity = eq

    # ── inspection ───────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        if self._entry_price is None:
            return []
        notional = self._qty * (self._price if self._price is not None else self._entry_price)
        return [
            Position(
                asset=self._symbol,
                kind="lrt",
                notional_usd=round(notional, 2),
                qty=self._qty,
                entry_price=self._entry_price,
                meta={
                    "cum_restaking_usd": round(self._cum_restaking_usd, 2),
                    "cum_points_usd": round(self._cum_points_usd, 2),
                    "marked_price": self._price,
                },
            )
        ]

    def equity(self) -> float:
        if self._entry_price is None:
            return 0.0
        px = self._price if self._price is not None else self._entry_price
        return round(self._qty * px, 2)

    # ── kill check — FAIL-CLOSED ───────────────────────────────────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        """Fire (and latch) if drawdown from peak equity exceeds Z%, OR any required datapoint
        is invalid/missing (fail-closed → safe state)."""
        ts = getattr(market, "date", "")
        if self._killed:
            return KillResult(triggered=True, reason="already killed (latched)", ts=ts)

        # Required datapoints must be present — fail-closed on any gap.
        try:
            price = market.require("lrt_price", self._symbol)
            _ = market.require("restaking_apy", self._symbol)
        except InvalidDataError as exc:
            self._killed = True
            return KillResult(triggered=True, reason=f"fail-closed: {exc}", ts=ts)

        # If the leg isn't established yet (deferred entry, no step run), nothing to kill on.
        if self._entry_price is None or self._peak_equity <= 0:
            return KillResult(triggered=False, reason="", ts=ts)

        cur_equity = self._qty * price
        drawdown_pct = (self._peak_equity - cur_equity) / self._peak_equity * 100.0
        if drawdown_pct > self._drawdown_kill_pct:
            self._killed = True
            return KillResult(
                triggered=True,
                reason=(
                    f"drawdown {drawdown_pct:.2f}% > kill {self._drawdown_kill_pct:.2f}% "
                    f"(peak={self._peak_equity:.2f}, equity={cur_equity:.2f})"
                ),
                ts=ts,
            )
        return KillResult(triggered=False, reason="", ts=ts)

    # ── live partial metrics ───────────────────────────────────────────────────────────────
    def metrics(self) -> StrategyMetrics:
        """Live partials. Full set computed by metrics.py from the equity/event series."""
        # net_apy estimate = configured restaking + points (price P&L is captured separately
        # by realized return; this partial reflects the carry component).
        net_apy_pct: Optional[float] = None
        if self._entry_price is not None:
            net_apy_pct = round(self._points_apy * 100.0, 4)  # points carry; restaking is per-tick live
        return StrategyMetrics(
            net_apy_pct=net_apy_pct,
            beta_to_eth=1.0,  # unhedged long LRT → ≈ 1 by construction
            extra={
                "cum_restaking_usd": round(self._cum_restaking_usd, 2),
                "cum_points_usd": round(self._cum_points_usd, 2),
                "peak_equity": round(self._peak_equity, 2),
                "equity": self.equity(),
                "killed": self._killed,
            },
        )
