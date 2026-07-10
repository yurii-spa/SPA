#!/usr/bin/env python3
"""Novel-edge idea #2 — correlation-aware TIER COMPOSITION (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry).

Thesis: an aggressive TIER should be a diversified PORTFOLIO of surviving strategies, not one book.
Combining low-correlation survivors should give a better risk-adjusted return (lower drawdown per unit
of yield) than any single strategy — the classic diversification edge — and applying the Guardian on top
of the PORTFOLIO should tame it further. Test it honestly on the 2.5yr real-history fixture.

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


def _series_by_date(s):
    out = {}
    for p in (s.backtest.series if s.backtest.n_points >= 2 else []):
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            try:
                out[d] = float(e)
            except (TypeError, ValueError):
                pass
    return out


def _returns_by_date(by_date):
    dates = sorted(by_date)
    rets = {}
    for i in range(1, len(dates)):
        prev = by_date[dates[i - 1]]
        if prev:
            rets[dates[i]] = by_date[dates[i]] / prev - 1.0
    return rets


def _stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


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


def _portfolio_equity(rets_list, weights):
    all_dates = sorted(set().union(*[set(r) for r in rets_list]))
    eq = [100000.0]
    for d in all_dates:
        r = sum(weights[i] * rets_list[i].get(d, 0.0) for i in range(len(rets_list)))
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _metrics(eq):
    apy = metrics.net_apy_from_equity(eq)
    dd = metrics.max_drawdown_pct(eq)
    cal = (apy / dd) if (isinstance(apy, (int, float)) and isinstance(dd, (int, float)) and dd > 0) else None
    return apy, dd, cal


def main():
    tmp = Path(tempfile.mkdtemp(prefix="tier_pf_"))
    fx.materialize(tmp)
    loaded = ld.load_all(data_dir=tmp)

    # survivors = strategies with a positive realized backtest APY and non-catastrophic DD
    cand = {}
    for sid in sorted(loaded):
        eq = list(_series_by_date(loaded[sid]).values())
        if len(eq) < 60:
            continue
        apy, dd, _ = _metrics(eq)
        if isinstance(apy, (int, float)) and apy > 0 and isinstance(dd, (int, float)) and dd < 20:
            cand[sid] = loaded[sid]
    print("survivor candidates (positive APY, DD<20%):", list(cand.keys()))
    if len(cand) < 2:
        print("need >=2 survivors to diversify; abort.")
        return

    rmap = {sid: _returns_by_date(_series_by_date(cand[sid])) for sid in cand}

    print("\n=== pairwise correlation of daily returns ===")
    sids = list(cand)
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            c = _corr(rmap[sids[i]], rmap[sids[j]])
            print(f"  {sids[i]:16} ~ {sids[j]:16}: corr={c:.2f}" if c is not None else f"  {sids[i]} ~ {sids[j]}: n/a")

    def f(x):
        return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"

    print("\n=== individual survivors (apy / maxDD / Calmar) ===")
    for sid in sids:
        a, d, c = _metrics(list(_series_by_date(cand[sid]).values()))
        print(f"  {sid:18} {f(a)} / {f(d)} / {f(c)}")

    rets_list = [rmap[s] for s in sids]
    # equal weight
    ew = [1.0 / len(sids)] * len(sids)
    ew_eq = _portfolio_equity(rets_list, ew)
    ea, ed, ec = _metrics(ew_eq)
    # inverse-vol weight (risk parity-lite): weight ~ 1/vol
    vols = [_stdev(list(rmap[s].values())) or 1e-9 for s in sids]
    inv = [1.0 / v for v in vols]
    tot = sum(inv)
    iw = [x / tot for x in inv]
    iw_eq = _portfolio_equity(rets_list, iw)
    ia, idd, ic = _metrics(iw_eq)
    # guardian on the equal-weight portfolio
    g_eq = apply_guardian_vol(ew_eq, vol_mult=2.0, derisk_frac=0.0)
    ga, gd, gc = _metrics(g_eq)

    print("\n=== PORTFOLIO (diversification edge) ===")
    print(f"  equal-weight        : {f(ea)} / {f(ed)} / {f(ec)}")
    print(f"  inverse-vol weight  : {f(ia)} / {f(idd)} / {f(ic)}")
    print(f"  equal-weight+GUARDIAN: {f(ga)} / {f(gd)} / {f(gc)}")
    best_single_cal = max((c for c in (_metrics(list(_series_by_date(cand[s]).values()))[2] for s in sids)
                           if isinstance(c, (int, float))), default=None)
    print(f"\n  best single-strategy Calmar: {f(best_single_cal)}")
    print("  Diversification helps IF a portfolio Calmar > best single Calmar (lower DD per unit yield).")
    print("  Honest: same fixture history; a portfolio is only as diversified as the correlations are LOW,")
    print("  and shared tail events (systemic depeg/liquidation) correlate to 1 in a crisis — shown, not hidden.")


if __name__ == "__main__":
    main()
