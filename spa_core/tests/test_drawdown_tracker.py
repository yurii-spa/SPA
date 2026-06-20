"""
Tests for MP-704: DrawdownTracker
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.drawdown_tracker import (
    DD_MODERATE,
    DD_SEVERE,
    DD_SHALLOW,
    MAX_ENTRIES,
    DrawdownReport,
    DrawdownTracker,
    NavPoint,
)


def _pts(values):
    return [NavPoint(f"t{i}", v) for i, v in enumerate(values)]


class TestValues(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_empty(self):
        self.assertEqual(self.t._values([]), [])

    def test_all_positive(self):
        self.assertEqual(self.t._values(_pts([1, 2, 3])), [1, 2, 3])

    def test_drops_zero(self):
        self.assertEqual(self.t._values(_pts([1, 0, 3])), [1, 3])

    def test_drops_negative(self):
        self.assertEqual(self.t._values(_pts([1, -5, 3])), [1, 3])

    def test_all_nonpositive(self):
        self.assertEqual(self.t._values(_pts([0, -1, -2])), [])


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_none(self):
        self.assertEqual(self.t._classify(0.0), "NONE")

    def test_negative_treated_none(self):
        self.assertEqual(self.t._classify(-0.1), "NONE")

    def test_shallow_lower(self):
        self.assertEqual(self.t._classify(0.01), "SHALLOW")

    def test_shallow_upper(self):
        self.assertEqual(self.t._classify(0.049), "SHALLOW")

    def test_moderate_boundary(self):
        self.assertEqual(self.t._classify(DD_SHALLOW), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(self.t._classify(0.10), "MODERATE")

    def test_severe_boundary(self):
        self.assertEqual(self.t._classify(DD_MODERATE), "SEVERE")

    def test_severe_mid(self):
        self.assertEqual(self.t._classify(0.25), "SEVERE")

    def test_critical_boundary(self):
        self.assertEqual(self.t._classify(DD_SEVERE), "CRITICAL")

    def test_critical_high(self):
        self.assertEqual(self.t._classify(0.6), "CRITICAL")

    def test_critical_full(self):
        self.assertEqual(self.t._classify(1.0), "CRITICAL")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_empty(self):
        r = self.t.analyze([])
        self.assertEqual(r.severity, "UNKNOWN")
        self.assertEqual(r.num_points, 0)

    def test_single_point(self):
        r = self.t.analyze(_pts([100]))
        self.assertEqual(r.severity, "UNKNOWN")
        self.assertEqual(r.num_points, 1)
        self.assertEqual(r.start_value_usd, 100)

    def test_single_advisory(self):
        r = self.t.analyze(_pts([100]))
        self.assertTrue(any("at least 2" in a for a in r.advisory))

    def test_all_nonpositive(self):
        r = self.t.analyze(_pts([0, -1]))
        self.assertEqual(r.severity, "UNKNOWN")

    def test_returns_report_type(self):
        self.assertIsInstance(self.t.analyze(_pts([1, 2])), DrawdownReport)


class TestNoDrawdown(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_monotonic_up_no_dd(self):
        r = self.t.analyze(_pts([100, 110, 120, 130]))
        self.assertEqual(r.max_drawdown_pct, 0.0)
        self.assertEqual(r.severity, "NONE")

    def test_monotonic_up_not_underwater(self):
        r = self.t.analyze(_pts([100, 110, 120]))
        self.assertFalse(r.underwater_now)

    def test_flat_series(self):
        r = self.t.analyze(_pts([100, 100, 100]))
        self.assertEqual(r.max_drawdown_pct, 0.0)
        self.assertFalse(r.underwater_now)

    def test_monotonic_total_return(self):
        r = self.t.analyze(_pts([100, 200]))
        self.assertAlmostEqual(r.total_return_pct, 100.0, places=4)

    def test_longest_underwater_zero(self):
        r = self.t.analyze(_pts([100, 110, 120]))
        self.assertEqual(r.longest_underwater_points, 0)


class TestDrawdownMath(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_simple_max_drawdown(self):
        # peak 100 -> trough 80 = 20%
        r = self.t.analyze(_pts([100, 80, 90]))
        self.assertAlmostEqual(r.max_drawdown_pct, 20.0, places=4)

    def test_max_dd_severity(self):
        r = self.t.analyze(_pts([100, 80, 90]))
        self.assertEqual(r.severity, "SEVERE")

    def test_critical_drawdown(self):
        r = self.t.analyze(_pts([100, 60]))
        self.assertAlmostEqual(r.max_drawdown_pct, 40.0, places=4)
        self.assertEqual(r.severity, "CRITICAL")

    def test_shallow_drawdown(self):
        r = self.t.analyze(_pts([100, 97, 99]))
        self.assertEqual(r.severity, "SHALLOW")

    def test_moderate_drawdown(self):
        r = self.t.analyze(_pts([100, 90, 95]))
        self.assertAlmostEqual(r.max_drawdown_pct, 10.0, places=4)
        self.assertEqual(r.severity, "MODERATE")

    def test_peak_after_recovery(self):
        # new peak resets reference; dd from 120 to 108 = 10%
        r = self.t.analyze(_pts([100, 120, 108]))
        self.assertAlmostEqual(r.max_drawdown_pct, 10.0, places=4)

    def test_max_dd_peak_trough_recorded(self):
        r = self.t.analyze(_pts([100, 120, 90, 130]))
        # worst dd is from 120 to 90 = 25%
        self.assertEqual(r.max_drawdown_peak_usd, 120)
        self.assertEqual(r.max_drawdown_trough_usd, 90)

    def test_trough_is_global_min(self):
        r = self.t.analyze(_pts([100, 70, 130, 90]))
        self.assertEqual(r.trough_value_usd, 70)

    def test_peak_is_global_max(self):
        r = self.t.analyze(_pts([100, 70, 130, 90]))
        self.assertEqual(r.peak_value_usd, 130)

    def test_two_drawdowns_takes_worst(self):
        # dd1: 100->90 (10%); dd2: 120->84 (30%)
        r = self.t.analyze(_pts([100, 90, 120, 84]))
        self.assertAlmostEqual(r.max_drawdown_pct, 30.0, places=4)


class TestUnderwater(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_currently_underwater(self):
        r = self.t.analyze(_pts([100, 120, 90]))
        self.assertTrue(r.underwater_now)

    def test_current_drawdown_pct(self):
        r = self.t.analyze(_pts([100, 120, 90]))
        self.assertAlmostEqual(r.current_drawdown_pct, 25.0, places=4)

    def test_recovered_not_underwater(self):
        r = self.t.analyze(_pts([100, 120, 90, 120]))
        self.assertFalse(r.underwater_now)

    def test_recovered_zero_current_dd(self):
        r = self.t.analyze(_pts([100, 120, 90, 120]))
        self.assertEqual(r.current_drawdown_pct, 0.0)

    def test_longest_underwater_run(self):
        # below peak 100 at indices 1,2,3 then recovers -> longest run 3
        r = self.t.analyze(_pts([100, 90, 85, 80, 110]))
        self.assertEqual(r.longest_underwater_points, 3)

    def test_underwater_advisory(self):
        r = self.t.analyze(_pts([100, 120, 90]))
        self.assertTrue(any("underwater" in a.lower() for a in r.advisory))

    def test_recovered_advisory(self):
        r = self.t.analyze(_pts([100, 80, 130]))
        self.assertTrue(any("recovered" in a.lower() for a in r.advisory))


class TestRecoveryFactor(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_positive_recovery_factor(self):
        # total return (100->130)=0.3 ; max dd 100->80=0.2 ; rf=1.5
        r = self.t.analyze(_pts([100, 80, 130]))
        self.assertAlmostEqual(r.recovery_factor, 1.5, places=4)

    def test_calmar_equals_recovery(self):
        r = self.t.analyze(_pts([100, 80, 130]))
        self.assertEqual(r.calmar_ratio, r.recovery_factor)

    def test_no_drawdown_zero_recovery(self):
        r = self.t.analyze(_pts([100, 110, 120]))
        self.assertEqual(r.recovery_factor, 0.0)

    def test_recovery_below_one_advisory(self):
        # total return 100->105=0.05 ; max dd 120 trough... use simple
        r = self.t.analyze(_pts([100, 120, 90, 105]))
        # total return 0.05, max dd (120->90)=0.25 -> rf=0.2 <1
        self.assertTrue(any("Recovery factor below 1.0" in a for a in r.advisory))

    def test_negative_total_return_negative_rf(self):
        r = self.t.analyze(_pts([100, 80]))
        self.assertLess(r.recovery_factor, 0.0)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_values_rounded(self):
        r = self.t.analyze(_pts([100.123456789, 90.0]))
        self.assertEqual(r.start_value_usd, round(100.123456789, 6))

    def test_pct_rounded_6dp(self):
        r = self.t.analyze(_pts([3, 1]))
        self.assertEqual(r.max_drawdown_pct, round((2 / 3) * 100, 6))

    def test_generated_at_set(self):
        r = self.t.analyze(_pts([1, 2]))
        self.assertTrue(r.generated_at.endswith("Z"))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "dd.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_returns_empty(self):
        self.assertEqual(self.t.load_history(self.path), [])

    def test_save_then_load(self):
        r = self.t.analyze(_pts([100, 80, 90]))
        self.t.save_report(r, self.path)
        hist = self.t.load_history(self.path)
        self.assertEqual(len(hist), 1)

    def test_saved_fields(self):
        r = self.t.analyze(_pts([100, 80, 90]))
        self.t.save_report(r, self.path)
        e = self.t.load_history(self.path)[0]
        self.assertIn("max_drawdown_pct", e)
        self.assertIn("severity", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(3):
            self.t.save_report(self.t.analyze(_pts([100, 80, 90])), self.path)
        self.assertEqual(len(self.t.load_history(self.path)), 3)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 10):
            self.t.save_report(self.t.analyze(_pts([100, 80])), self.path)
        self.assertEqual(len(self.t.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_file_returns_empty(self):
        self.path.write_text("not json{{{")
        self.assertEqual(self.t.load_history(self.path), [])

    def test_atomic_no_tmp_left(self):
        self.t.save_report(self.t.analyze(_pts([100, 80])), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json_on_disk(self):
        self.t.save_report(self.t.analyze(_pts([100, 80])), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "a" / "b" / "dd.json"
        self.t.save_report(self.t.analyze(_pts([100, 80])), nested)
        self.assertTrue(nested.exists())


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownTracker()

    def test_realistic_series(self):
        r = self.t.analyze(_pts([100_000, 108_000, 95_000, 88_000, 101_000, 112_000]))
        self.assertEqual(r.num_points, 6)
        self.assertFalse(r.underwater_now)
        self.assertGreater(r.max_drawdown_pct, 0.0)
        self.assertEqual(r.peak_value_usd, 112_000)

    def test_severity_in_known_set(self):
        r = self.t.analyze(_pts([100, 80, 90]))
        self.assertIn(
            r.severity, {"NONE", "SHALLOW", "MODERATE", "SEVERE", "CRITICAL", "UNKNOWN"}
        )

    def test_advisory_nonempty_on_drawdown(self):
        r = self.t.analyze(_pts([100, 60, 70]))
        self.assertTrue(len(r.advisory) >= 1)

    def test_end_value_recorded(self):
        r = self.t.analyze(_pts([100, 60, 70]))
        self.assertEqual(r.end_value_usd, 70)

    def test_num_points_counts_positive_only(self):
        r = self.t.analyze(_pts([100, 0, 60, -5, 70]))
        self.assertEqual(r.num_points, 3)


if __name__ == "__main__":
    unittest.main()
