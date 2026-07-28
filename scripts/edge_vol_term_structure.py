#!/usr/bin/env python3
"""
scripts/edge_vol_term_structure.py — Idea #21: Volatility Term Structure Trigger (VTST)

NOVEL EDGE IDEA #21 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  Ideas #1–#20 used ONE of these signals for de-risk:
    (A) Fixed: static weights — #3 25/50/25
    (B) Equity vol at single lookback: guardian #1 (vol_mult × baseline_vol)
    (C) Kelly μ/σ² at single lookback: KODS #15 (best Calmar = 4.55)
    (D) Trailing drawdown threshold: DDO #9
    (E) Continuous floor math: CPPI #11
    (F) Previous-day sign: — not tested
    (G) Passive short of correlated book: CACH #20

  NONE has used the SHAPE (slope) of the Volatility Term Structure (VTS) —
  the cross-lookback relationship between short-horizon and long-horizon realized vol:

      VTS_slope(t) = (σ_short(t) − σ_long(t)) / max(σ_long(t), ε)

  where σ_short = rolling std over `short_lb` days, σ_long = rolling std over `long_lb` days.

WHY THIS IS STRUCTURALLY DIFFERENT FROM KODS #15
  • KODS uses μ/σ² at ONE lookback → ratio of signal-to-noise at that horizon.
  • VTST uses the SLOPE of σ across two horizons → captures whether short-term
    realized vol has DIVERGED UPWARD from long-term realized vol (inversion signal).
  • In TradFi this is the Volatility Term Structure — a well-known leading indicator
    for regime change. Here we apply it to DeFi book return series.
  • Structural difference: KODS says "bet size proportional to Sharpe"; VTST says
    "de-risk when recent vol has outpaced historical vol".

HOW VTST BEHAVES IN OUR FIXTURE
  CALM:   σ_short ≈ σ_long ≈ 0 (no variance in deterministic drift) → slope ≈ 0
          (numerically: if σ_long < ε, we define slope = 0 → INVEST).
          → Allocation = max_risky (same as KODS calm behaviour).

  CRISIS day 1:  sUSDe takes front-loaded hit. Can't avoid: causal controller.

  CRISIS day 2:  σ_short(5d) SPIKES (crisis day in 5d window) while σ_long(20d)
                 is still dominated by calm days → slope = (big − small) / small >> 0
                 → DEFEND (de-risk to 0% sUSDe). SAME timing as KODS.

  RECOVERY:      σ_short drops quickly as crisis day rolls out of SHORT window (5d).
                 σ_long stays elevated longer (20d window, crisis lingers).
                 → slope = (near-0 − something) / something < 0 → INVEST.
                 KEY: σ_5 drops back to 0 roughly 5 days after the LAST big-loss day,
                 vs KODS-10 which needs 10 days for the crisis to roll out of
                 the Kelly window.  VTST recovers FASTER than KODS.

KEY HYPOTHESIS
  VTST recovers EARLIER than KODS after each crisis (σ_short drops below σ_long
  within ~5 days of losses decaying below drift), giving more carry-on-recovery.
  Calmar prediction: slightly ABOVE KODS 4.55.

PARAMETERS SWEPT
  short_lb ∈ {3, 5, 7}    — short-horizon σ window (days)
  long_lb  ∈ {15, 20, 30} — long-horizon σ window (days)
  slope_threshold ∈ {0.0, 0.5, 1.0} — VTS slope threshold to trigger de-risk
  max_risky ∈ {0.25, 0.35} — maximum sUSDe fraction in INVEST state

PORTFOLIO STRUCTURE (same as #3/#15)
  risky = f_active × sUSDe (capped at max_risky)
  safe  = (1 − f_active), split rates:RWA = 2:1
  At max_risky=0.25:  rates=50%, RWA=25% (= static #3 default)
  At f_active=0:      rates=66.7%, RWA=33.3% (= KODS DEFEND state)

BASELINES
  static #3:    Calmar ~2.03 (25/50/25 fixed)
  causal DDO #9: Calmar ~3.68
  KODS #15:     Calmar ~4.55 (current Calmar-leader)

HONEST CAVEATS
  (a) Fixture σ ≈ 0 in calm → VTST = 0 slope → trivially INVEST (no false positives,
      but also no test of FP-robustness).
  (b) In REAL markets (σ_calm > 0): VTS slope can false-positive during high-vol
      periods that are not actual crises → FP sensitivity TBD.
  (c) Day-1 crisis hit is unavoidable (causal controller).
  (d) Recovery speed advantage vs KODS depends on the SHAPE of the crisis loss
      distribution (geometric front-loading in fixture → big day 1, small days 2+).
  (e) rates-carry + RWA-floor are smooth synthetic (same limitation as #3–#20).
  (f) Evidence level: L0 (backtest/synthetic). NOT live results.

stdlib-only, deterministic, LLM-forbidden, no spa_core/execution imports.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import loader as ld, fixtures as fx  # noqa: E402
from spa_core.strategy_lab import metrics  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────
RWA_FLOOR_APY = 3.31            # %/yr (T-bill floor, near-zero-vol)
RATES_CARRY_APY = 4.6           # %/yr (rates-desk fixed-carry, smooth synthetic)
INITIAL_NAV = 100_000.0

# ── fixture data loading ──────────────────────────────────────────────────────
def _load_susde_series() -> Dict[str, float]:
    """Load the sUSDe-DN fixture equity series (deterministic, no network)."""
    tmp = Path(tempfile.mkdtemp(prefix="vtst_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if not s or not s.backtest or s.backtest.n_points < 2:
        raise RuntimeError("susde_dn fixture missing / too few points")
    out: Dict[str, float] = {}
    for p in s.backtest.series:
        d = p.get("date")
        e = p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            out[d] = float(e)
    return out


def _daily_returns(equity_by_date: Dict[str, float]) -> Dict[str, float]:
    dates = sorted(equity_by_date)
    ret: Dict[str, float] = {}
    for i in range(1, len(dates)):
        prev = equity_by_date[dates[i - 1]]
        if prev > 0:
            ret[dates[i]] = equity_by_date[dates[i]] / prev - 1.0
    return ret


# ── volatility utilities ──────────────────────────────────────────────────────
def _stddev(values: List[float]) -> float:
    """Sample std-dev; returns 0.0 for len < 2."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n   # population var (consistent with Kelly scripts)
    return math.sqrt(variance)


def _vts_slope(returns_hist: List[float], short_lb: int, long_lb: int,
               eps: float = 1e-8) -> float:
    """
    Volatility Term Structure slope = (σ_short − σ_long) / max(σ_long, eps).

    Positive slope: short-term vol > long-term vol → vol inversion → DANGER.
    Negative/zero slope: normal (short <= long) → safe.
    Returns 0.0 if both σ near zero (numerical safety).
    """
    if len(returns_hist) < long_lb:
        return 0.0  # warmup — not enough history, treat as normal
    σ_short = _stddev(returns_hist[-short_lb:])
    σ_long = _stddev(returns_hist[-long_lb:])
    if σ_long < eps and σ_short < eps:
        return 0.0  # both near-zero (calm fixture) → no signal
    denominator = max(σ_long, eps)
    return (σ_short - σ_long) / denominator


# ── synthetic safe-leg returns ────────────────────────────────────────────────
def _safe_leg_daily_return(rates_frac: float, rwa_frac: float) -> float:
    """Daily return of the composite safe leg (rates-carry + RWA floor)."""
    rates_daily = RATES_CARRY_APY / 100.0 / 365.0
    rwa_daily = RWA_FLOOR_APY / 100.0 / 365.0
    return rates_frac * rates_daily + rwa_frac * rwa_daily


# ── backtest engine ──────────────────────────────────────────────────────────
def run_vtst_backtest(
    susde_returns: Dict[str, float],
    short_lb: int = 5,
    long_lb: int = 20,
    slope_threshold: float = 0.0,
    max_risky: float = 0.25,
    oos_split: Optional[str] = None,
) -> dict:
    """
    Run the VTST overlay on the cross-desk portfolio.

    Signals:
      VTS slope > slope_threshold → DEFEND (0% sUSDe)
      VTS slope ≤ slope_threshold → INVEST (max_risky% sUSDe)

    Returns dict of {apy, max_dd, calmar, n_switches, ...} for full and OOS windows.
    """
    dates = sorted(susde_returns)
    if len(dates) < long_lb + 2:
        raise ValueError(f"Insufficient dates: {len(dates)}")

    nav = INITIAL_NAV
    hwm = INITIAL_NAV
    max_dd = 0.0
    log_returns: List[float] = []
    returns_hist: List[float] = []     # growing history of susde daily returns
    switches = 0
    prev_state = "INVEST"

    # OOS tracking
    oos_nav = None
    oos_hwm = None
    oos_max_dd = 0.0
    oos_log_rets: List[float] = []
    oos_started = False

    for d in dates:
        r_susde = susde_returns[d]
        returns_hist.append(r_susde)

        # ── VTS signal (fully causal: only history up to yesterday) ──
        slope = _vts_slope(returns_hist[:-1], short_lb, long_lb)  # exclude TODAY's return
        state = "DEFEND" if slope > slope_threshold else "INVEST"
        if state != prev_state:
            switches += 1
        prev_state = state

        # ── allocate ──
        if state == "INVEST":
            f_active = max_risky
        else:
            f_active = 0.0

        rates_frac = (1.0 - f_active) * (2.0 / 3.0)
        rwa_frac   = (1.0 - f_active) * (1.0 / 3.0)
        safe_ret = _safe_leg_daily_return(rates_frac, rwa_frac)
        port_ret = f_active * r_susde + safe_ret

        # ── OOS boundary ──
        if oos_split and d >= oos_split and not oos_started:
            oos_started = True
            oos_nav = nav
            oos_hwm = nav

        # ── NAV update ──
        nav *= (1.0 + port_ret)
        log_returns.append(math.log(1.0 + port_ret) if port_ret > -1 else -10.0)
        if nav > hwm:
            hwm = nav
        dd = (hwm - nav) / hwm
        if dd > max_dd:
            max_dd = dd

        # ── OOS tracking ──
        if oos_started and oos_nav is not None:
            oos_nav *= (1.0 + port_ret)
            oos_log_rets.append(math.log(1.0 + port_ret) if port_ret > -1 else -10.0)
            if oos_nav > oos_hwm:
                oos_hwm = oos_nav
            oos_dd = (oos_hwm - oos_nav) / oos_hwm
            if oos_dd > oos_max_dd:
                oos_max_dd = oos_dd

    # ── metrics ──
    n_days = len(dates)
    years = n_days / 365.0
    total_return = nav / INITIAL_NAV - 1.0
    apy = (1.0 + total_return) ** (1.0 / years) - 1.0

    calmar = (apy * 100.0) / (max_dd * 100.0) if max_dd > 1e-9 else float("inf")

    # OOS
    oos_calmar = None
    oos_apy = None
    if oos_started and oos_nav is not None and oos_log_rets:
        oos_years = len(oos_log_rets) / 365.0
        oos_total = oos_nav / INITIAL_NAV - 1.0  # relative to portfolio start, not OOS start
        _oos_nav_start = INITIAL_NAV * math.exp(sum(log_returns[: n_days - len(oos_log_rets)]))
        oos_total_proper = oos_nav / _oos_nav_start - 1.0
        oos_apy = (1.0 + oos_total_proper) ** (1.0 / oos_years) - 1.0
        oos_calmar = (oos_apy * 100.0) / (oos_max_dd * 100.0) if oos_max_dd > 1e-9 else float("inf")

    return {
        "apy_pct": round(apy * 100.0, 4),
        "max_dd_pct": round(max_dd * 100.0, 4),
        "calmar": round(calmar, 2) if calmar != float("inf") else "inf",
        "n_days": n_days,
        "n_switches": switches,
        "state_breakdown": {"short_lb": short_lb, "long_lb": long_lb,
                            "slope_threshold": slope_threshold, "max_risky": max_risky},
        "oos_apy_pct": round(oos_apy * 100.0, 4) if oos_apy is not None else None,
        "oos_max_dd_pct": round(oos_max_dd * 100.0, 4) if oos_started else None,
        "oos_calmar": round(oos_calmar, 2) if (oos_calmar is not None and oos_calmar != float("inf")) else (
            "inf" if oos_calmar == float("inf") else None),
    }


# ── per-crisis DD breakdown (mirror of prior scripts) ────────────────────────
STRESS_WINDOWS = [
    {"key": "eth_crash_2024_08",    "date_from": "2024-08-01", "date_to": "2024-08-31"},
    {"key": "usde_unwind_2025_10",  "date_from": "2025-10-01", "date_to": "2025-11-30"},
    {"key": "rseth_depeg_2026_04",  "date_from": "2026-04-01", "date_to": "2026-04-30"},
]


def _per_crisis_dd(
    susde_returns: Dict[str, float],
    short_lb: int, long_lb: int, slope_threshold: float, max_risky: float,
) -> List[dict]:
    """Return per-crisis portfolio DD for VTST and static #3 baseline."""
    results = []
    for w in STRESS_WINDOWS:
        d_from = w["date_from"]
        d_to = w["date_to"]
        window_dates = [d for d in sorted(susde_returns) if d_from <= d <= d_to]

        # VTST portfolio NAV within window
        # (Use SAME causal history for signal — rebuild up to window start)
        all_dates = sorted(susde_returns)
        pre_window = [d for d in all_dates if d < d_from]
        hist: List[float] = [susde_returns[d] for d in pre_window]

        vtst_nav = 100.0
        vtst_hwm = 100.0
        vtst_dd = 0.0

        static_nav = 100.0
        static_hwm = 100.0
        static_dd = 0.0

        # rebuild state at start of window from causal history
        slope_at_start = _vts_slope(hist, short_lb, long_lb)
        state = "DEFEND" if slope_at_start > slope_threshold else "INVEST"

        for d in window_dates:
            r = susde_returns[d]
            hist.append(r)
            slope = _vts_slope(hist[:-1], short_lb, long_lb)
            state = "DEFEND" if slope > slope_threshold else "INVEST"

            f_active = max_risky if state == "INVEST" else 0.0
            rates_frac = (1 - f_active) * (2 / 3)
            rwa_frac   = (1 - f_active) * (1 / 3)
            safe_r = _safe_leg_daily_return(rates_frac, rwa_frac)
            port_r = f_active * r + safe_r

            vtst_nav *= (1 + port_r)
            if vtst_nav > vtst_hwm:
                vtst_hwm = vtst_nav
            dd = (vtst_hwm - vtst_nav) / vtst_hwm
            if dd > vtst_dd:
                vtst_dd = dd

            # Static #3 baseline (25% sUSDe, 50% rates, 25% RWA)
            static_r = 0.25 * r + _safe_leg_daily_return(0.50, 0.25)
            static_nav *= (1 + static_r)
            if static_nav > static_hwm:
                static_hwm = static_nav
            sdd = (static_hwm - static_nav) / static_hwm
            if sdd > static_dd:
                static_dd = sdd

        results.append({
            "window": w["key"],
            "vtst_dd_pct": round(vtst_dd * 100, 4),
            "static_dd_pct": round(static_dd * 100, 4),
            "saved_pp": round((static_dd - vtst_dd) * 100, 4),
        })
    return results


# ── KODS #15 reference (simplified Kelly on same portfolio) ──────────────────
def _kods_reference(susde_returns: Dict[str, float], lookback: int = 10,
                    max_risky: float = 0.25, alpha: float = 0.1) -> dict:
    """Reproduce KODS #15 logic (μ/σ² Kelly) for direct comparison."""
    r_f_daily = RATES_CARRY_APY / 100.0 / 365.0
    eps = 1e-12
    dates = sorted(susde_returns)
    nav = INITIAL_NAV
    hwm = INITIAL_NAV
    max_dd = 0.0
    hist: List[float] = []

    for d in dates:
        r = susde_returns[d]
        hist.append(r)
        # Kelly (causal: use history BEFORE today)
        window = hist[max(0, len(hist) - 1 - lookback): len(hist) - 1]
        if len(window) >= 2:
            mu = sum(window) / len(window)
            var = sum((x - mu) ** 2 for x in window) / len(window)
            f_kelly = (mu - r_f_daily) / (var + eps)
            f_active = max(0.0, min(alpha * f_kelly, max_risky))
        else:
            f_active = max_risky

        rates_frac = (1 - f_active) * (2 / 3)
        rwa_frac   = (1 - f_active) * (1 / 3)
        port_r = f_active * r + _safe_leg_daily_return(rates_frac, rwa_frac)
        nav *= (1 + port_r)
        if nav > hwm:
            hwm = nav
        dd = (hwm - nav) / hwm
        if dd > max_dd:
            max_dd = dd

    years = len(dates) / 365.0
    apy = (nav / INITIAL_NAV) ** (1.0 / years) - 1.0
    calmar = (apy * 100) / (max_dd * 100) if max_dd > 1e-9 else float("inf")
    return {"label": f"KODS_lkb={lookback}", "apy_pct": round(apy * 100, 4),
            "max_dd_pct": round(max_dd * 100, 4), "calmar": round(calmar, 2)}


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 72)
    print("VTST #21 — Volatility Term Structure Trigger Backtest")
    print("(all results: bt = backtest / synthetic fixture / evidence L0)")
    print("=" * 72)

    susde_equity = _load_susde_series()
    susde_returns = _daily_returns(susde_equity)
    n_total = len(susde_returns)
    print(f"\nData: {min(susde_returns)} → {max(susde_returns)} ({n_total} return days)")
    OOS_SPLIT = "2025-06-01"  # same as #11/#15/#20

    # ── static #3 baseline ──────────────────────────────────────────────────
    static_nav = INITIAL_NAV
    static_hwm = INITIAL_NAV
    static_dd = 0.0
    for r in (susde_returns[d] for d in sorted(susde_returns)):
        port_r = 0.25 * r + _safe_leg_daily_return(0.50, 0.25)
        static_nav *= (1 + port_r)
        if static_nav > static_hwm:
            static_hwm = static_nav
        dd = (static_hwm - static_nav) / static_hwm
        if dd > static_dd:
            static_dd = dd
    years_tot = n_total / 365.0
    static_apy = (static_nav / INITIAL_NAV) ** (1 / years_tot) - 1.0
    static_calmar = (static_apy * 100) / (static_dd * 100) if static_dd > 1e-9 else float("inf")
    print(f"\n{'Baseline':30s} APY={static_apy*100:.3f}%  maxDD={static_dd*100:.3f}%"
          f"  Calmar={static_calmar:.2f}  [static #3]")

    # ── KODS #15 reference ──────────────────────────────────────────────────
    kods = _kods_reference(susde_returns, lookback=10, max_risky=0.25, alpha=0.1)
    print(f"{'KODS #15 reference':30s} APY={kods['apy_pct']:.3f}%  "
          f"maxDD={kods['max_dd_pct']:.3f}%  Calmar={kods['calmar']:.2f}  [registry leader]")

    # ── VTST parameter sweep ────────────────────────────────────────────────
    print("\n── VTST Parameter Sweep ──────────────────────────────────────────")
    print(f"{'Config':40s} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8} {'OOS_Cal':>8} {'Switches':>8}")
    print("-" * 88)

    SHORT_LBS   = [3, 5, 7]
    LONG_LBS    = [15, 20, 30]
    SLOPE_THRS  = [0.0, 0.5, 1.0]
    MAX_RISKIES = [0.25, 0.35]

    best_calmar = -1.0
    best_cfg = None
    best_result = None

    for short_lb in SHORT_LBS:
        for long_lb in LONG_LBS:
            if short_lb >= long_lb:
                continue
            for slope_thr in SLOPE_THRS:
                for max_risky in MAX_RISKIES:
                    r = run_vtst_backtest(
                        susde_returns, short_lb=short_lb, long_lb=long_lb,
                        slope_threshold=slope_thr, max_risky=max_risky,
                        oos_split=OOS_SPLIT,
                    )
                    cal = r["calmar"] if r["calmar"] != "inf" else 999.0
                    oos_cal = r["oos_calmar"] if r["oos_calmar"] not in (None, "inf") else (
                        99.9 if r["oos_calmar"] == "inf" else 0.0)
                    label = f"slb={short_lb} llb={long_lb} thr={slope_thr} mrk={max_risky}"
                    print(f"  {label:38s} {r['apy_pct']:>8.3f} {r['max_dd_pct']:>8.3f} "
                          f"{cal:>8.2f} {oos_cal:>8.2f} {r['n_switches']:>8d}")
                    if cal > best_calmar:
                        best_calmar = cal
                        best_cfg = (short_lb, long_lb, slope_thr, max_risky)
                        best_result = r

    # ── best config per-crisis breakdown ────────────────────────────────────
    if best_cfg and best_result:
        short_lb, long_lb, slope_thr, max_risky = best_cfg
        print(f"\n── Best config: slb={short_lb} llb={long_lb} thr={slope_thr} mrk={max_risky} ──")
        print(f"   APY={best_result['apy_pct']:.3f}%  maxDD={best_result['max_dd_pct']:.3f}%"
              f"  Calmar={best_calmar:.2f}  OOS_Calmar={best_result['oos_calmar']}")
        print(f"   Switches: {best_result['n_switches']}")

        print("\n── Per-Crisis Breakdown (best VTST vs static #3) ─────────────")
        crisis_results = _per_crisis_dd(susde_returns, short_lb, long_lb, slope_thr, max_risky)
        for c in crisis_results:
            print(f"  {c['window']:30s}  static_DD={c['static_dd_pct']:.3f}%  "
                  f"VTST_DD={c['vtst_dd_pct']:.3f}%  saved={c['saved_pp']:+.3f}pp")

    # ── comparison table ─────────────────────────────────────────────────────
    print("\n── Registry Comparison (bt numbers, evidence L0) ──────────────")
    print(f"  {'Method':35s} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    print("  " + "-" * 61)
    print(f"  {'static #3 (25/50/25)':35s} {static_apy*100:>8.3f} {static_dd*100:>8.3f} {static_calmar:>8.2f}")
    print(f"  {'KODS #15 (registry leader)':35s} {kods['apy_pct']:>8.3f} {kods['max_dd_pct']:>8.3f} {kods['calmar']:>8.2f}")
    if best_result:
        cal_display = best_calmar if best_calmar < 900 else float("inf")
        print(f"  {'VTST #21 (best config)':35s} {best_result['apy_pct']:>8.3f} "
              f"{best_result['max_dd_pct']:>8.3f} {best_calmar:>8.2f}")

    # ── VTS slope recovery analysis ──────────────────────────────────────────
    print("\n── VTS Slope Dynamics Analysis (mechanistic transparency) ──────")
    if best_cfg:
        short_lb, long_lb, slope_thr, max_risky = best_cfg
        print(f"  Lookbacks: short={short_lb}d / long={long_lb}d / threshold={slope_thr}")
        print("  Showing VTS slope & state on key crisis/recovery days for USDe-unwind:")
        # Reconstruct for USDe-unwind window
        hist: List[float] = []
        usde_start = "2025-10-01"
        usde_end   = "2025-11-30"
        for d in sorted(susde_returns):
            r = susde_returns[d]
            if d < usde_start:
                hist.append(r)
        show_count = 0
        for d in sorted(susde_returns):
            if d < usde_start or d > usde_end:
                if d >= usde_start:
                    hist.append(susde_returns[d])
                continue
            r = susde_returns[d]
            slope = _vts_slope(hist, short_lb, long_lb)
            state = "DEFEND" if slope > slope_thr else "INVEST"
            hist.append(r)
            if show_count < 20:
                print(f"    {d}  r={r*100:+.4f}%  VTS_slope={slope:+.3f}  state={state}")
                show_count += 1
            elif show_count == 20:
                print("    ... (truncated at 20 days)")
                break

    print("\n── Honest verdict ──────────────────────────────────────────────")
    print("  Evidence level: L0 (backtest/synthetic fixture). NOT live results.")
    print("  All numbers labeled 'bt' = backtest; never presented as realized returns.")
    print("  See registry entry #21 for caveats.")


if __name__ == "__main__":
    main()
