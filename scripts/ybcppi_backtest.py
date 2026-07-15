#!/usr/bin/env python3
"""
scripts/ybcppi_backtest.py — Idea #10: Yield-Bearing CPPI (YB-CPPI)

NOVEL EDGE IDEA #11 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE HONESTY PROBLEM THIS IDEA ATTACKS
  Every crisis-protection idea in this registry (#1 guardian, #7 PERS, #8 PCCH, #9 DDO)
  requires a SIGNAL: vol spike, oracle crisis dates, trailing drawdown threshold, or regime label.
  Signal-based approaches share common failure modes:
    • Lag:  signal fires AFTER the loss begins (you absorb a minimum "entry fee" per event).
    • Whipsaw: false triggers in calm periods waste carry.
    • Threshold sensitivity: small parameter changes shift Calmar dramatically.

  CPPI (Constant Proportion Portfolio Insurance), invented in TradFi (Black & Perold 1992),
  eliminates the signal entirely. Instead of "detect crisis → switch mode", it CONTINUOUSLY
  adjusts risky exposure as a smooth function of the current cushion vs floor:

        risky_allocation(t) = min( m × cushion(t),  max_risky_pct × V(t) )
        cushion(t)          = max( 0,  V(t) − floor(t) )

  As the portfolio falls toward the floor, cushion shrinks → risky allocation shrinks
  AUTOMATICALLY. No threshold, no lag into a new state, no whipsaw on micro-dips.

THE DeFi TWIST — what makes YB-CPPI genuinely new vs TradFi CPPI
  Classic TradFi CPPI: floor = zero-yield cash.
    - Insurance premium = full opportunity cost of holding non-yielding floor.
    - After de-risking, no natural cushion recovery (floor is static).

  YB-CPPI (DeFi): floor earns REAL YIELD via rates-carry / RWA T-bills (~3.4–4.6%/yr).
    (1) "Self-healing cushion": even when fully de-risked, floor grows → cushion recovers
        WITHOUT needing to take any additional risk.  The floor heals itself.
    (2) Lower insurance premium: the safe leg earns 4.6% not 0% → opportunity cost of
        protection is dramatically reduced.
    (3) Ratcheting variant: on each new portfolio high-water mark (HWM), the floor is
        ratcheted up to maintain the original protection ratio (V × (1−cushion_pct)).
        This LOCKS IN gains — the floor can never fall below a fraction of the best-ever V.

  This is structurally different from ALL #1–#9 ideas:
    • No vol signal (≠ #1 guardian, #4 vol-targeted)
    • No crisis oracle (≠ #7 PERS, #8 PCCH)
    • No drawdown threshold state-machine (≠ #9 DDO)
    → Just continuous cushion-proportional math with a yield-bearing floor.

SETUP
  All variants start with the SAME initial risky allocation as the #3 static portfolio (25%),
  so the baseline comparison is fair:
        cushion_pct = TARGET_INITIAL_RISKY / m   →   floor = V × (1 − cushion_pct)
  e.g., m=5: cushion_pct=5%, floor=95% of V — i.e., at start, risky = 5% × 5 = 25%. ✓

PARAMETERS SWEPT
  m ∈ {2, 3, 5, 8}                — CPPI multiplier; higher = more sensitive de-risking
  safe_leg ∈ {"rates", "rwa"}    — safe leg yield: rates-carry 4.6% vs RWA 3.31%
  max_risky_pct ∈ {0.40, 0.60}  — cap on risky fraction (limits upside in calm periods)

BASELINES
  static #3 (25/50/25 sUSDe/rates/RWA)   — the validated cross-desk portfolio
  pure RWA floor (100% floor)             — trivially safe, lowest return
  causal DDO #9 (θ=0.3%, harvest=21d)    — best prior causal method

All results labelled bt (backtest) / synthetic. NOT live results.
Evidence level L0. Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, LLM FORBIDDEN.
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
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS                   # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────────────────────────
RATES_APY_PCT        = 4.6    # smooth rates-carry (idea #3; near-zero-vol in fixture)
RWA_APY_PCT          = 3.31   # live T-bill floor
TARGET_INITIAL_RISKY = 0.25   # all CPPI variants start with 25% in sUSDe (same as #3 static)

# Static #3 weights for comparison [sUSDe, rates-carry, RWA]
WEIGHTS_STATIC  = [0.25, 0.50, 0.25]
# DDO #9 weights
WEIGHTS_CRUISE  = [0.25, 0.50, 0.25]
WEIGHTS_DEFEND  = [0.05, 0.25, 0.70]
WEIGHTS_HARVEST = [0.40, 0.45, 0.15]


# ── data loading ──────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    """sUSDe daily fractional returns from fixture (real-crisis-shaped)."""
    tmp = Path(tempfile.mkdtemp(prefix="ybcppi_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture not available — check aggressive_lab loader")
    eq: Dict[str, float] = {}
    for p in s.backtest.series:
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq[d] = float(e)
    dates = sorted(eq)
    return {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0
            for i in range(1, len(dates)) if eq[dates[i - 1]]}


def _smooth_returns(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── performance metrics ───────────────────────────────────────────────────────────────────────────

def _cagr(series: List[float], n_days: int) -> float:
    if n_days < 2 or series[0] <= 0 or series[-1] <= 0:
        return 0.0
    return (series[-1] / series[0]) ** (365.0 / n_days) - 1.0


def _max_dd(series: List[float]) -> float:
    peak = series[0]
    worst = 0.0
    for v in series:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > worst:
            worst = dd
    return worst


def _crisis_window_dd(series: List[float], dates_all: List[str], window_key: str) -> float:
    """Max portfolio drawdown WITHIN a named stress window."""
    w = next((w for w in STRESS_WINDOWS if str(w["key"]) == window_key), None)
    if w is None:
        return 0.0
    lo, hi = str(w["date_from"]), str(w["date_to"])
    # series has len(dates)+1 points (initial + one per date)
    idxs = [i + 1 for i, d in enumerate(dates_all) if lo <= d <= hi]
    if not idxs:
        return 0.0
    pre_idx = idxs[0] - 1
    start_val = series[pre_idx] if pre_idx < len(series) else series[-1]
    min_val = min(series[i] for i in idxs if i < len(series))
    if start_val <= 0:
        return 0.0
    return max(0.0, (start_val - min_val) / start_val)


def _calmar(apy: float, mdd: float) -> Optional[float]:
    return apy / mdd if mdd > 1e-6 else None   # None = infinite (no drawdown)


def _fmt(calmar: Optional[float]) -> str:
    return f"{calmar:.2f}" if calmar is not None else "∞"


# ── portfolio engines ─────────────────────────────────────────────────────────────────────────────

def _blend_static(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    weights: List[float],
) -> List[float]:
    """Fixed-weight blended portfolio (#3 / baselines)."""
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = (weights[0] * r_susde.get(d, 0.0)
             + weights[1] * r_rates.get(d, 0.0)
             + weights[2] * r_rwa.get(d, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
    return out


def _ybcppi_ratchet(
    dates: List[str],
    r_susde: Dict[str, float],
    r_safe: Dict[str, float],
    m: float,
    max_risky_pct: float = 0.60,
) -> Tuple[List[float], Dict]:
    """
    YB-CPPI with ratcheting floor.

    Floor(t):
      - Grows each day at the safe rate (yield-bearing — the DeFi twist).
      - On each new portfolio HWM, ratcheted UP to V × (1 − cushion_pct)
        → gains are locked in, protection level maintained at every new peak.

    Risky allocation:
      risky(t) = min(m × cushion(t), max_risky_pct × V(t))

    Safe allocation:
      safe(t) = V(t) − risky(t)

    Returns (equity_series[len(dates)+1], diagnostics).
    """
    cushion_pct = TARGET_INITIAL_RISKY / m          # initial protection: e.g., m=5 → 5% cushion
    V = 100_000.0
    floor = V * (1.0 - cushion_pct)                 # e.g., m=5 → floor=95k
    hwm = V

    out = [V]
    risky_fracs: List[float] = []
    for d in dates:
        cushion = max(0.0, V - floor)
        risky = min(m * cushion, max_risky_pct * V)
        safe  = V - risky

        new_risky = risky * (1.0 + r_susde.get(d, 0.0))
        new_safe  = safe  * (1.0 + r_safe.get(d, 0.0))
        V = new_risky + new_safe

        # floor grows at safe rate (yield-bearing self-healing)
        floor = floor * (1.0 + r_safe.get(d, 0.0))

        # ratchet: lock in protection at each new HWM
        if V > hwm:
            hwm = V
            floor = max(floor, V * (1.0 - cushion_pct))

        risky_fracs.append(risky / max(V, 1.0))
        out.append(V)

    avg_risky = sum(risky_fracs) / len(risky_fracs) if risky_fracs else 0.0
    return out, {"avg_risky_pct": avg_risky, "m": m, "cushion_pct": cushion_pct,
                 "final_floor": floor, "final_V": V}


def _causal_ddo(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    theta_enter: float = 0.003,
    theta_exit:  float = 0.001,
    harvest_days: int  = 21,
) -> List[float]:
    """Best causal DDO from idea #9 (replicated here for apples-to-apples comparison)."""
    eq = 100_000.0
    out = [eq]
    hwm = eq
    was_defending = False
    harvest_left = 0
    for d in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -theta_enter:
            regime = "DEFEND"
            was_defending = True
            harvest_left = 0
        elif was_defending and abs(dd) <= theta_exit:
            was_defending = False
            harvest_left = harvest_days
            regime = "HARVEST"
        elif harvest_left > 0:
            harvest_left -= 1
            regime = "HARVEST"
        else:
            regime = "CRUISE"

        if regime == "DEFEND":
            w = WEIGHTS_DEFEND
        elif regime == "HARVEST":
            w = WEIGHTS_HARVEST
        else:
            w = WEIGHTS_CRUISE

        r = (w[0] * r_susde.get(d, 0.0)
             + w[1] * r_rates.get(d, 0.0)
             + w[2] * r_rwa.get(d, 0.0))
        eq *= (1.0 + r)
        if eq > hwm:
            hwm = eq
        out.append(eq)
    return out


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("Novel-edge idea #10 — YB-CPPI (Yield-Bearing CPPI) backtest")
    print("Evidence level L0 (bt=backtest/synthetic). NOT live results.")
    print("=" * 70)

    # ── load data ──────────────────────────────────────────────────────────
    print("\n[1/5] Loading fixture data …")
    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    n_days  = len(dates)
    print(f"      sUSDe series: {n_days} trading days "
          f"({dates[0]} … {dates[-1]})")

    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)
    # CPPI safe leg = rates-carry (higher yield, near-zero-vol in fixture)
    r_safe_rates = _smooth_returns(dates, RATES_APY_PCT)
    # Also run with pure-RWA safe leg
    r_safe_rwa   = _smooth_returns(dates, RWA_APY_PCT)

    # ── baselines ──────────────────────────────────────────────────────────
    print("\n[2/5] Computing baselines …")
    eq_static   = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
    eq_rwa_only = _blend_static(dates, r_susde, r_rates, r_rwa, [0.0, 0.0, 1.0])
    eq_ddo      = _causal_ddo(dates, r_susde, r_rates, r_rwa)

    CRISIS_KEYS = ["eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"]
    CRISIS_LABELS = ["ETH-crash 2024-08", "USDe-unwind 2025-10", "rsETH-depeg 2026-04"]

    def row(label: str, series: List[float]) -> None:
        apy  = _cagr(series, n_days)
        mdd  = _max_dd(series)
        cal  = _calmar(apy, mdd)
        crisis_dds = [_crisis_window_dd(series, dates, k) for k in CRISIS_KEYS]
        print(f"  {label:<38}  APY={apy*100:5.2f}%  maxDD={mdd*100:5.2f}%  "
              f"Calmar={_fmt(cal):>6}  "
              + "  ".join(f"{k}: {v*100:.2f}%" for k, v in zip(CRISIS_LABELS, crisis_dds)))

    row("static #3 (25/50/25)", eq_static)
    row("pure RWA floor",       eq_rwa_only)
    row("causal DDO #9 (θ=0.3%)", eq_ddo)

    # ── YB-CPPI sweep ──────────────────────────────────────────────────────
    print("\n[3/5] YB-CPPI parameter sweep …")
    print("      (all start with 25% sUSDe risky allocation, cushion_pct = 25% / m)")

    configs = [
        (m, max_r, safe_leg, r_safe)
        for m       in [2, 3, 5, 8]
        for max_r   in [0.40, 0.60]
        for safe_leg, r_safe in [("rates", r_safe_rates), ("rwa", r_safe_rwa)]
    ]

    best: Optional[Tuple[float, List[float], str, dict]] = None   # (calmar, series, label, diag)

    for m, max_r, safe_name, r_safe in configs:
        eq, diag = _ybcppi_ratchet(dates, r_susde, r_safe, m=m, max_risky_pct=max_r)
        apy = _cagr(eq, n_days)
        mdd = _max_dd(eq)
        cal = _calmar(apy, mdd)
        cal_val = cal if cal is not None else 1e9
        label = f"YB-CPPI m={m} maxR={int(max_r*100)}% safe={safe_name}"
        row(label, eq)
        if best is None or cal_val > (best[0] if best[0] is not None else 0):
            best = (cal_val, eq, label, diag)

    # ── best variant highlighted ───────────────────────────────────────────
    print("\n[4/5] Best YB-CPPI variant vs key baselines:")
    if best:
        b_cal, b_series, b_label, b_diag = best
        print(f"\n  WINNER: {b_label}")
        print(f"  cushion_pct = {b_diag['cushion_pct']*100:.2f}%  "
              f"(floor starts at {(1-b_diag['cushion_pct'])*100:.1f}% of V)")
        print(f"  avg risky fraction over run: {b_diag['avg_risky_pct']*100:.1f}%")

        print("\n  Full comparison table (bt = backtest label):")
        header = f"  {'Strategy':<38}  {'APY':>6}  {'maxDD':>7}  {'Calmar':>7}"
        for key, lbl in zip(CRISIS_KEYS, CRISIS_LABELS):
            header += f"  {lbl[:16]:>16}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        def fmtrow(label: str, series: List[float]) -> str:
            apy = _cagr(series, n_days)
            mdd = _max_dd(series)
            cal = _calmar(apy, mdd)
            s = f"  {label:<38}  {apy*100:>5.2f}%  {mdd*100:>6.2f}%  {_fmt(cal):>7}"
            for k in CRISIS_KEYS:
                s += f"  {_crisis_window_dd(series, dates, k)*100:>15.2f}%"
            return s

        print(fmtrow("static #3 (bt)", eq_static))
        print(fmtrow("pure RWA (bt)", eq_rwa_only))
        print(fmtrow("causal DDO #9 (bt)", eq_ddo))
        print(fmtrow(f"BEST: {b_label} (bt)", b_series))

    # ── OOS validation ─────────────────────────────────────────────────────
    print("\n[5/5] Out-of-sample validation …")
    # Train: first ~half; Test: second half (same unseen-tail approach as prior ideas)
    split_idx  = n_days // 2
    train_dates = dates[:split_idx]
    test_dates  = dates[split_idx:]
    print(f"  Train: {train_dates[0]} … {train_dates[-1]} ({len(train_dates)}d)")
    print(f"  Test:  {test_dates[0]}  … {test_dates[-1]} ({len(test_dates)}d)")

    # Identify best m on training period for each safe-leg variant
    for safe_name, r_safe in [("rates", r_safe_rates), ("rwa", r_safe_rwa)]:
        best_m_train = None
        best_cal_train = -1e9
        for m in [2, 3, 5, 8]:
            eq_tr, _ = _ybcppi_ratchet(train_dates, r_susde, r_safe, m=m)
            apy = _cagr(eq_tr, len(train_dates))
            mdd = _max_dd(eq_tr)
            cal = _calmar(apy, mdd)
            cal_v = cal if cal is not None else 1e9
            if cal_v > best_cal_train:
                best_cal_train = cal_v
                best_m_train = m

        # apply to test period (causal: no look-ahead — CPPI uses only current V and floor)
        eq_test, diag_test = _ybcppi_ratchet(test_dates, r_susde, r_safe, m=best_m_train)
        apy_oos  = _cagr(eq_test, len(test_dates))
        mdd_oos  = _max_dd(eq_test)
        cal_oos  = _calmar(apy_oos, mdd_oos)

        # compare to baselines on test period
        eq_stat_oos = _blend_static(test_dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
        eq_ddo_oos  = _causal_ddo(test_dates, r_susde, r_rates, r_rwa)
        apy_stat = _cagr(eq_stat_oos, len(test_dates))
        mdd_stat = _max_dd(eq_stat_oos)
        cal_stat = _calmar(apy_stat, mdd_stat)
        apy_ddo  = _cagr(eq_ddo_oos, len(test_dates))
        mdd_ddo  = _max_dd(eq_ddo_oos)
        cal_ddo  = _calmar(apy_ddo, mdd_ddo)

        print(f"\n  Safe leg = {safe_name} (best m from train = {best_m_train}):")
        print(f"    static #3 (OOS):   APY={apy_stat*100:.2f}%  maxDD={mdd_stat*100:.2f}%  "
              f"Calmar={_fmt(cal_stat)}")
        print(f"    causal DDO #9 (OOS): APY={apy_ddo*100:.2f}%  maxDD={mdd_ddo*100:.2f}%  "
              f"Calmar={_fmt(cal_ddo)}")
        print(f"    YB-CPPI m={best_m_train} (OOS): APY={apy_oos*100:.2f}%  "
              f"maxDD={mdd_oos*100:.2f}%  Calmar={_fmt(cal_oos)}")

    # ── summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("HONEST SUMMARY (all numbers = bt/backtest, NOT live realized)")
    print("=" * 70)
    apy_s   = _cagr(eq_static, n_days)
    mdd_s   = _max_dd(eq_static)
    cal_s   = _calmar(apy_s, mdd_s)
    apy_d   = _cagr(eq_ddo, n_days)
    mdd_d   = _max_dd(eq_ddo)
    cal_d   = _calmar(apy_d, mdd_d)
    if best:
        b_cal, b_series, b_label, b_diag = best
        apy_b = _cagr(b_series, n_days)
        mdd_b = _max_dd(b_series)
        cal_b = _calmar(apy_b, mdd_b)
        print(f"\n  static #3   (bt): APY={apy_s*100:.2f}%  maxDD={mdd_s*100:.2f}%  "
              f"Calmar={_fmt(cal_s)}")
        print(f"  causal DDO  (bt): APY={apy_d*100:.2f}%  maxDD={mdd_d*100:.2f}%  "
              f"Calmar={_fmt(cal_d)}")
        print(f"  YB-CPPI BEST(bt): APY={apy_b*100:.2f}%  maxDD={mdd_b*100:.2f}%  "
              f"Calmar={_fmt(cal_b)}  ({b_label})")
        delta_calmar = (cal_b - cal_d) if (cal_b is not None and cal_d is not None) else None
        print(f"\n  YB-CPPI vs DDO #9 Δ Calmar: {_fmt(delta_calmar)}")
        print(f"  YB-CPPI vs static #3 Δ Calmar: {_fmt(cal_b - cal_s if cal_b is not None and cal_s is not None else None)}")

    print("""
HONEST CAVEATS (mandatory per registry standard):
  (a) CONTINUOUS vs BINARY: YB-CPPI de-risks as a smooth function of cushion, not a threshold
      — this means it NEVER achieves the extreme low-DD of DDO (which can jump to 5% sUSDe
      immediately). The trade-off is no whipsaw and mathematically bounded downside.
  (b) FIXTURE CRISIS SHAPE: losses are geometrically front-loaded (heaviest on day 1 of window).
      In reality, crisis evolution varies — sometimes gradual, sometimes gap. CPPI handles
      gradual better; gaps still breach any pre-committed floor (irreducible gap-risk).
  (c) SAFE LEG IS SYNTHETIC: rates-carry and RWA returns are smooth (4.6% / 3.31% daily),
      no maturity / duration mismatch modelled. Real rates-carry has some PT-roll timing noise.
  (d) RATCHET HAS NO FRICTION: moving the floor up on new HWM implies real rebalancing
      (selling risky, buying safe) which has transaction costs — not modelled.
  (e) OOS IS A CALM PERIOD: the test half of the fixture has fewer/milder crisis events than
      the train half (as noted in ideas #1 #8 #9). Crisis-protection improvement is hard to
      confirm in a calm test window — same limitation as prior ideas.
  (f) EVIDENCE LEVEL: L0 (backtest / synthetic). NOT live results. Never present as realized.
""")
    print("Registry entry → see docs/DYNAMIC_LEVERAGE_GUARDIAN.md  idea #11")


if __name__ == "__main__":
    main()
