#!/usr/bin/env python3
"""
scripts/edge_carry_rotation_floor.py — Idea #34 (CRF): Carry Rotation Floor

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0 or the live track.

IDEA
----
Every de-risk overlay tested in ideas #1-#33 routes sUSDe capital to CASH (0 %) when the
signal fires DEFEND. No previous idea changed the DESTINATION of the freed capital.

CRF changes exactly that: freed sUSDe weight is rotated into the RATES book instead of cash.

  NORMAL state:   25 % sUSDe  |  50 % rates  |  25 % RWA
  DEFEND state:    0 % sUSDe  |  75 % rates  |  25 % RWA   ← 25pp freed sUSDe → rates
  KODS baseline:   0 % sUSDe  |  50 % rates  |  25 % RWA + 25 % CASH

Economic rationale: in DeFi, the near-risk-free asset is stablecoin money-market
(currently ~4.6 %/yr), not fiat cash (0 %). If DEFEND is triggered by a low-carry regime,
the best place for the freed capital is the stablecoin carry itself — the same rates book
that is already in the portfolio. This is the floor of yield one should earn while waiting
to re-enter sUSDe.

TESTING VARIANTS
----------------
Signal drivers tested:
  1. KODS-5   : Kelly signal on lkb=5 rolling window (symmetric, same as #15 baseline)
  2. KODS-10  : Kelly signal on lkb=10 rolling window
  3. ECDR-10-30: exponential carry drift (EMA10 - EMA30, same as #23 survivor on real data)

For each signal × {KODS routing (baseline), CRF routing} → 6 configurations.

BACKTEST UNIVERSE (fixture)
---------------------------
susde_dn   : 11 %/yr drift, real stress-window losses (eth_crash 3 %, usde_unwind 9 %, rseth 1 %)
rates book : 4.6 %/yr flat (stablecoin money-market, no stress losses — not in fixture spec)
rwa book   : 3.31 %/yr flat (RWA backstop — not in fixture spec, used by prior entries)

EVIDENCE LEVEL
--------------
L0 — deterministic synthetic fixture only.  NOT realized / NOT live.
Stress magnitudes are fixture-spec values; real panel unavailable in cloud checkout.
Per #32 (CFPT) finding: on real books, positive-drift assets penalise ALL de-risk overlays
(KODS worst: -1.97 ΔCalmar). CRF improves WITHIN the de-risk family, but does not solve
the fundamental FP-tax identified in #32. Numbers here are fixture estimates only.

LLM FORBIDDEN in this module. stdlib-only. IS_ADVISORY=True.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ── constants ────────────────────────────────────────────────────────────────
SUSDE_APY   = 0.11          # 11 %/yr drift from fixture spec
RATES_APY   = 0.046         # 4.6 %/yr stablecoin money-market (rates desk)
RWA_APY     = 0.0331        # 3.31 %/yr RWA backstop

SUSDE_DD    = {             # fractional drawdown magnitudes per crisis window (fixture spec)
    "eth_crash_2024_08":   0.03,
    "usde_unwind_2025_10": 0.09,
    "rseth_depeg_2026_04": 0.01,
}

# base allocation weights (NORMAL state, shared across all configs)
W_SUSDE_BASE = 0.25
W_RATES_BASE = 0.50
W_RWA_BASE   = 0.25

MAX_RISKY    = 0.25         # sUSDe weight cap (never exceed 25pp exposure)

# stress window date ranges (from STRESS_WINDOWS in aggressive_lab/__init__.py)
_WINDOWS = [
    ("eth_crash_2024_08",   datetime.date(2024, 8, 1),  datetime.date(2024, 8, 31)),
    ("usde_unwind_2025_10", datetime.date(2025, 10, 1), datetime.date(2025, 10, 31)),
    ("rseth_depeg_2026_04", datetime.date(2026, 4, 1),  datetime.date(2026, 4, 30)),
]

BT_START = datetime.date(2024, 7, 1)
BT_END   = datetime.date(2026, 5, 31)
OOS_SPLIT = datetime.date(2026, 1, 1)   # last ~150 days as OOS


# ── build daily returns for susde ────────────────────────────────────────────

def _build_susde_daily() -> Dict[datetime.date, float]:
    """Deterministic daily fractional return for sUSDe book (mirrors fixture logic)."""
    drift = SUSDE_APY / 365.0
    # precompute window losses as front-loaded geometric series
    wl: Dict[str, float] = {}   # key -> total fractional loss
    wlen: Dict[str, int] = {}
    for key, lo, hi in _WINDOWS:
        wlen[key] = (hi - lo).days + 1
        wl[key] = SUSDE_DD.get(key, 0.0)

    def _window_for(d: datetime.date):
        for key, lo, hi in _WINDOWS:
            if lo <= d <= hi:
                return key, lo
        return None, None

    counters: Dict[str, int] = {}
    rets: Dict[datetime.date, float] = {}
    d = BT_START
    while d <= BT_END:
        key, lo = _window_for(d)
        daily_loss = 0.0
        if key is not None and wl[key] > 0:
            n = wlen[key]
            idx = counters.get(key, 0)
            counters[key] = idx + 1
            norm = sum(0.5 ** j for j in range(n))
            frac = (0.5 ** idx) / norm if norm > 0 else 0.0
            daily_loss = wl[key] * frac
        rets[d] = drift - daily_loss
        d += datetime.timedelta(days=1)
    return rets


# ── signal computation ────────────────────────────────────────────────────────

def _kods_signal(susde_rets: List[float], lkb: int, r_f_daily: float) -> List[int]:
    """Kelly de-risk signal: 1 = NORMAL (long sUSDe), 0 = DEFEND.
    DEFEND when rolling mean(lkb) < r_f_daily.
    Returns one value per day (index 0 = first day; first lkb-1 days use expanding window)."""
    n = len(susde_rets)
    signals = []
    for i in range(n):
        window = susde_rets[max(0, i - lkb + 1):i + 1]
        mu = sum(window) / len(window)
        signals.append(1 if mu >= r_f_daily else 0)
    return signals


def _ecdr_signal(susde_rets: List[float], fast: int = 10, slow: int = 30) -> List[int]:
    """Exponential carry drift signal: EMA(fast) > EMA(slow) → NORMAL, else DEFEND.
    Uses expanding EMA until window fills."""
    n = len(susde_rets)
    alpha_f = 2.0 / (fast + 1)
    alpha_s = 2.0 / (slow + 1)
    ema_f = ema_s = susde_rets[0]
    signals = []
    for r in susde_rets:
        ema_f = alpha_f * r + (1 - alpha_f) * ema_f
        ema_s = alpha_s * r + (1 - alpha_s) * ema_s
        signals.append(1 if ema_f >= ema_s else 0)
    return signals


# ── portfolio simulation ──────────────────────────────────────────────────────

def _simulate(
    dates: List[datetime.date],
    susde_rets: List[float],
    signals: List[int],
    use_crf: bool,
) -> Tuple[List[float], List[float], List[int]]:
    """
    Simulate daily portfolio equity (starting at $100k).

    use_crf=False (KODS baseline): freed sUSDe weight → CASH (0 %)
    use_crf=True  (CRF variant):   freed sUSDe weight → RATES book

    Returns (equity_curve, daily_portret, signals_used).
    """
    eq = 100_000.0
    equity = [eq]
    portrets = []

    rates_daily = RATES_APY / 365.0
    rwa_daily   = RWA_APY / 365.0

    for i, (d, r_su, sig) in enumerate(zip(dates, susde_rets, signals)):
        if sig == 1:
            # NORMAL: 25% sUSDe + 50% rates + 25% RWA
            w_su = W_SUSDE_BASE
            w_ra = W_RATES_BASE
        else:
            # DEFEND
            w_su = 0.0
            if use_crf:
                # freed 25pp sUSDe goes to rates
                w_ra = W_RATES_BASE + W_SUSDE_BASE   # = 0.75
            else:
                # freed 25pp sUSDe goes to cash (0 %)
                w_ra = W_RATES_BASE                  # = 0.50
        w_rw = W_RWA_BASE  # always 25%

        # portfolio daily return
        pr = w_su * r_su + w_ra * rates_daily + w_rw * rwa_daily
        # cash portion earns 0 by design (KODS routing)
        # (w_su + w_ra + w_rw <= 1; remainder is cash at 0 %)

        eq *= (1.0 + pr)
        equity.append(round(eq, 4))
        portrets.append(pr)

    return equity, portrets, signals


# ── statistics ────────────────────────────────────────────────────────────────

def _stats(equity: List[float], portrets: List[float], days: int) -> Dict:
    """Compute APY, maxDD, Calmar for a completed simulation."""
    n = days
    final = equity[-1]
    initial = equity[0]
    total_ret = (final - initial) / initial
    apy = (1 + total_ret) ** (365.0 / n) - 1

    hwm = initial
    max_dd = 0.0
    for eq in equity:
        if eq > hwm:
            hwm = eq
        dd = (hwm - eq) / hwm
        if dd > max_dd:
            max_dd = dd

    calmar = apy / max_dd if max_dd > 1e-9 else float("inf")
    return {"apy_pct": round(apy * 100, 3), "max_dd_pct": round(max_dd * 100, 3),
            "calmar": round(calmar, 3), "n_days": n}


def _per_crisis_dd(equity: List[float], dates: List[datetime.date]) -> Dict[str, float]:
    """Max drawdown within each stress window."""
    result = {}
    for key, lo, hi in _WINDOWS:
        wdd = 0.0
        hwm = None
        for d, eq in zip(dates, equity[1:]):  # equity[0] = initial before day0
            if lo <= d <= hi:
                if hwm is None:
                    hwm = eq
                if eq > hwm:
                    hwm = eq
                dd = (hwm - eq) / hwm if hwm else 0.0
                wdd = max(wdd, dd)
        result[key] = round(wdd * 100, 3)
    return result


def _signal_stats(dates: List[datetime.date], signals: List[int]) -> Dict:
    """Count DEFEND days, switches, and calendar breakdown."""
    defend_days = sum(1 for s in signals if s == 0)
    switches = sum(1 for i in range(1, len(signals)) if signals[i] != signals[i-1])
    years = len(signals) / 365.25
    return {
        "defend_days": defend_days,
        "defend_pct": round(defend_days / len(signals) * 100, 1),
        "switches_per_yr": round(switches / years, 2),
    }


# ── daily earnings comparison (NORMAL vs DEFEND for KODS vs CRF) ─────────────

def _defend_yield_comparison(signals: List[int]) -> Dict:
    """Expected daily yield in DEFEND state: KODS vs CRF."""
    rates_daily = RATES_APY / 365.0
    rwa_daily   = RWA_APY / 365.0

    # KODS defend daily yield: 50% rates + 25% RWA + 25% cash
    kods_defend = W_RATES_BASE * rates_daily + W_RWA_BASE * rwa_daily + 0.0
    # CRF defend daily yield:  75% rates + 25% RWA
    crf_defend = (W_RATES_BASE + W_SUSDE_BASE) * rates_daily + W_RWA_BASE * rwa_daily

    kods_apy = ((1 + kods_defend) ** 365 - 1) * 100
    crf_apy  = ((1 + crf_defend)  ** 365 - 1) * 100

    defend_days = sum(1 for s in signals if s == 0)
    total_days = len(signals)

    return {
        "kods_defend_apy_pct": round(kods_apy, 3),
        "crf_defend_apy_pct":  round(crf_apy, 3),
        "delta_defend_apy_pp": round(crf_apy - kods_apy, 3),
        "defend_days": defend_days,
        "total_days": total_days,
        "expected_portfolio_apy_lift_pp": round(
            (crf_apy - kods_apy) * defend_days / total_days, 4),
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    susde_ret_map = _build_susde_daily()
    dates = sorted(susde_ret_map.keys())
    susde_rets_full = [susde_ret_map[d] for d in dates]

    r_f_daily = RATES_APY / 365.0

    configs = [
        ("KODS-5",    _kods_signal(susde_rets_full, 5,  r_f_daily), False),
        ("KODS-10",   _kods_signal(susde_rets_full, 10, r_f_daily), False),
        ("ECDR-10-30",_ecdr_signal(susde_rets_full, 10, 30),         False),
        ("CRF-KODS5", _kods_signal(susde_rets_full, 5,  r_f_daily), True),
        ("CRF-KODS10",_kods_signal(susde_rets_full, 10, r_f_daily), True),
        ("CRF-ECDR",  _ecdr_signal(susde_rets_full, 10, 30),         True),
    ]

    # Also run static baseline (no overlay, 25/50/25 all the time)
    static_sig = [1] * len(dates)

    print("=" * 72)
    print("Idea #34 · CRF: Carry Rotation Floor")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  EVIDENCE=L0 (fixture)")
    print("=" * 72)
    print()
    print(f"Backtest:  {BT_START} … {BT_END}  ({len(dates)} days)")
    print(f"OOS split: {OOS_SPLIT}  "
          f"(BT={sum(1 for d in dates if d < OOS_SPLIT)}d  "
          f"OOS={sum(1 for d in dates if d >= OOS_SPLIT)}d)")
    print()
    print(f"Rates APY = {RATES_APY*100:.2f}%/yr (stablecoin rates book)")
    print(f"RWA   APY = {RWA_APY*100:.2f}%/yr")
    print(f"sUSDe APY = {SUSDE_APY*100:.2f}%/yr (fixture drift, pre-shock)")
    print()

    # ── static baseline ───────────────────────────────────────────────────────
    eq_static, pr_static, _ = _simulate(dates, susde_rets_full, static_sig, False)
    s_static = _stats(eq_static, pr_static, len(dates))
    print(f"{'STATIC (no overlay)':24s}  APY {s_static['apy_pct']:6.2f}%  "
          f"maxDD {s_static['max_dd_pct']:5.2f}%  Calmar {s_static['calmar']:6.3f}")
    print()

    # ── all 6 configs ─────────────────────────────────────────────────────────
    print(f"{'Config':20s}  {'Routing':8s}  {'APY':>7s}  {'maxDD':>6s}  {'Calmar':>7s}  "
          f"{'OOS Cal':>7s}  {'Defend%':>7s}  {'Sw/yr':>6s}")
    print("-" * 80)

    results = {}
    for name, sig, crf in configs:
        eq, pr, _ = _simulate(dates, susde_rets_full, sig, crf)

        # full backtest stats
        st_full = _stats(eq, pr, len(dates))

        # OOS stats (only dates >= OOS_SPLIT)
        oos_idx = [i for i, d in enumerate(dates) if d >= OOS_SPLIT]
        if len(oos_idx) > 10:
            oos_eq = [eq[oos_idx[0]]] + [eq[i + 1] for i in oos_idx]
            oos_pr = [pr[i] for i in oos_idx]
            st_oos = _stats(oos_eq, oos_pr, len(oos_idx))
        else:
            st_oos = {"calmar": float("nan")}

        ss = _signal_stats(dates, sig)
        routing = "→rates" if crf else "→cash "

        print(f"{name:20s}  {routing:8s}  "
              f"{st_full['apy_pct']:6.2f}%  {st_full['max_dd_pct']:5.2f}%  "
              f"{st_full['calmar']:7.3f}  {st_oos['calmar']:7.3f}  "
              f"{ss['defend_pct']:6.1f}%  {ss['switches_per_yr']:6.2f}")
        results[name] = {
            "full": st_full, "oos": st_oos, "signal": ss,
            "crf": crf, "sig_name": name.replace("CRF-", ""),
        }

    # ── CRF vs KODS delta table ───────────────────────────────────────────────
    print()
    print("── CRF improvement over KODS baseline (same signal) ──")
    print(f"{'Pair':30s}  {'ΔCalmar':>8s}  {'ΔAPY pp':>8s}  {'ΔmaxDD pp':>10s}")
    print("-" * 65)
    pairs = [
        ("CRF-KODS5",  "KODS-5"),
        ("CRF-KODS10", "KODS-10"),
        ("CRF-ECDR",   "ECDR-10-30"),
    ]
    for crf_name, base_name in pairs:
        cr = results[crf_name]["full"]
        ba = results[base_name]["full"]
        d_cal = cr["calmar"]   - ba["calmar"]
        d_apy = cr["apy_pct"]  - ba["apy_pct"]
        d_dd  = cr["max_dd_pct"] - ba["max_dd_pct"]
        print(f"{crf_name:15s} vs {base_name:12s}  {d_cal:+8.3f}  {d_apy:+8.3f}  {d_dd:+10.3f}")

    # ── per-crisis drawdown (CRF-KODS5 vs KODS-5) ─────────────────────────────
    print()
    print("── Per-crisis max drawdown: KODS-5 vs CRF-KODS5 ──")
    print(f"{'Window':28s}  {'KODS-5':>8s}  {'CRF-KODS5':>10s}  {'Δ':>6s}")
    print("-" * 60)
    eq_k5,  _, _ = _simulate(dates, susde_rets_full,
                              _kods_signal(susde_rets_full, 5, r_f_daily), False)
    eq_crf5, _, _ = _simulate(dates, susde_rets_full,
                               _kods_signal(susde_rets_full, 5, r_f_daily), True)
    dd_k5   = _per_crisis_dd(eq_k5,   dates)
    dd_crf5 = _per_crisis_dd(eq_crf5, dates)
    for key, _, _ in _WINDOWS:
        dk = dd_k5.get(key, 0.0)
        dc = dd_crf5.get(key, 0.0)
        print(f"{key:28s}  {dk:7.3f}%  {dc:9.3f}%  {dc-dk:+6.3f}%")

    # ── defend-yield decomposition ────────────────────────────────────────────
    print()
    print("── Defend-state yield decomposition (KODS-5 signal) ──")
    kods5_sig = _kods_signal(susde_rets_full, 5, r_f_daily)
    dy = _defend_yield_comparison(kods5_sig)
    print(f"  KODS defend APY : {dy['kods_defend_apy_pct']:.3f}%/yr "
          f"(50% rates + 25% RWA + 25% cash)")
    print(f"  CRF  defend APY : {dy['crf_defend_apy_pct']:.3f}%/yr "
          f"(75% rates + 25% RWA)")
    print(f"  Δ defend APY    : +{dy['delta_defend_apy_pp']:.3f} pp")
    print(f"  Defend days     : {dy['defend_days']} / {dy['total_days']}")
    print(f"  → Expected portfolio APY lift: +{dy['expected_portfolio_apy_lift_pp']:.4f} pp")

    # ── honesty caveats ───────────────────────────────────────────────────────
    print()
    print("── CAVEATS ──")
    print("1. FIXTURE (L0): σ²≈0 in calm periods → signal is binary mu/r_f gate.")
    print("   Calmar differences between configs are small on this fixture.")
    print("2. #32 (CFPT) finding: on REAL books, positive-drift de-risk HURTS.")
    print("   KODS is -1.97 ΔCalmar on real panel; ECDR(10/30) only survivor (+0.44).")
    print("   CRF improves within the de-risk family but does NOT solve the FP-tax.")
    print("3. CRF APY gain is small (~+0.07 pp) because defend days are ~12% of time.")
    print("4. EVIDENCE LEVEL: L0 (synthetic fixture). NOT realized, NOT live.")
    print()
    print("── VERDICT ──")
    # Find best CRF delta
    best_pair = max(pairs, key=lambda p: results[p[0]]["full"]["calmar"] - results[p[1]]["full"]["calmar"])
    bname, basname = best_pair
    best_delta = results[bname]["full"]["calmar"] - results[basname]["full"]["calmar"]
    print(f"Best CRF improvement: {bname} vs {basname}: ΔCalmar = {best_delta:+.3f}")
    if best_delta > 0.05:
        verdict = "MARGINAL_POSITIVE (fixture only; real-data test blocked — #32 caveat)"
    elif best_delta > 0:
        verdict = "NEAR_NEUTRAL (improvement too small to trust on fixture alone)"
    else:
        verdict = "NEUTRAL_OR_NEGATIVE"
    print(f"Verdict: {verdict}")
    print()
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True")


if __name__ == "__main__":
    main()
