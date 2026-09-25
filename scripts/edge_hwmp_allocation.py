#!/usr/bin/env python3
"""
scripts/edge_hwmp_allocation.py — Idea #114: High-Water-Mark Proportional (HWMP) Allocation

NOVEL EDGE IDEA #114 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE CORE IDEA
  All prior multi-leg ideas use either:
    (A) Static fixed weights (#3: 25/50/25)
    (B) Binary demotion from portfolio (#39 CDR, #40 XSD, #45 XVD)
    (C) Threshold-based kill/restore (#48 PKP)
    (D) Signal-based regime switch (#113 CMRS)

  HWMP uses a CONTINUOUSLY UPDATING, PATH-DEPENDENT sizing:
  Each leg's weight is proportional to exp(−α × drawdown_from_HWM).

  When a leg is at its running peak → weight = exp(0) = 1 (full contribution).
  When a leg is in drawdown from its peak by δ → weight = exp(−α × δ) < 1.

  Concretely:
    peak(b, t)   = max(equity(b, s) for s ≤ t−1)   [causal: use yesterday's peak]
    dd(b, t)     = 1 − equity(b, t−1) / peak(b, t)  [fraction below peak, ≥0]
    score(b, t)  = exp(−α × dd(b, t))
    w(b, t)      = score(b, t) / Σ_b score(b, t)

  Portfolio return on day t:
    r_port(t) = Σ_b w(b, t) × r(b, t)

WHY THIS IS STRUCTURALLY DIFFERENT
  • From XVD (#45): XVD demotes binary (below median vol → out). HWMP sizes continuously
    and uses DRAWDOWN PATH not realized volatility.
  • From CDR (#39): CDR readmits after M days of no loss. HWMP readmits as soon as a leg
    RECOVERS toward its HWM (drawdown decreases → exp score increases).
  • From static #3: weights adapt continuously to actual loss events.
  • Economic intuition: "If I lost 20% from peak in leg X, I believe there's ongoing risk;
    wait for it to RECOVER before reinstating full size." This is the Kelly-corrected
    position-sizing principle applied to the path.

FIXTURE BEHAVIOR
  CALM:  all legs at HWM → dd = 0 → score = exp(0) = 1 for all → equal weight.
         (No unnecessary overweighting of the high-drift leg during calm.)
  CRISIS day 1:  unavoidable (causal). dd starts accumulating.
  CRISIS day 2+: hit leg shows dd > 0 → gets downweighted relative to other legs.
  RECOVERY:  leg rebuilds equity → dd shrinks → weight recovers smoothly.
             α controls speed: high α = punish drawdown harshly (slow readmit).
             low α = punish drawdown gently (fast readmit).

PARAMETERS SWEPT
  legs ∈ 4 backtest-eligible strategies (susde_dn, lrt_carry, leverage_loop, points_farm)
  α ∈ {5, 10, 20, 50}   — drawdown sensitivity

BASELINES
  ew4:          Equal-weight 4 legs (static reference)
  susde_dn:     Single-leg (best risk-adjusted in prior registry)
  leverage_loop: Single-leg (highest headline)

COSTS
  96 bp round-trip switching cost (consistent with #10 and registry convention).
  Daily turnover = 0.5 × Σ_b |w(b,t) − w(b,t−1)| × 96 bp.
  (This reflects that HWMP costs are proportional to actual weight changes, not
   a per-switch flat fee.)

HONEST CAVEATS
  (a) Fixture σ²≈0 in calm periods → in calm, all legs at HWM → no weight signal.
      The only information comes from the crisis windows.
  (b) Day-1 crisis hit is unavoidable with causal sizing.
  (c) Fixture has only 3 crises (limited sample for tuning α).
  (d) In real markets, HWM-based sizing is subject to re-entry timing risk:
      a recovering leg that gets re-weighted could suffer a second drawdown.
  (e) EWM Sharpe-ratio alternative (originally planned as #114) collapsed to the same
      degeneracy on this fixture: σ=0 in calm → Sharpe = ε for all → equal weight.
      HWMP survives this because path/peak is non-degenerate even with σ=0 drift.

EVIDENCE LEVEL: L0 (backtest on deterministic synthetic fixture, NOT live data)
stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# ── import path setup ────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from spa_core.strategy_lab.aggressive_lab.fixtures import (  # noqa: E402
    _build_backtest_series,
    _SPEC,
    _BACKTEST_START,
    _BACKTEST_END,
)

# ── constants ────────────────────────────────────────────────────────────────
COST_RT_BPS = 96          # round-trip cost basis points (from #10 registry)
COST_RT = COST_RT_BPS / 10_000.0
LEGS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm"]

# Stress windows (for per-crisis reporting)
CRISIS_WINDOWS = [
    ("eth_crash_2024_08",    "2024-08-01", "2024-08-31"),
    ("usde_unwind_2025_10",  "2025-10-01", "2025-10-31"),
    ("rseth_depeg_2026_04",  "2026-04-01", "2026-04-30"),
]


def _date_range_idx(dates: list, start: str, end: str):
    """Return [i_start, i_end] indices (inclusive) for a date range."""
    i0 = next((i for i, d in enumerate(dates) if d >= start), None)
    i1 = next((i for i, d in enumerate(dates) if d > end), len(dates)) - 1
    return i0, i1


def _build_returns(leg_id: str):
    """Return list of (date, daily_return) for the backtest period."""
    series = _build_backtest_series(_SPEC[leg_id])
    # filter to backtest phase only, extract fractional returns
    days = []
    prev_eq = None
    for row in series:
        if row["phase"] != "backtest":
            continue
        eq = row["equity_usd"]
        if prev_eq is None:
            r = 0.0
        else:
            r = eq / prev_eq - 1.0
        days.append((row["date"], r))
        prev_eq = eq
    return days


def _run_hwmp(alpha: float, ew_fallback: bool = True) -> dict:
    """
    Run HWMP allocation across LEGS with given alpha.
    Returns performance summary dict.
    """
    # Build per-leg return series (aligned by date)
    leg_returns = {lid: _build_returns(lid) for lid in LEGS}
    # Verify all legs have the same dates
    dates = [d for d, _ in leg_returns[LEGS[0]]]
    for lid in LEGS[1:]:
        assert [d for d, _ in leg_returns[lid]] == dates, f"Date mismatch: {lid}"

    n = len(dates)
    leg_r = {lid: [r for _, r in leg_returns[lid]] for lid in LEGS}

    # --- Simulation ---
    equity = 100_000.0
    equity_curve = []
    weights_prev = [1.0 / len(LEGS)] * len(LEGS)  # initial equal weight
    peak = {lid: 100_000.0 for lid in LEGS}
    leg_equity = {lid: 100_000.0 for lid in LEGS}  # per-leg tracking equity
    total_cost = 0.0

    for t in range(n):
        # ── Causal weight computation: use end-of-day t−1 state ──────────────
        if t == 0:
            weights = [1.0 / len(LEGS)] * len(LEGS)
        else:
            # Update peak with yesterday's equity (already updated at end of t-1)
            scores = []
            for lid in LEGS:
                dd = max(0.0, 1.0 - leg_equity[lid] / max(peak[lid], 1e-9))
                scores.append(math.exp(-alpha * dd))
            s_total = sum(scores)
            if s_total < 1e-12 or not ew_fallback:
                weights = [1.0 / len(LEGS)] * len(LEGS)
            else:
                weights = [s / s_total for s in scores]

        # ── Turnover cost ─────────────────────────────────────────────────────
        turnover = 0.5 * sum(abs(w - wp) for w, wp in zip(weights, weights_prev))
        daily_cost = turnover * COST_RT
        total_cost += daily_cost

        # ── Portfolio return ──────────────────────────────────────────────────
        port_r = sum(w * leg_r[lid][t] for w, lid in zip(weights, LEGS))
        net_r = port_r - daily_cost

        equity = equity * (1.0 + net_r)
        equity_curve.append((dates[t], equity))

        # ── Update per-leg equity and peaks ──────────────────────────────────
        for lid in LEGS:
            leg_equity[lid] = leg_equity[lid] * (1.0 + leg_r[lid][t])
            if leg_equity[lid] > peak[lid]:
                peak[lid] = leg_equity[lid]

        weights_prev = weights

    # ── Performance metrics ───────────────────────────────────────────────────
    n_days = len(equity_curve)
    final_eq = equity_curve[-1][1]
    total_return = final_eq / 100_000.0 - 1.0
    net_apy = (final_eq / 100_000.0) ** (365.0 / n_days) - 1.0

    # Max drawdown
    peak_eq = 100_000.0
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq
        if dd > max_dd:
            max_dd = dd

    calmar = net_apy / max_dd if max_dd > 1e-9 else float("inf")

    # Per-crisis drawdown
    crisis_results = {}
    eq_list = [eq for _, eq in equity_curve]
    date_list = [d for d, _ in equity_curve]
    for cname, cstart, cend in CRISIS_WINDOWS:
        i0, i1 = _date_range_idx(date_list, cstart, cend)
        if i0 is None or i0 > i1:
            crisis_results[cname] = None
            continue
        eq_before = eq_list[i0 - 1] if i0 > 0 else 100_000.0
        eq_trough = min(eq_list[i0:i1 + 1])
        crisis_dd = (eq_before - eq_trough) / eq_before
        crisis_results[cname] = round(crisis_dd * 100, 3)

    return {
        "alpha": alpha,
        "net_apy_pct": round(net_apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3),
        "total_cost_bps": round(total_cost * 10_000, 1),
        "crisis": crisis_results,
        "n_days": n_days,
        "total_return_pct": round(total_return * 100, 3),
    }


def _run_static_ew4() -> dict:
    """Equal-weight 4-leg static baseline (no rebalancing cost: weights constant)."""
    leg_returns = {lid: _build_returns(lid) for lid in LEGS}
    dates = [d for d, _ in leg_returns[LEGS[0]]]
    n = len(dates)
    leg_r = {lid: [r for _, r in leg_returns[lid]] for lid in LEGS}

    equity = 100_000.0
    equity_curve = []
    for t in range(n):
        port_r = sum(leg_r[lid][t] for lid in LEGS) / len(LEGS)
        equity = equity * (1.0 + port_r)
        equity_curve.append((dates[t], equity))

    n_days = len(equity_curve)
    final_eq = equity_curve[-1][1]
    net_apy = (final_eq / 100_000.0) ** (365.0 / n_days) - 1.0
    peak_eq = 100_000.0
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq
        if dd > max_dd:
            max_dd = dd
    calmar = net_apy / max_dd if max_dd > 1e-9 else float("inf")

    eq_list = [eq for _, eq in equity_curve]
    date_list = [d for d, _ in equity_curve]
    crisis_results = {}
    for cname, cstart, cend in CRISIS_WINDOWS:
        i0, i1 = _date_range_idx(date_list, cstart, cend)
        if i0 is None or i0 > i1:
            crisis_results[cname] = None
            continue
        eq_before = eq_list[i0 - 1] if i0 > 0 else 100_000.0
        eq_trough = min(eq_list[i0:i1 + 1])
        crisis_dd = (eq_before - eq_trough) / eq_before
        crisis_results[cname] = round(crisis_dd * 100, 3)

    return {
        "label": "EW-4 static",
        "net_apy_pct": round(net_apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3),
        "crisis": crisis_results,
    }


def _run_single_leg(lid: str) -> dict:
    """Single-leg baseline."""
    days = _build_returns(lid)
    n = len(days)
    equity = 100_000.0
    equity_curve = []
    for _, r in days:
        equity = equity * (1.0 + r)
        equity_curve.append(equity)
    net_apy = (equity_curve[-1] / 100_000.0) ** (365.0 / n) - 1.0
    peak_eq = 100_000.0
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq
        if dd > max_dd:
            max_dd = dd
    calmar = net_apy / max_dd if max_dd > 1e-9 else float("inf")
    return {
        "label": lid,
        "net_apy_pct": round(net_apy * 100, 3),
        "max_dd_pct": round(max_dd * 100, 3),
        "calmar": round(calmar, 3),
    }


def main():
    print("=" * 70)
    print("IDEA #114 — HWMP: High-Water-Mark Proportional Allocation (bt)")
    print("EVIDENCE LEVEL: L0 (deterministic synthetic fixture, NOT live data)")
    print(f"Fixture legs: {LEGS}")
    print(f"Backtest period: {_BACKTEST_START} .. {_BACKTEST_END}")
    print(f"Round-trip cost: {COST_RT_BPS} bp")
    print()

    # ── Baselines ─────────────────────────────────────────────────────────────
    print("── BASELINES ────────────────────────────────────────────────────────")
    ew4 = _run_static_ew4()
    print(f"  EW-4 static:    netAPY={ew4['net_apy_pct']:.2f}%  "
          f"maxDD={ew4['max_dd_pct']:.2f}%  Calmar={ew4['calmar']:.2f}")
    for lid in LEGS:
        r = _run_single_leg(lid)
        print(f"  {lid:16s}: netAPY={r['net_apy_pct']:.2f}%  "
              f"maxDD={r['max_dd_pct']:.2f}%  Calmar={r['calmar']:.2f}")
    print()

    # ── HWMP sweep ────────────────────────────────────────────────────────────
    print("── HWMP (α sweep) ───────────────────────────────────────────────────")
    alphas = [5, 10, 20, 50]
    results = []
    best = None
    for alpha in alphas:
        r = _run_hwmp(alpha)
        results.append(r)
        marker = ""
        if best is None or r["calmar"] > best["calmar"]:
            best = r
            marker = "  ← best Calmar"
        print(f"  α={alpha:2d}: netAPY={r['net_apy_pct']:.2f}%  "
              f"maxDD={r['max_dd_pct']:.2f}%  Calmar={r['calmar']:.2f}  "
              f"cost={r['total_cost_bps']:.0f}bp  {marker}")
    print()

    # ── Per-crisis detail for best config ────────────────────────────────────
    print(f"── PER-CRISIS (best α={best['alpha']}) vs EW-4 ─────────────────────")
    print(f"  {'Crisis':<30s}  {'HWMP':>8s}  {'EW-4':>8s}  {'Δ':>8s}")
    for cname, _, _ in CRISIS_WINDOWS:
        hw_val = best["crisis"].get(cname)
        ew_val = ew4["crisis"].get(cname)
        hw_str = f"{hw_val:.2f}%" if hw_val is not None else "N/A"
        ew_str = f"{ew_val:.2f}%" if ew_val is not None else "N/A"
        delta_str = ""
        if hw_val is not None and ew_val is not None:
            delta = hw_val - ew_val
            delta_str = f"{delta:+.2f}%"
        print(f"  {cname:<30s}  {hw_str:>8s}  {ew_str:>8s}  {delta_str:>8s}")
    print()

    # ── Full table ────────────────────────────────────────────────────────────
    print("── FULL RESULTS TABLE ───────────────────────────────────────────────")
    print(f"  {'Config':<18}  {'netAPY':>8}  {'maxDD':>8}  {'Calmar':>8}  {'Cost':>8}")
    print(f"  {ew4['label']:<18}  {ew4['net_apy_pct']:>7.2f}%  "
          f"{ew4['max_dd_pct']:>7.2f}%  {ew4['calmar']:>8.2f}  {'0 bp':>8}")
    for r in results:
        lbl = f"HWMP α={r['alpha']}"
        print(f"  {lbl:<18}  {r['net_apy_pct']:>7.2f}%  "
              f"{r['max_dd_pct']:>7.2f}%  {r['calmar']:>8.2f}  "
              f"{r['total_cost_bps']:>5.0f} bp")
    print()

    # ── Verdict ───────────────────────────────────────────────────────────────
    ew4_calmar = ew4["calmar"]
    ew4_apy = ew4["net_apy_pct"]
    best_calmar = best["calmar"]
    best_apy = best["net_apy_pct"]

    print("── VERDICT ──────────────────────────────────────────────────────────")
    print(f"  EW-4 baseline:  netAPY={ew4_apy:.2f}%  Calmar={ew4_calmar:.2f}")
    print(f"  HWMP best:      netAPY={best_apy:.2f}%  Calmar={best_calmar:.2f}  "
          f"(α={best['alpha']})")
    delta_calmar = best_calmar - ew4_calmar
    delta_apy = best_apy - ew4_apy

    if best_calmar > ew4_calmar and best_apy >= ew4_apy - 0.5:
        verdict = "IMPROVED"
        symbol = "✅"
    elif best_calmar > ew4_calmar:
        verdict = "IMPROVED_CALMAR_ONLY"
        symbol = "⚠️"
    elif best_apy > ew4_apy + 1.0:
        verdict = "IMPROVED_APY_ONLY"
        symbol = "⚠️"
    else:
        verdict = "NO_IMPROVEMENT"
        symbol = "❌"

    print(f"\n  {symbol} Verdict: {verdict}")
    print(f"     ΔCalmar={delta_calmar:+.2f}  ΔnetAPY={delta_apy:+.2f}%")
    print()
    print("── FIXTURE DEGENERACY NOTE ──────────────────────────────────────────")
    print("  In calm periods: all legs at HWM → dd=0 → equal weight (correct)")
    print("  In crisis: hit leg dd>0 → downweighted → HWMP signal is ACTIVE")
    print("  Unlike signal-timing ideas, HWMP is non-degenerate on this fixture")
    print("  because path/peak is informative even with σ=0 drift.")
    print()
    print("bt — backtest on synthetic fixture. NOT realized performance.")

    # Return machine-readable result for registry
    return {
        "idea": "HWMP",
        "verdict": verdict,
        "best_alpha": best["alpha"],
        "best_netapy_pct_bt": best["net_apy_pct"],
        "best_maxdd_pct_bt": best["max_dd_pct"],
        "best_calmar_bt": best["calmar"],
        "ew4_calmar_bt": ew4_calmar,
        "ew4_netapy_pct_bt": ew4_apy,
    }


if __name__ == "__main__":
    result = main()
    sys.exit(0)
