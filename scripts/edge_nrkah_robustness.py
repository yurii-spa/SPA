#!/usr/bin/env python3
"""
scripts/edge_nrkah_robustness.py — Idea #31 (Hardening of #26):
NRK-AH Multi-Seed & Noise-Model Robustness Validator (NMRV)

CONTEXT (Idea #26 NRK-AH)
  scripts/edge_noise_robust_kelly.py showed that adding a Schmitt-trigger
  hysteresis band δ=1 (Kelly-ratio units) around KODS under σ=0.5%/day
  Gaussian noise improves Calmar from 4.55 (KODS) to 5.91 (+30%). Registered
  as the BEST result in the registry. BUT:

  Caveat (c) from #26: "Single seed=42: specific noise realization may be
  atypical." The Part 2/3 results already showed Calmar 571/89 artefacts from
  seed=42 at specific configs. → The CRITICAL OPEN QUESTION:

  "Is Calmar 5.91 robust across seeds, or is seed=42 a lucky draw?"

WHAT THIS IDEA (HARDENING #31) TESTS
  1. MULTI-SEED SWEEP (200 seeds, iid Gaussian, σ=0.5%/day):
     Report P10/P50/P90 of Calmar for δ∈{0, 0.5, 1, 2, 5, 10}.
     Answer: Is δ=1 the winner at the MEDIAN (not just seed=42)?

  2. AUTOCORRELATED NOISE (AR(1), ρ=0.1, 0.3, 0.5, σ_innov=0.5%/day):
     Real DeFi funding noise has persistence (AR process). Test same δ sweep.
     Answer: Does hysteresis help MORE under autocorrelation, or less?

  3. NOISE-LEVEL ROBUSTNESS (σ=0.1%, 0.5%, 1.0% at best δ):
     Report median Calmar vs δ=0 baseline across noise levels.

OUTCOME POSSIBILITIES (pre-declared, no look-ahead)
  A. δ=1 wins at P50 across seeds → confirm registry #26 edge, flag for
     forward paper.
  B. Calmar 5.91 was seed-42 luck (P50 << 5.91) → DEMOTE #26 Calmar
     headline, keep mechanism but lower confidence.
  C. AR(1) changes the picture → AR(1) section informs real-world relevance.

INVARIANTS
  LLM_FORBIDDEN · stdlib-only · deterministic (seeded rng) · no execution import
  no fabricated data · IS_ADVISORY=True · evidence level L0

HONEST CAVEATS (mandatory)
  (a) iid and AR(1) Gaussian noise ≠ real DeFi fat-tailed noise.
  (b) Fixture σ²=0 in calm: noise dominates Kelly ratio denominator.
  (c) Evidence L0 (backtest/synthetic). NOT live results.
  (d) maxDD near 0 on OOS calm period → Calmar → ∞ (degenerate ratio);
      flag any Calmar > 100 as likely degenerate.
  (e) 200 seeds × 6 δ-values × 4 AR-rho = many runs; runtime ~60s.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx   # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld     # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RATES_APY   = 4.6
RWA_APY     = 3.31
RATES_DAILY = RATES_APY / 100.0 / 365.0
RWA_DAILY   = RWA_APY   / 100.0 / 365.0
RF_DAILY    = RATES_DAILY
MAX_RISKY   = 0.25
ALPHA_KELLY = 0.1
MIN_VAR     = 1e-10
LOOKBACK    = 10          # KODS #15 reference lookback

N_SEEDS         = 200
SIGMA_MAIN      = 0.005   # 0.5 %/day (winning #26 noise level)
DELTA_GRID      = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]   # Kelly-ratio units
AR_RHOS         = [0.0, 0.1, 0.3, 0.5]               # AR(1) persistence
NOISE_STDS      = [0.001, 0.005, 0.010]               # 0.1%, 0.5%, 1.0%/day
MAX_DEGENERATE  = 100.0   # Calmar > this → flag as degenerate


# ── data loading ──────────────────────────────────────────────────────────────
def _load_susde() -> Tuple[List[str], List[float]]:
    tmp = Path(tempfile.mkdtemp(prefix="nmrv_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None:
        raise RuntimeError("susde_dn not in fixture")
    eq_map = {}
    for p in s.backtest.series:
        d = p.get("date")
        e = p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq_map[d] = float(e)
    dates_sorted = sorted(eq_map)
    rets = [eq_map[dates_sorted[i]] / eq_map[dates_sorted[i - 1]] - 1.0
            for i in range(1, len(dates_sorted)) if eq_map.get(dates_sorted[i - 1])]
    return dates_sorted[1:], rets


# ── noise generators ──────────────────────────────────────────────────────────
def _iid_noise(rets: List[float], sigma: float, seed: int) -> List[float]:
    if sigma == 0.0:
        return rets[:]
    rng = random.Random(seed)
    return [r + rng.gauss(0.0, sigma) for r in rets]


def _ar1_noise(rets: List[float], sigma_innov: float, rho: float, seed: int) -> List[float]:
    """AR(1) process: ε_t = ρ × ε_{t-1} + innovation, innovation ~ N(0, σ_innov)."""
    if sigma_innov == 0.0 and rho == 0.0:
        return rets[:]
    rng = random.Random(seed)
    noisy = []
    eps = 0.0
    for r in rets:
        innov = rng.gauss(0.0, sigma_innov)
        eps = rho * eps + innov
        noisy.append(r + eps)
    return noisy


# ── Kelly signal ──────────────────────────────────────────────────────────────
def _kelly(rets: List[float], t: int, lookback: int) -> float:
    window = rets[max(0, t - lookback): t]
    n = len(window)
    if n < 2:
        return float("inf")
    mu = sum(window) / n - RF_DAILY
    var = max(MIN_VAR, sum((r - (sum(window) / n)) ** 2 for r in window) / (n - 1))
    return (ALPHA_KELLY * mu) / var


# ── simulator ─────────────────────────────────────────────────────────────────
def _simulate(signal_rets: List[float], actual_rets: List[float],
              rates_r: List[float], rwa_r: List[float],
              lookback: int, delta: float) -> float:
    """Returns Calmar ratio (capped at MAX_DEGENERATE to flag degenerate cases)."""
    n = len(actual_rets)
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    state = "CRUISE"
    for t in range(n):
        kr = _kelly(signal_rets, t, lookback)
        if state == "CRUISE" and kr < -delta:
            state = "DEFEND"
        elif state == "DEFEND" and kr > delta:
            state = "CRUISE"
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
    if max_dd < 1e-9:
        return MAX_DEGENERATE
    calmar = cagr / max_dd
    return min(calmar, MAX_DEGENERATE)


def _static(rets: List[float], rates: List[float], rwa: List[float]) -> float:
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
    if max_dd < 1e-9:
        return MAX_DEGENERATE
    return min(cagr / max_dd, MAX_DEGENERATE)


# ── statistics helpers ────────────────────────────────────────────────────────
def _percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = pct / 100.0 * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _stats(data: List[float]) -> str:
    degens = sum(1 for x in data if x >= MAX_DEGENERATE)
    clean = [x for x in data if x < MAX_DEGENERATE]
    if not clean:
        return f"ALL-DEGEN({degens})"
    return (f"P10={_percentile(clean,10):.2f}  "
            f"P50={_percentile(clean,50):.2f}  "
            f"P90={_percentile(clean,90):.2f}  "
            f"mean={sum(clean)/len(clean):.2f}"
            + (f"  degen={degens}" if degens else ""))


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 76)
    print("Idea #31 (Hardening of #26): NRK-AH Multi-Seed Robustness Validator")
    print("EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("=" * 76)

    dates, base_rets = _load_susde()
    n = len(base_rets)
    rates_r = [RATES_DAILY] * n
    rwa_r   = [RWA_DAILY]   * n
    n_yrs   = n / 365.0

    print(f"\nFixture: {n} returns ({n_yrs:.2f} yrs)  {dates[0]}..{dates[-1]}")

    # ── Reference baselines (zero noise) ──────────────────────────────────
    s3_cal = _static(base_rets, rates_r, rwa_r)
    kods_cal = _simulate(base_rets, base_rets, rates_r, rwa_r, lookback=LOOKBACK, delta=0.0)
    kods_d1_cal = _simulate(base_rets, base_rets, rates_r, rwa_r, lookback=LOOKBACK, delta=1.0)
    print(f"\nBaselines (ZERO noise, deterministic fixture):")
    print(f"  static #3:          Calmar {s3_cal:.3f}")
    print(f"  KODS #15 (δ=0):     Calmar {kods_cal:.3f}  (reference)")
    print(f"  NRK-AH (δ=1):       Calmar {kods_d1_cal:.3f}  "
          f"[ONLY meaningful if δ << Kelly_calm ≈ inf → no effect expected]")
    print(f"  Note: at zero noise, Kelly_calm→∞ so any δ is negligible → δ=0 = δ=1 here.")

    # ── PART 1: Multi-seed sweep (iid Gaussian, σ=0.5%) ──────────────────
    print(f"\n{'='*76}")
    print(f"PART 1: Multi-seed sweep  (N={N_SEEDS} seeds, iid Gaussian, σ={SIGMA_MAIN*100:.1f}%/day)")
    print(f"KEY QUESTION: Is Calmar 5.91 from seed=42 reproducible or a lucky draw?")
    print(f"{'='*76}")

    seed42_ref = {}
    for delta in DELTA_GRID:
        noisy42 = _iid_noise(base_rets, SIGMA_MAIN, 42)
        seed42_ref[delta] = _simulate(noisy42, noisy42, rates_r, rwa_r,
                                      lookback=LOOKBACK, delta=delta)

    all_calmars = {delta: [] for delta in DELTA_GRID}
    for seed in range(N_SEEDS):
        noisy = _iid_noise(base_rets, SIGMA_MAIN, seed)
        for delta in DELTA_GRID:
            c = _simulate(noisy, noisy, rates_r, rwa_r, lookback=LOOKBACK, delta=delta)
            all_calmars[delta].append(c)

    print(f"\n{'δ':>6}  {'seed42':>7}  {'P10':>7}  {'P50':>7}  {'P90':>7}  "
          f"{'mean':>7}  {'degen':>5}  {'vs δ=0 P50':>12}")
    kods_p50 = _percentile([x for x in all_calmars[0.0] if x < MAX_DEGENERATE], 50)
    for delta in DELTA_GRID:
        clean = [x for x in all_calmars[delta] if x < MAX_DEGENERATE]
        degen = sum(1 for x in all_calmars[delta] if x >= MAX_DEGENERATE)
        p10 = _percentile(clean, 10) if clean else 0.0
        p50 = _percentile(clean, 50) if clean else 0.0
        p90 = _percentile(clean, 90) if clean else 0.0
        mean = sum(clean)/len(clean) if clean else 0.0
        vs_kods = p50 - kods_p50
        s42 = seed42_ref.get(delta, 0.0)
        print(f"{delta:>6.1f}  {s42:>7.2f}  {p10:>7.2f}  {p50:>7.2f}  "
              f"{p90:>7.2f}  {mean:>7.2f}  {degen:>5}  {vs_kods:>+12.2f}")

    best_delta_by_p50 = max(DELTA_GRID,
                             key=lambda d: _percentile([x for x in all_calmars[d]
                                                        if x < MAX_DEGENERATE], 50))
    best_p50 = _percentile([x for x in all_calmars[best_delta_by_p50]
                            if x < MAX_DEGENERATE], 50)
    kods_seed42 = seed42_ref[0.0]
    print(f"\n  ANSWER to KEY QUESTION:")
    print(f"  seed=42 gave Calmar {seed42_ref[1.0]:.2f} at δ=1 vs KODS {kods_seed42:.2f}")
    print(f"  P50 across {N_SEEDS} seeds: δ=0 → {kods_p50:.2f}, "
          f"best-δ={best_delta_by_p50} → {best_p50:.2f}")
    if best_p50 > kods_p50 + 0.1:
        print(f"  ✅ SEED-ROBUST: P50 Calmar {best_p50:.2f} > KODS {kods_p50:.2f} "
              f"(+{best_p50-kods_p50:.2f}) at δ={best_delta_by_p50}")
    else:
        print(f"  ⚠️  NOT SEED-ROBUST: P50 Calmar {best_p50:.2f} ≈ KODS {kods_p50:.2f} "
              f"(+{best_p50-kods_p50:.2f}); seed=42 was likely atypical.")

    # ── PART 2: AR(1) noise (realistic DeFi autocorrelation) ─────────────
    print(f"\n{'='*76}")
    print("PART 2: AR(1) autocorrelated noise  (σ_innov=0.5%/day, ρ=persistence)")
    print("KEY QUESTION: Does hysteresis help more/less under autocorrelated noise?")
    print(f"{'='*76}")

    print(f"\n{'ρ':>6}  {'δ':>6}  {'P10':>7}  {'P50':>7}  {'P90':>7}  "
          f"{'mean':>7}  vs δ=0 P50")
    for rho in AR_RHOS:
        ar_calmars = {delta: [] for delta in [0.0, 1.0, 2.0, 5.0]}
        for seed in range(N_SEEDS):
            noisy = _ar1_noise(base_rets, SIGMA_MAIN, rho, seed)
            for delta in ar_calmars:
                c = _simulate(noisy, noisy, rates_r, rwa_r, lookback=LOOKBACK, delta=delta)
                ar_calmars[delta].append(c)
        ar_kods_clean = [x for x in ar_calmars[0.0] if x < MAX_DEGENERATE]
        ar_kods_p50 = _percentile(ar_kods_clean, 50) if ar_kods_clean else 0.0
        for delta in [0.0, 1.0, 2.0, 5.0]:
            clean = [x for x in ar_calmars[delta] if x < MAX_DEGENERATE]
            p10 = _percentile(clean, 10) if clean else 0.0
            p50 = _percentile(clean, 50) if clean else 0.0
            p90 = _percentile(clean, 90) if clean else 0.0
            mean = sum(clean)/len(clean) if clean else 0.0
            vs_kods = p50 - ar_kods_p50
            label = "iid" if rho == 0.0 else f"AR(ρ={rho})"
            prefix = f"  {label:>10}" if delta == 0.0 else f"  {'':>10}"
            print(f"{prefix}  δ={delta:<4.1f}  {p10:>7.2f}  {p50:>7.2f}  "
                  f"{p90:>7.2f}  {mean:>7.2f}  {vs_kods:>+9.2f}")

    # ── PART 3: Noise-level sensitivity of best δ at P50 ─────────────────
    print(f"\n{'='*76}")
    print("PART 3: Noise-level robustness  (best δ at each σ, median Calmar)")
    print(f"{'='*76}")

    print(f"\n{'σ_noise':>10}  {'δ=0 P50':>9}  {'best-δ':>7}  "
          f"{'best P50':>9}  {'Δ vs δ=0':>10}")
    for sigma in NOISE_STDS:
        sigma_calmars = {delta: [] for delta in DELTA_GRID}
        for seed in range(N_SEEDS):
            noisy = _iid_noise(base_rets, sigma, seed)
            for delta in DELTA_GRID:
                c = _simulate(noisy, noisy, rates_r, rwa_r, lookback=LOOKBACK, delta=delta)
                sigma_calmars[delta].append(c)
        kods_clean = [x for x in sigma_calmars[0.0] if x < MAX_DEGENERATE]
        kods_p50s = _percentile(kods_clean, 50) if kods_clean else 0.0
        best_d = max(DELTA_GRID,
                     key=lambda d: _percentile([x for x in sigma_calmars[d]
                                                if x < MAX_DEGENERATE], 50))
        best_c = [x for x in sigma_calmars[best_d] if x < MAX_DEGENERATE]
        best_p50s = _percentile(best_c, 50) if best_c else 0.0
        delta_vs = best_p50s - kods_p50s
        print(f"{sigma*100:>9.1f}%  {kods_p50s:>9.2f}  {best_d:>7.1f}  "
              f"{best_p50s:>9.2f}  {delta_vs:>+10.2f}")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print("SUMMARY — HONEST VERDICT (evidence L0, backtest/synthetic)")
    print(f"{'='*76}")
    kods_p50_summary = _percentile([x for x in all_calmars[0.0] if x < MAX_DEGENERATE], 50)
    best_p50_summary = _percentile([x for x in all_calmars[best_delta_by_p50]
                                    if x < MAX_DEGENERATE], 50)
    delta1_p50 = _percentile([x for x in all_calmars[1.0] if x < MAX_DEGENERATE], 50)
    delta1_p10 = _percentile([x for x in all_calmars[1.0] if x < MAX_DEGENERATE], 10)
    delta1_p90 = _percentile([x for x in all_calmars[1.0] if x < MAX_DEGENERATE], 90)
    print(f"\n  #26 NRK-AH seed=42 headline:  Calmar {seed42_ref[1.0]:.2f} at δ=1")
    print(f"  Seed-robust P50 at δ=1:       {delta1_p50:.2f}  "
          f"[P10={delta1_p10:.2f}, P90={delta1_p90:.2f}]")
    print(f"  KODS δ=0 P50:                 {kods_p50_summary:.2f}")
    print(f"  Best-δ P50:                   {best_p50_summary:.2f} at δ={best_delta_by_p50}")
    print()
    robust = (best_p50_summary > kods_p50_summary + 0.15)
    if robust:
        print("  VERDICT: NRK-AH edge IS seed-robust (P50 > KODS + 0.15).")
        print("  The headline Calmar from seed=42 may exceed the typical case,")
        print("  but the DIRECTIONAL edge (δ>0 beats δ=0) holds at median.")
        print("  → Forward paper recommendation remains valid for NRK-AH.")
        print("  → Report SEED-ROBUST P50 as honest headline (not seed-42 value).")
    else:
        print("  VERDICT: NRK-AH edge is NOT seed-robust (P50 ≈ KODS).")
        print("  Calmar 5.91 from seed=42 was an ATYPICAL draw.")
        print("  → DEMOTE #26 headline: remove 5.91 from forward-paper justification.")
        print("  → Mechanism (hysteresis) remains theoretically sound, but empirical")
        print("    support on fixture is weaker than one-seed result suggested.")
    print()
    print("  Caveats (mandatory):")
    print("  (a) iid + AR(1) Gaussian ≠ real DeFi fat-tailed autocorrelated noise.")
    print("  (b) σ²=0 in calm fixture makes noise dominate Kelly denominator.")
    print("  (c) Degenerate Calmar (maxDD→0 on calm OOS) capped at 100.")
    print("  (d) Evidence L0. NOT live results. IS_ADVISORY=True.")
    print("  (e) ADR before any capital movement.")
    print("=" * 76)


if __name__ == "__main__":
    main()
