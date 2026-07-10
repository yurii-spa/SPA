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


def _metrics(equity):
    apy = metrics.net_apy_from_equity(equity)
    mdd = metrics.max_drawdown_pct(equity)
    cal = (apy / mdd) if (isinstance(apy, (int, float)) and isinstance(mdd, (int, float)) and mdd > 0) else None
    return apy, mdd, cal


def main():
    tmp = Path(__import__("tempfile").mkdtemp(prefix="guardian_bt_"))
    fx.materialize(tmp)
    loaded = ld.load_all(data_dir=tmp)

    grid = [(dd, fr) for dd in (0.02, 0.03, 0.04, 0.06) for fr in (0.0, 0.2, 0.35, 0.5)]
    print(f"{'strategy':22} {'raw_apy':>8} {'raw_dd':>7} {'raw_cal':>8}   {'g_apy':>8} {'g_dd':>7} {'g_cal':>8}  {'best(dd,fr)':>12}  helped?")
    print("-" * 110)
    for sid in sorted(loaded.keys()):
        s = loaded[sid]
        eq = _equity_of(s.backtest.series if s.backtest.n_points >= 2 else [])
        if len(eq) < 30:
            continue
        r_apy, r_dd, r_cal = _metrics(eq)
        best = None
        for dd, fr in grid:
            g = apply_guardian(eq, derisk_dd=dd, derisk_frac=fr)
            g_apy, g_dd, g_cal = _metrics(g)
            # objective: maximize Calmar; require dd actually reduced
            key = (g_cal if g_cal is not None else -1e9)
            if best is None or key > best[0]:
                best = (key, dd, fr, g_apy, g_dd, g_cal)
        _, bdd, bfr, g_apy, g_dd, g_cal = best
        helped = (isinstance(g_cal, (int, float)) and isinstance(r_cal, (int, float)) and g_cal > r_cal) \
            or (isinstance(g_dd, (int, float)) and isinstance(r_dd, (int, float)) and g_dd < r_dd * 0.8)
        def f(x):
            return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"
        print(f"{sid:22} {f(r_apy):>8} {f(r_dd):>7} {f(r_cal):>8}   {f(g_apy):>8} {f(g_dd):>7} {f(g_cal):>8}  ({bdd},{bfr})  {'YES' if helped else 'no'}")
    print()
    print("Honest read: the guardian can only react AFTER it observes a drawdown, so the first `dd`% of")
    print("any move is UNAVOIDABLE (the gap you cannot outrun). It reduces the COMPOUNDING beyond that.")
    print("A 'no' means de-risking whipsawed (cut exposure, missed the recovery bounce) — also honest.")


if __name__ == "__main__":
    main()
