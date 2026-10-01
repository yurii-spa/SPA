"""spa_core/paper_trading/loop_book.py — Aggressive SIMULATED recursive-lending loop (PAPER).

Mandate ``aggressive-susde-loop-v1`` (ADR-533). One looped position on ONE Morpho Blue market
(sUSDe collateral, PYUSD debt, LLTV 0.915), modelled from that market's own primary data
(``morpho_market.observe``). Nothing here borrows: it is arithmetic over observations.

State of the position — two quantities, nothing else:

* ``collateral_units`` — sUSDe held as collateral. Its value is ``units × oracle price`` — the price
  this market LIQUIDATES at. Staking yield arrives through that price (sUSDe's share price grows);
  no APY is added on top (no double counting).
* ``debt_shares`` — Morpho borrow shares. Debt = ``shares × borrow share price``, the share price
  grown by the observed borrow APY since the market's ``lastUpdate`` — interest on the debt accrues
  exactly as the market accrues it, rate changes included.

Derived each run: ``LTV = debt / collateral value``, ``HF = collateral value × LLTV / debt``.

Supervision (EVERY run, hourly) — de-risk only, never adds:
  HF ≤ 1.00 ⇒ liquidation simulated: a liquidator repays the debt and seizes
             ``debt × LIF / price`` units (LIF from LLTV by Morpho Blue's formula);
  HF < 1.08 or the oracle-implied USDe price < 0.97 ⇒ full unwind at STRESS slippage;
  HF < 1.15 ⇒ deleverage back to the target LTV.
  Unmeasured inputs ⇒ NO action (an unmeasured run cannot justify a trade) and the run is counted;
  the book reports the gap — it does not value the position at an invented price.

Decision (once a day): enter only when every input is measured and the levered carry beats the
unlevered yield after the round-trip cost (mandate); exit on 3 consecutive days of negative carry.

PYUSD is taken at $1 — the loan asset's own USD peg is NOT measured here and every valuation says so.
Stdlib only, LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from typing import Optional

TARGET_LTV = 0.70
MAX_ENTRY_LTV = 0.75
DELEVER_HF = 1.15
EMERGENCY_HF = 1.08
UNDERLYING_FLOOR = 0.97          # oracle-implied USDe price in PYUSD
LOOP_SHARE = 0.50                 # loop equity ≤ 50 % of the book
MIN_SPREAD_PP = 0.5
MIN_EDGE_PP = 1.0
AMORTISE_DAYS = 90.0
MAX_UTILIZATION = 0.95
MIN_FREE_LIQUIDITY_MULT = 20.0
SWAP_COST = 0.0005
STRESS_MULT = 3.0
GAS_USD = 12.0
NEG_CARRY_DAYS = 3
YIELD_WINDOW_DAYS = 7
LOAN_USD_ASSUMPTION = "PYUSD valued at $1.00 — its USD peg is not measured by this model"
#: Measured 2026-10-01: oracle 0xE6212D05… priced sUSDe at 1.25029 PYUSD while the sUSDe share price
#: was 1.25091 USDe ⇒ the oracle values USDe at 0.99951 PYUSD — it carries a USDe price feed, not a
#: hard-coded $1, so a depeg reaches this market's collateral value (and our HF) through the oracle.
ORACLE_NOTE = "market oracle carries a USDe/USD feed (implied 0.9995 on 2026-10-01), not a fixed $1"
REENTRY_COOLDOWN_DAYS = 7


def _yr_frac(seconds: float) -> float:
    return max(0.0, seconds) / (365.0 * 86400.0)


def debt_per_share(obs: dict, now: datetime) -> Optional[float]:
    bsp, apy, lu = obs.get("borrow_share_price"), obs.get("borrow_apy_pct"), obs.get("last_update")
    if bsp is None or apy is None or lu is None:
        return None
    return float(bsp) * (1.0 + float(apy) / 100.0) ** _yr_frac(now.timestamp() - float(lu))


def valuation(sub: dict, obs: Optional[dict], now: datetime) -> dict:
    """Value the position on ``obs``. ``measured=False`` (with a reason) unless every input is."""
    if sub.get("status") != "open":
        return {"measured": True, "collateral_value": 0.0, "debt_value": 0.0, "equity": 0.0,
                "hf": None, "ltv": None}
    if not obs or not obs.get("ok"):
        return {"measured": False, "reason": "; ".join((obs or {}).get("missing") or ["no observation"])}
    dps = debt_per_share(obs, now)
    price = obs.get("collateral_price_in_loan")
    if dps is None or price is None:
        return {"measured": False, "reason": "price or debt share price not measured"}
    coll = float(sub["collateral_units"]) * float(price)
    debt = float(sub["debt_shares"]) * dps
    return {"measured": True, "collateral_value": round(coll, 6), "debt_value": round(debt, 6),
            "equity": round(coll - debt, 6), "ltv": (round(debt / coll, 6) if coll > 0 else None),
            "hf": (round(coll * float(obs["lltv"]) / debt, 6) if debt > 0 else None),
            "price": price, "debt_per_share": dps,
            "implied_underlying": obs.get("implied_underlying_price_in_loan"),
            "loan_usd": LOAN_USD_ASSUMPTION}


def _event(sub: dict, now: datetime, kind: str, **kw) -> dict:
    e = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": kind, **kw}
    sub.setdefault("events", []).append(e)
    sub["events"] = sub["events"][-200:]
    return e


def _close(sub: dict, now: datetime, kind: str, cash: float, **kw) -> dict:
    sub.update(status="flat", collateral_units=0.0, debt_shares=0.0)
    return _event(sub, now, kind, cash_out_usd=round(cash, 6), **kw)


def unwind(sub: dict, obs: dict, now: datetime, *, stress: bool, reason: str) -> dict:
    """Sell collateral, repay all debt, return the rest as cash. Bad debt is named, never hidden."""
    v = valuation(sub, obs, now)
    s = SWAP_COST * (STRESS_MULT if stress else 1.0)
    coll, debt = v["collateral_value"], v["debt_value"]
    gross = coll * (1.0 - s)
    if gross < debt:
        return _close(sub, now, "unwind_insolvent", 0.0, reason=reason, shortfall_usd=round(debt - gross, 6),
                      collateral_value=coll, debt_value=debt, stress=stress)
    cash = gross - debt - 2 * GAS_USD
    return _close(sub, now, "unwound", max(0.0, cash), reason=reason, collateral_value=coll,
                  debt_value=debt, cost_usd=round(coll * s + 2 * GAS_USD, 6), stress=stress)


def liquidate(sub: dict, obs: dict, now: datetime) -> dict:
    """Morpho Blue liquidation, simulated: the debt is repaid by a liquidator who seizes
    ``debt × LIF / price`` collateral units; the remainder is sold back at stress slippage."""
    v = valuation(sub, obs, now)
    price, lif = float(obs["collateral_price_in_loan"]), float(obs["liquidation_incentive_factor"])
    seized = min(float(sub["collateral_units"]), v["debt_value"] * lif / price)
    rest_units = float(sub["collateral_units"]) - seized
    bad_debt = max(0.0, v["debt_value"] - seized * price / lif)
    cash = max(0.0, rest_units * price * (1.0 - SWAP_COST * STRESS_MULT) - GAS_USD)
    return _close(sub, now, "liquidated", cash, seized_units=round(seized, 8), lif=lif,
                  bad_debt_usd=round(bad_debt, 6), hf=v["hf"], collateral_value=v["collateral_value"],
                  debt_value=v["debt_value"])


def deleverage(sub: dict, obs: dict, now: datetime) -> dict:
    """Sell collateral value x and repay with the proceeds until LTV = TARGET_LTV."""
    v = valuation(sub, obs, now)
    coll, debt = v["collateral_value"], v["debt_value"]
    s = SWAP_COST
    x = (debt - TARGET_LTV * coll) / ((1.0 - s) - TARGET_LTV)
    x = max(0.0, min(x, coll))
    repaid = x * (1.0 - s) - GAS_USD
    price, dps = float(v["price"]), float(v["debt_per_share"])
    sub["collateral_units"] = float(sub["collateral_units"]) - x / price
    sub["debt_shares"] = max(0.0, float(sub["debt_shares"]) - repaid / dps)
    after = valuation(sub, obs, now)
    return _event(sub, now, "deleveraged", sold_collateral_usd=round(x, 6), repaid_usd=round(repaid, 6),
                  cost_usd=round(x * s + GAS_USD, 6), hf_before=v["hf"], hf_after=after["hf"])


def supervise(sub: dict, obs: Optional[dict], now: datetime) -> dict:
    """EVERY run. De-risk only. Returns ``{"valuation", "action", "cash_out_usd"}``."""
    if sub.get("status") != "open":
        return {"valuation": valuation(sub, obs, now), "action": None, "cash_out_usd": 0.0}
    v = valuation(sub, obs, now)
    if not v["measured"]:
        sub["unmeasured_runs"] = int(sub.get("unmeasured_runs") or 0) + 1
        return {"valuation": v, "action": f"none — inputs unmeasured ({v['reason']})", "cash_out_usd": 0.0}
    sub["unmeasured_runs"] = 0
    hf, under = v["hf"], v.get("implied_underlying")
    if hf is not None and hf <= 1.0:
        e = liquidate(sub, obs, now)
        return {"valuation": v, "action": "liquidated", "cash_out_usd": e["cash_out_usd"]}
    if (hf is not None and hf < EMERGENCY_HF) or (under is not None and under < UNDERLYING_FLOOR):
        e = unwind(sub, obs, now, stress=True,
                   reason=f"emergency: HF {hf} / implied USDe {under}")
        return {"valuation": v, "action": "emergency_unwind", "cash_out_usd": e["cash_out_usd"]}
    if hf is not None and hf < DELEVER_HF:
        deleverage(sub, obs, now)
        after = valuation(sub, obs, now)
        _remember(sub, after, now)
        return {"valuation": after, "action": "deleveraged", "cash_out_usd": 0.0}
    _remember(sub, v, now)
    return {"valuation": v, "action": None, "cash_out_usd": 0.0}


def _remember(sub: dict, v: dict, now: datetime) -> None:
    """The last MEASURED valuation, taken AFTER any action of the run (the fallback for unmeasured runs)."""
    sub["last_valuation"] = {**{k: v[k] for k in ("collateral_value", "debt_value", "equity", "hf", "ltv")},
                             "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def collateral_yield_pct(sub: dict, hint_pct: Optional[float]) -> tuple[Optional[float], str]:
    """sUSDe yield from the position's OWN share-price observations (≥ 7 days), else the live hint."""
    h = sub.get("share_price_history") or []
    if len(h) >= 2:
        from datetime import date as _date
        try:
            last_d = _date.fromisoformat(h[-1][0])
            base = next((x for x in reversed(h[:-1])
                         if (last_d - _date.fromisoformat(x[0])).days >= YIELD_WINDOW_DAYS), None)
        except Exception:  # noqa: BLE001
            base = None
        if base:
            days = (last_d - _date.fromisoformat(base[0])).days
            a, b = float(base[1]), float(h[-1][1])
            if a > 0 and b > 0 and days > 0:
                return (((b / a) ** (365.0 / days) - 1.0) * 100.0,
                        f"own sUSDe share price over {days} d (dated observations)")
    if hint_pct is not None:
        return float(hint_pct), "live sUSDe APY from the orchestrator snapshot (bootstrap)"
    return None, "sUSDe yield not measured"


def economics(yield_pct: float, borrow_pct: float, ltv: float = TARGET_LTV) -> dict:
    lev = 1.0 / (1.0 - ltv)
    gross = yield_pct * lev - borrow_pct * (lev - 1.0)
    # The whole collateral (equity + debt) is converted on the way in (cash → sUSDe) and on the way
    # out (sUSDe → PYUSD), so the swap cost is on the COLLATERAL notional both ways — one basis for
    # entry, exit and this estimate (review 2026-10-01).
    round_trip = 2 * (lev * SWAP_COST) * 100.0                  # % of loop equity, in & out
    amort = round_trip * 365.0 / AMORTISE_DAYS
    return {"leverage": round(lev, 4), "levered_gross_pct": round(gross, 4),
            "round_trip_cost_pct_of_equity": round(round_trip, 4),
            "amortised_cost_pct": round(amort, 4), "levered_net_pct": round(gross - amort, 4),
            "spread_pp": round(yield_pct - borrow_pct, 4)}


def daily_decide(sub: dict, obs: Optional[dict], *, budget_usd: float, yield_hint_pct: Optional[float],
                 allow_new: bool, now: datetime) -> dict:
    """Once a day: record the share price, judge carry, maybe open or exit. Returns a decision."""
    if obs and obs.get("ok") and obs.get("collateral_share_price"):
        hist = sub.setdefault("share_price_history", [])
        day = now.strftime("%Y-%m-%d")
        if not hist or hist[-1][0] != day:
            hist.append([day, obs["collateral_share_price"]])
            sub["share_price_history"] = hist[-40:]
    y, ysrc = collateral_yield_pct(sub, yield_hint_pct)
    if not obs or not obs.get("ok"):
        return {"decision": "hold", "reason": "inputs unmeasured: " + "; ".join((obs or {}).get("missing") or ["none"]),
                "cash_in_usd": 0.0, "cash_out_usd": 0.0, "yield_pct": y, "yield_source": ysrc}
    b = float(obs["borrow_apy_pct"])
    if sub.get("status") == "open":
        if y is not None and y < b:
            sub["negative_carry_days"] = int(sub.get("negative_carry_days") or 0) + 1
        elif y is not None:
            sub["negative_carry_days"] = 0
        # y unmeasured ⇒ the counter neither advances nor resets: no evidence either way
        if sub["negative_carry_days"] >= NEG_CARRY_DAYS:
            e = unwind(sub, obs, now, stress=False, reason=f"negative carry {NEG_CARRY_DAYS} days")
            return {"decision": "exit", "reason": e["reason"], "cash_in_usd": 0.0,
                    "cash_out_usd": e["cash_out_usd"], "yield_pct": y, "yield_source": ysrc}
        return {"decision": "hold", "reason": "position open; carry checked", "cash_in_usd": 0.0,
                "cash_out_usd": 0.0, "yield_pct": y, "yield_source": ysrc, "borrow_pct": b}
    reasons = []
    if not allow_new:
        reasons.append("CIO directive: no new positions")
    if y is None:
        reasons.append(ysrc)
    econ = economics(y, b) if y is not None else None
    if econ:
        if econ["spread_pp"] < MIN_SPREAD_PP:
            reasons.append(f"spread {econ['spread_pp']:.3f} pp < {MIN_SPREAD_PP} pp")
        if econ["levered_net_pct"] < y + MIN_EDGE_PP:
            reasons.append(f"levered net {econ['levered_net_pct']:.3f} % < unlevered {y:.3f} % + {MIN_EDGE_PP} pp")
    under = obs.get("implied_underlying_price_in_loan")
    if under is None or under < UNDERLYING_FLOOR:
        reasons.append(f"implied USDe {under} below the {UNDERLYING_FLOOR} floor (or unmeasured)")
    last_exit = next((e for e in reversed(sub.get("events") or [])
                      if e.get("event") in ("unwound", "unwind_insolvent", "liquidated")), None)
    if last_exit:
        try:
            age_d = (now - datetime.fromisoformat(str(last_exit["at"]).replace("Z", "+00:00"))).total_seconds() / 86400.0
        except Exception:  # noqa: BLE001
            age_d = 0.0
        if age_d < REENTRY_COOLDOWN_DAYS:
            reasons.append(f"cooldown: {last_exit['event']} {age_d:.1f} d ago < {REENTRY_COOLDOWN_DAYS} d")
    util, free = obs.get("utilization"), obs.get("available_liquidity")
    debt_needed = budget_usd * TARGET_LTV / (1.0 - TARGET_LTV)
    if util is None or util > MAX_UTILIZATION:
        reasons.append(f"utilisation {util} > {MAX_UTILIZATION}")
    if free is None or free < MIN_FREE_LIQUIDITY_MULT * debt_needed:
        reasons.append(f"free liquidity {free} < {MIN_FREE_LIQUIDITY_MULT:.0f}× borrow {debt_needed:,.0f}")
    if budget_usd < 1_000.0:
        reasons.append("loop budget below $1,000")
    if reasons:
        return {"decision": "hold", "reason": "; ".join(reasons), "economics": econ, "cash_in_usd": 0.0,
                "cash_out_usd": 0.0, "yield_pct": y, "yield_source": ysrc, "borrow_pct": b}
    # open: equity and debt are both converted into sUSDe — swap cost on the collateral notional
    cost = (budget_usd / (1.0 - TARGET_LTV)) * SWAP_COST + 3 * GAS_USD
    equity_in = budget_usd - cost
    debt = equity_in * TARGET_LTV / (1.0 - TARGET_LTV)
    coll_value = equity_in + debt
    price, dps = float(obs["collateral_price_in_loan"]), debt_per_share(obs, now)
    sub.update(status="open", collateral_units=coll_value / price, debt_shares=debt / dps,
               negative_carry_days=0, unmeasured_runs=0,
               entry={"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "budget_usd": round(budget_usd, 2),
                      "equity_in_usd": round(equity_in, 2), "debt_usd": round(debt, 2),
                      "collateral_value_usd": round(coll_value, 2), "price": price,
                      "ltv": TARGET_LTV, "economics": econ, "yield_source": ysrc,
                      "borrow_apy_pct": b, "cost_usd": round(cost, 2)})
    _event(sub, now, "opened", **sub["entry"])
    return {"decision": "enter", "reason": "all entry conditions met", "economics": econ,
            "cash_in_usd": budget_usd, "cash_out_usd": 0.0, "yield_pct": y, "yield_source": ysrc,
            "borrow_pct": b}


STRESS_SCENARIOS = (
    ("usde_depeg_2", {"underlying_mult": 0.98}),
    ("usde_depeg_5", {"underlying_mult": 0.95}),
    ("usde_depeg_10", {"underlying_mult": 0.90}),
    ("usde_depeg_20", {"underlying_mult": 0.80}),
    ("usde_depeg_30", {"underlying_mult": 0.70}),
    ("borrow_spike_30pct_30d", {"borrow_apy_pct": 30.0, "days": 30}),
    ("yield_zero_60d", {"yield_pct": 0.0, "days": 60}),
)


def stress(sub: dict, obs: dict, now: datetime, *, yield_pct: float) -> list[dict]:
    """Deterministic what-ifs on the CURRENT position (or a hypothetical one at target LTV)."""
    base = valuation(sub, obs, now) if sub.get("status") == "open" else None
    if base is None or not base.get("measured") or not base.get("collateral_value"):
        coll, debt = 1.0 / (1.0 - TARGET_LTV), TARGET_LTV / (1.0 - TARGET_LTV)
        hypothetical = True
    else:
        coll, debt, hypothetical = base["collateral_value"], base["debt_value"], False
    lltv = float(obs.get("lltv") or 0.0)
    out = []
    for name, sc in STRESS_SCENARIOS:
        c, d = coll, debt
        if "underlying_mult" in sc:
            c = coll * sc["underlying_mult"]
        if "days" in sc:
            t = sc["days"] / 365.0
            d = debt * (1.0 + sc.get("borrow_apy_pct", float(obs.get("borrow_apy_pct") or 0.0)) / 100.0) ** t
            c = coll * (1.0 + sc.get("yield_pct", yield_pct) / 100.0) ** t
        hf = c * lltv / d if d > 0 else None
        base_under = float(obs.get("implied_underlying_price_in_loan") or 1.0)
        under_after = base_under * sc.get("underlying_mult", 1.0)
        out.append({"scenario": name, "hypothetical_unit_position": hypothetical,
                    "implied_underlying_after": round(under_after, 4),
                    "hf": (round(hf, 4) if hf is not None else None), "equity_change_pct":
                    round(((c - d) - (coll - debt)) / (coll - debt) * 100.0, 3) if coll > debt else None,
                    "liquidatable": bool(hf is not None and hf <= 1.0),
                    "emergency_unwind": bool((hf is not None and hf < EMERGENCY_HF)
                                             or under_after < UNDERLYING_FLOOR)})
    return out
