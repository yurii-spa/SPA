#!/usr/bin/env python3
"""Novel-edge idea (working name, number claimed at push) — TAIL-ORTHOGONAL PORTFOLIO FRONTIER.

Registry context: spa_core/strategy_lab/aggressive_lab/fixtures.py supplies 5 testable strategies
(susde_dn / lrt_carry / leverage_loop / points_farm / variant_d) with explicit per-crisis-window
hit fractions {eth_crash_2024_08, usde_unwind_2025_10, rseth_depeg_2026_04}. All prior fixture-based
entries (e.g. #3 cross_desk_portfolio) blended only 1–3 strategies. This entry asks: given 5
strategies with DIFFERENT TAIL SHAPES (funding_flip / depeg / liquidation / incentive_decay /
directional), does minimizing max-crisis combined loss ("tail-optimal") produce a better or different
portfolio than maximising Calmar?

Honesty-gated by construction:
• Sweep is deterministic over the 5-strategy weight simplex (10 ppt steps → 1001 combos).
• "Tail-optimal" objective is LOOK-AHEAD: we know the 3 crisis windows and their hits. This is
  stated as evidence level L0 (backtest/synthetic) and the look-ahead caveat is the first finding.
• Class-D risk (points_farm): the fixture uses a constant daily drift at the headline 14 % APY.
  In reality incentive/airdrop farms decay. A "class-D penalty" run cuts points_farm APY by 50 %
  to test whether conclusions are robust. If they flip → incentive_decay risk is load-bearing.
• Output labels every number [bt] — never 'live' or 'realized'.
• IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True. No spa_core/execution import. No RiskPolicy touch.
• stdlib-only, deterministic, atomic write via spa_core.utils.atomic if available (graceful fallback).

Usage:  python3 scripts/edge_tail_portfolio_frontier.py
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from itertools import product as iterproduct

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

# ── load fixture ─────────────────────────────────────────────────────────────────────────────────

def _load_fixture_series() -> dict[str, list[float]]:
    """Returns {strategy_id: [equity_day0, equity_day1, ...]} from the aggressive-lab fixture."""
    from spa_core.strategy_lab.aggressive_lab import loader as ld, fixtures as fx

    tmp = Path(tempfile.mkdtemp(prefix="topf_"))
    fx.materialize(tmp)
    all_strategies = ld.load_all(data_dir=tmp)

    series: dict[str, list[float]] = {}
    for sid, st in all_strategies.items():
        if st is None or st.backtest is None:
            continue
        pts = st.backtest.series
        if not pts or len(pts) < 30:
            continue  # skip thin_new (6 fwd days only)
        equities = []
        for p in pts:
            e = p.get("equity_usd") or p.get("equity")
            if e is not None:
                equities.append(float(e))
        if len(equities) >= 30:
            series[sid] = equities
    return series


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────

def _apy(equities: list[float]) -> float:
    if len(equities) < 2 or equities[0] <= 0:
        return 0.0
    n = len(equities) - 1
    return ((equities[-1] / equities[0]) ** (365.0 / n) - 1.0) * 100.0


def _maxdd(equities: list[float]) -> float:
    """Max drawdown as a positive percentage (0 = no drawdown)."""
    peak = equities[0]
    worst = 0.0
    for e in equities:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > worst:
            worst = dd
    return worst * 100.0


def _calmar(apy: float, dd: float) -> float | None:
    if dd <= 0:
        return None
    return apy / dd


# ── portfolio blend ───────────────────────────────────────────────────────────────────────────────

def _blend(series_list: list[list[float]], weights: list[float]) -> list[float]:
    """Blend N equity series by weight (all series must have same length)."""
    n = min(len(s) for s in series_list)
    # initial portfolio value = weighted sum of initial equities (normalised to 1 unit)
    # Convert each series to daily-return form; start equity at 100k
    INIT = 100_000.0
    portfolio = [INIT]
    for i in range(1, n):
        daily_r = sum(
            weights[k] * (series_list[k][i] / series_list[k][i - 1] - 1.0)
            for k in range(len(weights))
            if series_list[k][i - 1] > 0
        )
        portfolio.append(portfolio[-1] * (1.0 + daily_r))
    return portfolio


# ── crisis-window loss (LOOK-AHEAD — uses known fixture window_hits) ──────────────────────────────

# These are the exact window_hits from fixtures._SPEC — look-ahead by construction.
_WINDOW_HITS: dict[str, dict[str, float]] = {
    "susde_dn":     {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09, "rseth_depeg_2026_04": 0.01},
    "lrt_carry":    {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04, "rseth_depeg_2026_04": 0.22},
    "leverage_loop":{"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28, "rseth_depeg_2026_04": 0.11},
    "points_farm":  {"eth_crash_2024_08": 0.01, "usde_unwind_2025_10": 0.02, "rseth_depeg_2026_04": 0.015},
    "variant_d":    {"eth_crash_2024_08": 0.18, "usde_unwind_2025_10": 0.10, "rseth_depeg_2026_04": 0.20},
}

_WINDOWS = ["eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"]


def _window_losses(weights: list[float], sids: list[str]) -> dict[str, float]:
    """Weighted combined loss per crisis window (look-ahead)."""
    return {
        w: sum(weights[i] * _WINDOW_HITS[sids[i]].get(w, 0.0) for i in range(len(sids)))
        for w in _WINDOWS
    }


def _max_window_loss(weights: list[float], sids: list[str]) -> float:
    return max(_window_losses(weights, sids).values())


# ── simplex sweep ─────────────────────────────────────────────────────────────────────────────────

def _simplex_weights(n_strategies: int, step: int = 10) -> list[tuple[int, ...]]:
    """All integer weight tuples (each in 0..100, sum = 100, step ppt)."""
    steps = range(0, 101, step)
    result = []
    for combo in iterproduct(steps, repeat=n_strategies):
        if sum(combo) == 100:
            result.append(combo)
    return result


# ── class-D penalty run ───────────────────────────────────────────────────────────────────────────

_CLASS_D_STRATEGIES = {"points_farm"}
_CLASS_D_APY_DISCOUNT = 0.50  # assume 50 % APY decay over the period for incentive/airdrop farms


def _penalise_series(sid: str, equities: list[float]) -> list[float]:
    """Cut APY by CLASS_D_APY_DISCOUNT for class-D strategies by compressing daily returns."""
    if sid not in _CLASS_D_STRATEGIES:
        return equities
    out = [equities[0]]
    for i in range(1, len(equities)):
        raw_r = equities[i] / equities[i - 1] - 1.0
        penalised_r = raw_r * (1.0 - _CLASS_D_APY_DISCOUNT)
        out.append(out[-1] * (1.0 + penalised_r))
    return out


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def compute(penalise_class_d: bool = False) -> dict:
    """Run the sweep. Returns result dict with all key portfolios."""
    raw_series = _load_fixture_series()
    sids = sorted(raw_series)  # deterministic ordering
    n = len(sids)
    if n == 0:
        return {"error": "no fixture strategies loaded"}

    series = {
        sid: (_penalise_series(sid, raw_series[sid]) if penalise_class_d else raw_series[sid])
        for sid in sids
    }

    # truncate all to the same length (shortest)
    min_len = min(len(series[s]) for s in sids)
    series_list = [series[s][:min_len] for s in sids]

    weight_tuples = _simplex_weights(n, step=10)

    best_calmar = {"calmar": None, "weights": None}
    best_tail = {"max_window_loss": 1e9, "calmar": None, "weights": None}
    equal_w = tuple(100 // n for _ in range(n))
    equal_result = None
    rows = []

    for wt in weight_tuples:
        w = [wt[i] / 100.0 for i in range(n)]
        portfolio = _blend(series_list, w)
        apy = _apy(portfolio)
        dd = _maxdd(portfolio)
        cal = _calmar(apy, dd)
        mwl = _max_window_loss(w, sids)
        wloss = _window_losses(w, sids)

        row = {
            "weights": dict(zip(sids, wt)),
            "apy": round(apy, 2),
            "maxdd": round(dd, 2),
            "calmar": round(cal, 2) if cal is not None else None,
            "max_window_loss_pct": round(mwl * 100, 2),
            "window_losses_pct": {k: round(v * 100, 2) for k, v in wloss.items()},
        }
        rows.append(row)

        if wt == equal_w or (equal_result is None and all(abs(wi - 1.0 / n) < 0.05 for wi in w)):
            equal_result = row

        if cal is not None and (best_calmar["calmar"] is None or cal > best_calmar["calmar"]):
            best_calmar = row.copy()

        if mwl < best_tail["max_window_loss"]:
            best_tail = row.copy()
            best_tail["max_window_loss"] = mwl

    # pareto frontier: for each max_window_loss bucket, best calmar
    wl_buckets: dict[float, dict] = {}
    for r in rows:
        key = round(r["max_window_loss_pct"], 0)
        c = r["calmar"]
        if c is not None and (key not in wl_buckets or c > wl_buckets[key]["calmar"]):
            wl_buckets[key] = r

    pareto = sorted(wl_buckets.values(), key=lambda x: x["max_window_loss_pct"])

    return {
        "n_strategies": n,
        "strategies": sids,
        "n_combos": len(weight_tuples),
        "series_length_days": min_len,
        "penalise_class_d": penalise_class_d,
        "best_calmar": best_calmar,
        "best_tail": best_tail,
        "equal_weight": equal_result,
        "pareto_frontier": pareto[:15],  # first 15 buckets (lowest tail to highest)
    }


def _fmt(x, suffix=""):
    if x is None:
        return "n/a"
    return f"{x:.1f}{suffix}"


def _weights_str(w: dict) -> str:
    return " | ".join(f"{k}:{v}%" for k, v in sorted(w.items()))


def run() -> None:
    print("=" * 72)
    print("NOVEL-EDGE R&D — Tail-Orthogonal Portfolio Frontier [bt]")
    print("IS_ADVISORY=True | OUTSIDE_RISKPOLICY=True | Evidence: L0")
    print("=" * 72)
    print()

    for penalise in [False, True]:
        label = "FULL APY (fixture as-is)" if not penalise else "CLASS-D PENALTY (points_farm APY ×0.5)"
        print(f"── RUN: {label} ──")
        r = compute(penalise_class_d=penalise)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue

        print(f"  Strategies ({r['n_strategies']}): {', '.join(r['strategies'])}")
        print(f"  Sweep:  {r['n_combos']} weight combinations (10 ppt steps)")
        print(f"  Days:   {r['series_length_days']}")
        print()

        eq = r["equal_weight"]
        bc = r["best_calmar"]
        bt = r["best_tail"]

        print(f"  EQUAL-WEIGHT ({100//r['n_strategies']}% each) [bt]:")
        if eq:
            print(f"    APY {_fmt(eq['apy'],'%')}  maxDD {_fmt(eq['maxdd'],'%')}"
                  f"  Calmar {_fmt(eq['calmar'])}  max-window-loss {_fmt(eq['max_window_loss_pct'],'%')}")
        print()

        print(f"  CALMAR-OPTIMAL [bt]:")
        print(f"    APY {_fmt(bc['apy'],'%')}  maxDD {_fmt(bc['maxdd'],'%')}"
              f"  Calmar {_fmt(bc['calmar'])}  max-window-loss {_fmt(bc['max_window_loss_pct'],'%')}")
        print(f"    Weights: {_weights_str(bc['weights'])}")
        print()

        print(f"  TAIL-OPTIMAL (min max-window-loss) [bt]:")
        print(f"    APY {_fmt(bt['apy'],'%')}  maxDD {_fmt(bt['maxdd'],'%')}"
              f"  Calmar {_fmt(bt['calmar'])}  max-window-loss {_fmt(bt['max_window_loss_pct'],'%')}")
        print(f"    Weights: {_weights_str(bt['weights'])}")
        wl = bt.get("window_losses_pct", {})
        for w_name, val in sorted(wl.items()):
            print(f"      {w_name}: {_fmt(val,'%')}")
        print()

        print("  PARETO FRONTIER (tail-vs-Calmar, top-Calmar per window-loss bucket) [bt]:")
        print(f"  {'max-wl%':>9}  {'Calmar':>7}  {'APY%':>7}  {'maxDD%':>7}  top-weights")
        for row in r["pareto_frontier"]:
            top2 = sorted(row["weights"].items(), key=lambda x: -x[1])[:2]
            top_str = " ".join(f"{k}:{v}%" for k, v in top2)
            print(f"  {_fmt(row['max_window_loss_pct']):>9}  {_fmt(row['calmar']):>7}"
                  f"  {_fmt(row['apy']):>7}  {_fmt(row['maxdd']):>7}  {top_str}")
        print()

    print("─" * 72)
    print("HONEST CAVEATS (all numbers [bt] = backtest/synthetic, NOT live):")
    print(" (a) LOOK-AHEAD: tail-optimal uses KNOWN crisis window hits from fixture spec.")
    print("     In reality, crises are unpredictable — this is a frontier, not a strategy.")
    print(" (b) CLASS-D RISK: points_farm uses constant 14% APY in fixture. Incentive/airdrop")
    print("     farms decay. The 50%-cut penalty run tests whether conclusions survive.")
    print(" (c) Fixture front-loads 50% of each crisis on day-1. Real crises develop gradually.")
    print(" (d) Only 5 strategies. Real aggressive-tier blends may have different shape mix.")
    print(" (e) IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True. No capital moves. L0 evidence only.")
    print(" (f) Calmar = APY / maxDD. Strategies with near-zero maxDD have undefined Calmar.")


if __name__ == "__main__":
    run()
