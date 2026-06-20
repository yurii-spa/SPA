"""
Tests for MP-745: YieldSpreadZScoreAnalyzer
>=60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import math
import sys
import unittest
import tempfile
from pathlib import Path

# Make spa_core importable when run directly from spa_core/tests.
_SPA_ROOT = Path(__file__).resolve().parents[2]
if str(_SPA_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPA_ROOT))

from spa_core.analytics.yield_spread_zscore_analyzer import (  # noqa: E402
    MAX_ENTRIES,
    SpreadZReport,
    YieldSpreadZScoreAnalyzer,
)


class TestMean(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_empty(self):
        self.assertEqual(self.a._mean([]), 0.0)

    def test_single(self):
        self.assertEqual(self.a._mean([1.5]), 1.5)

    def test_average(self):
        self.assertAlmostEqual(self.a._mean([1.0, 2.0, 3.0]), 2.0)

    def test_negative(self):
        self.assertAlmostEqual(self.a._mean([-1.0, 1.0]), 0.0)


class TestStdev(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_fewer_than_two(self):
        self.assertEqual(self.a._sample_stdev([1.0], 1.0), 0.0)

    def test_empty(self):
        self.assertEqual(self.a._sample_stdev([], 0.0), 0.0)

    def test_zero_variance(self):
        self.assertEqual(self.a._sample_stdev([2.0, 2.0, 2.0], 2.0), 0.0)

    def test_two_points(self):
        self.assertAlmostEqual(self.a._sample_stdev([0.0, 2.0], 1.0), math.sqrt(2.0))

    def test_known_value(self):
        xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean = sum(xs) / len(xs)
        self.assertAlmostEqual(
            self.a._sample_stdev(xs, mean), math.sqrt(32 / 7), places=6
        )


class TestPercentile(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_empty(self):
        self.assertEqual(self.a._percentile_of([], 1.0), 0.0)

    def test_all_below(self):
        self.assertEqual(self.a._percentile_of([1.0, 2.0, 3.0], 5.0), 1.0)

    def test_all_above(self):
        self.assertEqual(self.a._percentile_of([1.0, 2.0, 3.0], 0.5), 0.0)

    def test_middle(self):
        # 2 of 4 values <= 2.0
        self.assertEqual(self.a._percentile_of([1.0, 2.0, 3.0, 4.0], 2.0), 0.5)

    def test_inclusive(self):
        # value equal to a sample counts (<=)
        self.assertEqual(self.a._percentile_of([1.0, 1.0], 1.0), 1.0)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_strong_long_at_neg_entry(self):
        self.assertEqual(self.a._classify(-2.0, 2.0), "STRONG_LONG")

    def test_strong_long_below(self):
        self.assertEqual(self.a._classify(-3.5, 2.0), "STRONG_LONG")

    def test_lean_long_band(self):
        self.assertEqual(self.a._classify(-1.5, 2.0), "LEAN_LONG")

    def test_lean_long_at_neg_one(self):
        self.assertEqual(self.a._classify(-1.0, 2.0), "LEAN_LONG")

    def test_neutral_just_above_neg_one(self):
        self.assertEqual(self.a._classify(-0.999, 2.0), "NEUTRAL")

    def test_neutral_zero(self):
        self.assertEqual(self.a._classify(0.0, 2.0), "NEUTRAL")

    def test_neutral_just_below_one(self):
        self.assertEqual(self.a._classify(0.999, 2.0), "NEUTRAL")

    def test_lean_short_at_one(self):
        self.assertEqual(self.a._classify(1.0, 2.0), "LEAN_SHORT")

    def test_lean_short_band(self):
        self.assertEqual(self.a._classify(1.5, 2.0), "LEAN_SHORT")

    def test_lean_short_just_below_entry(self):
        self.assertEqual(self.a._classify(1.999, 2.0), "LEAN_SHORT")

    def test_strong_short_at_entry(self):
        self.assertEqual(self.a._classify(2.0, 2.0), "STRONG_SHORT")

    def test_strong_short_above(self):
        self.assertEqual(self.a._classify(3.5, 2.0), "STRONG_SHORT")

    def test_custom_entry_z(self):
        # entry_z 3.0: z=-2.5 is between -3 and -1 -> LEAN_LONG
        self.assertEqual(self.a._classify(-2.5, 3.0), "LEAN_LONG")

    def test_custom_entry_strong(self):
        self.assertEqual(self.a._classify(-3.0, 3.0), "STRONG_LONG")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_empty_unknown(self):
        r = self.a.analyze([])
        self.assertEqual(r.signal_tier, "UNKNOWN")
        self.assertEqual(r.samples, 0)

    def test_empty_current_none(self):
        r = self.a.analyze([])
        self.assertIsNone(r.current_spread)

    def test_empty_min_max_none(self):
        r = self.a.analyze([])
        self.assertIsNone(r.min_spread)
        self.assertIsNone(r.max_spread)

    def test_single_unknown(self):
        r = self.a.analyze([1.5])
        self.assertEqual(r.signal_tier, "UNKNOWN")
        self.assertEqual(r.samples, 1)

    def test_single_current_recorded(self):
        r = self.a.analyze([1.5])
        self.assertEqual(r.current_spread, 1.5)

    def test_single_zero_z(self):
        r = self.a.analyze([1.5])
        self.assertEqual(r.zscore, 0.0)
        self.assertEqual(r.stdev_spread, 0.0)

    def test_single_advisory(self):
        r = self.a.analyze([1.5])
        self.assertTrue(any(s in r.advisory for s in ("at least 2", "2 samples")))

    def test_returns_report_type(self):
        self.assertIsInstance(self.a.analyze([1.0, 2.0]), SpreadZReport)


class TestConstantSeries(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_constant_zero_z(self):
        r = self.a.analyze([1.5, 1.5, 1.5, 1.5])
        self.assertEqual(r.zscore, 0.0)

    def test_constant_zero_stdev(self):
        r = self.a.analyze([1.5, 1.5, 1.5])
        self.assertEqual(r.stdev_spread, 0.0)

    def test_constant_neutral(self):
        r = self.a.analyze([1.5, 1.5, 1.5])
        self.assertEqual(r.signal_tier, "NEUTRAL")

    def test_constant_zero_range(self):
        r = self.a.analyze([1.5, 1.5, 1.5])
        self.assertEqual(r.spread_range, 0.0)


class TestKnownZScore(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_known_zscore_value(self):
        spreads = [1.0, 2.0, 3.0]
        mean = 2.0
        stdev = math.sqrt(((1 - 2) ** 2 + (2 - 2) ** 2 + (3 - 2) ** 2) / 2)
        expected = round((spreads[-1] - mean) / stdev, 6)
        r = self.a.analyze(spreads)
        self.assertAlmostEqual(r.zscore, expected, places=6)

    def test_zscore_positive_when_current_high(self):
        r = self.a.analyze([1.0, 1.0, 1.0, 5.0])
        self.assertGreater(r.zscore, 0.0)

    def test_zscore_negative_when_current_low(self):
        r = self.a.analyze([5.0, 5.0, 5.0, 1.0])
        self.assertLess(r.zscore, 0.0)

    def test_mean_recorded(self):
        r = self.a.analyze([1.0, 2.0, 3.0])
        self.assertEqual(r.mean_spread, 2.0)

    def test_two_point_zscore(self):
        # [0, 2]: mean 1, stdev sqrt2, current 2 -> z = 1/sqrt2
        r = self.a.analyze([0.0, 2.0])
        self.assertAlmostEqual(r.zscore, round(1.0 / math.sqrt(2.0), 6), places=6)


class TestSignalTiers(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_strong_long(self):
        # build a series where the last point is far below the mean
        spreads = [2.0] * 10 + [0.5]
        r = self.a.analyze(spreads, entry_z=2.0)
        self.assertEqual(r.signal_tier, "STRONG_LONG")

    def test_strong_short(self):
        spreads = [2.0] * 10 + [3.5]
        r = self.a.analyze(spreads, entry_z=2.0)
        self.assertEqual(r.signal_tier, "STRONG_SHORT")

    def test_neutral(self):
        # current equals mean -> z 0 -> NEUTRAL
        r = self.a.analyze([1.0, 2.0, 3.0, 2.0])
        self.assertEqual(r.signal_tier, "NEUTRAL")

    def test_lean_long(self):
        # craft z between -2 and -1
        spreads = [1.0, 1.0, 1.0, 1.0, 0.7]
        r = self.a.analyze(spreads, entry_z=2.0)
        self.assertEqual(r.signal_tier, "LEAN_LONG")

    def test_lean_short(self):
        spreads = [1.0, 1.0, 1.0, 1.0, 1.3]
        r = self.a.analyze(spreads, entry_z=2.0)
        self.assertEqual(r.signal_tier, "LEAN_SHORT")

    def test_all_five_tiers_reachable(self):
        seen = set()
        seen.add(self.a.analyze([2.0] * 10 + [0.5]).signal_tier)
        seen.add(self.a.analyze([2.0] * 10 + [3.5]).signal_tier)
        seen.add(self.a.analyze([1.0, 2.0, 3.0, 2.0]).signal_tier)
        seen.add(self.a.analyze([1.0, 1.0, 1.0, 1.0, 0.7]).signal_tier)
        seen.add(self.a.analyze([1.0, 1.0, 1.0, 1.0, 1.3]).signal_tier)
        self.assertEqual(
            seen,
            {"STRONG_LONG", "STRONG_SHORT", "NEUTRAL", "LEAN_LONG", "LEAN_SHORT"},
        )


class TestPercentileOfCurrent(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_current_is_max(self):
        r = self.a.analyze([1.0, 2.0, 3.0])
        self.assertEqual(r.percentile_of_current, 1.0)

    def test_current_is_min(self):
        r = self.a.analyze([3.0, 2.0, 1.0])
        # current 1.0, only 1 of 3 <= 1.0
        self.assertAlmostEqual(r.percentile_of_current, 1 / 3, places=6)

    def test_current_middle(self):
        r = self.a.analyze([1.0, 3.0, 2.0])
        # current 2.0, 2 of 3 <= 2.0
        self.assertAlmostEqual(r.percentile_of_current, 2 / 3, places=6)


class TestRangeAndExtremes(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_min_max(self):
        r = self.a.analyze([1.0, 5.0, 3.0, 0.5])
        self.assertEqual(r.min_spread, 0.5)
        self.assertEqual(r.max_spread, 5.0)

    def test_spread_range(self):
        r = self.a.analyze([1.0, 5.0, 3.0, 0.5])
        self.assertAlmostEqual(r.spread_range, 4.5, places=6)

    def test_current_recorded(self):
        r = self.a.analyze([1.0, 2.0, 3.5])
        self.assertEqual(r.current_spread, 3.5)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_all_floats_6dp(self):
        r = self.a.analyze([1.123456789, 2.234567891, 0.345678912])
        for v in (
            r.current_spread,
            r.mean_spread,
            r.stdev_spread,
            r.zscore,
            r.min_spread,
            r.max_spread,
            r.spread_range,
            r.percentile_of_current,
        ):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.a.analyze([1.0, 2.0])
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_label_recorded(self):
        r = self.a.analyze([1.0, 2.0], label="aave-comp")
        self.assertEqual(r.label, "aave-comp")

    def test_entry_z_recorded(self):
        r = self.a.analyze([1.0, 2.0], entry_z=2.5)
        self.assertEqual(r.entry_z, 2.5)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_strong_long_advisory(self):
        r = self.a.analyze([2.0] * 10 + [0.5])
        self.assertIn("long", r.advisory.lower())

    def test_strong_short_advisory(self):
        r = self.a.analyze([2.0] * 10 + [3.5])
        self.assertIn("short", r.advisory.lower())

    def test_neutral_advisory(self):
        r = self.a.analyze([1.0, 2.0, 3.0, 2.0])
        self.assertIn("mean", r.advisory.lower())


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "zscore.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.a.load_history(self.path), [])

    def test_save_then_load(self):
        self.a.save_report(self.a.analyze([1.0, 2.0, 3.0]), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.a.save_report(self.a.analyze([1.0, 2.0, 3.0]), self.path)
        e = self.a.load_history(self.path)[0]
        self.assertIn("zscore", e)
        self.assertIn("signal_tier", e)
        self.assertIn("percentile_of_current", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.a.save_report(self.a.analyze([1.0, 2.0]), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 6):
            self.a.save_report(self.a.analyze([1.0, 2.0]), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.a.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.a.save_report(self.a.analyze([1.0, 2.0]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_no_tmp_left_after_many(self):
        for _ in range(5):
            self.a.save_report(self.a.analyze([1.0, 2.0]), self.path)
        leftovers = list(Path(self.tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_valid_json(self):
        self.a.save_report(self.a.analyze([1.0, 2.0]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "zscore.json"
        self.a.save_report(self.a.analyze([1.0, 2.0]), nested)
        self.assertTrue(nested.exists())

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            r = self.a.analyze([1.0, 2.0], label=f"L{i}")
            self.a.save_report(r, self.path)
        hist = self.a.load_history(self.path)
        self.assertEqual(hist[-1]["label"], f"L{MAX_ENTRIES + 2}")


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.a = YieldSpreadZScoreAnalyzer()

    def test_realistic_series(self):
        spreads = [1.2, 1.3, 1.1, 1.4, 1.25, 1.35, 1.15, 1.3, 0.4]
        r = self.a.analyze(spreads, entry_z=2.0, label="aave-compound")
        self.assertEqual(r.samples, 9)
        self.assertIn(
            r.signal_tier,
            {
                "STRONG_LONG",
                "LEAN_LONG",
                "NEUTRAL",
                "LEAN_SHORT",
                "STRONG_SHORT",
                "UNKNOWN",
            },
        )
        self.assertTrue(len(r.advisory) > 0)

    def test_tier_in_known_set(self):
        r = self.a.analyze([1.0, 2.0, 3.0])
        self.assertIn(
            r.signal_tier,
            {
                "STRONG_LONG",
                "LEAN_LONG",
                "NEUTRAL",
                "LEAN_SHORT",
                "STRONG_SHORT",
                "UNKNOWN",
            },
        )

    def test_negative_spreads(self):
        # spreads can be negative (APY_a < APY_b); analyzer still works
        r = self.a.analyze([-0.5, -0.3, -0.7, -2.0])
        self.assertLess(r.zscore, 0.0)
        self.assertEqual(r.min_spread, -2.0)


if __name__ == "__main__":
    unittest.main()
