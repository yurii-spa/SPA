"""spa_core/capital_shadow/exchange_sim.py — deterministic local spot-exchange order simulator.

ADR-556 WP-S03: centralised trading has no sandbox and no keys, so a real-venue simulation does not
exist and MUST NOT be faked by quietly calling production. This is pure, local computation only: no
network, no exchange SDK, no keys. It validates an order against PUBLIC filters (lot size / step size,
tick size, min notional, fee bps) and fills it against a caller-supplied static order book. Every
record is labelled so it is never mistaken for a real fill.

# LLM_FORBIDDEN — a deterministic match against a given book, never a venue call.
"""
from __future__ import annotations

LABEL = "LOCAL_SIMULATOR — not a venue"
SIDE_BUY, SIDE_SELL = "BUY", "SELL"
SIDES = (SIDE_BUY, SIDE_SELL)
TYPE_MARKET, TYPE_LIMIT = "MARKET", "LIMIT"
TYPES = (TYPE_MARKET, TYPE_LIMIT)
#: review #15: a record's outcome must be nameable as ONE of these three, not inferred from
#: ``accepted``/``partial_fill`` separately — a partial fill was indistinguishable from a full one
#: before this field existed, and an unaffordable BUY was never checked at all.
STATUS_REJECTED = "REJECTED"
STATUS_SIMULATED = "SIMULATED"
STATUS_PARTIAL = "PARTIAL"
_EPS = 1e-9


def _round_to_step(value: float, step: float) -> float:
    if not step or step <= 0:
        return value
    return round(value / step) * step


def _reject(order: dict, reason: str) -> dict:
    return {"label": LABEL, "status": STATUS_REJECTED, "accepted": False, "reason": reason, "order": order,
            "fills": [], "filled_qty": 0.0, "avg_price": None, "fee_paid": 0.0, "notional": 0.0,
            "cash_before": order.get("cash"), "position_before": order.get("position"),
            "cash_after": None, "position_after": None, "partial_fill": False}


def simulate_order(order: dict, filters: dict, book: dict) -> dict:
    """Validate + fill ``order`` against the static ``book``; touches nothing but its arguments.

    ``order``: ``{symbol, side, type, quantity, price?, cash, position}``.
    ``filters``: ``{symbol?, lot_size?, step_size?, tick_size?, min_notional?, fee_bps?}`` — public
    exchange filters, never fetched here.
    ``book``: ``{"bids": [[price, qty], ...], "asks": [[price, qty], ...]}``, best level first —
    supplied by the caller; this function never fetches one.
    """
    symbol = order.get("symbol")
    side = order.get("side")
    order_type = order.get("type")
    quantity = order.get("quantity")
    cash = order.get("cash", 0.0)
    position = order.get("position", 0.0)

    if filters.get("symbol") and filters["symbol"] != symbol:
        return _reject(order, f"symbol mismatch: order={symbol!r} filters={filters.get('symbol')!r}")
    if side not in SIDES:
        return _reject(order, f"unknown side {side!r}")
    if order_type not in TYPES:
        return _reject(order, f"unknown order type {order_type!r}")
    if not isinstance(quantity, (int, float)) or quantity <= 0:
        return _reject(order, "quantity must be a positive number")

    step_size = filters.get("step_size") or filters.get("lot_size") or 0
    if step_size and abs(_round_to_step(quantity, step_size) - quantity) > _EPS:
        return _reject(order, f"quantity {quantity} violates step_size {step_size}")
    lot_size = filters.get("lot_size")
    if lot_size and quantity < lot_size:
        return _reject(order, f"quantity {quantity} below lot_size {lot_size}")

    limit_price = order.get("price")
    tick_size = filters.get("tick_size") or 0
    if order_type == TYPE_LIMIT:
        if not isinstance(limit_price, (int, float)) or limit_price <= 0:
            return _reject(order, "a LIMIT order needs a positive price")
        if tick_size and abs(_round_to_step(limit_price, tick_size) - limit_price) > _EPS:
            return _reject(order, f"price {limit_price} violates tick_size {tick_size}")

    levels = book.get("asks" if side == SIDE_BUY else "bids") or []
    fee_bps = filters.get("fee_bps", 0.0)
    min_notional = filters.get("min_notional", 0.0)

    remaining = float(quantity)
    fills = []
    for price, available_qty in levels:
        if remaining <= 0:
            break
        if order_type == TYPE_LIMIT:
            if side == SIDE_BUY and price > limit_price:
                break
            if side == SIDE_SELL and price < limit_price:
                break
        take = min(remaining, available_qty)
        if take <= 0:
            continue
        fills.append({"price": price, "qty": take})
        remaining -= take

    filled_qty = sum(f["qty"] for f in fills)
    if filled_qty <= 0:
        return _reject(order, "no liquidity at an acceptable price in the given book")

    notional = sum(f["price"] * f["qty"] for f in fills)
    avg_price = notional / filled_qty
    if notional < min_notional:
        return _reject(order, f"notional {notional} below min_notional {min_notional}")

    fee_paid = notional * (fee_bps / 10_000.0)
    partial = filled_qty < quantity - _EPS

    # review #15: a BUY was never checked against the cash actually available, and a SELL was never
    # checked against the position actually held — a "SIMULATED" fill with insufficient cash/position
    # was indistinguishable from a real one. Both are rejected the same way validation above rejects
    # a bad filter, with the exact shortfall named.
    if side == SIDE_BUY:
        cost = notional + fee_paid
        if cost > cash + _EPS:
            return _reject(order, f"insufficient cash: need {cost}, have {cash}")
        cash_after = cash - cost
        position_after = position + filled_qty
    else:
        if filled_qty > position + _EPS:
            return _reject(order, f"insufficient position: need {filled_qty}, have {position}")
        cash_after = cash + notional - fee_paid
        position_after = position - filled_qty

    status = STATUS_PARTIAL if partial else STATUS_SIMULATED
    return {
        "label": LABEL, "status": status, "accepted": True, "reason": None, "partial_fill": partial,
        "order": order, "fills": fills, "filled_qty": filled_qty, "avg_price": avg_price,
        "fee_paid": fee_paid, "notional": notional, "cash_before": cash, "position_before": position,
        "cash_after": cash_after, "position_after": position_after,
    }
