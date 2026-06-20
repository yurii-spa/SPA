"""
Tests for MP-762: ConcentrationRiskAnalyzer
≥50 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.concentration_risk_analyzer import (
    HHI_CONCENTRATED,
    HHI_MODERATE,
    HHI_WELL_DIVERSIFIED,
    MAX_ENTRIES,
    TOP1_WARN_THRESHOLD,
    ConcentrationReport,
    ConcentrationRiskAnalyzer,
)


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_empty(self):
        self.assertEqual(self.c._hhi([]), 0.0)

    def test_single_weight_one(self):
        self.assertEqual(self.c._hhi([1.0]), 1.0)

    def test_two_equal(self):
        self.assertAlmostEqual(self.c._hhi([0.5, 0.5]), 0.5)

    def test_four_equal(self):
        self.assertAlmostEqual(self.c._hhi([0.25, 0.25, 0.25, 0.25]), 0.25)

    def test_known_value(self):
        # weights 0.6, 0.3, 0.1 -> 0.36 + 0.09 + 0.01 = 0.46
        self.assertAlmostEqual(self.c._hhi([0.6, 0.3, 0.1]), 0.46)

    def test_equal_weights_is_one_over_n(self):
        n = 5
        w = [1.0 / n] * n
        self.assertAlmostEqual(self.c._hhi(w), 1.0 / n)


class TestEffectiveN(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_zero_hhi(self):
        self.assertEqual(self.c._effective_n(0.0), 0.0)

    def test_negative_hhi(self):
        self.assertEqual(self.c._effective_n(-0.1), 0.0)

    def test_hhi_one(self):
        self.assertEqual(self.c._effective_n(1.0), 1.0)

    def test_hhi_half(self):
        self.assertAlmostEqual(self.c._effective_n(0.5), 2.0)

    def test_hhi_quarter(self):
        self.assertAlmostEqual(self.c._effective_n(0.25), 4.0)


class TestTopNSum(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_empty(self):
        self.assertEqual(self.c._top_n_sum([], 3), 0.0)

    def test_fewer_than_n(self):
        self.assertAlmostEqual(self.c._top_n_sum([0.6, 0.4], 3), 1.0)

    def test_exactly_n(self):
        self.assertAlmostEqual(self.c._top_n_sum([0.5, 0.3, 0.2], 3), 1.0)

    def test_more_than_n(self):
        self.assertAlmostEqual(self.c._top_n_sum([0.4, 0.3, 0.2, 0.1], 3), 0.9)

    def test_picks_largest(self):
        self.assertAlmostEqual(self.c._top_n_sum([0.1, 0.5, 0.4], 1), 0.5)

    def test_single_n_one(self):
        self.assertAlmostEqual(self.c._top_n_sum([0.25, 0.25, 0.25, 0.25], 1), 0.25)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_single_position(self):
        self.assertEqual(self.c._classify(1.0, 1), "SINGLE_POSITION")

    def test_single_position_overrides_hhi(self):
        # n==1 always SINGLE_POSITION regardless of hhi value
        self.assertEqual(self.c._classify(0.05, 1), "SINGLE_POSITION")

    def test_well_diversified(self):
        self.assertEqual(self.c._classify(0.10, 10), "WELL_DIVERSIFIED")

    def test_well_diversified_just_below_boundary(self):
        self.assertEqual(self.c._classify(0.1499, 8), "WELL_DIVERSIFIED")

    def test_moderate_at_boundary(self):
        self.assertEqual(self.c._classify(HHI_WELL_DIVERSIFIED, 5), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(self.c._classify(0.20, 5), "MODERATE")

    def test_concentrated_at_boundary(self):
        self.assertEqual(self.c._classify(HHI_MODERATE, 4), "CONCENTRATED")

    def test_concentrated_mid(self):
        self.assertEqual(self.c._classify(0.30, 4), "CONCENTRATED")

    def test_highly_concentrated_at_boundary(self):
        self.assertEqual(self.c._classify(HHI_CONCENTRATED, 3), "HIGHLY_CONCENTRATED")

    def test_highly_concentrated_high(self):
        self.assertEqual(self.c._classify(0.80, 2), "HIGHLY_CONCENTRATED")

    def test_just_below_moderate(self):
        self.assertEqual(self.c._classify(0.2499, 4), "MODERATE")

    def test_just_below_concentrated(self):
        self.assertEqual(self.c._classify(0.3999, 4), "CONCENTRATED")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_empty_list(self):
        r = self.c.analyze([])
        self.assertEqual(r.concentration_tier, "UNKNOWN")
        self.assertEqual(r.num_positions, 0)

    def test_empty_advisory(self):
        r = self.c.analyze([])
        self.assertTrue(any("No positions" in a for a in r.advisory))

    def test_zero_total(self):
        r = self.c.analyze([0.0, 0.0, 0.0])
        self.assertEqual(r.concentration_tier, "UNKNOWN")

    def test_zero_total_advisory(self):
        r = self.c.analyze([0.0, 0.0])
        self.assertTrue(any("non-positive" in a for a in r.advisory))

    def test_negative_value(self):
        r = self.c.analyze([100.0, -50.0])
        self.assertEqual(r.concentration_tier, "UNKNOWN")

    def test_negative_advisory(self):
        r = self.c.analyze([100.0, -50.0])
        self.assertTrue(any("Negative" in a for a in r.advisory))

    def test_guard_zero_stats(self):
        r = self.c.analyze([])
        self.assertEqual(r.hhi, 0.0)
        self.assertEqual(r.effective_number_of_positions, 0.0)
        self.assertEqual(r.max_weight, 0.0)
        self.assertEqual(r.top1_pct, 0.0)
        self.assertEqual(r.top3_pct, 0.0)

    def test_guard_records_count(self):
        r = self.c.analyze([10.0, -10.0, 5.0])
        self.assertEqual(r.num_positions, 3)

    def test_returns_report_type(self):
        self.assertIsInstance(self.c.analyze([50.0, 50.0]), ConcentrationReport)

    def test_negative_sum_to_positive_still_negative_guard(self):
        # contains a negative even though total > 0
        r = self.c.analyze([100.0, -10.0])
        self.assertEqual(r.concentration_tier, "UNKNOWN")


class TestAnalyzeMath(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_two_equal_hhi_half(self):
        r = self.c.analyze([50.0, 50.0])
        self.assertAlmostEqual(r.hhi, 0.5, places=6)

    def test_two_equal_tier(self):
        r = self.c.analyze([50.0, 50.0])
        self.assertEqual(r.concentration_tier, "HIGHLY_CONCENTRATED")

    def test_equal_weights_hhi_one_over_n(self):
        positions = [100.0] * 10
        r = self.c.analyze(positions)
        self.assertAlmostEqual(r.hhi, 1.0 / 10, places=6)

    def test_equal_weights_well_diversified(self):
        positions = [100.0] * 10
        r = self.c.analyze(positions)
        self.assertEqual(r.concentration_tier, "WELL_DIVERSIFIED")

    def test_effective_n_equals_count_when_equal(self):
        positions = [10.0] * 8
        r = self.c.analyze(positions)
        self.assertAlmostEqual(r.effective_number_of_positions, 8.0, places=4)

    def test_total_recorded(self):
        r = self.c.analyze([30.0, 20.0, 10.0])
        self.assertAlmostEqual(r.total, 60.0, places=6)

    def test_max_weight(self):
        r = self.c.analyze([60.0, 30.0, 10.0])
        self.assertAlmostEqual(r.max_weight, 0.6, places=6)

    def test_top1_equals_max_weight(self):
        r = self.c.analyze([60.0, 30.0, 10.0])
        self.assertEqual(r.top1_pct, r.max_weight)

    def test_top3_all_when_three(self):
        r = self.c.analyze([60.0, 30.0, 10.0])
        self.assertAlmostEqual(r.top3_pct, 1.0, places=6)

    def test_top3_when_more(self):
        r = self.c.analyze([40.0, 30.0, 20.0, 10.0])
        self.assertAlmostEqual(r.top3_pct, 0.9, places=6)

    def test_known_hhi_three_positions(self):
        # 60/30/10 -> weights 0.6/0.3/0.1 -> hhi 0.46
        r = self.c.analyze([60.0, 30.0, 10.0])
        self.assertAlmostEqual(r.hhi, 0.46, places=6)

    def test_num_positions(self):
        r = self.c.analyze([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(r.num_positions, 4)

    def test_weights_work_as_input(self):
        # passing weights summing to 1 directly
        r = self.c.analyze([0.25, 0.25, 0.25, 0.25])
        self.assertAlmostEqual(r.hhi, 0.25, places=6)


class TestSinglePosition(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_single_tier(self):
        r = self.c.analyze([1000.0])
        self.assertEqual(r.concentration_tier, "SINGLE_POSITION")

    def test_single_hhi_one(self):
        r = self.c.analyze([1000.0])
        self.assertAlmostEqual(r.hhi, 1.0, places=6)

    def test_single_effective_n_one(self):
        r = self.c.analyze([1000.0])
        self.assertAlmostEqual(r.effective_number_of_positions, 1.0, places=6)

    def test_single_max_weight_one(self):
        r = self.c.analyze([1000.0])
        self.assertAlmostEqual(r.max_weight, 1.0, places=6)

    def test_single_advisory(self):
        r = self.c.analyze([1000.0])
        self.assertTrue(any("Single position" in a for a in r.advisory))


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_label_of_largest(self):
        r = self.c.analyze([10.0, 80.0, 10.0], labels=["A", "B", "C"])
        self.assertEqual(r.top_position_label, "B")

    def test_no_labels_uses_index(self):
        r = self.c.analyze([10.0, 80.0, 10.0])
        self.assertEqual(r.top_position_label, "1")

    def test_label_first_position(self):
        r = self.c.analyze([90.0, 5.0, 5.0], labels=["X", "Y", "Z"])
        self.assertEqual(r.top_position_label, "X")

    def test_labels_shorter_than_positions_falls_back(self):
        # max index beyond labels length -> index string
        r = self.c.analyze([10.0, 10.0, 90.0], labels=["A", "B"])
        self.assertEqual(r.top_position_label, "2")

    def test_label_non_string_coerced(self):
        r = self.c.analyze([10.0, 80.0, 10.0], labels=[1, 2, 3])
        self.assertEqual(r.top_position_label, "2")


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_top1_warning_present(self):
        r = self.c.analyze([80.0, 10.0, 10.0])
        self.assertTrue(any("exceeds 50%" in a for a in r.advisory))

    def test_top1_warning_absent(self):
        r = self.c.analyze([40.0, 30.0, 30.0])
        self.assertFalse(any("exceeds 50%" in a for a in r.advisory))

    def test_top1_exactly_50_no_warning(self):
        # threshold is strict >, so exactly 0.5 should not warn
        r = self.c.analyze([50.0, 25.0, 25.0])
        self.assertEqual(r.top1_pct, 0.5)
        self.assertFalse(any("exceeds 50%" in a for a in r.advisory))

    def test_effective_n_in_advisory(self):
        r = self.c.analyze([40.0, 30.0, 30.0])
        self.assertTrue(any("Effective number" in a for a in r.advisory))

    def test_well_diversified_advisory(self):
        r = self.c.analyze([100.0] * 10)
        self.assertTrue(any("Well diversified" in a for a in r.advisory))

    def test_highly_concentrated_advisory(self):
        r = self.c.analyze([90.0, 5.0, 5.0])
        self.assertTrue(any("Highly concentrated" in a for a in r.advisory))

    def test_advisory_non_empty(self):
        r = self.c.analyze([40.0, 30.0, 30.0])
        self.assertTrue(len(r.advisory) >= 1)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_all_6dp(self):
        r = self.c.analyze([33.333333, 33.333333, 33.333334])
        for v in (r.hhi, r.effective_number_of_positions, r.max_weight,
                  r.top1_pct, r.top3_pct, r.total):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.c.analyze([50.0, 50.0])
        self.assertTrue(r.generated_at.endswith("Z"))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "conc.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.c.load_history(self.path), [])

    def test_save_then_load(self):
        self.c.save_report(self.c.analyze([50.0, 30.0, 20.0]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.c.save_report(self.c.analyze([50.0, 30.0, 20.0]), self.path)
        e = self.c.load_history(self.path)[0]
        self.assertIn("hhi", e)
        self.assertIn("concentration_tier", e)
        self.assertIn("advisory", e)
        self.assertIn("top_position_label", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.c.save_report(self.c.analyze([50.0, 50.0]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.c.save_report(self.c.analyze([50.0, 50.0]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.c.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.c.save_report(self.c.analyze([50.0, 50.0]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.c.save_report(self.c.analyze([50.0, 50.0]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "conc.json"
        self.c.save_report(self.c.analyze([50.0, 50.0]), nested)
        self.assertTrue(nested.exists())

    def test_round_trip_values(self):
        rep = self.c.analyze([60.0, 30.0, 10.0])
        self.c.save_report(rep, self.path)
        e = self.c.load_history(self.path)[0]
        self.assertEqual(e["hhi"], rep.hhi)
        self.assertEqual(e["concentration_tier"], rep.concentration_tier)


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.c = ConcentrationRiskAnalyzer()

    def test_realistic_portfolio(self):
        positions = [45000.0, 30000.0, 15000.0, 7000.0, 3000.0]
        labels = ["Aave", "Compound", "Pendle", "Curve", "Morpho"]
        r = self.c.analyze(positions, labels=labels)
        self.assertEqual(r.num_positions, 5)
        self.assertEqual(r.top_position_label, "Aave")
        self.assertIn(r.concentration_tier,
                      {"WELL_DIVERSIFIED", "MODERATE", "CONCENTRATED",
                       "HIGHLY_CONCENTRATED"})

    def test_tier_in_known_set(self):
        r = self.c.analyze([10.0, 20.0, 30.0])
        self.assertIn(
            r.concentration_tier,
            {"WELL_DIVERSIFIED", "MODERATE", "CONCENTRATED",
             "HIGHLY_CONCENTRATED", "SINGLE_POSITION", "UNKNOWN"},
        )

    def test_dominant_position_scenario(self):
        r = self.c.analyze([95.0, 2.0, 2.0, 1.0])
        self.assertEqual(r.concentration_tier, "HIGHLY_CONCENTRATED")
        self.assertTrue(any("exceeds 50%" in a for a in r.advisory))

    def test_top1_warn_threshold_constant(self):
        self.assertEqual(TOP1_WARN_THRESHOLD, 0.50)


if __name__ == "__main__":
    unittest.main()
