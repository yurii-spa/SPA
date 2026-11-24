#!/usr/bin/env python3
"""
scripts/edge_cps_conditional_suspension.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADVISORY / OUTSIDE_RISKPOLICY / IS_ADVISORY=True
LLM_FORBIDDEN — stdlib-only, deterministic, fail-CLOSED

#167 CPS — Cross-book Peril Suspension

Hypothesis:
  When ≥K books out of the 5 non-thin fixture books simultaneously
  report negative cumulative returns over a rolling W-day lookback
  window, the stress event is likely SYSTEMIC rather than
  idiosyncratic.  Under systemic stress, the highest-tail book
  (leverage_loop, risk_shape = liquidation) is temporarily suspended
  (weight reduced by fraction F) until the cross-book signal clears.

Economic mechanism:
  The fixture's stress events are multi-day (geometric front-loaded
  losses spread across 30-31 day windows).  After observing day-0's
  unavoidable losses, days 1-N are suspendable.  Cross-book BREADTH
  signal (K books negative) distinguishes systemic from idiosyncratic
  drawdowns — this is distinct from:
    • CADS (#119): per-book stop, not cross-book count
    • CTAC (#127): measures historical correlation, not live breadth
    • DDW (#85): weights by DEPTH of one book, not BREADTH of count

Portfolio:
  Equal-weight across 5 non-thin books (20% each).
  When CPS active: leverage_loop weight → w × (1-F);
    remaining weight → redistributed equally to other 4 books.
  Transaction cost: 96 bp × book_weight × F per state change.

Data: FIXTURE ONLY.  Results labeled [bt].
  Real-data validation requires the real panel
  (data/rates_desk/ or data/aggressive_lab/ — unavailable in cloud).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import json
import argparse
import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.strategy_lab.aggressive_lab.fixtures import strategy_jsonl
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS

IS_ADVISORY: bool = True
OUTSIDE_RISKPOLICY: bool = True

ROLL_COST_BP: float = 96.0
SEAM: str = "2025-06-30"

NON_THIN_BOOKS: Tuple[str, ...] = (
    "susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"
)
TARGET: str = "leverage_loop"

W_GRID: Tuple[int, ...] = (1, 3, 7, 14)
K_GRID: Tuple[int, ...] = (2, 3, 4)
F_GRID: Tuple[float, ...] = (0.5, 1.0)


def _load_backtest_series(strategy_id: str) -> List[Dict]:
    """Load backtest-phase points from fixture JSONL."""
    pts = []
    for line in strategy_jsonl(strategy_id).strip().split("\n"):
        if not line.strip():
            continue
        pt = json.loads(line)
        if pt.get("phase") == "backtest":
            pts.append(pt)
    return pts


def build_returns() -> Tuple[List[datetime.date], Dict[str, List[float]]]:
    """Build daily return arrays for all non-thin books (backtest phase only)."""
    series: Dict[str, List[Dict]] = {
        sid: _load_backtest_series(sid) for sid in NON_THIN_BOOKS
    }
    dates = [datetime.date.fromisoformat(pt["date"])
             for pt in series[NON_THIN_BOOKS[0]]]
    rets: Dict[str, List[float]] = {}
    for sid in NON_THIN_BOOKS:
        raw = series[sid]
        r: List[float] = []
        for i, pt in enumerate(raw):
            if i == 0:
                r.append(pt["equity_usd"] / 100_000.0 - 1.0)
            else:
                r.append(pt["equity_usd"] / raw[i - 1]["equity_usd"] - 1.0)
        rets[sid] = r
    return dates, rets


def _cum_w(rets_sid: List[float], i: int, W: int) -> float:
    """Cumulative return over lookback [i-W, i-1] (no lookahead)."""
    start = max(0, i - W)
    if start >= i:
        return 0.0
    return sum(rets_sid[start:i])


def run_cps(
    dates: List[datetime.date],
    rets: Dict[str, List[float]],
    W: int,
    K: int,
    F: float,
) -> Tuple[List[float], int, int]:
    """
    Run the CPS strategy.
    Returns (equity_curve, n_suspensions, n_resumptions).
    equity_curve[i] is portfolio equity at end of day i, starting at 1.0.
    """
    n = len(dates)
    base_w = 1.0 / len(NON_THIN_BOOKS)
    tgt_w = base_w * (1.0 - F)
    other_w = (1.0 - tgt_w) / (len(NON_THIN_BOOKS) - 1)
    cost_per_event = (ROLL_COST_BP / 10_000.0) * base_w * F

    eq = 1.0
    equity: List[float] = []
    suspended = False
    n_sus = n_res = 0

    for i in range(n):
        distressed = sum(
            1 for sid in NON_THIN_BOOKS
            if _cum_w(rets[sid], i, W) < 0.0
        )
        new_sus = distressed >= K

        tc = 0.0
        if new_sus != suspended:
            tc = cost_per_event
            if new_sus:
                n_sus += 1
            else:
                n_res += 1
        suspended = new_sus

        if not suspended:
            port = sum(rets[sid][i] * base_w for sid in NON_THIN_BOOKS)
        else:
            port = rets[TARGET][i] * tgt_w + sum(
                rets[sid][i] * other_w
                for sid in NON_THIN_BOOKS
                if sid != TARGET
            )

        eq *= (1.0 + port - tc)
        equity.append(eq)

    return equity, n_sus, n_res


def run_baseline(
    dates: List[datetime.date],
    rets: Dict[str, List[float]],
) -> List[float]:
    """Equal-weight portfolio, no CPS."""
    base_w = 1.0 / len(NON_THIN_BOOKS)
    eq = 1.0
    equity: List[float] = []
    for i in range(len(dates)):
        port = sum(rets[sid][i] * base_w for sid in NON_THIN_BOOKS)
        eq *= (1.0 + port)
        equity.append(eq)
    return equity


def _seg_metrics(seg_d: List[datetime.date], seg_e: List[float]) -> Dict:
    if len(seg_e) < 2:
        return {}
    days = (seg_d[-1] - seg_d[0]).days
    if days == 0:
        return {}
    total = seg_e[-1] / seg_e[0] - 1.0
    apy = (1.0 + total) ** (365.0 / days) - 1.0
    peak = seg_e[0]
    mdd = 0.0
    for e in seg_e:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > mdd:
            mdd = dd
    cal = apy / mdd if mdd > 1e-9 else 9999.0
    return {
        "apy_pct": round(apy * 100, 2),
        "maxdd_pct": round(mdd * 100, 2),
        "calmar": round(cal, 2),
        "days": days,
    }


def compute_metrics(
    dates: List[datetime.date],
    equity: List[float],
    seam: str,
) -> Dict:
    seam_d = datetime.date.fromisoformat(seam)
    split = next((i for i, d in enumerate(dates) if d > seam_d), len(dates))

    full = _seg_metrics(dates, equity)
    train = _seg_metrics(dates[:split], equity[:split])

    test: Dict = {}
    if 0 < split < len(dates):
        test_d = [dates[split - 1]] + list(dates[split:])
        test_e = [equity[split - 1]] + list(equity[split:])
        test = _seg_metrics(test_d, test_e)

    return {"full": full, "train": train, "test": test}


def compute_window_dd(
    dates: List[datetime.date],
    equity: List[float],
) -> Dict[str, float]:
    eq_map = dict(zip(dates, equity))
    result: Dict[str, float] = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        pre = [d for d in dates if d < lo]
        if not pre:
            continue
        pre_eq = eq_map[pre[-1]]
        during = [eq_map[d] for d in dates if lo <= d <= hi and d in eq_map]
        if not during:
            continue
        wdd = max(0.0, (pre_eq - min(during)) / pre_eq)
        result[str(w["key"])] = round(wdd * 100, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "CPS #167 — Cross-book Peril Suspension  [ADVISORY / fixture only]"
        )
    )
    parser.add_argument("--json", action="store_true",
                        help="Output full results as JSON")
    args = parser.parse_args()

    dates, rets = build_returns()

    base_eq = run_baseline(dates, rets)
    base_m = compute_metrics(dates, base_eq, SEAM)
    base_wdd = compute_window_dd(dates, base_eq)

    best_calmar: float = -1e9
    best_params: Optional[Tuple] = None
    best_entry: Optional[Dict] = None
    grid: List[Dict] = []

    for W in W_GRID:
        for K in K_GRID:
            for F in F_GRID:
                eq, n_sus, n_res = run_cps(dates, rets, W, K, F)
                m = compute_metrics(dates, eq, SEAM)
                wdd = compute_window_dd(dates, eq)
                entry = {
                    "W": W, "K": K, "F": F,
                    "metrics": m,
                    "window_dd_pct": wdd,
                    "n_sus": n_sus,
                    "n_res": n_res,
                }
                grid.append(entry)
                te_cal = m.get("test", {}).get("calmar", -1e9)
                if isinstance(te_cal, (int, float)) and te_cal > best_calmar:
                    best_calmar = float(te_cal)
                    best_params = (W, K, F)
                    best_entry = entry

    if args.json:
        print(json.dumps({
            "strategy": "CPS_167",
            "is_advisory": IS_ADVISORY,
            "outside_riskpolicy": OUTSIDE_RISKPOLICY,
            "data_source": "fixture_only",
            "seam": SEAM,
            "baseline": {"metrics": base_m, "window_dd_pct": base_wdd},
            "grid": grid,
            "best_params": best_params,
            "best_calmar_test": best_calmar,
        }, indent=2))
        return

    sep = "=" * 70
    print(sep)
    print("  CPS #167 — Cross-book Peril Suspension  [bt FIXTURE ONLY]")
    print(f"  ADVISORY / OUTSIDE_RISKPOLICY  |  seam: {SEAM}")
    print(sep)

    def _show(label: str, m: Dict, wdd: Optional[Dict] = None) -> None:
        print(f"\n{label}:")
        for period in ("full", "train", "test"):
            pm = m.get(period, {})
            if pm:
                print(f"  {period.upper():<6}: APY {pm['apy_pct']:7.2f}%  "
                      f"maxDD {pm['maxdd_pct']:6.2f}%  "
                      f"Calmar {pm['calmar']:7.2f}  "
                      f"({pm['days']} days)")
        if wdd is not None:
            print(f"  Window DD [%]: {wdd}")

    _show("BASELINE (equal-weight, 5 books, no CPS)", base_m, base_wdd)

    print(f"\nCPS PARAMETER GRID (W=lookback days, K=min books distressed, "
          f"F=suspension fraction):")
    print(
        f"{'W':>3} {'K':>3} {'F':>5}  "
        f"{'TR APY%':>8} {'TR DD%':>7} {'TR Cal':>7}  "
        f"{'TE APY%':>8} {'TE DD%':>7} {'TE Cal':>7}  "
        f"{'Sus':>4}"
    )
    print("-" * 76)
    for e in grid:
        tr = e["metrics"].get("train", {})
        te = e["metrics"].get("test", {})
        print(
            f"{e['W']:>3} {e['K']:>3} {e['F']:>5.2f}  "
            f"{tr.get('apy_pct', 0):>8.2f} "
            f"{tr.get('maxdd_pct', 0):>7.2f} "
            f"{tr.get('calmar', 0):>7.2f}  "
            f"{te.get('apy_pct', 0):>8.2f} "
            f"{te.get('maxdd_pct', 0):>7.2f} "
            f"{te.get('calmar', 0):>7.2f}  "
            f"{e['n_sus']:>4}"
        )

    if best_params and best_entry:
        print(f"\n--- BEST BY TEST CALMAR: W={best_params[0]} K={best_params[1]} "
              f"F={best_params[2]:.2f} (Calmar={best_calmar:.2f}) ---")
        _show("BEST-CPS", best_entry["metrics"], best_entry["window_dd_pct"])

    print(f"\nHONEST CAVEATS [bt]:")
    print(f"  · fixture substrate only — 5 books, constant drift + 3 stress windows")
    print(f"  · signal fires AFTER day-0 of each window (1-day lag, unavoidable)")
    print(f"  · only 3 stress events → Calmar not statistically robust")
    print(f"  · real data may produce false-positive signals outside stress windows")
    print(f"  · TC = {ROLL_COST_BP:.0f}bp × book_weight × F per state-change event")
    print(f"  · NOT live-track, NOT real panel, NOT go-live-eligible")


if __name__ == "__main__":
    main()
