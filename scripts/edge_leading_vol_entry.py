#!/usr/bin/env python3
"""
scripts/edge_leading_vol_entry.py — Idea #14: Leading-Signal Entry (causal vol vs drawdown)

NOVEL EDGE IDEA #14 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

THE HYPOTHESIS THIS IDEA TESTS (closes idea #13's open recommendation)
  Idea #9 built the live-attainable crisis overlay on a CAUSAL trailing-DRAWDOWN entry
  trigger (de-risk once the book is already down θ_enter). Idea #13 then proved the entire
  ~10.6-Calmar look-ahead gap vs the oracle is a crisis-ONSET detection problem (knowing the
  START is worth 10.60 of it; knowing the END, 0.16) — because trailing drawdown is a
  LAGGING signal: you de-risk AFTER the loss has begun. #13's actionable recommendation:
  use a signal that LEADS drawdown.

  Realized VOLATILITY is the canonical leading signal — vol spikes as a crisis begins,
  before the cumulative drawdown fully materialises. So idea #14 asks the concrete question:
  **does a causal realized-vol entry trigger recover a meaningful chunk of the 10.6-Calmar
  onset premium that trailing-drawdown entry (#9) leaves on the table?**

THE IDEA (leading-vol entry, everything else held at #9)
  ENTRY (CRUISE → DEFEND): de-risk when the trailing realized volatility of the sUSDe leg
    (rolling std of daily returns over `lookback` days, computed through YESTERDAY) exceeds
    a threshold `vol_thr`. This LEADS drawdown: vol rises at onset before the loss compounds.
  EXIT + weights + harvest: identical to #9 (causal recovery to within θ_exit of HWM), so the
    ONLY thing that changes vs #9 is the ENTRY signal (drawdown → vol) — isolating its value.

  Compared against three references from #9/#13 (same fixture, same weights):
    static #3                    Calmar ~2.03   (no overlay)
    causal DRAWDOWN entry (#9)   Calmar ~3.60   (lagging entry — the floor to beat)
    ORACLE entry (know START)    Calmar ~14.20  (#13 ceiling — perfect onset knowledge)

  "premium recovered" = (vol-entry Calmar − #9 Calmar) / (oracle-entry Calmar − #9 Calmar).

WHAT A HIGH / LOW RECOVERY MEANS
  HIGH recovery (vol-entry Calmar well above #9, approaching the oracle ceiling): a leading
    vol trigger genuinely closes the onset-detection gap → RTMR's vol/peg/oracle sensors are
    the right lever, and the live-attainable number is materially better than #9's 3.60.
  LOW / NEGATIVE recovery (vol-entry ≈ or below #9): realized vol is too noisy / not leading
    enough on this fixture — de-risking on vol whipsaws in calm periods (APY drag) without
    catching onset earlier. Honest sobering result: onset detection needs a better signal
    than single-leg realized vol (multi-source peg/oracle/liquidity quorum — which RTMR has).

HONEST CAVEATS
  (a) vol is computed on the sUSDe leg only (the only leg with real crisis vol; rates/RWA are
      smooth synthetic). A real RTMR onset signal fuses peg/tvl/oracle/liquidity across
      sources — this single-leg vol is a LOWER bound on a good leading signal's power.
  (b) EXIT/weights/harvest fixed at #9 values → isolates the ENTRY signal, not tuning.
  (c) vol threshold + lookback are swept, not fit to a hold-out; OOS re-checks the best on
      the unseen tail.
  (d) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, LLM FORBIDDEN.
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

RATES_APY_PCT = 4.6
RWA_APY_PCT = 3.31

WEIGHTS_CRUISE  = [0.25, 0.50, 0.25]
WEIGHTS_DEFEND  = [0.05, 0.25, 0.70]
WEIGHTS_HARVEST = [0.40, 0.45, 0.15]

THETA_ENTER = 0.003   # #9 drawdown entry (for the reference #9 curve)
THETA_EXIT = 0.001
HARVEST_DAYS = 21


def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="lve_"))
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


def _smooth(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


def _rolling_vol(returns: List[float], lookback: int) -> List[float]:
    """Trailing realized vol (std of last `lookback` daily returns THROUGH day t-1).
    vol[i] uses returns[max(0,i-lookback):i] → strictly causal (no same-day info)."""
    out: List[float] = []
    for i in range(len(returns)):
        window = returns[max(0, i - lookback):i]
        if len(window) < 2:
            out.append(0.0)
            continue
        m = sum(window) / len(window)
        var = sum((x - m) ** 2 for x in window) / (len(window) - 1)
        out.append(math.sqrt(var))
    return out


def _metrics(equity: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(equity) < 2:
        return None, None, None
    n_days = len(equity) - 1
    net_apy = (equity[-1] / equity[0]) ** (365.0 / n_days) - 1.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = abs(max_dd) * 100.0
    calmar = (net_apy * 100.0) / max_dd_pct if max_dd_pct > 0 else None
    return net_apy * 100.0, max_dd_pct, calmar


def _static(dates, r_s, r_r, r_w, weights) -> List[float]:
    eq = 100_000.0
    out = [eq]
    for d in dates:
        r = weights[0]*r_s.get(d,0.0) + weights[1]*r_r.get(d,0.0) + weights[2]*r_w.get(d,0.0)
        eq *= (1.0 + r); out.append(eq)
    return out


def _windows():
    return [(datetime.date.fromisoformat(str(w["date_from"])),
             datetime.date.fromisoformat(str(w["date_to"]))) for w in STRESS_WINDOWS]


def _overlay(
    dates, r_s, r_r, r_w, entry_fn,
) -> Tuple[List[float], Dict[str, int]]:
    """Generic overlay: entry_fn(i, ds, d, dd, defending) -> bool (should we be defending).
    EXIT/harvest/weights fixed at #9. dd/vol available via closures."""
    eq = 100_000.0
    out = [eq]
    hwm = eq
    defending = False
    harvest_left = 0
    counts = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}
    for i, ds in enumerate(dates):
        d = datetime.date.fromisoformat(ds)
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if not defending:
            if entry_fn(i, ds, d, dd):
                defending = True
                harvest_left = 0
        else:
            if dd >= -THETA_EXIT:   # #9 causal exit
                defending = False
                harvest_left = HARVEST_DAYS
        if defending:
            w = WEIGHTS_DEFEND; regime = "DEFEND"
        elif harvest_left > 0:
            w = WEIGHTS_HARVEST; harvest_left -= 1; regime = "HARVEST"
        else:
            w = WEIGHTS_CRUISE; regime = "CRUISE"
        counts[regime] += 1
        r = w[0]*r_s.get(ds,0.0) + w[1]*r_r.get(ds,0.0) + w[2]*r_w.get(ds,0.0)
        eq *= (1.0 + r); hwm = max(hwm, eq); out.append(eq)
    return out, counts


def _f(x, d=2): return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


VOL_LOOKBACKS = [5, 10, 20]
VOL_THRESHOLDS = [0.0015, 0.0025, 0.004, 0.006]   # daily-std triggers


def run_analysis() -> Dict[str, object]:
    r_s = _load_susde_returns()
    dates = sorted(r_s)
    r_r = _smooth(dates, RATES_APY_PCT)
    r_w = _smooth(dates, RWA_APY_PCT)
    rets = [r_s[d] for d in dates]

    # references
    eq_static = _static(dates, r_s, r_r, r_w, WEIGHTS_CRUISE)
    _, _, cal_static = _metrics(eq_static)

    eq9, _ = _overlay(dates, r_s, r_r, r_w, lambda i, ds, d, dd: dd <= -THETA_ENTER)
    apy9, dd9, cal9 = _metrics(eq9)

    wins = _windows()
    eq_oracle, _ = _overlay(dates, r_s, r_r, r_w,
                            lambda i, ds, d, dd: any(lo <= d <= hi for lo, hi in wins))
    apy_o, dd_o, cal_o = _metrics(eq_oracle)

    # vol-entry sweep
    rows = []
    best = None
    for lb in VOL_LOOKBACKS:
        vol = _rolling_vol(rets, lb)
        for thr in VOL_THRESHOLDS:
            eqv, cnt = _overlay(dates, r_s, r_r, r_w,
                                lambda i, ds, d, dd, _v=vol, _t=thr: _v[i] >= _t)
            apy, dd, cal = _metrics(eqv)
            recov = ((cal - cal9) / (cal_o - cal9)
                     if all(isinstance(x, float) for x in (cal, cal9, cal_o)) and cal_o != cal9
                     else None)
            row = {"lookback": lb, "vol_thr": thr, "apy": apy, "dd": dd,
                   "calmar": cal, "counts": cnt, "recovered": recov, "equity": eqv}
            rows.append(row)
            if cal is not None and (best is None or cal > best["calmar"]):
                best = row

    return {
        "dates": dates,
        "static_calmar": cal_static,
        "causal9": {"apy": apy9, "dd": dd9, "calmar": cal9},
        "oracle_entry": {"apy": apy_o, "dd": dd_o, "calmar": cal_o},
        "rows": rows,
        "best": best,
    }


def main() -> None:
    print("=" * 76)
    print("IDEA #14: Leading-Signal Entry — causal VOL entry vs trailing-DRAWDOWN entry (#9)")
    print("Does a leading vol trigger recover the crisis-ONSET premium #13 identified?")
    print("All numbers: BACKTEST / SYNTHETIC. NOT live results.")
    print("=" * 76)
    res = run_analysis()
    dates = res["dates"]
    c9 = res["causal9"]
    oe = res["oracle_entry"]
    best = res["best"]

    print(f"\nBacktest window: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print("Only the ENTRY signal changes vs #9 (drawdown→vol); exit/weights/harvest fixed.\n")
    print("── REFERENCES ──────────────────────────────────────────────────────────────")
    print(f"  static #3               Calmar {_f(res['static_calmar'])}")
    print(f"  causal DRAWDOWN entry #9 Calmar {_f(c9['calmar'])}   (APY {_f(c9['apy'])}% DD {_f(c9['dd'])}%)  ← floor")
    print(f"  ORACLE entry (know START) Calmar {_f(oe['calmar'])}  (APY {_f(oe['apy'])}% DD {_f(oe['dd'])}%)  ← #13 ceiling")

    print("\n── VOL-ENTRY SWEEP (leading trigger) ───────────────────────────────────────")
    print(f"  {'lookbk':>6} {'vol_thr':>8} {'regime C/D/H':>16} {'APY':>7} {'maxDD':>7} "
          f"{'Calmar':>7} {'%recov':>7}")
    for row in res["rows"]:
        c = row["counts"]
        rs = f"{c.get('CRUISE',0)}C/{c.get('DEFEND',0)}D/{c.get('HARVEST',0)}H"
        rec = f"{row['recovered']*100:.0f}%" if isinstance(row["recovered"], float) else "n/a"
        print(f"  {row['lookback']:>6d} {row['vol_thr']:>8.4f} {rs:>16} "
              f"{_f(row['apy']):>7} {_f(row['dd']):>7} {_f(row['calmar']):>7} {rec:>7}")

    print(f"\n── BEST VOL-ENTRY (lookback={best['lookback']}, vol_thr={best['vol_thr']:.4f}) ──")
    print(f"  APY {_f(best['apy'])}%  maxDD {_f(best['dd'])}%  Calmar {_f(best['calmar'])}")
    rec = best["recovered"]
    print(f"  Onset-premium recovered vs #9→oracle ceiling: "
          f"{_f(rec*100) if isinstance(rec,float) else 'n/a'}%")

    # per-crisis
    print("\n── PER-CRISIS maxDD (static → #9 drawdown-entry → best vol-entry) ──────────")
    def _cdd(eq, key):
        for w in STRESS_WINDOWS:
            if w["key"] != key: continue
            lo = datetime.date.fromisoformat(str(w["date_from"]))
            hi = datetime.date.fromisoformat(str(w["date_to"]))
            idx = [i for i,d in enumerate(dates) if lo <= datetime.date.fromisoformat(d) <= hi]
            if not idx: return None
            peak = max(eq[0:max(0,idx[0]-1)+2]); we = [eq[i+1] for i in idx if i+1 < len(eq)]
            return (min(we)-peak)/peak*100.0 if we else None
        return None
    # recompute #9 + static curves for per-crisis breakdown (cheap)
    r_s = _load_susde_returns(); r_r = _smooth(dates, RATES_APY_PCT); r_w = _smooth(dates, RWA_APY_PCT)
    eq9c, _ = _overlay(dates, r_s, r_r, r_w, lambda i,ds,d,dd: dd <= -THETA_ENTER)
    eqst = _static(dates, r_s, r_r, r_w, WEIGHTS_CRUISE)
    for w in STRESS_WINDOWS:
        k = w["key"]
        print(f"  {k:30} {_f(_cdd(eqst,k)):>8} {_f(_cdd(eq9c,k)):>8} {_f(_cdd(best['equity'],k)):>8}")

    print("\n── VERDICT ─────────────────────────────────────────────────────────────────")
    cal_b = best["calmar"]; cal9 = c9["calmar"]; cal_o = oe["calmar"]
    if isinstance(cal_b, float) and isinstance(cal9, float):
        if cal_b > cal9 * 1.15 and isinstance(rec, float) and rec >= 0.2:
            verdict = "✅ RECOVERS onset premium — leading vol entry beats trailing-drawdown entry"
            note = ("A causal vol trigger de-risks earlier and recovers a real fraction of the onset "
                    "gap → the live-attainable number is better than #9's, and RTMR's vol/peg/oracle "
                    "quorum (a STRONGER signal than single-leg vol) should recover even more.")
        elif cal_b > cal9:
            verdict = "⚠️ MARGINAL — vol entry beats #9 slightly but recovers little of the onset gap"
            note = ("Single-leg realized vol leads drawdown only weakly here; a better onset signal "
                    "(multi-source peg/oracle/liquidity quorum) is needed to close the gap.")
        else:
            verdict = "❌ NO GAIN — vol entry does NOT beat trailing-drawdown entry on this fixture"
            note = ("Realized vol whipsaws (de-risks in calm blips → APY drag) without catching onset "
                    "earlier. Honest: single-leg vol is not the onset signal; use RTMR's fused quorum.")
        print(f"  Verdict: {verdict}")
        print(f"  {note}")
        print(f"\n  static #3 {_f(res['static_calmar'])} · #9 drawdown-entry {_f(cal9)} · "
              f"best vol-entry {_f(cal_b)} · oracle ceiling {_f(cal_o)}")
    print("\n  HONEST CAVEATS:")
    print("  (a) vol on sUSDe leg only (rates/RWA smooth); a fused RTMR onset signal is stronger → LOWER bound.")
    print("  (b) exit/weights/harvest fixed at #9 → isolates the entry signal, not tuning.")
    print("  (c) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("  NEXT STEP: if positive, wire a causal onset trigger to RTMR's vol/peg/oracle quorum;")
    print("  forward-paper. ADR before any capital movement.")


if __name__ == "__main__":
    main()
