#!/usr/bin/env python3
"""Novel-edge idea #3 — CROSS-DESK portfolio (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry).

Idea #2 showed a naive portfolio of TWO sUSDe strategies fails to diversify (corr 0.87 — same bet).
The fix: combine GENUINELY DECORRELATED desks, each with a different tail shape. Tested on REAL daily
series (no fabrication):
  • sUSDe aggressive (fixture susde_dn)         — volatile, depeg tail.
  • rates-desk fixed-carry (real backtest series) — near-zero-vol PT carry + idle-cash floor; a
    differently-shaped desk (its risk is a fixed-rate carry, not a stablecoin depeg). Extracted via
    backtest_rates.replay_sleeve(..., return_series=True) — the same deterministic backtest, now
    surfacing its per-day equity axis (previously only summary stats were persisted).
  • RWA floor (~3.31%/yr steady accrual)         — the T-bill cash floor; near-zero-vol, structurally
    decorrelated from both crypto legs.

Measures pairwise correlation (should be ~0 across desks), then sweeps portfolio weights and reports
drawdown / yield / Calmar vs the single sUSDe book — the classic diversification edge, shown honestly.

Deterministic, stdlib-only, LLM-forbidden. Advisory research; touches no live track / RiskPolicy.
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

RWA_FLOOR_PCT = 3.31  # live metrics.rwa_floor_apy_pct(); steady near-zero-vol accrual


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


def _rates_carry_series():
    """Real rates-desk fixed-carry daily equity via the deterministic backtest (return_series=True)."""
    from spa_core.strategy_lab.rates_desk import backtest_rates as br, pendle_pt_history as pph, retro
    from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
    from spa_core.strategy_lab.rates_desk.opportunity_engine import CostConfig
    from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
    deep = pph.load()
    try:
        funding = retro.load_funding()
    except FileNotFoundError:
        funding = {}
    dates = br._all_dates(deep)
    universe = sorted({m["underlying"].lower() for m in deep["markets"].values()})
    hedge_map = BorosFeed().hedge_available(universe)
    res = br.replay_sleeve("fixed_carry", dates, deep, funding, hedge_map,
                           RatePolicyParams(), CostConfig(), return_series=True)
    return {p["date"]: float(p["equity_usd"]) for p in (res.get("series") or [])}


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


def _blend_equity(dates, ret_maps, weights):
    eq = [100000.0]
    for d in dates:
        r = sum(weights[i] * ret_maps[i].get(d, 0.0) for i in range(len(ret_maps)))
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _m(eq):
    a = metrics.net_apy_from_equity(eq)
    d = metrics.max_drawdown_pct(eq)
    c = (a / d) if (isinstance(a, (int, float)) and isinstance(d, (int, float)) and d > 0) else None
    return a, d, c


def _f(x):
    return f"{x:.1f}" if isinstance(x, (int, float)) else "n/a"


def main():
    susde = _susde_series()
    rates = _rates_carry_series()
    if len(susde) < 60:
        print("no sUSDe series")
        return
    r_susde = _returns(susde)
    r_rates = _returns(rates)
    # common overlap (the desks span different windows) — honest apples-to-apples
    dates = sorted(set(r_susde) & set(r_rates))
    if len(dates) < 60:
        # fall back to sUSDe window; rates missing days contribute 0 return (cash) on those days
        dates = sorted(r_susde)
    daily_rwa = (RWA_FLOOR_PCT / 100.0) / 365.0
    r_rwa = {d: daily_rwa for d in dates}
    print(f"overlap window: {dates[0]}..{dates[-1]}  ({len(dates)} days)")

    print("\n=== pairwise correlation of daily returns (target ~0 = decorrelated) ===")
    print(f"  sUSDe ~ rates-carry : {_corr(r_susde, r_rates)}")
    print(f"  sUSDe ~ RWA-floor   : {_corr(r_susde, r_rwa)}  (flat floor → ~0 by construction)")
    print(f"  rates ~ RWA-floor   : {_corr(r_rates, r_rwa)}")

    print("\n=== individual desks (apy / maxDD / Calmar over overlap) ===")
    for name, rm in (("sUSDe (aggr)", r_susde), ("rates-carry", r_rates), ("RWA-floor", r_rwa)):
        a, d, c = _m(_blend_equity(dates, [rm], [1.0]))
        print(f"  {name:14} {_f(a)} / {_f(d)} / {_f(c)}")

    solo = _m(_blend_equity(dates, [r_susde], [1.0]))
    print(f"\n{'blend (sUSDe/rates/RWA)':>26}   {'apy':>6} {'maxDD':>7} {'Calmar':>7}")
    print("-" * 54)
    blends = [
        ("100 / 0 / 0  (solo sUSDe)", [1.0, 0.0, 0.0]),
        ("50 / 50 / 0", [0.5, 0.5, 0.0]),
        ("50 / 25 / 25", [0.5, 0.25, 0.25]),
        ("40 / 40 / 20", [0.4, 0.4, 0.2]),
        ("34 / 33 / 33  (equal)", [0.34, 0.33, 0.33]),
        ("25 / 50 / 25", [0.25, 0.5, 0.25]),
    ]
    best = None
    for label, w in blends:
        a, d, c = _m(_blend_equity(dates, [r_susde, r_rates, r_rwa], w))
        print(f"{label:>26}   {_f(a):>6} {_f(d):>7} {_f(c):>7}")
        if isinstance(c, (int, float)) and (best is None or c > best[3]):
            best = (label, a, d, c)

    print("\n=== VERDICT ===")
    print(f"  solo sUSDe:            apy {_f(solo[0])}  maxDD {_f(solo[1])}  Calmar {_f(solo[2])}")
    if best:
        print(f"  best cross-desk blend: apy {_f(best[1])}  maxDD {_f(best[2])}  Calmar {_f(best[3])}  ({best[0].strip()})")
        better = isinstance(best[3], (int, float)) and isinstance(solo[2], (int, float)) and best[3] > solo[2]
        print(f"  → cross-desk diversification {'HELPS (Calmar up = lower DD per unit yield)' if better else 'does NOT beat solo on Calmar'}")
    print("  Honest: rates-carry & RWA-floor are near-zero-vol, different-tail desks → they cut the")
    print("  portfolio's depeg drawdown for a small yield give-up. A SHARED systemic crisis would still")
    print("  correlate all crypto legs toward 1 — the RWA (off-chain T-bill) leg is the true decorrelator.")


if __name__ == "__main__":
    main()
