"""spa_core/defi_engine/apy_contract.py — ONE named definition per APY quantity (ADR-532, P1-5).

The gap audit (§C #52) measured four «current APY» values on the same morning — 5.39 (`apy_today`),
5.469 (`apy_now_pp`), 5.757 (tuner), 4.92 (site) — because four quantities shared one word. They are
all legitimate; they are different questions. This contract gives each its own name, unit,
annualisation method and source, and computes gross AND net wherever costs exist.

=============================  ==================================================================
definition id                  meaning
=============================  ==================================================================
``pool_spot_apy``              one pool's current APY as the money path observed it (snapshot)
``book_spot_apy_gross``        notional-weighted spot APY of the held positions (deployed only)
``book_spot_apy_on_nav``       the same income over the whole NAV (cash drag included)
``book_cost_drag_30d``         trailing-30-day modelled cost, annualised, as a share of NAV
``book_spot_apy_net``          ``book_spot_apy_on_nav − book_cost_drag_30d``
``track_realized_apy_net``     compound-annualised realised track return, net of charged costs —
                               the SITE's headline method (scripts/generate_track_snapshot.py)
``track_realized_apy_gross``   the same with every charged cost added back
``cumulative_return_pct``      plain (non-annualised) return over the measured series
=============================  ==================================================================

Every value is in PERCENT. ``None`` = not measured (with a reason), never 0.0 (invariant #17).
Annualisation of track figures is compound, ``(end/start)^(365/days) − 1``, exactly as the site;
``spa_core/tests/test_defi_engine.py::test_track_net_equals_the_site_headline_method`` pins it.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

DEFINITIONS: dict[str, dict] = {
    "pool_spot_apy": {
        "unit": "percent", "annualisation": "as reported by the source (APY)",
        "source": "data/adapter_orchestrator_status.json (orchestrator snapshot)",
        "formula": "adapter APY for the pool, normalised to percent",
    },
    "book_spot_apy_gross": {
        "unit": "percent", "annualisation": "as reported (APY)",
        "source": "book positions × pool_spot_apy",
        "formula": "Σ notional·apy / Σ notional (held positions only)",
    },
    "book_spot_apy_on_nav": {
        "unit": "percent", "annualisation": "as reported (APY)",
        "source": "book positions × pool_spot_apy, book NAV",
        "formula": "Σ notional·apy / NAV (cash earns 0)",
    },
    "book_cost_drag_30d": {
        "unit": "percent", "annualisation": "simple, × 365 / window days",
        "source": "book series cost_usd (modelled gas + slippage actually charged)",
        "formula": ("Σ cost_usd over the trailing run (≤30) of bars WITH an observed cost, excluding the "
                    "run's first bar, / mean equity × 365 / (bars − 1) — interval convention"),
    },
    "book_spot_apy_net": {
        "unit": "percent", "annualisation": "as reported, less annualised cost",
        "source": "book_spot_apy_on_nav, book_cost_drag_30d",
        "formula": "book_spot_apy_on_nav − book_cost_drag_30d",
    },
    "track_realized_apy_net": {
        "unit": "percent", "annualisation": "compound: (end/start)^(365/days) − 1",
        "source": "book series equity (net of charged costs)",
        "formula": ("first → last measured equity; days = number of measured BARS (not intervals) — "
                    "the site's convention, kept for parity"),
    },
    "track_realized_apy_gross": {
        "unit": "percent", "annualisation": "compound: (end/start)^(365/days) − 1",
        "source": "book series equity + cumulative cost_usd",
        "formula": ("as net, with every CHARGED cost after the first bar added back to the end value "
                    "(simple add-back, not compounded); bars without a cost field are counted"),
    },
    "cumulative_return_pct": {
        "unit": "percent", "annualisation": "none",
        "source": "book series equity",
        "formula": "last / first − 1",
    },
}


def _value(v: Optional[float], reason: Optional[str] = None, **extra) -> dict:
    d: dict = {"value": (round(v, 4) if isinstance(v, (int, float)) else None)}
    if d["value"] is None:
        d["unmeasured_reason"] = reason or "not measured"
    d.update(extra)
    return d


def compound_annualised(start: float, end: float, days: int) -> Optional[float]:
    if start <= 0 or end <= 0 or days <= 0:
        return None
    return ((end / start) ** (365.0 / days) - 1.0) * 100.0


def book_contract(book: dict) -> dict:
    """All definitions for ONE book (as loaded by ``books.load_books``)."""
    if not book.get("measured"):
        reason = book.get("reason") or "book not measured"
        return {k: _value(None, reason) for k in DEFINITIONS if k != "pool_spot_apy"}
    positions = book.get("positions") or []
    nav = book.get("nav_usd")
    priced = [p for p in positions if isinstance(p.get("apy_pct"), (int, float))]
    unpriced = sorted(p["protocol"] for p in positions if p not in priced)
    deployed = sum(p["notional_usd"] for p in priced)
    income = sum(p["notional_usd"] * p["apy_pct"] for p in priced)
    cash = book.get("cash_usd")
    out: dict[str, dict] = {}
    if unpriced:
        why = f"no observed APY for {unpriced}"
        out["book_spot_apy_gross"] = _value(None, why)
        out["book_spot_apy_on_nav"] = _value(None, why)
    elif not positions:
        out["book_spot_apy_gross"] = _value(None, "book holds no position")
        out["book_spot_apy_on_nav"] = _value(0.0 if (nav and cash is not None) else None,
                                             book.get("cash_reason") or "NAV not measured", note="all cash")
    else:
        out["book_spot_apy_gross"] = _value(income / deployed if deployed else None)
        # On NAV only when the book's cash is MEASURED: a sleeve state has no cash field and its
        # legs may exceed equity by a day's cost, so income/NAV would exceed the gross rate.
        out["book_spot_apy_on_nav"] = (_value(income / nav) if (nav and cash is not None)
                                       else _value(None, book.get("cash_reason") or "NAV not measured"))

    series = [r for r in (book.get("series") or []) if isinstance(r.get("equity"), (int, float))
              and r["equity"] > 0]
    # Cost drag over the TRAILING run of bars whose cost was observed (≤ 30). A bar with no
    # cost field is not a zero-cost bar (invariant #17); it ends the run.
    run: list[dict] = []
    for r in reversed(series):
        if not isinstance(r.get("cost_usd"), (int, float)) or len(run) >= 30:
            break
        run.append(r)
    run.reverse()
    if len(run) >= 2:
        mean_eq = sum(r["equity"] for r in run) / len(run)
        cost = sum(float(r["cost_usd"]) for r in run[1:])
        days = len(run) - 1
        out["book_cost_drag_30d"] = _value(cost / mean_eq * 365.0 / days * 100.0,
                                           window_days=days, cost_usd=round(cost, 2))
    else:
        out["book_cost_drag_30d"] = _value(None, book.get("series_reason")
                                           or "fewer than 2 trailing bars with an observed cost")
    nav_apy = out["book_spot_apy_on_nav"]["value"]
    drag = out["book_cost_drag_30d"]["value"]
    out["book_spot_apy_net"] = (_value(nav_apy - drag) if nav_apy is not None and drag is not None
                                else _value(None, "needs book_spot_apy_on_nav and book_cost_drag_30d"))

    if len(series) >= 2:
        start, end, days = series[0]["equity"], series[-1]["equity"], len(series)
        charged = [float(r["cost_usd"]) for r in series[1:] if isinstance(r.get("cost_usd"), (int, float))]
        unobserved = sum(1 for r in series[1:] if not isinstance(r.get("cost_usd"), (int, float)))
        out["track_realized_apy_net"] = _value(compound_annualised(start, end, days),
                                               days=days, first_date=series[0].get("date"),
                                               last_date=series[-1].get("date"))
        out["track_realized_apy_gross"] = _value(
            compound_annualised(start, end + sum(charged), days),
            days=days, costs_added_back_usd=round(sum(charged), 2),
            bars_without_cost_field=unobserved,
            note=("only CHARGED costs are added back; a bar with no cost field had none deducted "
                  "from its equity, so its gross equals its net") if unobserved else None)
        out["cumulative_return_pct"] = _value((end / start - 1.0) * 100.0, days=days)
    else:
        why = book.get("series_reason") or "fewer than 2 measured bars"
        for k in ("track_realized_apy_net", "track_realized_apy_gross", "cumulative_return_pct"):
            out[k] = _value(None, why)
    return out


def pool_contract(pools: dict) -> dict:
    """``pool_spot_apy`` for every pool in the snapshot, with its provenance."""
    out = {}
    for proto, a in sorted(pools.items()):
        apy = a.get("apy_pct")
        out[proto] = _value(apy if isinstance(apy, (int, float)) and not isinstance(apy, bool) else None,
                            "adapter returned no APY",
                            live=bool(a.get("live_data")), tvl_source=a.get("tvl_source"),
                            last_updated=a.get("last_updated"))
    return out
