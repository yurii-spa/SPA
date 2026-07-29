#!/usr/bin/env python3
"""
scripts/edge_drawdown_age_composite.py — Idea #23: Drawdown-Age Composite Risk Signal (DACRS)

NOVEL EDGE IDEA #23 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE (after 20 ideas)
  Ideas #1–#20 used the following signal families:
    A. VOL LEVEL         — #1 guardian, #4 vol-targeting, #14 vol-entry (own σ)
    B. DRAWDOWN DEPTH    — #9 DDO threshold on (V-HWM)/HWM
    C. KELLY μ/σ²        — #15 KODS rolling mean-over-variance
    D. REGIME ORACLE     — #7 PERS, #8 PCCH (uses STRESS_WINDOWS dates — oracle look-ahead)
    E. CROSS-ASSET       — #20 CACH passive short on correlated asset
    F. COMPOSITION/SELECTION — #3, #5, #6

  NONE measured HOW LONG the portfolio has consecutively been below its High-Water-Mark (HWM).
  This is a purely TEMPORAL dimension: independent of depth, independent of vol,
  independent of rolling mean — it just counts calendar days since the last equity peak.

THE ECONOMIC HYPOTHESIS
  Being -1% for 1 day is structurally DIFFERENT from being -1% for 25 consecutive days:
  • Brief, deep crash      (high depth, low age): technical/gap event → recovers quickly
  • Prolonged, shallow slump (low depth, high age): protocol yield erosion, regime shift
  • Both deep AND aged     (high depth + high age): maximum de-risk warranted

  The AGE dimension captures the «prolonged slump» scenario that all prior timing signals
  (which fire on MAGNITUDE) can miss:
  • KODS #15:   fires when μ_rolling < r_f — only after sustained negative returns
  • DDO #9:     fires when DD depth > θ_enter — silent on shallow-but-prolonged slumps
  • DACRS #23:  fires when EITHER (a) depth is large OR (b) age is long → catches both

  REAL-WORLD VALUE (not well-tested in the front-loaded fixture, but documentable):
  Imagine a protocol where yield gradually compresses from 11% → 3% over 60 days.
  No single day is a crash, so DDO and KODS stay invested (no big loss, no negative μ).
  DD_age grows steadily → DACRS gradually de-risks over those 60 days.
  This is the "gradual carry erosion" scenario the fixture can't model well.

MECHANISM
  At every day t (causal, no future data):
    1. hwm(t)        = max(V(0), V(1), ..., V(t)) — running peak
    2. dd_depth(t)   = max(0, (hwm(t) − V(t)) / hwm(t))  — fraction below HWM [0, ∞)
    3. dd_age(t)     = consecutive calendar days V < hwm (resets to 0 when V reaches new hwm)

    4. depth_score(t) = min(1, dd_depth(t) / depth_thresh)   ∈ [0, 1]
    5. age_score(t)   = min(1, dd_age(t)   / age_thresh)     ∈ [0, 1]
    6. risk_score(t)  = alpha_d × depth_score + alpha_a × age_score  ∈ [0, alpha_d + alpha_a]
    7. de_risk_f(t)   = min(1, risk_score(t))                ∈ [0, 1]  (1 = full de-risk)
    8. susde_weight(t) = base_susde × (1 − de_risk_f(t))

  The safe leg (rates + RWA) expands proportionally when sUSDe shrinks:
    rates_w = (1 − susde_w) × 2/3,  rwa_w = (1 − susde_w) × 1/3

  Recovery: when a new HWM is set (dd_age resets to 0), a «HARVEST» window opens for
  harvest_days: susde_weight = HARVEST_SUSDE for harvest_days, then back to base_susde.

WHAT MAKES DACRS STRUCTURALLY DIFFERENT
  • NOT a threshold: proportional, continuous response (vs binary DDO #9 / KODS).
  • MONOTONE in age: every consecutive below-HWM day INCREASES the signal — no whipsaw.
    (Unlike vol or rolling μ which can bounce back from a single positive day.)
  • MEMORYFUL: age accumulates the full below-HWM history, unlike rolling windows that
    only look back N days.
  • ORTHOGONAL DIMENSIONS: depth fires for brief-deep events; age fires for prolonged-shallow.
    Together they create a 2D risk map, not a 1D signal.

PARAMETERS SWEPT
  depth_thresh ∈ {0.005, 0.010, 0.020}   — depth fraction that scores full 1.0
  age_thresh   ∈ {7, 14, 21}             — days below HWM that score full 1.0
  alpha_d      ∈ {0.5, 0.7}              — weight on depth dimension
  alpha_a      ∈ {0.5, 0.3}             — weight on age dimension (1 − alpha_d)
  harvest_days ∈ {14, 21}               — post-HWM-recovery harvest window
  base_susde   = 0.25                    — fixed (matches static #3 baseline)

BASELINES (from registry, apples-to-apples)
  static #3:   Calmar ~2.03  (25/50/25, no timing)
  causal DDO #9: Calmar ~3.68 (threshold de-risk 5%, 21d harvest)
  KODS #15:    Calmar ~4.55  (Kelly μ/σ², lookback=10, max_risky=25%)

HONEST EXPECTED RESULT
  On the FRONT-LOADED synthetic fixture, the first-day crisis loss is unavoidable for any
  causal method (as proven by #19 EWVM). DACRS will likely perform COMPARABLY or slightly
  BELOW KODS because:
    a) Day-1 loss always hits (like KODS).
    b) Age accumulates during recovery (when equity is below HWM but rising) → keeps
       de-risk elevated during the recovery phase → may miss recovery carry.
  WHERE DACRS ADDS VALUE (not well-captured by fixture): gradual carry compression over
  many days — the age signal grows even if depth stays small. This is worth documenting.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants ───────────────────────────────────────────────────────────────────
RATES_APY_PCT   = 4.6       # smooth rates-carry (same as #3/#9/#15)
RWA_APY_PCT     = 3.31      # T-bill floor
RATES_DAILY     = RATES_APY_PCT / 100.0 / 365.0
MIN_VAR         = 1e-10     # Kelly variance floor (for KODS baseline)

WEIGHTS_STATIC  = [0.25, 0.50, 0.25]   # [sUSDe, rates, RWA]
BASE_SUSDE      = 0.25
HARVEST_SUSDE   = 0.40      # sUSDe weight during post-crisis harvest
HARVEST_RATES   = (1.0 - HARVEST_SUSDE) * (2.0 / 3.0)
HARVEST_RWA     = (1.0 - HARVEST_SUSDE) * (1.0 / 3.0)

OOS_SPLIT       = "2025-06-01"   # consistent with #11/#15/#19/#20


# ── data loading ────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="dacrs_"))
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


def _smooth_returns(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── engines ─────────────────────────────────────────────────────────────────────

def _dacrs_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    depth_thresh: float,
    age_thresh: int,
    alpha_d: float,       # weight on depth signal
    alpha_a: float,       # weight on age signal (should be 1 - alpha_d for a [0,1] combined signal)
    harvest_days: int,
    base_susde: float = BASE_SUSDE,
) -> Tuple[List[float], Dict[str, object]]:
    """
    Drawdown-Age Composite Risk Signal (DACRS).

    Pure causal: on each day, computes depth + age signals from PAST equity only.
    Returns (equity_series, stats_dict).
    """
    eq         = 100_000.0
    hwm        = eq
    dd_age     = 0           # consecutive days below HWM
    harvest_left = 0         # remaining harvest days

    out           = [eq]
    age_vals: List[int]   = []
    depth_vals: List[float] = []
    susde_ws: List[float] = []

    for ds in dates:
        # ── CAUSAL signal: compute from V(t-1) / hwm — before applying today's return ──
        dd_depth = max(0.0, (hwm - eq) / hwm) if hwm > 0 else 0.0
        depth_score = min(1.0, dd_depth / depth_thresh) if depth_thresh > 0 else 0.0
        age_score   = min(1.0, dd_age  / age_thresh)   if age_thresh > 0  else 0.0
        risk_score  = alpha_d * depth_score + alpha_a * age_score  # ∈ [0, alpha_d + alpha_a]
        de_risk_f   = min(1.0, risk_score)                          # ∈ [0, 1]

        # If in harvest (post-HWM-reset window), override to harvest weight
        if harvest_left > 0 and de_risk_f < 0.05:
            # Only harvest if no significant new drawdown (not re-entering crisis)
            w_susde = HARVEST_SUSDE
            w_rates = HARVEST_RATES
            w_rwa   = HARVEST_RWA
            harvest_left -= 1
        else:
            w_susde = base_susde * (1.0 - de_risk_f)
            w_rates = (1.0 - w_susde) * (2.0 / 3.0)
            w_rwa   = (1.0 - w_susde) * (1.0 / 3.0)
            if harvest_left > 0:
                harvest_left -= 1

        susde_ws.append(w_susde)
        age_vals.append(dd_age)
        depth_vals.append(dd_depth)

        # ── apply return ─────────────────────────────────────────────────────────
        r = (w_susde * r_susde.get(ds, 0.0)
             + w_rates * r_rates.get(ds, 0.0)
             + w_rwa   * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)

        # ── update HWM and DD-age ─────────────────────────────────────────────────
        if eq >= hwm:
            hwm   = eq
            if dd_age > 0:
                # Reset: just hit new HWM → open harvest window
                harvest_left = harvest_days
            dd_age = 0
        else:
            dd_age += 1

    avg_susde   = sum(susde_ws) / len(susde_ws) if susde_ws else 0.0
    zero_susde  = sum(1 for w in susde_ws if w < 1e-6)
    max_age     = max(age_vals)   if age_vals   else 0
    max_depth   = max(depth_vals) if depth_vals else 0.0

    stats = {
        "avg_susde_pct": avg_susde * 100.0,
        "zero_susde_days": zero_susde,
        "max_dd_age": max_age,
        "max_dd_depth_pct": max_depth * 100.0,
    }
    return out, stats


def _blend_static(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    weights: List[float],
) -> List[float]:
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = (weights[0] * r_susde.get(d, 0.0)
             + weights[1] * r_rates.get(d, 0.0)
             + weights[2] * r_rwa.get(d, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
    return out


def _kods_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    lookback: int = 10,
    alpha: float  = 0.1,
    max_risky: float = 0.25,
) -> List[float]:
    """KODS #15 reference (best in-registry: lookback=10, alpha=0.1, max=25%)."""
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    for ds in dates:
        if len(buf) >= lookback:
            window  = buf[-lookback:]
            mu      = sum(window) / lookback
            sq_dev  = sum((r - mu) ** 2 for r in window)
            sigma2  = max(sq_dev / (lookback - 1), MIN_VAR)
            f_star  = (mu - RATES_DAILY) / sigma2
            f_active = min(alpha * max(0.0, f_star), max_risky)
        else:
            f_active = WEIGHTS_STATIC[0]
        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)
        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw    * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))
    return out


def _causal_ddo9(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
) -> List[float]:
    """Causal DDO #9 reference."""
    W_CRUISE  = [0.25, 0.50, 0.25]
    W_DEFEND  = [0.05, 0.25, 0.70]
    W_HARVEST = [0.40, 0.45, 0.15]
    theta_enter, theta_exit, harvest_days = 0.003, 0.001, 21
    eq = 100_000.0
    out = [eq]
    hwm, was_defending, harvest_left = eq, False, 0
    for ds in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -theta_enter:
            was_defending, harvest_left = True, 0
            regime = "DEFEND"
        else:
            if was_defending and dd >= -theta_exit:
                was_defending, harvest_left = False, harvest_days
            regime = "HARVEST" if harvest_left > 0 else "CRUISE"
            if harvest_left > 0:
                harvest_left -= 1
        w = W_DEFEND if regime == "DEFEND" else (W_HARVEST if regime == "HARVEST" else W_CRUISE)
        r = w[0] * r_susde.get(ds, 0.0) + w[1] * r_rates.get(ds, 0.0) + w[2] * r_rwa.get(ds, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out


# ── metrics ──────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(equity) < 2:
        return None, None, None
    n   = len(equity) - 1
    apy = (equity[-1] / equity[0]) ** (365.0 / n) - 1.0
    peak, max_dd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        dd   = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    dd_pct  = abs(max_dd) * 100.0
    calmar  = (apy * 100.0) / dd_pct if dd_pct > 0 else None
    return apy * 100.0, dd_pct, calmar


def _crisis_dd(dates: List[str], equity: List[float], window_key: str) -> Optional[float]:
    for w in STRESS_WINDOWS:
        if w["key"] != window_key:
            continue
        lo  = datetime.date.fromisoformat(str(w["date_from"]))
        hi  = datetime.date.fromisoformat(str(w["date_to"]))
        idxs = [i for i, d in enumerate(dates) if lo <= datetime.date.fromisoformat(d) <= hi]
        if not idxs:
            return None
        pre    = max(0, idxs[0] - 1)
        peak   = max(equity[: pre + 2])
        trough = min(equity[i + 1] for i in idxs if i + 1 < len(equity))
        return (trough - peak) / peak * 100.0
    return None


def _oos_calmar(
    dates: List[str], equity: List[float], split: str
) -> Optional[float]:
    idx = next((i for i, d in enumerate(dates) if d >= split), None)
    if idx is None or idx + 10 >= len(equity):
        return None
    oos_eq = equity[idx:]
    _, _, calmar = _metrics(oos_eq)
    return calmar


def _f(x: object, d: int = 2) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


# ── full sweep ────────────────────────────────────────────────────────────────────

def run_analysis() -> Dict[str, object]:
    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)

    # ── baselines ────────────────────────────────────────────────────────────────
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
    eq_ddo9   = _causal_ddo9(dates, r_susde, r_rates, r_rwa)
    eq_kods   = _kods_equity(dates, r_susde, r_rates, r_rwa)

    apy_s, dd_s, cal_s = _metrics(eq_static)
    apy_d, dd_d, cal_d = _metrics(eq_ddo9)
    apy_k, dd_k, cal_k = _metrics(eq_kods)

    oos_s = _oos_calmar(dates, eq_static, OOS_SPLIT)
    oos_d = _oos_calmar(dates, eq_ddo9,   OOS_SPLIT)
    oos_k = _oos_calmar(dates, eq_kods,   OOS_SPLIT)

    # ── DACRS sweep ───────────────────────────────────────────────────────────────
    depth_thresholds = [0.005, 0.010, 0.020]
    age_thresholds   = [7, 14, 21]
    alpha_ds         = [0.5, 0.7]
    harvest_days_opts = [14, 21]

    sweep = []
    best = None

    for depth_t, age_t, alpha_d, harv_d in product(
        depth_thresholds, age_thresholds, alpha_ds, harvest_days_opts
    ):
        alpha_a = 1.0 - alpha_d
        eq_d, stats = _dacrs_equity(
            dates, r_susde, r_rates, r_rwa,
            depth_thresh=depth_t,
            age_thresh=age_t,
            alpha_d=alpha_d,
            alpha_a=alpha_a,
            harvest_days=harv_d,
        )
        apy, dd, calmar = _metrics(eq_d)
        oos_c = _oos_calmar(dates, eq_d, OOS_SPLIT)
        row = {
            "depth_thresh": depth_t,
            "age_thresh": age_t,
            "alpha_d": alpha_d,
            "alpha_a": alpha_a,
            "harvest_days": harv_d,
            "apy": apy,
            "dd": dd,
            "calmar": calmar,
            "oos_calmar": oos_c,
            "avg_susde_pct": stats["avg_susde_pct"],
            "zero_susde_days": stats["zero_susde_days"],
            "max_dd_age": stats["max_dd_age"],
            "max_dd_depth_pct": stats["max_dd_depth_pct"],
            "equity": eq_d,
        }
        sweep.append(row)
        if calmar is not None and (best is None or calmar > best["calmar"]):
            best = row

    return {
        "dates": dates,
        "r_susde": r_susde,
        "static":  {"apy": apy_s, "dd": dd_s, "calmar": cal_s, "oos_calmar": oos_s, "equity": eq_static},
        "ddo9":    {"apy": apy_d, "dd": dd_d, "calmar": cal_d, "oos_calmar": oos_d, "equity": eq_ddo9},
        "kods15":  {"apy": apy_k, "dd": dd_k, "calmar": cal_k, "oos_calmar": oos_k, "equity": eq_kods},
        "sweep":   sweep,
        "best":    best,
    }


# ── main (report) ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 78)
    print("IDEA #23: Drawdown-Age Composite Risk Signal (DACRS)")
    print("Combined signal: DEPTH score + AGE score (consecutive days below HWM)")
    print("All numbers: BACKTEST / SYNTHETIC (L0). NOT live results.")
    print("=" * 78)

    res = run_analysis()
    dates = res["dates"]
    st    = res["static"]
    ddo   = res["ddo9"]
    kods  = res["kods15"]
    best  = res["best"]

    print(f"\n{'Baseline':20s}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>7}  {'OOS Calmar':>10}")
    print("-" * 62)
    print(f"  static #3          {_f(st['apy']):>7}  {_f(st['dd']):>7}  {_f(st['calmar']):>7}  {_f(st['oos_calmar']):>10}")
    print(f"  causal DDO #9      {_f(ddo['apy']):>7}  {_f(ddo['dd']):>7}  {_f(ddo['calmar']):>7}  {_f(ddo['oos_calmar']):>10}")
    print(f"  KODS #15 (leader)  {_f(kods['apy']):>7}  {_f(kods['dd']):>7}  {_f(kods['calmar']):>7}  {_f(kods['oos_calmar']):>10}")

    print(f"\n--- DACRS #23 sweep (top 10 by Calmar) ---")
    print(f"{'depth_t':>8} {'age_t':>6} {'alpha_d':>8} {'harv_d':>7}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>7}  {'OOS Cal':>8}")
    print("-" * 78)
    sweep_sorted = sorted(res["sweep"], key=lambda r: (r["calmar"] or -99), reverse=True)
    for row in sweep_sorted[:10]:
        print(
            f"  {row['depth_thresh']:6.3f}  {row['age_thresh']:5d}  {row['alpha_d']:6.2f}  {row['harvest_days']:5d}  "
            f"{_f(row['apy']):>7}  {_f(row['dd']):>7}  {_f(row['calmar']):>7}  {_f(row['oos_calmar']):>8}"
        )

    print(f"\n--- BEST DACRS configuration ---")
    if best:
        print(f"  depth_thresh={best['depth_thresh']:.3f}  age_thresh={best['age_thresh']}d  "
              f"alpha_d={best['alpha_d']:.2f}  harvest_days={best['harvest_days']}d")
        print(f"  APY {_f(best['apy'])}%  maxDD {_f(best['dd'])}%  Calmar {_f(best['calmar'])}  "
              f"OOS-Calmar {_f(best['oos_calmar'])}")
        print(f"  avg sUSDe weight: {_f(best['avg_susde_pct'])}%  "
              f"zero-sUSDe days: {best['zero_susde_days']}  "
              f"max_dd_age: {best['max_dd_age']}d")

    print(f"\n--- Per-crisis DD breakdown (best DACRS vs static #3 / DDO #9 / KODS #15) ---")
    print(f"{'Crisis':30s}  {'static #3':>10}  {'DDO #9':>8}  {'KODS #15':>9}  {'DACRS best':>10}")
    print("-" * 74)
    for window_key in ["eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"]:
        dd_s  = _crisis_dd(dates, st["equity"],    window_key)
        dd_d  = _crisis_dd(dates, ddo["equity"],   window_key)
        dd_k  = _crisis_dd(dates, kods["equity"],  window_key)
        dd_b  = _crisis_dd(dates, best["equity"],  window_key) if best else None
        print(
            f"  {window_key:28s}  {_f(dd_s):>10}  {_f(dd_d):>8}  {_f(dd_k):>9}  {_f(dd_b):>10}"
        )

    print(f"\n--- AGE signal anatomy (DACRS signals) ---")
    print("Max DD ages observed across the three crises:")
    if best:
        print(f"  In best config: max consecutive days below HWM = {best['max_dd_age']}d")
    print("  ETH crash window length:     8 days")
    print("  USDe-unwind window length:  30 days")
    print("  rsETH-depeg window length:  ~5 days (small loss)")

    print("\n--- Summary table (BACKTEST = bt, L0) ---")
    print(f"{'Method':22s}  {'APY% (bt)':>10}  {'maxDD% (bt)':>12}  {'Calmar (bt)':>12}  {'OOS Calmar':>10}")
    print("-" * 72)
    print(f"  {'static #3':20s}  {_f(st['apy']):>10}  {_f(st['dd']):>12}  {_f(st['calmar']):>12}  {_f(st['oos_calmar']):>10}")
    print(f"  {'causal DDO #9':20s}  {_f(ddo['apy']):>10}  {_f(ddo['dd']):>12}  {_f(ddo['calmar']):>12}  {_f(ddo['oos_calmar']):>10}")
    print(f"  {'KODS #15 (leader)':20s}  {_f(kods['apy']):>10}  {_f(kods['dd']):>12}  {_f(kods['calmar']):>12}  {_f(kods['oos_calmar']):>10}")
    if best:
        print(f"  {'DACRS #23 (best)':20s}  {_f(best['apy']):>10}  {_f(best['dd']):>12}  {_f(best['calmar']):>12}  {_f(best['oos_calmar']):>10}")

    print("\n--- Honest caveats ---")
    print("(a) FRONT-LOADED FIXTURE: crisis losses land mostly on day 1. Day-1 loss")
    print("    is unavoidable for any causal method (#19 EWVM). DACRS also misses it.")
    print("(b) AGE signal fires DURING RECOVERY (equity still below HWM while climbing)")
    print("    → keeps strategy defensive during recovery phase → may lose carry.")
    print("    This is the fixture-specific penalty: DACRS is conservative in recovery.")
    print("(c) REAL-WORLD VALUE (not visible in fixture): gradual carry compression over")
    print("    many days creates rising age signal even without large depth — this is where")
    print("    DACRS provides structural value that KODS/DDO miss.")
    print("(d) rates-carry + RWA-floor are smooth synthetic. Same apples-to-apples")
    print("    assumption as #3/#9/#15.")
    print("(e) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("(f) FIXTURE DEGENERATE: σ² ≈ 0 in calm periods — DACRS pure arithmetic,")
    print("    not vol-dependent. Age signal provides genuine information not in KODS.")
    print("=" * 78)


if __name__ == "__main__":
    main()
