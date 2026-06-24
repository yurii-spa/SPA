"""
spa_core/backtesting/tier1/oos.py — out-of-sample (walk-forward) check for YIELD.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden.

The classic walk-forward validator scores in-sample vs out-of-sample Sharpe. But for
near-deterministic stablecoin yield, Sharpe is degenerate (see tier1/evaluator regimes),
so the meaningful OOS question is about YIELD, not volatility:

    "Does the strategy's blended net yield in the HELD-OUT (recent) window still match its
     in-sample yield, or did it only look good because of an early high-yield period?"

Using the real per-protocol DeFiLlama APY series (data/bee/defillama_apy_history.json),
this computes a strategy's allocation-weighted blended APY over an in-sample window (first
`split`) vs an out-of-sample window (the remainder), aligned on a common date axis
(forward-filled — series start on different dates). A strategy passes OOS when its OOS
yield holds at >= (1 - tolerance) of in-sample — i.e. the edge did not decay.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[3]
_CACHE = _ROOT / "data" / "bee" / "defillama_apy_history.json"

SPLIT = 0.70          # first 70% in-sample, last 30% out-of-sample
TOLERANCE = 0.20      # OOS yield must be >= 80% of in-sample yield
MIN_WINDOW_DAYS = 20  # need enough days in each window to judge


def load_protocol_series() -> Dict[str, Dict[str, float]]:
    """{protocol: {date_iso: apy_decimal}} from the real DeFiLlama cache."""
    out: Dict[str, Dict[str, float]] = {}
    try:
        cache = json.loads(_CACHE.read_text())
    except Exception:
        return out
    for key, val in (cache.get("pool_results") or {}).items():
        series = val.get("apy_series") if isinstance(val, dict) else None
        if not series:
            continue
        out[key] = {p["date"]: float(p["apy"]) for p in series if "date" in p and "apy" in p}
    return out


def _common_axis(series_map: Dict[str, Dict[str, float]], protocols: List[str]) -> List[str]:
    """Sorted union of dates across the strategy's (cached) protocols."""
    dates = set()
    for p in protocols:
        if p in series_map:
            dates.update(series_map[p].keys())
    return sorted(dates)


def _ffill_apy(per_date: Dict[str, float], axis: List[str]) -> List[Optional[float]]:
    """Forward-filled APY along the common axis (None until the series starts)."""
    out: List[Optional[float]] = []
    last: Optional[float] = None
    for d in axis:
        if d in per_date:
            last = per_date[d]
        out.append(last)
    return out


def oos_check(allocation: Dict[str, float],
              series_map: Optional[Dict[str, Dict[str, float]]] = None,
              split: float = SPLIT, tolerance: float = TOLERANCE) -> dict:
    """In-sample vs out-of-sample blended APY for a strategy allocation, on real data."""
    if series_map is None:
        series_map = load_protocol_series()
    # protocols in the allocation that we have real series for
    weights = {k: float(v) for k, v in (allocation or {}).items()
               if k != "cash" and v and k in series_map}
    covered = sum(weights.values())
    if not weights or covered <= 0:
        return {"status": "insufficient_data", "oos_holds": None,
                "coverage": round(covered, 4)}

    axis = _common_axis(series_map, list(weights.keys()))
    if len(axis) < 2 * MIN_WINDOW_DAYS:
        return {"status": "insufficient_history", "oos_holds": None,
                "n_days": len(axis), "coverage": round(covered, 4)}

    ffilled = {p: _ffill_apy(series_map[p], axis) for p in weights}

    def _avg_blended(lo: int, hi: int) -> float:
        tot, n = 0.0, 0
        for i in range(lo, hi):
            num, wsum = 0.0, 0.0
            for p, w in weights.items():
                a = ffilled[p][i]
                if a is not None:
                    num += w * a
                    wsum += w
            if wsum > 0:
                tot += num / wsum  # weighted average APY (renormalised over available)
                n += 1
        return (tot / n) if n else 0.0

    cut = int(len(axis) * split)
    is_apy = _avg_blended(0, cut) * 100.0          # decimal → percent
    oos_apy = _avg_blended(cut, len(axis)) * 100.0
    holds = oos_apy >= is_apy * (1.0 - tolerance) if is_apy > 0 else oos_apy >= 0
    return {
        "status": "ok",
        "in_sample_apy_pct": round(is_apy, 3),
        "out_of_sample_apy_pct": round(oos_apy, 3),
        "decay_pct": round((is_apy - oos_apy), 3),
        "oos_holds": bool(holds),
        "coverage": round(covered, 4),
        "n_days": len(axis),
        "split_at_day": cut,
    }


if __name__ == "__main__":
    sm = load_protocol_series()
    print("protocols with real series:", sorted(sm.keys()))
    demo = {"aave_v3": 0.5, "compound_v3": 0.3, "cash": 0.2}
    print(json.dumps(oos_check(demo, sm), indent=2))
