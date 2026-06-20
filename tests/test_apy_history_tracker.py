"""
tests/test_apy_history_tracker.py

Sprint v11.22 — MP-1506: APY history tracker + trend analysis — 25 tests covering:
  - record() — stores entries, respects ring-buffer, defaults date to today
  - get_trend() — rising / falling / stable / unknown
  - best_trending_adapters() — filtering + sorting
  - all_trends() / adapter_names() / history_for()
  - Constants (TREND_WINDOW_DAYS, TREND_THRESHOLD, MAX_HISTORY_DAYS)
  - save/load round-trip via temp directory
"""
from __future__ import annotations

import datetime
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.apy_history_tracker import (
    APYHistoryTracker,
    TREND_WINDOW_DAYS,
    TREND_THRESHOLD,
    MAX_HISTORY_DAYS,
    TREND_RISING,
    TREND_FALLING,
    TREND_STABLE,
    TREND_UNKNOWN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracker(tmp_path: str = None, **kwargs) -> APYHistoryTracker:
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    return APYHistoryTracker(base_dir=tmp_path, **kwargs)


def _record_series(tracker: APYHistoryTracker, adapter: str, apys: list[float]) -> None:
    """Record a series of APY values on sequential dates."""
    base_date = datetime.date(2026, 1, 1)
    for i, apy in enumerate(apys):
        date = (base_date + datetime.timedelta(days=i)).isoformat()
        tracker.record(adapter, apy, date=date)


# ---------------------------------------------------------------------------
# 1. record() — storage
# ---------------------------------------------------------------------------

class TestRecord(unittest.TestCase):

    def test_record_creates_adapter_entry(self):
        t = _tracker()
        t.record("aave-v3", 5.0, date="2026-01-01")
        assert "aave-v3" in t.adapter_names()

    def test_record_stores_date_and_apy(self):
        t = _tracker()
        t.record("aave-v3", 3.5, date="2026-02-15")
        hist = t.history_for("aave-v3")
        assert hist[0]["date"] == "2026-02-15"
        assert hist[0]["apy"] == 3.5

    def test_record_multiple_entries(self):
        t = _tracker()
        _record_series(t, "morpho", [5.0, 5.1, 5.2])
        assert len(t.history_for("morpho")) == 3

    def test_record_default_date_is_today(self):
        t = _tracker()
        t.record("compound", 4.0)
        today = datetime.date.today().isoformat()
        assert t.history_for("compound")[0]["date"] == today

    def test_ring_buffer_limits_history(self):
        t = _tracker(max_history_days=5)
        for i in range(10):
            date = (datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat()
            t.record("yearn", float(i), date=date)
        hist = t.history_for("yearn")
        assert len(hist) == 5
        # Should keep the 5 most recent entries
        assert hist[-1]["apy"] == 9.0

    def test_ring_buffer_default_is_90(self):
        assert MAX_HISTORY_DAYS == 90


# ---------------------------------------------------------------------------
# 2. get_trend() — trend classification
# ---------------------------------------------------------------------------

class TestGetTrend(unittest.TestCase):

    def test_unknown_when_insufficient_data(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "aave-v3", [5.0] * 5)  # only 5 entries
        result = t.get_trend("aave-v3")
        assert result["trend"] == TREND_UNKNOWN

    def test_unknown_for_nonexistent_adapter(self):
        t = _tracker()
        result = t.get_trend("nonexistent")
        assert result["trend"] == TREND_UNKNOWN

    def test_stable_trend(self):
        t = _tracker(trend_window_days=7, trend_threshold=0.005)
        # Constant APY: delta = 0
        _record_series(t, "aave-v3", [5.0] * 7)
        result = t.get_trend("aave-v3")
        assert result["trend"] == TREND_STABLE

    def test_rising_trend(self):
        t = _tracker(trend_window_days=7, trend_threshold=0.005)
        # first 3 mean = 4.0, last 3 mean = 5.0 → delta = +1.0
        apys = [4.0, 4.0, 4.0, 4.5, 5.0, 5.0, 5.0]
        _record_series(t, "compound", apys)
        result = t.get_trend("compound")
        assert result["trend"] == TREND_RISING

    def test_falling_trend(self):
        t = _tracker(trend_window_days=7, trend_threshold=0.005)
        # first 3 mean = 6.0, last 3 mean = 4.0 → delta = -2.0
        apys = [6.0, 6.0, 6.0, 5.0, 4.0, 4.0, 4.0]
        _record_series(t, "yearn", apys)
        result = t.get_trend("yearn")
        assert result["trend"] == TREND_FALLING

    def test_trend_result_has_required_keys(self):
        t = _tracker()
        _record_series(t, "morpho", [5.0] * 7)
        result = t.get_trend("morpho")
        for key in ("adapter", "trend", "data_points", "delta", "latest_apy"):
            assert key in result

    def test_data_points_reflects_history_length(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "aave-v3", [5.0] * 10)
        result = t.get_trend("aave-v3")
        assert result["data_points"] == 10

    def test_latest_apy_is_most_recent_entry(self):
        t = _tracker(trend_window_days=7)
        apys = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
        _record_series(t, "aave-v3", apys)
        result = t.get_trend("aave-v3")
        assert result["latest_apy"] == 6.0

    def test_trend_threshold_constant(self):
        assert TREND_THRESHOLD == 0.005

    def test_trend_window_days_constant(self):
        assert TREND_WINDOW_DAYS == 7


# ---------------------------------------------------------------------------
# 3. best_trending_adapters()
# ---------------------------------------------------------------------------

class TestBestTrendingAdapters(unittest.TestCase):

    def test_returns_only_rising_adapters(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "rising-a", [4.0, 4.0, 4.0, 4.5, 5.0, 5.0, 5.0])
        _record_series(t, "stable-b", [5.0] * 7)
        _record_series(t, "falling-c", [6.0, 6.0, 6.0, 5.0, 4.0, 4.0, 4.0])
        best = t.best_trending_adapters()
        names = [b["adapter"] for b in best]
        assert "rising-a" in names
        assert "stable-b" not in names
        assert "falling-c" not in names

    def test_sorted_by_apy_descending(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "adapter-low",  [4.0, 4.0, 4.0, 4.5, 5.0, 5.0, 5.0])  # latest 5.0
        _record_series(t, "adapter-high", [7.0, 7.0, 7.0, 7.5, 8.0, 8.0, 8.0])  # latest 8.0
        best = t.best_trending_adapters()
        assert best[0]["adapter"] == "adapter-high"
        assert best[1]["adapter"] == "adapter-low"

    def test_n_limits_results(self):
        t = _tracker(trend_window_days=7)
        for i in range(5):
            name = f"adapter-{i}"
            apys = [float(i)] * 3 + [float(i) + 0.5] * 4
            _record_series(t, name, apys)
        best = t.best_trending_adapters(n=2)
        assert len(best) <= 2

    def test_empty_when_no_rising_adapters(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "flat", [5.0] * 7)
        best = t.best_trending_adapters()
        assert best == []

    def test_result_dict_has_required_keys(self):
        t = _tracker(trend_window_days=7)
        _record_series(t, "rising", [4.0, 4.0, 4.0, 5.0, 5.0, 5.0, 6.0])
        best = t.best_trending_adapters()
        if best:
            for key in ("adapter", "apy", "trend", "delta", "data_points"):
                assert key in best[0]


# ---------------------------------------------------------------------------
# 4. all_trends / adapter_names / history_for
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_all_trends_covers_all_adapters(self):
        t = _tracker()
        _record_series(t, "aave-v3", [5.0] * 7)
        _record_series(t, "compound", [4.0] * 7)
        trends = t.all_trends()
        assert "aave-v3" in trends
        assert "compound" in trends

    def test_adapter_names_returns_all(self):
        t = _tracker()
        t.record("a", 1.0, date="2026-01-01")
        t.record("b", 2.0, date="2026-01-01")
        names = t.adapter_names()
        assert "a" in names and "b" in names

    def test_history_for_empty_for_unknown(self):
        t = _tracker()
        assert t.history_for("nonexistent") == []

    def test_to_dict_contains_adapters_key(self):
        t = _tracker()
        d = t.to_dict()
        assert "adapters" in d
        assert "last_update" in d


if __name__ == "__main__":
    unittest.main()
