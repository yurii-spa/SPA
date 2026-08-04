#!/usr/bin/env python3
"""
scripts/edge_drift_portfolio.py — Registry Idea #34: Allocation-Drift Portfolio (ADP)

THE GAP IN THE REGISTRY:
  Idea #32 (CFPT) proved on REAL books that reactive de-risk signals HURT positive-drift books.
  The mechanism (measured, not assumed): corr(reactivity, ΔCalmar) = −0.78.  The ONLY survivor
  was ecdr#23(10/30) — the SLOWEST signal.  The recommendation from #33 was "need more real data".

  But there is a LOGICAL EXTRAPOLATION to the infinite-slowness limit:

      Fastest signal → most false positives → most carry forgone → worst on real books
      Slowest signal → fewest false positives → least carry forgone → best on real books
      Infinitely slow (= never rebalance) → ZERO false positives → ZERO carry forgone → ???

  This script tests that limit: a portfolio that NEVER rebalances.  The weights DRIFT with
  compound returns.  The question: does natural drift ALSO protect against crises AND earn
  MORE carry in calm — strictly dominating static daily rebalancing?

THE MECHANISM (intuition):
  CALM periods: high-APY sUSDe leg (11%/yr) grows faster than rates (4.6%) and RWA (3.31%).
                Weight drifts UP from 25% → earns MORE carry than fixed-25% portfolio.
                This is the "anti-rebalancing premium": don't sell your winner.

  CRISIS periods: sUSDe takes geometric front-loaded losses across the window (fixture).
                  Day 1: sUSDe weight drops from ~27% to ~24%.
                  Day 2: portfolio now has LESS sUSDe → absorbs less of day-2 loss.
                  Day N: progressively lighter sUSDe exposure throughout the window.
                  COMPARE to daily-rebalanced: buys sUSDe back to 25% EVERY DAY (buying the
                  falling knife) → MORE exposure to days 2-N of the crisis.

  DRIFT IS STRUCTURALLY ANTI-MOMENTUM ON LOSSES: it auto-reduces exposure to a declining book
  without any signal, lookback, threshold, or false-positive cost.

  COST: no active recovery-harvest — sUSDe doesn't jump back to 25% after crisis ends.
        Misses some post-crisis carry (compare to #8 PCCH which overweights sUSDe in recovery).
        This is the main cost.  #8 showed recovery harvest adds ~0.1pp APY.

WHAT IS TESTED:
  A. PURE DRIFT  — never rebalance, compound all three legs independently.
  B. BAND DRIFT  — rebalance only when sUSDe deviates > Δ from target weight.
     Δ = 5%, 10%, 15% (progressively laxer bands).  Interpolates between drift and static.
  C. CALENDAR    — monthly and quarterly rebalancing (bounded comparison).
  D. DAILY       — the static #3 baseline (25/50/25 every day).

  All tested on the fixture 2024-07-01..2026-05-31 (699 days).
  OOS split: train ≤ 2025-06-30, test > 2025-06-30 (same convention as #9/#10/#15).

KEY METRICS (causal, no look-ahead):
  APY, maxDD, Calmar, per-crisis DD, average sUSDe weight (calm vs crisis vs full).

HONEST CAVEATS (up front):
  (a) Fixture losses are geometrically front-loaded (half in day 1, quarter in day 2, ...).
      This IS multi-day and drift IS protective across those days — but real crises can be
      sharper (pure single-event gap) where drift provides zero intra-window protection.
  (b) Pure drift eventually concentrates in the highest-returner.  Over very long periods
      (years), sUSDe weight could reach 40-50%+ (Kelly growth criterion effect).  The
      portfolio would need an eventual hard-reset — not modelled in 699 days.
  (c) No switching costs modelled (drift has zero switches; comparison is fair vs daily-
      rebalanced which also ignores switching costs per registry convention).
  (d) rates-carry and RWA are smooth synthetic (4.6%/3.31% per year, no mark-to-market
      volatility) — same assumption as #3/#4/#7-#33 (apples-to-apples).
  (e) Evidence level: L0 (backtest on synthetic stress fixture).  IS_ADVISORY=True,
      OUTSIDE_RISKPOLICY.  NOT live results.  LLM FORBIDDEN.

Read-only: does not write data/, does not import spa_core.execution, does not touch the
live paper track, RiskPolicy v1.0, the site, or any agent.  stdlib-only, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, STRESS_WINDOWS  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6      # smooth fixed-carry rates desk
RWA_APY_PCT = 3.31       # smooth RWA floor
INITIAL_CAPITAL = 100_000.0
TARGET_SUSDE = 0.25
TARGET_RATES = 0.50
TARGET_RWA = 0.25
TRAIN_END = "2025-06-30"   # OOS split: consistent with #9/#10/#15/#32/#33

_RATES_DAILY = RATES_APY_PCT / 100.0 / 365.0
_RWA_DAILY = RWA_APY_PCT / 100.0 / 365.0


# ── data loading ─────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Tuple[List[str], Dict[str, float]]:
    """Daily fractional returns from susde_dn fixture (backtest phase only)."""
    rows = [
        json.loads(line)
        for line in fx.strategy_jsonl("susde_dn").strip().split("\n")
        if line.strip()
    ]
    bt = [r for r in rows if r.get("phase") == "backtest"]
    dates: List[str] = []
    rets: Dict[str, float] = {}
    for i in range(1, len(bt)):
        d = bt[i]["date"]
        e_prev = bt[i - 1]["equity_usd"]
        e_curr = bt[i]["equity_usd"]
        if e_prev > 0:
            rets[d] = e_curr / e_prev - 1.0
            dates.append(d)
    return dates, rets


# ── portfolio simulation ─────────────────────────────────────────────────────────────────────────

class _PortfolioState:
    """Three-leg portfolio state: sUSDe, rates, RWA."""

    __slots__ = ("v_susde", "v_rates", "v_rwa")

    def __init__(self) -> None:
        self.v_susde = INITIAL_CAPITAL * TARGET_SUSDE
        self.v_rates = INITIAL_CAPITAL * TARGET_RATES
        self.v_rwa = INITIAL_CAPITAL * TARGET_RWA

    @property
    def total(self) -> float:
        return self.v_susde + self.v_rates + self.v_rwa

    @property
    def w_susde(self) -> float:
        t = self.total
        return self.v_susde / t if t > 0 else TARGET_SUSDE

    def step(self, r_s: float, r_r: float, r_w: float) -> None:
        self.v_susde *= 1.0 + r_s
        self.v_rates *= 1.0 + r_r
        self.v_rwa *= 1.0 + r_w

    def rebalance(self) -> None:
        t = self.total
        if t <= 0:
            return
        self.v_susde = t * TARGET_SUSDE
        self.v_rates = t * TARGET_RATES
        self.v_rwa = t * TARGET_RWA


def _simulate(
    dates: List[str],
    r_susde: Dict[str, float],
    *,
    rebalance_every: int = 0,          # 0 = never; 1 = daily; 30 = monthly; 91 = quarterly
    band_threshold: float = 0.0,       # > 0: rebalance when |w_susde − TARGET| > this fraction
    asymmetric: bool = False,          # True: rebalance DOWN only (sell winners, hold losers)
    cap_weight: float = 0.0,           # > 0: hard cap on sUSDe weight (one-sided rebalance)
) -> Tuple[List[float], List[float]]:
    """
    Simulate portfolio.  Returns (equity_series, susde_weight_series).

    Priority: band_threshold > rebalance_every.
    If both zero: pure drift (never rebalance).

    asymmetric=True: ONLY rebalance DOWN (sell sUSDe when it exceeds target) — never buy.
                     This prevents concentration before a crisis but doesn't force-buy in crisis.
    cap_weight > 0: Only rebalance when sUSDe exceeds cap_weight (one-sided hard cap).
    """
    state = _PortfolioState()
    equity: List[float] = []
    weights: List[float] = []
    day_counter = 0

    for d in dates:
        r_s = r_susde.get(d, 0.0)
        state.step(r_s, _RATES_DAILY, _RWA_DAILY)
        equity.append(state.total)
        weights.append(state.w_susde)
        day_counter += 1

        # rebalance decision (AFTER recording today's state)
        w = state.w_susde
        if cap_weight > 0.0:
            # One-sided: cap sUSDe at cap_weight, never force-buy below target
            if w > cap_weight:
                state.rebalance()
        elif asymmetric:
            # Sell winners (sUSDe > target) daily; never buy (sUSDe < target stays low)
            if w > TARGET_SUSDE + 1e-6:
                state.rebalance()
        elif band_threshold > 0.0:
            if abs(w - TARGET_SUSDE) > band_threshold:
                state.rebalance()
        elif rebalance_every > 0 and day_counter % rebalance_every == 0:
            state.rebalance()

    return equity, weights


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Tuple[float, float, Optional[float]]:
    """(apy_pct, max_dd_pct, calmar)."""
    n = len(equity) - 1
    if n < 1 or equity[0] <= 0:
        return 0.0, 0.0, None
    apy = ((equity[-1] / equity[0]) ** (365.0 / n) - 1.0) * 100.0
    peak, max_dd = equity[0], 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    calmar = (apy / (abs(max_dd) * 100.0)) if max_dd < 0 else None
    return apy, abs(max_dd) * 100.0, calmar


def _crisis_dd(dates: List[str], equity: List[float], key: str) -> Optional[float]:
    """Max drawdown from pre-window peak to within-window trough for a named crisis."""
    for w in STRESS_WINDOWS:
        if w["key"] != key:
            continue
        lo, hi = w["date_from"], w["date_to"]
        pre = [equity[i] for i, d in enumerate(dates) if d < lo]
        win = [equity[i] for i, d in enumerate(dates) if lo <= d <= hi]
        if not pre or not win:
            return None
        peak = max(pre)
        trough = min(win)
        return (trough - peak) / peak * 100.0
    return None


def _avg_weight(
    weights: List[float], dates: List[str], period: str = "full"
) -> float:
    """Average sUSDe weight: 'full', 'calm' (not in any crisis window), 'crisis' (in a window)."""
    crisis_dates = set()
    for w in STRESS_WINDOWS:
        for i, d in enumerate(dates):
            if w["date_from"] <= d <= w["date_to"]:
                crisis_dates.add(d)

    if period == "crisis":
        vals = [wt for wt, d in zip(weights, dates) if d in crisis_dates]
    elif period == "calm":
        vals = [wt for wt, d in zip(weights, dates) if d not in crisis_dates]
    else:
        vals = list(weights)

    return sum(vals) / len(vals) * 100.0 if vals else 0.0


# ── main backtest ─────────────────────────────────────────────────────────────────────────────────

def _fmt(apy: float, dd: float, cal: Optional[float]) -> str:
    cal_str = f"{cal:.2f}" if cal is not None else "n/a"
    return f"apy {apy:+.2f}%  maxDD {dd:.2f}%  Calmar {cal_str}"


def main() -> None:
    dates, r_susde = _load_susde_returns()
    total_days = len(dates)
    print(f"Fixture dates: {dates[0]} .. {dates[-1]}  ({total_days} days)\n")

    train_dates = [d for d in dates if d <= TRAIN_END]
    test_dates = [d for d in dates if d > TRAIN_END]
    print(
        f"Train: {train_dates[0]} .. {train_dates[-1]}  ({len(train_dates)}d)\n"
        f"Test:  {test_dates[0]}  .. {test_dates[-1]}  ({len(test_dates)}d)\n"
    )

    # ── define all strategies ────────────────────────────────────────────────────────────────────
    strategies = [
        ("daily (static #3 baseline)", dict(rebalance_every=1,  band_threshold=0.0)),
        ("monthly",                    dict(rebalance_every=30, band_threshold=0.0)),
        ("quarterly",                  dict(rebalance_every=91, band_threshold=0.0)),
        ("annual",                     dict(rebalance_every=365, band_threshold=0.0)),
        ("band ±10pp",                 dict(rebalance_every=0,  band_threshold=0.10)),
        ("pure drift (never)",         dict(rebalance_every=0,  band_threshold=0.0)),
        # ASYMMETRIC VARIANTS — sell winners, hold losers
        ("asym: cap@30% sUSDe",        dict(rebalance_every=0,  cap_weight=0.30)),
        ("asym: cap@27% sUSDe",        dict(rebalance_every=0,  cap_weight=0.27)),
        ("asym: sell>target daily",    dict(rebalance_every=0,  asymmetric=True)),
    ]

    # ── FULL PERIOD ──────────────────────────────────────────────────────────────────────────────
    print("=" * 74)
    print("FULL PERIOD — 2024-07 .. 2026-05  (699 days, fixture, bt)")
    print(f"  Baseline reference: static #3 Calmar ~2.03  DDO #9 Calmar ~3.68")
    print("=" * 74)

    rows_full: List[Tuple] = []
    for label, params in strategies:
        eq, wts = _simulate(dates, r_susde, **params)
        apy, dd, cal = _metrics(eq)
        # count rebalances (weight jumps back to 25%)
        rebalances = sum(
            1 for i in range(1, len(wts))
            if abs(wts[i] - wts[i - 1]) > 0.001
            and abs(wts[i] - TARGET_SUSDE) < 0.001  # snapped back to target
        )
        rows_full.append((label, apy, dd, cal, wts, eq, rebalances))

    header = (
        f"{'strategy':<22}  {'APY':>6}  {'maxDD':>7}  {'Calmar':>7}  "
        f"{'w̄_full':>7}  {'w̄_calm':>7}  {'w̄_crisis':>9}  {'swaps':>5}"
    )
    print(header)
    print("-" * len(header))
    for label, apy, dd, cal, wts, eq, swaps in rows_full:
        cal_s = f"{cal:.2f}" if cal is not None else "  n/a"
        wf = _avg_weight(wts, dates, "full")
        wc = _avg_weight(wts, dates, "calm")
        wr = _avg_weight(wts, dates, "crisis")
        print(
            f"{label:<22}  {apy:>+6.2f}%  {dd:>6.2f}%  {cal_s:>7}  "
            f"{wf:>6.1f}%  {wc:>6.1f}%  {wr:>8.1f}%  {swaps:>5}"
        )

    # ── PER-CRISIS BREAKDOWN ─────────────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("PER-CRISIS DRAWDOWN (from pre-window peak to within-window trough)")
    print("=" * 74)
    crisis_header = f"{'strategy':<22}" + "".join(
        f"  {w['key'][:12]:>12}" for w in STRESS_WINDOWS
    )
    print(crisis_header)
    print("-" * len(crisis_header))
    for label, apy, dd, cal, wts, eq, swaps in rows_full:
        cds = "".join(
            f"  {(_crisis_dd(dates, eq, w['key']) or 0.0):>+11.2f}%"
            for w in STRESS_WINDOWS
        )
        print(f"{label:<22}{cds}")

    # ── OOS SPLIT ────────────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print(f"OUT-OF-SAMPLE — test > {TRAIN_END}  ({len(test_dates)} days)")
    print("  (no parameter choices here — pure drift has no parameters)")
    print("=" * 74)
    print(f"{'strategy':<22}  {'APY':>6}  {'maxDD':>7}  {'Calmar':>7}")
    print("-" * 52)
    for label, params in strategies:
        eq, wts = _simulate(test_dates, r_susde, **params)
        apy, dd, cal = _metrics(eq)
        cal_s = f"{cal:.2f}" if cal is not None else "  n/a"
        print(f"{label:<22}  {apy:>+6.2f}%  {dd:>6.2f}%  {cal_s:>7}")

    # ── WEIGHT EVOLUTION DEEP-DIVE ───────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("DRIFT WEIGHT EVOLUTION — pure drift strategy")
    print("  (sUSDe weight at key dates: shows the natural drift dynamics)")
    print("=" * 74)
    eq_drift, wts_drift = _simulate(dates, r_susde, rebalance_every=0, band_threshold=0.0)
    eq_static, wts_static = _simulate(dates, r_susde, rebalance_every=1)

    key_dates = (
        [dates[0]]
        + [d for w in STRESS_WINDOWS for d in [w["date_from"], w["date_to"]]]
        + [dates[-1]]
    )
    print(f"{'date':<12}  {'drift w_sUSDe':>13}  {'static w_sUSDe':>14}  {'delta':>6}")
    print("-" * 52)
    for kd in key_dates:
        if kd in dates:
            i = dates.index(kd)
            wdrift = wts_drift[i] * 100
            wstatic = wts_static[i] * 100
            print(f"{kd:<12}  {wdrift:>12.1f}%  {wstatic:>13.1f}%  {wdrift-wstatic:>+5.1f}pp")

    # ── MECHANISM VERIFICATION ───────────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("MECHANISM VERIFICATION — does drift accumulate more carry in CALM?")
    print("  Compute sUSDe weight on first day of each crisis (pre-crisis drift)")
    print("=" * 74)
    for w in STRESS_WINDOWS:
        lo = w["date_from"]
        if lo in dates:
            i = dates.index(lo)
            # weight JUST BEFORE the crisis (day i−1)
            pre_i = max(0, i - 1)
            w_pre_drift = wts_drift[pre_i] * 100
            w_pre_static = wts_static[pre_i] * 100
            crisis_hit = r_susde.get(lo, 0.0)
            print(
                f"  {w['key'][:28]:<28}  "
                f"drift pre-crisis w_sUSDe: {w_pre_drift:.1f}%  "
                f"static: {w_pre_static:.1f}%  "
                f"day-1 hit: {crisis_hit*100:+.2f}%"
            )
        else:
            print(f"  {w['key']} — start date not in fixture window")

    # ── HONEST COMPARISON SUMMARY ────────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("HONEST COMPARISON SUMMARY (backtest, evidence L0, NOT live results)")
    print("=" * 74)
    # grab static and pure-drift rows
    static_row = next(r for r in rows_full if "daily" in r[0])
    drift_row = next(r for r in rows_full if "pure drift" in r[0])

    static_apy, static_dd, static_cal, _, static_eq, _ = static_row[1:]
    drift_apy, drift_dd, drift_cal, _, drift_eq, _ = drift_row[1:]

    delta_apy = drift_apy - static_apy
    delta_dd = drift_dd - static_dd  # positive = drift has more DD (worse)
    print(f"  static #3 (daily rebalance):  {_fmt(static_apy, static_dd, static_cal)}")
    print(f"  pure drift (never rebalance): {_fmt(drift_apy,  drift_dd,  drift_cal)}")
    print()
    print(f"  Δ APY:  {delta_apy:+.2f}pp  (drift {'higher' if delta_apy>0 else 'lower'} carry)")
    print(f"  Δ DD:   {delta_dd:+.2f}pp  (drift {'worse' if delta_dd>0 else 'better'} drawdown)")
    if drift_cal is not None and static_cal is not None:
        print(f"  Δ Calmar: {drift_cal - static_cal:+.2f}")
    print()
    print("  Registry context:")
    print("    static #3  Calmar ~2.03  (cross-desk #3 baseline, from registry)")
    print("    DDO #9     Calmar ~3.68  (best reactive signal, from registry)")
    print("    ecdr#23    Calmar ~3.74  (best on real panel, #32)")

    # ── FINDING + CAVEATS ────────────────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("KEY FINDING (honest):")
    if drift_cal is not None and static_cal is not None:
        if drift_cal > static_cal:
            print(
                f"  Pure drift IMPROVES Calmar ({drift_cal:.2f} vs static {static_cal:.2f}, "
                f"Δ={drift_cal - static_cal:+.2f}) by capturing higher carry in calm and "
                f"reducing crisis exposure via natural weight drift."
            )
        else:
            print(
                f"  Pure drift does NOT improve Calmar ({drift_cal:.2f} vs static "
                f"{static_cal:.2f}, Δ={drift_cal - static_cal:+.2f}).  The cost of "
                f"missing post-crisis carry recovery outweighs the FP-free protection."
            )
    print()
    print("  HONEST CAVEATS (always show the tail):")
    print("  (a) Fixture crises are geometrically front-loaded over the window — drift IS")
    print("      protective within the multi-day window.  Real crises can be pure single-day")
    print("      gaps where drift provides zero intra-window protection.")
    print("  (b) Drift eventually concentrates in the highest-returner (Kelly growth).  Over")
    print("      very long horizons, sUSDe weight could dominate.  Needs a floor review.")
    print("  (c) No switching costs (drift = 0 switches vs daily = 365+ switches/year).")
    print("      Real comparison under costs (#10 ~96bp/switch) would favour drift FURTHER.")
    print("  (d) smooth synthetic rates/RWA legs — no mark-to-market volatility on safe legs.")
    print("  (e) Evidence L0 (backtest/synthetic fixture).  IS_ADVISORY.  NOT live results.")
    print("=" * 74)


if __name__ == "__main__":
    main()
