#!/usr/bin/env python3
"""
scripts/edge_asymmetric_lookback_kelly.py — Idea #21: Asymmetric Lookback Kelly (ALK)

NOVEL EDGE IDEA #21 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  KODS #15 (Calmar-leader, 4.55) uses the SAME lookback window for BOTH the
  de-risk decision (exit) AND the re-entry decision. This conflates two
  economically distinct decisions:

    EXIT  (de-risk):  should be SLOWER — avoid whipsaw from 1-2-day noise spikes.
                      High lookback → more days needed to bring μ_rolling negative.
    RE-ENTRY:         should be FASTER — capture post-crisis carry as soon as the
                      regime clears. Low lookback → crisis days roll out of window
                      sooner → μ turns positive → re-invest.

  The structural gap in the registry: KODS was swept on lookback ∈ {10, 20, 30}
  but never tested (a) lookback=5 (fastest re-entry), or (b) DIFFERENT lookbacks
  for exit vs re-entry ("hysteretic" controller).

MECHANISM — HYSTERESIS STATE MACHINE
  Two states: IN_MARKET / DERISKED. Two separate Kelly signals:

    f_exit(t)   = (μ_exit − r_f)  / σ²_exit   [lookback_exit  days, causal]
    f_entry(t)  = (μ_entry − r_f) / σ²_entry  [lookback_entry days, causal]

    IN_MARKET   → if f_exit(t) < 0:   transition to DERISKED
    DERISKED    → if f_entry(t) > 0:  transition to IN_MARKET

  When IN_MARKET:  allocation = min(alpha × max(0, f_exit), max_risky) → same as KODS
  When DERISKED:   allocation = 0%  sUSDe (safe-leg only)

  Symmetric case (lookback_exit == lookback_entry): identical to KODS.

WHY RE-ENTRY IS FASTER WITH SMALLER lookback_entry
  Fixture has geometric front-loading: day-0 of USDe-unwind ≈ −4.5%, day-1 ≈ −2.2%,
  day-8+ already positive.  With lookback_entry = 5:
    Day 12 of crisis window: buffer[5] = [days 7-11], μ > r_f → RE-ENTER.
  With KODS lookback = 10:
    Day 18: buffer[10] = [days 8-17], μ > r_f → RE-ENTER (6 extra carry days).
  Same for ETH crash (+7d) and rsETH depeg (+9d).

WHY EXIT LOOKBACK DOESN'T MATTER ON THIS FIXTURE (honest caveat)
  Day-0 crisis hit is so large (−4.5% for USDe-unwind) that even a 30-day buffer
  returns μ < 0 → both short and long exit lookbacks fire on day 1.  The
  "avoid-whipsaw" benefit of long exit lookback is not testable here
  (fixture has zero calm-period variance → no false positives).

PARAMETERS SWEPT
  lookback_exit  ∈ {5, 10, 20, 30}
  lookback_entry ∈ {5, 10, 15, 20}  (only tested when <= lookback_exit, or separately)
  max_risky      ∈ {0.25, 0.40}
  alpha          = 0.1  (fractional Kelly; same as KODS best per registry #15)

BASELINES
  static #3:   Calmar ~2.03 (fixed 25/50/25)
  KODS #15:    Calmar ~4.55 (lookback=10, alpha=0.1, max_risky=0.25, symmetric)

SAFE-LEG SPLIT (identical to KODS)
  rates = (1 − f_active) × 2/3,  RWA = (1 − f_active) × 1/3

HONEST CAVEATS
  (a) Fixture is clean: no calm-period variance → no false exits → exit lookback
      doesn't affect de-risk timing (it always fires on day 1 of any crisis).
      The "avoid-whipsaw" benefit of asymmetry exists only with real market noise.
  (b) Smaller entry lookback = faster re-entry ONLY because day-8+ crisis days
      are already positive.  A multi-leg crisis (2nd shock within lookback_entry
      window) would cause premature re-entry.
  (c) Calmar improvement is modest (estimated +0.1-0.3 Calmar over KODS).
  (d) Crisis day-0 hit is UNAVOIDABLE for any causal method.
  (e) rates-carry + RWA = smooth synthetic (same caveat as #3–#20).
  (f) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

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
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants (identical to KODS #15 for apples-to-apples) ──────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT   = 3.31
MIN_VAR       = 1e-10      # same floor as KODS (avoids div-by-zero in calm)
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0

WEIGHTS_STATIC = [0.25, 0.50, 0.25]   # sUSDe / rates / RWA

OOS_SPLIT = "2025-06-01"   # consistent with #11/#15/#18 OOS boundary


# ── data loading (identical to KODS) ────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="alk_"))
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


def _kelly_f(window: List[float]) -> float:
    """Causal Kelly fraction from a return window. Returns raw f* (may be negative)."""
    n = len(window)
    if n < 2:
        return WEIGHTS_STATIC[0]  # warmup: static #3 default
    mu = sum(window) / n
    sq_dev = sum((r - mu) ** 2 for r in window)
    sigma2 = max(sq_dev / (n - 1), MIN_VAR)
    excess = mu - RATES_DAILY
    return excess / sigma2


# ── ALK engine ───────────────────────────────────────────────────────────────

def _alk_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    lookback_exit: int,
    lookback_entry: int,
    alpha: float,
    max_risky: float,
) -> Tuple[List[float], Dict[str, float]]:
    """
    Hysteretic Kelly controller:
      - IN_MARKET  : use buffer[-lookback_exit:] to compute exit signal.
                     If f_exit < 0 → transition to DERISKED.
      - DERISKED   : use buffer[-lookback_entry:] to compute entry signal.
                     If f_entry > 0 → transition to IN_MARKET.
    Symmetric case (lookback_exit == lookback_entry) == KODS.
    """
    buf: List[float] = []   # always collects sUSDe returns (causal)
    eq = 100_000.0
    out = [eq]
    state = "IN_MARKET"
    kelly_fracs: List[float] = []
    transitions: List[Tuple[str, str]] = []   # (date, transition)

    for ds in dates:
        # ── compute signal from buffer (causal: does NOT include today's return) ─
        if state == "IN_MARKET":
            window = buf[-lookback_exit:] if len(buf) >= lookback_exit else buf
            if len(window) < 2:
                f_raw = WEIGHTS_STATIC[0]   # warmup
                f_active = f_raw
            else:
                f_raw = _kelly_f(window)
                if f_raw < 0:
                    state = "DERISKED"
                    transitions.append((ds, "EXIT→DERISKED"))
                    f_active = 0.0
                else:
                    f_active = min(alpha * f_raw, max_risky)
        else:   # DERISKED
            window = buf[-lookback_entry:] if len(buf) >= lookback_entry else buf
            if len(window) < 2:
                f_raw = 0.0
                f_active = 0.0
            else:
                f_raw = _kelly_f(window)
                if f_raw > 0:
                    state = "IN_MARKET"
                    transitions.append((ds, "ENTER←IN_MARKET"))
                    f_active = min(alpha * f_raw, max_risky)
                else:
                    f_active = 0.0

        kelly_fracs.append(f_active)

        # ── portfolio weights ─────────────────────────────────────────────────
        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)

        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw    * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)

        buf.append(r_susde.get(ds, 0.0))

    avg_frac  = sum(kelly_fracs) / len(kelly_fracs) if kelly_fracs else 0.0
    zero_days = sum(1 for f in kelly_fracs if f < 1e-6)
    return out, {
        "avg_risky_pct": avg_frac * 100.0,
        "zero_risky_days": zero_days,
        "transitions": transitions,
    }


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


# ── metrics ──────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Dict[str, float]:
    if len(equity) < 2:
        return {"apy": 0.0, "max_dd": 0.0, "calmar": 0.0}
    start, end = equity[0], equity[-1]
    n_days = len(equity) - 1
    apy = ((end / start) ** (365.0 / n_days) - 1.0) * 100.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)
    max_dd_pct = max_dd * 100.0
    calmar = apy / max_dd_pct if max_dd_pct > 1e-6 else float("inf")
    return {"apy": apy, "max_dd": max_dd_pct, "calmar": calmar}


def _crisis_dd(
    dates: List[str],
    equity: List[float],
    window_key: str,
) -> float:
    """Max drawdown inside the named stress window (peak-to-trough, equity index)."""
    for w in STRESS_WINDOWS:
        if str(w["key"]) == window_key:
            lo = str(w["date_from"])
            hi = str(w["date_to"])
            break
    else:
        return 0.0
    # equity index i corresponds to AFTER processing dates[i-1]
    date_to_idx = {d: i + 1 for i, d in enumerate(dates)}
    peak = None
    max_dd = 0.0
    for d in dates:
        if lo <= d <= hi:
            i = date_to_idx[d]
            v = equity[i]
            if peak is None:
                peak = equity[i - 1]   # value just before window
            peak = max(peak, v)
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _oos_metrics(dates: List[str], equity: List[float], split: str) -> Dict[str, float]:
    split_dates = [d for d in dates if d >= split]
    if len(split_dates) < 2:
        return {"apy": 0.0, "max_dd": 0.0, "calmar": 0.0}
    i0 = dates.index(split_dates[0])
    eq_oos = equity[i0:]
    return _metrics(eq_oos)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("IDEA #21 — Asymmetric Lookback Kelly (ALK)")
    print("EVIDENCE LEVEL: L0 (backtest/synthetic fixture). NOT live results.")
    print("=" * 70)

    # ── load data ────────────────────────────────────────────────────────────
    print("\nLoading fixture data...")
    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)
    print(f"  {len(dates)} trading days  ({dates[0]} .. {dates[-1]})")

    # ── BASELINE: static #3 ───────────────────────────────────────────────────
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
    m_static  = _metrics(eq_static)

    # ── BASELINE: KODS #15 reference (symmetric, lookback=10, alpha=0.1) ──────
    eq_kods, kods_stats = _alk_equity(
        dates, r_susde, r_rates, r_rwa,
        lookback_exit=10, lookback_entry=10,
        alpha=0.1, max_risky=0.25,
    )
    m_kods = _metrics(eq_kods)

    print("\n── BASELINES ──────────────────────────────────────────────────────")
    print(f"  static #3  (25/50/25 fixed):  APY {m_static['apy']:.2f}%  "
          f"maxDD {m_static['max_dd']:.2f}%  Calmar {m_static['calmar']:.2f}")
    print(f"  KODS #15   (lkb=10, sym):     APY {m_kods['apy']:.2f}%  "
          f"maxDD {m_kods['max_dd']:.2f}%  Calmar {m_kods['calmar']:.2f}")
    print(f"    (transitions: {kods_stats['transitions']})")

    # ── SWEEP: symmetric Kelly with lookback ∈ {5, 10, 20, 30} ───────────────
    print("\n── SYMMETRIC KELLY (exit == entry lookback) — extend KODS sweep ──")
    print(f"  {'lkb':>6}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>7}  "
          f"{'OOS Calmar':>10}  {'zero_days':>9}")

    best_sym: Optional[Tuple[float, int, float]] = None   # (calmar, lkb, apy)

    for lkb in [5, 10, 20, 30]:
        eq, stats = _alk_equity(
            dates, r_susde, r_rates, r_rwa,
            lookback_exit=lkb, lookback_entry=lkb,
            alpha=0.1, max_risky=0.25,
        )
        m = _metrics(eq)
        oos = _oos_metrics(dates, eq, OOS_SPLIT)
        oos_cal = oos["calmar"]
        oos_str = f"{oos_cal:.2f}" if oos_cal < 1e6 else "∞"
        cal_str = f"{m['calmar']:.2f}" if m['calmar'] < 1e6 else "∞"
        marker = " ◄ NEW" if lkb == 5 else ("  (KODS ref)" if lkb == 10 else "")
        print(f"  lkb={lkb:>2}:  APY {m['apy']:>6.2f}%  "
              f"maxDD {m['max_dd']:>5.2f}%  Calmar {cal_str:>7}  "
              f"OOS {oos_str:>9}  zeros {stats['zero_risky_days']:>4}  {marker}")
        if m['calmar'] > (best_sym[0] if best_sym else -1):
            best_sym = (m['calmar'], lkb, m['apy'])

    # ── SWEEP: asymmetric (different exit vs entry lookbacks) ─────────────────
    print("\n── ASYMMETRIC ALK (exit_lkb ≠ entry_lkb) ─────────────────────────")
    print(f"  {'exit':>5}  {'entry':>5}  {'APY%':>7}  {'maxDD%':>7}  "
          f"{'Calmar':>7}  {'OOS Calmar':>10}  {'zeros':>5}")

    configs = [
        # (exit_lkb, entry_lkb)
        (10,  5),
        (20,  5),
        (20, 10),
        (30,  5),
        (30, 10),
        (30, 20),
    ]

    best_alk: Optional[Tuple[float, int, int, float]] = None  # (calmar, ex, en, apy)

    for (ex, en) in configs:
        eq, stats = _alk_equity(
            dates, r_susde, r_rates, r_rwa,
            lookback_exit=ex, lookback_entry=en,
            alpha=0.1, max_risky=0.25,
        )
        m   = _metrics(eq)
        oos = _oos_metrics(dates, eq, OOS_SPLIT)
        oos_cal = oos["calmar"]
        oos_str = f"{oos_cal:.2f}" if oos_cal < 1e6 else "∞"
        cal_str = f"{m['calmar']:.2f}" if m['calmar'] < 1e6 else "∞"
        print(f"  ex={ex:>2} en={en:>2}:  APY {m['apy']:>6.2f}%  "
              f"maxDD {m['max_dd']:>5.2f}%  Calmar {cal_str:>7}  "
              f"OOS {oos_str:>9}  zeros {stats['zero_risky_days']:>4}")
        if m['calmar'] > (best_alk[0] if best_alk else -1):
            best_alk = (m['calmar'], ex, en, m['apy'])

    # ── SWEEP: max_risky=0.40 for the best asymmetric ─────────────────────────
    print("\n── BEST ASYMMETRIC with max_risky=0.40 ────────────────────────────")
    for (ex, en) in [(20, 5), (30, 5)]:
        eq, stats = _alk_equity(
            dates, r_susde, r_rates, r_rwa,
            lookback_exit=ex, lookback_entry=en,
            alpha=0.1, max_risky=0.40,
        )
        m   = _metrics(eq)
        oos = _oos_metrics(dates, eq, OOS_SPLIT)
        oos_cal = oos["calmar"]
        oos_str = f"{oos_cal:.2f}" if oos_cal < 1e6 else "∞"
        cal_str = f"{m['calmar']:.2f}" if m['calmar'] < 1e6 else "∞"
        print(f"  ex={ex} en={en} max_r=0.40:  APY {m['apy']:>6.2f}%  "
              f"maxDD {m['max_dd']:>5.2f}%  Calmar {cal_str:>7}  OOS {oos_str}")

    # ── PER-CRISIS BREAKDOWN (best asymmetric config) ────────────────────────
    best_ex, best_en = 20, 5
    eq_best, _ = _alk_equity(
        dates, r_susde, r_rates, r_rwa,
        lookback_exit=best_ex, lookback_entry=best_en,
        alpha=0.1, max_risky=0.25,
    )

    print(f"\n── PER-CRISIS DD (ALK ex={best_ex}/en={best_en} vs static #3 vs KODS #15) ─")
    print(f"  {'window':<25}  {'static DD':>9}  {'KODS DD':>8}  {'ALK DD':>7}  {'saved vs static':>15}")
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        label = str(w["label"])[:24]
        dd_s = _crisis_dd(dates, eq_static, key)
        dd_k = _crisis_dd(dates, eq_kods,  key)
        dd_a = _crisis_dd(dates, eq_best,  key)
        saved = dd_s - dd_a
        print(f"  {label:<25}  {dd_s:>8.3f}%  {dd_k:>7.3f}%  {dd_a:>6.3f}%  {saved:>+14.3f}pp")

    # ── RE-ENTRY TIMING ANALYSIS ──────────────────────────────────────────────
    print("\n── RE-ENTRY TIMING (how many crisis carry-days ALK recovers early) ──")
    for (ex, en) in [(10, 5), (20, 5), (30, 5)]:
        eq_a, st_a = _alk_equity(
            dates, r_susde, r_rates, r_rwa,
            lookback_exit=ex, lookback_entry=en,
            alpha=0.1, max_risky=0.25,
        )
        eq_k, st_k = _alk_equity(
            dates, r_susde, r_rates, r_rwa,
            lookback_exit=ex, lookback_entry=ex,
            alpha=0.1, max_risky=0.25,
        )
        m_a = _metrics(eq_a)
        m_k = _metrics(eq_k)
        print(f"  ALK ex={ex}/en={en}: APY {m_a['apy']:.2f}%  Calmar {m_a['calmar']:.2f}"
              f"  vs sym lkb={ex}: APY {m_k['apy']:.2f}%  Calmar {m_k['calmar']:.2f}"
              f"  → ΔAPY {m_a['apy']-m_k['apy']:+.3f}pp")

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    m_best = _metrics(eq_best)
    oos_best = _oos_metrics(dates, eq_best, OOS_SPLIT)
    print("\n── SUMMARY ─────────────────────────────────────────────────────────")
    print(f"  static #3           : APY {m_static['apy']:.2f}%  "
          f"maxDD {m_static['max_dd']:.2f}%  Calmar {m_static['calmar']:.2f}")
    print(f"  KODS #15 (sym lkb=10): APY {m_kods['apy']:.2f}%  "
          f"maxDD {m_kods['max_dd']:.2f}%  Calmar {m_kods['calmar']:.2f}")
    print(f"  ALK ex=20/en=5      : APY {m_best['apy']:.2f}%  "
          f"maxDD {m_best['max_dd']:.2f}%  Calmar {m_best['calmar']:.2f}  "
          f"OOS Calmar {oos_best['calmar']:.2f}")

    print("\n── HONEST CAVEATS ──────────────────────────────────────────────────")
    print("  (a) fixture clean: no calm noise → exit lookback doesn't affect")
    print("      false-positive rate (can't test whipsaw-avoidance benefit).")
    print("  (b) faster re-entry = real improvement in this fixture; risky in")
    print("      real markets if crisis has multiple legs (premature re-entry).")
    print("  (c) all numbers = backtest (bt), evidence L0 — NOT live results.")
    print("  (d) OOS period = calm (rsETH-depeg only crisis) → calm-OOS caveat.")
    print("  (e) rates-carry + RWA = smooth synthetic (same as #3–#20).")
    print()
    print("DONE — idea #21 ALK backtest complete.")


if __name__ == "__main__":
    main()
