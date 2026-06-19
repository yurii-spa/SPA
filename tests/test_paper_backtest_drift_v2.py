"""
tests/test_paper_backtest_drift_v2.py

40 unit tests for PaperBacktestDriftV2 (MP-1306 / Sprint v9.22).

CPA-methodology coverage:
  - nav_drift()
  - drift_alert()
  - allocation_drift()
  - source_drift()
  - record_paper_day()
  - weekly_drift_report()
  - save() atomic write + load()
  - ring-buffer cap = 100
"""

import json
import math
import os
import shutil
import tempfile
import unittest

from spa_core.analytics.paper_backtest_drift_v2 import PaperBacktestDriftV2


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_tracker(backtest_apy=0.068, initial_nav=100_000.0):
    return PaperBacktestDriftV2(backtest_apy=backtest_apy, initial_nav=initial_nav)


def _record_n_days(tracker, n, paper_nav=None, allocations=None, sources=None):
    """Helper: record n identical days."""
    for i in range(n):
        date = f"2026-06-{10 + i:02d}"
        nav = paper_nav if paper_nav is not None else tracker.initial_nav
        alloc = allocations or {}
        src = sources or []
        tracker.record_paper_day(date, nav, alloc, src)


# ─────────────────────────────────────────────────────────────────────────────
# 1–5: nav_drift() basic contract
# ─────────────────────────────────────────────────────────────────────────────

class TestNavDriftBasic(unittest.TestCase):

    def test_01_nav_drift_zero_at_day_zero(self):
        """nav_drift returns 0.0 when days_elapsed <= 0."""
        t = _make_tracker(backtest_apy=0.10)
        self.assertEqual(t.nav_drift(100_000.0, 0), 0.0)

    def test_02_nav_drift_zero_identical_trajectory(self):
        """nav_drift is 0.0 when paper_nav equals expected_nav exactly."""
        t = _make_tracker(backtest_apy=0.068, initial_nav=100_000.0)
        daily = (1 + 0.068 / 365) ** 10
        expected = 100_000.0 * daily
        drift = t.nav_drift(expected, 10)
        self.assertAlmostEqual(drift, 0.0, places=8)

    def test_03_nav_drift_positive_when_paper_outperforms(self):
        """nav_drift > 0 when paper NAV exceeds backtest expected NAV."""
        t = _make_tracker(backtest_apy=0.068, initial_nav=100_000.0)
        # Give paper a much higher NAV than expected after 30 days
        drift = t.nav_drift(105_000.0, 30)
        self.assertGreater(drift, 0.0)

    def test_04_nav_drift_negative_when_paper_underperforms(self):
        """nav_drift < 0 when paper NAV is below expected."""
        t = _make_tracker(backtest_apy=0.10, initial_nav=100_000.0)
        # Expected after 30 days at 10% APY is ~ $100,822
        drift = t.nav_drift(99_000.0, 30)
        self.assertLess(drift, 0.0)

    def test_05_nav_drift_formula(self):
        """nav_drift formula: (paper - expected) / expected * 100."""
        t = _make_tracker(backtest_apy=0.0, initial_nav=100_000.0)
        # At 0 % APY, expected always = initial_nav
        drift = t.nav_drift(102_000.0, 10)
        self.assertAlmostEqual(drift, 2.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 6–11: drift_alert() thresholds
# ─────────────────────────────────────────────────────────────────────────────

class TestDriftAlert(unittest.TestCase):

    def test_06_alert_ok_at_zero(self):
        t = _make_tracker()
        self.assertEqual(t.drift_alert(0.0), "OK")

    def test_07_alert_ok_below_2pct(self):
        t = _make_tracker()
        self.assertEqual(t.drift_alert(1.99), "OK")

    def test_08_alert_ok_at_minus_1pct(self):
        t = _make_tracker()
        self.assertEqual(t.drift_alert(-1.99), "OK")

    def test_09_alert_warn_at_2pct(self):
        """Exactly 2 % triggers WARN (|drift| > 2)."""
        t = _make_tracker()
        # > 2 % is WARN; exactly 2 is still WARN because threshold is > 2
        # Verify behaviour at boundary: 2.0001 → WARN
        self.assertEqual(t.drift_alert(2.01), "WARN")

    def test_10_alert_warn_between_2_and_5(self):
        t = _make_tracker()
        self.assertEqual(t.drift_alert(3.5), "WARN")
        self.assertEqual(t.drift_alert(-3.5), "WARN")

    def test_11_alert_critical_above_5(self):
        t = _make_tracker()
        self.assertEqual(t.drift_alert(5.01), "CRITICAL")
        self.assertEqual(t.drift_alert(-6.0), "CRITICAL")


# ─────────────────────────────────────────────────────────────────────────────
# 12–16: allocation_drift() (KL-divergence)
# ─────────────────────────────────────────────────────────────────────────────

class TestAllocationDrift(unittest.TestCase):

    def test_12_alloc_drift_zero_no_expected(self):
        """No expected allocations → KL-divergence = 0."""
        t = PaperBacktestDriftV2(backtest_expected_allocations=None)
        self.assertEqual(t.allocation_drift({"Aave": 0.5, "Morpho": 0.5}), 0.0)

    def test_13_alloc_drift_zero_identical(self):
        """Identical distributions → KL ≈ 0."""
        expected = {"Aave": 0.6, "Morpho": 0.4}
        t = PaperBacktestDriftV2(backtest_expected_allocations=expected)
        drift = t.allocation_drift({"Aave": 0.6, "Morpho": 0.4})
        self.assertAlmostEqual(drift, 0.0, places=6)

    def test_14_alloc_drift_positive_divergent(self):
        """Different distributions → KL > 0."""
        expected = {"Aave": 0.5, "Morpho": 0.5}
        t = PaperBacktestDriftV2(backtest_expected_allocations=expected)
        drift = t.allocation_drift({"Aave": 1.0, "Morpho": 0.0})
        self.assertGreater(drift, 0.0)

    def test_15_alloc_drift_normalises_actual(self):
        """Actual allocation is normalised before KL computation."""
        expected = {"Aave": 0.5, "Morpho": 0.5}
        t = PaperBacktestDriftV2(backtest_expected_allocations=expected)
        # Give unnormalised weights that sum to 2
        drift = t.allocation_drift({"Aave": 1.0, "Morpho": 1.0})
        self.assertAlmostEqual(drift, 0.0, places=6)

    def test_16_alloc_drift_handles_missing_key(self):
        """Keys in expected but absent in actual are treated as ε."""
        expected = {"Aave": 0.5, "Morpho": 0.5}
        t = PaperBacktestDriftV2(backtest_expected_allocations=expected)
        drift = t.allocation_drift({"Aave": 1.0})  # Morpho missing
        self.assertGreater(drift, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 17–20: source_drift()
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceDrift(unittest.TestCase):

    def test_17_source_drift_empty_when_no_backtest_sources(self):
        t = PaperBacktestDriftV2(backtest_sources=[])
        self.assertEqual(t.source_drift(["Aave", "Morpho"]), [])

    def test_18_source_drift_empty_when_all_present(self):
        t = PaperBacktestDriftV2(backtest_sources=["Aave", "Morpho"])
        self.assertEqual(t.source_drift(["Aave", "Morpho", "Compound"]), [])

    def test_19_source_drift_lists_missing_sources(self):
        t = PaperBacktestDriftV2(backtest_sources=["Aave", "Morpho", "Compound"])
        missing = t.source_drift(["Aave"])
        self.assertIn("Morpho", missing)
        self.assertIn("Compound", missing)
        self.assertNotIn("Aave", missing)

    def test_20_source_drift_returns_list(self):
        t = PaperBacktestDriftV2(backtest_sources=["X"])
        result = t.source_drift([])
        self.assertIsInstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# 21–28: record_paper_day()
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordPaperDay(unittest.TestCase):

    def test_21_record_returns_dict(self):
        t = _make_tracker()
        r = t.record_paper_day("2026-06-10", 100_100.0, {}, [])
        self.assertIsInstance(r, dict)

    def test_22_record_contains_required_keys(self):
        t = _make_tracker()
        r = t.record_paper_day("2026-06-10", 100_100.0, {}, [])
        required = {
            "date", "paper_nav", "expected_nav", "days_elapsed",
            "nav_drift_pct", "nav_alert", "apy_drift", "apy_alert",
            "allocation_drift_kl", "source_drift_missing",
        }
        self.assertTrue(required.issubset(r.keys()))

    def test_23_record_days_elapsed_increments(self):
        t = _make_tracker()
        r1 = t.record_paper_day("2026-06-10", 100_000.0, {}, [])
        r2 = t.record_paper_day("2026-06-11", 100_000.0, {}, [])
        self.assertEqual(r1["days_elapsed"], 1)
        self.assertEqual(r2["days_elapsed"], 2)

    def test_24_record_nav_alert_ok_for_identical_nav(self):
        """At 0% APY, staying at initial_nav → drift=0 → OK."""
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        r = t.record_paper_day("2026-06-10", 100_000.0, {}, [])
        self.assertEqual(r["nav_alert"], "OK")

    def test_25_record_nav_alert_critical_for_large_drop(self):
        """A 10 % drop below expected triggers CRITICAL."""
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        r = t.record_paper_day("2026-06-10", 89_000.0, {}, [])
        self.assertEqual(r["nav_alert"], "CRITICAL")

    def test_26_record_apy_alert_warn_when_paper_underperforms(self):
        """Paper APY significantly below backtest APY → apy_alert WARN."""
        t = PaperBacktestDriftV2(backtest_apy=0.10, initial_nav=100_000.0)
        # Record 30 days at flat NAV (0% paper APY) → severe underperform
        for i in range(30):
            r = t.record_paper_day(f"2026-06-{10+i:02d}", 100_000.0, {}, [])
        self.assertEqual(r["apy_alert"], "WARN")

    def test_27_record_source_drift_in_output(self):
        t = PaperBacktestDriftV2(backtest_sources=["Aave", "Morpho"])
        r = t.record_paper_day("2026-06-10", 100_000.0, {}, ["Aave"])
        self.assertIn("Morpho", r["source_drift_missing"])

    def test_28_record_paper_nav_rounded(self):
        t = _make_tracker()
        r = t.record_paper_day("2026-06-10", 100_000.123456789, {}, [])
        self.assertAlmostEqual(r["paper_nav"], 100_000.1235, places=4)


# ─────────────────────────────────────────────────────────────────────────────
# 29–34: weekly_drift_report()
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyDriftReport(unittest.TestCase):

    def test_29_weekly_report_empty_tracker(self):
        """Empty tracker returns report with all required keys, records=0."""
        t = _make_tracker()
        rpt = t.weekly_drift_report()
        required = {
            "week_records", "avg_nav_drift_pct", "max_nav_drift_pct",
            "min_nav_drift_pct", "drift_alert", "apy_drift_avg",
            "critical_days", "warn_days", "ok_days",
            "total_days_tracked", "recommendations", "generated_at",
        }
        self.assertTrue(required.issubset(rpt.keys()))
        self.assertEqual(rpt["week_records"], 0)

    def test_30_weekly_report_ok_alert_nominal(self):
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        _record_n_days(t, 7, paper_nav=100_000.0)
        rpt = t.weekly_drift_report()
        self.assertEqual(rpt["drift_alert"], "OK")

    def test_31_weekly_report_warn_when_drift_2_to_5(self):
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        # 97_000 at 0% APY → -3% drift
        _record_n_days(t, 7, paper_nav=97_000.0)
        rpt = t.weekly_drift_report()
        self.assertEqual(rpt["drift_alert"], "WARN")

    def test_32_weekly_report_critical_when_drift_above_5(self):
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        _record_n_days(t, 7, paper_nav=90_000.0)
        rpt = t.weekly_drift_report()
        self.assertEqual(rpt["drift_alert"], "CRITICAL")

    def test_33_weekly_report_uses_last_7_days(self):
        """Report only looks at the last 7 days, ignoring older records."""
        t = PaperBacktestDriftV2(backtest_apy=0.0, initial_nav=100_000.0)
        # First 20 days: extreme drop (CRITICAL)
        _record_n_days(t, 20, paper_nav=80_000.0)
        # Last 7 days: nominal
        _record_n_days(t, 7, paper_nav=100_000.0)
        rpt = t.weekly_drift_report()
        self.assertEqual(rpt["week_records"], 7)
        # All 7 recent days are OK
        self.assertEqual(rpt["ok_days"], 7)

    def test_34_weekly_report_recommendations_is_list(self):
        t = _make_tracker()
        _record_n_days(t, 3)
        rpt = t.weekly_drift_report()
        self.assertIsInstance(rpt["recommendations"], list)
        self.assertGreater(len(rpt["recommendations"]), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 35–38: save() and load() — atomic persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, "data", "paper", "drift_v2.json")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_35_save_creates_valid_json(self):
        t = _make_tracker()
        _record_n_days(t, 5)
        t.save(self.path)
        with open(self.path, encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertIn("schema_version", d)
        self.assertEqual(d["schema_version"], "2.0")

    def test_36_save_and_load_preserves_records(self):
        t = _make_tracker(backtest_apy=0.068, initial_nav=100_000.0)
        _record_n_days(t, 10)
        t.save(self.path)
        t2 = PaperBacktestDriftV2.load(self.path)
        self.assertEqual(len(t2._records), 10)

    def test_37_save_atomic_no_tmp_leftover(self):
        """After save(), no .tmp files remain in the directory."""
        t = _make_tracker()
        _record_n_days(t, 3)
        t.save(self.path)
        data_dir = os.path.dirname(self.path)
        tmp_files = [f for f in os.listdir(data_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_38_load_returns_default_if_missing(self):
        """load() from a non-existent path returns a default instance."""
        t = PaperBacktestDriftV2.load("/nonexistent/path/drift.json")
        self.assertIsInstance(t, PaperBacktestDriftV2)
        self.assertEqual(len(t._records), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 39–40: ring-buffer cap = 100
# ─────────────────────────────────────────────────────────────────────────────

class TestRingBuffer(unittest.TestCase):

    def test_39_ring_buffer_caps_at_100(self):
        """After 120 records, only 100 are retained."""
        t = _make_tracker()
        for i in range(120):
            t.record_paper_day(f"2026-01-{(i % 28) + 1:02d}", 100_000.0, {}, [])
        self.assertEqual(len(t._records), 100)

    def test_40_ring_buffer_retains_newest(self):
        """The retained records are the most recent ones (highest days_elapsed)."""
        t = _make_tracker()
        for i in range(110):
            t.record_paper_day(f"2026-01-01", 100_000.0 + i, {}, [])
        # The last record should have paper_nav = 100_000 + 109
        self.assertAlmostEqual(t._records[-1]["paper_nav"], 100_109.0, places=2)
        # The first retained record: day 11 (index 10), paper_nav = 100_010
        self.assertAlmostEqual(t._records[0]["paper_nav"], 100_010.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
