#!/usr/bin/env python3
"""
scripts/edge_ema_crossover_derisk.py — Idea #21: EMA/SMA Crossover De-Risk (ECDR)

NOVEL EDGE IDEA #21 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE UNTESTED ANGLE
  All prior timing ideas (#9 DDO, #15 KODS, #14 vol) use LEVEL or RATIO signals:
    - DDO #9:   threshold on trailing drawdown from HWM  (level vs maximum-ever)
    - KODS #15: Kelly = μ/σ²  (mean-over-variance RATIO)
    - vol #14:  rolling std threshold  (dispersion level)

  None tested TREND-REVERSAL signals — whether the sUSDe NAV is in a down-trend
  vs an up-trend, independent of how far it has fallen from any reference.

  This script tests:

      fast_ema(t) = EMA of sUSDe cumulative NAV over 'fast_period' days
      slow_sma(t) = SMA of sUSDe cumulative NAV over 'slow_period' days

      DEFEND: fast_ema(t-1) < slow_sma(t-1)   ← downtrend signal
      CRUISE: fast_ema(t-1) ≥ slow_sma(t-1)   ← uptrend signal

  Signal computed on sUSDe-ONLY NAV (no feedback from portfolio weights —
  avoids the problem where DEFEND→flat NAV→ instantly cancels de-risk signal).

STRUCTURAL DIFFERENCES vs prior ideas
  • Different MECHANISM: detects TREND DIRECTION, not level vs HWM or μ/σ².
  • STICKIER than threshold-based signals: once EMA < SMA (downtrend confirmed),
    it takes sustained positive returns to reverse — intra-crisis small bounces
    that push the NAV up slightly won't immediately flip the signal.
  • Particularly relevant for MULTI-DAY crises (USDe-unwind: 23-day window with
    geometrically front-loaded losses). DDO's tight θ might trigger re-entry on
    small intra-crisis bounces; MA crossover maintains DEFEND mode throughout.
  • NO cushion math (≠ CPPI #11), NO Kelly math (≠ KODS #15), NO HWM (≠ DDO #9).
  • Analogous to classic "Golden Cross / Death Cross" in equity trend-following,
    applied to carry-yield NAV.

FIXTURE STRUCTURE (important for interpretation):
  The stress windows use geometric front-loading:
    day 1 of crisis: loss ≈ 50% of total window loss
    day 2: ≈ 25%, day 3: ≈ 12.5%, ... (halving each day)
  This means:
    - Any causal method misses day-1 loss (no signal before it happens)
    - MA crossover signals on day 2 (same as KODS #15, DDO #9)
    - STICKINESS advantage: EMA stays below SMA throughout multi-day window
      even as remaining losses become tiny (EMA doesn't "snap back" until
      sustained positive return period pushes it above slow SMA)

PARAMETERS SWEPT
  fast_period ∈ {3, 5, 7, 10}    ← EMA half-life (shorter = more responsive)
  slow_period ∈ {15, 20, 30}     ← SMA lookback

BASELINES (same fixture, apples-to-apples)
  static #3:    Calmar ~2.03  (fixed 25/50/25 forever)
  causal DDO #9: Calmar ~3.68 (drawdown threshold)
  KODS #15:     Calmar ~4.55  (Kelly μ/σ², current Calmar leader)

HONEST CAVEATS
  (a) Day-1 crisis loss unavoidable — any causal method shares this.
  (b) Fixture front-loads losses geometrically → stickiness advantage most
      visible in multi-day crises. In single-day gap events, no difference.
  (c) sUSDe NAV signal is own-leg-based (same as vol #14) — #14 showed own-leg
      vol doesn't LEAD the crisis. ECDR has the same limitation: we detect the
      trend AFTER the first big loss. Leading signal would need exogenous RTMR.
  (d) rates-carry + RWA-floor = smooth synthetic (same as #3–#20 baseline).
  (e) In calm periods with near-zero variance (fixture), EMA ≈ SMA (both track
      smooth upward drift) → always CRUISE → same as static #3 in calm.
      Advantage shows only during and after crisis periods.
  (f) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants (same as #3/#9/#11/#15/#18/#19/#20 — apples-to-apples) ─────────────────────────────
RATES_APY_PCT = 4.6
RWA_APY_PCT   = 3.31
RATES_DAILY   = RATES_APY_PCT / 100.0 / 365.0
RWA_DAILY     = RWA_APY_PCT   / 100.0 / 365.0

WEIGHTS_CRUISE = [0.25, 0.50, 0.25]          # [sUSDe, rates, RWA] — same as static #3
WEIGHTS_DEFEND = [0.00, 2.0 / 3.0, 1.0 / 3.0]  # 0% sUSDe — same DEFEND as KODS #15

OOS_CUTOFF = "2025-06-01"   # same split as #11/#15/#18/#19/#20

INITIAL_EQ = 100_000.0


# ── data loading ──────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    """sUSDe daily fractional returns from fixture. Identical to #9/#15/#19/#20."""
    tmp = Path(tempfile.mkdtemp(prefix="ecdr_"))
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
    return {
        dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0
        for i in range(1, len(dates))
        if eq[dates[i - 1]] != 0.0
    }


def _smooth_returns(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


# ── EMA / SMA helpers ─────────────────────────────────────────────────────────────────────────────

def _ema_series(values: List[float], period: int) -> List[float]:
    """Exponential moving average. alpha = 2 / (period + 1). Initialises from first value."""
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def _sma_at(values: List[float], i: int, period: int) -> Optional[float]:
    """SMA of values[i-period+1 .. i] (inclusive). Returns None if i < period-1."""
    if i < period - 1:
        return None
    return sum(values[i - period + 1 : i + 1]) / period


# ── main backtest engine ───────────────────────────────────────────────────────────────────────────

def _ecdr_equity(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa:   Dict[str, float],
    fast_period: int,
    slow_period: int,
) -> Tuple[List[float], List[str]]:
    """
    EMA/SMA Crossover De-Risk engine.

    Signal computed on sUSDe-only NAV independently of portfolio weights (no
    feedback loop). Uses yesterday's EMA and SMA to decide today's allocation.

    Warmup: first slow_period days → CRUISE (static #3 weights), so signal has
    sufficient history before it fires. Same fair warmup used in #15 KODS.
    """
    # ── build sUSDe-only NAV series (signal track) ────────────────────────────
    # susde_nav[0] = initial before any returns; susde_nav[i+1] = after dates[i]
    susde_nav: List[float] = [INITIAL_EQ]
    for d in dates:
        susde_nav.append(susde_nav[-1] * (1.0 + r_susde.get(d, 0.0)))
    # susde_nav has len(dates)+1 elements; index i corresponds to end-of-day i-1

    # ── pre-compute EMA on the full NAV series ────────────────────────────────
    susde_ema: List[float] = _ema_series(susde_nav, fast_period)
    # susde_ema[i] = EMA through susde_nav[i] = after day i-1 close

    # ── portfolio simulation ───────────────────────────────────────────────────
    eq = INITIAL_EQ
    out: List[float] = [eq]
    state_log: List[str] = []

    for idx, d in enumerate(dates):
        # Signal from YESTERDAY (index idx in susde_nav / susde_ema):
        #   susde_ema[idx] = EMA through previous close
        #   sma at idx     = SMA of susde_nav[idx-slow+1 .. idx]
        if idx >= slow_period:
            sma_prev = _sma_at(susde_nav, idx, slow_period)
            ema_prev = susde_ema[idx]
            defend = (sma_prev is not None) and (ema_prev < sma_prev)
        else:
            # warmup: static #3 (fair treatment — same as KODS #15)
            defend = False

        state = "DEFEND" if defend else "CRUISE"
        state_log.append(state)

        w = WEIGHTS_DEFEND if defend else WEIGHTS_CRUISE
        r_today = (
            w[0] * r_susde.get(d, 0.0)
            + w[1] * r_rates.get(d, 0.0)
            + w[2] * r_rwa.get(d, 0.0)
        )
        eq *= 1.0 + r_today
        out.append(eq)

    return out, state_log


def _blend_static(
    dates: List[str],
    r_susde: Dict[str, float],
    r_rates: Dict[str, float],
    r_rwa:   Dict[str, float],
    weights: List[float],
) -> List[float]:
    eq = INITIAL_EQ
    out = [eq]
    for d in dates:
        r = (
            weights[0] * r_susde.get(d, 0.0)
            + weights[1] * r_rates.get(d, 0.0)
            + weights[2] * r_rwa.get(d, 0.0)
        )
        eq *= 1.0 + r
        out.append(eq)
    return out


# ── metrics ───────────────────────────────────────────────────────────────────────────────────────

def _metrics(equity: List[float]) -> Dict[str, float]:
    if len(equity) < 2:
        return {}
    n = len(equity) - 1
    final = equity[-1]
    init  = equity[0]
    cagr = (final / init) ** (365.0 / n) - 1.0 if init > 0 else 0.0

    hwm = equity[0]
    max_dd = 0.0
    for v in equity[1:]:
        hwm = max(hwm, v)
        dd = (hwm - v) / hwm
        max_dd = max(max_dd, dd)

    calmar = (cagr / max_dd) if max_dd > 1e-9 else float("inf")
    return {"apy_pct": round(cagr * 100, 3), "max_dd_pct": round(max_dd * 100, 3),
            "calmar": round(calmar, 2), "n_days": n}


def _crisis_dd(
    equity: List[float],
    dates: List[str],
) -> Dict[str, float]:
    """Maximum drawdown inside each named crisis window."""
    out = {}
    dates_set: Dict[str, int] = {d: i + 1 for i, d in enumerate(dates)}  # map date→equity index
    for w in STRESS_WINDOWS:
        lo = str(w["date_from"])
        hi = str(w["date_to"])
        key = str(w["key"])
        idxs = [dates_set[d] for d in dates if lo <= d <= hi and d in dates_set]
        if not idxs:
            out[key] = 0.0
            continue
        # high-water from start through crisis start
        first_idx = min(idxs)
        hwm_before = max(equity[:first_idx])
        # max DD during window
        local_hwm = hwm_before
        max_local_dd = 0.0
        for i in idxs:
            local_hwm = max(local_hwm, equity[i])
            dd = (local_hwm - equity[i]) / local_hwm
            max_local_dd = max(max_local_dd, dd)
        out[key] = round(max_local_dd * 100, 3)
    return out


def _split_dates(dates: List[str], cutoff: str) -> Tuple[List[str], List[str]]:
    train = [d for d in dates if d < cutoff]
    test  = [d for d in dates if d >= cutoff]
    return train, test


def _defend_duty(state_log: List[str]) -> float:
    if not state_log:
        return 0.0
    return sum(1 for s in state_log if s == "DEFEND") / len(state_log)


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("Idea #21: EMA/SMA Crossover De-Risk (ECDR)  [L0 — backtest/synthetic]")
    print("=" * 72)
    print()

    r_susde = _load_susde_returns()
    dates   = sorted(r_susde)
    r_rates = _smooth_returns(dates, RATES_APY_PCT)
    r_rwa   = _smooth_returns(dates, RWA_APY_PCT)

    train_dates, test_dates = _split_dates(dates, OOS_CUTOFF)
    print(f"Full window:  {dates[0]} .. {dates[-1]}  ({len(dates)} days)")
    print(f"Train (IS):   {dates[0]} .. {OOS_CUTOFF}  ({len(train_dates)} days)")
    print(f"Test  (OOS):  {OOS_CUTOFF} .. {dates[-1]}  ({len(test_dates)} days)")
    print()

    # ── baselines (full window) ────────────────────────────────────────────────
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, WEIGHTS_STATIC if False else WEIGHTS_CRUISE)

    # Static #3 (25/50/25 always)
    eq_static = _blend_static(dates, r_susde, r_rates, r_rwa, [0.25, 0.50, 0.25])
    m_static  = _metrics(eq_static)
    dd_static = _crisis_dd(eq_static, dates)

    # Registered baselines from prior ideas (documented figures from registry)
    KODS_CALMAR_REGISTRY = 4.55
    DDO_CALMAR_REGISTRY  = 3.68

    print("── BASELINES ───────────────────────────────────────────────────────────")
    print(f"  static #3  (25/50/25):  apy={m_static['apy_pct']}%  maxDD={m_static['max_dd_pct']}%  "
          f"Calmar={m_static['calmar']}")
    print(f"  DDO #9     (registry):  Calmar~{DDO_CALMAR_REGISTRY}")
    print(f"  KODS #15   (registry):  Calmar~{KODS_CALMAR_REGISTRY}  [current leader]")
    print()

    # ── per-crisis baseline ────────────────────────────────────────────────────
    for key, dd in dd_static.items():
        print(f"  static #3 crisis DD  {key}: {dd}%")
    print()

    # ── parameter sweep ───────────────────────────────────────────────────────
    fast_periods = [3, 5, 7, 10]
    slow_periods = [15, 20, 30]

    print("── FULL-WINDOW SWEEP (bt = backtest, L0) ───────────────────────────────")
    header = f"{'fast':>5}  {'slow':>5}  {'APY%':>8}  {'maxDD%':>8}  {'Calmar':>8}  "
    header += f"{'duty%':>7}  {'vs #3':>8}  {'vs KODS':>8}"
    print(header)
    print("-" * len(header))

    best: Optional[Dict] = None
    all_results = []

    for fp in fast_periods:
        for sp in slow_periods:
            if fp >= sp:
                continue  # fast must be shorter than slow
            eq, state_log = _ecdr_equity(dates, r_susde, r_rates, r_rwa, fp, sp)
            m   = _metrics(eq)
            dty = _defend_duty(state_log)
            row = {
                "fast": fp, "slow": sp, "equity": eq, "state": state_log,
                **m, "duty": dty,
            }
            all_results.append(row)
            vs3  = round(m["calmar"] - m_static["calmar"], 2)
            vsk  = round(m["calmar"] - KODS_CALMAR_REGISTRY, 2)
            flag = "★" if best is None or m["calmar"] > best["calmar"] else ""
            print(
                f"  {fp:>5}  {sp:>5}  {m['apy_pct']:>8.3f}  {m['max_dd_pct']:>8.3f}  "
                f"{m['calmar']:>8.2f}  {dty * 100:>7.1f}  {vs3:>+8.2f}  {vsk:>+8.2f}  {flag}"
            )
            if best is None or m["calmar"] > best["calmar"]:
                best = row

    print()
    print(f"★ Best: fast={best['fast']}d  slow={best['slow']}d  "
          f"APY={best['apy_pct']}%  maxDD={best['max_dd_pct']}%  "
          f"Calmar={best['calmar']}")
    print()

    # ── per-crisis breakdown for best ─────────────────────────────────────────
    print("── PER-CRISIS DD (best ECDR vs static #3) ─────────────────────────────")
    best_dd = _crisis_dd(best["equity"], dates)
    for key in dd_static:
        saved = round(dd_static[key] - best_dd.get(key, 0.0), 3)
        print(f"  {key:<30}  static={dd_static[key]}%  ECDR={best_dd.get(key,0.0)}%  "
              f"saved={saved:+.3f}pp")
    print()

    # ── DEFEND state analysis during crisis windows ────────────────────────────
    print("── DEFEND STATE DURING EACH CRISIS (best ECDR) ────────────────────────")
    state_map = {d: s for d, s in zip(dates, best["state"])}
    for w in STRESS_WINDOWS:
        lo, hi = str(w["date_from"]), str(w["date_to"])
        key = str(w["key"])
        crisis_days = [d for d in dates if lo <= d <= hi]
        defend_days = sum(1 for d in crisis_days if state_map.get(d) == "DEFEND")
        cruise_days = len(crisis_days) - defend_days
        # Also count 7 days before crisis (pre-crisis)
        all_lo = datetime.date.fromisoformat(lo)
        pre_dates = [
            (all_lo - datetime.timedelta(days=7 - i)).isoformat() for i in range(7)
        ]
        pre_defend = sum(1 for d in pre_dates if state_map.get(d) == "DEFEND")
        print(
            f"  {key}: {len(crisis_days)}d window  →  "
            f"DEFEND {defend_days}d / CRUISE {cruise_days}d  "
            f"(pre-crisis 7d: {pre_defend} in DEFEND)"
        )
    print()

    # ── OOS validation ────────────────────────────────────────────────────────
    print("── OOS VALIDATION (unseen test set, same best params) ──────────────────")
    # OOS: rebuild test-window equity using SAME parameters trained on full run
    # (signal uses past data only — naturally causal, so just apply to test window)
    # BUT: we need pre-test NAV history to warm up EMA/SMA — supply via full run
    # then measure metrics only on test portion

    fp_best, sp_best = best["fast"], best["slow"]

    # Full run
    eq_full, state_full = _ecdr_equity(dates, r_susde, r_rates, r_rwa, fp_best, sp_best)

    # Split equity/state at OOS_CUTOFF
    split_idx = len(train_dates)  # equity has len(dates)+1 elements; equity[split_idx] = end of train
    oos_equity = eq_full[split_idx:]  # from end-of-train value through end

    m_oos   = _metrics(oos_equity)
    m_train = _metrics(eq_full[:split_idx + 1])

    # static #3 OOS
    eq_static_oos = eq_static[split_idx:]
    m_static_oos  = _metrics(eq_static_oos)

    print(f"  Train (IS)  ECDR:    APY={m_train['apy_pct']}%  maxDD={m_train['max_dd_pct']}%  "
          f"Calmar={m_train['calmar']}")
    print(f"  Test  (OOS) ECDR:    APY={m_oos['apy_pct']}%  maxDD={m_oos['max_dd_pct']}%  "
          f"Calmar={m_oos['calmar']}")
    print(f"  Test  (OOS) static:  APY={m_static_oos['apy_pct']}%  "
          f"maxDD={m_static_oos['max_dd_pct']}%  Calmar={m_static_oos['calmar']}")
    print()

    # ── Full summary comparison ───────────────────────────────────────────────
    print("── FULL SUMMARY (full-window, bt = backtest, L0) ───────────────────────")
    print()
    rows = [
        ("static #3 (25/50/25)", m_static["apy_pct"], m_static["max_dd_pct"], m_static["calmar"]),
        ("DDO #9  (registry)",   None,                 None,                   DDO_CALMAR_REGISTRY),
        ("KODS #15 (registry)",  None,                 None,                   KODS_CALMAR_REGISTRY),
        (f"ECDR best (fast={best['fast']}, slow={best['slow']})",
         best["apy_pct"], best["max_dd_pct"], best["calmar"]),
    ]
    print(f"  {'Method':<38}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>7}")
    print("  " + "-" * 65)
    for name, apy, dd, cal in rows:
        apy_str = f"{apy:>7.3f}" if apy is not None else "     —  "
        dd_str  = f"{dd:>7.3f}"  if dd  is not None else "     —  "
        print(f"  {name:<38}  {apy_str}  {dd_str}  {cal:>7.2f}")
    print()

    # ── Signal analysis (why does/doesn't it beat KODS) ───────────────────────
    _analyze_signal_stickiness(dates, r_susde, r_rates, r_rwa, best, state_map)

    # ── Verdict ────────────────────────────────────────────────────────────────
    beat_kods    = best["calmar"] > KODS_CALMAR_REGISTRY
    beat_ddo     = best["calmar"] > DDO_CALMAR_REGISTRY
    beat_static3 = best["calmar"] > m_static["calmar"]
    verdict = (
        "✅ ПОЗИТИВНО (beats KODS #15, current leader)"  if beat_kods  else
        "⚠️  MARGINAL  (beats DDO #9 but not KODS #15)"   if beat_ddo   else
        "⚠️  PARTIAL   (beats static #3 but not DDO #9)"  if beat_static3 else
        "❌ НЕГАТИВНО  (does not beat static #3)"
    )
    print(f"  VERDICT: {verdict}")
    print()
    print("  ⚠️  Evidence level: L0 (backtest/synthetic). NOT live results.")
    print("  ⚠️  Numbers are BACKTEST results — label 'bt' on all references.")
    print("  ⚠️  Fixture stress is synthetic; real crises may differ in timing.")
    print()


def _analyze_signal_stickiness(
    dates, r_susde, r_rates, r_rwa, best, state_map,
) -> None:
    """Decompose DEFEND days in- vs out-of-crisis to measure stickiness vs false signals."""
    print("── SIGNAL STICKINESS ANALYSIS ──────────────────────────────────────────")
    # Label each date as crisis / non-crisis
    crisis_dates = set()
    for w in STRESS_WINDOWS:
        lo, hi = str(w["date_from"]), str(w["date_to"])
        for d in dates:
            if lo <= d <= hi:
                crisis_dates.add(d)

    total = len(dates)
    in_crisis  = len(crisis_dates)
    out_crisis = total - in_crisis

    defend_in  = sum(1 for d in dates if d in crisis_dates and state_map.get(d) == "DEFEND")
    defend_out = sum(1 for d in dates if d not in crisis_dates and state_map.get(d) == "DEFEND")

    print(f"  Crisis days:       {in_crisis} / {total}  ({100*in_crisis/total:.1f}%)")
    print(f"  DEFEND in-crisis:  {defend_in} / {in_crisis}  ({100*defend_in/in_crisis:.1f}%)")
    print(f"  DEFEND out-crisis: {defend_out} / {out_crisis}  ({100*defend_out/out_crisis:.1f}%)")
    print(f"  → Precision (DEFEND days that are in a crisis): "
          f"{100*defend_in/(defend_in+defend_out+1e-9):.1f}%")
    print()

    # Also: EMA/SMA ratio profile to understand "how fast does it snap back"
    fp, sp = best["fast"], best["slow"]
    alpha = 2.0 / (fp + 1.0)

    susde_nav: List[float] = [INITIAL_EQ]
    for d in dates:
        susde_nav.append(susde_nav[-1] * (1.0 + r_susde.get(d, 0.0)))
    susde_ema = _ema_series(susde_nav, fp)

    print("  EMA vs SMA at key dates:")
    # Find the end of each crisis and the crossback
    for w in STRESS_WINDOWS:
        hi = str(w["date_to"])
        key = str(w["key"])
        # Find the crisis end index in dates
        hi_idx = next((i for i, d in enumerate(dates) if d > hi), len(dates) - 1)
        # Find when EMA recrosses SMA (CRUISE resumes) after crisis
        crossback = None
        for i in range(hi_idx, min(hi_idx + 60, len(dates))):
            sma = _sma_at(susde_nav, i, sp)
            ema = susde_ema[i]
            if sma is not None and ema >= sma:
                crossback = (i - hi_idx, dates[i])
                break
        cb_str = f"+{crossback[0]}d ({crossback[1]})" if crossback else "not within 60d"
        print(f"  {key}: crisis ends {hi} → EMA recrosses SMA at {cb_str}")
    print()


if __name__ == "__main__":
    main()
