"""Backtest runner — the SAME signal functions and execution model the forward paper uses.

Validation per candidate:
  * in-sample (bars before OOS_START) vs out-of-sample (from OOS_START) — parameters are fixed grid
    points chosen before this run, so OOS is genuinely unseen by any fitting step;
  * walk-forward stability: calendar-year slices of the one continuous simulation;
  * regime slices (bull / bear / sideways / stress), labels from regime.RegimeIndex (causal);
  * cost sensitivity: the whole simulation re-run at 0×, 1×, 2×, 3× fees+slippage;
  * funding included for the perpetual model; liquidations counted.
Everything is written with a run manifest: data range + data hash, code version, split, costs.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import market_data as md
from .execution import EXEC_MODELS, simulate
from .metrics import evaluate, slice_metrics
from .regime import RegimeIndex
from .strategies import Candidate, registry

OOS_START_MS = calendar.timegm((2023, 1, 1, 0, 0, 0)) * 1000
COST_MULTS = (0.0, 1.0, 2.0, 3.0)
PKG = Path(__file__).resolve().parent


def code_version() -> str:
    """sha256 over the package's own source files — the code identity recorded with every result."""
    h = hashlib.sha256()
    for p in sorted(PKG.glob("*.py")):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()[:16]


def data_ref(bars) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b.open_time},{b.open},{b.high},{b.low},{b.close}".encode())
    return h.hexdigest()[:16]


def _years(bars) -> List[int]:
    return sorted({datetime.fromtimestamp(b.open_time / 1000, tz=timezone.utc).year for b in bars})


def run_candidate(cand: Candidate, bars, *, funding=None, regimes: Optional[RegimeIndex] = None) -> Dict:
    model = EXEC_MODELS[cand.exec_model]
    tf_ms = md.TF_MS[cand.timeframe]
    targets = cand.signal(bars)
    sims = {m: simulate(bars, targets, model, tf_ms=tf_ms, funding=funding, cost_mult=m) for m in COST_MULTS}
    base = sims[1.0]
    full = evaluate(base.equity, base.position, base.trades, cand.timeframe,
                    cost_paid=base.cost_paid, funding_paid=base.funding_paid)
    res = {"id": cand.id, "definition": cand.definition(), "def_hash": cand.def_hash,
           "full": full, "liquidations": base.liquidations,
           "in_sample": slice_metrics(base, bars, cand.timeframe, None, OOS_START_MS),
           "out_of_sample": slice_metrics(base, bars, cand.timeframe, OOS_START_MS, None),
           "by_year": {}, "by_regime": {}, "cost_sensitivity": {}}
    for y in _years(bars):
        lo = calendar.timegm((y, 1, 1, 0, 0, 0)) * 1000
        hi = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) * 1000
        m = slice_metrics(base, bars, cand.timeframe, lo, hi)
        if m.get("measured"):
            res["by_year"][str(y)] = {k: m[k] for k in ("net_return", "sharpe", "max_drawdown", "trades")}
    if regimes is not None:
        keys = regimes.keys_for(bars)
        for reg in ("bull", "bear", "sideways", "stress"):
            idx = [i for i, k in enumerate(keys) if k == reg and i > 0]
            if len(idx) < 30:
                continue
            r = [base.equity[i] / base.equity[i - 1] - 1 for i in idx]
            mu = sum(r) / len(r)
            res["by_regime"][reg] = {"bars": len(idx), "mean_bar_return": mu,
                                     "cum_return": _prod(r) - 1}
    for m, s in sims.items():
        oos = slice_metrics(s, bars, cand.timeframe, OOS_START_MS, None)
        res["cost_sensitivity"][f"{m:g}x"] = {"oos_net_return": oos.get("net_return"),
                                               "oos_sharpe": oos.get("sharpe")}
    # daily OOS returns (for inter-strategy correlation) — compact
    res["oos_daily_returns"] = _daily_returns(base, bars, OOS_START_MS)
    res["oos_positions_daily"] = _daily_positions(base, bars, OOS_START_MS)
    return res


def _prod(xs):
    p = 1.0
    for x in xs:
        p *= 1 + x
    return p


def _daily_returns(sim, bars, lo_ms):
    """{UTC day index: return since the previous day present} — keyed, so two candidates are compared
    on the SAME days even when their timeframes lost different buckets to data gaps."""
    last, out, prev = {}, {}, None
    for i, b in enumerate(bars):
        if b.open_time >= lo_ms:
            last[b.open_time // 86_400_000] = sim.equity[i]
    for d in sorted(last):
        if prev is not None and d - prev[0] == 1:
            out[str(d)] = round(last[d] / prev[1] - 1, 7)
        prev = (d, last[d])
    return out


def _daily_positions(sim, bars, lo_ms):
    last = {}
    for i, b in enumerate(bars):
        if b.open_time >= lo_ms:
            last[b.open_time // 86_400_000] = sim.position[i]
    return [last[d] for d in sorted(last)]


def run_all(conn, *, symbol: str = "BTCUSDT", candidates: Optional[List[Candidate]] = None,
            now_ms: Optional[int] = None) -> Dict:
    candidates = candidates or registry()
    b1h = md.load_1h(conn, symbol)
    series = {tf: md.aggregate(b1h, tf) for tf in {c.timeframe for c in candidates}}
    days = series.get("1D") or md.aggregate(b1h, "1D")
    regimes = RegimeIndex(days)
    funding = md.funding_series(conn, symbol)
    results = [run_candidate(c, series[c.timeframe], funding=funding if EXEC_MODELS[c.exec_model].funding else None,
                             regimes=regimes) for c in candidates]
    return {
        "manifest": {
            "generated_at_ms": now_ms, "code_version": code_version(), "symbol": symbol,
            "source": md.SOURCE, "base_tf": "1h",
            "data_from_ms": b1h[0].open_time if b1h else None, "data_to_ms": b1h[-1].open_time if b1h else None,
            "bars_1h": len(b1h), "data_ref_1h": data_ref(b1h), "gaps_1h": len(md.gaps_1h(b1h)),
            "funding_points": len(funding), "oos_start_ms": OOS_START_MS, "cost_mults": COST_MULTS,
            "exec_models": {k: vars(v) for k, v in EXEC_MODELS.items()},
            "timing": "signal on bar close t, fill on bar open t+1",
        },
        "results": results,
    }


def save(result: dict, path: Path) -> None:
    from spa_core.utils.atomic import atomic_save
    atomic_save(result, str(path), indent=None)
