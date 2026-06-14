"""
Tests for MP-783: RewardEmissionDecayTracker
>=70 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.reward_emission_decay_tracker import (
    DECAYING_FACTOR,
    GROWING_FACTOR,
    HIGH_HALF_LIFE,
    MEDIUM_HALF_LIFE,
    MAX_ENTRIES,
    RewardEmissionDecayTracker,
    EmissionDecayReport,
)


class TestClassifyTrend(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_none_unknown(self):
        self.assertEqual(self.t._classify_trend(None), "UNKNOWN")

    def test_decaying_low(self):
        self.assertEqual(self.t._classify_trend(0.9), "DECAYING")

    def test_decaying_just_below(self):
        self.assertEqual(self.t._classify_trend(0.9799), "DECAYING")

    def test_stable_at_decaying_boundary(self):
        self.assertEqual(self.t._classify_trend(DECAYING_FACTOR), "STABLE")

    def test_stable_one(self):
        self.assertEqual(self.t._classify_trend(1.0), "STABLE")

    def test_stable_at_growing_boundary(self):
        self.assertEqual(self.t._classify_trend(GROWING_FACTOR), "STABLE")

    def test_growing_just_above(self):
        self.assertEqual(self.t._classify_trend(1.0201), "GROWING")

    def test_growing_high(self):
        self.assertEqual(self.t._classify_trend(1.5), "GROWING")


class TestClassifySustainability(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_unknown_trend(self):
        self.assertEqual(self.t._classify_sustainability("UNKNOWN", None), "UNKNOWN")

    def test_stable_high(self):
        self.assertEqual(self.t._classify_sustainability("STABLE", None), "HIGH")

    def test_growing_high(self):
        self.assertEqual(self.t._classify_sustainability("GROWING", None), "HIGH")

    def test_decaying_none_half_life_high(self):
        self.assertEqual(self.t._classify_sustainability("DECAYING", None), "HIGH")

    def test_decaying_long_half_life_high(self):
        self.assertEqual(
            self.t._classify_sustainability("DECAYING", HIGH_HALF_LIFE), "HIGH"
        )

    def test_decaying_medium(self):
        self.assertEqual(
            self.t._classify_sustainability("DECAYING", MEDIUM_HALF_LIFE), "MEDIUM"
        )

    def test_decaying_medium_mid(self):
        self.assertEqual(self.t._classify_sustainability("DECAYING", 12.0), "MEDIUM")

    def test_decaying_low(self):
        self.assertEqual(self.t._classify_sustainability("DECAYING", 3.0), "LOW")

    def test_decaying_low_just_below_medium(self):
        self.assertEqual(
            self.t._classify_sustainability("DECAYING", MEDIUM_HALF_LIFE - 0.01), "LOW"
        )


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_empty_unknown(self):
        r = self.t.analyze([])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")
        self.assertEqual(r.trend, "UNKNOWN")

    def test_empty_num_points(self):
        r = self.t.analyze([])
        self.assertEqual(r.num_points, 0)

    def test_single_unknown(self):
        r = self.t.analyze([100.0])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")

    def test_single_advisory(self):
        r = self.t.analyze([100.0])
        self.assertTrue(any("at least 2" in x for x in r.advisory))

    def test_single_current_set(self):
        r = self.t.analyze([42.0])
        self.assertEqual(r.current_emission, 42.0)
        self.assertEqual(r.initial_emission, 42.0)

    def test_zero_initial_unknown(self):
        r = self.t.analyze([0.0, 100.0])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")

    def test_zero_current_unknown(self):
        r = self.t.analyze([100.0, 0.0])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")

    def test_negative_endpoint_unknown(self):
        r = self.t.analyze([100.0, -50.0])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")

    def test_negative_initial_unknown(self):
        r = self.t.analyze([-100.0, 50.0])
        self.assertEqual(r.sustainability_tier, "UNKNOWN")

    def test_nonpositive_advisory(self):
        r = self.t.analyze([100.0, 0.0])
        self.assertTrue(any("positive" in x for x in r.advisory))

    def test_guard_no_projection(self):
        r = self.t.analyze([0.0, 100.0])
        self.assertEqual(r.projected_emissions, [])

    def test_guard_factor_none(self):
        r = self.t.analyze([100.0, 0.0])
        self.assertIsNone(r.period_decay_rate)

    def test_returns_report_type(self):
        self.assertIsInstance(self.t.analyze([100.0, 90.0]), EmissionDecayReport)


class TestDecayFactor(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_two_points_factor(self):
        # 100 -> 50 over 1 step -> factor 0.5
        r = self.t.analyze([100.0, 50.0])
        self.assertAlmostEqual(r.period_decay_rate, 0.5, places=6)

    def test_factor_geometric(self):
        # 100 -> 25 over 2 steps -> factor 0.5
        r = self.t.analyze([100.0, 50.0, 25.0])
        self.assertAlmostEqual(r.period_decay_rate, 0.5, places=6)

    def test_decay_pct(self):
        r = self.t.analyze([100.0, 50.0])
        self.assertAlmostEqual(r.decay_pct_per_period, 0.5, places=6)

    def test_factor_one_no_decay(self):
        r = self.t.analyze([100.0, 100.0, 100.0])
        self.assertAlmostEqual(r.period_decay_rate, 1.0, places=8)
        self.assertAlmostEqual(r.decay_pct_per_period, 0.0, places=8)

    def test_factor_one_half_life_none(self):
        r = self.t.analyze([100.0, 100.0])
        self.assertIsNone(r.half_life_periods)

    def test_factor_one_stable(self):
        r = self.t.analyze([100.0, 100.0])
        self.assertEqual(r.trend, "STABLE")

    def test_growth_factor_above_one(self):
        r = self.t.analyze([100.0, 200.0])
        self.assertAlmostEqual(r.period_decay_rate, 2.0, places=6)

    def test_growth_negative_decay_pct(self):
        r = self.t.analyze([100.0, 200.0])
        self.assertLess(r.decay_pct_per_period, 0.0)


class TestHalfLife(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_half_life_factor_half(self):
        # factor 0.5 -> half-life exactly 1 period
        r = self.t.analyze([100.0, 50.0])
        self.assertAlmostEqual(r.half_life_periods, 1.0, places=6)

    def test_half_life_formula(self):
        r = self.t.analyze([100.0, 90.0])
        expected = math.log(0.5) / math.log(0.9)
        self.assertAlmostEqual(r.half_life_periods, round(expected, 6), places=6)

    def test_half_life_growing_none(self):
        r = self.t.analyze([100.0, 200.0])
        self.assertIsNone(r.half_life_periods)

    def test_half_life_factor_one_none(self):
        r = self.t.analyze([100.0, 100.0])
        self.assertIsNone(r.half_life_periods)

    def test_half_life_slow_decay_large(self):
        r = self.t.analyze([100.0, 99.0])
        self.assertGreater(r.half_life_periods, 24.0)

    def test_half_life_fast_decay_small(self):
        r = self.t.analyze([100.0, 10.0])
        self.assertLess(r.half_life_periods, 1.5)


class TestTrend(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_decaying(self):
        r = self.t.analyze([1000.0, 900.0, 800.0])
        self.assertEqual(r.trend, "DECAYING")

    def test_stable(self):
        r = self.t.analyze([1000.0, 1000.0, 1000.0])
        self.assertEqual(r.trend, "STABLE")

    def test_stable_small_wobble(self):
        # factor close to 1, within +/-2%
        r = self.t.analyze([1000.0, 1005.0])
        self.assertEqual(r.trend, "STABLE")

    def test_growing(self):
        r = self.t.analyze([1000.0, 1100.0, 1210.0])
        self.assertEqual(r.trend, "GROWING")

    def test_decaying_2pct(self):
        # factor exactly 0.97 -> below 0.98 -> DECAYING
        r = self.t.analyze([100.0, 97.0])
        self.assertEqual(r.trend, "DECAYING")


class TestSustainabilityTier(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_stable_high(self):
        r = self.t.analyze([1000.0, 1000.0, 1000.0])
        self.assertEqual(r.sustainability_tier, "HIGH")

    def test_growing_high(self):
        r = self.t.analyze([1000.0, 1100.0])
        self.assertEqual(r.sustainability_tier, "HIGH")

    def test_slow_decay_high(self):
        # 1% per period decay -> half-life ~69 -> HIGH
        r = self.t.analyze([1000.0, 990.0])
        self.assertEqual(r.sustainability_tier, "HIGH")

    def test_moderate_decay_medium(self):
        # ~7% per period -> half-life ~9.5 periods -> MEDIUM
        r = self.t.analyze([1000.0, 930.0])
        self.assertEqual(r.sustainability_tier, "MEDIUM")

    def test_fast_decay_low(self):
        # 30% per period -> half-life ~1.9 -> LOW
        r = self.t.analyze([1000.0, 700.0])
        self.assertEqual(r.sustainability_tier, "LOW")

    def test_tier_in_known_set(self):
        r = self.t.analyze([1000.0, 950.0, 900.0])
        self.assertIn(
            r.sustainability_tier, {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
        )


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_projection_length(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=12)
        self.assertEqual(len(r.projected_emissions), 12)

    def test_projection_length_custom(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=5)
        self.assertEqual(len(r.projected_emissions), 5)

    def test_projection_first_step(self):
        # factor 0.5, current 50 -> first projected 25
        r = self.t.analyze([100.0, 50.0], periods_ahead=3)
        self.assertAlmostEqual(r.projected_emissions[0], 25.0, places=6)

    def test_projection_decaying(self):
        r = self.t.analyze([100.0, 50.0], periods_ahead=3)
        self.assertGreater(r.projected_emissions[0], r.projected_emissions[1])

    def test_projection_growing_increases(self):
        r = self.t.analyze([100.0, 200.0], periods_ahead=3)
        self.assertGreater(r.projected_emissions[1], r.projected_emissions[0])

    def test_projection_stable_constant(self):
        r = self.t.analyze([100.0, 100.0], periods_ahead=3)
        for v in r.projected_emissions:
            self.assertAlmostEqual(v, 100.0, places=6)

    def test_zero_periods_ahead(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=0)
        self.assertEqual(r.projected_emissions, [])

    def test_negative_periods_ahead_clamped(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=-3)
        self.assertEqual(r.projected_emissions, [])
        self.assertEqual(r.periods_ahead, 0)

    def test_cumulative_sum(self):
        r = self.t.analyze([100.0, 50.0], periods_ahead=3)
        self.assertAlmostEqual(
            r.cumulative_projected, sum(r.projected_emissions), places=6
        )

    def test_cumulative_zero_when_no_periods(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=0)
        self.assertEqual(r.cumulative_projected, 0.0)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_high_msg(self):
        r = self.t.analyze([1000.0, 1000.0])
        self.assertTrue(any("sustainable" in x for x in r.advisory))

    def test_medium_msg(self):
        r = self.t.analyze([1000.0, 930.0])
        self.assertTrue(any("moderately decaying" in x for x in r.advisory))

    def test_low_msg(self):
        r = self.t.analyze([1000.0, 700.0])
        self.assertTrue(any("decaying fast" in x for x in r.advisory))

    def test_decaying_pct_note(self):
        r = self.t.analyze([1000.0, 700.0])
        self.assertTrue(any("per period" in x for x in r.advisory))

    def test_growing_note(self):
        r = self.t.analyze([1000.0, 1100.0])
        self.assertTrue(any("growing" in x.lower() for x in r.advisory))

    def test_advisory_nonempty(self):
        r = self.t.analyze([1000.0, 900.0])
        self.assertGreaterEqual(len(r.advisory), 1)


class TestFields(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_num_points(self):
        r = self.t.analyze([100.0, 90.0, 80.0, 70.0])
        self.assertEqual(r.num_points, 4)

    def test_current_initial(self):
        r = self.t.analyze([100.0, 90.0, 80.0])
        self.assertEqual(r.initial_emission, 100.0)
        self.assertEqual(r.current_emission, 80.0)

    def test_label_propagated(self):
        r = self.t.analyze([100.0, 90.0], label="CRV")
        self.assertEqual(r.label, "CRV")

    def test_generated_at_z(self):
        r = self.t.analyze([100.0, 90.0])
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_periods_ahead_recorded(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=8)
        self.assertEqual(r.periods_ahead, 8)


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_same_factor(self):
        r1 = self.t.analyze([100.0, 80.0, 64.0])
        r2 = self.t.analyze([100.0, 80.0, 64.0])
        self.assertEqual(r1.period_decay_rate, r2.period_decay_rate)

    def test_same_tier(self):
        r1 = self.t.analyze([1000.0, 700.0])
        r2 = self.t.analyze([1000.0, 700.0])
        self.assertEqual(r1.sustainability_tier, r2.sustainability_tier)

    def test_same_projection(self):
        r1 = self.t.analyze([100.0, 90.0], periods_ahead=6)
        r2 = self.t.analyze([100.0, 90.0], periods_ahead=6)
        self.assertEqual(r1.projected_emissions, r2.projected_emissions)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_factor_8dp(self):
        r = self.t.analyze([100.0, 33.0])
        self.assertEqual(r.period_decay_rate, round(r.period_decay_rate, 8))

    def test_half_life_6dp(self):
        r = self.t.analyze([100.0, 90.0])
        self.assertEqual(r.half_life_periods, round(r.half_life_periods, 6))

    def test_projection_8dp(self):
        r = self.t.analyze([100.0, 90.0], periods_ahead=3)
        for v in r.projected_emissions:
            self.assertEqual(v, round(v, 8))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "emi.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.t.load_history(self.path), [])

    def test_save_then_load(self):
        self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        self.assertEqual(len(self.t.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        e = self.t.load_history(self.path)[0]
        self.assertIn("sustainability_tier", e)
        self.assertIn("trend", e)
        self.assertIn("projected_emissions", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        self.assertEqual(len(self.t.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        self.assertEqual(len(self.t.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.t.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.t.save_report(self.t.analyze([100.0, 90.0]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "emi.json"
        self.t.save_report(self.t.analyze([100.0, 90.0]), nested)
        self.assertTrue(nested.exists())

    def test_save_unknown_report(self):
        self.t.save_report(self.t.analyze([100.0]), self.path)
        e = self.t.load_history(self.path)[0]
        self.assertEqual(e["sustainability_tier"], "UNKNOWN")


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.t = RewardEmissionDecayTracker()

    def test_realistic_decay(self):
        series = [1000.0, 960.0, 925.0, 890.0, 855.0, 820.0]
        r = self.t.analyze(series, periods_ahead=12, label="demo")
        self.assertEqual(r.num_points, 6)
        self.assertEqual(r.trend, "DECAYING")
        self.assertEqual(len(r.projected_emissions), 12)
        self.assertGreaterEqual(len(r.advisory), 1)

    def test_stable_scenario(self):
        r = self.t.analyze([500.0, 500.0, 500.0, 500.0], periods_ahead=6)
        self.assertEqual(r.trend, "STABLE")
        self.assertEqual(r.sustainability_tier, "HIGH")

    def test_growing_scenario(self):
        r = self.t.analyze([100.0, 120.0, 144.0], periods_ahead=4)
        self.assertEqual(r.trend, "GROWING")
        self.assertEqual(r.sustainability_tier, "HIGH")

    def test_fast_decay_scenario(self):
        r = self.t.analyze([1000.0, 500.0, 250.0], periods_ahead=6)
        self.assertEqual(r.trend, "DECAYING")
        self.assertEqual(r.sustainability_tier, "LOW")

    def test_tier_known_set(self):
        r = self.t.analyze([1000.0, 900.0, 810.0])
        self.assertIn(r.sustainability_tier, {"HIGH", "MEDIUM", "LOW", "UNKNOWN"})


if __name__ == "__main__":
    unittest.main()
