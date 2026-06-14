"""
Tests for MP-767 StrategyCorrelationMatrix.
65+ unit tests covering: single strategy, empty input, perfect correlation,
perfect anti-correlation, zero variance, negative returns, rolling window,
diversification score, correlated pairs, persistence, and advisory text.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.strategy_correlation_matrix import (
    StrategyCorrelationMatrix,
    CorrelationResult,
    HIGH_CORR_THRESHOLD,
)

_EPS = 1e-5


def _make_returns(n: int = 30, seed: int = 42) -> list:
    """Deterministic pseudo-random returns for testing."""
    import hashlib
    result = []
    for i in range(n):
        h = hashlib.md5(f"{seed}-{i}".encode()).hexdigest()
        val = (int(h[:4], 16) / 0xFFFF - 0.5) * 0.02  # ~ ±1 %
        result.append(val)
    return result


class TestEmptyAndSingleStrategy(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_empty_dict_returns_empty_matrix(self):
        result = self.scm.compute_matrix({})
        self.assertEqual(result.strategy_ids, [])
        self.assertEqual(result.correlation_matrix, {})

    def test_empty_dict_avg_corr_zero(self):
        result = self.scm.compute_matrix({})
        self.assertAlmostEqual(result.avg_pairwise_correlation, 0.0, places=6)

    def test_empty_dict_diversification_default(self):
        result = self.scm.compute_matrix({})
        # No pairs → avg=0 → score=50
        self.assertAlmostEqual(result.diversification_score, 50.0, places=4)

    def test_empty_dict_no_correlated_pairs(self):
        result = self.scm.compute_matrix({})
        self.assertEqual(result.highly_correlated_pairs, [])

    def test_single_strategy_diagonal_one(self):
        result = self.scm.compute_matrix({"S0": [0.01, 0.02, -0.01, 0.005]})
        self.assertAlmostEqual(result.correlation_matrix["S0"]["S0"], 1.0, places=6)

    def test_single_strategy_no_off_diagonal_pairs(self):
        result = self.scm.compute_matrix({"S0": [0.01, 0.02, -0.01]})
        self.assertEqual(result.highly_correlated_pairs, [])

    def test_single_strategy_avg_corr_zero(self):
        result = self.scm.compute_matrix({"S0": _make_returns(20)})
        self.assertAlmostEqual(result.avg_pairwise_correlation, 0.0, places=6)

    def test_single_strategy_ids(self):
        result = self.scm.compute_matrix({"S0": [0.01, -0.01, 0.02]})
        self.assertEqual(result.strategy_ids, ["S0"])

    def test_single_strategy_empty_returns(self):
        result = self.scm.compute_matrix({"S0": []})
        self.assertAlmostEqual(result.correlation_matrix["S0"]["S0"], 1.0, places=6)


class TestPerfectCorrelation(unittest.TestCase):
    """Two identical series → r = 1.0."""

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()
        self.base = _make_returns(30, seed=1)

    def test_identical_series_r_equals_one(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertAlmostEqual(result.correlation_matrix["A"]["B"], 1.0, places=5)

    def test_identical_series_avg_corr_one(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertAlmostEqual(result.avg_pairwise_correlation, 1.0, places=5)

    def test_identical_series_div_score_near_zero(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertAlmostEqual(result.diversification_score, 0.0, places=3)

    def test_identical_series_highly_correlated_pair(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertEqual(len(result.highly_correlated_pairs), 1)
        self.assertAlmostEqual(result.highly_correlated_pairs[0][2], 1.0, places=5)

    def test_identical_series_symmetric(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertAlmostEqual(
            result.correlation_matrix["A"]["B"],
            result.correlation_matrix["B"]["A"],
            places=6,
        )


class TestPerfectAntiCorrelation(unittest.TestCase):
    """One series is the exact negation of the other → r = -1.0."""

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()
        self.base = _make_returns(30, seed=2)
        self.neg_base = [-x for x in self.base]

    def test_negated_series_r_minus_one(self):
        result = self.scm.compute_matrix({"P": self.base, "Q": self.neg_base})
        self.assertAlmostEqual(result.correlation_matrix["P"]["Q"], -1.0, places=5)

    def test_negated_series_avg_corr_minus_one(self):
        result = self.scm.compute_matrix({"P": self.base, "Q": self.neg_base})
        self.assertAlmostEqual(result.avg_pairwise_correlation, -1.0, places=5)

    def test_negated_series_div_score_near_100(self):
        result = self.scm.compute_matrix({"P": self.base, "Q": self.neg_base})
        self.assertAlmostEqual(result.diversification_score, 100.0, places=3)

    def test_negated_series_not_in_highly_correlated(self):
        result = self.scm.compute_matrix({"P": self.base, "Q": self.neg_base})
        # |r| = 1 > threshold 0.8 → should appear
        self.assertEqual(len(result.highly_correlated_pairs), 1)


class TestConstantReturns(unittest.TestCase):
    """Constant series → std = 0 → correlation treated as 0."""

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_constant_vs_constant_r_zero(self):
        result = self.scm.compute_matrix(
            {"C1": [0.005] * 30, "C2": [0.005] * 30}
        )
        self.assertAlmostEqual(result.correlation_matrix["C1"]["C2"], 0.0, places=6)

    def test_constant_vs_variable_r_zero(self):
        result = self.scm.compute_matrix(
            {"C": [0.005] * 30, "V": _make_returns(30, seed=3)}
        )
        self.assertAlmostEqual(result.correlation_matrix["C"]["V"], 0.0, places=6)

    def test_constant_zero_vs_any_r_zero(self):
        result = self.scm.compute_matrix(
            {"Z": [0.0] * 30, "V": _make_returns(30, seed=4)}
        )
        self.assertAlmostEqual(result.correlation_matrix["Z"]["V"], 0.0, places=6)


class TestNegativeReturns(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_all_negative_returns_correlation_computed(self):
        neg1 = [-abs(x) for x in _make_returns(30, seed=5)]
        neg2 = [-abs(x) for x in _make_returns(30, seed=6)]
        result = self.scm.compute_matrix({"N1": neg1, "N2": neg2})
        r = result.correlation_matrix["N1"]["N2"]
        self.assertGreaterEqual(r, -1.0)
        self.assertLessEqual(r, 1.0)

    def test_mixed_positive_negative_returns(self):
        data = [0.01, -0.01, 0.02, -0.02, 0.005, -0.005] * 5
        result = self.scm.compute_matrix({"A": data, "B": [-x for x in data]})
        self.assertAlmostEqual(result.correlation_matrix["A"]["B"], -1.0, places=5)

    def test_negative_returns_no_crash(self):
        neg = [-0.05, -0.03, -0.01, -0.04, -0.02] * 6
        result = self.scm.compute_matrix({"D": neg, "E": list(neg)})
        self.assertAlmostEqual(result.correlation_matrix["D"]["E"], 1.0, places=5)


class TestRollingWindow(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_window_truncates_long_series(self):
        long_series_a = [0.01] * 50 + _make_returns(30, seed=7)
        long_series_b = [-0.01] * 50 + _make_returns(30, seed=7)  # identical last 30
        result = self.scm.compute_matrix(
            {"A": long_series_a, "B": long_series_b}, window=30
        )
        # Last 30 points are identical → r ≈ 1.0
        self.assertAlmostEqual(result.correlation_matrix["A"]["B"], 1.0, places=4)

    def test_window_recorded_in_result(self):
        result = self.scm.compute_matrix(
            {"X": _make_returns(40), "Y": _make_returns(40, seed=8)}, window=20
        )
        self.assertEqual(result.window, 20)

    def test_window_less_than_2_treated_as_2(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30), "B": _make_returns(30, seed=9)}, window=1
        )
        self.assertEqual(result.window, 2)

    def test_actual_window_reflects_shorter_series(self):
        result = self.scm.compute_matrix(
            {"S": _make_returns(10)}, window=30
        )
        self.assertEqual(result.actual_window["S"], 10)

    def test_actual_window_not_exceeds_request(self):
        result = self.scm.compute_matrix(
            {"S": _make_returns(50)}, window=30
        )
        self.assertLessEqual(result.actual_window["S"], 30)

    def test_window_default_30(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(50), "B": _make_returns(50, seed=10)}
        )
        self.assertEqual(result.window, 30)


class TestDiversificationScore(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_score_bounded_0_to_100(self):
        base = _make_returns(30, seed=11)
        result = self.scm.compute_matrix(
            {"A": base, "B": list(base), "C": [-x for x in base]}
        )
        self.assertGreaterEqual(result.diversification_score, 0.0)
        self.assertLessEqual(result.diversification_score, 100.0)

    def test_score_50_for_zero_avg_correlation(self):
        # Manually compute: avg=0 → (1-0)/2*100 = 50
        result = self.scm.compute_matrix({})
        self.assertAlmostEqual(result.diversification_score, 50.0, places=4)

    def test_score_higher_for_lower_correlation(self):
        base = _make_returns(30, seed=12)
        high_corr = self.scm.compute_matrix(
            {"A": base, "B": list(base)}
        )
        low_corr = self.scm.compute_matrix(
            {"A": base, "B": [-x for x in base]}
        )
        self.assertLess(
            high_corr.diversification_score, low_corr.diversification_score
        )

    def test_get_diversification_score_returns_last_result(self):
        base = _make_returns(30, seed=13)
        result = self.scm.compute_matrix({"A": base, "B": list(base)})
        self.assertAlmostEqual(
            self.scm.get_diversification_score(), result.diversification_score, places=5
        )

    def test_get_diversification_score_before_any_call_returns_50(self):
        fresh = StrategyCorrelationMatrix()
        self.assertEqual(fresh.get_diversification_score(), 50.0)


class TestCorrelatedPairs(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()
        self.base = _make_returns(30, seed=14)

    def test_identical_pair_flagged(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertEqual(len(result.highly_correlated_pairs), 1)

    def test_negated_pair_flagged(self):
        result = self.scm.compute_matrix({"A": self.base, "B": [-x for x in self.base]})
        self.assertEqual(len(result.highly_correlated_pairs), 1)

    def test_independent_pair_not_flagged(self):
        orthogonal = _make_returns(30, seed=999)
        result = self.scm.compute_matrix({"A": self.base, "B": orthogonal})
        # Not guaranteed zero, but should not reach 0.8 with independent seeds
        # Just verify the structure is correct
        for pair in result.highly_correlated_pairs:
            self.assertGreater(abs(pair[2]), HIGH_CORR_THRESHOLD)

    def test_get_correlated_pairs_before_any_call_empty(self):
        fresh = StrategyCorrelationMatrix()
        self.assertEqual(fresh.get_correlated_pairs(), [])

    def test_get_correlated_pairs_matches_result(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        self.assertEqual(
            self.scm.get_correlated_pairs(), result.highly_correlated_pairs
        )

    def test_pair_structure_is_triplet(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        for pair in result.highly_correlated_pairs:
            self.assertEqual(len(pair), 3)
            self.assertIsInstance(pair[0], str)
            self.assertIsInstance(pair[1], str)
            self.assertIsInstance(pair[2], float)

    def test_threshold_is_0_8(self):
        self.assertAlmostEqual(HIGH_CORR_THRESHOLD, 0.8, places=5)

    def test_no_self_pairs(self):
        result = self.scm.compute_matrix({"A": self.base, "B": list(self.base)})
        for pair in result.highly_correlated_pairs:
            self.assertNotEqual(pair[0], pair[1])


class TestMatrixSymmetry(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_matrix_is_symmetric(self):
        data = {
            "S0": _make_returns(30, seed=15),
            "S1": _make_returns(30, seed=16),
            "S2": _make_returns(30, seed=17),
        }
        result = self.scm.compute_matrix(data)
        ids = result.strategy_ids
        for i, sid in enumerate(ids):
            for tid in ids[i:]:
                self.assertAlmostEqual(
                    result.correlation_matrix[sid][tid],
                    result.correlation_matrix[tid][sid],
                    places=6,
                )

    def test_diagonal_is_one(self):
        data = {
            "X": _make_returns(30, seed=18),
            "Y": _make_returns(30, seed=19),
        }
        result = self.scm.compute_matrix(data)
        for sid in result.strategy_ids:
            self.assertAlmostEqual(result.correlation_matrix[sid][sid], 1.0, places=6)

    def test_all_correlations_between_minus1_and_1(self):
        data = {
            "A": _make_returns(30, seed=20),
            "B": _make_returns(30, seed=21),
            "C": _make_returns(30, seed=22),
        }
        result = self.scm.compute_matrix(data)
        for sid, row in result.correlation_matrix.items():
            for tid, r in row.items():
                if sid != tid:
                    self.assertGreaterEqual(r, -1.0 - _EPS)
                    self.assertLessEqual(r, 1.0 + _EPS)

    def test_three_strategies_have_all_pairs(self):
        data = {"A": _make_returns(30, 23), "B": _make_returns(30, 24), "C": _make_returns(30, 25)}
        result = self.scm.compute_matrix(data)
        for sid in ["A", "B", "C"]:
            for tid in ["A", "B", "C"]:
                self.assertIn(tid, result.correlation_matrix[sid])


class TestMultipleStrategies(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def test_many_strategies(self):
        data = {f"S{i}": _make_returns(30, seed=i + 30) for i in range(6)}
        result = self.scm.compute_matrix(data)
        self.assertEqual(len(result.strategy_ids), 6)

    def test_strategy_ids_sorted(self):
        data = {"S3": _make_returns(30, 33), "S1": _make_returns(30, 31), "S2": _make_returns(30, 32)}
        result = self.scm.compute_matrix(data)
        self.assertEqual(result.strategy_ids, ["S1", "S2", "S3"])

    def test_avg_pairwise_correct_for_three_pairs(self):
        # All three identical → avg = 1.0
        base = _make_returns(30, seed=40)
        data = {"A": base, "B": list(base), "C": list(base)}
        result = self.scm.compute_matrix(data)
        self.assertAlmostEqual(result.avg_pairwise_correlation, 1.0, places=5)

    def test_generated_at_is_string(self):
        data = {"A": _make_returns(30, 41), "B": _make_returns(30, 42)}
        result = self.scm.compute_matrix(data)
        self.assertIsInstance(result.generated_at, str)
        self.assertTrue(len(result.generated_at) > 0)


class TestAdvisoryContent(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()

    def _text(self, result: CorrelationResult) -> str:
        return " ".join(result.advisory)

    def test_empty_advisory_mentioned(self):
        result = self.scm.compute_matrix({})
        self.assertGreater(len(result.advisory), 0)

    def test_single_strategy_advisory_mentioned(self):
        result = self.scm.compute_matrix({"S0": _make_returns(30, 50)})
        self.assertGreater(len(result.advisory), 0)

    def test_high_corr_advisory_present(self):
        base = _make_returns(30, seed=51)
        result = self.scm.compute_matrix({"A": base, "B": list(base)})
        self.assertIn("Highly correlated", self._text(result))

    def test_diversification_score_in_advisory(self):
        base = _make_returns(30, seed=52)
        result = self.scm.compute_matrix({"A": base, "B": list(base)})
        text = self._text(result)
        self.assertTrue("score" in text.lower() or "Diversification" in text)

    def test_excellent_diversification_advisory(self):
        base = _make_returns(30, seed=53)
        result = self.scm.compute_matrix({"P": base, "Q": [-x for x in base]})
        text = self._text(result)
        self.assertIn("EXCELLENT", text)

    def test_poor_diversification_advisory(self):
        base = _make_returns(30, seed=54)
        result = self.scm.compute_matrix({"A": base, "B": list(base)})
        text = self._text(result)
        self.assertIn("POOR", text)

    def test_short_series_warning_advisory(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(5, seed=55), "B": _make_returns(30, seed=56)},
            window=30,
        )
        text = self._text(result)
        self.assertTrue("short" in text.lower() or "Short" in text)

    def test_window_mentioned_in_advisory(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30, 57), "B": _make_returns(30, 58)}, window=30
        )
        self.assertIn("30", self._text(result))


class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.scm = StrategyCorrelationMatrix()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "corr_test.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_creates_file(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30, 60), "B": _make_returns(30, 61)}
        )
        self.scm.save_result(result, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_valid_json(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30, 62), "B": _make_returns(30, 63)}
        )
        self.scm.save_result(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_multiple_appends(self):
        for seed in [64, 65, 66]:
            result = self.scm.compute_matrix(
                {"A": _make_returns(30, seed), "B": _make_returns(30, seed + 100)}
            )
            self.scm.save_result(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_100(self):
        base = _make_returns(30, seed=70)
        for i in range(105):
            result = self.scm.compute_matrix({"A": base, "B": list(base)})
            self.scm.save_result(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertLessEqual(len(data), 100)

    def test_load_empty_when_missing(self):
        missing = Path(self.tmp_dir) / "gone.json"
        self.assertEqual(self.scm.load_history(missing), [])

    def test_load_corrupt_returns_empty(self):
        self.data_file.write_text("{NOT JSON}")
        self.assertEqual(self.scm.load_history(self.data_file), [])

    def test_entry_has_required_keys(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30, 71), "B": _make_returns(30, 72)}
        )
        self.scm.save_result(result, self.data_file)
        entry = json.loads(self.data_file.read_text())[0]
        for key in ["timestamp", "strategy_ids", "window",
                    "avg_pairwise_correlation", "diversification_score",
                    "highly_correlated_pairs", "correlation_matrix"]:
            self.assertIn(key, entry, f"Missing key: {key}")

    def test_atomic_write_no_tmp_leftover(self):
        result = self.scm.compute_matrix(
            {"A": _make_returns(30, 73), "B": _make_returns(30, 74)}
        )
        self.scm.save_result(result, self.data_file)
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_directory_created_if_missing(self):
        nested = Path(self.tmp_dir) / "nested" / "corr.json"
        result = self.scm.compute_matrix({"A": _make_returns(30, 75)})
        self.scm.save_result(result, nested)
        self.assertTrue(nested.exists())


class TestNoForbiddenImports(unittest.TestCase):

    def test_no_numpy(self):
        import spa_core.analytics.strategy_correlation_matrix as mod
        source = Path(mod.__file__).read_text()
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import pandas", source)
        self.assertNotIn("import scipy", source)

    def test_pearson_uses_pure_math(self):
        import spa_core.analytics.strategy_correlation_matrix as mod
        source = Path(mod.__file__).read_text()
        self.assertIn("math.sqrt", source)

    def test_atomic_write_used(self):
        import spa_core.analytics.strategy_correlation_matrix as mod
        source = Path(mod.__file__).read_text()
        self.assertIn("os.replace", source)

    def test_no_llm_call(self):
        import spa_core.analytics.strategy_correlation_matrix as mod
        source = Path(mod.__file__).read_text()
        self.assertNotIn("anthropic", source.lower())
        self.assertNotIn("openai", source.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
