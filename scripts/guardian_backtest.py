#!/usr/bin/env python3
"""Dynamic Leverage Guardian — honest backtest of owner idea #1 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md).

Question: does a real-time de-risk overlay (cut exposure when a drawdown starts building) reduce a
strategy's realized max-drawdown WITHOUT killing its return — i.e. improve risk-adjusted return (Calmar)?

Method (deterministic, on the SAME 2.5yr real-history fixture the lab uses, no network):
  • load each strategy's daily backtest equity series;
  • apply a guardian that de-risks (exposure -> derisk_frac) once the drawdown from the running peak
    breaches derisk_dd, and re-enters (exposure -> 1.0) after recovery;
  • recompute realized APY / max-DD / Calmar for RAW vs GUARDED, and report the HONEST split:
    the first `derisk_dd` of any drawdown is UNAVOIDABLE (the guardian only reacts AFTER it observes
    the move — this is the "gap you cannot outrun"), what it prevents is the COMPOUNDING beyond that.
  • small parameter sweep -> report the best (by Calmar) guarded config per strategy.

stdlib-only, LLM-forbidden, deterministic. Advisory research; touches no live track.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab import metrics  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures as fx  # noqa: E402


def _equity_of(series):
    out = []
    for p in series:
        v = p.get("equity_usd", p.get("equity"))
        if v is not None:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def apply_guardian(equity, derisk_dd=0.04, derisk_frac=0.25, reenter_frac=0.5):
    """Return the guarded equity curve. exposure cuts to derisk_frac once drawdown from the guarded
    running peak breaches derisk_dd; restores to 1.0 once the curve recovers reenter_frac of the way
    back toward the peak. The guardian reacts to OBSERVED drawdown (honest: the first derisk_dd is
    unavoidable)."""
    if len(equity) < 2:
        return list(equity)
    guarded = [equity[0]]
    peak = equity[0]
    exposure = 1.0
    for i in range(1, len(equity)):
        raw_ret = equity[i] / equity[i - 1] - 1.0
        gr = raw_ret * exposure                       # only `exposure` of the move is taken
        new_eq = guarded[-1] * (1.0 + gr)
        guarded.append(new_eq)
        peak = max(peak, new_eq)
        dd = new_eq / peak - 1.0                       # <= 0
        if exposure >= 1.0 and dd <= -derisk_dd:
            exposure = derisk_frac                      # DE-RISK: cut exposure
        elif exposure < 1.0 and new_eq >= peak * (1.0 - derisk_dd * (1.0 - reenter_frac)):
            exposure = 1.0                              # RE-ENTER after recovery
    return guarded


def apply_guardian_vol(equity, lookback=10, vol_mult=2.0, derisk_frac=0.25, calm_mult=1.2):
    """PRE-EMPTIVE variant: de-risk when the strategy's own rolling realized volatility spikes above
    vol_mult × its trailing baseline (a regime signal that often LEADS the drawdown), re-enter when vol
    calms below calm_mult × baseline. Uses only the strategy's own returns (no exogenous feed in the
    fixture). Honest: this is the best self-contained proxy for a forward-signal guardian — a real RTMR
    guardian would use exogenous vol/funding/liquidity, potentially earlier still."""
    if len(equity) < lookback + 2:
        return list(equity)
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]

    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5

    guarded = [equity[0]]
    exposure = 1.0
    for i in range(len(rets)):
        gr = rets[i] * exposure
        guarded.append(guarded[-1] * (1.0 + gr))
        if i >= lookback:
            recent = _stdev(rets[i - lookback + 1: i + 1])
            base = _stdev(rets[max(0, i - 4 * lookback): i - lookback + 1]) or 1e-9
            if exposure >= 1.0 and recent > vol_mult * base:
                exposure = derisk_frac                 # regime turned hostile → cut BEFORE the loss compounds
            elif exposure < 1.0 and recent < calm_mult * base:
                exposure = 1.0                          # regime calmed → re-enter
    return guarded


def _metrics(equity):
    apy = metrics.net_apy_from_equity(equity)
    mdd = metrics.max_drawdown_pct(equity)
    cal = (apy / mdd) if (isinstance(apy, (int, float)) and isinstance(mdd, (int, float)) and mdd > 0) else None
    return apy, mdd, cal


def out_of_sample(loaded, split_date="2026-01-01"):
    """Honest overfitting check: pick the best vol-guardian params on the TRAIN half (dates < split),
    then apply those FIXED params to the unseen TEST half and see if the improvement HOLDS. If it
    collapses out-of-sample, the in-sample win was curve-fit."""
    vgrid = [(vm, fr) for vm in (1.5, 2.0, 3.0) for fr in (0.0, 0.25, 0.5)]

    def f(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"

    print("\n=== OUT-OF-SAMPLE (params fit on <%s, applied to >=%s) ===" % (split_date, split_date))
    print(f"{'strategy':20} {'TEST raw dd/cal':>16}   {'TEST guarded dd/cal':>20}   {'params(vm,fr)':>14}  holds?")
    print("-" * 84)
    for sid in sorted(loaded.keys()):
        s = loaded[sid]
        ser = s.backtest.series if s.backtest.n_points >= 2 else []
        train = _equity_of([p for p in ser if p.get("date", "") < split_date])
        test = _equity_of([p for p in ser if p.get("date", "") >= split_date])
        if len(train) < 40 or len(test) < 30:
            continue
        # fit on train
        best = None
        for vm, fr in vgrid:
            _, tdd, tcal = _metrics(apply_guardian_vol(train, vol_mult=vm, derisk_frac=fr))
            key = tcal if isinstance(tcal, (int, float)) else -1e9
            if best is None or key > best[0]:
                best = (key, vm, fr)
        _, vm, fr = best
        # apply FIXED params to test
        r_apy, r_dd, r_cal = _metrics(test)
        g_apy, g_dd, g_cal = _metrics(apply_guardian_vol(test, vol_mult=vm, derisk_frac=fr))
        holds = (isinstance(g_cal, (int, float)) and isinstance(r_cal, (int, float)) and g_cal >= r_cal) \
            or (isinstance(g_dd, (int, float)) and isinstance(r_dd, (int, float)) and g_dd <= r_dd)
        print(f"{sid:20} {f(r_dd)+'/'+f(r_cal):>16}   {f(g_dd)+'/'+f(g_cal):>20}   ({vm},{fr}){'':>4}  {'HOLDS' if holds else 'overfit'}")


def main():
    tmp = Path(__import__("tempfile").mkdtemp(prefix="guardian_bt_"))
    fx.materialize(tmp)
    loaded = ld.load_all(data_dir=tmp)

    grid = [(dd, fr) for dd in (0.02, 0.03, 0.04, 0.06) for fr in (0.0, 0.2, 0.35, 0.5)]
    vgrid = [(vm, fr) for vm in (1.5, 2.0, 3.0) for fr in (0.0, 0.25, 0.5)]

    def f(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"

    def best_over(eq, fn, params):
        best = None
        for p in params:
            g = fn(eq, *p)
            a, d, c = _metrics(g)
            key = c if isinstance(c, (int, float)) else -1e9
            if best is None or key > best[0]:
                best = (key, a, d, c, p)
        return best[1], best[2], best[3]  # apy, dd, cal

    print(f"{'strategy':20} {'RAW apy/dd/cal':>18}   {'REACTIVE(dd) apy/dd/cal':>26}   {'PRE-EMPTIVE(vol) apy/dd/cal':>28}")
    print("-" * 100)
    for sid in sorted(loaded.keys()):
        s = loaded[sid]
        eq = _equity_of(s.backtest.series if s.backtest.n_points >= 2 else [])
        if len(eq) < 30:
            continue
        r_apy, r_dd, r_cal = _metrics(eq)
        d_apy, d_dd, d_cal = best_over(eq, lambda e, dd, fr: apply_guardian(e, derisk_dd=dd, derisk_frac=fr), grid)
        v_apy, v_dd, v_cal = best_over(eq, lambda e, vm, fr: apply_guardian_vol(e, vol_mult=vm, derisk_frac=fr), vgrid)
        print(f"{sid:20} {f(r_apy)+'/'+f(r_dd)+'/'+f(r_cal):>18}   "
              f"{f(d_apy)+'/'+f(d_dd)+'/'+f(d_cal):>26}   {f(v_apy)+'/'+f(v_dd)+'/'+f(v_cal):>28}")
    print()
    print("REACTIVE = de-risk after drawdown breaches a threshold. PRE-EMPTIVE = de-risk when own realized")
    print("vol spikes above baseline (a regime signal that often LEADS the loss). Higher Calmar = better")
    print("risk-adjusted. Honest limits: gap moves are still unavoidable; a real RTMR guardian would use")
    print("exogenous vol/funding/liquidity (not in this equity-only fixture) — potentially earlier still.")

    out_of_sample(loaded)


if __name__ == "__main__":
    main()
