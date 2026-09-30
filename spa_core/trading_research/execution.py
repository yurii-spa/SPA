"""Execution MODELS — simulation only. Nothing here talks to an exchange.

Timing (the anti-look-ahead contract, shared by backtest and forward paper):
    a target computed from bar t's CLOSE is filled at bar t+1's OPEN.
Costs are charged on traded notional: fee + slippage, in basis points per side.

    spot_long   cash → BTC → cash; exposure 0 or 1; no borrowing, no shorting, no funding.
    perp_ls_1x  USDⓈ-M perpetual PAPER model: a FIXED-size position of 1× equity at entry, long or
                short (isolated);
                funding charged at every funding timestamp inside the bar (long pays a positive
                rate, short receives it); liquidation modelled from entry price, leverage and
                maintenance margin. Real futures execution does not exist and is not enabled.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ExecModel:
    name: str
    version: int
    fee_bps: float
    slippage_bps: float
    allow_short: bool
    leverage: float = 1.0
    maintenance_margin: float = 0.005
    funding: bool = False

    @property
    def cost_per_side(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 10_000.0


EXEC_MODELS: Dict[str, ExecModel] = {
    # Binance spot taker 10 bps; 5 bps slippage for BTCUSDT market orders at research size.
    "spot_long": ExecModel("spot_long", 2, fee_bps=10.0, slippage_bps=5.0, allow_short=False),
    # Binance USDⓈ-M taker 5 bps; 5 bps slippage; funding from the public funding history.
    "perp_ls_1x": ExecModel("perp_ls_1x", 2, fee_bps=5.0, slippage_bps=5.0, allow_short=True,
                            leverage=1.0, funding=True),
}


def liquidation_price(base: float, qty: float, entry: float, mm: float) -> Optional[float]:
    """Price at which a FIXED-size position's equity falls to the maintenance margin of its notional.

    equity(p) = base + qty·(p − entry); liquidation when equity(p) ≤ mm·|qty|·p.
    Long (qty > 0): p = (qty·entry − base) / (qty·(1 − mm)) — for a 1× long this is ≤ 0: unreachable.
    Short (qty < 0): p = (base − qty·entry) / (|qty|·(1 + mm)) — for a 1× short ≈ 1.99 × entry."""
    if qty > 0:
        p = (qty * entry - base) / (qty * (1 - mm))
        return p if p > 0 else None
    if qty < 0:
        return (base - qty * entry) / (-qty * (1 + mm))
    return None


@dataclass
class State:
    """A paper book: FIXED position size from entry (not re-sized every bar).

    equity = base + qty·(price − ref). A short therefore loses exactly what a real short loses as the
    price rises (the review of 2026-09-30 found the earlier per-bar re-scaling let a liquidated 1× short
    keep half its equity). Spot long is the same formula with qty = equity/price at entry."""
    equity: float = 1.0
    position: int = 0              # side for reporting: -1 / 0 / +1
    qty: float = 0.0               # signed units of the asset
    base: float = 1.0              # equity right after entry (fees paid), before any mark
    ref: Optional[float] = None    # entry price
    entry_eq: Optional[float] = None   # equity BEFORE the entry fee — a trade's return includes both fees
    liq: Optional[float] = None


def _mark(st: State, px: float) -> float:
    return st.base + st.qty * (px - st.ref) if st.qty else st.equity


def step(st: State, bar, prev_close: float, want: int, model: ExecModel, *,
         funding_rates: Sequence[float] = (), cost_mult: float = 1.0) -> dict:
    """Advance ONE bar: mark at this bar's open, fill `want` at the open (after a gap-through-liquidation
    check), check liquidation inside the bar, mark to close, charge funding on the notional.
    Shared verbatim by the backtest and the forward paper (one semantics, two users)."""
    c = model.cost_per_side * cost_mult
    ev = {"fill_price": None, "cost": 0.0, "funding": 0.0, "trade": None, "liquidated": False}
    if not model.allow_short and want < 0:
        want = 0

    def close_position(px: float, liquidated: bool = False) -> None:
        st.equity = max(0.0, _mark(st, px))
        if not liquidated:
            fee = abs(st.qty) * px * c
            st.equity -= fee
            ev["cost"] += fee
        ev["trade"] = {"side": st.position, "entry_px": st.ref, "exit_px": px,
                       "ret": st.equity / st.entry_eq - 1 if st.entry_eq else None,
                       "exit_time": bar.open_time, **({"liquidated": True} if liquidated else {})}
        st.qty, st.position, st.ref, st.entry_eq, st.liq = 0.0, 0, None, None, None
        st.base = st.equity

    # a gap through the liquidation price is liquidated AT THE OPEN, never booked as a gain
    if st.qty and st.liq is not None and ((st.qty > 0 and bar.open <= st.liq) or (st.qty < 0 and bar.open >= st.liq)):
        close_position(bar.open, liquidated=True)
        ev["liquidated"] = True
    elif st.qty:
        st.equity = _mark(st, bar.open)
    if want != st.position:
        if st.position != 0:
            close_position(bar.open)
        if want != 0 and st.equity > 0:
            st.entry_eq = st.equity
            notional = st.equity * model.leverage
            fee = notional * c
            st.equity -= fee
            ev["cost"] += fee
            st.qty = want * notional / bar.open
            st.position, st.ref, st.base = want, bar.open, st.equity
            st.liq = liquidation_price(st.base, st.qty, st.ref, model.maintenance_margin) if model.allow_short else None
        ev["fill_price"] = bar.open
    if st.qty and st.liq is not None and ((st.qty > 0 and bar.low <= st.liq) or (st.qty < 0 and bar.high >= st.liq)):
        close_position(st.liq, liquidated=True)
        ev["liquidated"] = True
    elif st.qty:
        st.equity = _mark(st, bar.close)
    if model.funding and st.qty:
        for rate in funding_rates:
            paid = st.qty * bar.close * rate          # long pays a positive rate on its notional
            st.base -= paid
            st.equity -= paid
            ev["funding"] += paid
    return ev


def funding_in_bar(funding, fts, open_time: int, tf_ms: int) -> List[float]:
    if not funding:
        return []
    lo = bisect.bisect_right(fts, open_time)
    hi = bisect.bisect_right(fts, open_time + tf_ms)
    return [funding[k][1] for k in range(lo, hi)]


@dataclass
class SimResult:
    equity: List[float]            # at each bar close (index-aligned with bars)
    position: List[int]            # exposure held DURING each bar
    trades: List[dict]             # closed round trips
    cost_paid: float
    funding_paid: float
    liquidations: int


def simulate(bars: Sequence, targets: Sequence[int], model: ExecModel, *, tf_ms: int,
             funding: Optional[List[Tuple[int, float]]] = None, cost_mult: float = 1.0,
             start: int = 0, equity0: float = 1.0) -> SimResult:
    fts = [f[0] for f in funding] if funding else []
    st = State(equity=equity0)
    res = SimResult([], [], [], 0.0, 0.0, 0)
    for i, b in enumerate(bars):
        if i <= start:
            res.equity.append(st.equity); res.position.append(0)
            continue
        ev = step(st, b, bars[i - 1].close, targets[i - 1], model,
                  funding_rates=funding_in_bar(funding, fts, b.open_time, tf_ms), cost_mult=cost_mult)
        res.cost_paid += ev["cost"]; res.funding_paid += ev["funding"]
        if ev["trade"]:
            res.trades.append(ev["trade"])
        res.liquidations += int(ev["liquidated"])
        res.equity.append(st.equity); res.position.append(st.position)
    return res
