"""
Tests for MP-719: KellyPositionSizer
≥50 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.kelly_position_sizer import (
    KELLY_CONSERVATIVE_MAX,
    KELLY_MODERATE_MAX,
    MAX_ENTRIES,
    KellyPositionSizer,
    KellyReport,
)


class TestMean(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_empty(self):
        self.assertEqual(self.s._mean([]), 0.0)

    def test_single(self):
        self.assertEqual(self.s._mean([0.05]), 0.05)

    def test_average(self):
        self.assertAlmostEqual(self.s._mean([0.1, 0.2, 0.3]), 0.2)


class TestVariance(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_fewer_than_two(self):
        self.assertEqual(self.s._sample_variance([0.1], 0.1), 0.0)

    def test_empty(self):
        self.assertEqual(self.s._sample_variance([], 0.0), 0.0)

    def test_zero_variance(self):
        self.assertEqual(self.s._sample_variance([0.05, 0.05, 0.05], 0.05), 0.0)

    def test_two_points(self):
        # values 0 and 2, mean 1, sample var = ((1)+(1))/1 = 2
        self.assertAlmostEqual(self.s._sample_variance([0.0, 2.0], 1.0), 2.0)

    def test_known(self):
        xs = [0.0, 0.02]
        m = 0.01
        expected = ((0.0 - 0.01) ** 2 + (0.02 - 0.01) ** 2) / 1
        self.assertAlmostEqual(self.s._sample_variance(xs, m), expected)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_negative(self):
        self.assertEqual(self.s._classify(-0.1), "NEGATIVE")

    def test_zero_conservative(self):
        self.assertEqual(self.s._classify(0.0), "CONSERVATIVE")

    def test_conservative_boundary(self):
        self.assertEqual(self.s._classify(KELLY_CONSERVATIVE_MAX), "CONSERVATIVE")

    def test_moderate_mid(self):
        self.assertEqual(self.s._classify(0.3), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(self.s._classify(KELLY_MODERATE_MAX), "MODERATE")

    def test_aggressive_mid(self):
        self.assertEqual(self.s._classify(0.75), "AGGRESSIVE")

    def test_aggressive_boundary(self):
        self.assertEqual(self.s._classify(1.0), "AGGRESSIVE")

    def test_extreme(self):
        self.assertEqual(self.s._classify(1.5), "EXTREME")

    def test_just_above_conservative(self):
        self.assertEqual(self.s._classify(0.2501), "MODERATE")

    def test_just_above_moderate(self):
        self.assertEqual(self.s._classify(0.5001), "AGGRESSIVE")

    def test_just_above_aggressive(self):
        self.assertEqual(self.s._classify(1.0001), "EXTREME")


class TestKellyFromReturnsGuards(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_empty(self):
        r = self.s.kelly_from_returns([])
        self.assertEqual(r.method, "UNKNOWN")
        self.assertEqual(r.aggressiveness_tier, "UNKNOWN")

    def test_single(self):
        r = self.s.kelly_from_returns([0.05])
        self.assertEqual(r.method, "UNKNOWN")

    def test_single_advisory(self):
        r = self.s.kelly_from_returns([0.05])
        self.assertTrue(any("at least 2" in a for a in r.advisory))

    def test_empty_num_samples(self):
        r = self.s.kelly_from_returns([])
        self.assertEqual(r.num_samples, 0)

    def test_single_num_samples(self):
        r = self.s.kelly_from_returns([0.05])
        self.assertEqual(r.num_samples, 1)

    def test_returns_report_type(self):
        self.assertIsInstance(self.s.kelly_from_returns([0.01, 0.02]), KellyReport)

    def test_unknown_zero_fractions(self):
        r = self.s.kelly_from_returns([0.05])
        self.assertEqual(r.kelly_fraction, 0.0)
        self.assertEqual(r.capped_fraction, 0.0)
        self.assertEqual(r.recommended_fraction, 0.0)


class TestKellyFromReturnsMath(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_method_returns(self):
        r = self.s.kelly_from_returns([0.01, 0.02, 0.015])
        self.assertEqual(r.method, "RETURNS")

    def test_num_samples(self):
        r = self.s.kelly_from_returns([0.01, 0.02, 0.015, 0.03])
        self.assertEqual(r.num_samples, 4)

    def test_win_prob_none(self):
        r = self.s.kelly_from_returns([0.01, 0.02])
        self.assertIsNone(r.win_prob)
        self.assertIsNone(r.win_loss_ratio)

    def test_kelly_value(self):
        # returns [0.0, 0.02], mean 0.01, var 0.0002, kelly = 0.01/0.0002 = 50
        r = self.s.kelly_from_returns([0.0, 0.02])
        mean = 0.01
        var = ((0.0 - 0.01) ** 2 + (0.02 - 0.01) ** 2) / 1
        self.assertAlmostEqual(r.kelly_fraction, round(mean / var, 6), places=6)

    def test_risk_free_reduces_kelly(self):
        base = self.s.kelly_from_returns([0.02, 0.03, 0.04], risk_free_per_period=0.0)
        with_rf = self.s.kelly_from_returns([0.02, 0.03, 0.04], risk_free_per_period=0.01)
        self.assertGreater(base.kelly_fraction, with_rf.kelly_fraction)

    def test_zero_variance_kelly_zero(self):
        r = self.s.kelly_from_returns([0.05, 0.05, 0.05])
        self.assertEqual(r.kelly_fraction, 0.0)

    def test_zero_variance_advisory(self):
        r = self.s.kelly_from_returns([0.05, 0.05, 0.05])
        self.assertTrue(any("Zero variance" in a for a in r.advisory))

    def test_zero_variance_tier(self):
        r = self.s.kelly_from_returns([0.05, 0.05, 0.05])
        self.assertEqual(r.aggressiveness_tier, "CONSERVATIVE")

    def test_negative_edge(self):
        # mean negative => kelly negative => NEGATIVE tier
        r = self.s.kelly_from_returns([-0.02, -0.01, -0.03])
        self.assertLess(r.kelly_fraction, 0.0)
        self.assertEqual(r.aggressiveness_tier, "NEGATIVE")

    def test_negative_edge_advisory(self):
        r = self.s.kelly_from_returns([-0.02, -0.01, -0.03])
        self.assertTrue(any("do not allocate" in a for a in r.advisory))

    def test_negative_edge_capped_zero(self):
        r = self.s.kelly_from_returns([-0.02, -0.01, -0.03])
        self.assertEqual(r.capped_fraction, 0.0)
        self.assertEqual(r.recommended_fraction, 0.0)

    def test_positive_edge_positive_kelly(self):
        r = self.s.kelly_from_returns([0.01, 0.012, 0.011, 0.013])
        self.assertGreater(r.kelly_fraction, 0.0)


class TestKellyFromOddsGuards(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_win_prob_too_high(self):
        r = self.s.kelly_from_odds(1.5, 1.2)
        self.assertEqual(r.method, "UNKNOWN")
        self.assertEqual(r.aggressiveness_tier, "UNKNOWN")

    def test_win_prob_negative(self):
        r = self.s.kelly_from_odds(-0.1, 1.2)
        self.assertEqual(r.method, "UNKNOWN")

    def test_win_prob_advisory(self):
        r = self.s.kelly_from_odds(1.5, 1.2)
        self.assertTrue(any("win_prob" in a for a in r.advisory))

    def test_zero_ratio(self):
        r = self.s.kelly_from_odds(0.6, 0.0)
        self.assertEqual(r.method, "UNKNOWN")

    def test_negative_ratio(self):
        r = self.s.kelly_from_odds(0.6, -1.0)
        self.assertEqual(r.method, "UNKNOWN")

    def test_ratio_advisory(self):
        r = self.s.kelly_from_odds(0.6, 0.0)
        self.assertTrue(any("win_loss_ratio" in a for a in r.advisory))

    def test_unknown_preserves_inputs(self):
        r = self.s.kelly_from_odds(1.5, 1.2)
        self.assertEqual(r.win_prob, 1.5)
        self.assertEqual(r.win_loss_ratio, 1.2)


class TestKellyFromOddsMath(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_method_odds(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertEqual(r.method, "ODDS")

    def test_num_samples_zero(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertEqual(r.num_samples, 0)

    def test_records_inputs(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertEqual(r.win_prob, 0.55)
        self.assertEqual(r.win_loss_ratio, 1.2)

    def test_kelly_value(self):
        # (0.55*1.2 - 0.45)/1.2 = (0.66 - 0.45)/1.2 = 0.175
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertAlmostEqual(r.kelly_fraction, round(0.21 / 1.2, 6), places=6)

    def test_even_money_fair(self):
        # win_prob 0.5, b=1 => kelly = (0.5 - 0.5)/1 = 0.0
        r = self.s.kelly_from_odds(0.5, 1.0)
        self.assertAlmostEqual(r.kelly_fraction, 0.0, places=6)

    def test_no_edge_negative(self):
        # win_prob 0.4, b=1 => (0.4 - 0.6)/1 = -0.2
        r = self.s.kelly_from_odds(0.4, 1.0)
        self.assertLess(r.kelly_fraction, 0.0)
        self.assertEqual(r.aggressiveness_tier, "NEGATIVE")

    def test_strong_edge(self):
        # win_prob 0.9, b=2 => (1.8 - 0.1)/2 = 0.85 => AGGRESSIVE
        r = self.s.kelly_from_odds(0.9, 2.0)
        self.assertEqual(r.aggressiveness_tier, "AGGRESSIVE")

    def test_win_prob_one_full(self):
        # win_prob 1.0, b=1 => (1.0 - 0.0)/1 = 1.0 => AGGRESSIVE boundary
        r = self.s.kelly_from_odds(1.0, 1.0)
        self.assertAlmostEqual(r.kelly_fraction, 1.0, places=6)


class TestCapping(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_cap_when_kelly_above_one(self):
        # win_prob 1.0, small b=0.5 => (0.5 - 0.0)/0.5 = 1.0 ... use returns for >1
        r = self.s.kelly_from_returns([0.0, 0.02])  # kelly ~ 50 >> 1
        self.assertGreater(r.kelly_fraction, 1.0)
        self.assertEqual(r.capped_fraction, 1.0)

    def test_extreme_tier_when_kelly_above_one(self):
        r = self.s.kelly_from_returns([0.0, 0.02])
        self.assertEqual(r.aggressiveness_tier, "EXTREME")

    def test_extreme_advisory_leverage(self):
        r = self.s.kelly_from_returns([0.0, 0.02])
        self.assertTrue(any("leverage" in a.lower() for a in r.advisory))

    def test_custom_cap(self):
        r = self.s.kelly_from_returns([0.0, 0.02], cap=0.5)
        self.assertEqual(r.capped_fraction, 0.5)
        self.assertEqual(r.cap, 0.5)

    def test_half_kelly_is_half_capped(self):
        r = self.s.kelly_from_returns([0.0, 0.02])
        self.assertAlmostEqual(r.half_kelly, r.capped_fraction / 2.0, places=6)

    def test_quarter_kelly_is_quarter_capped(self):
        r = self.s.kelly_from_returns([0.0, 0.02])
        self.assertAlmostEqual(r.quarter_kelly, r.capped_fraction / 4.0, places=6)

    def test_recommended_is_half_kelly(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertAlmostEqual(r.recommended_fraction, r.half_kelly, places=6)

    def test_recommended_not_above_cap(self):
        r = self.s.kelly_from_returns([0.0, 0.02], cap=1.0)
        self.assertLessEqual(r.recommended_fraction, r.cap)

    def test_invalid_cap_defaults_to_one(self):
        r = self.s.kelly_from_returns([0.0, 0.02], cap=0.0)
        self.assertEqual(r.cap, 1.0)

    def test_capped_never_negative(self):
        r = self.s.kelly_from_returns([-0.05, -0.03])
        self.assertGreaterEqual(r.capped_fraction, 0.0)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_always_fractional_advice(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        self.assertTrue(any("fractional" in a.lower() for a in r.advisory))

    def test_fractional_advice_on_returns(self):
        r = self.s.kelly_from_returns([0.01, 0.012, 0.011])
        self.assertTrue(any("fractional" in a.lower() for a in r.advisory))

    def test_advisory_present(self):
        r = self.s.kelly_from_odds(0.6, 1.5)
        self.assertGreaterEqual(len(r.advisory), 1)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_all_fields_6dp(self):
        r = self.s.kelly_from_returns([0.013, 0.027, 0.011])
        for v in (
            r.kelly_fraction,
            r.capped_fraction,
            r.half_kelly,
            r.quarter_kelly,
            r.recommended_fraction,
            r.cap,
        ):
            self.assertEqual(v, round(v, 6))

    def test_odds_fields_6dp(self):
        r = self.s.kelly_from_odds(0.55, 1.2)
        for v in (r.kelly_fraction, r.capped_fraction, r.half_kelly, r.quarter_kelly):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.s.kelly_from_returns([0.01, 0.02])
        self.assertTrue(r.generated_at.endswith("Z"))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "kelly.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.s.load_history(self.path), [])

    def test_save_then_load(self):
        self.s.save_report(self.s.kelly_from_returns([0.01, 0.02, 0.015]), self.path)
        self.assertEqual(len(self.s.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.s.save_report(self.s.kelly_from_odds(0.55, 1.2), self.path)
        e = self.s.load_history(self.path)[0]
        self.assertIn("kelly_fraction", e)
        self.assertIn("recommended_fraction", e)
        self.assertIn("aggressiveness_tier", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), self.path)
        self.assertEqual(len(self.s.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), self.path)
        self.assertEqual(len(self.s.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.s.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "kelly.json"
        self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), nested)
        self.assertTrue(nested.exists())

    def test_save_odds_report(self):
        self.s.save_report(self.s.kelly_from_odds(0.55, 1.2), self.path)
        e = self.s.load_history(self.path)[0]
        self.assertEqual(e["method"], "ODDS")
        self.assertEqual(e["win_prob"], 0.55)

    def test_ring_buffer_keeps_latest(self):
        for _ in range(MAX_ENTRIES + 3):
            self.s.save_report(self.s.kelly_from_returns([0.01, 0.02]), self.path)
        hist = self.s.load_history(self.path)
        self.assertEqual(len(hist), MAX_ENTRIES)
        self.assertEqual(hist[-1]["method"], "RETURNS")


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.s = KellyPositionSizer()

    def test_realistic_returns(self):
        returns = [0.012, 0.008, -0.004, 0.015, 0.006, 0.010, -0.002, 0.009]
        r = self.s.kelly_from_returns(returns, risk_free_per_period=0.003)
        self.assertEqual(r.method, "RETURNS")
        self.assertIn(
            r.aggressiveness_tier,
            {"NEGATIVE", "CONSERVATIVE", "MODERATE", "AGGRESSIVE", "EXTREME"},
        )
        self.assertGreaterEqual(len(r.advisory), 1)

    def test_realistic_odds(self):
        r = self.s.kelly_from_odds(win_prob=0.55, win_loss_ratio=1.2)
        self.assertEqual(r.method, "ODDS")
        self.assertGreater(r.kelly_fraction, 0.0)
        self.assertGreaterEqual(len(r.advisory), 1)

    def test_tier_in_known_set(self):
        r = self.s.kelly_from_odds(0.6, 1.5)
        self.assertIn(
            r.aggressiveness_tier,
            {"NEGATIVE", "CONSERVATIVE", "MODERATE", "AGGRESSIVE", "EXTREME", "UNKNOWN"},
        )


if __name__ == "__main__":
    unittest.main()
