"""
spa_core/backtesting/tier1/regime.py — market-regime detection + regime-conditioned
yield statistics, from REAL historical APY data (Tier-1).

PARALLEL MODEL. Pure stdlib (math, statistics), deterministic, no network, LLM-forbidden.

The DeFi rate environment is not constant: stablecoin lending APY drifts between high-yield
booms, quiet low-yield troughs, and trending periods. A strategy validated only against a
single regime can silently fail when the environment shifts. This module builds an aggregate
"DeFi rate environment" series from the REAL per-protocol DeFiLlama APY history (T1 lending
protocols: aave_v3, compound_v3, morpho_steakhouse) on a common forward-filled date axis,
then deterministically classifies each date into one of:

    HIGH_YIELD  — rolling mean well above the long-run median
    LOW_YIELD   — rolling mean well below the long-run median
    RISING      — rolling mean trending up materially (positive slope)
    FALLING     — rolling mean trending down materially (negative slope)
    NORMAL      — none of the above (near the long-run median, flat)

Level (HIGH/LOW vs median) dominates trend, then trend (RISING/FALLING) over flat NORMAL.
All rolling statistics are pure-Python. Writes data/tier1_regime.json atomically.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as _dt
import math  # noqa: F401  (stdlib-only contract; available for downstream math)
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_OUT = _DATA / "tier1_regime.json"

# T1 lending protocols that define the "DeFi rate environment".
RATE_PROTOCOLS: List[str] = ["aave_v3", "compound_v3", "morpho_steakhouse"]

WINDOW = 30                 # rolling window (days) for mean + slope
HIGH_BAND = 1.20           # rolling mean >= median * HIGH_BAND  -> HIGH_YIELD
LOW_BAND = 0.80            # rolling mean <= median * LOW_BAND   -> LOW_YIELD
# Slope is per-day change of the rolling mean (in percent APY). A trend counts as
# RISING/FALLING when |slope * WINDOW| exceeds this fraction of the long-run median.
TREND_FRAC = 0.10          # cumulative move over the window >= 10% of median

REGIME_LABELS = ("HIGH_YIELD", "LOW_YIELD", "RISING", "FALLING", "NORMAL")


# ---------------------------------------------------------------------------
# series building
# ---------------------------------------------------------------------------
def aggregate_rate_series(
    series_map: Optional[Dict[str, Dict[str, float]]] = None,
    protocols: Optional[List[str]] = None,
) -> List[Tuple[str, float]]:
    """Cross-protocol average APY (percent) per date over the T1 lending protocols.

    Returns [(date_iso, apy_pct)] on a common, monotonically increasing date axis.
    Each protocol series is forward-filled (it only contributes once it has started),
    and each date's value is the average of the protocols available on that date.
    """
    if series_map is None:
        series_map = oos_mod.load_protocol_series()
    if protocols is None:
        protocols = RATE_PROTOCOLS
    present = [p for p in protocols if p in series_map and series_map[p]]
    if not present:
        return []

    axis = oos_mod._common_axis(series_map, present)
    if not axis:
        return []
    ff = {p: oos_mod._ffill_apy(series_map[p], axis) for p in present}

    out: List[Tuple[str, float]] = []
    for i, d in enumerate(axis):
        vals = [ff[p][i] for p in present if ff[p][i] is not None]
        if not vals:
            continue  # before any protocol has started
        out.append((d, (sum(vals) / len(vals)) * 100.0))  # decimal -> percent
    return out


# ---------------------------------------------------------------------------
# pure-python rolling stats
# ---------------------------------------------------------------------------
def _rolling_mean(vals: List[float], window: int) -> List[float]:
    """Trailing rolling mean; for the first (window-1) points uses the available prefix."""
    out: List[float] = []
    for i in range(len(vals)):
        lo = max(0, i - window + 1)
        chunk = vals[lo:i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _rolling_slope(vals: List[float], window: int) -> List[float]:
    """Per-day slope of a trailing window via ordinary least squares (pure python).

    Slope units = APY-percent per day. For the first point slope is 0.
    """
    out: List[float] = []
    for i in range(len(vals)):
        lo = max(0, i - window + 1)
        chunk = vals[lo:i + 1]
        n = len(chunk)
        if n < 2:
            out.append(0.0)
            continue
        xs = list(range(n))
        mx = (n - 1) / 2.0
        my = sum(chunk) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            out.append(0.0)
            continue
        num = sum((xs[k] - mx) * (chunk[k] - my) for k in range(n))
        out.append(num / denom)
    return out


# ---------------------------------------------------------------------------
# regime classification
# ---------------------------------------------------------------------------
def classify_regimes(series: List[Tuple[str, float]], window: int = WINDOW
                     ) -> List[Tuple[str, str]]:
    """Classify each date into one of REGIME_LABELS.

    Deterministic rule, in priority order:
      1. rolling mean >= median * HIGH_BAND          -> HIGH_YIELD
      2. rolling mean <= median * LOW_BAND           -> LOW_YIELD
      3. |slope * window| >= median * TREND_FRAC     -> RISING (slope>0) / FALLING (slope<0)
      4. otherwise                                   -> NORMAL
    """
    if not series:
        return []
    dates = [d for d, _ in series]
    vals = [v for _, v in series]
    median = statistics.median(vals)
    rmean = _rolling_mean(vals, window)
    rslope = _rolling_slope(vals, window)

    hi = median * HIGH_BAND
    lo = median * LOW_BAND
    trend_threshold = abs(median) * TREND_FRAC

    out: List[Tuple[str, str]] = []
    for i in range(len(series)):
        m = rmean[i]
        cumulative_move = rslope[i] * window
        if m >= hi:
            regime = "HIGH_YIELD"
        elif m <= lo:
            regime = "LOW_YIELD"
        elif abs(cumulative_move) >= trend_threshold:
            regime = "RISING" if cumulative_move > 0 else "FALLING"
        else:
            regime = "NORMAL"
        out.append((dates[i], regime))
    return out


def _trend_word(slope: float) -> str:
    if slope > 0:
        return "up"
    if slope < 0:
        return "down"
    return "flat"


def current_regime(series: Optional[List[Tuple[str, float]]] = None,
                   window: int = WINDOW) -> dict:
    """{regime, rate_apy, trend, since} for the most recent date."""
    if series is None:
        series = aggregate_rate_series()
    if not series:
        return {"regime": "NORMAL", "rate_apy": None, "trend": "flat",
                "since": None, "status": "no_data"}
    labels = classify_regimes(series, window)
    vals = [v for _, v in series]
    rslope = _rolling_slope(vals, window)
    last_date, last_regime = labels[-1]

    # walk back to find the first date of the current contiguous regime run
    since = last_date
    for i in range(len(labels) - 1, -1, -1):
        if labels[i][1] == last_regime:
            since = labels[i][0]
        else:
            break
    return {
        "regime": last_regime,
        "rate_apy": round(series[-1][1], 4),
        "trend": _trend_word(rslope[-1]),
        "slope_per_day": round(rslope[-1], 5),
        "since": since,
        "as_of": last_date,
        "status": "ok",
    }


def regime_summary(series: Optional[List[Tuple[str, float]]] = None,
                   window: int = WINDOW) -> dict:
    """{regime_counts, current, transitions} over the whole history."""
    if series is None:
        series = aggregate_rate_series()
    if not series:
        return {"regime_counts": {}, "current": current_regime(series, window),
                "transitions": [], "n_days": 0}
    labels = classify_regimes(series, window)
    counts: Dict[str, int] = {lbl: 0 for lbl in REGIME_LABELS}
    for _, r in labels:
        counts[r] = counts.get(r, 0) + 1

    transitions: List[dict] = []
    prev = None
    for d, r in labels:
        if r != prev:
            if prev is not None:
                transitions.append({"date": d, "from": prev, "to": r})
            prev = r
    return {
        "regime_counts": counts,
        "current": current_regime(series, window),
        "transitions": transitions,
        "n_transitions": len(transitions),
        "n_days": len(labels),
    }


def _per_regime_yield(series: List[Tuple[str, float]], window: int) -> Dict[str, dict]:
    """Average aggregate APY observed while in each regime."""
    labels = classify_regimes(series, window)
    buckets: Dict[str, List[float]] = {lbl: [] for lbl in REGIME_LABELS}
    for (_, apy), (_, regime) in zip(series, labels):
        buckets.setdefault(regime, []).append(apy)
    out: Dict[str, dict] = {}
    for lbl, vals in buckets.items():
        if vals:
            out[lbl] = {
                "n_days": len(vals),
                "avg_apy_pct": round(sum(vals) / len(vals), 4),
                "min_apy_pct": round(min(vals), 4),
                "max_apy_pct": round(max(vals), 4),
            }
        else:
            out[lbl] = {"n_days": 0, "avg_apy_pct": None,
                        "min_apy_pct": None, "max_apy_pct": None}
    return out


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def build_report(write: bool = True, window: int = WINDOW) -> dict:
    series_map = oos_mod.load_protocol_series()
    series = aggregate_rate_series(series_map)
    summary = regime_summary(series, window)
    per_regime = _per_regime_yield(series, window) if series else {}

    out = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "model": "tier1_regime",
        "llm_forbidden": True,
        "method": ("rolling-mean vs long-run-median band + OLS slope over a "
                   f"{window}-day window on the cross-protocol average T1 lending APY"),
        "rate_protocols": [p for p in RATE_PROTOCOLS if p in series_map],
        "window_days": window,
        "high_band": HIGH_BAND,
        "low_band": LOW_BAND,
        "trend_frac": TREND_FRAC,
        "labels": list(REGIME_LABELS),
        "current": summary["current"],
        "regime_counts": summary["regime_counts"],
        "n_transitions": summary["n_transitions"],
        "recent_transitions": summary["transitions"][-10:],
        "per_regime_yield": per_regime,
        "n_days": summary["n_days"],
        "axis_start": series[0][0] if series else None,
        "axis_end": series[-1][0] if series else None,
    }
    if write:
        atomic_save(out, str(_OUT))
    return out


if __name__ == "__main__":
    rep = build_report(write=True)
    cur = rep["current"]
    print("=== Tier-1 DeFi Rate Regime ===")
    print(f"current regime : {cur.get('regime')}")
    print(f"rate APY       : {cur.get('rate_apy')}% (trend {cur.get('trend')})")
    print(f"since          : {cur.get('since')}  as_of {cur.get('as_of')}")
    print(f"axis           : {rep.get('axis_start')} .. {rep.get('axis_end')} "
          f"({rep.get('n_days')} days)")
    print("regime distribution over history:")
    for lbl in REGIME_LABELS:
        c = rep["regime_counts"].get(lbl, 0)
        py = rep["per_regime_yield"].get(lbl, {})
        print(f"  {lbl:11s} {c:5d} days  avg_apy={py.get('avg_apy_pct')}")
    print(f"transitions    : {rep.get('n_transitions')}")
