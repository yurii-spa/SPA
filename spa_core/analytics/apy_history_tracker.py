"""
spa_core/analytics/apy_history_tracker.py

Sprint v11.22 — MP-1506: APY history tracker + trend analysis.

Records daily APY observations per adapter/protocol, retains up to 90 days
of history, and derives trend labels: rising / falling / stable / unknown.
Also provides best_trending_adapters() for portfolio advisory use.

Architecture
------------
- Strictly read-only / advisory — never touches allocator, risk, or execution.
- Pure stdlib; inherits BaseAnalytics for atomic save/load.
- CLI:  python3 -m spa_core.analytics.apy_history_tracker --check | --run

Trend algorithm
---------------
Window = last TREND_WINDOW_DAYS entries.  Compare mean of first 3 vs last 3.
  delta > +TREND_THRESHOLD  → "rising"
  delta < -TREND_THRESHOLD  → "falling"
  |delta| ≤ TREND_THRESHOLD → "stable"
  < TREND_WINDOW_DAYS entries → "unknown"
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Optional

from spa_core.base import BaseAnalytics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TREND_WINDOW_DAYS: int = 7        # minimum entries needed to compute trend
TREND_THRESHOLD: float = 0.005    # 0.5% absolute APY change defines trend boundary
MAX_HISTORY_DAYS: int = 90        # ring-buffer depth per adapter

TREND_RISING  = "rising"
TREND_FALLING = "falling"
TREND_STABLE  = "stable"
TREND_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class APYHistoryTracker(BaseAnalytics):
    """Tracks and analyzes APY trends per adapter.

    Parameters
    ----------
    base_dir:
        Project root directory (default ".").
    max_history_days:
        Maximum number of daily entries retained per adapter (default 90).
    trend_window_days:
        Minimum entries required to compute a trend (default 7).
    trend_threshold:
        Minimum APY delta (absolute, not percentage) to classify as
        rising/falling.  Default 0.005 (= 0.5% APY).
    """

    OUTPUT_PATH = "data/apy_history_tracker.json"

    def __init__(
        self,
        base_dir: str = ".",
        max_history_days: int = MAX_HISTORY_DAYS,
        trend_window_days: int = TREND_WINDOW_DAYS,
        trend_threshold: float = TREND_THRESHOLD,
    ) -> None:
        super().__init__(base_dir)
        self._max_history_days = max_history_days
        self._trend_window_days = trend_window_days
        self._trend_threshold = trend_threshold
        self._data: dict = {
            "adapters": {},
            "last_update": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        adapter_name: str,
        apy: float,
        date: Optional[str] = None,
    ) -> None:
        """Record *apy* for *adapter_name* on *date*.

        Parameters
        ----------
        adapter_name:
            Identifier string (e.g. ``"aave-v3"``, ``"morpho-steakhouse"``).
        apy:
            APY value to record.  May be percentage (e.g. 5.0 for 5%) or
            fractional (e.g. 0.05) — callers must be consistent.
        date:
            ISO date string ``"YYYY-MM-DD"``.  Defaults to today (UTC).
        """
        date = date or datetime.date.today().isoformat()

        if adapter_name not in self._data["adapters"]:
            self._data["adapters"][adapter_name] = []

        history: list = self._data["adapters"][adapter_name]

        # Append new entry
        history.append({"date": date, "apy": apy})

        # Enforce ring-buffer: keep only the last max_history_days entries
        if len(history) > self._max_history_days:
            self._data["adapters"][adapter_name] = history[-self._max_history_days:]

        self._data["last_update"] = datetime.datetime.utcnow().isoformat()
        self.save()

    def get_trend(self, adapter_name: str) -> dict:
        """Compute trend for *adapter_name* over the last TREND_WINDOW_DAYS entries.

        Returns
        -------
        dict with keys:
            trend        – "rising" | "falling" | "stable" | "unknown"
            data_points  – int (entries used)
            delta        – float (second_half_mean − first_half_mean), or None
            latest_apy   – float | None
        """
        history = self._data["adapters"].get(adapter_name, [])
        n = len(history)

        if n < self._trend_window_days:
            return {
                "adapter": adapter_name,
                "trend": TREND_UNKNOWN,
                "data_points": n,
                "delta": None,
                "latest_apy": history[-1]["apy"] if history else None,
            }

        window = [e["apy"] for e in history[-self._trend_window_days:]]
        # Compare first 3 vs last 3 within the window
        first_half_mean = sum(window[:3]) / 3
        second_half_mean = sum(window[-3:]) / 3
        delta = second_half_mean - first_half_mean

        if delta > self._trend_threshold:
            trend = TREND_RISING
        elif delta < -self._trend_threshold:
            trend = TREND_FALLING
        else:
            trend = TREND_STABLE

        return {
            "adapter": adapter_name,
            "trend": trend,
            "data_points": n,
            "delta": delta,
            "latest_apy": history[-1]["apy"],
        }

    def best_trending_adapters(self, n: int = 3) -> list[dict]:
        """Return top *n* adapters by APY among those with a "rising" trend.

        Results are sorted by latest APY, descending (highest first).

        Returns
        -------
        list of dicts with keys: adapter, apy, trend, delta, data_points.
        """
        results: list[dict] = []
        for adapter_name, history in self._data["adapters"].items():
            if not history:
                continue
            trend_info = self.get_trend(adapter_name)
            if trend_info["trend"] == TREND_RISING:
                results.append({
                    "adapter": adapter_name,
                    "apy": history[-1]["apy"],
                    "trend": TREND_RISING,
                    "delta": trend_info["delta"],
                    "data_points": trend_info["data_points"],
                })

        results.sort(key=lambda x: x["apy"], reverse=True)
        return results[:n]

    def all_trends(self) -> dict[str, dict]:
        """Return trend info for all tracked adapters."""
        return {
            adapter: self.get_trend(adapter)
            for adapter in self._data["adapters"]
        }

    def adapter_names(self) -> list[str]:
        """Return list of all tracked adapter names."""
        return list(self._data["adapters"].keys())

    def history_for(self, adapter_name: str) -> list[dict]:
        """Return raw history list for *adapter_name* (may be empty)."""
        return list(self._data["adapters"].get(adapter_name, []))

    def to_dict(self) -> dict:
        return self._data

    def load_from_disk(self) -> None:
        """Load persisted data from OUTPUT_PATH into _data."""
        loaded = self.load()
        if isinstance(loaded, dict) and "adapters" in loaded:
            self._data = loaded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="APY History Tracker — trend analysis per adapter"
    )
    parser.add_argument("--check", action="store_true",
                        help="Print current trends without saving (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically save to data/")
    parser.add_argument("--data-dir", default=".",
                        help="Project root directory")
    args = parser.parse_args(argv)

    tracker = APYHistoryTracker(base_dir=args.data_dir)
    tracker.load_from_disk()

    trends = tracker.all_trends()
    best = tracker.best_trending_adapters()

    output = {
        "trends": trends,
        "best_trending": best,
        "adapters_tracked": len(tracker.adapter_names()),
    }

    print(json.dumps(output, indent=2, default=str))

    if args.run:
        path = tracker.save()
        print(f"\n[apy_history_tracker] Saved → {path}")


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
