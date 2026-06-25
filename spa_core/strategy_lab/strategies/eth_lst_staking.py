"""
spa_core/strategy_lab/strategies/eth_lst_staking.py — directional ETH staking (long LST).

STRATEGY (directional, beta ≈ 1 to ETH):
    HOLD a plain-staking LST (stETH/rETH, NOT an LRT) and earn the STAKING APY (~2.5%) ON TOP OF
    full ETH price exposure (beta ≈ 1 to ETH). The directional counterpart to the existing
    delta-neutral eth_lst_neutral: same SAFE asset (LSTs barely depeg vs the LRTs that died in
    2024), but UNHEDGED — you take the full ETH swing and bank the staking carry.

    Honest framing: the dominant P&L driver is the ETH price; the staking APY is a steady ~2.5%
    additive carry on top. This is "hold staked ETH" — a directional ETH play with a yield kicker,
    NOT a market-neutral yield product.

ISOLATED sleeve, OUTSIDE the stablecoin mandate: mandate="directional", is_advisory=True,
paper-only, SEPARATE from the go-live track.

Mark-to-market accounting (same idea as variant_d):
  - init() defers entry; the leg opens on the first step() at that day's LST unit price
    (qty0 = capital / entry_unit_price, where entry_unit_price = eth_price * lst_ratio).
  - Each step() marks the leg to the new LST unit price (equity = qty * unit_price → full ETH
    beta via the LST), then reinvests the day's staking yield by buying more qty at that price,
    so equity stays self-consistent (= qty * unit_price) with no separate cash drift.

The LST price + ratio + staking APY flow through the SAME snapshot maps the LRT variants use
(lrt_price_usd / lrt_eth_ratio / restaking_apy); for an LST "restaking_apy" is the plain staking
APY (see data/price_feed.py + data/restaking_feed.py SELECTORS for steth/reth).

KILL (FAIL-CLOSED): a drawdown from the high-water-mark equity beyond `drawdown_kill_pct` fires
the kill; ANY missing/invalid required datapoint also fires it (safe-hold), never a silent
continue.

stdlib only, deterministic. LLM FORBIDDEN.
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


class EthLstStaking(Strategy):
    """Directional ETH staking: long plain-staking LST (stETH/rETH), beta ≈ 1 to ETH."""

    id = "eth_lst_staking"
    name = "ETH LST Staking (directional long stETH/rETH + staking yield, β ≈ 1)"
    is_advisory = True
    mandate = "directional"

    def __init__(self) -> None:
        self._symbol: str = ""
        self._drawdown_kill_pct: float = 0.0
        self._qty: float = 0.0                          # LST units held
        self._entry_unit_price: Optional[float] = None  # entry USD/unit (eth_price * lst_ratio)
        self._unit_price: Optional[float] = None        # last marked USD/unit
        self._peak_equity: float = 0.0
        self._killed: bool = False
        self._cum_staking_usd: float = 0.0
        self._pending_capital: float = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        if config is None:
            raise InvalidDataError("eth_lst_staking: config block is required")
        symbol = config.get("lst_symbol")
        if not symbol:
            raise InvalidDataError("eth_lst_staking: config missing 'lst_symbol'")
        if "drawdown_kill_pct" not in config:
            raise InvalidDataError("eth_lst_staking: config missing 'drawdown_kill_pct'")
        if capital <= 0:
            raise InvalidDataError(
                f"eth_lst_staking: capital must be positive, got {capital!r}"
            )

        self._symbol = symbol
        self._drawdown_kill_pct = float(config["drawdown_kill_pct"])
        # Deferred entry: leg opens on the first step() at the live LST unit price.
        self._entry_unit_price = None
        self._unit_price = None
        self._qty = 0.0
        self._pending_capital = float(capital)
        self._peak_equity = 0.0

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if self._killed:
            return

        # Required: ETH price + LST/ETH ratio (→ the LST unit price, the directional driver) and
        # the staking APY. The LST flows through the SAME maps as the LRTs.
        eth_price = market.require("eth_price")
        ratio = market.require("lrt_ratio", self._symbol)
        staking_apy = market.require("restaking_apy", self._symbol)
        unit_price = eth_price * ratio

        # Establish the leg on first valid price if entry was deferred.
        if self._entry_unit_price is None:
            self._entry_unit_price = unit_price
            self._qty = self._pending_capital / unit_price
            self._unit_price = unit_price
            self._peak_equity = self._qty * unit_price

        # Mark-to-market FIRST: equity moves with the LST unit price (full ETH beta).
        self._unit_price = unit_price
        notional_marked = self._qty * unit_price

        # Accrue + reinvest the daily staking yield into more qty (self-consistent single leg).
        staking_usd = notional_marked * (float(staking_apy) / 365.0)
        if staking_usd:
            self._cum_staking_usd += staking_usd
            self._qty += staking_usd / unit_price

        eq = self._qty * unit_price
        if eq > self._peak_equity:
            self._peak_equity = eq

    # ── inspection ───────────────────────────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        if self._entry_unit_price is None:
            return []
        up = self._unit_price if self._unit_price is not None else self._entry_unit_price
        return [
            Position(
                asset=self._symbol,
                kind="spot",  # plain-staked LST held directionally (NOT 'lrt' — the safe path)
                notional_usd=round(self._qty * up, 2),
                qty=self._qty,
                entry_price=self._entry_unit_price,
                meta={
                    "cum_staking_usd": round(self._cum_staking_usd, 2),
                    "marked_unit_price": self._unit_price,
                    "kind_detail": "lst",
                },
            )
        ]

    def equity(self) -> float:
        if self._entry_unit_price is None:
            return 0.0
        up = self._unit_price if self._unit_price is not None else self._entry_unit_price
        return round(self._qty * up, 2)

    # ── kill check — FAIL-CLOSED ───────────────────────────────────────────────────────────
    def kill_check(self, market: MarketSnapshot) -> KillResult:
        ts = getattr(market, "date", "")
        if self._killed:
            return KillResult(triggered=True, reason="already killed (latched)", ts=ts)

        try:
            eth_price = market.require("eth_price")
            ratio = market.require("lrt_ratio", self._symbol)
            _ = market.require("restaking_apy", self._symbol)
        except InvalidDataError as exc:
            self._killed = True
            return KillResult(triggered=True, reason=f"fail-closed: {exc}", ts=ts)

        if self._entry_unit_price is None or self._peak_equity <= 0:
            return KillResult(triggered=False, reason="", ts=ts)

        cur_equity = self._qty * (eth_price * ratio)
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
        return StrategyMetrics(
            beta_to_eth=1.0,   # unhedged long LST → ≈ 1 to ETH by construction
            extra={
                "cum_staking_usd": round(self._cum_staking_usd, 2),
                "peak_equity": round(self._peak_equity, 2),
                "equity": self.equity(),
                "killed": self._killed,
                "lst_symbol": self._symbol,
            },
        )
