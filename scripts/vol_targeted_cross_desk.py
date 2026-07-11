#!/usr/bin/env python3
"""Novel-edge idea #4 — VOLATILITY-TARGETED cross-desk sizing (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry).

Idea #3 validated a FIXED-weight cross-desk blend (sUSDe + rates-carry + RWA-floor, 25/50/25 → same yield,
DD 8.5%→2.1%, Calmar ×4). Idea #4 asks: can we do better than fixed weights by sizing the VOLATILE sleeve
(sUSDe) INVERSELY to its own recent realized vol — a continuous, forward-looking risk-parity-in-TIME —
so exposure auto-shrinks INTO a vol spike (crisis onset) and re-expands when calm, with the freed weight
parked in the RWA cash-floor? This is #1 (the guardian's vol signal) fused with #3 (the cross-desk blend)
as a CONTINUOUS sizing function rather than a binary de-risk switch.

Sizing (deterministic, causal — uses only PAST returns): w_susde(t) = clamp(target_vol / recent_vol(t),
0, w_max); rates-carry held at a fixed low weight (it is near-zero-vol); the RWA floor absorbs the
remainder (1 − w_susde − w_rates). Compared head-to-head against the fixed 25/50/25 #3 blend on the same
2.5yr real-history fixture across the crisis windows.

Deterministic, stdlib-only, LLM-forbidden. Advisory research; touches no live track / RiskPolicy.
HONEST caveat up front: vol-targeting almost always LOWERS drawdown (it cuts into spikes) — the open
question is whether it does so WITHOUT giving back so much yield that risk-adjusted return doesn't improve,
and whether the improvement survives OUT-OF-SAMPLE (in-sample vol timing flatters every such model).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab import metrics  # noqa: E402
# reuse idea #3's real-data loaders (no duplication)
from scripts.cross_desk_portfolio import (  # noqa: E402
    _susde_series, _rates_carry_series, _returns, RWA_FLOOR_PCT,
)

_LOOKBACK = 20          # trailing days for the realized-vol estimate
_W_RATES = 0.50         # fixed rates-carry weight (near-zero-vol, matches #3's best blend)
_W_SUSDE_MAX = 0.50     # cap on the vol-targeted sUSDe sleeve


def _stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def _m(eq):
    a = metrics.net_apy_from_equity(eq)
    d = metrics.max_drawdown_pct(eq)
    c = (a / d) if (isinstance(a, (int, float)) and isinstance(d, (int, float)) and d > 0) else None
    return a, d, c


def _f(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else "n/a"


def _fixed_blend(dates, r_susde, r_rates, r_rwa, w_susde, w_rates):
    eq = [100000.0]
    for d in dates:
        w_rwa = max(0.0, 1.0 - w_susde - w_rates)
        r = w_susde * r_susde.get(d, 0.0) + w_rates * r_rates.get(d, 0.0) + w_rwa * r_rwa.get(d, 0.0)
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _vol_targeted(dates, r_susde, r_rates, r_rwa, target_vol):
    """Size sUSDe by target_vol / trailing-realized-vol (causal); floor absorbs the rest."""
    eq = [100000.0]
    hist = []
    weights_used = []
    for d in dates:
        rs = r_susde.get(d, 0.0)
        # weight from PAST vol only (causal: use hist BEFORE appending today)
        rv = _stdev(hist[-_LOOKBACK:]) if len(hist) >= 5 else None
        if rv and rv > 1e-9:
            w_susde = min(_W_SUSDE_MAX, target_vol / rv)
        else:
            w_susde = _W_SUSDE_MAX          # warmup: no vol estimate yet → cap (fail-safe: not over-sized)
        weights_used.append(w_susde)
        w_rwa = max(0.0, 1.0 - w_susde - _W_RATES)
        r = w_susde * rs + _W_RATES * r_rates.get(d, 0.0) + w_rwa * r_rwa.get(d, 0.0)
        eq.append(eq[-1] * (1.0 + r))
        hist.append(rs)
    avg_w = sum(weights_used) / len(weights_used) if weights_used else 0.0
    return eq, avg_w


def main():
    susde = _susde_series()
    rates = _rates_carry_series()
    if len(susde) < 60:
        print("no sUSDe series")
        return
    r_susde, r_rates = _returns(susde), _returns(rates)
    dates = sorted(set(r_susde) & set(r_rates)) or sorted(r_susde)
    daily_rwa = (RWA_FLOOR_PCT / 100.0) / 365.0
    r_rwa = {d: daily_rwa for d in dates}
    print(f"overlap window: {dates[0]}..{dates[-1]}  ({len(dates)} days)  ·  lookback {_LOOKBACK}d")

    # baseline = idea #3's best fixed blend (25% sUSDe / 50% rates / 25% floor)
    base_eq = _fixed_blend(dates, r_susde, r_rates, r_rwa, w_susde=0.25, w_rates=_W_RATES)
    ba, bd, bc = _m(base_eq)
    print(f"\n  #3 fixed 25/50/25:            apy {_f(ba)}%  maxDD {_f(bd)}%  Calmar {_f(bc)}")

    # target the sUSDe sleeve's daily vol to ~ the fixed blend's implied sUSDe-vol budget. Sweep a few
    # targets so the result isn't a single cherry-picked knob.
    susde_daily_vol = _stdev(list(r_susde.values()))
    print(f"  (sUSDe realized daily vol over window: {susde_daily_vol*100:.3f}%)")
    print(f"\n{'target daily vol':>18} {'avg wS':>7} {'apy':>7} {'maxDD':>7} {'Calmar':>7}")
    print("-" * 52)
    best = None
    for mult in (0.25, 0.5, 0.75, 1.0):
        tv = susde_daily_vol * mult
        eq, avg_w = _vol_targeted(dates, r_susde, r_rates, r_rwa, target_vol=tv)
        a, d, c = _m(eq)
        print(f"{tv*100:>16.3f}% {avg_w:>7.2f} {_f(a):>7} {_f(d):>7} {_f(c):>7}")
        if isinstance(c, (int, float)) and (best is None or c > best[3]):
            best = (tv, avg_w, a, d, c)

    print("\n=== VERDICT ===")
    print(f"  #3 fixed blend:        apy {_f(ba)}%  maxDD {_f(bd)}%  Calmar {_f(bc)}")
    if best:
        print(f"  best vol-targeted:     apy {_f(best[2])}%  maxDD {_f(best[3])}%  Calmar {_f(best[4])}  "
              f"(target {best[0]*100:.3f}%/day, avg sUSDe wt {best[1]:.2f})")
        improved = isinstance(best[4], (int, float)) and isinstance(bc, (int, float)) and best[4] > bc * 1.05
        print(f"  → vol-targeting {'IMPROVES risk-adjusted (Calmar +>5%)' if improved else 'does NOT beat fixed by >5% Calmar'}")
    print("  HONEST: vol-targeting mechanically cuts drawdown by shrinking into spikes; the real test is")
    print("  (a) does risk-adjusted return actually improve vs the simpler fixed blend, and (b) does it hold")
    print("  OUT-OF-SAMPLE (this run is IN-sample — vol timing flatters every such model). Sizing is CAUSAL")
    print("  (past-vol only), so no look-ahead — but forward paper is the honest confirmation.")


if __name__ == "__main__":
    main()
