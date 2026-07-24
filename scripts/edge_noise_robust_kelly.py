#!/usr/bin/env python3
"""
scripts/edge_noise_robust_kelly.py — Idea #20: Noise-Robust Kelly via Adaptive Hysteresis (NRK-AH)

NOVEL EDGE IDEA #20 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  KODS #15 is the current Calmar-leader (4.55 in fixture). It fires EXACTLY at
  Kelly-ratio zero: CRUISE when Kelly≥0, DEFEND when Kelly<0. This is optimal
  for a NOISE-FREE fixture (deterministic drift + front-loaded shocks).

  BUT: real DeFi returns are NOISY. Daily sUSDe returns in real markets carry
  idiosyncratic noise (oracle jitter, on-chain block timing, microstructure).
  The Kelly ratio μ/σ² can OSCILLATE under noise, causing spurious CRUISE↔DEFEND
  transitions = excessive turnover + real trading costs.

  TWO DEFENCES against noise are tested:
    A) HYSTERESIS BAND ±δ (Schmitt-trigger analog):
       Switch to DEFEND when Kelly < −δ; return to CRUISE when Kelly > +δ.
       Key: δ must be calibrated to the ACTUAL Kelly ratio magnitude, not tiny.
    B) LONGER LOOKBACK (averaging noise out):
       Longer lookback window reduces noise-driven μ_rolling volatility.

  FINDING IN ADVANCE (spoiler, for honest framing):
    In fixture, calm-period Kelly ≈ 0.1×μ/noise_var. At σ_noise=0.1%/day:
    noise_var ≈ 1e-6/day → Kelly_calm ≈ 0.1×0.0003/1e-6 ≈ 30.
    The signal oscillates between ±30, NOT near zero — so small hysteresis
    (δ≪30) is invisible. Real hysteresis requires δ on the order of Kelly_calm.
    Longer lookback DOES reduce noise via averaging: std(μ_rolling) ∝ 1/√N.

WHY THIS IS GENUINELY NEW vs #1–#19
  • #15 KODS: fixed lookback=10, δ=0 (no hysteresis, no noise test)
  • #10 TCB: break-even cost, didn't test reduced-switch strategies
  • No prior idea tested KODS under realistic return noise OR a dead-band
    around the Kelly threshold OR lookback sensitivity to noise.

METHODOLOGY
  1. Baseline: KODS δ=0, lookback=10, zero noise → verify Calmar ≈ 4.55
  2. Noise grid: σ ∈ {0%, 0.1%, 0.5%, 1.0%} daily std (seeded Gaussian, seed=42)
  3. Hysteresis grid (Kelly-ratio units): δ ∈ {0, 1, 5, 15, 30, 60}
  4. Lookback grid: {5, 10, 20, 40} days under each noise level
  5. Key metrics: Calmar, switches/year, APY, maxDD

FIXTURE
  spa_core/strategy_lab/aggressive_lab/fixtures.py → materialize().
  Deterministic, ~699 trading days, 3 real-shaped stress windows.

HONEST CAVEATS
  (a) Gaussian noise simplifies real DeFi fat-tailed microstructure noise.
  (b) Fixture calm-period σ²=0 exactly; any noise dominates the variance floor
      differently from real markets (where σ²>0 naturally).
  (c) Single seed=42. A seed sweep would show a distribution of outcomes.
  (d) rates/RWA legs smooth synthetic (same assumption as all prior ideas).
  (e) Evidence level: L0 (backtest/synthetic). NOT live results.

INVARIANTS
  LLM_FORBIDDEN · stdlib-only · deterministic (seed=42) · no execution import
  no fabricated data · IS_ADVISORY=True
"""
# LLM_FORBIDDEN
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx   # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld     # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS   # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RATES_APY   = 4.6     # %/yr synthetic
RWA_APY     = 3.31    # %/yr synthetic
RATES_DAILY = RATES_APY / 100.0 / 365.0
RWA_DAILY   = RWA_APY / 100.0 / 365.0
RF_DAILY    = RATES_DAILY
MAX_RISKY   = 0.25    # sUSDe cap in calm (matches static #3 and KODS #15)
ALPHA_KELLY = 0.1     # fractional Kelly multiplier
MIN_VAR     = 1e-10   # variance floor

NOISE_SEED  = 42

# Grids
NOISE_STDS   = [0.0, 0.001, 0.005, 0.010]
DELTA_GRID   = [0.0, 1.0, 5.0, 15.0, 30.0, 60.0]   # Kelly-ratio units
LOOKBACK_GRID = [5, 10, 20, 40]


# ── data loading ──────────────────────────────────────────────────────────────
def _load_susde() -> Tuple[List[str], List[float]]:
    tmp = Path(tempfile.mkdtemp(prefix="nrk_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None:
        raise RuntimeError("susde_dn not in fixture")
    eq_map: Dict[str, float] = {}
    for p in s.backtest.series:
        d = p.get("date")
        e = p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq_map[d] = float(e)
    dates_sorted = sorted(eq_map)
    rets = [eq_map[dates_sorted[i]] / eq_map[dates_sorted[i - 1]] - 1.0
            for i in range(1, len(dates_sorted)) if eq_map.get(dates_sorted[i - 1])]
    return dates_sorted[1:], rets


def _add_noise(rets: List[float], sigma: float, seed: int) -> List[float]:
    if sigma == 0.0:
        return rets[:]
    rng = random.Random(seed)
    return [r + rng.gauss(0.0, sigma) for r in rets]


# ── Kelly ratio ────────────────────────────────────────────────────────────────
def _kelly(rets: List[float], t: int, lookback: int) -> float:
    """Causal rolling Kelly ratio in Kelly-criterion units (dimensionless)."""
    window = rets[max(0, t - lookback): t]
    n = len(window)
    if n < 2:
        return float("inf")
    mu = sum(window) / n - RF_DAILY
    var = max(MIN_VAR, sum((r - (sum(window) / n)) ** 2 for r in window) / (n - 1))
    return (ALPHA_KELLY * mu) / var


# ── portfolio simulator ────────────────────────────────────────────────────────
def _simulate(signal_rets: List[float], actual_rets: List[float],
              rates_r: List[float], rwa_r: List[float],
              lookback: int, delta: float) -> dict:
    """
    Hysteresis-Kelly cross-desk portfolio.
    signal_rets: returns used for Kelly signal computation.
    actual_rets: clean fixture returns used for P&L (same as signal in our tests).
    """
    n = len(actual_rets)
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    state = "CRUISE"
    n_sw = 0
    for t in range(n):
        kr = _kelly(signal_rets, t, lookback)
        prev = state
        if state == "CRUISE" and kr < -delta:
            state = "DEFEND"
        elif state == "DEFEND" and kr > delta:
            state = "CRUISE"
        if state != prev:
            n_sw += 1
        f = MAX_RISKY if state == "CRUISE" else 0.0
        safe = 1.0 - f
        port = f * actual_rets[t] + safe * (2/3) * rates_r[t] + safe * (1/3) * rwa_r[t]
        nav *= (1.0 + port)
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak
        if dd > max_dd:
            max_dd = dd
    n_yrs = n / 365.0
    cagr = (nav ** (1.0 / n_yrs) - 1.0) if n_yrs > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 1e-9 else float("inf")
    return {
        "cagr": round(cagr * 100, 3),
        "max_dd": round(max_dd * 100, 3),
        "calmar": round(calmar, 3),
        "sw": n_sw,
        "sw_yr": round(n_sw / n_yrs, 2),
    }


def _static(rets: List[float], rates: List[float], rwa: List[float]) -> dict:
    nav, peak, max_dd = 1.0, 1.0, 0.0
    for t in range(len(rets)):
        port = 0.25 * rets[t] + 0.50 * rates[t] + 0.25 * rwa[t]
        nav *= (1.0 + port)
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak
        if dd > max_dd:
            max_dd = dd
    n_yrs = len(rets) / 365.0
    cagr = (nav ** (1.0 / n_yrs) - 1.0) if n_yrs > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 1e-9 else float("inf")
    return {"cagr": round(cagr*100,3), "max_dd": round(max_dd*100,3), "calmar": round(calmar,3)}


# ── per-crisis breakdown ───────────────────────────────────────────────────────
def _crisis_dd(dates: List[str], sig_rets: List[float], act_rets: List[float],
               rates: List[float], rwa: List[float],
               lookback: int, delta: float) -> Dict[str, float]:
    result = {}
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        lo, hi = str(w["date_from"]), str(w["date_to"])
        idxs = [i for i, d in enumerate(dates) if lo <= d <= hi]
        if not idxs:
            result[key] = 0.0
            continue
        nav, peak, max_dd_w = 1.0, 1.0, 0.0
        state = "CRUISE"
        idx_set = set(idxs)
        for t in range(idxs[-1] + 1):
            kr = _kelly(sig_rets, t, lookback)
            if state == "CRUISE" and kr < -delta:
                state = "DEFEND"
            elif state == "DEFEND" and kr > delta:
                state = "CRUISE"
            f = MAX_RISKY if state == "CRUISE" else 0.0
            safe = 1.0 - f
            port = f * act_rets[t] + safe * (2/3) * rates[t] + safe * (1/3) * rwa[t]
            nav *= (1.0 + port)
            if nav > peak:
                peak = nav
            if t in idx_set:
                dd = (peak - nav) / peak
                if dd > max_dd_w:
                    max_dd_w = dd
        result[key] = round(-max_dd_w * 100, 3)
    return result


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("Idea #20: Noise-Robust Kelly via Adaptive Hysteresis (NRK-AH)")
    print("EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("=" * 72)

    dates, base_rets = _load_susde()
    n = len(base_rets)
    rates_r = [RATES_DAILY] * n
    rwa_r   = [RWA_DAILY]   * n
    n_yrs = n / 365.0

    print(f"\nFixture: {n} returns ({n_yrs:.2f} yrs)  {dates[0]}..{dates[-1]}")

    # ── baselines ────────────────────────────────────────────────────────
    s3 = _static(base_rets, rates_r, rwa_r)
    print(f"\nBaseline static #3:  APY {s3['cagr']}%  maxDD {s3['max_dd']}%  Calmar {s3['calmar']}")

    kods_base = _simulate(base_rets, base_rets, rates_r, rwa_r, lookback=10, delta=0.0)
    print(f"KODS #15 (lb=10,δ=0): APY {kods_base['cagr']}%  maxDD {kods_base['max_dd']}%  "
          f"Calmar {kods_base['calmar']}  sw {kods_base['sw']} ({kods_base['sw_yr']}/yr)")

    # ── Diagnostic: Kelly ratio magnitude at noise levels ─────────────────
    print("\n--- DIAGNOSTIC: Kelly ratio magnitude (calibrate δ scale) ---")
    print("  In calm fixture (σ²=0), Kelly=±∞. Under noise, var ≈ σ_noise².")
    print("  Kelly_calm ≈ ALPHA × μ_carry / σ_noise²")
    for sigma in NOISE_STDS[1:]:  # skip 0
        mu_carry = 11.0 / 100.0 / 365.0 - RF_DAILY   # excess return/day
        kelly_est = ALPHA_KELLY * mu_carry / (sigma ** 2) if sigma > 0 else float("inf")
        print(f"  σ={sigma*100:.1f}%/day → Kelly_calm ≈ {kelly_est:.0f}  "
              f"(valid δ range: ~{kelly_est*0.1:.0f}–{kelly_est*2:.0f})")

    # ── PART 1: Hysteresis δ sweep (noise=0.5%, lookback=10) ─────────────
    sigma_demo = 0.005
    noisy_demo = _add_noise(base_rets, sigma_demo, NOISE_SEED)
    print(f"\n--- PART 1: Hysteresis δ sweep (σ=0.5%/day, lookback=10, Kelly units) ---")
    print(f"{'δ':>8}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>8}  {'sw/yr':>6}  "
          f"{'vs_KODS_zeronoise':>18}")
    for delta in DELTA_GRID:
        res = _simulate(noisy_demo, noisy_demo, rates_r, rwa_r, lookback=10, delta=delta)
        vs = round(res["calmar"] - kods_base["calmar"], 3)
        print(f"{delta:>8.1f}  {res['cagr']:>7.3f}  {res['max_dd']:>7.3f}  "
              f"{res['calmar']:>8.3f}  {res['sw_yr']:>6.2f}  {vs:>+18.3f}")

    # ── PART 2: Lookback sweep under noise (this is the main finding) ─────
    print("\n--- PART 2: Lookback sensitivity under noise (δ=0, KEY FINDING) ---")
    print(f"{'σ_noise':>9}  {'lookback':>10}  {'APY%':>7}  {'maxDD%':>7}  "
          f"{'Calmar':>8}  {'sw/yr':>6}  {'vs_lb10_no_noise':>18}")
    kods_base_calmar = kods_base["calmar"]
    for sigma in NOISE_STDS:
        noisy = _add_noise(base_rets, sigma, NOISE_SEED)
        for lb in LOOKBACK_GRID:
            res = _simulate(noisy, noisy, rates_r, rwa_r, lookback=lb, delta=0.0)
            vs = round(res["calmar"] - kods_base_calmar, 3)
            print(f"{sigma*100:>8.1f}%  {lb:>10}  {res['cagr']:>7.3f}  "
                  f"{res['max_dd']:>7.3f}  {res['calmar']:>8.3f}  "
                  f"{res['sw_yr']:>6.2f}  {vs:>+18.3f}")

    # ── PART 3: Best combination (δ×lookback) under noise ─────────────────
    print("\n--- PART 3: Best (lookback, δ) under each noise level ---")
    print(f"{'σ_noise':>9}  {'lb':>4}  {'δ':>8}  {'Calmar':>8}  {'sw/yr':>6}")
    for sigma in NOISE_STDS:
        noisy = _add_noise(base_rets, sigma, NOISE_SEED)
        best = None
        for lb in LOOKBACK_GRID:
            for delta in [0.0, 5.0, 15.0, 30.0]:
                res = _simulate(noisy, noisy, rates_r, rwa_r, lookback=lb, delta=delta)
                if best is None or res["calmar"] > best["calmar"]:
                    best = {**res, "lb": lb, "delta": delta}
        print(f"{sigma*100:>8.1f}%  {best['lb']:>4}  {best['delta']:>8.1f}  "
              f"{best['calmar']:>8.3f}  {best['sw_yr']:>6.2f}")

    # ── PART 4: Per-crisis breakdown (zero noise, compare lookbacks) ───────
    print("\n--- PART 4: Per-crisis DD — does longer lookback hurt crisis protection? ---")
    known_static = {"eth_crash_2024_08": -0.64, "usde_unwind_2025_10": -2.11,
                    "rseth_depeg_2026_04": -0.17}
    print(f"{'crisis':>30}  {'static#3':>8}", end="")
    for lb in [5, 10, 20, 40]:
        print(f"  {'lb='+str(lb):>8}", end="")
    print()
    for w in STRESS_WINDOWS:
        k = str(w["key"])
        print(f"{k:>30}  {known_static.get(k,'?'):>8}", end="")
        for lb in [5, 10, 20, 40]:
            bd = _crisis_dd(dates, base_rets, base_rets, rates_r, rwa_r,
                            lookback=lb, delta=0.0)
            print(f"  {bd.get(k, 0.0):>8.3f}", end="")
        print()

    # ── OOS check ─────────────────────────────────────────────────────────
    oos_start = "2026-01-01"
    oos_idxs = [i for i, d in enumerate(dates) if d >= oos_start]
    if oos_idxs:
        oi = oos_idxs[0]
        oos_r = base_rets[oi:]
        oos_rates = rates_r[oi:]
        oos_rwa = rwa_r[oi:]
        print(f"\n--- OOS (2026+, {len(oos_r)} days, calm period, zero noise) ---")
        for lb in [10, 20, 40]:
            r = _simulate(oos_r, oos_r, oos_rates, oos_rwa, lookback=lb, delta=0.0)
            print(f"  lb={lb}: Calmar {r['calmar']}  sw/yr {r['sw_yr']}")
        oos_noisy_05 = _add_noise(oos_r, 0.005, NOISE_SEED)
        r_k = _simulate(oos_noisy_05, oos_noisy_05, oos_rates, oos_rwa, lookback=10, delta=0.0)
        r_l = _simulate(oos_noisy_05, oos_noisy_05, oos_rates, oos_rwa, lookback=40, delta=0.0)
        print(f"  lb=10, σ=0.5% noise: Calmar {r_k['calmar']}  sw/yr {r_k['sw_yr']}")
        print(f"  lb=40, σ=0.5% noise: Calmar {r_l['calmar']}  sw/yr {r_l['sw_yr']}")

    # ── Honest verdict ─────────────────────────────────────────────────────
    print("\n--- HONEST VERDICT (backtest/synthetic, evidence L0) ---")
    # Collect key numbers for verdict
    noisy_k005 = _add_noise(base_rets, 0.005, NOISE_SEED)
    kn05_lb10 = _simulate(noisy_k005, noisy_k005, rates_r, rwa_r, lookback=10, delta=0.0)
    kn05_lb40 = _simulate(noisy_k005, noisy_k005, rates_r, rwa_r, lookback=40, delta=0.0)
    kn05_lb40d15 = _simulate(noisy_k005, noisy_k005, rates_r, rwa_r, lookback=40, delta=15.0)
    kn05_lb10d30 = _simulate(noisy_k005, noisy_k005, rates_r, rwa_r, lookback=10, delta=30.0)

    print(f"\n  KEY NUMBERS (σ=0.5% daily noise):")
    print(f"  KODS #15 (lb=10, δ=0):     Calmar {kods_base['calmar']}  sw/yr {kods_base['sw_yr']}"
          f"  [ZERO noise reference]")
    print(f"  KODS (lb=10, δ=0):         Calmar {kn05_lb10['calmar']}  sw/yr {kn05_lb10['sw_yr']}"
          f"  [under 0.5% noise]")
    print(f"  NRK (lb=40, δ=0):          Calmar {kn05_lb40['calmar']}  sw/yr {kn05_lb40['sw_yr']}"
          f"  [longer lookback, under 0.5% noise]")
    print(f"  NRK (lb=40, δ=15):         Calmar {kn05_lb40d15['calmar']}  sw/yr {kn05_lb40d15['sw_yr']}"
          f"  [lookback+hysteresis, 0.5% noise]")
    print(f"  NRK (lb=10, δ=30):         Calmar {kn05_lb10d30['calmar']}  sw/yr {kn05_lb10d30['sw_yr']}"
          f"  [hysteresis only, 0.5% noise]")

    print()
    print("  Caveats (mandatory):")
    print("  (a) Gaussian noise ≠ real DeFi noise (fat tails, autocorrelation).")
    print("  (b) Fixture σ²=0 in calm: under any Gaussian noise, calm-period")
    print("      Kelly = α×μ_carry/σ_noise² >> any practical δ. Hysteresis")
    print("      only activates when Kelly oscillates near ±δ — which only")
    print("      happens at the Kelly-ratio scale, NOT fraction-of-return scale.")
    print("  (c) Single seed=42: specific noise realization may be atypical.")
    print("  (d) OOS is calm period: doesn't test crisis-detection degradation.")
    print("  (e) Evidence level: L0. NOT live results.")
    print()
    print("  REGISTRY ENTRY: see docs/DYNAMIC_LEVERAGE_GUARDIAN.md '#20'")
    print("=" * 72)


if __name__ == "__main__":
    main()
