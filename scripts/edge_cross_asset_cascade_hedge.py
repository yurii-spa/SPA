#!/usr/bin/env python3
"""
scripts/edge_cross_asset_cascade_hedge.py — Idea #20: Cross-Asset Cascade Hedge (CACH)

NOVEL EDGE IDEA #20 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  All 19 prior registry ideas operate on ONE TYPE of action:
    • TIMING/SIZING:    de-risk / re-enter the sUSDe leg based on signals (#1,#4,#7-#15,#18,#19)
    • COMPOSITION:      blend decorrelated desks (#2,#3,#6,#17)
    • SELECTION/VETO:   refuse high-risk books (#5,#16)
    • ANALYSIS:         decompose / measure the existing edge (#10,#13,#14,#19)

  NONE tested CROSS-ASSET PASSIVE HEDGING — holding a permanent short in a CORRELATED
  crisis-sensitive asset to extract positive carry when the main book is hit.

THE HEDGE
  The fixture includes `variant_d` (pure ETH-directional restaking, RiskClass B):
    • Calm period carry:  +9%/yr  (the cost we pay to be short — we're borrowing and selling)
    • ETH crash 2024-08:  −18%   → our short GAINS +18%
    • USDe unwind 2025-10: −10%  → our short GAINS +10%
    • rsETH depeg 2026-04: −20%  → our short GAINS +20%

  DeFi-structural rationale: variant_d captures pure ETH-beta restaking risk. In systemic
  events (ETH crashes, protocol depegs, funding unwinds), variant_d tends to lose MORE than
  susde_dn because it has no delta hedge.  A small permanent short creates a STRUCTURAL
  INSURANCE LEG: pay 9%/yr × hedge_size to receive CRISIS GAINS when they are most needed.

PORTFOLIO CONSTRUCTION
  Base cross-desk (#3): 25% susde_dn / 50% rates-carry / 25% RWA-floor
  CACH adds a short leg funded from the proceeds of the short sale:
    sUSDe_wt:   25%          (unchanged)
    rates_wt:   50% + h      (short proceeds reinvested in rates-carry — highest risk-free)
    RWA_wt:     25%          (unchanged)
    variant_short: −h       (short position; gain when variant_d loses)
    Total long = 100% + h, net = 100% ✓

  Sweep h ∈ {0%, 2%, 4%, 5%, 8%, 10%, 15%}.

ECONOMIC LOGIC
  Calm (no crisis):
    Short cost  = h × 9%/yr
    Extra carry = h × rates_APY = h × 4.6%/yr
    NET DRAG    = h × (9% − 4.6%) = h × 4.4%/yr  ← the "insurance premium"

  Crisis (when variant_d loses v%):
    Short GAIN  = h × v%
    This directly reduces portfolio DD and adds to NAV.

  Break-even hedge size: net_annual_cost = net_annual_crisis_gain
    At h=5%: annual cost = 5% × 4.4% = 0.22%/yr
    Annual crisis gains: (5% × 18% + 5% × 10% + 5% × 20%) / 2.5yr ≈ 0.096%/yr ... wait
    2.4% / 2.5yr = 0.96%/yr annual gain at h=5% → NET BENEFIT = 0.96% − 0.22% = +0.74%/yr

  So theory predicts CACH improves APY AND reduces maxDD vs static #3.
  Key question: does it beat KODS #15 (the Calmar leader)?

COMBINATION TEST (bonus): CACH + KODS
  KODS times the sUSDe leg (de-risks to 0% in crisis).
  The short variant_d is ALWAYS ON (not timed) — provides protection in:
    (a) the unavoidable day-1 crisis gap (before KODS reacts)
    (b) crises that KODS doesn't fully catch (mild ones)
  Tests whether defence-in-depth (timing + passive hedge) improves on timing alone.

BASELINES
  static #3:   APY 4.26% / maxDD 2.11% / Calmar 2.03
  KODS #15:    APY 5.05% / maxDD 1.11% / Calmar 4.55  ← the Calmar leader

HONEST CAVEATS
  (a) variant_d short = 100% SYNTHETIC (no perp-funding cost, no borrow fee modelled).
      Real DeFi short of LRT-restaking: borrow fees 1-3%/yr + funding + slippage.
      True cost = h × (9% + 2%_borrow_rate) ≈ h × 11%/yr → NET DRAG higher.
  (b) Crisis correlation is FIXTURE-CALIBRATED (same window dates for susde_dn + variant_d).
      In real markets, variant_d and susde_dn crises may not be perfectly simultaneous.
  (c) Shorting variant_d in real DeFi is: short ETH perp + long eETH/rsETH → complex,
      multiple legs. Not a simple single trade.
  (d) Short gamma: if variant_d RALLIES strongly in calm, short costs MORE than modelled.
      DeFi restaking strategies can have non-linear payoffs.
  (e) Evidence level: L0 (backtest/synthetic). NOT live results.
  (f) Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────────────────────────
RATES_APY_PCT = 4.6     # smooth rates-carry (same as registry #3–#19)
RWA_APY_PCT   = 3.31    # T-bill floor
MIN_VAR       = 1e-10   # variance floor for KODS (from registry)
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0

# Hedge sizes to sweep (h = fraction of portfolio in short variant_d)
HEDGE_SIZES = [0.00, 0.02, 0.04, 0.05, 0.08, 0.10, 0.15]

# KODS params (best from registry #15)
KODS_ALPHA   = 0.1
KODS_LOOKBACK = 10
KODS_MAX_RISKY = 0.25


# ── data loading ─────────────────────────────────────────────────────────────────────────────────

def _load_fixture_returns(strategy_id: str) -> Dict[str, float]:
    """Load daily fractional returns for a given fixture strategy."""
    tmp = Path(tempfile.mkdtemp(prefix=f"cach_{strategy_id}_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get(strategy_id)
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError(f"{strategy_id} fixture not available")
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


# ── metrics ───────────────────────────────────────────────────────────────────────────────────────

def _compute_metrics(equity: List[float], label: str) -> dict:
    """Compute APY, maxDD, Calmar from equity series."""
    if len(equity) < 2:
        return {"label": label, "apy_pct": 0.0, "maxDD_pct": 0.0, "calmar": 0.0}
    n_days = len(equity) - 1
    total_return = equity[-1] / equity[0] - 1.0
    apy = (1.0 + total_return) ** (365.0 / n_days) - 1.0
    hwm = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > hwm:
            hwm = v
        dd = (v - hwm) / hwm
        if dd < max_dd:
            max_dd = dd
    max_dd_abs = abs(max_dd)
    calmar = (apy / max_dd_abs) if max_dd_abs > 1e-8 else float("inf")
    return {
        "label": label,
        "apy_pct": round(apy * 100.0, 3),
        "maxDD_pct": round(max_dd_abs * 100.0, 3),
        "calmar": round(calmar, 2),
    }


def _crisis_breakdown(
    equity: List[float],
    dates: List[str],
    label: str,
) -> dict:
    """Per-crisis drawdown analysis."""
    by_date = dict(zip(dates, equity[1:]))
    results = {}
    for w in STRESS_WINDOWS:
        lo = str(w["date_from"])
        hi = str(w["date_to"])
        window_dates = [d for d in sorted(by_date) if lo <= d <= hi]
        if not window_dates:
            continue
        # find equity just before window
        all_dates = sorted(by_date)
        pre_idx = all_dates.index(window_dates[0])
        eq_pre = equity[pre_idx]  # equity at start of window
        worst = 0.0
        for d in window_dates:
            idx = all_dates.index(d)
            dd = (equity[idx + 1] - eq_pre) / eq_pre
            if dd < worst:
                worst = dd
        results[w["key"]] = round(abs(worst) * 100.0, 3)
    return {"label": label, "per_crisis_dd": results}


# ── portfolio engines ─────────────────────────────────────────────────────────────────────────────

def _cach_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_variant: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    hedge_size: float,
) -> Tuple[List[float], dict]:
    """
    Static Cross-Asset Cascade Hedge (CACH).

    Weights (gross, with short-proceeds reinvested in rates-carry):
      w_susde      = 0.25
      w_rates      = 0.50 + hedge_size   (includes short-sale proceeds at rates APY)
      w_rwa        = 0.25
      w_variant_short = −hedge_size       (negative → gain when variant loses)

    Net exposure = 0.25 + (0.50 + h) + 0.25 − h = 1.00 ✓
    """
    w_su = 0.25
    w_rt = 0.50 + hedge_size   # rates get the short proceeds
    w_rw = 0.25
    w_vs = -hedge_size          # short variant_d

    eq = 100_000.0
    out = [eq]
    for ds in dates:
        r = (w_su * r_susde.get(ds, 0.0)
             + w_rt * r_rates.get(ds, 0.0)
             + w_rw * r_rwa.get(ds, 0.0)
             + w_vs * r_variant.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)

    # compute economic decomposition
    calm_days = [d for d in dates if not _in_crisis_window(d)]
    crisis_days = [d for d in dates if _in_crisis_window(d)]
    # Net contribution of hedge leg to portfolio returns:
    # In calm: w_vs * r_variant = (-h) * (+drift) = negative  (cost, drain)
    # In crisis: w_vs * r_variant = (-h) * (-loss) = positive (gain, insurance payoff)
    hedge_calm_pnl  = sum(w_vs * r_variant.get(d, 0.0) for d in calm_days)
    hedge_crisis_pnl = sum(w_vs * r_variant.get(d, 0.0) for d in crisis_days)
    stats = {
        "hedge_size": round(hedge_size * 100, 1),
        "calm_days": len(calm_days),
        "crisis_days": len(crisis_days),
        "hedge_calm_drag_pct":  round(hedge_calm_pnl  * 100.0, 3),  # negative = cost
        "hedge_crisis_gain_pct": round(hedge_crisis_pnl * 100.0, 3), # positive = gain
        "net_hedge_value_pct": round((hedge_calm_pnl + hedge_crisis_pnl) * 100.0, 3),
    }
    return out, stats


def _in_crisis_window(d: str) -> bool:
    for w in STRESS_WINDOWS:
        if str(w["date_from"]) <= d <= str(w["date_to"]):
            return True
    return False


def _kods_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
) -> List[float]:
    """Replicate best KODS #15 (alpha=0.1, lookback=10, max_risky=0.25)."""
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    W_STATIC = [0.25, 0.50, 0.25]
    for ds in dates:
        if len(buf) >= KODS_LOOKBACK:
            window = buf[-KODS_LOOKBACK:]
            mu = sum(window) / KODS_LOOKBACK
            sq_dev = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq_dev / (KODS_LOOKBACK - 1) if KODS_LOOKBACK > 1 else MIN_VAR, MIN_VAR)
            excess = mu - RATES_DAILY
            f_star = excess / sigma2
            f_active = min(KODS_ALPHA * max(0.0, f_star), KODS_MAX_RISKY)
        else:
            f_active = W_STATIC[0]
        f_rt = (1.0 - f_active) * (2.0 / 3.0)
        f_rw = (1.0 - f_active) * (1.0 / 3.0)
        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw    * r_rwa.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))
    return out


def _cach_kods_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_variant: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa: Dict[str, float],
    hedge_size: float,
) -> List[float]:
    """
    CACH + KODS combination (defence in depth):
    - KODS dynamically sizes the sUSDe leg
    - Short variant_d is ALWAYS ON (passive hedge, not timed)
    - Short proceeds reinvested in rates-carry

    When KODS is in cruise (f_active=0.25):
      sUSDe=0.25, rates=0.50+h, RWA=0.25, short=-h  (same as CACH)
    When KODS is in de-risk (f_active→0):
      sUSDe→0,   rates=1.0+h−0, RWA→... [KODS scale + hedge]

    Implementation: first compute KODS f_active, then apply hedge on top.
    """
    buf: List[float] = []
    eq = 100_000.0
    out = [eq]
    for ds in dates:
        if len(buf) >= KODS_LOOKBACK:
            window = buf[-KODS_LOOKBACK:]
            mu = sum(window) / KODS_LOOKBACK
            sq_dev = sum((r - mu) ** 2 for r in window)
            sigma2 = max(sq_dev / (KODS_LOOKBACK - 1) if KODS_LOOKBACK > 1 else MIN_VAR, MIN_VAR)
            excess = mu - RATES_DAILY
            f_star = excess / sigma2
            f_active = min(KODS_ALPHA * max(0.0, f_star), KODS_MAX_RISKY)
        else:
            f_active = 0.25  # warmup

        # KODS safe-leg (complement of sUSDe)
        safe = 1.0 - f_active
        f_rt_kods = safe * (2.0 / 3.0)
        f_rw_kods = safe * (1.0 / 3.0)

        # add short variant_d (funded from rates portion)
        f_rt = f_rt_kods + hedge_size   # extra rates from short proceeds
        f_vs = -hedge_size               # short

        r = (f_active * r_susde.get(ds, 0.0)
             + f_rt    * r_rates.get(ds, 0.0)
             + f_rw_kods * r_rwa.get(ds, 0.0)
             + f_vs    * r_variant.get(ds, 0.0))
        eq *= (1.0 + r)
        out.append(eq)
        buf.append(r_susde.get(ds, 0.0))
    return out


# ── OOS split ─────────────────────────────────────────────────────────────────────────────────────

OOS_SPLIT_DATE = "2025-06-01"  # same as registry #11/#12/#15/#18

def _oos_calmar(equity: List[float], dates: List[str]) -> float:
    """Compute Calmar on OOS portion (dates >= OOS_SPLIT_DATE)."""
    oos_idx = [i for i, d in enumerate(dates) if d >= OOS_SPLIT_DATE]
    if not oos_idx:
        return 0.0
    start = oos_idx[0]
    oos_eq = equity[start: start + len(oos_idx) + 1]  # +1 for initial
    if len(oos_eq) < 2:
        return 0.0
    m = _compute_metrics(oos_eq, "oos")
    return m["calmar"]


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("IDEA #20 — Cross-Asset Cascade Hedge (CACH)")
    print("EVIDENCE LEVEL: L0 (backtest/synthetic fixture). NOT live results.")
    print("=" * 72)

    # load data
    print("\n[1] Loading fixture returns (susde_dn + variant_d) ...")
    r_susde   = _load_fixture_returns("susde_dn")
    r_variant = _load_fixture_returns("variant_d")

    all_dates = sorted(set(r_susde) & set(r_variant))
    if not all_dates:
        print("ERROR: no common dates between susde_dn and variant_d.")
        sys.exit(1)
    print(f"    Common dates: {all_dates[0]} .. {all_dates[-1]} ({len(all_dates)} days)")

    r_rates = _smooth_returns(all_dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(all_dates, RWA_APY_PCT)

    # ── per-asset crisis behaviour (show the hedge rationale) ────────────────────────────────────
    print("\n[2] Crisis behaviour of variant_d (the hedge asset) vs susde_dn:")
    print(f"    {'Crisis':<28} {'susde_dn loss':>14} {'variant_d loss':>16} {'hedge profit (h=5%)':>20}")
    print("    " + "-" * 80)
    for w in STRESS_WINDOWS:
        lo, hi = str(w["date_from"]), str(w["date_to"])
        wdates = [d for d in all_dates if lo <= d <= hi]
        if not wdates:
            continue
        pre_idx = all_dates.index(wdates[0])
        # equity before the window: reconstruct from initial+returns
        eq_s, eq_v = 100_000.0, 100_000.0
        for d in all_dates[:pre_idx]:
            eq_s *= (1.0 + r_susde[d])
            eq_v *= (1.0 + r_variant[d])
        loss_s = sum(r_susde.get(d, 0.0) for d in wdates)
        loss_v = sum(r_variant.get(d, 0.0) for d in wdates)
        hedge_gain = -0.05 * loss_v
        print(f"    {w['key']:<28} {loss_s*100:>+12.2f}%   {loss_v*100:>+14.2f}%   "
              f"{'+'}{hedge_gain*100:>+17.2f}%")

    # ── CACH sweep ───────────────────────────────────────────────────────────────────────────────
    print("\n[3] CACH static hedge sweep (bt = backtest, L0):")
    print(f"    {'hedge%':>7} {'APY(bt)':>10} {'maxDD(bt)':>11} {'Calmar(bt)':>12} "
          f"{'OOS Calmar':>12} {'net hedge val':>14}")
    print("    " + "-" * 72)

    best_calmar = 0.0
    best_hedge  = 0.0
    all_results = []

    for h in HEDGE_SIZES:
        eq, hstats = _cach_equity(all_dates, r_susde, r_variant, r_rates, r_rwa, h)
        m = _compute_metrics(eq, f"CACH h={h*100:.0f}%")
        oos_c = _oos_calmar(eq, all_dates)
        row = {**m, **hstats, "oos_calmar": oos_c}
        all_results.append(row)
        star = " ◄ best IS" if h > 0 and m["calmar"] > best_calmar else ""
        if h > 0 and m["calmar"] > best_calmar:
            best_calmar = m["calmar"]
            best_hedge = h
        print(f"    {h*100:>6.0f}%  {m['apy_pct']:>9.3f}%  {m['maxDD_pct']:>9.3f}%  "
              f"{m['calmar']:>12.2f}  {oos_c:>12.2f}  "
              f"{hstats['net_hedge_value_pct']:>+12.3f}%{star}")

    # ── baselines ────────────────────────────────────────────────────────────────────────────────
    print("\n[4] Baselines (from registry):")
    eq_kods = _kods_equity(all_dates, r_susde, r_rates, r_rwa)
    m_kods  = _compute_metrics(eq_kods, "KODS #15")
    oos_kods = _oos_calmar(eq_kods, all_dates)
    print(f"    {'static #3 (h=0%)':>25} APY 4.26%  maxDD 2.11%  Calmar 2.03  [registry]")
    print(f"    {'KODS #15 (no hedge)':>25} APY {m_kods['apy_pct']:.3f}%  maxDD {m_kods['maxDD_pct']:.3f}%  "
          f"Calmar {m_kods['calmar']:.2f}  OOS {oos_kods:.2f}")

    # ── CACH + KODS combination ──────────────────────────────────────────────────────────────────
    print("\n[5] CACH + KODS combination (defence in depth):")
    print(f"    {'hedge%':>7} {'APY(bt)':>10} {'maxDD(bt)':>11} {'Calmar(bt)':>12} {'OOS Calmar':>12}")
    print("    " + "-" * 56)
    for h in [0.0, 0.02, 0.05, 0.10]:
        eq_combo = _cach_kods_equity(all_dates, r_susde, r_variant, r_rates, r_rwa, h)
        m_combo  = _compute_metrics(eq_combo, f"CACH+KODS h={h*100:.0f}%")
        oos_combo = _oos_calmar(eq_combo, all_dates)
        print(f"    {h*100:>6.0f}%  {m_combo['apy_pct']:>9.3f}%  {m_combo['maxDD_pct']:>9.3f}%  "
              f"{m_combo['calmar']:>12.2f}  {oos_combo:>12.2f}")

    # ── per-crisis breakdown for best CACH ───────────────────────────────────────────────────────
    print(f"\n[6] Per-crisis breakdown (best CACH h={best_hedge*100:.0f}% vs static #3 vs KODS):")
    eq_best, _ = _cach_equity(all_dates, r_susde, r_variant, r_rates, r_rwa, best_hedge)
    eq_static, _ = _cach_equity(all_dates, r_susde, r_variant, r_rates, r_rwa, 0.0)

    for w in STRESS_WINDOWS:
        lo, hi = str(w["date_from"]), str(w["date_to"])
        wdates = [d for d in all_dates if lo <= d <= hi]
        if not wdates:
            continue

        def window_dd(eq_series, dates_list, window_dates):
            d0 = window_dates[0]
            pre_idx = dates_list.index(d0)
            eq_pre = eq_series[pre_idx]
            worst = 0.0
            for wd in window_dates:
                idx = dates_list.index(wd)
                dd = (eq_series[idx + 1] - eq_pre) / eq_pre
                if dd < worst:
                    worst = dd
            return abs(worst) * 100.0

        dd_static = window_dd(eq_static, all_dates, wdates)
        dd_best   = window_dd(eq_best, all_dates, wdates)
        dd_kods   = window_dd(eq_kods, all_dates, wdates)
        saved_vs_static = dd_static - dd_best
        print(f"    {w['key']:<28} static {dd_static:>5.3f}%  "
              f"CACH-best {dd_best:>5.3f}%  KODS {dd_kods:>5.3f}%  "
              f"saved vs static {saved_vs_static:>+.3f}pp")

    # ── hedge economics decomposition ────────────────────────────────────────────────────────────
    print(f"\n[7] Hedge economics at best h={best_hedge*100:.0f}%:")
    best_result = next(r for r in all_results if abs(r["hedge_size"] - best_hedge * 100) < 0.1)
    print(f"    Crisis days:           {best_result['crisis_days']}")
    print(f"    Calm days:             {best_result['calm_days']}")
    print(f"    Hedge calm drag:       {best_result['hedge_calm_drag_pct']:+.3f}%  "
          f"(cost of short on {best_result['calm_days']} calm days — drag)")
    print(f"    Hedge crisis gains:    {best_result['hedge_crisis_gain_pct']:+.3f}%  "
          f"(insurance payoff when variant_d collapses on {best_result['crisis_days']} crisis days)")
    print(f"    Net hedge value:       {best_result['net_hedge_value_pct']:+.3f}%  "
          f"({'POSITIVE — hedge earns more than it costs' if best_result['net_hedge_value_pct'] > 0 else 'NEGATIVE'})")

    # ── summary verdict ──────────────────────────────────────────────────────────────────────────
    best_m = next(r for r in all_results if abs(r["hedge_size"] - best_hedge * 100) < 0.1)
    print("\n" + "=" * 72)
    print("VERDICT (bt = backtest, L0, advisory only):")
    print(f"  Static #3 (no hedge):  APY 4.26%  maxDD 2.11%  Calmar 2.03")
    print(f"  CACH best (h={best_hedge*100:.0f}%):  "
          f"APY {best_m['apy_pct']:.3f}%  "
          f"maxDD {best_m['maxDD_pct']:.3f}%  "
          f"Calmar {best_m['calmar']:.2f}  "
          f"OOS {best_m['oos_calmar']:.2f}")
    print(f"  KODS #15 (no hedge):   APY {m_kods['apy_pct']:.3f}%  "
          f"maxDD {m_kods['maxDD_pct']:.3f}%  "
          f"Calmar {m_kods['calmar']:.2f}  "
          f"OOS {oos_kods:.2f}")
    print()

    if best_m["calmar"] > 2.03:
        print("  CACH improves over static #3 (honest: cross-asset hedge has positive NPV).")
    else:
        print("  CACH does NOT improve over static #3 on this fixture.")

    if best_m["calmar"] > m_kods["calmar"]:
        print("  CACH BEATS KODS — passive hedge outperforms timing on this fixture.")
    else:
        print("  CACH does NOT beat KODS #15 — timing beats passive hedging on this fixture.")

    print()
    print("HONEST CAVEATS (mandatory):")
    print("  (a) Fixture is SYNTHETIC — crisis correlations are deterministically matched by design.")
    print("      Real variant_d/susde_dn correlations may differ in timing (not simultaneous).")
    print("  (b) Short cost = (headline_APY − rates_APY) × h. Missing: borrow fee (~2-3%/yr),")
    print("      perp funding, slippage on entry/exit. True break-even h is LOWER than shown.")
    print("  (c) OOS = calm period (rsETH-depeg only); same limitation as #1/#15/#18.")
    print("  (d) 'variant_d short' ≈ short ETH perp + long eETH — multi-leg, complex in DeFi.")
    print("  (e) Evidence level: L0 (backtest/synthetic). NEVER present as realized returns.")
    print("=" * 72)


if __name__ == "__main__":
    main()
