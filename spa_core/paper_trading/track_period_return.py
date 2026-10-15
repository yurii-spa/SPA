"""spa_core/paper_trading/track_period_return.py — the paper track's return over its ACTUAL period.

P1 Wave 2 (owner/ARB 2026-10-08, step 3): the public metric is the paper return over the period
that was actually observed, computed from the ledger and proven from it; an annualised figure is
a separate, labelled equivalent that needs the owner's approval.

Method, decided by evidence in the ledger (``data/equity_curve_daily.json``), not by choice:

* **Window.** Start = the CLOSE of the first evidenced bar (the first NAV the track recorded as
  evidence — the open of that bar is the close of an excluded, reconstructed bar). End = the close
  of the last evidenced bar.
* **External flows.** A bar's NAV may move only by its own yield minus its own costs, and must open
  at the previous evidenced close. Any residual is an external flow (or an unexplained jump, which
  is counted the same way — never silently absorbed).
* **No flows ⇒ ``NAV_RATIO``:** ``NAV_end / NAV_start − 1``. With no flows the time-weighted and
  money-weighted returns are the same number; both are still reported, separately.
* **Flows ⇒ ``TWR``:** the product of per-bar ``close / open`` (the open is the valuation AFTER the
  flow), and an MWR (Modified Dietz) reported separately.
* **Day count.** ``ACT/365 Fixed`` on VALUATION DATES: ``days_act = end_date − start_date``. A bar is
  an end-of-day mark labelled by its date and accrues one day of yield; the wall-clock run time of
  the cycle (which moved during the track) is recorded alongside, not used as the duration.
  Calendar days with no bar stay inside the period: their yield was never credited (the NAV is
  continuous across them), so the elapsed-time convention can only UNDER-state the rate.
* **Annualised equivalent** = ``(1 + R) ** (365 / days_act) − 1`` — separate, labelled, and marked
  ``approval_required``.

Pure stdlib, no file I/O, no wall clock. Absence is ``None`` with a reason (inv. #17), never 0.
LLM forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

CONVENTION = "ACT/365 Fixed on valuation dates"
NAV_TOL_USD = 0.011      # open vs previous close (ledger rounds to cents)
PNL_TOL_USD = 0.02       # close − open vs yield − cost


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _close(bar: dict) -> Optional[float]:
    c = _num(bar.get("close_equity"))
    return c if c is not None else _num(bar.get("equity"))


def _date(bar: dict) -> Optional[date]:
    try:
        return date.fromisoformat(str(bar.get("date"))[:10])
    except (TypeError, ValueError):
        return None


def _provenance(bar: dict) -> str:
    """One label per evidenced bar, from the ledger's own fields."""
    if bar.get("recovered_from") in ("self_heal", "daily_cycle_log"):
        return "restored_from_cycle_log"
    acc = bar.get("accrual_source")
    if acc == "live":
        return "live_rates"
    if acc == "fallback":
        return "fallback_rate"
    return "cycle_unlabelled"


def _absent(reason: str) -> Dict[str, Any]:
    return {"state": "UNMEASURED", "reason": reason, "method": None, "period": None,
            "nav_start": None, "nav_end": None, "period_return_pct": None,
            "twr_pct": None, "mwr_pct": None, "annualised_equivalent_pct": None,
            "annualised_approval_required": True, "flows": None, "costs_paid_usd": None,
            "provenance": None, "gaps": None}


def period_return(bars: List[dict], *, end_ts: Optional[str] = None,
                  start_ts: Optional[str] = None) -> Dict[str, Any]:
    """The track's return over its actual period, from the evidenced bars of the ledger.

    ``start_ts`` / ``end_ts`` — the wall-clock times the boundary NAVs were recorded, when the caller
    knows them (the ledger stores dates only). Recorded, never used as the duration.
    """
    if not isinstance(bars, list):
        return _absent("ledger has no bar list")
    ev = [b for b in bars if isinstance(b, dict) and b.get("evidenced") is True and _date(b) is not None]
    ev.sort(key=lambda b: _date(b))
    if len(ev) < 2:
        return _absent("fewer than two evidenced bars — a single NAV carries no period")
    first, last = ev[0], ev[-1]
    nav_start, nav_end = _close(first), _close(last)
    if not nav_start or not nav_end or nav_start <= 0 or nav_end <= 0:
        return _absent("boundary NAV missing or non-positive")
    d0, d1 = _date(first), _date(last)
    days_act = (d1 - d0).days
    if days_act <= 0:
        return _absent("period has no duration")

    # ── flows: every bar after the start must open at the previous close and move only by yield − cost
    flows: List[Dict[str, Any]] = []
    unchecked: List[str] = []
    costs = 0.0
    twr_growth = 1.0
    prev_close = nav_start
    dates = {d0}
    zero_yield: List[str] = []
    for b in ev[1:]:
        dates.add(_date(b))
        o, c = _num(b.get("open_equity")), _close(b)
        y, k = _num(b.get("daily_yield_usd")), _num(b.get("cost_usd")) or 0.0
        costs += k
        if o is None or c is None or y is None:
            unchecked.append(str(b.get("date")))
            o = prev_close if o is None else o
        jump = round(o - prev_close, 2)
        if abs(o - prev_close) > NAV_TOL_USD:
            flows.append({"date": str(b.get("date")), "kind": "open_jump", "usd": jump})
        if y is not None and c is not None and abs((c - o) - (y - k)) > PNL_TOL_USD:
            flows.append({"date": str(b.get("date")), "kind": "unexplained_intraday",
                          "usd": round((c - o) - (y - k), 2)})
        if y is not None and y == 0.0:
            zero_yield.append(str(b.get("date")))
        if c is not None and o:
            twr_growth *= c / o
        prev_close = c if c is not None else prev_close

    missing = []
    cur = d0
    while cur < d1:
        cur = date.fromordinal(cur.toordinal() + 1)
        if cur not in dates:
            missing.append(cur.isoformat())

    ratio = nav_end / nav_start - 1.0
    if flows:
        method = "TWR"
        twr = twr_growth - 1.0
        net_flow = sum(f["usd"] for f in flows)
        # Modified Dietz with flows at their dates (weight = remaining fraction of the period).
        w = 0.0
        for f in flows:
            fd = date.fromisoformat(f["date"])
            w += f["usd"] * ((d1 - fd).days / days_act)
        denom = nav_start + w
        mwr = ((nav_end - nav_start - net_flow) / denom) if denom > 0 else None
        primary = twr
    else:
        method = "NAV_RATIO"
        twr = ratio
        mwr = ratio
        primary = ratio
    annual = (1.0 + primary) ** (365.0 / days_act) - 1.0 if primary > -1.0 else None

    prov: Dict[str, int] = {}
    for b in ev:
        p = _provenance(b)
        prov[p] = prov.get(p, 0) + 1
    repaired = [str(b.get("date")) for b in ev if b.get("continuity_repaired")]

    return {
        "state": "MEASURED",
        "method": method,
        "period": {
            "start_date": d0.isoformat(), "end_date": d1.isoformat(),
            "start_ts": start_ts, "end_ts": end_ts,
            "start_ts_reason": None if start_ts else "the ledger records valuation dates, not run times",
            "days_act": days_act, "convention": CONVENTION,
            "evidenced_bars": len(ev), "accrual_bars": len(ev) - 1,
        },
        "nav_start": round(nav_start, 2),
        "nav_end": round(nav_end, 2),
        "nav_start_basis": "close of the first evidenced bar",
        "period_return_pct": round(primary * 100.0, 6),
        "twr_pct": round(twr * 100.0, 6),
        "mwr_pct": round(mwr * 100.0, 6) if mwr is not None else None,
        "annualised_equivalent_pct": round(annual * 100.0, 6) if annual is not None else None,
        "annualised_formula": "(1 + R) ^ (365 / days_act) − 1",
        "annualised_approval_required": True,
        "flows": {"count": len(flows), "state": "MEASURED" if not unchecked else "PARTIAL",
                  "items": flows[:20], "unchecked_bars": unchecked,
                  "basis": "open = previous close and close − open = yield − cost, per evidenced bar"},
        "costs_paid_usd": round(costs, 2),
        "costs_basis": "sum of cost_usd over the bars after the start; already inside NAV",
        "provenance": prov,
        "continuity_repaired": repaired,
        "gaps": {"missing_dates": missing, "zero_yield_dates": zero_yield,
                 "nav_continuous_across_missing": not any(f["kind"] == "open_jump" for f in flows)},
    }
