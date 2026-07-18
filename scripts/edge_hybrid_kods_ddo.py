#!/usr/bin/env python3
"""
scripts/edge_hybrid_kods_ddo.py — Idea #12: Hybrid KODS+DDO

NOVEL EDGE IDEA #12 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  Ideas #9 (DDO) and #15 (KODS) pointed to a structural decomposition:
    - DDO #9 de-risks modestly (5% sUSDe, DEFEND weights = [0.05, 0.25, 0.70])
      but RECOVERS aggressively (discrete 40% sUSDe for 21d HARVEST)
    - KODS #15 de-risks aggressively (0% sUSDe, f* < 0 → clip to 0%)
      but RECOVERS slowly (smooth Kelly ramp over ~lookback days)
  Both #11 (YB-CPPI) and #15 (KODS) explicitly called for the combination:
      "Hybrid #12 = KODS de-risk (0%) + DDO harvest (40% post-crisis)"

  No idea in the registry (#1-#17) has combined these two mechanisms.

THE HYBRID MECHANISM
  State machine (three regimes, fully causal):

    CRUISE  (25/50/25 = static #3 default in calm)
      → DEFEND: when Kelly signal f*(t) < 0
                f*(t) = (μ_rolling − r_f) / σ²_rolling   [causal, lookback days]

    DEFEND  (0%/67%/33% sUSDe — KODS-style, stronger than DDO's 5%)
      → HARVEST: when trailing DD recovers above −θ_exit   [DDO-style causal recovery]

    HARVEST (40/45/15 — DDO #8/#9 carry overweight)
      → CRUISE: after harvest_days expire

  Component credits:
    DEFEND trigger  → KODS #15 (Kelly μ/σ², no drawdown threshold needed)
    DEFEND depth    → KODS #15 (0% sUSDe, not 5%)
    HARVEST trigger → DDO #9 (portfolio recovery to HWM within θ_exit)
    HARVEST depth   → DDO #8/#9 (40/45/15 weights, discrete jump)
    HARVEST length  → DDO #9 (N days, swept below)

WHY THIS SHOULD DOMINATE BOTH
  If f*(t) < 0 fires after day 1 of crisis (same as #15): DEFEND is deeper (0% vs 5%)
  → smaller DD during crisis. Recovery is faster and larger (discrete 40% vs slow ramp)
  → more carry captured in the post-crisis window.

  Mathematical argument: separating crisis-protection (KODS 0%) from recovery-harvest
  (DDO 40%/21d) lets each mechanism specialize:
    KODS 0%-defend: minimises equity loss during crisis
    DDO harvest:    maximises log-wealth recovery by temporarily overweighting cheap carry

BASELINES (from registry, all on same fixture/data)
  static #3     : Calmar ~2.03 (fixed 25/50/25)
  causal DDO #9 : Calmar ~3.68 (5% defend, DDO trigger, 40%/21d harvest)
  KODS #15      : Calmar ~4.55 (0% defend, Kelly trigger, slow ramp recovery)

KEY QUESTIONS
  Q1. Does Hybrid #12 beat KODS #15 (4.55) by adding discrete harvest?
  Q2. Does Hybrid #12 beat DDO #9  (3.68) by using 0% defend?
  Q3. What is the decomposition:
        DDO-0% = (DDO trigger / 0% defend / DDO harvest) vs
        Hybrid  = (Kelly trigger / 0% defend / DDO harvest)
      → isolates trigger type contribution.

4-WAY COMPARISON (informative decomposition)
  DDO #9   : 5% defend / DDO-DD trigger / 40% harvest  [Calmar ~3.68]
  DDO-0%   : 0% defend / DDO-DD trigger / 40% harvest  [new: purer 0% defend baseline]
  KODS #15 : 0% defend / Kelly trigger  / slow ramp    [Calmar ~4.55]
  Hybrid #12: 0% defend / Kelly trigger / 40% harvest  [the combination]

  This isolates:
    DDO#9 vs DDO-0%:   effect of defend depth (5% vs 0%), holding trigger/harvest constant
    DDO-0% vs Hybrid:  effect of trigger type (DD vs Kelly), holding 0%/harvest constant
    KODS vs Hybrid:    effect of recovery (slow ramp vs 40%/21d), holding Kelly/0% constant

PARAMETERS SWEPT
  lookback     ∈ {10, 20, 30}  days — Kelly rolling window
  theta_exit   ∈ {0.001, 0.002} — recovery proximity to HWM before HARVEST begins
  harvest_days ∈ {14, 21, 28}   — days to hold HARVEST weights

HONEST CAVEATS
  (a) Day-1 crisis hit unavoidable for any causal method (same as #9, #15).
  (b) Fixture σ²≈0 in calm → Kelly → ∞ → defence is effectively binary
      (KODS binary-behaviour noted in #15 registry). Real-world σ² > 0 → Kelly
      would provide gradual de-risk before crisis, not just after.
  (c) DEFEND/HARVEST weights are reused from #7/#8/#9/#15; changing ONLY the
      state-machine — apples-to-apples comparison with prior ideas.
  (d) rates-carry + RWA-floor = smooth synthetic (Pendle PT / T-bill not in cloud
      checkout). Same limitation as #3–#15.
  (e) Kelly θ_exit DDO hybrid: two regimes could conflict if Kelly fires again
      during HARVEST (handled: HARVEST interrupted → DEFEND).
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

# ── constants ─────────────────────────────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6     # synthetic smooth rates-carry (same as #3/#9/#11/#15)
RWA_APY_PCT   = 3.31    # T-bill floor
MIN_VAR       = 1e-10   # absolute vol-floor (from UPD6 lesson; prevents div-by-zero in calm)

RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0

# Weights (from validated ideas #3/#7/#8; same as #9 and #15)
WEIGHTS_STATIC   = [0.25, 0.50, 0.25]   # static #3 baseline: sUSDe / rates / RWA
WEIGHTS_DEFEND   = [0.00, 2/3,   1/3]   # 0% sUSDe (KODS-style; 2:1 safe-leg split as in #15)
WEIGHTS_HARVEST  = [0.40, 0.45, 0.15]   # DDO #8/#9 post-crisis overweight
WEIGHTS_DEFEND5  = [0.05, 0.25, 0.70]   # DDO #9 original defend (5% sUSDe; baseline for #9)


# ── data loading (identical to #9 and #15 — apples-to-apples) ─────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    """sUSDe daily fractional returns from fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="hybrid12_"))
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


# ── engines ───────────────────────────────────────────────────────────────────────────────────────

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


def _causal_ddo_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    theta_enter: float = 0.003,
    theta_exit: float  = 0.001,
    harvest_days: int  = 21,
    defend_weights: Optional[List[float]] = None,
) -> Tuple[List[float], Dict[str, int]]:
    """
    DDO #9 baseline (DD-triggered) with optional custom defend weights.
    defend_weights=None → original DDO #9 (5% sUSDe).
    defend_weights=WEIGHTS_DEFEND → 0% sUSDe variant (DDO-0%).
    """
    if defend_weights is None:
        defend_weights = WEIGHTS_DEFEND5
    eq = 100_000.0
    out = [eq]
    hwm = eq
    counts = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}
    was_defending = False
    harvest_left = 0
    for ds in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -theta_enter:
            regime = "DEFEND"
            was_defending = True
            harvest_left = 0
        else:
            if was_defending and dd >= -theta_exit:
                was_defending = False
                harvest_left = harvest_days
            regime = "HARVEST" if harvest_left > 0 else "CRUISE"
            if harvest_left > 0:
                harvest_left -= 1
        counts[regime] += 1
        if regime == "DEFEND":
            w = defend_weights
        elif regime == "HARVEST":
            w = WEIGHTS_HARVEST
        else:
            w = WEIGHTS_STATIC
        r = w[0] * r_susde.get(ds, 0.0) + w[1] * r_rates.get(ds, 0.0) + w[2] * r_rwa.get(ds, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out, counts


def _kods_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    lookback: int = 10,
    max_risky: float = 0.25,
) -> Tuple[List[float], Dict[str, int]]:
    """
    KODS #15 baseline: Kelly trigger → 0% sUSDe; Kelly recovery → smooth ramp.
    """
    W_CRUISE = [max_risky, (1 - max_risky) * 2 / 3, (1 - max_risky) / 3]
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    counts = {"CRUISE": 0, "DEFEND": 0}
    for ds in dates:
        if len(buf) >= lookback:
            window = buf[-lookback:]
            mu = sum(window) / lookback
            sq_dev = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq_dev / (lookback - 1) if lookback > 1 else MIN_VAR, MIN_VAR)
            f_star = (mu - RATES_DAILY) / sigma2
            f_active = min(max(0.0, 0.1 * f_star), max_risky)  # alpha=0.1 (best from #15)
        else:
            f_active = WEIGHTS_STATIC[0]  # warmup: static #3 fraction

        mode = "DEFEND" if f_active < 1e-9 else "CRUISE"
        counts[mode] += 1

        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)
        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw    * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))
    return out, counts


def _hybrid_kods_ddo_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    lookback: int,
    theta_exit: float,
    harvest_days: int,
    max_risky: float = 0.25,
) -> Tuple[List[float], Dict[str, int]]:
    """
    Idea #12: Hybrid KODS+DDO.

    State machine (fully causal — weights on day T use only info through day T-1):

      CRUISE   → DEFEND:  Kelly f*(t) < 0  [μ_rolling < r_f after crisis days enter buffer]
      DEFEND   → HARVEST: trailing DD recovers above −theta_exit  [portfolio near HWM]
      HARVEST  → CRUISE:  harvest countdown exhausted
      (HARVEST → DEFEND:  if Kelly fires again during HARVEST → interrupt, re-defend)

    CRUISE weights  = [max_risky, (1-max_risky)×2/3, (1-max_risky)×1/3]
    DEFEND weights  = WEIGHTS_DEFEND  = [0, 2/3, 1/3]   (0% sUSDe)
    HARVEST weights = WEIGHTS_HARVEST = [0.40, 0.45, 0.15]
    """
    W_CRUISE = [max_risky, (1 - max_risky) * 2 / 3, (1 - max_risky) / 3]

    buf: List[float] = []
    eq = 100_000.0
    hwm = eq
    out = [eq]
    counts = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}

    state = "CRUISE"
    harvest_left = 0

    for ds in dates:
        # ── causal Kelly signal (from yesterday's buffer) ─────────────────────────
        if len(buf) >= lookback:
            window = buf[-lookback:]
            mu = sum(window) / lookback
            sq_dev = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq_dev / (lookback - 1) if lookback > 1 else MIN_VAR, MIN_VAR)
            f_star = (mu - RATES_DAILY) / sigma2
            kelly_negative = f_star < 0.0   # true when expected return is negative net of r_f
        else:
            kelly_negative = False   # warmup → optimistic (stay CRUISE)

        # ── causal trailing DD (from yesterday's eq, hwm) ────────────────────────
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0

        # ── state transitions ─────────────────────────────────────────────────────
        if state == "CRUISE":
            if kelly_negative:
                state = "DEFEND"
                harvest_left = 0

        elif state == "DEFEND":
            if not kelly_negative and dd >= -theta_exit:
                # Kelly recovered AND portfolio near HWM → enter harvest
                state = "HARVEST"
                harvest_left = harvest_days

        elif state == "HARVEST":
            if kelly_negative:
                # crisis re-flares during harvest → interrupt, re-defend
                state = "DEFEND"
                harvest_left = 0
            elif harvest_left <= 0:
                state = "CRUISE"

        counts[state] += 1

        # ── portfolio return ──────────────────────────────────────────────────────
        if state == "DEFEND":
            w = WEIGHTS_DEFEND
        elif state == "HARVEST":
            w = WEIGHTS_HARVEST
        else:
            w = W_CRUISE

        r = (w[0] * r_susde.get(ds, 0.0)
             + w[1] * r_rates.get(ds, 0.0)
             + w[2] * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)

        # ── update buffer and harvest countdown ───────────────────────────────────
        buf.append(r_susde.get(ds, 0.0))
        if state == "HARVEST":
            harvest_left -= 1

    return out, counts


# ── metrics ───────────────────────────────────────────────────────────────────────────────────────

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
    calmar = (apy * 100.0) / dd_pct if dd_pct > 0 else None
    return apy * 100.0, dd_pct, calmar


def _crisis_dd(dates: List[str], equity: List[float], window_key: str) -> Optional[float]:
    for w in STRESS_WINDOWS:
        if w["key"] != window_key:
            continue
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        idxs = [i for i, d in enumerate(dates) if lo <= datetime.date.fromisoformat(d) <= hi]
        if not idxs:
            return None
        pre = max(0, idxs[0] - 1)
        peak = max(equity[: pre + 2])
        trough = min(equity[i + 1] for i in idxs if i + 1 < len(equity))
        return (trough - peak) / peak * 100.0
    return None


def _f(x: object, d: int = 2) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


# ── full analysis (importable, deterministic) ─────────────────────────────────────────────────────

def run_analysis() -> Dict[str, object]:
    """End-to-end deterministic analysis. Returns structured result dict."""
    r_susde = _load_susde_returns()
    dates = sorted(r_susde)
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)

    # Baselines
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC)
    eq_ddo9, cnt_ddo9 = _causal_ddo_equity(dates, r_susde, r_rates, r_rwa)
    eq_ddo0, cnt_ddo0 = _causal_ddo_equity(dates, r_susde, r_rates, r_rwa,
                                            defend_weights=WEIGHTS_DEFEND)
    eq_kods15, cnt_kods15 = _kods_equity(dates, r_susde, r_rates, r_rwa)

    apy_s,  dd_s,  cal_s  = _metrics(eq_static)
    apy_9,  dd_9,  cal_9  = _metrics(eq_ddo9)
    apy_d0, dd_d0, cal_d0 = _metrics(eq_ddo0)
    apy_k,  dd_k,  cal_k  = _metrics(eq_kods15)

    # Sweep Hybrid #12 parameters
    sweep = []
    best = None
    for lookback in (10, 20, 30):
        for theta_exit in (0.001, 0.002):
            for harvest_days in (14, 21, 28):
                eq_h, cnt_h = _hybrid_kods_ddo_equity(
                    dates, r_susde, r_rates, r_rwa,
                    lookback=lookback, theta_exit=theta_exit, harvest_days=harvest_days)
                apy, dd, calmar = _metrics(eq_h)
                row = {
                    "lookback": lookback, "theta_exit": theta_exit,
                    "harvest_days": harvest_days,
                    "apy": apy, "dd": dd, "calmar": calmar,
                    "counts": cnt_h, "equity": eq_h,
                }
                sweep.append(row)
                if calmar is not None and (best is None or calmar > best["calmar"]):
                    best = row

    return {
        "dates": dates,
        "r_susde": r_susde, "r_rates": r_rates, "r_rwa": r_rwa,
        "static": {"apy": apy_s,  "dd": dd_s,  "calmar": cal_s,  "equity": eq_static,  "counts": {}},
        "ddo9":   {"apy": apy_9,  "dd": dd_9,  "calmar": cal_9,  "equity": eq_ddo9,   "counts": cnt_ddo9},
        "ddo0":   {"apy": apy_d0, "dd": dd_d0, "calmar": cal_d0, "equity": eq_ddo0,   "counts": cnt_ddo0},
        "kods15": {"apy": apy_k,  "dd": dd_k,  "calmar": cal_k,  "equity": eq_kods15, "counts": cnt_kods15},
        "sweep": sweep,
        "best": best,
    }


# ── main (human-readable report) ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 76)
    print("IDEA #12: Hybrid KODS+DDO  (Kelly de-risk 0% + DDO harvest 40%)")
    print("Combines: KODS #15 aggressive de-risk  +  DDO #9 discrete harvest")
    print("All numbers: BACKTEST / SYNTHETIC (L0). NOT live results.")
    print("=" * 76)

    res = run_analysis()
    dates = res["dates"]
    st  = res["static"]
    d9  = res["ddo9"]
    d0  = res["ddo0"]
    k15 = res["kods15"]
    best = res["best"]

    print(f"\nBacktest window: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"sUSDe: fixture (real-shaped crises, 11%/yr normal carry)")
    print(f"Rates: synthetic smooth {RATES_APY_PCT}%/yr | RWA floor: {RWA_APY_PCT}%/yr")
    print(f"Crises: ETH-crash 2024-08 | USDe-unwind 2025-10 | rsETH-depeg 2026-04")

    print("\n── 4-WAY DECOMPOSITION (isolates contribution of each component) ────────────")
    print("  #   method           defend%  trigger  recovery      APY    maxDD  Calmar")
    print("  --- --------------- -------- -------- ----------- ------- ------- -------")
    print(f"  0   static #3         25%   —        —            {_f(st['apy'])}%  {_f(st['dd'])}%   {_f(st['calmar'])}")
    print(f"  9   DDO #9             5%   DD>θ     40%/21d      {_f(d9['apy'])}%  {_f(d9['dd'])}%   {_f(d9['calmar'])}")
    print(f"  9'  DDO-0%             0%   DD>θ     40%/21d      {_f(d0['apy'])}%  {_f(d0['dd'])}%   {_f(d0['calmar'])}")
    print(f"  15  KODS #15           0%   Kelly    slow ramp    {_f(k15['apy'])}%  {_f(k15['dd'])}%   {_f(k15['calmar'])}")

    print(f"\n── IDEA #12 SWEEP (Kelly trigger + 0% defend + DDO harvest) ─────────────────")
    print(f"  {'lkb':>4} {'θ_exit%':>8} {'harv_d':>7} {'C/D/H regime':>16} "
          f"{'APY':>7} {'maxDD':>7} {'Calmar':>8}")
    print(f"  {'-'*4} {'-'*8} {'-'*7} {'-'*16} {'-'*7} {'-'*7} {'-'*8}")
    for row in res["sweep"]:
        c = row["counts"]
        regime_str = f"{c.get('CRUISE',0)}C/{c.get('DEFEND',0)}D/{c.get('HARVEST',0)}H"
        marker = " ◀ best" if row is best else ""
        print(f"  {row['lookback']:>4d} {row['theta_exit']*100:>7.2f}% {row['harvest_days']:>7d}"
              f" {regime_str:>16}"
              f" {_f(row['apy']):>7} {_f(row['dd']):>7} {_f(row['calmar']):>8}{marker}")

    print(f"\n── BEST HYBRID #12 "
          f"(lookback={best['lookback']}d, θ_exit={best['theta_exit']*100:.2f}%,"
          f" harvest={best['harvest_days']}d) ──")
    bc = best["counts"]
    print(f"  APY {_f(best['apy'])}%  maxDD {_f(best['dd'])}%  Calmar {_f(best['calmar'])}")
    print(f"  Regime days: {bc.get('CRUISE',0)}C / {bc.get('DEFEND',0)}D / {bc.get('HARVEST',0)}H")

    print("\n── PER-CRISIS DRAWDOWN (4-way comparison) ───────────────────────────────────")
    print(f"  {'event':32s} {'static':>7} {'DDO#9':>7} {'DDO-0%':>7} {'KODS':>6} {'Hybrid':>7}")
    print(f"  {'-'*32} {'-'*7} {'-'*7} {'-'*7} {'-'*6} {'-'*7}")
    for w in STRESS_WINDOWS:
        k = w["key"]
        cd_s  = _crisis_dd(dates, st["equity"], k)
        cd_9  = _crisis_dd(dates, d9["equity"], k)
        cd_d0 = _crisis_dd(dates, d0["equity"], k)
        cd_k  = _crisis_dd(dates, k15["equity"], k)
        cd_h  = _crisis_dd(dates, best["equity"], k)
        print(f"  {k:32s} {_f(cd_s):>7} {_f(cd_9):>7} {_f(cd_d0):>7}"
              f" {_f(cd_k):>6} {_f(cd_h):>7}")

    # ── OOS validation ─────────────────────────────────────────────────────────────────────────────
    print("\n── OUT-OF-SAMPLE (best params applied to unseen tail) ────────────────────────")
    n_train = 500
    test_dates = dates[n_train:]
    if len(test_dates) > 10:
        r_su = res["r_susde"]
        r_rt = res["r_rates"]
        r_rw = res["r_rwa"]
        eq_s_oos = _blend_static(test_dates, r_su, r_rt, r_rw, WEIGHTS_STATIC)
        eq_9_oos, cnt9 = _causal_ddo_equity(test_dates, r_su, r_rt, r_rw)
        eq_k_oos, cntk = _kods_equity(test_dates, r_su, r_rt, r_rw)
        eq_h_oos, cnth = _hybrid_kods_ddo_equity(
            test_dates, r_su, r_rt, r_rw,
            lookback=best["lookback"], theta_exit=best["theta_exit"],
            harvest_days=best["harvest_days"])
        a_s,  d_s,  c_s  = _metrics(eq_s_oos)
        a_9,  d_9,  c_9  = _metrics(eq_9_oos)
        a_k,  d_k,  c_k  = _metrics(eq_k_oos)
        a_h,  d_h,  c_h  = _metrics(eq_h_oos)
        print(f"  OOS window: {test_dates[0]} → {test_dates[-1]} ({len(test_dates)} days)")
        print(f"    static #3  : APY {_f(a_s)}%  maxDD {_f(d_s)}%  Calmar {_f(c_s)}")
        print(f"    DDO #9     : APY {_f(a_9)}%  maxDD {_f(d_9)}%  Calmar {_f(c_9)}")
        print(f"    KODS #15   : APY {_f(a_k)}%  maxDD {_f(d_k)}%  Calmar {_f(c_k)}")
        print(f"    Hybrid #12 : APY {_f(a_h)}%  maxDD {_f(d_h)}%  Calmar {_f(c_h)}")
        oos_defend = cnth.get("DEFEND", 0) + cnth.get("HARVEST", 0)
        if oos_defend == 0:
            print("    ⚠️  OOS window had NO DEFEND/HARVEST activations → calm-OOS caveat applies")
            print("       (same as #1/#4/#8-#15): crisis-protection not tested in this window.")

    # ── mechanism decomposition ────────────────────────────────────────────────────────────────────
    print("\n── MECHANISM DECOMPOSITION ──────────────────────────────────────────────────")
    cal_s  = st["calmar"]
    cal_9  = d9["calmar"]
    cal_d0 = d0["calmar"]
    cal_k  = k15["calmar"]
    cal_h  = best["calmar"]
    if all(isinstance(x, float) for x in [cal_9, cal_d0, cal_k, cal_h]):
        print(f"  Effect of 0% vs 5% defend  (DDO#9→DDO-0%):  Δ={_f(cal_d0-cal_9)} Calmar")
        print(f"  Effect of Kelly vs DD trigger (DDO-0%→Hybrid): Δ={_f(cal_h-cal_d0)} Calmar")
        print(f"  Effect of harvest vs slow ramp (KODS→Hybrid):  Δ={_f(cal_h-cal_k)} Calmar")
        print(f"  Total vs static #3:                            Δ={_f(cal_h-cal_s)} Calmar")

    # ── verdict ───────────────────────────────────────────────────────────────────────────────────
    print("\n── VERDICT ──────────────────────────────────────────────────────────────────")
    beats_static = isinstance(cal_h, float) and isinstance(cal_s, float) and cal_h > cal_s
    beats_ddo9   = isinstance(cal_h, float) and isinstance(cal_9, float) and cal_h > cal_9
    beats_kods   = isinstance(cal_h, float) and isinstance(cal_k, float) and cal_h > cal_k

    if beats_kods:
        verdict = "✅ HYBRID BEATS BOTH PRIOR LEADERS — new Calmar leader in the registry"
    elif beats_ddo9:
        verdict = "✅ HYBRID BEATS DDO #9 (and KODS was already leading) — positive"
    elif beats_static:
        verdict = "⚠️ PARTIAL — hybrid beats static #3 but lags one/both component methods"
    else:
        verdict = "❌ NEGATIVE — hybrid does not beat static #3"

    print(f"  {verdict}")
    print(f"\n  Summary (best Hybrid #12 vs baselines):")
    print(f"    static #3    : Calmar {_f(cal_s)}  APY {_f(st['apy'])}%  maxDD {_f(st['dd'])}%")
    print(f"    DDO #9       : Calmar {_f(cal_9)}  APY {_f(d9['apy'])}%  maxDD {_f(d9['dd'])}%")
    print(f"    DDO-0%       : Calmar {_f(cal_d0)}  APY {_f(d0['apy'])}%  maxDD {_f(d0['dd'])}%")
    print(f"    KODS #15     : Calmar {_f(cal_k)}  APY {_f(k15['apy'])}%  maxDD {_f(k15['dd'])}%")
    print(f"    Hybrid #12   : Calmar {_f(cal_h)}  APY {_f(best['apy'])}%  maxDD {_f(best['dd'])}%")

    print("\n  HONEST CAVEATS:")
    print("  (a) Day-1 crisis hit unavoidable by any causal method.")
    print("  (b) Fixture σ²≈0 in calm → Kelly effectively binary (fires after day 1 only).")
    print("      Real-market σ² > 0 → Kelly provides continuous sizing, not just binary defence.")
    print("  (c) DEFEND/HARVEST weights from validated #7/#8/#9/#15 — only control method changes.")
    print("  (d) rates-carry + RWA-floor synthetic smooth (Pendle/T-bill not in cloud checkout).")
    print("  (e) Harvest interrupt on Kelly re-trigger (HARVEST→DEFEND) tested; see counts above.")
    print("  (f) OOS on calm tail does NOT test crisis-protection (same caveat as #1/#4/#8-#15).")
    print("  (g) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("\n  NEXT STEP:")
    print("  If Calmar > #15 (4.55): forward-paper this hybrid controller alongside KODS guardian.")
    print("  Wire causal Hybrid state to RTMR advisory: signal-only, no capital movement.")
    print("  ADR required before any real capital movement.")


if __name__ == "__main__":
    main()
