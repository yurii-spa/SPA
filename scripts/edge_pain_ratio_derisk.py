#!/usr/bin/env python3
"""
scripts/edge_pain_ratio_derisk.py — Idea #29: Pain-Ratio De-Risk (PRD)

NOVEL EDGE IDEA #29 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)
IS_ADVISORY = True  ·  does NOT touch execution, live paper track, or RiskPolicy v1.0
stdlib-only, deterministic, LLM FORBIDDEN.

═══════════════════════════════════════════════════════════════════════════════════════
THE UNTESTED ANGLE
═══════════════════════════════════════════════════════════════════════════════════════
  All 28 prior ideas use SYMMETRIC metrics for de-risk signals:
    A. μ LEVEL    — KODS #15: fire when rolling_mean < r_f (symmetric: mean treats up/down equally)
    B. σ² / σ    — KODS denominator / #4 vol-targeting (squares BOTH sides)
    C. NAV DEPTH — DDO #9: depth from HWM (symmetric absolute distance)
    D. NAV TREND — ECDR #23: EMA/SMA ratio (symmetric averages)
    E. AGE       — DACRS #25: continuous days below HWM (symmetric in count)
    F. SLOPE     — CSD #28: dμ/dt — FIRST derivative of mean (still symmetric)

  Idea #29 introduces the first ASYMMETRIC signal: the PAIN RATIO (PR) —
  the fraction of total absolute return magnitude that comes from NEGATIVE days:

        PR(t) = |mean(neg_rets)| / ( mean(pos_rets) + |mean(neg_rets)| + ε )

  • PR = 0   → only positive return days in the window → full exposure (CRUISE)
  • PR = 0.5 → gain magnitude ≈ pain magnitude → equally balanced, signal to reduce
  • PR → 1   → dominated by losses → strong de-risk

  Position sizing (continuous, no discrete DEFEND/CRUISE states):
        w_susde(t) = max_risky × max(0, 1 − PR(t) / PR_threshold)

  Where PR_threshold calibrates "tolerable level of pain" (above this → zero weight).

═══════════════════════════════════════════════════════════════════════════════════════
WHY THIS IS STRUCTURALLY DIFFERENT FROM KODS (#15)
═══════════════════════════════════════════════════════════════════════════════════════
  Critical scenario where PRD ≠ KODS:

      10-day window: 8 positive days (+0.01%/day) + 2 negative days (−0.005%/day)
        μ_rolling = (8×0.01 − 2×0.005) / 10 = +0.007%/day  → POSITIVE → KODS CRUISE
        PR = 0.005 / (0.010 + 0.005) = 0.333             → PRD de-risks partially!

  PRD detects the PRESENCE of negative days even when the overall mean is positive.
  This models the pre-crash scenario where:
    • Peg is slowly eroding (occasional small negative days) before a full depeg
    • Funding rates are intermittently negative before a full unwind
    • Carry is compressed (some days below cost) while mean still positive

  KODS can only detect once cumulative losses push the mean negative.
  PRD starts detecting as soon as negative days APPEAR in the window.

═══════════════════════════════════════════════════════════════════════════════════════
COMPARISON WITH CSD #28 (previous slope-based idea)
═══════════════════════════════════════════════════════════════════════════════════════
  CSD #28 tested whether dμ/dt could detect gradual carry compression.
  Honest result: CSD FAILED in compression because ΔμROLLING is 40× below threshold.
  PRD takes a different approach:
    • CSD looks at HOW FAST the mean is changing (derivative → resolves poorly when gradual)
    • PRD looks at WHAT FRACTION of days are negative (distribution shape → resolves well)

  In gradual compression (carry 8% → 3% over 60 days):
    • Around day 20 (carry 5%), some days will have loss > drift → first negative-return days
    • PRD fires as soon as those negative days appear (fraction > threshold)
    • CSD didn't fire because the derivative was too small

NEW STRESS SCENARIO: PRE-CRASH MILD DETERIORATION
  Injects 5 mild negative days (−0.1%/day) BEFORE each crisis window.
  Simulates: peg erosion / funding flip pre-signal before full unwind.
  Tests: does PRD partially de-risk before the main crash (KODS can't)?

PARAMETERS SWEPT
  lkb           ∈ {5, 10, 20}      rolling window
  PR_threshold  ∈ {0.15, 0.25, 0.40}  pain fraction at which weight → 0

BASELINES
  static #3   (25/50/25 always):     Calmar ~2.03
  causal DDO #9 (threshold 5%/HWM):  Calmar ~3.68
  KODS #15    (Kelly μ/σ², lkb=10):  Calmar ~4.55

SAFE-LEG SPLIT (identical to prior ideas, preserving #3 structure)
  remaining_weight = 1 − w_susde
  w_rates = remaining_weight × 2/3
  w_rwa   = remaining_weight × 1/3

EVIDENCE LEVEL
  L0 (backtest / synthetic fixture + new pre-crash scenario). NOT live results.
  Labelled "bt" throughout. IS_ADVISORY = True.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld   # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS                  # noqa: E402

# ─── constants ───────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT   = 3.31
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0
RWA_DAILY     = RWA_APY_PCT   / 100.0 / 365.0
BASE_SUSDE    = 0.25
MAX_RISKY     = 0.25
MIN_VAR       = 1e-10    # for KODS baseline denominator
ALPHA_KELLY   = 0.1      # for KODS baseline
CALDAYS       = 365.0

# ─── data loading ─────────────────────────────────────────────────────────────
def _load_susde_returns() -> Tuple[List[str], List[float]]:
    """sUSDe daily fractional returns from fixture (real-crisis-shaped)."""
    tmp = Path(tempfile.mkdtemp(prefix="prd_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture unavailable")
    series = s.backtest.series  # list of {'date': str, 'equity_usd': float}
    dates_str = [p["date"] for p in series]
    eqs = [p["equity_usd"] for p in series]
    rets = [0.0] + [(eqs[i] - eqs[i-1]) / eqs[i-1] for i in range(1, len(eqs))]
    return dates_str, rets


# ─── stress window helpers ────────────────────────────────────────────────────
def _date_in_stress_window(d: str) -> bool:
    """True if date string falls inside any STRESS_WINDOW."""
    dt = datetime.date.fromisoformat(d)
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= dt <= hi:
            return True
    return False


def _crisis_label(d: str) -> Optional[str]:
    """Return the stress window key the date falls in, or None."""
    dt = datetime.date.fromisoformat(d)
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= dt <= hi:
            return str(w["key"])
    return None


# ─── Pain Ratio ───────────────────────────────────────────────────────────────
def _pain_ratio(rets: List[float], t: int, lkb: int) -> float:
    """
    Causal Pain Ratio at index t over the past lkb returns.
    PR = |mean(neg_rets)| / (mean(pos_rets) + |mean(neg_rets)| + ε)
    Uses rets[max(0, t-lkb)..t-1] — strictly causal (no rets[t]).
    Returns 0.0 if no data or no negative returns in window.
    """
    eps = 1e-12
    window = rets[max(0, t - lkb): t]  # causal: index t is today, not included
    if not window:
        return 0.0
    pos_vals = [r for r in window if r > 0.0]
    neg_vals = [r for r in window if r < 0.0]
    gain = sum(pos_vals) / len(pos_vals) if pos_vals else 0.0
    pain = abs(sum(neg_vals) / len(neg_vals)) if neg_vals else 0.0
    return pain / (gain + pain + eps)


# ─── KODS baseline ───────────────────────────────────────────────────────────
def _kods_weight(rets: List[float], t: int, lkb: int) -> float:
    """
    Kelly Optimal De-Risk Sizing — KODS #15 (lkb=10, α=0.1).
    f*(t) = α × max(0, (μ(t) − r_f) / max(σ²(t), MIN_VAR))
    Causal: window rets[t-lkb:t] (excludes rets[t]).
    """
    window = rets[max(0, t - lkb): t]
    if len(window) < 2:
        return MAX_RISKY
    mu = sum(window) / len(window)
    var = sum((r - mu) ** 2 for r in window) / len(window)
    f_star = ALPHA_KELLY * max(0.0, (mu - RATES_DAILY) / max(var, MIN_VAR))
    return min(MAX_RISKY, f_star)


# ─── portfolio simulation ─────────────────────────────────────────────────────
def _run_portfolio(
    dates: List[str],
    rets: List[float],
    lkb: int,
    pr_threshold: float,
    use_kods: bool = False,
) -> Tuple[List[float], List[float]]:
    """
    Simulate cross-desk portfolio NAV.
    sUSDe risky leg weight determined by PRD (or KODS if use_kods).
    Remaining weight split rates(2/3) + RWA(1/3) per #3 structure.
    Returns (equity_series, susde_weights).
    """
    eq = 1.0
    equity_series: List[float] = []
    weight_series: List[float] = []
    for i, (d, r_susde) in enumerate(zip(dates, rets)):
        # compute weight using yesterday's signal (causal)
        if use_kods:
            w_susde = _kods_weight(rets, i, lkb)
        else:
            pr = _pain_ratio(rets, i, lkb)
            w_susde = MAX_RISKY * max(0.0, 1.0 - pr / pr_threshold)
        w_rem = 1.0 - w_susde
        w_rates = w_rem * (2.0 / 3.0)
        w_rwa   = w_rem * (1.0 / 3.0)

        r_port = w_susde * r_susde + w_rates * RATES_DAILY + w_rwa * RWA_DAILY
        eq *= (1.0 + r_port)
        equity_series.append(eq)
        weight_series.append(w_susde)
    return equity_series, weight_series


def _run_static(dates: List[str], rets: List[float]) -> List[float]:
    """Static #3 baseline: fixed 25/50/25."""
    eq = 1.0
    equities = []
    for r_susde in rets:
        r_port = 0.25 * r_susde + 0.50 * RATES_DAILY + 0.25 * RWA_DAILY
        eq *= (1.0 + r_port)
        equities.append(eq)
    return equities


# ─── metrics ─────────────────────────────────────────────────────────────────
def _metrics(equity: List[float]) -> Tuple[float, float, float]:
    """Returns (annualised APY, max_drawdown, Calmar)."""
    n = len(equity)
    total_ret = equity[-1] - 1.0
    apy = ((equity[-1]) ** (CALDAYS / n) - 1.0) * 100.0 if n > 0 else 0.0
    # max drawdown from high-water-mark
    peak = 1.0
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd
    calmar = apy / (mdd * 100.0) if mdd > 1e-9 else float("inf")
    return apy, mdd * 100.0, calmar


def _per_crisis_dd(equity: List[float], dates: List[str]) -> Dict[str, float]:
    """Maximum drawdown within each stress window."""
    result: Dict[str, float] = {}
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        idx = [i for i, d in enumerate(dates)
               if lo <= datetime.date.fromisoformat(d) <= hi]
        if not idx:
            result[key] = 0.0
            continue
        pre = equity[idx[0] - 1] if idx[0] > 0 else 1.0
        peak = pre
        worst = 0.0
        for i in idx:
            if equity[i] > peak:
                peak = equity[i]
            dd = (peak - equity[i]) / peak
            if dd > worst:
                worst = dd
        result[key] = worst * 100.0
    return result


# ─── Part 1: main fixture backtest ────────────────────────────────────────────
def part1_main_fixture() -> None:
    print("\n" + "═" * 70)
    print("PART 1 — Main Fixture Backtest (699 days, 2024-07..2026-05)")
    print("═" * 70)
    dates, rets = _load_susde_returns()

    # baselines
    static_eq = _run_static(dates, rets)
    s_apy, s_dd, s_cal = _metrics(static_eq)
    print(f"\nBaseline static #3 (25/50/25): APY={s_apy:.2f}% / maxDD={s_dd:.2f}% / Calmar={s_cal:.2f}")

    kods10_eq, _ = _run_portfolio(dates, rets, lkb=10, pr_threshold=0.0, use_kods=True)
    k_apy, k_dd, k_cal = _metrics(kods10_eq)
    print(f"Baseline KODS #15 (lkb=10):   APY={k_apy:.2f}% / maxDD={k_dd:.2f}% / Calmar={k_cal:.2f}")

    print("\nPRD parameter sweep (lkb × PR_threshold):")
    print(f"{'lkb':>5} {'PR_thresh':>12} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    print("-" * 45)
    best_cal = -1.0
    best_params: Optional[Tuple] = None
    best_eq: Optional[List[float]] = None

    for lkb in [5, 10, 20]:
        for prt in [0.15, 0.25, 0.40]:
            eq, wts = _run_portfolio(dates, rets, lkb=lkb, pr_threshold=prt)
            apy, dd, cal = _metrics(eq)
            marker = " ◄ best" if cal > best_cal else ""
            print(f"{lkb:>5} {prt:>12.2f} {apy:>8.2f} {dd:>8.2f} {cal:>8.2f}{marker}")
            if cal > best_cal:
                best_cal = cal
                best_params = (lkb, prt)
                best_eq = eq

    if best_eq is None or best_params is None:
        print("ERROR: no valid results")
        return

    best_lkb, best_prt = best_params
    print(f"\nBest PRD config: lkb={best_lkb}, PR_threshold={best_prt:.2f}")

    # per-crisis breakdown: best PRD vs KODS vs static
    print("\nPer-crisis max-drawdown breakdown (best PRD vs KODS #15 vs static #3):")
    print(f"{'crisis':30} {'static DD%':>12} {'KODS DD%':>10} {'PRD DD%':>10} {'saved vs static':>16}")
    prd_crisis = _per_crisis_dd(best_eq, dates)
    kods_crisis = _per_crisis_dd(kods10_eq, dates)
    static_crisis = _per_crisis_dd(static_eq, dates)
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        label = key[:28]
        sdd = static_crisis.get(key, 0.0)
        kdd = kods_crisis.get(key, 0.0)
        pdd = prd_crisis.get(key, 0.0)
        saved = sdd - pdd
        print(f"  {label:30} {sdd:>12.2f}% {kdd:>10.2f}% {pdd:>10.2f}% {saved:>+15.2f}pp")


def part1_oos_test() -> None:
    """OOS: fit best PRD lkb on train (70%), apply to test (30%), compare vs KODS."""
    print("\n" + "─" * 60)
    print("OOS VALIDATION (70/30 split, unseen test period)")
    print("─" * 60)
    dates, rets = _load_susde_returns()
    n = len(dates)
    split = int(n * 0.70)
    train_d, train_r = dates[:split], rets[:split]
    test_d, test_r   = dates[split:], rets[split:]

    # pick best lkb on TRAIN
    train_best_cal = -1.0
    train_best_params = (10, 0.25)
    for lkb in [5, 10, 20]:
        for prt in [0.15, 0.25, 0.40]:
            eq, _ = _run_portfolio(train_d, train_r, lkb=lkb, pr_threshold=prt)
            _, _, cal = _metrics(eq)
            if cal > train_best_cal:
                train_best_cal = cal
                train_best_params = (lkb, prt)

    best_lkb, best_prt = train_best_params
    print(f"Best from train: lkb={best_lkb}, PR_threshold={best_prt:.2f}  (Calmar={train_best_cal:.2f})")

    # apply to test (unseen)
    prd_eq, _ = _run_portfolio(test_d, test_r, lkb=best_lkb, pr_threshold=best_prt)
    kods_eq, _ = _run_portfolio(test_d, test_r, lkb=10, pr_threshold=0.0, use_kods=True)
    static_eq   = _run_static(test_d, test_r)

    p_apy, p_dd, p_cal = _metrics(prd_eq)
    k_apy, k_dd, k_cal = _metrics(kods_eq)
    s_apy, s_dd, s_cal = _metrics(static_eq)

    print(f"\nOOS results ({n - split} days, unseen data):")
    print(f"  static #3:       APY={s_apy:.2f}%  maxDD={s_dd:.2f}%  Calmar={s_cal:.2f}")
    print(f"  KODS #15 (lkb=10): APY={k_apy:.2f}%  maxDD={k_dd:.2f}%  Calmar={k_cal:.2f}")
    print(f"  PRD (best lkb/prt): APY={p_apy:.2f}%  maxDD={p_dd:.2f}%  Calmar={p_cal:.2f}")
    print(f"  Δ PRD vs KODS OOS: {p_cal - k_cal:+.2f} Calmar")


# ─── Part 2: pre-crash mild deterioration scenario ────────────────────────────
def part2_precrash_scenario() -> None:
    """
    NEW STRESS SCENARIO: 5 mild negative days BEFORE each crisis window.
    Tests whether PRD partial de-risks before main crash (KODS cannot).
    Models: peg eroding (-0.1%/day), funding going slightly negative pre-event.
    """
    print("\n" + "═" * 70)
    print("PART 2 — Pre-Crash Mild Deterioration Scenario")
    print("  Injects −0.1%/day for 5 days before each stress window.")
    print("  Simulates: peg erosion / funding-flip pre-signal before full unwind.")
    print("═" * 70)

    dates, rets = _load_susde_returns()
    n = len(dates)

    # Build date → stress window map for pre-crash injection
    window_starts: Dict[str, datetime.date] = {}
    for w in STRESS_WINDOWS:
        window_starts[str(w["key"])] = datetime.date.fromisoformat(str(w["date_from"]))

    PRE_CRASH_DAYS = 5
    PRE_CRASH_RET  = -0.001  # −0.1%/day

    # Inject mild pre-crash negative returns
    rets_modified = list(rets)
    for i, d_str in enumerate(dates):
        dt = datetime.date.fromisoformat(d_str)
        for key, start in window_starts.items():
            delta = (start - dt).days
            if 0 < delta <= PRE_CRASH_DAYS:
                # this date is in the [1, PRE_CRASH_DAYS] window before crisis
                rets_modified[i] = PRE_CRASH_RET
                break  # don't double-inject

    print(f"\n  Injected {PRE_CRASH_DAYS} pre-crash days at {PRE_CRASH_RET*100:.1f}%/day before each window.")
    print("  (Original returns unchanged during and after crisis windows.)\n")

    # Run all three methods on modified returns
    static_eq      = _run_static(dates, rets_modified)
    kods_eq, _     = _run_portfolio(dates, rets_modified, lkb=10, pr_threshold=0.0, use_kods=True)
    prd_eq_5, _    = _run_portfolio(dates, rets_modified, lkb=5,  pr_threshold=0.25)
    prd_eq_10, _   = _run_portfolio(dates, rets_modified, lkb=10, pr_threshold=0.25)

    s_apy, s_dd, s_cal   = _metrics(static_eq)
    k_apy, k_dd, k_cal   = _metrics(kods_eq)
    p5_apy, p5_dd, p5_cal = _metrics(prd_eq_5)
    p10_apy, p10_dd, p10_cal = _metrics(prd_eq_10)

    print("Results on pre-crash-modified series:")
    print(f"  static #3:       APY={s_apy:.2f}%  maxDD={s_dd:.2f}%  Calmar={s_cal:.2f}")
    print(f"  KODS #15 (lkb=10): APY={k_apy:.2f}%  maxDD={k_dd:.2f}%  Calmar={k_cal:.2f}")
    print(f"  PRD lkb=5/prt=0.25:  APY={p5_apy:.2f}%  maxDD={p5_dd:.2f}%  Calmar={p5_cal:.2f}")
    print(f"  PRD lkb=10/prt=0.25: APY={p10_apy:.2f}%  maxDD={p10_dd:.2f}%  Calmar={p10_cal:.2f}")

    print("\nPer-crisis breakdown (PRD lkb=5 vs KODS vs static on MODIFIED series):")
    print(f"  {'crisis':28} {'static':>10} {'KODS':>10} {'PRD-5':>10}")
    for w_crisis in STRESS_WINDOWS:
        key = str(w_crisis["key"])
        sdd  = _per_crisis_dd(static_eq, dates).get(key, 0.0)
        kdd  = _per_crisis_dd(kods_eq, dates).get(key, 0.0)
        pdd5 = _per_crisis_dd(prd_eq_5, dates).get(key, 0.0)
        print(f"  {key[:28]:28} {sdd:>9.2f}% {kdd:>9.2f}% {pdd5:>9.2f}%")

    print("\nPRE-CRISIS WINDOW (5 days before each crisis):")
    print("  Examining whether PRD partially de-risked BEFORE the main crash.")
    print(f"  {'crisis':28}  {'pre_start':>12}  {'PRD-5 avg w_susde':>18}  {'KODS avg w_susde':>18}")
    for w_crisis in STRESS_WINDOWS:
        key = str(w_crisis["key"])
        crisis_start = datetime.date.fromisoformat(str(w_crisis["date_from"]))
        pre_start = crisis_start - datetime.timedelta(days=PRE_CRASH_DAYS)
        # gather weights in pre-crash window
        prd_pre_ws, kods_pre_ws = [], []
        # re-run to extract weights
        _, prd5_wts  = _run_portfolio(dates, rets_modified, lkb=5,  pr_threshold=0.25)
        _, kods_wts  = _run_portfolio(dates, rets_modified, lkb=10, pr_threshold=0.0, use_kods=True)
        for i, d_str in enumerate(dates):
            dt = datetime.date.fromisoformat(d_str)
            if pre_start <= dt < crisis_start:
                prd_pre_ws.append(prd5_wts[i])
                kods_pre_ws.append(kods_wts[i])
        avg_prd5 = sum(prd_pre_ws) / len(prd_pre_ws) if prd_pre_ws else 0.0
        avg_kods = sum(kods_pre_ws) / len(kods_pre_ws) if kods_pre_ws else 0.0
        print(f"  {key[:28]:28}  {pre_start!s:>12}  {avg_prd5:>18.4f}  {avg_kods:>18.4f}")
    print("\n  (max_risky = 0.25; lower avg weight = more pre-crisis defense)")


# ─── Part 3: signal analysis ──────────────────────────────────────────────────
def part3_signal_analysis() -> None:
    """Show Pain Ratio signal around crisis windows vs KODS signal."""
    print("\n" + "═" * 70)
    print("PART 3 — Signal Analysis: PR(t) vs KODS Kelly-fraction around crises")
    print("═" * 70)
    dates, rets = _load_susde_returns()

    for w in STRESS_WINDOWS:
        key = str(w["key"])
        crisis_start = datetime.date.fromisoformat(str(w["date_from"]))
        print(f"\n  {key} [{w['date_from']} .. {w['date_to']}]:")
        print(f"  {'date':>12} {'susde_ret%':>12} {'PR(lkb=10)':>12} {'KODS_w':>10} {'PRD_w(prt=.25)':>15}")
        for i, d_str in enumerate(dates):
            dt = datetime.date.fromisoformat(d_str)
            delta = (dt - crisis_start).days
            if -3 <= delta <= 10:
                pr  = _pain_ratio(rets, i, lkb=10)
                kw  = _kods_weight(rets, i, lkb=10)
                prd_w = MAX_RISKY * max(0.0, 1.0 - pr / 0.25)
                print(f"  {d_str:>12} {rets[i]*100:>12.4f} {pr:>12.6f} {kw:>10.4f} {prd_w:>15.4f}")


# ─── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 70)
    print("IDEA #29: Pain-Ratio De-Risk (PRD)")
    print("  Asymmetric gain/pain distribution signal for de-risk.")
    print("  IS_ADVISORY=True  LLM_FORBIDDEN  stdlib-only  L0 evidence.")
    print("=" * 70)

    part1_main_fixture()
    part1_oos_test()
    part2_precrash_scenario()
    part3_signal_analysis()

    print("\n" + "═" * 70)
    print("SUMMARY (see docs/DYNAMIC_LEVERAGE_GUARDIAN.md for registry entry)")
    print("  Compare PRD (best config) vs KODS #15 baseline:")
    print("  Main fixture: run part1 above for Calmar comparison.")
    print("  Pre-crash scenario: run part2 above for onset-detection comparison.")
    print("  Evidence level: L0 (backtest/synthetic). NOT live results.")
    print("  IS_ADVISORY=True. Does NOT touch execution or RiskPolicy v1.0.")
    print("=" * 70)


if __name__ == "__main__":
    main()
