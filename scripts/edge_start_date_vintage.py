"""
scripts/edge_start_date_vintage.py — Idea #147: SAV (Start-Date Vintage Analysis)

Question: Does a new investor's entry date materially affect EW-portfolio Calmar?
Method:   Sweep start dates T ∈ [2024-07-01 … 2025-12-01] (monthly granularity, 18 vintages).
          For each T, compute EW equity from T to the fixture backtest end (2026-05-31),
          then measure CAGR, maxDD, Calmar.
          Report: best/worst vintage, Calmar CDF, relation to crisis windows.

stdlib-only, deterministic. LLM FORBIDDEN. IS_ADVISORY=True. OUTSIDE_RISKPOLICY=True.
Evidence level: L0 backtest [bt].
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- project path -----------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_equity_map(strategy_id: str) -> Dict[datetime.date, float]:
    """Return {date: equity_usd} for the full backtest of one fixture strategy."""
    spec = fixtures._SPEC[strategy_id]
    rows = []
    if not spec.get("no_backtest"):
        rows.extend(fixtures._build_backtest_series(spec))
    # forward phase not included — we only want the backtest window
    return {datetime.date.fromisoformat(r["date"]): r["equity_usd"] for r in rows}


def _ew_portfolio(
    maps: List[Dict[datetime.date, float]],
    start: datetime.date,
    end: datetime.date,
    initial: float = 100_000.0,
) -> List[Tuple[datetime.date, float]]:
    """Equal-weight portfolio equity from [start..end].

    Each book is re-indexed to its value on `start`, then averaged daily.
    Returns list of (date, portfolio_equity) sorted by date.
    """
    n = len(maps)
    series: List[Tuple[datetime.date, float]] = []

    # Find anchor values (equity on start date for each book)
    anchors: Optional[List[float]] = None
    d = start
    while d <= end and anchors is None:
        vals = []
        ok = True
        for m in maps:
            if d not in m:
                ok = False
                break
            vals.append(m[d])
        if ok:
            anchors = vals
        d += datetime.timedelta(days=1)

    if anchors is None:
        return []  # no common data at start

    # Now sweep from start to end, computing EW portfolio
    d = start
    while d <= end:
        vals = []
        ok = True
        for m in maps:
            if d not in m:
                ok = False
                break
            vals.append(m[d])
        if not ok:
            d += datetime.timedelta(days=1)
            continue

        # each book's factor vs its anchor value
        factors = [vals[i] / anchors[i] for i in range(n)]
        ew = initial * (sum(factors) / n)
        series.append((d, round(ew, 4)))
        d += datetime.timedelta(days=1)

    return series


def _calmar(series: List[Tuple[datetime.date, float]]) -> Tuple[float, float, float]:
    """Return (CAGR%, maxDD%, Calmar). Calmar = CAGR / maxDD (0.0 if maxDD==0)."""
    if len(series) < 2:
        return 0.0, 0.0, 0.0

    start_date, start_eq = series[0]
    end_date, end_eq = series[-1]

    days = (end_date - start_date).days
    if days <= 0:
        return 0.0, 0.0, 0.0

    years = days / 365.25
    cagr = ((end_eq / start_eq) ** (1.0 / years) - 1.0) * 100.0

    # max drawdown
    peak = series[0][1]
    max_dd = 0.0
    for _, eq in series:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd * 100.0

    calmar = (cagr / max_dd_pct) if max_dd_pct > 0.001 else (cagr / 0.001)
    return round(cagr, 3), round(max_dd_pct, 3), round(calmar, 4)


# ---------------------------------------------------------------------------
# crisis window lookup (for annotation)
# ---------------------------------------------------------------------------
_CRISIS_LABELS: List[Tuple[datetime.date, datetime.date, str]] = [
    (datetime.date(2024, 8, 1),  datetime.date(2024, 8, 31),  "eth_crash_2024_08"),
    (datetime.date(2025, 10, 1), datetime.date(2025, 10, 31), "usde_unwind_2025_10"),
    (datetime.date(2026, 4, 1),  datetime.date(2026, 4, 30),  "rseth_depeg_2026_04"),
]


def _crisis_relation(start: datetime.date) -> str:
    """Classify start date as pre/during/post each crisis window."""
    tags = []
    for lo, hi, name in _CRISIS_LABELS:
        if start < lo:
            tags.append(f"pre-{name}")
        elif lo <= start <= hi:
            tags.append(f"in-{name}")
        else:
            tags.append(f"post-{name}")
    return " | ".join(tags)


# ---------------------------------------------------------------------------
# main analysis
# ---------------------------------------------------------------------------

def run_sav() -> dict:
    # books to include (exclude thin_new: no backtest)
    BOOKS = [sid for sid in fixtures.roster() if sid != "thin_new"]

    # build equity maps once
    equity_maps = {sid: _build_equity_map(sid) for sid in BOOKS}

    BACKTEST_END = fixtures._BACKTEST_END   # 2026-05-31

    # sweep start dates: monthly from 2024-07-01 to 2025-12-01
    start_dates: List[datetime.date] = []
    d = fixtures._BACKTEST_START  # 2024-07-01
    limit = datetime.date(2025, 12, 1)
    while d <= limit:
        start_dates.append(d)
        # advance ~1 month
        month = d.month + 1
        year = d.year
        if month > 12:
            month = 1
            year += 1
        d = datetime.date(year, month, 1)

    results = []
    maps_list = [equity_maps[sid] for sid in BOOKS]

    for start in start_dates:
        series = _ew_portfolio(maps_list, start, BACKTEST_END)
        if len(series) < 30:
            continue  # too few points
        days_span = (BACKTEST_END - start).days
        cagr, max_dd, calmar = _calmar(series)
        results.append({
            "start": start.isoformat(),
            "days": days_span,
            "cagr_pct": cagr,
            "max_dd_pct": max_dd,
            "calmar": calmar,
            "crisis_relation": _crisis_relation(start),
        })

    # summary statistics
    calmars = [r["calmar"] for r in results]
    cagrs = [r["cagr_pct"] for r in results]
    max_dds = [r["max_dd_pct"] for r in results]

    n = len(results)
    best = max(results, key=lambda x: x["calmar"])
    worst = min(results, key=lambda x: x["calmar"])
    calmar_positive = sum(1 for c in calmars if c > 0)
    calmar_above_1 = sum(1 for c in calmars if c >= 1.0)
    calmar_neg = sum(1 for c in calmars if c < 0)

    avg_calmar = sum(calmars) / n
    avg_cagr = sum(cagrs) / n
    avg_dd = sum(max_dds) / n

    return {
        "n_vintages": n,
        "books": BOOKS,
        "best_vintage": best,
        "worst_vintage": worst,
        "avg_calmar": round(avg_calmar, 4),
        "avg_cagr_pct": round(avg_cagr, 3),
        "avg_max_dd_pct": round(avg_dd, 3),
        "calmar_positive": calmar_positive,
        "calmar_above_1": calmar_above_1,
        "calmar_negative": calmar_neg,
        "all_vintages": results,
    }


def main() -> None:
    print("=" * 72)
    print("SAV — Start-Date Vintage Analysis  [bt L0 fixture]")
    print("=" * 72)
    r = run_sav()

    print(f"\nBooks analysed: {r['books']}")
    print(f"Vintages tested: {r['n_vintages']}  (monthly 2024-07 … 2025-12)")
    print(f"\nAverage across all vintages:")
    print(f"  CAGR:   {r['avg_cagr_pct']:+.2f}%  [bt]")
    print(f"  MaxDD:  {r['avg_max_dd_pct']:.2f}%  [bt]")
    print(f"  Calmar: {r['avg_calmar']:+.4f}  [bt]")
    print(f"\nCalmar distribution:")
    print(f"  Calmar >= 1.0 : {r['calmar_above_1']}/{r['n_vintages']}")
    print(f"  Calmar > 0    : {r['calmar_positive']}/{r['n_vintages']}")
    print(f"  Calmar < 0    : {r['calmar_negative']}/{r['n_vintages']}")

    b = r["best_vintage"]
    w = r["worst_vintage"]
    print(f"\nBest vintage  : {b['start']}  Calmar={b['calmar']:+.4f}"
          f"  CAGR={b['cagr_pct']:+.2f}%  DD={b['max_dd_pct']:.2f}%")
    print(f"  Crisis context: {b['crisis_relation']}")
    print(f"\nWorst vintage : {w['start']}  Calmar={w['calmar']:+.4f}"
          f"  CAGR={w['cagr_pct']:+.2f}%  DD={w['max_dd_pct']:.2f}%")
    print(f"  Crisis context: {w['crisis_relation']}")

    print("\nAll vintages (start | days | CAGR% | maxDD% | Calmar):")
    for v in r["all_vintages"]:
        print(f"  {v['start']}  {v['days']:4d}d  "
              f"CAGR={v['cagr_pct']:+7.2f}%  DD={v['max_dd_pct']:6.2f}%  "
              f"Calmar={v['calmar']:+7.4f}")

    # also output JSON for machine consumption
    out_path = Path(__file__).parent / "edge_start_date_vintage_results.json"
    out_path.write_text(json.dumps(r, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nResults written to {out_path}")
    print("=" * 72)

    return r


if __name__ == "__main__":
    main()
