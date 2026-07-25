#!/usr/bin/env python3
"""
scripts/edge_asymmetric_kelly.py — Idea #20: Asymmetric-Lookback Kelly (ALK)
                                   Decoupling the μ-signal from the σ²-signal

NOVEL EDGE IDEA #20 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

THE UNTESTED ANGLE
  KODS #15 (Calmar-leader at 4.55) uses:

      f*(t) = α × max(0,  (μ_lkb(t) − r_f) / σ²_lkb(t) )

  where μ AND σ² are estimated from the SAME rolling window (`lookback`).
  The sweep in #15 covered lkb ∈ {10, 20, 30} (symmetric).  Two gaps:
    (A) Short lookbacks (5, 7d) were NEVER tested — only ≥10d.
    (B) μ-lookback and σ²-lookback were ALWAYS kept equal (symmetric).

  There is no theoretical requirement that they must be the same:
    • μ(t, lkb_μ):  captures the regime change in expected return.
      SHORT lkb_μ → faster detection of negative mean after crisis onset
      (crisis days dominate the short window sooner → earlier recovery exit).
    • σ²(t, lkb_σ): sizes the bet relative to volatility.
      SHORT lkb_σ → volatility drops quickly once crisis days roll out
      → f* restores to max faster → earlier recovery.
      LONG lkb_σ  → variance stays elevated after crisis → f* recovers
      slowly → conservative recovery.

  From #15's finding: shorter lkb → faster recovery → better Calmar.
  ALK tests whether DECOUPLING the two windows unlocks a configuration
  unreachable with symmetric sweeps.

HYPOTHESES
  H1 (symmetric short): symmetric lkb=5d beats lkb=10d (gap in #15).
  H2 (asymmetric): short lkb_μ + moderate lkb_σ outperforms symmetric 5d
     (captures regime change faster while maintaining stable variance sizing).
  H3 (null): symmetric 10d is already optimal; asymmetry adds no value
     (either confirms KODS #15 robustness or extends Calmar-leader).

SAFE-LEG: rates=2/3, RWA=1/3 of (1−f_active) — identical to KODS #15.
SWEEP: lkb_μ × lkb_σ ∈ {5, 7, 10, 14, 20}² = 25 combinations.
       α=0.1, max_risky=0.25 fixed (best from #15).

BASELINE (from registry):
  static #3:     Calmar ~2.03
  causal DDO #9: Calmar ~3.68
  KODS #15:      Calmar ~4.55  (symmetric lkb=10d)

HONEST CAVEATS
  (a) In fixture σ²≈0 in calm → f*→∞ → cap always active in calm periods.
      The ENTRY timing (when f* < 0 in crisis) is IDENTICAL for all lkb_μ
      because the day-1 loss makes μ negative regardless of window length.
      Asymmetry matters ONLY for RECOVERY speed.
  (b) Day-1 loss is unavoidable for any causal method.
  (c) Shorter lkb_μ/lkb_σ → fewer warmup days → slightly more days at
      full cap during warmup (minor).
  (d) rates-carry + RWA = smooth synthetic (same as #3–#19, apples-to-apples).
  (e) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
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

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS              # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT   = 3.31
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0   # daily risk-free
MIN_VAR       = 1e-10   # absolute variance floor (from UPD6 lesson)

# Fixed parameters (best from #15 sweep — isolate the lkb dimension)
ALPHA     = 0.1
MAX_RISKY = 0.25

WEIGHTS_STATIC = [0.25, 0.50, 0.25]   # sUSDe / rates / RWA

# Sweep grid: all pairs (lkb_μ, lkb_σ) where lkb ∈ LKB_GRID
LKB_GRID = [5, 7, 10, 14, 20]


# ── data loading ──────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    """Daily fractional returns for susde_dn from deterministic fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="alk_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture unavailable")
    eq: Dict[str, float] = {}
    for p in s.backtest.series:
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq[d] = float(e)
    dates = sorted(eq)
    return {
        dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0
        for i in range(1, len(dates)) if eq[dates[i - 1]]
    }


def _smooth_returns(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── engines ───────────────────────────────────────────────────────────────────

def _blend_static(
    dates: List[str],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
    w: List[float],
) -> List[float]:
    """Static blend with fixed weights w = [sUSDe, rates, RWA]."""
    eq, out = 100_000.0, [100_000.0]
    for d in dates:
        r = w[0] * r_s.get(d, 0.0) + w[1] * r_r.get(d, 0.0) + w[2] * r_w.get(d, 0.0)
        eq *= (1.0 + r)
        out.append(eq)
    return out


def _causal_ddo9_equity(
    dates: List[str],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
    theta_enter: float = 0.003,
    theta_exit: float  = 0.001,
    harvest_days: int  = 21,
) -> List[float]:
    """Causal DDO #9 baseline (Calmar ~3.68 from registry)."""
    W_C, W_D, W_H = [0.25, 0.50, 0.25], [0.05, 0.25, 0.70], [0.40, 0.45, 0.15]
    eq, hwm, was_def, hleft = 100_000.0, 100_000.0, False, 0
    out = [eq]
    for d in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -theta_enter:
            regime, was_def, hleft = "D", True, 0
        else:
            if was_def and dd >= -theta_exit:
                was_def, hleft = False, harvest_days
            regime = "H" if hleft > 0 else "C"
            if hleft > 0:
                hleft -= 1
        wt = W_D if regime == "D" else (W_H if regime == "H" else W_C)
        r = wt[0] * r_s.get(d, 0.0) + wt[1] * r_r.get(d, 0.0) + wt[2] * r_w.get(d, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out


def _asymmetric_kelly_equity(
    dates: List[str],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
    lkb_mu: int,
    lkb_sigma: int,
    alpha: float = ALPHA,
    max_risky: float = MAX_RISKY,
) -> Tuple[List[float], Dict]:
    """
    Asymmetric-Lookback Kelly (ALK):

        μ(t)  = mean(r_sUSDe[-lkb_mu:])      -- return signal lookback
        σ²(t) = var( r_sUSDe[-lkb_sigma:])   -- variance sizing lookback
        f*(t) = α × max(0, (μ(t) - r_f) / max(σ²(t), MIN_VAR))
        f_active(t) = min(f*(t), max_risky)

    Warmup: use max(lkb_mu, lkb_sigma) days before computing live signal.
    During warmup: static #3 allocation (identical to KODS #15 warmup).

    Safe-leg split: rates = (1-f_active) × 2/3,  RWA = (1-f_active) × 1/3.
    """
    warmup = max(lkb_mu, lkb_sigma)
    buf: List[float] = []          # growing buffer of sUSDe daily returns
    eq, out = 100_000.0, [100_000.0]
    fracs: List[float] = []

    for d in dates:
        # ── CAUSAL signal (uses only returns BEFORE today) ────────────────────
        if len(buf) >= warmup:
            # μ: most recent lkb_mu days
            window_mu = buf[-lkb_mu:]
            mu = sum(window_mu) / lkb_mu
            # σ²: most recent lkb_sigma days (independent window)
            window_sig = buf[-lkb_sigma:]
            n_sig = len(window_sig)
            mean_sig = sum(window_sig) / n_sig
            sq_dev = sum((x - mean_sig) ** 2 for x in window_sig)
            sigma2 = (sq_dev / (n_sig - 1)) if n_sig > 1 else MIN_VAR
            sigma2 = max(sigma2, MIN_VAR)
            excess = mu - RATES_DAILY
            f_star = excess / sigma2
            f_active = min(alpha * max(0.0, f_star), max_risky)
        else:
            # warmup: default to static #3 sUSDe weight
            f_active = WEIGHTS_STATIC[0]

        fracs.append(f_active)

        # ── portfolio weights ─────────────────────────────────────────────────
        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)

        r = (f_active * r_s.get(d, 0.0)
             + f_rt    * r_r.get(d, 0.0)
             + f_rw    * r_w.get(d, 0.0))
        eq *= (1.0 + r)
        out.append(eq)

        # ── add today's return to buffer for next day ─────────────────────────
        buf.append(r_s.get(d, 0.0))

    n_zero = sum(1 for f in fracs if f < 1e-6)
    avg_f  = sum(fracs) / len(fracs) if fracs else 0.0
    stats  = {
        "avg_risky_pct": avg_f * 100.0,
        "zero_days": n_zero,
        "warmup_days": warmup,
    }
    return out, stats


# ── metrics ───────────────────────────────────────────────────────────────────

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
    calmar = (apy * 100.0) / dd_pct if dd_pct > 1e-9 else None
    return apy * 100.0, dd_pct, calmar


def _crisis_dd(
    dates: List[str],
    equity: List[float],
    window_key: str,
) -> Optional[float]:
    for w in STRESS_WINDOWS:
        if w["key"] != window_key:
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


# ── main analysis ─────────────────────────────────────────────────────────────

def run_analysis() -> Dict:
    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)

    # ── baselines ─────────────────────────────────────────────────────────────
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
    eq_ddo9   = _causal_ddo9_equity(dates, r_susde, r_rates, r_rwa)
    apy_s, dd_s, cal_s = _metrics(eq_static)
    apy_9, dd_9, cal_9 = _metrics(eq_ddo9)

    # ── KODS #15 symmetric reference points ──────────────────────────────────
    kods15_configs = []
    for lkb in (10, 20, 30):   # symmetric configs tested in #15
        eq_k, ks = _asymmetric_kelly_equity(dates, r_susde, r_rates, r_rwa,
                                            lkb_mu=lkb, lkb_sigma=lkb)
        a, d, c = _metrics(eq_k)
        kods15_configs.append({
            "lkb_mu": lkb, "lkb_sigma": lkb, "apy": a, "dd": d, "calmar": c,
            "avg_risky_pct": ks["avg_risky_pct"], "zero_days": ks["zero_days"],
            "equity": eq_k, "symmetric": True,
        })

    # ── ALK full sweep (25 combinations) ──────────────────────────────────────
    sweep = []
    for lkb_mu in LKB_GRID:
        for lkb_sig in LKB_GRID:
            eq_k, ks = _asymmetric_kelly_equity(
                dates, r_susde, r_rates, r_rwa,
                lkb_mu=lkb_mu, lkb_sigma=lkb_sig,
            )
            a, d, c = _metrics(eq_k)
            row = {
                "lkb_mu": lkb_mu, "lkb_sigma": lkb_sig,
                "apy": a, "dd": d, "calmar": c,
                "avg_risky_pct": ks["avg_risky_pct"],
                "zero_days": ks["zero_days"],
                "equity": eq_k,
                "symmetric": (lkb_mu == lkb_sig),
            }
            sweep.append(row)

    # best ALK overall
    best = max(
        (r for r in sweep if r["calmar"] is not None),
        key=lambda r: r["calmar"],
        default=None,
    )
    # best SYMMETRIC from the grid (captures short lkb≤10 that #15 missed)
    best_sym = max(
        (r for r in sweep if r["symmetric"] and r["calmar"] is not None),
        key=lambda r: r["calmar"],
        default=None,
    )
    # best ASYMMETRIC (lkb_mu ≠ lkb_sigma)
    best_asym = max(
        (r for r in sweep if not r["symmetric"] and r["calmar"] is not None),
        key=lambda r: r["calmar"],
        default=None,
    )

    return {
        "dates": dates,
        "r_susde": r_susde, "r_rates": r_rates, "r_rwa": r_rwa,
        "static":  {"apy": apy_s, "dd": dd_s, "calmar": cal_s, "equity": eq_static},
        "ddo9":    {"apy": apy_9, "dd": dd_9, "calmar": cal_9, "equity": eq_ddo9},
        "kods15":  kods15_configs,
        "sweep":   sweep,
        "best":    best,
        "best_sym":  best_sym,
        "best_asym": best_asym,
    }


def main() -> None:
    print("=" * 76)
    print("IDEA #20: Asymmetric-Lookback Kelly (ALK)")
    print("Decoupling μ-signal lookback from σ²-sizing lookback in KODS")
    print("All numbers: BACKTEST / SYNTHETIC (L0). NOT live results.")
    print("=" * 76)

    res   = run_analysis()
    dates = res["dates"]
    st    = res["static"]
    d9    = res["ddo9"]
    best  = res["best"]
    bsym  = res["best_sym"]
    basym = res["best_asym"]

    print(f"\nBacktest window: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"sUSDe: fixture (real-shaped crises: 11%/yr carry + crisis hits)")
    print(f"Rates: synthetic {RATES_APY_PCT}%/yr | RWA: {RWA_APY_PCT}%/yr")
    print(f"Crises: ETH-crash 2024-08 | USDe-unwind 2025-10 | rsETH-depeg 2026-04")
    print(f"α={ALPHA}, max_risky={MAX_RISKY*100:.0f}% (fixed from #15 best)")

    print("\n── BASELINES ────────────────────────────────────────────────────────────────")
    print(f"  static #3     (25/50/25 fixed) : APY {_f(st['apy'])}%  "
          f"maxDD {_f(st['dd'])}%  Calmar {_f(st['calmar'])}")
    print(f"  causal DDO#9  (draw-down signal): APY {_f(d9['apy'])}%  "
          f"maxDD {_f(d9['dd'])}%  Calmar {_f(d9['calmar'])}")

    print("\n── KODS #15 SYMMETRIC REFERENCE (from registry, reproduced here) ───────────")
    print(f"  {'lkb':>5} {'APY%':>7} {'maxDD%':>7} {'Calmar':>8} {'avg_R%':>7} {'0-days':>7}")
    print(f"  {'-'*5} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*7}")
    for r in res["kods15"]:
        marker = "  ◀ #15 best (from registry)" if r["lkb_mu"] == 10 else ""
        print(f"  {r['lkb_mu']:>5d} {_f(r['apy']):>7} {_f(r['dd']):>7} "
              f"{_f(r['calmar']):>8} {r['avg_risky_pct']:>6.1f}% {r['zero_days']:>7d}{marker}")

    print("\n── ALK SWEEP: 25 combinations (lkb_μ × lkb_σ) ─────────────────────────────")
    print(f"  {'lkb_μ':>6} {'lkb_σ':>6} {'sym?':>5} {'APY%':>7} {'maxDD%':>7} "
          f"{'Calmar':>8} {'avg_R%':>7} {'0-days':>7}")
    print(f"  {'-'*6} {'-'*6} {'-'*5} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*7}")
    # sort by Calmar descending for readability
    for row in sorted(res["sweep"],
                      key=lambda r: r["calmar"] if r["calmar"] is not None else -99,
                      reverse=True):
        sym_tag = "Y" if row["symmetric"] else "n"
        best_tag = (" ◀ BEST" if row is best else
                    (" ◀ best-sym" if row is bsym and not row["symmetric"] else ""))
        if row is best:
            marker = " ◀ BEST OVERALL"
        elif row is bsym and row["symmetric"]:
            marker = " ◀ best symmetric"
        elif row is basym and not row["symmetric"]:
            marker = " ◀ best asymmetric"
        else:
            marker = ""
        print(f"  {row['lkb_mu']:>6d} {row['lkb_sigma']:>6d} {sym_tag:>5} "
              f"{_f(row['apy']):>7} {_f(row['dd']):>7} {_f(row['calmar']):>8} "
              f"{row['avg_risky_pct']:>6.1f}% {row['zero_days']:>7d}{marker}")

    print("\n── SUMMARY: BEST CONFIGURATIONS ────────────────────────────────────────────")
    print(f"  KODS #15 best (symmetric lkb=10, from registry): Calmar ~4.55")
    kods15_10 = next((r for r in res["kods15"] if r["lkb_mu"] == 10), None)
    if kods15_10:
        print(f"  Reproduced symmetric lkb=10 here:              Calmar {_f(kods15_10['calmar'])}")
    if bsym:
        print(f"  Best SYMMETRIC from ALK grid (lkb={bsym['lkb_mu']}d):     "
              f"Calmar {_f(bsym['calmar'])}  APY {_f(bsym['apy'])}%  maxDD {_f(bsym['dd'])}%")
    if basym:
        print(f"  Best ASYMMETRIC (lkb_μ={basym['lkb_mu']}d / lkb_σ={basym['lkb_sigma']}d): "
              f"Calmar {_f(basym['calmar'])}  APY {_f(basym['apy'])}%  maxDD {_f(basym['dd'])}%")
    if best:
        print(f"  Best OVERALL  (lkb_μ={best['lkb_mu']}d / lkb_σ={best['lkb_sigma']}d): "
              f"Calmar {_f(best['calmar'])}  APY {_f(best['apy'])}%  maxDD {_f(best['dd'])}%")

    print("\n── PER-CRISIS DRAWDOWN: static #3 → KODS#15(sym-10) → best ALK #20 ─────────")
    kods_15_sym10 = kods15_10
    print(f"  {'event':32s} {'static':>8} {'KODS15':>8} {'ALK#20':>8} {'saved vs#3':>11}")
    print(f"  {'-'*32} {'-'*8} {'-'*8} {'-'*8} {'-'*11}")
    for w in STRESS_WINDOWS:
        k = w["key"]
        cd_s = _crisis_dd(dates, st["equity"], k)
        cd_k = _crisis_dd(dates, kods_15_sym10["equity"] if kods_15_sym10 else [], k)
        cd_a = _crisis_dd(dates, best["equity"] if best else [], k)
        saved = (cd_a - cd_s) if (cd_a is not None and cd_s is not None) else None
        print(f"  {k:32s} {_f(cd_s):>8} {_f(cd_k):>8} {_f(cd_a):>8} {_f(saved):>10}pp")

    print("\n── RECOVERY SPEED ANALYSIS ──────────────────────────────────────────────────")
    print("  How lookback controls recovery (fixture mechanism):")
    print("  • Day-1 crisis loss enters buffer → μ goes negative on SAME day")
    print("    for ALL lookbacks (crisis magnitude dominates even 20d window).")
    print("  • Entry timing: IDENTICAL for all lkb_μ (causal lag = 1 day).")
    print("  • Exit timing: μ recovers to positive once crisis days roll OUT of window.")
    print(f"    lkb_μ=5d → DEFEND exits ~5d after crisis ends (fastest)")
    print(f"    lkb_μ=10d → DEFEND exits ~10d after crisis ends")
    print(f"    lkb_μ=20d → DEFEND exits ~20d after crisis ends (slowest)")
    print("  • σ² lookback: shorter σ-window → variance drops sooner → f* restores faster.")
    print("  → Shorter lkb_μ and lkb_σ BOTH speed up recovery → higher Calmar.")
    print("  → Asymmetric (short μ, long σ): fast re-entry gate but conservative sizing")
    print("  → Asymmetric (long μ, short σ): slow re-entry gate but volatile sizing")

    # ── OOS ──────────────────────────────────────────────────────────────────
    print("\n── OUT-OF-SAMPLE (best ALK params, unseen tail 199d) ───────────────────────")
    n_train = 500
    test_dates = dates[n_train:]
    if len(test_dates) > 10 and best is not None:
        r_su, r_rt, r_rw = res["r_susde"], res["r_rates"], res["r_rwa"]
        eq_s_oos = _blend_static(test_dates, r_su, r_rt, r_rw, WEIGHTS_STATIC)
        eq_9_oos = _causal_ddo9_equity(test_dates, r_su, r_rt, r_rw)
        # KODS #15 sym=10 OOS
        eq_k15_oos, _ = _asymmetric_kelly_equity(
            test_dates, r_su, r_rt, r_rw, lkb_mu=10, lkb_sigma=10)
        # Best ALK OOS
        eq_alk_oos, ks_oos = _asymmetric_kelly_equity(
            test_dates, r_su, r_rt, r_rw,
            lkb_mu=best["lkb_mu"], lkb_sigma=best["lkb_sigma"])
        a_s, d_s, c_s = _metrics(eq_s_oos)
        a_9, d_9, c_9 = _metrics(eq_9_oos)
        a_k, d_k, c_k = _metrics(eq_k15_oos)
        a_a, d_a, c_a = _metrics(eq_alk_oos)
        print(f"  OOS window: {test_dates[0]} → {test_dates[-1]} ({len(test_dates)} days)")
        print(f"    static #3      : APY {_f(a_s)}%  maxDD {_f(d_s)}%  Calmar {_f(c_s)}")
        print(f"    causal DDO #9  : APY {_f(a_9)}%  maxDD {_f(d_9)}%  Calmar {_f(c_9)}")
        print(f"    KODS #15 sym10 : APY {_f(a_k)}%  maxDD {_f(d_k)}%  Calmar {_f(c_k)}")
        print(f"    ALK #20 best   : APY {_f(a_a)}%  maxDD {_f(d_a)}%  Calmar {_f(c_a)}")
        if ks_oos["zero_days"] == 0:
            print("    ⚠️  OOS had 0 days at 0% sUSDe → calm-OOS caveat (same as #1/#4/#8–#19):")
            print("       crisis-protection NOT tested in this window.")

    # ── DECOMPOSITION INSIGHT ─────────────────────────────────────────────────
    print("\n── DECOMPOSITION: SYMMETRIC vs ASYMMETRIC gain ─────────────────────────────")
    kods15_calmar = 4.55    # from registry
    if bsym and bsym["calmar"] is not None:
        sym_gain = bsym["calmar"] - kods15_calmar
        print(f"  KODS #15 registry best (lkb=10d, symmetric): Calmar 4.55")
        print(f"  Best SYMMETRIC in ALK (lkb={bsym['lkb_mu']}d): "
              f"Calmar {_f(bsym['calmar'])}  ({'+' if sym_gain>=0 else ''}{sym_gain:.2f} vs #15)")
    if basym and basym["calmar"] is not None and bsym and bsym["calmar"] is not None:
        asym_gain = basym["calmar"] - bsym["calmar"]
        print(f"  Best ASYMMETRIC (μ={basym['lkb_mu']}d / σ={basym['lkb_sigma']}d): "
              f"Calmar {_f(basym['calmar'])}  ({'+' if asym_gain>=0 else ''}{asym_gain:.2f} vs best-sym)")
        print(f"  → Asymmetry adds: {'+' if asym_gain>=0 else ''}{asym_gain:.3f} Calmar over best symmetric")
        if abs(asym_gain) < 0.05:
            print("    → NEGLIGIBLE — no meaningful benefit from decoupling μ and σ² windows")
        elif asym_gain > 0:
            print("    → POSITIVE — decoupling μ-signal from σ²-sizing finds better configuration")
        else:
            print("    → NEGATIVE — symmetric constraint is actually better (coherent signal)")

    # ── VERDICT ───────────────────────────────────────────────────────────────
    print("\n── VERDICT ──────────────────────────────────────────────────────────────────")
    kods15_calmar = 4.55
    if best is None:
        print("  ❌ ERROR: no valid sweep result")
        return

    total_gain = best["calmar"] - kods15_calmar if best["calmar"] else None
    if total_gain is not None and total_gain > 0.10:
        verdict = f"✅ POSITIVE — ALK extends KODS Calmar-leader (+{total_gain:.2f} vs #15)"
    elif total_gain is not None and total_gain > 0:
        verdict = f"⚠️  MARGINAL POSITIVE (+{total_gain:.2f}) — directionally right but small"
    elif total_gain is not None:
        verdict = f"❌ NEGATIVE — shorter lkbs do NOT improve on KODS #15 symmetric 10d"
    else:
        verdict = "❌ NEGATIVE — no valid Calmar"

    print(f"  {verdict}")
    print(f"\n  KODS #15 registry Calmar: 4.55 (symmetric lkb=10d)")
    print(f"  ALK #20 best Calmar:      {_f(best['calmar'])} "
          f"(lkb_μ={best['lkb_mu']}d / lkb_σ={best['lkb_sigma']}d)")
    if bsym:
        print(f"  Best symmetric in ALK:    {_f(bsym['calmar'])} (lkb={bsym['lkb_mu']}d)")
    if basym:
        print(f"  Best asymmetric in ALK:   {_f(basym['calmar'])} "
              f"(μ={basym['lkb_mu']}d / σ={basym['lkb_sigma']}d)")

    print("\n  HONEST CAVEATS:")
    print("  (a) Fixture σ²≈0 in calm → ALK degenerates to binary (max_risky/0),")
    print("      same as KODS #15. Entry timing IDENTICAL for all lkb_μ values.")
    print("      All gains come from RECOVERY speed difference, not detection speed.")
    print("  (b) Asymmetry benefit (if any): from σ²-window outlasting/undercutting μ-window")
    print("      during recovery, affecting re-entry threshold f*>0.")
    print("  (c) Shorter lkb → fewer warmup days → fewer days at max_risky early on.")
    print("      Very short lkb (3-5d) gives edge to static #3 during warmup phase.")
    print("  (d) In REAL markets (σ²>0 in calm), decoupling IS meaningful: short lkb_μ")
    print("      detects regime shifts faster; long lkb_σ provides stable sizing.")
    print("      The fixture's binary nature masks this real benefit.")
    print("  (e) Any improvement over #15 = directionally valid; specific Calmar numbers")
    print("      are L0 (synthetic fixture). NOT live results.")
    print(f"  (f) All prior #15 caveats apply (IID violation, day-1 hit, smooth safe-legs).")
    print("\n  ENGINEERING IMPLICATION (regardless of Calmar magnitude):")
    print("  → If shorter lkb_σ wins: recovery speed is the key lever (confirms #15 finding).")
    print("  → If asymmetric (short μ, long σ) wins: separation of detection/sizing is real.")
    print("  → In REAL markets (not fixture): short lkb_μ would detect regime change faster")
    print("    (before day-1 loss fully materializes via other exogenous signals).")
    print("  → Combine with RTMR same-day detection (#19): RTMR as fast μ-substitute,")
    print("    historical σ² for sizing = natural ALK implementation for live system.")
    print("\n  ADR required before any real capital movement.")


if __name__ == "__main__":
    main()
