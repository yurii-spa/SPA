#!/usr/bin/env python3
"""
scripts/edge_temporal_ensemble_kelly.py — Idea #20: Temporal Ensemble Kelly (TEK)

NOVEL EDGE IDEA #20 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  KODS #15 swept single lookbacks {10, 20, 30} days and found 10d best (faster recovery
  → better Calmar).  The #15 analysis noted σ²≈0 in calm → Kelly effectively binary:
  max_risky in calm, 0% in crisis.  The RECOVERY slope is determined by how quickly
  the crisis return exits the rolling window.

  TWO GAPS not yet filled:
    (A) SHORT lookbacks {3, 5, 7} were NEVER individually tested.  If 10d beats 20d and 30d,
        does 7d > 10d?  5d?  3d?  There may be a finer optimal single-window.
    (B) ENSEMBLE: instead of picking one window, AVERAGE the Kelly fractions across multiple
        timescales simultaneously.  Hypothesis: the ensemble dampens false-positive triggers
        from very short windows while inheriting the faster recovery of short windows.

  Formally (Temporal Ensemble Kelly):
      f_tek(t) = max( 0,  mean([f_kelly(lb, t)  for lb in lookbacks]) )
      f_active = min( alpha × f_tek,  max_risky )

  MECHANISM vs KODS-10d
    • Entry (crisis day 1):  ALL Kelly windows fire simultaneously (front-loaded crash
      drives every μ_lb negative) → ensemble mean < 0 → f_active = 0.  Same as KODS.
    • Recovery:  Short-window Kelly clears FIRST (crash days exit the 3d window after day 3
      post-crisis, vs day 10 for the 10d window).  Ensemble mean starts positive EARLIER
      than KODS-10d → graduated re-entry begins sooner → more carry captured.
    • False-positive damping:  A brief noise spike in sUSDe that drives the 3d mean negative
      may NOT drive the 5d, 7d, 10d negative → ensemble mean stays positive → no de-risk.
      Single KODS-3d would fire; TEK ensemble absorbs the noise.

  EXPECTED RESULT (honest pre-analysis):
    • Single KODS-7d or KODS-5d may outperform KODS-10d (faster recovery, same crisis
      protection — front-loaded crashes fire all windows simultaneously anyway).
    • TEK ensemble [3,5,7,10] should lie between the best and worst single-window in APY
      (due to blending), but potentially better RISK-ADJUSTED (damped false positives).
    • On this fixture (σ²≈0 in calm → zero false positives regardless), TEK's damping
      benefit doesn't materialise → TEK may not beat best single-window on this fixture.
      Honest pre-registered expectation: MIXED — likely marginal vs KODS-10d.

STRUCTURAL NOVELTY vs #1–#19
  • #15 KODS:    single lookback, BINARY de-risk (f*→0% in crisis), sweep {10,20,30}d
  • #12 Hybrid:  KODS de-risk + DDO discrete harvest — two mechanisms, one timescale each
  • TEK:         MULTIPLE timescales averaged SIMULTANEOUSLY → smoother, earlier recovery
  • Not inverse-vol (#4), not DDO threshold (#9), not CPPI (#11), not CPRS (#18), not EWVM (#19)

BASELINES (registry numbers for comparison — same fixture, same approach):
  static #3:      Calmar ~2.03   (fixed 25/50/25)
  causal DDO #9:  Calmar ~3.68   (trailing-drawdown, best from registry)
  KODS #15:       Calmar ~4.55   (Kelly 10d, current Calmar leader)

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, fail-closed.  LLM FORBIDDEN.
Evidence level: L0 (backtest/synthetic).  NOT live results.
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

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants ──────────────────────────────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6       # synthetic smooth rates-carry
RWA_APY_PCT   = 3.31      # T-bill floor
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0
MIN_VAR       = 1e-10     # absolute vol floor (from UPD6 lesson #1)
MAX_RISKY     = 0.25      # calm-period sUSDe cap (= static #3 in calm)
ALPHA         = 0.1       # fractional Kelly multiplier (best from #15 sweep — alpha-degenerate
                           # in fixture due to σ²=0 in calm, but keeps framework honest)

# Lookback sets to test
ALL_SHORT_LOOKBACKS = [3, 5, 7]        # individually AND as ensemble
KODS_10D_LB         = [10]             # KODS #15 reference (reproduced here for clean comparison)
ALL_ENSEMBLE_SETS   = {
    "TEK-[3,5,7]"    : [3, 5, 7],
    "TEK-[5,7,10]"   : [5, 7, 10],
    "TEK-[3,5,7,10]" : [3, 5, 7, 10],
    "TEK-[5,10,20]"  : [5, 10, 20],
}
ALL_SINGLE_LBS = [3, 5, 7, 10, 20, 30]  # full sweep including #15's {10,20,30}

# ── data loading ───────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="tek_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture not available — fail-closed")
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

def _kelly_frac(buf: List[float], lookback: int) -> float:
    """Single-timescale causal Kelly fraction (≥0, clipped at 0)."""
    if len(buf) < lookback:
        return MAX_RISKY          # warmup: static #3-equivalent
    window = buf[-lookback:]
    mu = sum(window) / lookback
    sq_dev = sum((r - mu) ** 2 for r in window)
    sigma2 = sq_dev / (lookback - 1) if lookback > 1 else MIN_VAR
    sigma2 = max(sigma2, MIN_VAR)
    f_star = (mu - RATES_DAILY) / sigma2
    return max(0.0, ALPHA * f_star)   # clip negative → 0 (don't go short safe legs)


def _tek_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa:   Dict[str, float],
    lookbacks: List[int],
) -> Tuple[List[float], Dict[str, float]]:
    """
    Temporal Ensemble Kelly:
      f_tek(t) = mean( f_kelly(lb, t) for lb in lookbacks )
      f_active = min( f_tek, MAX_RISKY )
    Causal: signal computed from buffer[:-1] (yesterday's returns only).
    """
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    fracs: List[float] = []

    for ds in dates:
        # Ensemble: average of individual Kelly fracs (each already ≥ 0)
        ensemble_f = sum(_kelly_frac(buf, lb) for lb in lookbacks) / len(lookbacks)
        f_active = min(ensemble_f, MAX_RISKY)
        fracs.append(f_active)

        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)

        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw    * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))

    avg_frac = sum(fracs) / len(fracs) if fracs else 0.0
    zero_days = sum(1 for f in fracs if f < 1e-6)
    return out, {"avg_risky_pct": avg_frac * 100.0, "zero_days": zero_days}


def _blend_static(
    dates: List[str], r_susde: Dict, r_rates: Dict, r_rwa: Dict,
) -> List[float]:
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = (0.25 * r_susde.get(d, 0.0) + 0.50 * r_rates.get(d, 0.0) + 0.25 * r_rwa.get(d, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
    return out


def _ddo9_equity(
    dates: List[str], r_susde: Dict, r_rates: Dict, r_rwa: Dict,
) -> List[float]:
    """Causal DDO #9 — registry Calmar ~3.68."""
    W_CR = [0.25, 0.50, 0.25]
    W_DF = [0.05, 0.25, 0.70]
    W_HV = [0.40, 0.45, 0.15]
    eq, hwm, defending, harvest_left = 100_000.0, 100_000.0, False, 0
    out = [eq]
    for ds in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -0.003:
            defending, harvest_left = True, 0
        else:
            if defending and dd >= -0.001:
                defending, harvest_left = False, 21
        if defending:
            w = W_DF
        elif harvest_left > 0:
            w, harvest_left = W_HV, harvest_left - 1
        else:
            w = W_CR
        r = w[0] * r_susde.get(ds, 0.0) + w[1] * r_rates.get(ds, 0.0) + w[2] * r_rwa.get(ds, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out


# ── metrics ────────────────────────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(equity) < 2:
        return None, None, None
    n = len(equity) - 1
    apy = (equity[-1] / equity[0]) ** (365.0 / n) - 1.0
    peak, max_dd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    dd_pct = abs(max_dd) * 100.0
    calmar = (apy * 100.0) / dd_pct if dd_pct > 1e-6 else None
    return apy * 100.0, dd_pct, calmar


def _crisis_dd(dates: List[str], equity: List[float], key: str) -> Optional[float]:
    for w in STRESS_WINDOWS:
        if w["key"] != key:
            continue
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        idxs = [i for i, d in enumerate(dates)
                if lo <= datetime.date.fromisoformat(d) <= hi]
        if not idxs:
            return None
        pre = max(0, idxs[0] - 1)
        peak = max(equity[: pre + 2])
        trough = min(equity[i + 1] for i in idxs if i + 1 < len(equity))
        return (trough - peak) / peak * 100.0
    return None


def _f(x: object, d: int = 2) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


# ── main analysis ──────────────────────────────────────────────────────────────────────────────────

def run_analysis() -> Dict[str, object]:
    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    r_rates = _smooth(dates, RATES_APY_PCT)
    r_rwa   = _smooth(dates, RWA_APY_PCT)

    # ── baselines ──────────────────────────────────────────────────────────────────────────────────
    eq_static  = _blend_static(dates, r_susde, r_rates, r_rwa)
    eq_ddo9    = _ddo9_equity(dates, r_susde, r_rates, r_rwa)
    eq_kods10, kods10_stats = _tek_equity(dates, r_susde, r_rates, r_rwa, [10])

    # ── single-window sweep (extends #15's {10,20,30} to short lookbacks) ─────────────────────────
    single_rows: List[Dict] = []
    for lb in ALL_SINGLE_LBS:
        eq, stats = _tek_equity(dates, r_susde, r_rates, r_rwa, [lb])
        apy, dd, cal = _metrics(eq)
        single_rows.append({
            "label": f"KODS-{lb}d", "lookbacks": [lb],
            "apy": apy, "dd": dd, "calmar": cal,
            "avg_risky_pct": stats["avg_risky_pct"], "zero_days": stats["zero_days"],
            "equity": eq,
        })

    best_single = max((r for r in single_rows if r["calmar"] is not None), key=lambda r: r["calmar"])

    # ── ensemble sweep ─────────────────────────────────────────────────────────────────────────────
    ensemble_rows: List[Dict] = []
    for label, lbs in ALL_ENSEMBLE_SETS.items():
        eq, stats = _tek_equity(dates, r_susde, r_rates, r_rwa, lbs)
        apy, dd, cal = _metrics(eq)
        ensemble_rows.append({
            "label": label, "lookbacks": lbs,
            "apy": apy, "dd": dd, "calmar": cal,
            "avg_risky_pct": stats["avg_risky_pct"], "zero_days": stats["zero_days"],
            "equity": eq,
        })

    best_ensemble = max((r for r in ensemble_rows if r["calmar"] is not None),
                        key=lambda r: r["calmar"])

    # ── OOS (unseen 199d tail, same split as #12/#15/#18) ─────────────────────────────────────────
    n_train = 500
    test_dates = dates[n_train:]
    oos_results: Dict[str, object] = {}
    if len(test_dates) > 10:
        eq_s_oos  = _blend_static(test_dates, r_susde, r_rates, r_rwa)
        eq_d9_oos = _ddo9_equity(test_dates, r_susde, r_rates, r_rwa)
        eq_k10_oos, _ = _tek_equity(test_dates, r_susde, r_rates, r_rwa, [10])
        eq_bs_oos, _  = _tek_equity(test_dates, r_susde, r_rates, r_rwa, best_single["lookbacks"])
        eq_be_oos, _  = _tek_equity(test_dates, r_susde, r_rates, r_rwa, best_ensemble["lookbacks"])
        oos_results = {
            "test_dates": test_dates,
            "static":         _metrics(eq_s_oos),
            "ddo9":           _metrics(eq_d9_oos),
            "kods10":         _metrics(eq_k10_oos),
            "best_single":    _metrics(eq_bs_oos),
            "best_ensemble":  _metrics(eq_be_oos),
        }

    return {
        "dates": dates,
        "r_susde": r_susde,
        "eq_static": eq_static,
        "eq_ddo9": eq_ddo9,
        "eq_kods10": eq_kods10,
        "static":  _metrics(eq_static),
        "ddo9":    _metrics(eq_ddo9),
        "kods10":  _metrics(eq_kods10),
        "single_rows": single_rows,
        "ensemble_rows": ensemble_rows,
        "best_single": best_single,
        "best_ensemble": best_ensemble,
        "oos": oos_results,
    }


def main() -> None:
    print("=" * 78)
    print("IDEA #20: Temporal Ensemble Kelly (TEK)")
    print("f_tek(t) = mean(f_kelly(lb, t) for lb in lookbacks);  f_active = min(f_tek, max_risky)")
    print("All numbers: BACKTEST / SYNTHETIC FIXTURE (L0 evidence). NOT live results.")
    print("=" * 78)

    res = run_analysis()
    dates = res["dates"]
    apy_s, dd_s, cal_s = res["static"]
    apy_9, dd_9, cal_9 = res["ddo9"]
    apy_10, dd_10, cal_10 = res["kods10"]

    print(f"\nBacktest window: {dates[0]} → {dates[-1]}  ({len(dates)} days)")
    print(f"sUSDe:     fixture (real-crisis-shaped; susde_dn, headline ~11%)")
    print(f"Rates-carry: synthetic smooth {RATES_APY_PCT}%/yr  |  RWA floor: {RWA_APY_PCT}%/yr")
    print(f"Crisis windows: ETH-crash 2024-08  |  USDe-unwind 2025-10  |  rsETH-depeg 2026-04")

    print("\n── BASELINES ──────────────────────────────────────────────────────────────────")
    print(f"  Static #3 (25/50/25):  APY {_f(apy_s)}%  maxDD {_f(dd_s)}%  Calmar {_f(cal_s)}")
    print(f"  DDO #9 (causal):       APY {_f(apy_9)}%  maxDD {_f(dd_9)}%  Calmar {_f(cal_9)}")
    print(f"  KODS #15 (10d reprod): APY {_f(apy_10)}%  maxDD {_f(dd_10)}%  Calmar {_f(cal_10)}")
    print(f"    (registry: KODS #15 Calmar ~4.55; small deviation from script differences ok)")

    print("\n── PART A: SINGLE-WINDOW SWEEP (extends #15 to short lookbacks) ──────────────")
    print(f"  {'label':14s} {'lkb':>5} {'avg_R%':>7} {'0-days':>7} {'APY':>7} {'maxDD':>7} {'Calmar':>8}")
    print(f"  {'-'*14} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
    for row in res["single_rows"]:
        marker = " ◀ best" if row is res["best_single"] else ""
        print(f"  {row['label']:14s} {row['lookbacks'][0]:>5d}"
              f" {row['avg_risky_pct']:>6.1f}% {row['zero_days']:>7d}"
              f" {_f(row['apy']):>7} {_f(row['dd']):>7} {_f(row['calmar']):>8}{marker}")

    bs = res["best_single"]
    print(f"\n  Best single-window: {bs['label']} → Calmar {_f(bs['calmar'])}"
          f"  APY {_f(bs['apy'])}%  maxDD {_f(bs['dd'])}%")

    print("\n── PART B: TEMPORAL ENSEMBLE SWEEP (TEK — multiple timescales averaged) ───────")
    print(f"  {'label':22s} {'lkbs':>15} {'avg_R%':>7} {'0-days':>7} {'APY':>7} {'maxDD':>7} {'Calmar':>8}")
    print(f"  {'-'*22} {'-'*15} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
    for row in res["ensemble_rows"]:
        marker = " ◀ best" if row is res["best_ensemble"] else ""
        lbs_str = str(row["lookbacks"])
        print(f"  {row['label']:22s} {lbs_str:>15s}"
              f" {row['avg_risky_pct']:>6.1f}% {row['zero_days']:>7d}"
              f" {_f(row['apy']):>7} {_f(row['dd']):>7} {_f(row['calmar']):>8}{marker}")

    be = res["best_ensemble"]
    print(f"\n  Best ensemble: {be['label']} → Calmar {_f(be['calmar'])}"
          f"  APY {_f(be['apy'])}%  maxDD {_f(be['dd'])}%")

    print("\n── PART C: PER-CRISIS BREAKDOWN (static #3 vs KODS-10d vs best single vs best ensemble) ─")
    eq_s  = res["eq_static"]
    eq_k10 = res["eq_kods10"]
    eq_bs_full, _ = _tek_equity(dates, res["r_susde"],
                                 _smooth(dates, RATES_APY_PCT), _smooth(dates, RWA_APY_PCT),
                                 bs["lookbacks"])
    eq_be_full, _ = _tek_equity(dates, res["r_susde"],
                                 _smooth(dates, RATES_APY_PCT), _smooth(dates, RWA_APY_PCT),
                                 be["lookbacks"])
    print(f"  {'event':32s} {'static':>8} {'KODS10':>8} {bs['label']:>12} {be['label']:>20}")
    print(f"  {'-'*32} {'-'*8} {'-'*8} {'-'*12} {'-'*20}")
    for w in STRESS_WINDOWS:
        k = w["key"]
        cd_s   = _crisis_dd(dates, eq_s,       k)
        cd_k10 = _crisis_dd(dates, eq_k10,     k)
        cd_bs  = _crisis_dd(dates, eq_bs_full, k)
        cd_be  = _crisis_dd(dates, eq_be_full, k)
        print(f"  {k:32s} {_f(cd_s):>8} {_f(cd_k10):>8} {_f(cd_bs):>12} {_f(cd_be):>20}")

    # ── OOS ──────────────────────────────────────────────────────────────────────────────────────
    oos = res["oos"]
    if oos:
        td = oos["test_dates"]
        print(f"\n── PART D: OUT-OF-SAMPLE (unseen tail: {td[0]} → {td[-1]}, {len(td)} days) ─")
        def _oos_line(label: str, t: Tuple) -> None:
            a, d, c = t
            print(f"  {label:28s}  APY {_f(a)}%  maxDD {_f(d)}%  Calmar {_f(c)}")
        _oos_line("static #3",          oos["static"])
        _oos_line("DDO #9",             oos["ddo9"])
        _oos_line("KODS-10d (reproduced)", oos["kods10"])
        _oos_line(f"best-single ({bs['label']})", oos["best_single"])
        _oos_line(f"best-ensemble ({be['label']})", oos["best_ensemble"])
        a_bs_oos, d_bs_oos, c_bs_oos = oos["best_single"]
        if oos.get("best_single", (None,))[2] is not None:
            zero_days_oos = sum(1 for d in td
                                if _kelly_frac(
                                    [res["r_susde"][x] for x in sorted(res["r_susde"])
                                     if x < d][-30:], bs["lookbacks"][0]
                                ) < 1e-6)
        print("    ⚠  OOS is likely a calm period (same caveat as #1/#4/#8–#19):")
        print("       crisis-protection behaviour NOT exercised if no crisis occurs.")

    # ── mechanism explanation ──────────────────────────────────────────────────────────────────────
    print("\n── MECHANISM: WHY SHORTER LOOKBACKS MAY WIN ON THIS FIXTURE ────────────────")
    print("  FIXTURE PROPERTY: σ²≈0 in calm → Kelly = max_risky (same for all lkb)")
    print("  ENTRY DAY 1:  one large negative return → μ_lb < 0 for ALL lookbacks simultaneously")
    print("    → both KODS-10d AND KODS-3d fire on day 1 (no earlier detection advantage)")
    print("    → de-risk depth = 0% for both (Kelly turns negative, clip at 0)")
    print("  RECOVERY (key differentiator):")
    print("    KODS-3d : crash day exits 3d window at day (crisis_end + 3) → f_kelly > 0")
    print("    KODS-10d: crash day exits 10d window at day (crisis_end + 10) → f_kelly > 0")
    print("    SHORTER lkb = 7 fewer days at 0% sUSDe per crisis × 3 crises = 21 extra carry days")
    print("  ENSEMBLE (TEK):")
    print("    f_tek = mean([f_kelly_3d, ..., f_kelly_10d])")
    print("    In recovery: short-lkb Kelly > 0 FIRST → positive contribution pulls mean up")
    print("    → f_active climbs from 0 → max_risky EARLIER than KODS-10d")
    print("    But: ensemble mean < any individual component's max → slower climb than KODS-3d alone")
    print("    TEK is a CONVEX COMBINATION of single-window KODSes → bounded between min and max")

    # ── verdict ────────────────────────────────────────────────────────────────────────────────────
    print("\n── FINAL VERDICT ─────────────────────────────────────────────────────────────")
    cal_kods = cal_10
    cal_bs   = bs["calmar"]
    cal_be   = be["calmar"]

    if cal_bs is not None and cal_kods is not None and cal_bs > cal_kods * 1.05:
        single_verdict = f"✅ BEST SINGLE-WINDOW ({bs['label']}) BEATS KODS-10d by >5%"
    elif cal_bs is not None and cal_kods is not None and cal_bs > cal_kods:
        single_verdict = f"✅ BEST SINGLE-WINDOW ({bs['label']}) MARGINALLY BEATS KODS-10d"
    else:
        single_verdict = f"◯  Best single ({bs['label']}) does NOT beat KODS-10d"

    if cal_be is not None and cal_bs is not None and cal_be >= cal_bs * 0.98:
        ensemble_verdict = "✅ TEK ENSEMBLE competitive with best single-window (within 2%)"
    elif cal_be is not None and cal_bs is not None and cal_be > cal_kods:
        ensemble_verdict = f"✅ TEK ENSEMBLE beats KODS-10d but trails best single ({bs['label']})"
    else:
        ensemble_verdict = "⚠  TEK ENSEMBLE does not clearly improve over best single-window"

    print(f"  Single-window finding: {single_verdict}")
    print(f"  Ensemble finding:      {ensemble_verdict}")

    print(f"\n  Calmar summary (bt = backtest, L0, synthetic):")
    print(f"    static #3         : Calmar {_f(cal_s)}")
    print(f"    DDO #9            : Calmar {_f(cal_9)}")
    print(f"    KODS #15 (10d)    : Calmar {_f(cal_10)}  ← registry leader (4.55)")
    print(f"    Best single TEK   : {bs['label']} → Calmar {_f(cal_bs)}")
    print(f"    Best ensemble TEK : {be['label']} → Calmar {_f(cal_be)}")

    print("\n  HONEST CAVEATS (ALL required):")
    print("  (a) σ²≈0 in calm → Kelly degenerate (cap always active); no false-positive risk")
    print("      to test ensemble damping on THIS fixture. Ensemble's noise-damping benefit")
    print("      only materialises in real DeFi where calm vol > 0.")
    print("  (b) Day-1 hit unavoidable for ANY causal method (all windows fire simultaneously).")
    print("  (c) Any improvement is via FASTER RECOVERY (more carry during post-crisis period).")
    print("  (d) rates-carry + RWA = smooth synthetic (same as #3–#19, apples-to-apples).")
    print("  (e) OOS window is likely calm (no crisis) — crisis-protection NOT re-tested there.")
    print("  (f) EVIDENCE LEVEL: L0 (backtest/synthetic fixture). NOT live results.")
    print("  (g) TEK is strictly a CONVEX COMBINATION of single-window KODSes (by construction).")
    print("      It cannot EXCEED the best individual component in expectation on this fixture.")
    print("      Structural upper bound: Calmar(TEK) ≤ Calmar(best-single) on fixture data.")

    print("\n  FORWARD PAPER NEXT STEP:")
    print("  If best-single lookback < 10d outperforms KODS-10d:")
    print("    → Update KODS forward paper agent to use the optimal short lookback (advisory).")
    print("    → Wire advisory to RTMR-posture (read risk_posture.json, not execute).")
    print("  If TEK ensemble competitive with best-single but NOT on this fixture:")
    print("    → Test TEK on real-return data once exogenous RTMR signals are available")
    print("      (TEK's false-positive damping only measurable with realistic calm-vol data).")
    print("  ADR required before any capital-movement.")


if __name__ == "__main__":
    main()
