"""Qualification, ranking and de-duplication — never by total return alone.

BACKTEST_QUALIFIED requires ALL of (each failure is recorded as a rejection reason):
  q_oos_sharpe      out-of-sample Sharpe ≥ 0.8
  q_is_sharpe       in-sample Sharpe ≥ 0.4 (the IS window contains the 2018 and 2022 bear markets)
  q_cost_3x         out-of-sample Sharpe ≥ 0.5 with fees+slippage tripled
  q_trades          ≥ 15 round trips over the full history (one lucky trade is not evidence)
  q_drawdown        full-history max drawdown no worse than -55 %
  q_vs_benchmark    full Calmar ≥ buy-and-hold Calmar, OR max drawdown ≥ 15 pp shallower than buy-and-hold
  q_neighbours      median OOS Sharpe of its family siblings (same timeframe + execution model) ≥ 0.3
                    — a lone good grid point among bad neighbours is curve-fit, not an edge

Score = the most pessimistic of (IS Sharpe, OOS Sharpe, OOS Sharpe at 3× costs).
The shortlist then drops any candidate whose OOS daily returns correlate > 0.85 with one already
picked — ten top-ranked strategies that are the same trade are ONE strategy.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from .metrics import correlation, evaluate

THRESHOLDS = {"oos_sharpe": 0.8, "is_sharpe": 0.4, "cost3x_sharpe": 0.5, "trades": 15,
              "max_drawdown": -0.55, "calmar_margin_pp": 0.15, "neighbour_sharpe": 0.3,
              "dedupe_corr": 0.85}


def benchmark(bars, tf: str) -> Dict:
    eq = [b.close / bars[0].close for b in bars]
    return evaluate(eq, [1] * len(eq), [], tf)


def _g(d, *ks):
    for k in ks:
        d = (d or {}).get(k)
    return d


def score(r: Dict) -> Optional[float]:
    xs = [_g(r, "in_sample", "sharpe"), _g(r, "out_of_sample", "sharpe"),
          _g(r, "cost_sensitivity", "3x", "oos_sharpe")]
    return None if any(x is None for x in xs) else min(xs)


def qualify(results: List[Dict], benchmarks: Dict[str, Dict]) -> List[Dict]:
    sib = defaultdict(list)
    for r in results:
        d = r["definition"]
        sib[(d["family"], d["timeframe"], d["exec_model"])].append(_g(r, "out_of_sample", "sharpe"))
    out = []
    T = THRESHOLDS
    for r in results:
        d = r["definition"]
        bm = benchmarks.get(d["timeframe"], {})
        fails = []
        if (_g(r, "out_of_sample", "sharpe") or -9) < T["oos_sharpe"]:
            fails.append("q_oos_sharpe")
        if (_g(r, "in_sample", "sharpe") or -9) < T["is_sharpe"]:
            fails.append("q_is_sharpe")
        if (_g(r, "cost_sensitivity", "3x", "oos_sharpe") or -9) < T["cost3x_sharpe"]:
            fails.append("q_cost_3x")
        if (_g(r, "full", "trades") or 0) < T["trades"]:
            fails.append("q_trades")
        if (_g(r, "full", "max_drawdown") or -1) < T["max_drawdown"]:
            fails.append("q_drawdown")
        cal, bcal = _g(r, "full", "calmar"), bm.get("calmar")
        mdd, bmdd = _g(r, "full", "max_drawdown"), bm.get("max_drawdown")
        beats = (cal is not None and bcal is not None and cal >= bcal) or \
                (mdd is not None and bmdd is not None and mdd >= bmdd + T["calmar_margin_pp"])
        if not beats:
            fails.append("q_vs_benchmark")
        ns = [x for x in sib[(d["family"], d["timeframe"], d["exec_model"])] if x is not None]
        if not ns or statistics.median(ns) < T["neighbour_sharpe"]:
            fails.append("q_neighbours")
        out.append({"id": r["id"], "score": score(r), "qualified": not fails, "rejections": fails})
    return out


def shortlist(results: List[Dict], quals: List[Dict], limit: int = 10) -> List[Dict]:
    by_id = {r["id"]: r for r in results}
    ranked = sorted((q for q in quals if q["qualified"] and q["score"] is not None),
                    key=lambda q: q["score"], reverse=True)
    picked: List[Dict] = []
    for q in ranked:
        rets = by_id[q["id"]].get("oos_daily_returns") or {}
        twin = next((p for p in picked
                     if (correlation(rets, by_id[p["id"]].get("oos_daily_returns") or {}) or 0) > THRESHOLDS["dedupe_corr"]),
                    None)
        if twin:
            continue
        picked.append({"id": q["id"], "score": q["score"]})
        if len(picked) >= limit:
            break
    return picked


def correlation_matrix(results: List[Dict], ids: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    by_id = {r["id"]: r for r in results}
    return {a: {b: (None if a == b else correlation(by_id[a]["oos_daily_returns"], by_id[b]["oos_daily_returns"]))
                for b in ids} for a in ids}
