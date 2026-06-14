"""
Tests for MP-663 TVLTrendMonitor (spa_core/analytics/tvl_trend_monitor.py)
Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_tvl_trend_monitor -v

All persistence tests are tempfile-based; the production data/ directory is
never written.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.tvl_trend_monitor import (  # noqa: E402
    TVLPoint,
    TVLTrendResult,
    TVLTrendMonitor,
    _classify_trend,
    _pct_change,
    _risk_flag_for_trend,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor(tmp_dir: str) -> TVLTrendMonitor:
    return TVLTrendMonitor(data_dir=tmp_dir)


def _growing_series(n=10, base=1000.0, step=50.0):
    return [base + step * i for i in range(n)]


# ===========================================================================
# 1. _pct_change helper
# ===========================================================================

class TestPctChange(unittest.TestCase):

    def test_basic_increase(self):
        self.assertAlmostEqual(_pct_change(100.0, 110.0), 10.0, places=6)

    def test_basic_decrease(self):
        self.assertAlmostEqual(_pct_change(100.0, 90.0), -10.0, places=6)

    def test_no_change(self):
        self.assertAlmostEqual(_pct_change(100.0, 100.0), 0.0, places=6)

    def test_double(self):
        self.assertAlmostEqual(_pct_change(100.0, 200.0), 100.0, places=6)

    def test_halved(self):
        self.assertAlmostEqual(_pct_change(100.0, 50.0), -50.0, places=6)

    def test_zero_old_returns_none(self):
        self.assertIsNone(_pct_change(0.0, 100.0))

    def test_negative_old_uses_abs(self):
        # (new - old)/|old| * 100 = (50 - (-100))/100 * 100 = 150
        self.assertAlmostEqual(_pct_change(-100.0, 50.0), 150.0, places=6)

    def test_to_zero(self):
        self.assertAlmostEqual(_pct_change(100.0, 0.0), -100.0, places=6)


# ===========================================================================
# 2. _classify_trend (module-level, default thresholds)
# ===========================================================================

class TestClassifyTrendModule(unittest.TestCase):

    def test_unknown_empty(self):
        self.assertEqual(_classify_trend([]), "UNKNOWN")

    def test_unknown_single_point(self):
        self.assertEqual(_classify_trend([100.0]), "UNKNOWN")

    def test_unknown_zero_old(self):
        self.assertEqual(_classify_trend([0.0, 100.0]), "UNKNOWN")

    def test_growing_above_5(self):
        self.assertEqual(_classify_trend([100.0, 106.0]), "GROWING")

    def test_growing_just_above_5(self):
        self.assertEqual(_classify_trend([100.0, 105.01]), "GROWING")

    def test_stable_at_plus_5_boundary(self):
        # +5.0 exactly → STABLE (GROWING is strictly > 5)
        self.assertEqual(_classify_trend([100.0, 105.0]), "STABLE")

    def test_stable_zero(self):
        self.assertEqual(_classify_trend([100.0, 100.0]), "STABLE")

    def test_stable_at_minus_5_boundary(self):
        # -5.0 exactly → STABLE (inclusive lower bound)
        self.assertEqual(_classify_trend([100.0, 95.0]), "STABLE")

    def test_declining_just_below_minus_5(self):
        self.assertEqual(_classify_trend([100.0, 94.99]), "DECLINING")

    def test_declining_mid(self):
        self.assertEqual(_classify_trend([100.0, 85.0]), "DECLINING")

    def test_declining_at_minus_25_boundary(self):
        # -25.0 exactly → DECLINING (inclusive lower bound)
        self.assertEqual(_classify_trend([100.0, 75.0]), "DECLINING")

    def test_collapsing_just_below_minus_25(self):
        self.assertEqual(_classify_trend([100.0, 74.99]), "COLLAPSING")

    def test_collapsing_severe(self):
        self.assertEqual(_classify_trend([100.0, 10.0]), "COLLAPSING")

    def test_collapsing_to_near_zero(self):
        self.assertEqual(_classify_trend([100.0, 1.0]), "COLLAPSING")

    def test_only_first_and_last_matter(self):
        # Intermediate spikes don't change first-vs-last logic.
        self.assertEqual(_classify_trend([100.0, 5000.0, 106.0]), "GROWING")

    def test_handles_string_numbers(self):
        self.assertEqual(_classify_trend(["100.0", "110.0"]), "GROWING")

    def test_skips_non_numeric(self):
        # "x" dropped; remaining [100, 80] → DECLINING
        self.assertEqual(_classify_trend([100.0, "x", 80.0]), "DECLINING")

    def test_dropping_below_min_points_unknown(self):
        # Only one usable point after dropping junk → UNKNOWN
        self.assertEqual(_classify_trend([100.0, "bad"]), "UNKNOWN")


# ===========================================================================
# 3. _risk_flag_for_trend
# ===========================================================================

class TestRiskFlag(unittest.TestCase):

    def test_collapsing_high(self):
        self.assertEqual(_risk_flag_for_trend("COLLAPSING"), "HIGH")

    def test_declining_medium(self):
        self.assertEqual(_risk_flag_for_trend("DECLINING"), "MEDIUM")

    def test_growing_low(self):
        self.assertEqual(_risk_flag_for_trend("GROWING"), "LOW")

    def test_stable_low(self):
        self.assertEqual(_risk_flag_for_trend("STABLE"), "LOW")

    def test_unknown_low(self):
        self.assertEqual(_risk_flag_for_trend("UNKNOWN"), "LOW")

    def test_garbage_low(self):
        self.assertEqual(_risk_flag_for_trend("WHATEVER"), "LOW")


# ===========================================================================
# 4. classify_trend (instance method + configurable thresholds)
# ===========================================================================

class TestClassifyTrendInstance(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_instance_growing(self):
        self.assertEqual(self.m.classify_trend([100.0, 120.0]), "GROWING")

    def test_instance_stable(self):
        self.assertEqual(self.m.classify_trend([100.0, 101.0]), "STABLE")

    def test_instance_declining(self):
        self.assertEqual(self.m.classify_trend([100.0, 80.0]), "DECLINING")

    def test_instance_collapsing(self):
        self.assertEqual(self.m.classify_trend([100.0, 50.0]), "COLLAPSING")

    def test_instance_unknown(self):
        self.assertEqual(self.m.classify_trend([100.0]), "UNKNOWN")

    def test_custom_growing_threshold(self):
        m = TVLTrendMonitor(data_dir=self.tmp, growing_threshold=10.0)
        # +6% no longer GROWING with a 10% threshold → STABLE
        self.assertEqual(m.classify_trend([100.0, 106.0]), "STABLE")

    def test_custom_stable_lower(self):
        m = TVLTrendMonitor(data_dir=self.tmp, stable_lower=-2.0)
        # -3% now DECLINING with stable_lower=-2
        self.assertEqual(m.classify_trend([100.0, 97.0]), "DECLINING")

    def test_custom_declining_lower(self):
        m = TVLTrendMonitor(data_dir=self.tmp, declining_lower=-10.0)
        # -15% now COLLAPSING with declining_lower=-10
        self.assertEqual(m.classify_trend([100.0, 85.0]), "COLLAPSING")

    def test_thresholds_stored(self):
        m = TVLTrendMonitor(
            data_dir=self.tmp,
            growing_threshold=7.0,
            stable_lower=-3.0,
            declining_lower=-20.0,
        )
        self.assertEqual(m.growing_threshold, 7.0)
        self.assertEqual(m.stable_lower, -3.0)
        self.assertEqual(m.declining_lower, -20.0)


# ===========================================================================
# 5. record_tvl
# ===========================================================================

class TestRecordTVL(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_returns_result_type(self):
        r = self.m.record_tvl("aave", 1000.0, [900.0, 950.0])
        self.assertIsInstance(r, TVLTrendResult)

    def test_adapter_id_preserved(self):
        r = self.m.record_tvl("aave", 1000.0, [900.0, 1000.0])
        self.assertEqual(r.adapter_id, "aave")

    def test_current_tvl_set(self):
        r = self.m.record_tvl("aave", 1234.5, [900.0, 1234.5])
        self.assertAlmostEqual(r.current_tvl, 1234.5, places=6)

    def test_growing_trend(self):
        r = self.m.record_tvl("aave", 2000.0, [1000.0, 1500.0, 2000.0])
        self.assertEqual(r.trend, "GROWING")
        self.assertEqual(r.risk_flag, "LOW")

    def test_collapsing_trend_high_flag(self):
        r = self.m.record_tvl("aave", 100.0, [1000.0, 500.0, 100.0])
        self.assertEqual(r.trend, "COLLAPSING")
        self.assertEqual(r.risk_flag, "HIGH")

    def test_declining_trend_medium_flag(self):
        r = self.m.record_tvl("aave", 850.0, [1000.0, 900.0, 850.0])
        self.assertEqual(r.trend, "DECLINING")
        self.assertEqual(r.risk_flag, "MEDIUM")

    def test_stable_trend(self):
        r = self.m.record_tvl("aave", 1010.0, [1000.0, 1005.0, 1010.0])
        self.assertEqual(r.trend, "STABLE")

    def test_unknown_with_empty_history(self):
        r = self.m.record_tvl("aave", 1000.0, [])
        # Single current point → UNKNOWN
        self.assertEqual(r.trend, "UNKNOWN")
        self.assertIsNone(r.change_pct_7d)
        self.assertIsNone(r.change_pct_30d)

    def test_current_appended_when_not_last(self):
        # history ends at 900, current 1000 → series becomes [..,900,1000]
        r = self.m.record_tvl("aave", 1000.0, [900.0])
        # now 2 points → GROWING
        self.assertEqual(r.trend, "GROWING")

    def test_current_not_duplicated_when_already_last(self):
        r = self.m.record_tvl("aave", 1000.0, [900.0, 1000.0])
        # change is 900->1000 = +11.1% GROWING (not appended twice)
        self.assertEqual(r.trend, "GROWING")

    def test_change_pct_30d_present(self):
        r = self.m.record_tvl("aave", 2000.0, [1000.0, 2000.0])
        self.assertIsNotNone(r.change_pct_30d)
        self.assertAlmostEqual(r.change_pct_30d, 100.0, places=4)

    def test_change_pct_7d_uses_last_7(self):
        series = [float(x) for x in range(1, 11)]  # 1..10
        r = self.m.record_tvl("a", 10.0, series)
        # last 7 = [4,5,6,7,8,9,10]; change 4->10 = +150%
        self.assertAlmostEqual(r.change_pct_7d, 150.0, places=4)

    def test_timestamp_nonempty(self):
        r = self.m.record_tvl("aave", 1000.0, [900.0, 1000.0])
        self.assertTrue(r.timestamp)

    def test_non_numeric_current_defaults_zero(self):
        r = self.m.record_tvl("aave", "bad", [900.0, 800.0])
        self.assertEqual(r.current_tvl, 0.0)

    def test_zero_old_yields_unknown(self):
        r = self.m.record_tvl("aave", 100.0, [0.0])
        # series [0,100] → pct change undefined → UNKNOWN
        self.assertEqual(r.trend, "UNKNOWN")


# ===========================================================================
# 6. generate_report
# ===========================================================================

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_report_has_keys(self):
        rep = self.m.generate_report({}, {})
        for k in ("generated_at", "adapter_count", "results",
                  "trend_counts", "flagged_count", "advisory"):
            self.assertIn(k, rep)

    def test_empty_maps_zero_adapters(self):
        rep = self.m.generate_report({}, {})
        self.assertEqual(rep["adapter_count"], 0)
        self.assertEqual(rep["results"], [])

    def test_empty_advisory_is_clean(self):
        rep = self.m.generate_report({}, {})
        self.assertIn("No adapters", rep["advisory"])

    def test_results_sorted_by_adapter(self):
        tvl = {"zeta": 1000.0, "alpha": 1000.0}
        hist = {"zeta": [900.0, 1000.0], "alpha": [900.0, 1000.0]}
        rep = self.m.generate_report(tvl, hist)
        ids = [r["adapter_id"] for r in rep["results"]]
        self.assertEqual(ids, sorted(ids))

    def test_adapter_count_matches(self):
        tvl = {"a": 1000.0, "b": 1000.0, "c": 1000.0}
        hist = {"a": [900.0, 1000.0], "b": [1000.0, 1000.0], "c": [1100.0, 1000.0]}
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(rep["adapter_count"], 3)
        self.assertEqual(len(rep["results"]), 3)

    def test_trend_counts_sum(self):
        tvl = {"a": 2000.0, "b": 1000.0, "c": 100.0}
        hist = {
            "a": [1000.0, 2000.0],   # GROWING
            "b": [1000.0, 1000.0],   # STABLE
            "c": [1000.0, 100.0],    # COLLAPSING
        }
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(sum(rep["trend_counts"].values()), 3)

    def test_flagged_counts_high_and_medium(self):
        tvl = {"hi": 100.0, "med": 850.0, "ok": 1100.0}
        hist = {
            "hi": [1000.0, 100.0],    # COLLAPSING → HIGH
            "med": [1000.0, 850.0],   # DECLINING → MEDIUM
            "ok": [1000.0, 1100.0],   # GROWING → LOW
        }
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(rep["flagged_count"], 2)

    def test_advisory_flags_adapters(self):
        tvl = {"exodus": 100.0}
        hist = {"exodus": [1000.0, 100.0]}
        rep = self.m.generate_report(tvl, hist)
        self.assertIn("exodus", rep["advisory"])
        self.assertIn("HIGH", rep["advisory"])

    def test_missing_history_yields_unknown(self):
        tvl = {"new": 1000.0}
        hist = {}  # no history → only current point → UNKNOWN
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(rep["results"][0]["trend"], "UNKNOWN")

    def test_non_numeric_tvl_defaults_zero(self):
        tvl = {"a": "junk"}
        hist = {"a": [100.0, 200.0]}
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(rep["results"][0]["current_tvl"], 0.0)

    def test_non_list_history_safe(self):
        tvl = {"a": 1000.0}
        hist = {"a": "not-a-list"}
        rep = self.m.generate_report(tvl, hist)
        # degrade to UNKNOWN, no crash
        self.assertEqual(rep["results"][0]["trend"], "UNKNOWN")

    def test_non_dict_tvl_map_safe(self):
        rep = self.m.generate_report("not-a-dict", {})
        self.assertEqual(rep["adapter_count"], 0)

    def test_non_dict_history_map_safe(self):
        tvl = {"a": 1000.0}
        rep = self.m.generate_report(tvl, "not-a-dict")
        self.assertEqual(rep["adapter_count"], 1)

    def test_all_trend_labels_present_in_counts(self):
        rep = self.m.generate_report({}, {})
        for label in ("GROWING", "STABLE", "DECLINING", "COLLAPSING", "UNKNOWN"):
            self.assertIn(label, rep["trend_counts"])


# ===========================================================================
# 7. Persistence (save_report ring-buffer, atomic write)
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def _out_path(self) -> Path:
        return Path(self.tmp) / "tvl_trend_report.json"

    def test_stub_created_on_init(self):
        self.assertTrue(self._out_path().exists())

    def test_stub_is_empty_list(self):
        with open(self._out_path()) as fh:
            self.assertEqual(json.load(fh), [])

    def test_save_creates_file(self):
        rep = self.m.generate_report({}, {})
        self.m.save_report(rep)
        self.assertTrue(self._out_path().exists())

    def test_save_appends_entry(self):
        rep = self.m.generate_report({}, {})
        self.m.save_report(rep)
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_multiple_saves_append(self):
        for _ in range(4):
            self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 4)

    def test_ring_buffer_caps(self):
        for _ in range(_RING_BUFFER_MAX + 10):
            self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), _RING_BUFFER_MAX)

    def test_ring_buffer_exactly_max(self):
        for _ in range(_RING_BUFFER_MAX):
            self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest(self):
        for _ in range(_RING_BUFFER_MAX + 5):
            self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), _RING_BUFFER_MAX)

    def test_no_tmp_left_behind(self):
        self.m.save_report(self.m.generate_report({}, {}))
        leftover = list(Path(self.tmp).glob("*.tmp")) + list(Path(self.tmp).glob(".tmp*"))
        self.assertEqual(leftover, [])

    def test_save_returns_path(self):
        path = self.m.save_report(self.m.generate_report({}, {}))
        self.assertEqual(path, str(self._out_path()))

    def test_file_is_valid_json_list(self):
        self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            self.assertIsInstance(json.load(fh), list)

    def test_corrupt_file_recovered(self):
        with open(self._out_path(), "w") as fh:
            fh.write("CORRUPT {{{")
        # save should reset to a fresh list, not crash
        self.m.save_report(self.m.generate_report({}, {}))
        with open(self._out_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_production_data_untouched(self):
        # The monitor under test writes only to the tempdir.
        prod = _ROOT / "data" / "tvl_trend_report.json"
        before = prod.read_text() if prod.exists() else None
        self.m.save_report(self.m.generate_report({}, {}))
        after = prod.read_text() if prod.exists() else None
        self.assertEqual(before, after)


# ===========================================================================
# 8. TVLPoint dataclass round-trip
# ===========================================================================

class TestTVLPointDataclass(unittest.TestCase):

    def test_to_dict_keys(self):
        p = TVLPoint(timestamp="2026-06-13T00:00:00", adapter_id="aave", tvl_usd=1000.0)
        d = p.to_dict()
        for k in ("timestamp", "adapter_id", "tvl_usd"):
            self.assertIn(k, d)

    def test_round_trip(self):
        p = TVLPoint(timestamp="2026-06-13T00:00:00", adapter_id="aave", tvl_usd=1234.567)
        p2 = TVLPoint.from_dict(p.to_dict())
        self.assertEqual(p2.adapter_id, "aave")
        self.assertEqual(p2.timestamp, p.timestamp)
        self.assertAlmostEqual(p2.tvl_usd, 1234.567, places=4)

    def test_tvl_rounded_in_dict(self):
        p = TVLPoint(timestamp="t", adapter_id="a", tvl_usd=1.123456789)
        self.assertEqual(p.to_dict()["tvl_usd"], round(1.123456789, 6))

    def test_from_dict_missing_fields(self):
        p = TVLPoint.from_dict({})
        self.assertEqual(p.adapter_id, "")
        self.assertEqual(p.tvl_usd, 0.0)
        self.assertEqual(p.timestamp, "")

    def test_from_dict_bad_tvl_defaults_zero(self):
        p = TVLPoint.from_dict({"tvl_usd": "junk"})
        self.assertEqual(p.tvl_usd, 0.0)

    def test_from_dict_coerces_adapter_id(self):
        p = TVLPoint.from_dict({"adapter_id": 123})
        self.assertEqual(p.adapter_id, "123")


# ===========================================================================
# 9. TVLTrendResult dataclass round-trip
# ===========================================================================

class TestTVLTrendResultDataclass(unittest.TestCase):

    def _make(self):
        return TVLTrendResult(
            adapter_id="aave",
            current_tvl=1000.0,
            change_pct_7d=12.5,
            change_pct_30d=-3.2,
            trend="GROWING",
            risk_flag="LOW",
            timestamp="2026-06-13T00:00:00",
        )

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for k in ("adapter_id", "current_tvl", "change_pct_7d",
                  "change_pct_30d", "trend", "risk_flag", "timestamp"):
            self.assertIn(k, d)

    def test_round_trip(self):
        r = self._make()
        r2 = TVLTrendResult.from_dict(r.to_dict())
        self.assertEqual(r2.adapter_id, "aave")
        self.assertEqual(r2.trend, "GROWING")
        self.assertEqual(r2.risk_flag, "LOW")
        self.assertAlmostEqual(r2.change_pct_7d, 12.5, places=4)
        self.assertAlmostEqual(r2.change_pct_30d, -3.2, places=4)

    def test_none_changes_preserved(self):
        r = TVLTrendResult(
            adapter_id="new", current_tvl=1000.0,
            change_pct_7d=None, change_pct_30d=None,
            trend="UNKNOWN", risk_flag="LOW", timestamp="t",
        )
        d = r.to_dict()
        self.assertIsNone(d["change_pct_7d"])
        self.assertIsNone(d["change_pct_30d"])
        r2 = TVLTrendResult.from_dict(d)
        self.assertIsNone(r2.change_pct_7d)
        self.assertIsNone(r2.change_pct_30d)

    def test_from_dict_defaults(self):
        r = TVLTrendResult.from_dict({})
        self.assertEqual(r.adapter_id, "")
        self.assertEqual(r.current_tvl, 0.0)
        self.assertEqual(r.trend, "UNKNOWN")
        self.assertEqual(r.risk_flag, "LOW")

    def test_changes_rounded(self):
        r = TVLTrendResult(
            adapter_id="a", current_tvl=1.0,
            change_pct_7d=1.123456789, change_pct_30d=2.987654321,
            trend="STABLE", risk_flag="LOW", timestamp="t",
        )
        d = r.to_dict()
        self.assertEqual(d["change_pct_7d"], round(1.123456789, 4))
        self.assertEqual(d["change_pct_30d"], round(2.987654321, 4))

    def test_current_tvl_rounded(self):
        r = TVLTrendResult(
            adapter_id="a", current_tvl=1.123456789,
            change_pct_7d=None, change_pct_30d=None,
            trend="UNKNOWN", risk_flag="LOW", timestamp="t",
        )
        self.assertEqual(r.to_dict()["current_tvl"], round(1.123456789, 6))


# ===========================================================================
# 10. Class constants / configuration
# ===========================================================================

class TestClassConstants(unittest.TestCase):

    def test_ring_buffer_size_is_30(self):
        self.assertEqual(TVLTrendMonitor.RING_BUFFER_SIZE, 30)

    def test_module_ring_buffer_is_30(self):
        self.assertEqual(_RING_BUFFER_MAX, 30)

    def test_output_filename(self):
        self.assertEqual(TVLTrendMonitor.OUTPUT_FILE, "tvl_trend_report.json")

    def test_min_history_points_is_2(self):
        self.assertEqual(TVLTrendMonitor.MIN_HISTORY_POINTS, 2)

    def test_default_data_dir_used_when_none(self):
        m = TVLTrendMonitor(data_dir=tempfile.mkdtemp())
        self.assertTrue(str(m._data_dir))


# ===========================================================================
# 11. Integration-style scenarios
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _make_monitor(self.tmp)

    def test_full_cycle_generate_and_save(self):
        tvl = {"aave": 1500.0, "comp": 950.0, "morpho": 100.0}
        hist = {
            "aave": _growing_series(8, 1000.0, 100.0),
            "comp": [1000.0, 950.0],
            "morpho": [1000.0, 100.0],
        }
        rep = self.m.generate_report(tvl, hist)
        path = self.m.save_report(rep)
        self.assertTrue(Path(path).exists())
        with open(path) as fh:
            saved = json.load(fh)
        self.assertEqual(saved[-1]["adapter_count"], 3)

    def test_growing_then_collapse_changes_flag(self):
        r1 = self.m.record_tvl("a", 2000.0, [1000.0, 2000.0])
        self.assertEqual(r1.risk_flag, "LOW")
        r2 = self.m.record_tvl("a", 100.0, [1000.0, 100.0])
        self.assertEqual(r2.risk_flag, "HIGH")

    def test_results_to_dict_serialisable(self):
        tvl = {"a": 1000.0}
        hist = {"a": [900.0, 1000.0]}
        rep = self.m.generate_report(tvl, hist)
        # round-trips through JSON without error
        json.dumps(rep)

    def test_many_adapters(self):
        tvl = {f"ad{i}": 1000.0 + i for i in range(50)}
        hist = {f"ad{i}": [1000.0, 1000.0 + i] for i in range(50)}
        rep = self.m.generate_report(tvl, hist)
        self.assertEqual(rep["adapter_count"], 50)


if __name__ == "__main__":
    unittest.main()
