"""spa_core/paper_trading/pt_carry.py — Balanced fixed-rate part: Pendle PT held to maturity (PAPER).

The mechanic that makes Balanced different from floating lending (ADR-533, mandate
``balanced-fixed-carry-v1``): part of the book buys a principal token at a discount and holds it to
expiry, when it redeems at par in its accounting asset. The return is LOCKED at purchase — it does
not float with lending utilisation — and it is earned through the PT's PRICE only:

* a leg is ``units`` of PT; its value is ``units × mark``; the mark is the OBSERVED PT price, and is
  only updated when ``pendle_market`` accepts it (observed ≈ implied-derived). No APY is accrued on
  top of the price — the pull to par IS the yield (no double counting);
* at expiry the leg redeems at ``1.0`` accounting-asset unit per PT (USDS ≈ $1, evidenced by DAI
  convertibility) — the gain is realised then, not before;
* an unobserved mark is NOT re-marked: the leg keeps its last observed mark with ``mark_ok=False``,
  and the day reports ``degraded`` (invariant #17);
* buying pays the Pendle fee rate + 5 bp slippage + $12 gas, embedded in the units bought (the
  floating part pays ``bought_usd``; the PT leg is worth ``bought_usd − cost`` at purchase), so the
  caller must NOT charge ``cost_usd`` a second time — it is reported, not owed.

``daily_step`` is pure given its inputs (observation, benchmark, equity, dates) — it returns the
new sub-book and the cash flows; the cycle owns the book file. Paper only, LLM_FORBIDDEN, stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

TARGET_SHARE = 0.40           # fixed-rate part of equity (mandate)
PER_MARKET_SHARE = 0.25
MIN_DAYS = 21.0
MAX_DAYS = 270.0
MIN_LIQUIDITY_USD = 2_000_000.0
MAX_ORDER_SHARE_OF_LIQUIDITY = 0.02
MIN_IMPLIED_PCT = 3.0
BENCHMARK_TOLERANCE_PP = 1.0
SLIPPAGE = 0.0005
DEFAULT_FEE_RATE = 0.001       # Pendle market fee when the feed does not carry it
GAS_USD = 12.0
STOP_UNMEASURED_DAYS = 3


def _parse(s: object) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def value(sub: dict) -> float:
    return round(sum(float(l["units"]) * float(l["mark"]) for l in sub.get("legs") or []), 6)


def eligible(market: dict, *, benchmark_apy_pct: Optional[float]) -> tuple[bool, str]:
    """Entry gate for ONE market. Returns (ok, reason) — the reason is recorded either way."""
    if not market.get("listed"):
        return False, "market not listed in /markets/active"
    if not market.get("peg_evidence"):
        return False, "underlying has no evidenced USD peg"
    if not market.get("mark_ok"):
        return False, f"price not confirmed ({market.get('mark_reason')})"
    days = market.get("days_to_expiry")
    if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
        return False, f"{days} days to expiry outside [{MIN_DAYS:.0f}, {MAX_DAYS:.0f}]"
    liq = market.get("liquidity_usd")
    if liq is None or liq < MIN_LIQUIDITY_USD:
        return False, f"liquidity {liq} < ${MIN_LIQUIDITY_USD:,.0f}"
    iy = market.get("implied_apy_pct")
    if iy is None:
        return False, "implied APY not measured"
    if benchmark_apy_pct is None:
        return False, "floating benchmark not measured — the comparison cannot be made"
    floor = max(MIN_IMPLIED_PCT, benchmark_apy_pct - BENCHMARK_TOLERANCE_PP)
    if iy < floor:
        return False, f"implied {iy:.3f} % < floor {floor:.3f} % (benchmark {benchmark_apy_pct:.3f} %)"
    return True, f"implied {iy:.3f} % ≥ floor {floor:.3f} %"


def daily_step(sub: Optional[dict], obs: Optional[dict], *, equity_total: float,
               benchmark_apy_pct: Optional[float], allow_new: bool, now: datetime) -> dict:
    """One accounting day of the fixed-rate part.

    Returns ``{"sub": new_sub_book, "value_before", "value_after", "mark_pnl_usd",
    "bought_usd", "redeemed_usd", "sold_usd", "cost_usd", "events", "degraded", "decision"}``.
    Cash flows (``bought`` out of, ``redeemed``/``sold`` into) belong to the floating part.
    """
    sub = {"legs": [dict(l) for l in (sub or {}).get("legs") or []],
           "unmeasured_days": int((sub or {}).get("unmeasured_days") or 0)}
    markets = {m.get("market"): m for m in ((obs or {}).get("markets") or [])}
    events: list[dict] = []
    v_before = value(sub)
    mark_pnl = redeemed = sold = cost = 0.0
    degraded: list[str] = []
    if not obs or not obs.get("ok"):
        degraded.append(f"Pendle feed: {(obs or {}).get('reason') or 'no observation'}")

    keep = []
    for leg in sub["legs"]:
        exp = _parse(leg.get("expiry"))
        if exp is not None and now >= exp:
            proceeds = float(leg["units"]) * 1.0
            mark_pnl += proceeds - float(leg["units"]) * float(leg["mark"])
            redeemed += proceeds
            events.append({"event": "redeemed_at_par", "market": leg["market"], "units": leg["units"],
                           "proceeds_usd": round(proceeds, 2)})
            continue
        m = markets.get(leg["market"])
        if m and m.get("mark_ok"):
            new = float(m["pt_price_usd"])
            mark_pnl += float(leg["units"]) * (new - float(leg["mark"]))
            leg.update(mark=new, mark_at=m.get("pt_price_updated_at"), mark_ok=True)
        else:
            leg["mark_ok"] = False
            degraded.append(f"{leg['market']}: mark not observed — last observed mark kept")
        keep.append(leg)
    sub["legs"] = keep
    sub["unmeasured_days"] = sub["unmeasured_days"] + 1 if degraded else 0

    held_value = value(sub)
    target = TARGET_SHARE * equity_total
    decision = "hold"
    reasons: list[str] = []
    if not allow_new:
        reasons.append("CIO directive: no new positions")
    elif sub["unmeasured_days"] >= STOP_UNMEASURED_DAYS:
        reasons.append(f"feed unmeasured {sub['unmeasured_days']} days — no adds (stop condition)")
    elif held_value < target - 1.0:
        best = None
        for m in sorted(markets.values(), key=lambda x: -(x.get("implied_apy_pct") or 0.0)):
            ok, why = eligible(m, benchmark_apy_pct=benchmark_apy_pct)
            reasons.append(f"{m.get('underlying')} {m.get('market')}: {why}")
            if ok:
                best = m
                break
        if best:
            in_market = sum(float(l["units"]) * float(l["mark"]) for l in sub["legs"]
                            if l["market"] == best["market"])
            room = min(target - held_value, PER_MARKET_SHARE * equity_total - in_market,
                       MAX_ORDER_SHARE_OF_LIQUIDITY * float(best["liquidity_usd"]))
            if room > 100.0:
                fee = float(best.get("fee_rate") or DEFAULT_FEE_RATE)
                price = float(best["pt_price_usd"])
                trade_cost = room * (fee + SLIPPAGE) + GAS_USD
                units = (room - trade_cost) / price
                sub["legs"].append({"market": best["market"], "pt": best.get("pt"),
                                    "underlying": best.get("underlying"), "expiry": best.get("expiry"),
                                    "units": round(units, 8), "entry_price": price, "mark": price,
                                    "mark_at": best.get("pt_price_updated_at"), "mark_ok": True,
                                    "entry_date": now.strftime("%Y-%m-%d"),
                                    "entry_implied_apy_pct": best.get("implied_apy_pct"),
                                    "cost_basis_usd": round(room, 2)})
                cost += trade_cost
                decision = "buy"
                events.append({"event": "bought", "market": best["market"], "usd": round(room, 2),
                               "price": price, "implied_apy_pct": best.get("implied_apy_pct"),
                               "cost_usd": round(trade_cost, 2)})
            else:
                reasons.append("no room within the per-market / liquidity limits")
    else:
        reasons.append("fixed-rate part at its target")
    v_after = value(sub)
    # bought_usd = cash that left the floating part (gross of the trade cost)
    bought = sum(e["usd"] for e in events if e["event"] == "bought")
    return {"sub": sub, "value_before": round(v_before, 6), "value_after": round(v_after, 6),
            "mark_pnl_usd": round(mark_pnl, 6), "bought_usd": round(bought, 6),
            "redeemed_usd": round(redeemed, 6), "sold_usd": round(sold, 6), "cost_usd": round(cost, 6),
            "events": events, "degraded": degraded, "decision": decision, "reasons": reasons,
            "target_usd": round(target, 2)}
