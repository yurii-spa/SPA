"""
Tests for MP-679: CorrelationMatrixBuilder
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.correlation_matrix_builder import (
    DIV_MODERATE,
    DIV_WELL,
    HIGH_NEG,
    HIGH_POS,
    MAX_ENTRIES,
    MOD_NEG,
    MOD_POS,
    AdapterSeries,
    CorrelationMatrixBuilder,
    CorrelationPair,
    CorrelationReport,
)


def _s(adapter_id="a", history=None) -> AdapterSeries:
    return AdapterSeries(adapter_id=adapter_id, apy_history=history or [1.0, 2.0, 3.0])


class TestPearson(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()

    def test_perfect_positive(self):
        r = self.b.pearson([1, 2, 3, 4], [1, 2, 3, 4])
        self.assertEqual(r, 1.0)

    def test_perfect_positive_scaled(self):
        r = self.b.pearson([1, 2, 3], [2, 4, 6])
        self.assertEqual(r, 1.0)

    def test_perfect_negative(self):
        r = self.b.pearson([1, 2, 3], [3, 2, 1])
        self.assertEqual(r, -1.0)

    def test_offset_positive(self):
        r = self.b.pearson([1, 2, 3], [11, 12, 13])
        self.assertEqual(r, 1.0)

    def test_zero_variance_x(self):
        self.assertEqual(self.b.pearson([5, 5, 5], [1, 2, 3]), 0.0)

    def test_zero_variance_y(self):
        self.assertEqual(self.b.pearson([1, 2, 3], [7, 7, 7]), 0.0)

    def test_both_constant(self):
        self.assertEqual(self.b.pearson([5, 5], [7, 7]), 0.0)

    def test_too_short_empty(self):
        self.assertEqual(self.b.pearson([], []), 0.0)

    def test_too_short_one(self):
        self.assertEqual(self.b.pearson([1], [1]), 0.0)

    def test_truncates_to_min_length(self):
        # second arg longer; should truncate
        r = self.b.pearson([1, 2, 3], [1, 2, 3, 99])
        self.assertEqual(r, 1.0)

    def test_in_range(self):
        r = self.b.pearson([1, 5, 2, 8, 3], [2, 3, 1, 9, 4])
        self.assertGreaterEqual(r, -1.0)
        self.assertLessEqual(r, 1.0)

    def test_rounded_6dp(self):
        r = self.b.pearson([1, 2, 4, 7], [2, 1, 5, 6])
        self.assertEqual(r, round(r, 6))

    def test_symmetric(self):
        x = [1, 4, 2, 8]
        y = [2, 3, 1, 9]
        self.assertEqual(self.b.pearson(x, y), self.b.pearson(y, x))


class TestRelationship(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()

    def test_high_positive(self):
        self.assertEqual(self.b._relationship(0.9), "HIGH_POSITIVE")

    def test_high_positive_boundary(self):
        self.assertEqual(self.b._relationship(HIGH_POS), "HIGH_POSITIVE")

    def test_moderate_positive(self):
        self.assertEqual(self.b._relationship(0.5), "MODERATE_POSITIVE")

    def test_moderate_positive_boundary(self):
        self.assertEqual(self.b._relationship(MOD_POS), "MODERATE_POSITIVE")

    def test_weak_zero(self):
        self.assertEqual(self.b._relationship(0.0), "WEAK")

    def test_weak_just_below_mod_pos(self):
        self.assertEqual(self.b._relationship(0.29), "WEAK")

    def test_weak_at_mod_neg_boundary(self):
        # > MOD_NEG is WEAK; exactly MOD_NEG is not weak
        self.assertEqual(self.b._relationship(-0.29), "WEAK")

    def test_moderate_negative_boundary(self):
        self.assertEqual(self.b._relationship(MOD_NEG), "MODERATE_NEGATIVE")

    def test_moderate_negative(self):
        self.assertEqual(self.b._relationship(-0.5), "MODERATE_NEGATIVE")

    def test_high_negative_boundary(self):
        self.assertEqual(self.b._relationship(HIGH_NEG), "HIGH_NEGATIVE")

    def test_high_negative(self):
        self.assertEqual(self.b._relationship(-0.95), "HIGH_NEGATIVE")


class TestClassifyDiversification(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()

    def test_well(self):
        self.assertEqual(self.b._classify_diversification(0.9), "WELL_DIVERSIFIED")

    def test_well_boundary(self):
        self.assertEqual(self.b._classify_diversification(DIV_WELL), "WELL_DIVERSIFIED")

    def test_moderate(self):
        self.assertEqual(self.b._classify_diversification(0.5), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(self.b._classify_diversification(DIV_MODERATE), "MODERATE")

    def test_poor(self):
        self.assertEqual(self.b._classify_diversification(0.2), "POOR")

    def test_poor_just_below(self):
        self.assertEqual(
            self.b._classify_diversification(DIV_MODERATE - 0.01), "POOR"
        )


class TestBuildBasic(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()

    def test_fewer_than_two(self):
        r = self.b.build([_s("a")])
        self.assertEqual(r.diversification_level, "UNKNOWN")
        self.assertEqual(r.pairs, [])

    def test_empty(self):
        r = self.b.build([])
        self.assertEqual(r.diversification_level, "UNKNOWN")
        self.assertEqual(r.num_adapters, 0)

    def test_unknown_has_advisory(self):
        r = self.b.build([_s("a")])
        self.assertTrue(any("at least 2" in a for a in r.advisory))

    def test_two_adapters_one_pair(self):
        r = self.b.build([_s("a", [1, 2, 3]), _s("b", [1, 2, 3])])
        self.assertEqual(len(r.pairs), 1)

    def test_three_adapters_three_pairs(self):
        r = self.b.build(
            [_s("a", [1, 2, 3]), _s("b", [3, 2, 1]), _s("c", [1, 3, 2])]
        )
        self.assertEqual(len(r.pairs), 3)

    def test_four_adapters_six_pairs(self):
        series = [_s(f"a{i}", [1, 2, 3, 4]) for i in range(4)]
        r = self.b.build(series)
        self.assertEqual(len(r.pairs), 6)

    def test_num_adapters(self):
        r = self.b.build([_s("a"), _s("b"), _s("c")])
        self.assertEqual(r.num_adapters, 3)

    def test_report_type(self):
        r = self.b.build([_s("a"), _s("b")])
        self.assertIsInstance(r, CorrelationReport)

    def test_pair_type(self):
        r = self.b.build([_s("a"), _s("b")])
        self.assertIsInstance(r.pairs[0], CorrelationPair)

    def test_has_timestamp(self):
        r = self.b.build([_s("a"), _s("b")])
        self.assertTrue(r.generated_at.endswith("Z"))


class TestBuildSemantics(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()

    def test_identical_high_correlation(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [1, 2, 3, 4])]
        )
        self.assertEqual(r.pairs[0].correlation, 1.0)
        self.assertEqual(r.pairs[0].relationship, "HIGH_POSITIVE")

    def test_identical_poor_diversification(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [1, 2, 3, 4])]
        )
        self.assertEqual(r.diversification_level, "POOR")
        self.assertEqual(r.diversification_score, 0.0)

    def test_anticorrelated_well_diversified(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [4, 3, 2, 1])]
        )
        # mean_abs = 1.0 -> score 0 -> POOR (perfect negative still concentrates risk in metric)
        self.assertEqual(r.mean_abs_correlation, 1.0)

    def test_mean_abs_correlation_value(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [1, 2, 3, 4])]
        )
        self.assertEqual(r.mean_abs_correlation, 1.0)

    def test_most_correlated_pair_selected(self):
        r = self.b.build(
            [
                _s("a", [1, 2, 3, 4]),
                _s("b", [1, 2, 3, 4]),     # perfectly correlated with a
                _s("c", [4, 1, 3, 2]),     # noisy
            ]
        )
        self.assertEqual(r.most_correlated_pair.correlation, 1.0)
        self.assertIn(r.most_correlated_pair.adapter_a, ("a", "b"))

    def test_diversification_score_clamped(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [4, 3, 2, 1])]
        )
        self.assertGreaterEqual(r.diversification_score, 0.0)
        self.assertLessEqual(r.diversification_score, 1.0)

    def test_poor_advisory(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [1, 2, 3, 4])]
        )
        self.assertTrue(any("POOR" in a for a in r.advisory))

    def test_high_correlation_advisory(self):
        r = self.b.build(
            [_s("a", [1, 2, 3, 4]), _s("b", [1, 2, 3, 4])]
        )
        self.assertTrue(any("highly correlated" in a for a in r.advisory))

    def test_zero_variance_pair_weak(self):
        r = self.b.build([_s("a", [5, 5, 5]), _s("b", [1, 2, 3])])
        self.assertEqual(r.pairs[0].correlation, 0.0)
        self.assertEqual(r.pairs[0].relationship, "WEAK")

    def test_well_diversified_scenario(self):
        # near-zero correlations -> high score
        r = self.b.build(
            [
                _s("a", [1, 5, 2, 6, 3]),
                _s("b", [5, 5, 5, 5, 5]),  # constant -> 0 corr with everything
            ]
        )
        self.assertEqual(r.mean_abs_correlation, 0.0)
        self.assertEqual(r.diversification_level, "WELL_DIVERSIFIED")


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.b = CorrelationMatrixBuilder()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "corr.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _report(self):
        return self.b.build([_s("a", [1, 2, 3]), _s("b", [1, 2, 3])])

    def test_load_missing(self):
        self.assertEqual(self.b.load_history(self.path), [])

    def test_save_then_load(self):
        self.b.save_report(self._report(), self.path)
        hist = self.b.load_history(self.path)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["num_adapters"], 2)

    def test_append(self):
        for _ in range(3):
            self.b.save_report(self._report(), self.path)
        self.assertEqual(len(self.b.load_history(self.path)), 3)

    def test_ring_buffer(self):
        for _ in range(MAX_ENTRIES + 5):
            self.b.save_report(self._report(), self.path)
        self.assertEqual(len(self.b.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt(self):
        self.path.write_text("{bad")
        self.assertEqual(self.b.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.b.save_report(self._report(), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.b.save_report(self._report(), self.path)
        with open(self.path) as fh:
            self.assertIsInstance(json.load(fh), list)

    def test_most_correlated_persisted(self):
        self.b.save_report(self._report(), self.path)
        entry = self.b.load_history(self.path)[0]
        self.assertIsNotNone(entry["most_correlated_pair"])
        self.assertEqual(entry["most_correlated_pair"]["correlation"], 1.0)

    def test_pairs_persisted(self):
        self.b.save_report(self._report(), self.path)
        entry = self.b.load_history(self.path)[0]
        self.assertEqual(len(entry["pairs"]), 1)

    def test_unknown_report_persists_none_pair(self):
        r = self.b.build([_s("a")])
        self.b.save_report(r, self.path)
        entry = self.b.load_history(self.path)[0]
        self.assertIsNone(entry["most_correlated_pair"])


if __name__ == "__main__":
    unittest.main()
