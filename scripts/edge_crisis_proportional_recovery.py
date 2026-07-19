#!/usr/bin/env python3
"""
scripts/edge_crisis_proportional_recovery.py — Idea #18: Crisis-Proportional Recovery Sizing (CPRS)

NOVEL EDGE IDEA #18 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

═══════════════════════════════════════════════════════════════════════════════
THE UNTESTED ANGLE
═══════════════════════════════════════════════════════════════════════════════
Every prior recovery idea in the registry (#8 PCCH, #9 DDO, #12 Hybrid) uses a FIXED
harvest size regardless of the crisis severity:
  - DDO #9:     40% sUSDe / 21d — same for all crises
  - PCCH #8:    40% sUSDe / 21d — same for all crises
  - Hybrid #12: 40% sUSDe / 28d — same for all crises
  - KODS #15:   smooth Kelly ramp to 25% max — same shape for all crises

None of them scale recovery by OBSERVED CRISIS DEPTH.

Economic hypothesis: the fear premium in sUSDe carry (funding rate) is PROPORTIONAL to crisis
severity. After a −9% USDe unwind, surviving protocols' carry spikes high and persists long.
After a −1% rsETH depeg, carry barely responds. Therefore:
    harvest_pct  ∝ crisis_depth   (larger crisis → more carry available → harvest more)
    harvest_days ∝ crisis_depth   (larger fear premium → persists longer → harvest longer)

This is distinct from ALL prior ideas:
  - #3 #9 #12: FIXED harvest (don't differentiate by crisis depth)
  - #1 #4 #15 #16: SIZING signals (vol/Kelly/breadth), not recovery-phase adaptation
  - #6 EYC: VENUE selection (equilibrium yield), not crisis-phase adaptation
  - #7 #8: COMPOSITION shifts (regime weights), not crisis-proportional harvest
  - #11 CPPI: CONTINUOUS floor-math, no explicit crisis tracking

═══════════════════════════════════════════════════════════════════════════════
STATE MACHINE (4 states, fully causal — uses only data through day T-1)
═══════════════════════════════════════════════════════════════════════════════

  CRUISE   → DEFEND:  Kelly f*(t) < 0  [same trigger as #15 KODS, #12 Hybrid]
  DEFEND   → HARVEST: Kelly f*(t) ≥ 0 AND trailing DD > -theta_exit
                      [at this transition, record crisis_depth and compute
                       proportional harvest_pct / harvest_days]
  HARVEST  → CRUISE:  harvest countdown exhausted
  HARVEST  → DEFEND:  Kelly fires again during harvest (secondary crisis)

  CRUISE weights  = [max_risky, (1-max_risky)×2/3, (1-max_risky)×1/3]  = [0.25, 0.50, 0.25]
  DEFEND weights  = [0.00, 2/3, 1/3]   — 0% sUSDe (KODS-style full de-risk)
  HARVEST weights = [harvest_pct, (1-harvest_pct)×2/3, (1-harvest_pct)×1/3]
      where harvest_pct = clip(base_h + range_h × (crisis_depth / depth_scale),
                                base_h, max_h)
            harvest_days = clip(base_d + int(range_d × (crisis_depth / depth_scale)),
                                 base_d, max_d)

  crisis_depth = deepest trailing-DD below HWM observed DURING this DEFEND period (causal)

INNOVATION:  harvest_pct and harvest_days are SET ONCE at DEFEND→HARVEST transition, computed
             from the observed crisis depth. They are NOT changed during HARVEST.
             After HARVEST→CRUISE, they reset for the next crisis.

═══════════════════════════════════════════════════════════════════════════════
BASELINES (from registry, same fixture, same data)
═══════════════════════════════════════════════════════════════════════════════
  static #3:      Calmar ~2.03  (fixed 25/50/25)
  causal DDO #9:  Calmar ~3.68  (5% defend, DD trigger, fixed 40%/21d harvest)
  KODS #15:       Calmar ~4.55  (0% defend, Kelly trigger, smooth ramp to 25%)
  Hybrid #12:     Calmar ~4.52  (0% defend, Kelly trigger, fixed 40%/28d harvest)

KEY HYPOTHESES
  H1: After the largest crisis (USDe unwind, 9% hit), CPRS harvests MORE than KODS's 25%
      smooth ramp → captures more fear-premium carry → APY higher.
  H2: After small crises (ETH crash 3%, rsETH depeg 1%), CPRS harvests PROPORTIONALLY LESS
      → stays disciplined → avoids unnecessary exposure.
  H3: Net Calmar > KODS #15 (4.55) if carry gain from proportional harvest > cost.
  H4: OOS (train parameters on 2024-2025, test unseen 2026) — does the proportional effect hold?

PARAMETERS SWEPT
  base_harvest ∈ {0.15, 0.20, 0.25}  — minimum harvest % (for small/no crisis)
  max_harvest  ∈ {0.40, 0.50, 0.60}  — maximum harvest % (for deepest observed crisis)
  depth_scale  ∈ {0.03, 0.06, 0.09}  — crisis depth that triggers max_harvest
  base_days    ∈ {7, 10, 14}          — minimum harvest days
  max_days     ∈ {21, 28, 35}         — maximum harvest days
  theta_exit   ∈ {0.001, 0.002}       — DDO-style recovery proximity to HWM
  lookback     ∈ {10, 20}             — Kelly rolling window (best from #15 was 10)

COMPONENT DECOMPOSITION
  (A) CPRS vs DDO-0%:        proportional vs fixed harvest, 0% defend, DD trigger → harvest effect
  (B) CPRS vs KODS #15:      proportional discrete vs Kelly smooth ramp → which is better?
  (C) CPRS vs Hybrid #12:    proportional vs fixed (40%/28d), Kelly trigger → size-scaling effect

HONEST CAVEATS
  (a) Fixture crises are SYNTHETIC and FRONT-LOADED geometrically. The proportionality of
      fear premium after crisis (carrier rate spike) is MODELLED IMPLICITLY by the drift
      continuing at full rate (constant drift = full carry persists post-crisis). This is
      an APPROXIMATION — real carry may be disrupted after large crises too.
  (b) Day-1 crisis hit is unavoidable for any causal method (same as #9/#15/#12).
  (c) The 3 crises in the fixture span: small (1%), medium (3%), large (9%). Proportionality
      is testable but the calibration (depth_scale) is FIT ON THE SAME 3 EVENTS — overfitting
      risk is REAL; OOS test is the key check.
  (d) Kelly fixture degeneracy: σ² ≈ 0 in calm → Kelly binarises (fires after day 1 of crisis,
      smooth ramp in recovery). Same as #15/#12.
  (e) rates-carry + RWA-floor: synthetic smooth (Pendle PT / T-bill not in cloud checkout).
  (f) harvest_pct/harvest_days SET AT TRANSITION — if crisis continues during harvest (false
      recovery), system re-enters DEFEND. Tested via HARVEST→DEFEND interrupt.
  (g) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

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

# ── constants (same as #12/#15 for apples-to-apples) ─────────────────────────────────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT   = 3.31
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0
MIN_VAR       = 1e-10  # vol-floor from UPD6 lesson

# Cruise / Defend weights (same as validated #3/#15/#12 — only HARVEST changes)
MAX_RISKY    = 0.25
W_STATIC     = [0.25, 0.50, 0.25]                   # static #3 baseline
W_DEFEND     = [0.00, 2.0/3.0, 1.0/3.0]             # 0% sUSDe (KODS-style)


# ── data loading ───────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Tuple[List[str], Dict[str, float]]:
    """sUSDe daily fractional returns from fixture (backtest phase only)."""
    tmp = Path(tempfile.mkdtemp(prefix="cprs18_"))
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
    rets: Dict[str, float] = {}
    for i in range(1, len(dates)):
        if eq[dates[i - 1]]:
            rets[dates[i]] = eq[dates[i]] / eq[dates[i - 1]] - 1.0
    return dates[1:], rets


def _smooth_returns(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── metrics ────────────────────────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float], n_days: int) -> Dict[str, float]:
    if len(equity) < 2:
        return {"apy": 0.0, "maxdd": 0.0, "calmar": 0.0}
    start, end = equity[0], equity[-1]
    apy = ((end / start) ** (365.0 / n_days) - 1.0) * 100.0
    hwm = equity[0]
    maxdd = 0.0
    for v in equity:
        hwm = max(hwm, v)
        dd = (v - hwm) / hwm
        maxdd = min(maxdd, dd)
    maxdd_pct = abs(maxdd) * 100.0
    calmar = apy / maxdd_pct if maxdd_pct > 1e-9 else float("inf")
    return {"apy": round(apy, 3), "maxdd": round(maxdd_pct, 3), "calmar": round(calmar, 3)}


def _per_crisis_dd(equity: List[float], dates: List[str]) -> Dict[str, float]:
    """Max drawdown within each named stress window (from STRESS_WINDOWS)."""
    date_idx = {d: i for i, d in enumerate(dates)}
    result: Dict[str, float] = {}
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        lo_s = str(w["date_from"])
        hi_s = str(w["date_to"])
        idxs = [date_idx[d] + 1 for d in dates
                if lo_s <= d <= hi_s and d in date_idx]
        if not idxs:
            result[key] = 0.0
            continue
        i_start = max(0, min(idxs) - 5)  # a few days before for HWM baseline
        hwm = max(equity[i_start:min(idxs)]) if i_start < min(idxs) else equity[0]
        worst = min(equity[i] for i in idxs if i < len(equity))
        result[key] = round((worst - hwm) / hwm * 100.0, 3) if hwm > 0 else 0.0
    return result


# ── static baseline ────────────────────────────────────────────────────────────────────────────────

def _static_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    weights: List[float] = None,
) -> List[float]:
    if weights is None:
        weights = W_STATIC
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = (weights[0] * r_susde.get(d, 0.0)
             + weights[1] * r_rates.get(d, 0.0)
             + weights[2] * r_rwa.get(d, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
    return out


# ── KODS #15 baseline ─────────────────────────────────────────────────────────────────────────────

def _kods_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    lookback: int = 10,
    max_risky: float = 0.25,
    alpha: float = 0.1,
) -> Tuple[List[float], Dict[str, int]]:
    """KODS #15: Kelly trigger → 0% defend, smooth Kelly-ramp recovery."""
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    counts: Dict[str, int] = {"CRUISE": 0, "DEFEND": 0}
    for ds in dates:
        if len(buf) >= lookback:
            window = buf[-lookback:]
            mu = sum(window) / lookback
            sq = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq / (lookback - 1) if lookback > 1 else MIN_VAR, MIN_VAR)
            f_star = (mu - RATES_DAILY) / sigma2
            f_active = min(max(0.0, alpha * f_star), max_risky)
        else:
            f_active = max_risky  # warmup: full risky

        mode = "DEFEND" if f_active < 1e-9 else "CRUISE"
        counts[mode] += 1

        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)
        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt * r_rates.get(ds, 0.0)
             + f_rw * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))
    return out, counts


# ── DDO-0% baseline (fixed 40/28d harvest, 0% defend, DD trigger) ────────────────────────────────

def _ddo0_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    theta_enter: float = 0.003,
    theta_exit: float  = 0.001,
    harvest_pct: float = 0.40,
    harvest_days: int  = 28,
) -> Tuple[List[float], Dict[str, int]]:
    """DDO-0%: 0% sUSDe defend (same as Hybrid #12 DDO component).
    Fixed harvest (no proportionality) — baseline for component decomposition."""
    eq = 100_000.0
    hwm = eq
    out = [eq]
    counts: Dict[str, int] = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}
    was_defending = False
    h_left = 0
    h_pct = harvest_pct  # fixed
    for ds in dates:
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if dd <= -theta_enter:
            state = "DEFEND"
            was_defending = True
            h_left = 0
        else:
            if was_defending and dd >= -theta_exit:
                was_defending = False
                h_left = harvest_days
            state = "HARVEST" if h_left > 0 else "CRUISE"
            if h_left > 0:
                h_left -= 1
        counts[state] += 1
        if state == "DEFEND":
            w = W_DEFEND
        elif state == "HARVEST":
            f = h_pct
            w = [f, (1 - f) * (2 / 3), (1 - f) * (1 / 3)]
        else:
            w = W_STATIC
        r = w[0] * r_susde.get(ds, 0.0) + w[1] * r_rates.get(ds, 0.0) + w[2] * r_rwa.get(ds, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out, counts


# ── CPRS (Idea #18) ───────────────────────────────────────────────────────────────────────────────

def _cprs_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    *,
    lookback: int    = 10,
    theta_exit: float= 0.001,
    base_harvest: float = 0.20,  # min sUSDe in harvest (small / no crisis)
    max_harvest: float  = 0.50,  # max sUSDe in harvest (deepest crisis)
    depth_scale: float  = 0.06,  # crisis depth that drives harvest to max
    base_days: int   = 10,       # min harvest days
    max_days: int    = 28,       # max harvest days
    alpha: float     = 0.1,      # Kelly multiplier (same as #15 best param)
) -> Tuple[List[float], Dict[str, int]]:
    """
    CPRS Idea #18: Crisis-Proportional Recovery Sizing.

    State machine:
      CRUISE → DEFEND:  Kelly f*(t) < 0  [μ_rolling < r_f, fires after day 1]
      DEFEND → HARVEST: Kelly f*(t) ≥ 0 AND trailing DD ≥ −theta_exit
                        [record crisis_depth at this moment → set proportional harvest]
      HARVEST → CRUISE: harvest countdown exhausted
      HARVEST → DEFEND: Kelly fires again (secondary crisis interrupt)

    HARVEST sizing (set once at DEFEND→HARVEST transition):
      crisis_depth = maximum negative DD observed during this DEFEND period (causal)
      harvest_pct  = clip(base_harvest + (max_harvest - base_harvest) × (cd / depth_scale),
                          base_harvest, max_harvest)
      harvest_days = clip(base_days + int((max_days - base_days) × (cd / depth_scale)),
                          base_days, max_days)
    """
    buf: List[float] = []
    eq = 100_000.0
    hwm = eq
    out = [eq]
    counts: Dict[str, int] = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}
    # harvest pct/days per episode (crisis-proportional)
    harvest_episodes: List[Dict] = []

    state = "CRUISE"
    h_left = 0
    h_pct_active = 0.0      # harvest pct for current episode
    defend_max_dd = 0.0     # deepest DD seen during current DEFEND period (tracks crisis depth)

    for ds in dates:
        # ── causal signals (from yesterday's buffer / equity) ──────────────────────
        if len(buf) >= lookback:
            window = buf[-lookback:]
            mu = sum(window) / lookback
            sq = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq / (lookback - 1) if lookback > 1 else MIN_VAR, MIN_VAR)
            f_star = (mu - RATES_DAILY) / sigma2
            kelly_neg = f_star < 0.0
        else:
            kelly_neg = False   # warmup → optimistic

        dd = (eq - hwm) / hwm if hwm > 0 else 0.0

        # ── state transitions ──────────────────────────────────────────────────────
        if state == "CRUISE":
            if kelly_neg:
                state = "DEFEND"
                h_left = 0
                defend_max_dd = 0.0   # reset crisis tracker

        elif state == "DEFEND":
            # track deepest DD while defending (causal)
            defend_max_dd = min(defend_max_dd, dd)

            if not kelly_neg and dd >= -theta_exit:
                # ── KEY TRANSITION: compute crisis-proportional harvest ─────────
                crisis_depth = abs(defend_max_dd)   # positive magnitude
                frac = min(1.0, crisis_depth / depth_scale) if depth_scale > 1e-9 else 1.0
                h_pct_active = min(
                    max_harvest,
                    base_harvest + (max_harvest - base_harvest) * frac
                )
                raw_days = base_days + int((max_days - base_days) * frac)
                h_days_active = min(max_days, max(base_days, raw_days))
                harvest_episodes.append({
                    "crisis_depth": round(crisis_depth * 100, 3),
                    "harvest_pct": round(h_pct_active * 100, 1),
                    "harvest_days": h_days_active,
                })
                state = "HARVEST"
                h_left = h_days_active

        elif state == "HARVEST":
            if kelly_neg:
                # secondary crisis: interrupt harvest, defend again
                state = "DEFEND"
                h_left = 0
                defend_max_dd = dd  # start fresh crisis tracking from current DD
            elif h_left <= 0:
                state = "CRUISE"

        counts[state] += 1

        # ── portfolio return ───────────────────────────────────────────────────────
        if state == "DEFEND":
            w = W_DEFEND
        elif state == "HARVEST":
            f = h_pct_active
            w = [f, (1.0 - f) * (2.0 / 3.0), (1.0 - f) * (1.0 / 3.0)]
        else:
            w = W_STATIC

        r = (w[0] * r_susde.get(ds, 0.0)
             + w[1] * r_rates.get(ds, 0.0)
             + w[2] * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)

        buf.append(r_susde.get(ds, 0.0))
        if state == "HARVEST":
            h_left -= 1

    return out, counts, harvest_episodes


# ── sweep ─────────────────────────────────────────────────────────────────────────────────────────

def _sweep(
    dates: List[str],
    r_s: Dict[str, float],
    r_rt: Dict[str, float],
    r_rw: Dict[str, float],
) -> Tuple[Dict, List[Dict]]:
    """Sweep CPRS parameters and return (best_row, all_rows)."""
    param_grid = {
        "base_harvest": [0.15, 0.20, 0.25],
        "max_harvest":  [0.40, 0.50, 0.60],
        "depth_scale":  [0.03, 0.06, 0.09],
        "base_days":    [7, 10, 14],
        "max_days":     [21, 28, 35],
        "theta_exit":   [0.001, 0.002],
        "lookback":     [10, 20],
    }
    results = []
    n = len(dates)

    for lkb in param_grid["lookback"]:
        for bh in param_grid["base_harvest"]:
            for mh in param_grid["max_harvest"]:
                if mh <= bh:
                    continue
                for ds in param_grid["depth_scale"]:
                    for bd in param_grid["base_days"]:
                        for md in param_grid["max_days"]:
                            if md <= bd:
                                continue
                            for te in param_grid["theta_exit"]:
                                eq_v, cnts, episodes = _cprs_equity(
                                    dates, r_s, r_rt, r_rw,
                                    lookback=lkb,
                                    theta_exit=te,
                                    base_harvest=bh,
                                    max_harvest=mh,
                                    depth_scale=ds,
                                    base_days=bd,
                                    max_days=md,
                                )
                                m = _metrics(eq_v, n)
                                results.append({
                                    "lookback": lkb,
                                    "base_harvest": bh,
                                    "max_harvest": mh,
                                    "depth_scale": ds,
                                    "base_days": bd,
                                    "max_days": md,
                                    "theta_exit": te,
                                    "apy": m["apy"],
                                    "maxdd": m["maxdd"],
                                    "calmar": m["calmar"],
                                    "n_cruise": cnts.get("CRUISE", 0),
                                    "n_defend": cnts.get("DEFEND", 0),
                                    "n_harvest": cnts.get("HARVEST", 0),
                                    "episodes": episodes,
                                })

    best = max(results, key=lambda x: x["calmar"])
    return best, results


# ── OOS split ─────────────────────────────────────────────────────────────────────────────────────

OOS_SPLIT = "2025-06-01"   # same as #9/#12/#15 for apples-to-apples

def _split(dates: List[str], r_susde: Dict[str, float]) -> Tuple[
        List[str], Dict[str, float], List[str], Dict[str, float]]:
    train = [d for d in dates if d < OOS_SPLIT]
    test  = [d for d in dates if d >= OOS_SPLIT]
    rt = {d: v for d, v in r_susde.items() if d < OOS_SPLIT}
    rv = {d: v for d, v in r_susde.items() if d >= OOS_SPLIT}
    return train, rt, test, rv


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("IDEA #18: Crisis-Proportional Recovery Sizing (CPRS)")
    print("EVIDENCE LEVEL: L0 (backtest/synthetic fixture). NOT live results.")
    print("=" * 70)

    dates, r_susde = _load_susde_returns()
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)
    n = len(dates)
    print(f"\nBacktest window: {dates[0]} .. {dates[-1]}  ({n} days)")

    # ── baselines ──────────────────────────────────────────────────────────────
    print("\n─── BASELINES ────────────────────────────────────────────────────────")

    eq_s3 = _static_equity(dates, r_susde, r_rates, r_rwa)
    m3 = _metrics(eq_s3, n)
    print(f"  Static #3  (25/50/25 fixed):           APY {m3['apy']:+.2f}%  maxDD {m3['maxdd']:.2f}%"
          f"  Calmar {m3['calmar']:.2f}")

    eq_kods, kc = _kods_equity(dates, r_susde, r_rates, r_rwa, lookback=10)
    mk = _metrics(eq_kods, n)
    print(f"  KODS #15   (0% defend, Kelly smooth):  APY {mk['apy']:+.2f}%  maxDD {mk['maxdd']:.2f}%"
          f"  Calmar {mk['calmar']:.2f}  [DEFEND {kc['DEFEND']}d]")

    eq_ddo0, dc = _ddo0_equity(dates, r_susde, r_rates, r_rwa,
                               harvest_pct=0.40, harvest_days=28)
    md0 = _metrics(eq_ddo0, n)
    print(f"  DDO-0% #12 (0% defend, fixed 40/28d):  APY {md0['apy']:+.2f}%  maxDD {md0['maxdd']:.2f}%"
          f"  Calmar {md0['calmar']:.2f}  [DEFEND {dc['DEFEND']}d / HARVEST {dc['HARVEST']}d]")

    # ── CPRS full sweep ────────────────────────────────────────────────────────
    print("\n─── CPRS FULL SWEEP (Crisis-Proportional Recovery Sizing) ───────────")
    print("    Sweeping base_harvest × max_harvest × depth_scale × base/max_days × theta_exit × lookback")

    best, all_results = _sweep(dates, r_susde, r_rates, r_rwa)
    print(f"\n  Best CPRS:  APY {best['apy']:+.2f}%  maxDD {best['maxdd']:.2f}%"
          f"  Calmar {best['calmar']:.2f}")
    print(f"    params: base_h={best['base_harvest']:.0%} max_h={best['max_harvest']:.0%}"
          f" depth_scale={best['depth_scale']:.0%}"
          f" base_d={best['base_days']} max_d={best['max_days']}"
          f" theta_exit={best['theta_exit']:.3f} lookback={best['lookback']}")
    print(f"    days: CRUISE {best['n_cruise']} / DEFEND {best['n_defend']} / HARVEST {best['n_harvest']}")

    # ── show per-episode harvest decisions ─────────────────────────────────────
    print("\n  Per-crisis harvest decisions (best CPRS):")
    for ep in best["episodes"]:
        print(f"    crisis_depth={ep['crisis_depth']:.2f}%  "
              f"→ harvest_pct={ep['harvest_pct']:.1f}%  "
              f"harvest_days={ep['harvest_days']}d")

    # ── per-crisis DD breakdown ────────────────────────────────────────────────
    print("\n─── PER-CRISIS DRAWDOWN BREAKDOWN ────────────────────────────────────")
    eq_best, _, _ = _cprs_equity(
        dates, r_susde, r_rates, r_rwa,
        lookback=best["lookback"],
        theta_exit=best["theta_exit"],
        base_harvest=best["base_harvest"],
        max_harvest=best["max_harvest"],
        depth_scale=best["depth_scale"],
        base_days=best["base_days"],
        max_days=best["max_days"],
    )
    dd_s3   = _per_crisis_dd(eq_s3,   dates)
    dd_kods = _per_crisis_dd(eq_kods, dates)
    dd_best = _per_crisis_dd(eq_best, dates)

    header = f"  {'crisis':<25}  {'static#3 DD':>12}  {'KODS#15 DD':>12}  {'CPRS#18 DD':>12}  {'saved vs static':>16}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        dd3  = dd_s3.get(key, 0.0)
        ddk  = dd_kods.get(key, 0.0)
        ddc  = dd_best.get(key, 0.0)
        saved = dd3 - ddc
        print(f"  {key:<25}  {dd3:>+12.3f}%  {ddk:>+12.3f}%  {ddc:>+12.3f}%  {saved:>+15.3f}pp")

    # ── component decomposition ────────────────────────────────────────────────
    print("\n─── COMPONENT DECOMPOSITION (isolates harvest-scaling effect) ─────────")
    print("  (A) DDO-0% fixed 40/28d vs CPRS proportional:")
    delta_calmar = best["calmar"] - md0["calmar"]
    delta_apy    = best["apy"]    - md0["apy"]
    delta_dd     = best["maxdd"]  - md0["maxdd"]
    print(f"      CPRS APY {best['apy']:+.2f}% vs DDO-0% {md0['apy']:+.2f}%  Δ={delta_apy:+.3f}pp")
    print(f"      CPRS maxDD {best['maxdd']:.2f}% vs DDO-0% {md0['maxdd']:.2f}%  Δ={delta_dd:+.3f}pp")
    print(f"      CPRS Calmar {best['calmar']:.3f} vs DDO-0% {md0['calmar']:.3f}  Δ={delta_calmar:+.3f}")

    print("  (B) KODS #15 smooth ramp vs CPRS proportional discrete:")
    delta_kods_c = best["calmar"] - mk["calmar"]
    delta_kods_a = best["apy"]    - mk["apy"]
    delta_kods_d = best["maxdd"]  - mk["maxdd"]
    print(f"      CPRS APY {best['apy']:+.2f}% vs KODS {mk['apy']:+.2f}%  Δ={delta_kods_a:+.3f}pp")
    print(f"      CPRS maxDD {best['maxdd']:.2f}% vs KODS {mk['maxdd']:.2f}%  Δ={delta_kods_d:+.3f}pp")
    print(f"      CPRS Calmar {best['calmar']:.3f} vs KODS {mk['calmar']:.3f}  Δ={delta_kods_c:+.3f}")

    # ── OOS validation ─────────────────────────────────────────────────────────
    print("\n─── OUT-OF-SAMPLE VALIDATION ─────────────────────────────────────────")
    print(f"    Train: before {OOS_SPLIT} / Test: {OOS_SPLIT} and after")

    train_d, r_s_train, test_d, r_s_test = _split(dates, r_susde)
    r_rt_train = _smooth_returns(train_d, RATES_APY_PCT)
    r_rw_train = _smooth_returns(train_d, RWA_APY_PCT)
    r_rt_test  = _smooth_returns(test_d, RATES_APY_PCT)
    r_rw_test  = _smooth_returns(test_d, RWA_APY_PCT)

    # Best CPRS params on TRAIN
    best_train, _ = _sweep(train_d, r_s_train, r_rt_train, r_rw_train)
    print(f"  Best CPRS (train):  Calmar {best_train['calmar']:.2f}"
          f"  params: base_h={best_train['base_harvest']:.0%}"
          f" max_h={best_train['max_harvest']:.0%}"
          f" depth_scale={best_train['depth_scale']:.0%}"
          f" base_d={best_train['base_days']} max_d={best_train['max_days']}"
          f" te={best_train['theta_exit']:.3f} lkb={best_train['lookback']}")

    # Apply train-fit params to TEST
    eq_cprs_oos, _, ep_oos = _cprs_equity(
        test_d, r_s_test, r_rt_test, r_rw_test,
        lookback=best_train["lookback"],
        theta_exit=best_train["theta_exit"],
        base_harvest=best_train["base_harvest"],
        max_harvest=best_train["max_harvest"],
        depth_scale=best_train["depth_scale"],
        base_days=best_train["base_days"],
        max_days=best_train["max_days"],
    )
    eq_kods_oos, _ = _kods_equity(test_d, r_s_test, r_rt_test, r_rw_test,
                                   lookback=best_train["lookback"])
    eq_s3_oos = _static_equity(test_d, r_s_test, r_rt_test, r_rw_test)

    mc_oos   = _metrics(eq_cprs_oos, len(test_d))
    mk_oos   = _metrics(eq_kods_oos, len(test_d))
    m3_oos   = _metrics(eq_s3_oos,   len(test_d))
    print(f"  OOS Results ({test_d[0]} .. {test_d[-1]}, {len(test_d)} days):")
    print(f"    static #3:   APY {m3_oos['apy']:+.2f}%  maxDD {m3_oos['maxdd']:.2f}%  Calmar {m3_oos['calmar']:.2f}")
    print(f"    KODS #15:    APY {mk_oos['apy']:+.2f}%  maxDD {mk_oos['maxdd']:.2f}%  Calmar {mk_oos['calmar']:.2f}")
    print(f"    CPRS #18:    APY {mc_oos['apy']:+.2f}%  maxDD {mc_oos['maxdd']:.2f}%  Calmar {mc_oos['calmar']:.2f}")
    if ep_oos:
        print(f"    OOS episodes: {ep_oos}")

    # ── summary ────────────────────────────────────────────────────────────────
    print("\n─── HONEST SUMMARY TABLE ─────────────────────────────────────────────")
    rows = [
        ("static #3",      m3["apy"],    m3["maxdd"],    m3["calmar"],    "baseline"),
        ("KODS #15",        mk["apy"],    mk["maxdd"],    mk["calmar"],    "Calmar leader"),
        ("DDO-0% (fixed)",  md0["apy"],   md0["maxdd"],   md0["calmar"],   "fixed harvest baseline"),
        ("CPRS #18 (best)", best["apy"],  best["maxdd"],  best["calmar"],  "proportional harvest"),
    ]
    print(f"  {'method':<22}  {'APY':>7}  {'maxDD':>7}  {'Calmar':>8}  {'note'}")
    print("  " + "-" * 65)
    for row in rows:
        print(f"  {row[0]:<22}  {row[1]:>+7.2f}%  {row[2]:>6.2f}%  {row[3]:>8.2f}  {row[4]}")

    print("\n─── HONEST VERDICT ────────────────────────────────────────────────────")
    if best["calmar"] > mk["calmar"] + 0.05:
        print(f"  ✅ CPRS #18 BEATS KODS #15: Calmar {best['calmar']:.2f} > {mk['calmar']:.2f}")
        print(f"     Crisis-proportional harvest captures more fear-premium carry")
        print(f"     after large crises and stays disciplined after small ones.")
    elif abs(best["calmar"] - mk["calmar"]) <= 0.05:
        print(f"  ⚠️  CPRS #18 TIES KODS #15 (within 0.05): Calmar {best['calmar']:.2f} ≈ {mk['calmar']:.2f}")
        print(f"     Proportional sizing adds complexity but not significant improvement.")
    else:
        print(f"  ❌ CPRS #18 DOES NOT BEAT KODS #15: Calmar {best['calmar']:.2f} < {mk['calmar']:.2f}")
        print(f"     Proportional harvest does not improve over KODS smooth ramp.")

    if best["calmar"] > m3["calmar"]:
        print(f"  ✅ CPRS #18 beats static #3 baseline: {best['calmar']:.2f} > {m3['calmar']:.2f}")

    print("\n  Honest caveats:")
    print("  (a) Day-1 crisis hit unavoidable for any causal method.")
    print("  (b) 3 fixture crises only — proportional calibration can overfit these 3 events.")
    print("  (c) Kelly fixture degeneracy: σ²≈0 in calm → binarizes to 0%/max.")
    print("  (d) rates-carry + RWA = synthetic smooth (no Pendle-history in cloud checkout).")
    print("  (e) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("\n  Registry status: see docs/DYNAMIC_LEVERAGE_GUARDIAN.md → #18")
    print("=" * 70)


if __name__ == "__main__":
    main()
