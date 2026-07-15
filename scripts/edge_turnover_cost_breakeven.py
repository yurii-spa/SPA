#!/usr/bin/env python3
"""
scripts/edge_turnover_cost_breakeven.py — Idea #10: Turnover-Cost Break-Even

NOVEL EDGE IDEA #10 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE HONESTY PROBLEM THIS IDEA ATTACKS
  Idea #9 established the honest LIVE-ATTAINABLE Calmar of the causal (no-look-ahead)
  crisis overlay: ~3.68 vs static #3's 2.03. But #9 (and #1–#8 before it) assumed
  FREE REBALANCING — every regime switch (25/50/25 ⇄ 5/25/70 ⇄ 40/45/15) moves real
  capital across three sleeves at ZERO cost. Live, each switch pays:
    • gas + DEX slippage to rotate sUSDe/rates/RWA sizes,
    • perp-hedge unwind/re-open spread on the delta-neutral sUSDe leg (worst exactly
      during crises, when perp books are congested — the caveat #8(d) already flagged).

  So the second killer question a funder asks — after "can you do it live without knowing
  crisis dates?" (idea #9) — is: "does the edge survive REAL trading costs?"

THE IDEA (Turnover-Cost Break-Even, TCB)
  Re-run the SAME causal drawdown overlay as #9, but charge a realistic cost on every
  rebalance, proportional to one-way turnover:

      turnover_t = 0.5 * Σ_i |w_t[i] − w_{t-1}[i]|          (one-way, in [0,1])
      cost_t     = turnover_t * cost_bps / 10_000          (fraction of equity)
      equity_t   = equity_t * (1 − cost_t)                 (charged at the switch)

  Sweep cost_bps ∈ {0, 5, 10, 20, 35, 50, 75, 100} and locate the BREAK-EVEN cost —
  the per-unit-turnover cost at which the net causal Calmar drops to static #3's Calmar.
  Above break-even the overlay is not worth trading; below it the honest edge is real net.

WHAT A HIGH / LOW BREAK-EVEN MEANS
  HIGH break-even (e.g. > 50 bps/switch): the edge is ROBUST to real costs → fundable
    even with meaningful slippage. Strong result.
  LOW break-even (e.g. < 10 bps/switch): the edge is FRAGILE — realistic DeFi rebalance
    costs (gas + slippage + hedge spread, easily 10–50 bps in a stressed market) would
    erase it. Important, sobering finding: the causal overlay needs cheap execution or
    a low switch-count design to be worth running.

HONEST CAVEATS
  (a) Cost is modeled as a flat bps-of-turnover, applied on the switch day. Real DeFi
      cost is state-dependent (higher slippage in thin/stressed markets — i.e. WORSE
      exactly when the overlay switches most). This flat model is therefore an
      OPTIMISTIC lower bound on true cost; the real break-even is reached SOONER.
  (b) Turnover counts sleeve-weight changes only; it does not model the perp-hedge
      leg's separate roll cost, which adds further drag on the sUSDe portion.
  (c) rates-carry + RWA-floor are SMOOTH SYNTHETIC; sUSDe carries the real crisis vol
      (same fixture as #7/#8/#9 — this adds ONLY the cost dimension, apples-to-apples).
  (d) Uses the #9 best-honest params (θ_enter=0.3%, θ_exit=0.1%, harvest=21d) so the
      comparison isolates cost, not re-tuning.
  (e) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402

# ── constants (identical sleeves to #3/#7/#8/#9) ────────────────────────────────────────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT = 3.31

WEIGHTS_CRUISE  = [0.25, 0.50, 0.25]  # #3
WEIGHTS_DEFEND  = [0.05, 0.25, 0.70]  # #7
WEIGHTS_HARVEST = [0.40, 0.45, 0.15]  # #8

# #9 best-honest causal params (drawdown fractions)
THETA_ENTER = 0.003
THETA_EXIT = 0.001
HARVEST_DAYS = 21


# ── data (same loader as #8/#9) ─────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="tcb_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture not available")
    eq: Dict[str, float] = {}
    for p in s.backtest.series:
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq[d] = float(e)
    dates = sorted(eq)
    return {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0
            for i in range(1, len(dates)) if eq[dates[i - 1]]}


def _smooth(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── engines ─────────────────────────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(equity) < 2:
        return None, None, None
    n_days = len(equity) - 1
    net_apy = (equity[-1] / equity[0]) ** (365.0 / n_days) - 1.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = abs(max_dd) * 100.0
    calmar = (net_apy * 100.0) / max_dd_pct if max_dd_pct > 0 else None
    return net_apy * 100.0, max_dd_pct, calmar


def _static_equity(dates, r_s, r_r, r_w, weights) -> List[float]:
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = weights[0] * r_s.get(d, 0.0) + weights[1] * r_r.get(d, 0.0) + weights[2] * r_w.get(d, 0.0)
        eq *= (1.0 + r)
        out.append(eq)
    return out


def _causal_weight_path(
    dates: List[str],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
) -> List[List[float]]:
    """
    The #9 causal regime → weight sequence, decided on the GROSS (cost-free) equity path.

    Textbook transaction-cost modeling: the SIGNAL is computed on the market/price path;
    costs are a separate drag on realized P&L (below). Deciding the regime on the gross
    path avoids the pathological cost→equity→signal feedback loop (charging cost on the
    equity that drives the drawdown trigger makes tiny cost noise cross the 0.3% threshold
    and manufacture spurious switches — a modeling artifact, not a real edge property).
    """
    eq = 100_000.0
    hwm = eq
    was_defending = False
    harvest_left = 0
    weights: List[List[float]] = []
    for d in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -THETA_ENTER:
            w = WEIGHTS_DEFEND
            was_defending = True
            harvest_left = 0
        else:
            if was_defending and dd >= -THETA_EXIT:
                was_defending = False
                harvest_left = HARVEST_DAYS
            if harvest_left > 0:
                w = WEIGHTS_HARVEST
                harvest_left -= 1
            else:
                w = WEIGHTS_CRUISE
        weights.append(w)
        r = w[0] * r_s.get(d, 0.0) + w[1] * r_r.get(d, 0.0) + w[2] * r_w.get(d, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
    return weights


def _replay_with_cost(
    dates: List[str],
    weights: List[List[float]],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
    cost_bps: float,
) -> Tuple[List[float], int, float]:
    """
    Replay a FIXED weight sequence, deducting one-way turnover cost on each change.
    Turnover (and hence switch count) is fixed by the weight path → cost scales cleanly.
    Returns (net_equity_series, n_switches, total_turnover).
    """
    eq = 100_000.0
    out = [eq]
    prev_w = WEIGHTS_CRUISE
    n_switches = 0
    total_turnover = 0.0
    for i, d in enumerate(dates):
        w = weights[i]
        if w != prev_w:
            turnover = 0.5 * sum(abs(w[j] - prev_w[j]) for j in range(3))
            total_turnover += turnover
            n_switches += 1
            eq *= (1.0 - turnover * cost_bps / 10_000.0)
        prev_w = w
        r = w[0] * r_s.get(d, 0.0) + w[1] * r_r.get(d, 0.0) + w[2] * r_w.get(d, 0.0)
        eq *= (1.0 + r)
        out.append(eq)
    return out, n_switches, total_turnover


def _f(x: Optional[float], d: int = 2) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


# ── analysis (importable, deterministic) ────────────────────────────────────────────────────────────

COST_GRID = [0.0, 5.0, 10.0, 20.0, 35.0, 50.0, 75.0, 100.0]


def run_analysis() -> Dict[str, object]:
    r_s = _load_susde_returns()
    dates = sorted(r_s)
    r_r = _smooth(dates, RATES_APY_PCT)
    r_w = _smooth(dates, RWA_APY_PCT)

    eq_static = _static_equity(dates, r_s, r_r, r_w, WEIGHTS_CRUISE)
    apy_s, dd_s, cal_s = _metrics(eq_static)

    # regime/weight path decided ONCE on the gross path (signal on prices, cost as drag)
    weights = _causal_weight_path(dates, r_s, r_r, r_w)

    rows = []
    for cost_bps in COST_GRID:
        eq9, n_sw, turn = _replay_with_cost(dates, weights, r_s, r_r, r_w, cost_bps)
        apy, dd, cal = _metrics(eq9)
        rows.append({"cost_bps": cost_bps, "apy": apy, "dd": dd, "calmar": cal,
                     "n_switches": n_sw, "total_turnover": turn})

    # break-even cost: linear-interpolate where causal Calmar crosses static Calmar
    breakeven = None
    for i in range(1, len(rows)):
        c0, c1 = rows[i - 1], rows[i]
        k0 = c0["calmar"]
        k1 = c1["calmar"]
        if not (isinstance(k0, float) and isinstance(k1, float) and isinstance(cal_s, float)):
            continue
        if (k0 - cal_s) >= 0 >= (k1 - cal_s) and k0 != k1:
            frac = (k0 - cal_s) / (k0 - k1)
            breakeven = c0["cost_bps"] + frac * (c1["cost_bps"] - c0["cost_bps"])
            break
    # if never crosses within the grid, it's either >max (robust) or <0 (already below at 0)
    return {
        "dates": dates,
        "static": {"apy": apy_s, "dd": dd_s, "calmar": cal_s},
        "rows": rows,
        "breakeven_bps": breakeven,
    }


# ── main (human-readable report) ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 74)
    print("IDEA #10: Turnover-Cost Break-Even for the causal crisis overlay (#9)")
    print("Does the honest (no-look-ahead) edge SURVIVE realistic rebalancing costs?")
    print("All numbers: BACKTEST / SYNTHETIC. NOT live results.")
    print("=" * 74)

    res = run_analysis()
    dates = res["dates"]
    st = res["static"]
    rows = res["rows"]
    be = res["breakeven_bps"]

    print(f"\nBacktest window: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print("Overlay = #9 causal (θ_enter=0.3%, θ_exit=0.1%, harvest=21d). Cost charged on each switch.")
    print(f"\n── Reference: static cross-desk #3 (25/50/25, no switching, no cost) ──────")
    print(f"  APY {_f(st['apy'])}%  maxDD {_f(st['dd'])}%  Calmar {_f(st['calmar'])}")

    r0 = rows[0]
    print(f"\n── COST SWEEP (causal #9 net of turnover cost) ─────────────────────────────")
    print(f"  Switches over backtest: {r0['n_switches']}  |  total one-way turnover: "
          f"{_f(r0['total_turnover'])}")
    print(f"  {'cost/switch':>11} {'net APY':>8} {'maxDD':>7} {'net Calmar':>11} {'vs static':>10}")
    print(f"  {'-'*11} {'-'*8} {'-'*7} {'-'*11} {'-'*10}")
    for row in rows:
        delta = (row["calmar"] - st["calmar"]
                 if isinstance(row["calmar"], float) and isinstance(st["calmar"], float) else None)
        marker = ""
        delta_str = "n/a"
        if isinstance(delta, float):
            delta_str = f"{delta:+.2f}"
            marker = "  ← edge gone" if delta <= 0 else ""
        print(f"  {row['cost_bps']:>9.0f}bp {_f(row['apy']):>8} {_f(row['dd']):>7} "
              f"{_f(row['calmar']):>11} {delta_str:>10}{marker}")

    print(f"\n── BREAK-EVEN COST ─────────────────────────────────────────────────────────")
    if be is None:
        # decide which side
        last = rows[-1]["calmar"]
        first = rows[0]["calmar"]
        if isinstance(last, float) and isinstance(st["calmar"], float) and last > st["calmar"]:
            print(f"  > {rows[-1]['cost_bps']:.0f} bps/switch — edge STILL beats static #3 at the highest")
            print(f"    tested cost. ROBUST to realistic costs within this grid.")
        elif isinstance(first, float) and isinstance(st["calmar"], float) and first <= st["calmar"]:
            print(f"  ≈ 0 bps — even at ZERO cost the overlay does not beat static #3 (see #9 verdict).")
        else:
            print(f"  not resolved within grid.")
    else:
        print(f"  ≈ {be:.1f} bps of one-way turnover per switch.")
        print(f"  Below ~{be:.0f} bps/switch: the causal edge is real NET of cost.")
        print(f"  Above ~{be:.0f} bps/switch: static #3 (no trading) is better.")

    # ── verdict ──────────────────────────────────────────────────────────────────────────────────────
    print(f"\n── VERDICT ─────────────────────────────────────────────────────────────────")
    if be is None:
        last = rows[-1]["calmar"]
        if isinstance(last, float) and isinstance(st["calmar"], float) and last > st["calmar"]:
            verdict = "✅ ROBUST — edge survives every tested cost up to 100 bps/switch"
            note = ("The overlay switches rarely enough that even heavy per-switch cost does not "
                    "erase the causal edge over static #3. Fundable net of realistic slippage.")
        else:
            verdict = "❌ NEGATIVE — overlay never beats static #3 (matches #9 if #9 was ≤static)"
            note = "See #9; the causal edge itself, not cost, is the binding constraint."
    elif be >= 50.0:
        verdict = f"✅ ROBUST — break-even ≈ {be:.0f} bps/switch (survives typical DeFi rebalance cost)"
        note = ("Real gas+slippage+hedge-spread on a rare-switching overlay is usually well under "
                f"{be:.0f} bps → the honest edge holds net of cost.")
    elif be >= 15.0:
        verdict = f"⚠️ CONDITIONAL — break-even ≈ {be:.0f} bps/switch (survives ONLY with cheap execution)"
        note = ("The edge is real but thin: a stressed-market rebalance (thin perp books, high gas) "
                f"can exceed {be:.0f} bps and erase it. Needs low-cost execution or fewer switches.")
    else:
        verdict = f"❌ FRAGILE — break-even ≈ {be:.1f} bps/switch (realistic costs erase the edge)"
        note = ("Real DeFi rebalance cost (10–50 bps in stress) exceeds break-even → the causal "
                "overlay is NOT worth trading as-is. Redesign for far fewer switches, or drop it.")
    print(f"  Verdict: {verdict}")
    print(f"  {note}")
    print(f"\n  HONEST CAVEATS:")
    print(f"  (a) Flat bps-of-turnover cost is OPTIMISTIC — real slippage is worst in the stressed")
    print(f"      markets where the overlay switches most, so true break-even is reached SOONER.")
    print(f"  (b) Perp-hedge roll cost on the sUSDe leg is NOT included (adds further drag).")
    print(f"  (c) Regime is decided on the GROSS path (signal-on-prices, cost-as-drag). A live")
    print(f"      controller watching NET equity would see cost-induced drawdown feed back into")
    print(f"      the tight 0.3% threshold and churn MORE — so the tight-θ design is even more")
    print(f"      cost-fragile than this clean drag model shows. Prefer wider θ / fewer switches.")
    print(f"  (d) rates/RWA smooth synthetic; sUSDe carries real crisis vol (same fixture as #7/#8/#9).")
    print(f"  (e) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print(f"\n  NEXT STEP: report the causal edge NET of a conservative cost assumption, not gross;")
    print(f"  and prefer overlay designs that switch rarely (the switch count IS the cost driver).")
    print(f"  ADR required before any real capital movement.")


if __name__ == "__main__":
    main()
