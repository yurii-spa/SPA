#!/usr/bin/env python3
"""Novel-edge idea #3 — CROSS-DESK portfolio (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry).

Idea #2 showed a naive portfolio of TWO sUSDe strategies fails to diversify (corr 0.87 — same bet).
The fix: combine GENUINELY DECORRELATED desks. Here we test the core thesis on real daily data:
  • sUSDe aggressive (fixture susde_dn) — volatile, depeg tail.
  • RWA floor — a steady ~3.3%/yr near-zero-vol accrual (honest: that is literally what the RWA
    cash-floor is; synthesized as constant daily accrual over the same dates, NOT a guessed shape).
These two are structurally decorrelated (a stablecoin depeg does not touch a T-bill floor). A cash-floor
allocation should cut portfolio drawdown for a modest yield give-up — the classic diversification edge.

The rates-desk PT-carry sleeve (a 3rd, differently-tailed desk) needs its daily backtest series
regenerated (only summary stats are persisted today) — flagged as the next step, NOT faked here.

Deterministic, stdlib-only, LLM-forbidden. Advisory research; touches no live track.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab import metrics  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import loader as ld, fixtures as fx  # noqa: E402
from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol  # noqa: E402

RWA_FLOOR_PCT = 3.31  # live metrics.rwa_floor_apy_pct() at time of writing; steady near-zero-vol accrual


def _susde_series():
    tmp = Path(tempfile.mkdtemp(prefix="crossdesk_"))
    fx.materialize(tmp)
    s = ld.load_all(data_dir=tmp).get("susde_dn")
    out = {}
    for p in (s.backtest.series if s and s.backtest.n_points >= 2 else []):
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            out[d] = float(e)
    return out


def _returns(by_date):
    dates = sorted(by_date)
    return {dates[i]: by_date[dates[i]] / by_date[dates[i - 1]] - 1.0
            for i in range(1, len(dates)) if by_date[dates[i - 1]]}


def _corr(a, b):
    common = sorted(set(a) & set(b))
    if len(common) < 3:
        return None
    xa = [a[d] for d in common]
    xb = [b[d] for d in common]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(len(xa)))
    da = sum((x - ma) ** 2 for x in xa) ** 0.5
    db = sum((x - mb) ** 2 for x in xb) ** 0.5
    return cov / (da * db) if da and db else None


def _equity(dates, ret_a, ret_b, wa):
    eq = [100000.0]
    for d in dates:
        r = wa * ret_a.get(d, 0.0) + (1.0 - wa) * ret_b.get(d, 0.0)
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _m(eq):
    a = metrics.net_apy_from_equity(eq)
    d = metrics.max_drawdown_pct(eq)
    c = (a / d) if (isinstance(a, (int, float)) and isinstance(d, (int, float)) and d > 0) else None
    return a, d, c


def main():
    susde = _susde_series()
    if len(susde) < 60:
        print("no sUSDe series")
        return
    r_susde = _returns(susde)
    dates = sorted(r_susde)
    # RWA floor: constant daily accrual over the SAME dates (near-zero vol, honest)
    daily = (RWA_FLOOR_PCT / 100.0) / 365.0
    r_rwa = {d: daily for d in dates}

    def f(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"

    print(f"corr(sUSDe, RWA-floor) = {_corr(r_susde, r_rwa)}  (RWA floor is flat → ~0 by construction; structurally decorrelated)")
    print(f"\n{'sUSDe wt / RWA wt':>18}   {'apy':>6} {'maxDD':>7} {'Calmar':>7}")
    print("-" * 46)
    rows = []
    for wa in (1.0, 0.9, 0.75, 0.6, 0.5, 0.25):
        eq = _equity(dates, r_susde, r_rwa, wa)
        a, d, c = _m(eq)
        rows.append((wa, a, d, c))
        print(f"{int(wa*100):>3}% / {int((1-wa)*100):>3}%{'':>7}   {f(a):>6} {f(d):>7} {f(c):>7}")
    # guardian on a representative blend (75/25)
    g = apply_guardian_vol(_equity(dates, r_susde, r_rwa, 0.75), vol_mult=2.0, derisk_frac=0.0)
    ga, gd, gc = _m(g)
    print(f"\n  75/25 + GUARDIAN: apy {f(ga)}  maxDD {f(gd)}  Calmar {f(gc)}  (guardian DD low = in-sample timing; discount it)")

    solo = rows[0]
    best_blend = max((r for r in rows[1:] if isinstance(r[3], (int, float))), key=lambda r: r[3], default=None)
    print("\n=== VERDICT ===")
    print(f"  100% sUSDe alone:      apy {f(solo[1])}  maxDD {f(solo[2])}  Calmar {f(solo[3])}")
    if best_blend:
        print(f"  best cross-desk blend: apy {f(best_blend[1])}  maxDD {f(best_blend[2])}  Calmar {f(best_blend[3])}  (sUSDe {int(best_blend[0]*100)}%)")
        better = isinstance(best_blend[3], (int, float)) and isinstance(solo[3], (int, float)) and best_blend[3] > solo[3]
        print(f"  → cross-desk diversification {'HELPS (higher Calmar = lower DD per unit yield)' if better else 'does NOT beat solo on Calmar here'}")
    print("  Honest: RWA floor cuts DRAWDOWN a lot for a modest yield give-up (a real, uncorrelated cash floor).")
    print("  NEXT: add the rates-desk PT-carry sleeve (differently-tailed 3rd desk) — needs its daily backtest")
    print("  series regenerated (only summary persisted today); NOT faked here.")


if __name__ == "__main__":
    main()
