"""Reproducible market-regime labels (rules, not an LLM), computed on DAILY bars.

A day's label is known at that day's close and applies to the NEXT day's bars — so labelling a bar
never uses information from its own future.

    trend:  bull   close > SMA200 and SMA200 rising over 20 days
            bear   close < SMA200 and SMA200 falling over 20 days
            sideways otherwise
    vol:    30-day realized volatility percentile inside the trailing 365 days:
            high > 0.70 · low < 0.30 · normal otherwise
    stress: |daily return| > 8% or vol percentile > 0.95
"""
from __future__ import annotations

import bisect
import math
from typing import Dict, List, Optional

from . import indicators as ind

DAY_MS = 86_400_000
RULES_VERSION = 1


def daily_labels(days) -> List[Optional[dict]]:
    c = [b.close for b in days]
    m = ind.sma(c, 200)
    rets = [None] + [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    vol: List[Optional[float]] = [None] * len(c)
    for i in range(30, len(c)):
        w = rets[i - 29:i + 1]
        mu = sum(w) / 30
        vol[i] = math.sqrt(sum((r - mu) ** 2 for r in w) / 29) * math.sqrt(365)
    out: List[Optional[dict]] = []
    for i in range(len(c)):
        if m[i] is None or i < 220 or vol[i] is None:
            out.append(None)
            continue
        slope = m[i] - m[i - 20]
        trend = "bull" if (c[i] > m[i] and slope > 0) else "bear" if (c[i] < m[i] and slope < 0) else "sideways"
        hist = [v for v in vol[max(0, i - 364):i + 1] if v is not None]
        pct = sum(1 for v in hist if v <= vol[i]) / len(hist)
        vlab = "high" if pct > 0.70 else "low" if pct < 0.30 else "normal"
        stress = abs(rets[i]) > 0.08 or pct > 0.95
        out.append({"trend": trend, "vol": vlab, "stress": stress})
    return out


class RegimeIndex:
    """Look up the regime in force for any bar: the label of the last COMPLETED day before it."""

    def __init__(self, days):
        self.days = [d.open_time for d in days]
        self.labels = daily_labels(days)

    def at(self, open_time: int) -> Optional[dict]:
        day_start = open_time - (open_time % DAY_MS)
        k = bisect.bisect_left(self.days, day_start) - 1        # previous day's close
        return self.labels[k] if 0 <= k < len(self.labels) else None

    def keys_for(self, bars) -> List[Optional[str]]:
        out = []
        for b in bars:
            r = self.at(b.open_time)
            out.append(None if r is None else ("stress" if r["stress"] else r["trend"]))
        return out
