"""Normalized evaluation schema — one function for backtest, OOS slices and forward paper alike.

Every metric that cannot be computed on the given sample is None (not measured), never 0.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

BARS_PER_YEAR = {"1h": 8760, "2h": 4380, "4h": 2190, "8h": 1095, "12h": 730, "1D": 365, "1W": 52}


def _returns(eq: Sequence[float]) -> List[float]:
    return [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]


def max_drawdown(eq: Sequence[float]) -> Optional[float]:
    if len(eq) < 2:
        return None
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1 if peak > 0 else -1.0)
    return mdd


def evaluate(eq: Sequence[float], positions: Sequence[int], trades: List[dict], tf: str, *,
             cost_paid: float = 0.0, funding_paid: float = 0.0, equity0: Optional[float] = None) -> Dict:
    n = len(eq)
    if n < 3:
        return {"bars": n, "measured": False}
    ppy = BARS_PER_YEAR[tf]
    e0 = equity0 if equity0 is not None else eq[0]
    rets = _returns(eq)
    net = eq[-1] / e0 - 1
    years = (n - 1) / ppy
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / max(1, len(rets) - 1))
    dn = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in dn) / len(rets)) if rets else 0.0
    mdd = max_drawdown(eq)
    cagr = (eq[-1] / e0) ** (1 / years) - 1 if years >= 0.25 and eq[-1] > 0 else None
    wins = [t["ret"] for t in trades if t["ret"] > 0]
    losses = [t["ret"] for t in trades if t["ret"] <= 0]
    turns = sum(abs(positions[i] - positions[i - 1]) for i in range(1, len(positions)))
    return {
        "bars": n, "measured": True, "years": round(years, 3),
        "net_return": net,
        "cagr": cagr,
        "volatility": sd * math.sqrt(ppy) if sd else None,
        "sharpe": (mu / sd) * math.sqrt(ppy) if sd else None,
        "sortino": (mu / dsd) * math.sqrt(ppy) if dsd else None,
        "max_drawdown": mdd,
        "calmar": (cagr / abs(mdd)) if (cagr is not None and mdd) else None,
        "trades": len(trades),
        "win_rate": (len(wins) / len(trades)) if trades else None,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None,
        "expectancy": (sum(t["ret"] for t in trades) / len(trades)) if trades else None,
        "turnover_per_year": turns / years if years > 0 else None,
        "exposure": sum(1 for p in positions if p != 0) / len(positions),
        "cost_drag": cost_paid / e0,
        "funding_drag": funding_paid / e0,
    }


def slice_metrics(sim, bars, tf: str, lo_ms: Optional[int], hi_ms: Optional[int]) -> Dict:
    """Metrics of the part of an existing simulation whose bars open in [lo, hi)."""
    idx = [i for i, b in enumerate(bars) if (lo_ms is None or b.open_time >= lo_ms)
           and (hi_ms is None or b.open_time < hi_ms)]
    if len(idx) < 3:
        return {"bars": len(idx), "measured": False}
    a, z = idx[0], idx[-1]
    eq = sim.equity[a:z + 1]
    pos = sim.position[a:z + 1]
    lo_t, hi_t = bars[a].open_time, bars[z].open_time
    trades = [t for t in sim.trades if lo_t <= t["exit_time"] <= hi_t]
    return evaluate(eq, pos, trades, tf)


def correlation(a, b) -> Optional[float]:
    """Pearson correlation. Dicts ({day: return}) are aligned on their SHARED keys; sequences must
    already be aligned. Fewer than 10 common points ⇒ None (not measured)."""
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a) & set(b))
        a, b = [a[k] for k in keys], [b[k] for k in keys]
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def drawdown_overlap(eq_a: Sequence[float], eq_b: Sequence[float], threshold: float = -0.1) -> Optional[float]:
    """Share of bars where BOTH are in a drawdown deeper than `threshold` among bars where either is."""
    def under(eq):
        peak, out = eq[0], []
        for v in eq:
            peak = max(peak, v)
            out.append(v / peak - 1 <= threshold)
        return out
    n = min(len(eq_a), len(eq_b))
    if n < 10:
        return None
    ua, ub = under(eq_a[-n:]), under(eq_b[-n:])
    either = sum(1 for x, y in zip(ua, ub) if x or y)
    return (sum(1 for x, y in zip(ua, ub) if x and y) / either) if either else 0.0
