"""
spa_core/strategy_lab/strategies/btc_lending_sleeve.py — directional BTC + lending floor.

STRATEGY (directional, beta ≈ 1 to BTC):
    HOLD a SAFE wrapped-BTC token (tBTC/cbBTC) and earn the wrapped-BTC LENDING APY (~0–1.2% —
    honest: BTC is rarely borrowed on-chain, so the supply floor is structurally LOW; see
    spa_core/adapters/btc_lending.py + docs/RESEARCH_EXPANSION_2026-06-25.md §1) ON TOP OF full
    BTC price exposure (beta ≈ 1 to BTC). This is "hold BTC + earn the floor" — a low-yield,
    directional sleeve, NOT a yield play. We are explicit about that: the income is the small
    floor; the dominant P&L driver is the BTC price itself.

WHY tBTC/cbBTC, NOT WBTC
    The real risk is the WRAPPER (bridge/custody/governance), not the APY. We hold only the two
    SAFE wrappers (tBTC decentralized / cbBTC regulated) and AVOID WBTC (governance overhang).

ISOLATED sleeve, OUTSIDE the stablecoin mandate: mandate="directional", is_advisory=True,
paper-only, SEPARATE from the go-live track. The directional BTC counterpart to btc_neutral.

Mark-to-market accounting (same idea as variant_d):
  - init() defers entry; the leg opens on the first step() at that day's wrapped-BTC price
    (qty0 = capital / entry_unit_price, where entry_unit_price = btc_price * wrapper_ratio).
  - Each step() marks the leg to the new wrapped-BTC price (equity = qty * unit_price → full BTC
    beta), then reinvests the day's lending-floor accrual by buying more qty at that price, so
    equity stays self-consistent (= qty * unit_price) with no separate cash drift to reconcile.

KILL (FAIL-CLOSED): a drawdown from the high-water-mark equity beyond `drawdown_kill_pct` fires
the kill; ANY missing/invalid required datapoint also fires it (safe-hold), never a silent
continue. The lending APY is OPTIONAL (0% is a legitimate, expected reading — no accrual that day).

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


class BtcLendingSleeve(Strategy):
    """Directional BTC + lending floor: hold tBTC/cbBTC, earn the floor, beta ≈ 1 to BTC."""

    id = "btc_lending_sleeve"
    name = "BTC Lending Sleeve (hold tBTC/cbBTC + earn the lending floor, β ≈ 1)"
    is_advisory = True
    mandate = "directional"

    def __init__(self) -> None:
        self._symbol: str = ""
        self._drawdown_kill_pct: float = 0.0
        self._qty: float = 0.0                     # wrapped-BTC units held
        self._entry_unit_price: Optional[float] = None  # entry USD/unit (btc_price * ratio)
        self._unit_price: Optional[float] = None        # last marked USD/unit
        self._peak_equity: float = 0.0
        self._killed: bool = False
        self._cum_lending_usd: float = 0.0
        self._pending_capital: float = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────────────────
    def init(self, capital: float, config: dict) -> None:
        if config is None:
            raise InvalidDataError("btc_lending_sleeve: config block is required")
        symbol = config.get("wrapper_symbol")
        if not symbol:
            raise InvalidDataError("btc_lending_sleeve: config missing 'wrapper_symbol'")
        if "drawdown_kill_pct" not in config:
            raise InvalidDataError("btc_lending_sleeve: config missing 'drawdown_kill_pct'")
        if capital <= 0:
            raise InvalidDataError(
                f"btc_lending_sleeve: capital must be positive, got {capital!r}"
            )

        self._symbol = symbol
        self._drawdown_kill_pct = float(config["drawdown_kill_pct"])
        # Deferred entry: leg opens on the first step() at the live wrapped-BTC unit price.
        self._entry_unit_price = None
        self._unit_price = None
        self._qty = 0.0
        self._pending_capital = float(capital)
        self._peak_equity = 0.0

    # ── per-tick advance ─────────────────────────────────────────────────────────────────
    def step(self, market: MarketSnapshot) -> None:
        if self._killed:
            return

        # Required: a valid BTC price + wrapper ratio (→ the wrapped-BTC unit price, the driver).
        btc_price = market.require("btc_price")
        ratio = market.require("btc_wrapper_ratio", self._symbol)
        unit_price = btc_price * ratio

        # Establish the leg on first valid price if entry was deferred.
        if self._entry_unit_price is None:
            self._entry_unit_price = unit_price
            self._qty = self._pending_capital / unit_price
            self._unit_price = unit_price
            self._peak_equity = self._qty * unit_price

        # Lending floor is OPTIONAL (0% is a legitimate read → no accrual that day).
        lending_apy, has_lending = market.get_btc_lending_apy(self._symbol)

        # Mark-to-market FIRST: equity moves with the wrapped-BTC unit price (full BTC beta).
        self._unit_price = unit_price
        notional_marked = self._qty * unit_price

        # Accrue + reinvest the daily lending floor into more qty (keeps the single leg
        # self-consistent: equity == qty * unit_price).
        if has_lending and lending_apy:
            lending_usd = notional_marked * (float(lending_apy) / 365.0)
            self._cum_lending_usd += lending_usd
            self._qty += lending_usd / unit_price

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
                kind="spot",  # SAFE wrapped-BTC spot held directionally
                notional_usd=round(self._qty * up, 2),
                qty=self._qty,
                entry_price=self._entry_unit_price,
                meta={
                    "cum_lending_usd": round(self._cum_lending_usd, 2),
                    "marked_unit_price": self._unit_price,
                    "kind_detail": "wrapped_btc",
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
            btc_price = market.require("btc_price")
            ratio = market.require("btc_wrapper_ratio", self._symbol)
        except InvalidDataError as exc:
            self._killed = True
            return KillResult(triggered=True, reason=f"fail-closed: {exc}", ts=ts)

        if self._entry_unit_price is None or self._peak_equity <= 0:
            return KillResult(triggered=False, reason="", ts=ts)

        cur_equity = self._qty * (btc_price * ratio)
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
            beta_to_eth=0.0,   # no ETH exposure
            extra={
                "cum_lending_usd": round(self._cum_lending_usd, 2),
                "peak_equity": round(self._peak_equity, 2),
                "equity": self.equity(),
                "killed": self._killed,
                "wrapper_symbol": self._symbol,
                "beta_to_btc": 1.0,   # unhedged long wrapped-BTC → ≈ 1 to BTC by construction
            },
        )
