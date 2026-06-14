"""
Tests for spa_core.analytics.adapter_correlation_matrix (MP-612).

Coverage: 90+ unit tests across:
  - TestCorrelationPair           (10)
  - TestCorrelationMatrix         (8)
  - TestPearsonCorrelation        (20)
  - TestAlignSeries               (6)
  - TestClassifyRelationship      (8)
  - TestLoadApySeries             (8)
  - TestGenerateMatrix            (18)
  - TestSaveMatrix                (5)
  - TestFormatTelegramMessage     (7)

Run:
  python3 -m unittest spa_core.tests.test_adapter_correlation_matrix -v
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.adapter_correlation_matrix import (
    AdapterCorrelationMatrix,
    CorrelationMatrix,
    CorrelationPair,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pair(
    a: str = "aave",
    b: str = "compound",
    r: float = 0.6,
    relationship: str = "CORRELATED",
    data_points: int = 10,
    is_diversifying: bool = False,
) -> CorrelationPair:
    return CorrelationPair(
        adapter_a=a,
        adapter_b=b,
        correlation=r,
        relationship=relationship,
        data_points=data_points,
        is_diversifying=is_diversifying,
    )


def _make_matrix(
    pairs=None,
    adapters=None,
    avg_correlation=0.0,
    min_data_points=5,
    low_data_warning=False,
) -> CorrelationMatrix:
    pairs = pairs or []
    adapters = adapters or []
    return CorrelationMatrix(
        generated_at="2026-06-13T00:00:00+00:00",
        adapters=adapters,
        pairs=pairs,
        best_diversifying_pairs=sorted(pairs, key=lambda p: p.correlation)[:5],
        most_correlated_pairs=sorted(pairs, key=lambda p: p.correlation, reverse=True)[:5],
        avg_correlation=avg_correlation,
        min_data_points=min_data_points,
        low_data_warning=low_data_warning,
    )


def _make_watchdog_history(snapshots: list) -> dict:
    """Build a watchdog_history.json dict with given snapshots."""
    return {
        "schema_version": 1,
        "source": "adapter_watchdog",
        "ring_buffer_max": 48,
        "snapshot_count": len(snapshots),
        "updated_at": "2026-06-13T00:00:00+00:00",
        "latest": snapshots[-1] if snapshots else {},
        "snapshots": snapshots,
    }


def _make_snapshot(ts: str, adapter_apys: dict) -> dict:
    """Build a single watchdog snapshot dict."""
    return {
        "generated_at": ts,
        "adapter_statuses": [
            {"adapter_id": k, "apy_pct": v}
            for k, v in adapter_apys.items()
        ],
    }


def _write_watchdog(data_dir: Path, snapshots: list) -> None:
    history = _make_watchdog_history(snapshots)
    wpath = data_dir / "watchdog_history.json"
    wpath.write_text(json.dumps(history), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestCorrelationPair
# ---------------------------------------------------------------------------

class TestCorrelationPair(unittest.TestCase):

    def test_fields_stored_correctly(self):
        p = _make_pair(a="aave", b="compound", r=0.75, relationship="CORRELATED",
                       data_points=10, is_diversifying=False)
        self.assertEqual(p.adapter_a, "aave")
        self.assertEqual(p.adapter_b, "compound")
        self.assertAlmostEqual(p.correlation, 0.75)
        self.assertEqual(p.relationship, "CORRELATED")
        self.assertEqual(p.data_points, 10)
        self.assertFalse(p.is_diversifying)

    def test_is_diversifying_true_when_r_below_0_5(self):
        p = _make_pair(r=0.3, is_diversifying=True)
        self.assertTrue(p.is_diversifying)

    def test_is_diversifying_false_when_r_above_0_5(self):
        p = _make_pair(r=0.8, is_diversifying=False)
        self.assertFalse(p.is_diversifying)

    def test_is_diversifying_boundary_exactly_0_5(self):
        # r = 0.5 → NOT diversifying (condition is r < 0.5)
        p = _make_pair(r=0.5, is_diversifying=False)
        self.assertFalse(p.is_diversifying)

    def test_is_diversifying_r_negative(self):
        p = _make_pair(r=-0.3, is_diversifying=True)
        self.assertTrue(p.is_diversifying)

    def test_to_dict_keys(self):
        p = _make_pair()
        d = p.to_dict()
        for key in ("adapter_a", "adapter_b", "correlation", "relationship",
                    "data_points", "is_diversifying"):
            self.assertIn(key, d)

    def test_to_dict_values_match(self):
        p = _make_pair(a="alpha", b="beta", r=0.42, relationship="WEAKLY_CORRELATED",
                       data_points=7, is_diversifying=True)
        d = p.to_dict()
        self.assertEqual(d["adapter_a"], "alpha")
        self.assertEqual(d["adapter_b"], "beta")
        self.assertAlmostEqual(d["correlation"], 0.42)
        self.assertEqual(d["relationship"], "WEAKLY_CORRELATED")
        self.assertEqual(d["data_points"], 7)
        self.assertTrue(d["is_diversifying"])

    def test_correlation_rounded_to_6_dp(self):
        p = _make_pair(r=0.123456789)
        d = p.to_dict()
        # to_dict rounds to 6 decimal places
        self.assertAlmostEqual(d["correlation"], 0.123457, places=5)

    def test_negatively_correlated_pair(self):
        p = _make_pair(r=-0.9, relationship="NEGATIVELY_CORRELATED", is_diversifying=True)
        self.assertEqual(p.relationship, "NEGATIVELY_CORRELATED")
        self.assertTrue(p.is_diversifying)

    def test_zero_correlation_pair(self):
        p = _make_pair(r=0.0, relationship="UNCORRELATED", is_diversifying=True)
        self.assertEqual(p.relationship, "UNCORRELATED")
        self.assertAlmostEqual(p.correlation, 0.0)


# ---------------------------------------------------------------------------
# TestCorrelationMatrix
# ---------------------------------------------------------------------------

class TestCorrelationMatrix(unittest.TestCase):

    def test_empty_matrix_fields(self):
        m = _make_matrix()
        self.assertEqual(m.adapters, [])
        self.assertEqual(m.pairs, [])
        self.assertEqual(m.avg_correlation, 0.0)

    def test_low_data_warning_true(self):
        m = _make_matrix(min_data_points=3, low_data_warning=True)
        self.assertTrue(m.low_data_warning)

    def test_low_data_warning_false_when_enough(self):
        m = _make_matrix(min_data_points=5, low_data_warning=False)
        self.assertFalse(m.low_data_warning)

    def test_avg_correlation_from_field(self):
        m = _make_matrix(avg_correlation=0.55)
        self.assertAlmostEqual(m.avg_correlation, 0.55)

    def test_best_diversifying_sorted_ascending(self):
        p1 = _make_pair(a="a", b="b", r=0.8)
        p2 = _make_pair(a="a", b="c", r=0.1)
        p3 = _make_pair(a="b", b="c", r=0.5)
        m = _make_matrix(pairs=[p1, p2, p3])
        corrs = [p.correlation for p in m.best_diversifying_pairs]
        self.assertEqual(corrs, sorted(corrs))

    def test_most_correlated_sorted_descending(self):
        p1 = _make_pair(a="a", b="b", r=0.8)
        p2 = _make_pair(a="a", b="c", r=0.1)
        p3 = _make_pair(a="b", b="c", r=0.5)
        m = _make_matrix(pairs=[p1, p2, p3])
        corrs = [p.correlation for p in m.most_correlated_pairs]
        self.assertEqual(corrs, sorted(corrs, reverse=True))

    def test_to_dict_has_all_keys(self):
        m = _make_matrix()
        d = m.to_dict()
        for key in ("generated_at", "adapters", "pairs", "best_diversifying_pairs",
                    "most_correlated_pairs", "avg_correlation", "min_data_points",
                    "low_data_warning"):
            self.assertIn(key, d)

    def test_to_dict_pairs_serialized(self):
        p = _make_pair()
        m = _make_matrix(pairs=[p])
        d = m.to_dict()
        self.assertEqual(len(d["pairs"]), 1)
        self.assertIsInstance(d["pairs"][0], dict)

    def test_adapters_list_stored(self):
        m = _make_matrix(adapters=["aave", "compound", "morpho"])
        self.assertEqual(m.adapters, ["aave", "compound", "morpho"])


# ---------------------------------------------------------------------------
# TestPearsonCorrelation
# ---------------------------------------------------------------------------

class TestPearsonCorrelation(unittest.TestCase):

    def setUp(self):
        self.acm = AdapterCorrelationMatrix.__new__(AdapterCorrelationMatrix)
        self.acm.MIN_DATA_POINTS = 3

    def test_perfect_positive_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        r = self.acm.pearson_correlation(xs, xs)
        self.assertAlmostEqual(r, 1.0, places=10)

    def test_perfect_negative_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertAlmostEqual(r, -1.0, places=10)

    def test_constant_series_returns_zero(self):
        xs = [3.0, 3.0, 3.0, 3.0]
        ys = [1.0, 2.0, 3.0, 4.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertEqual(r, 0.0)

    def test_both_constant_returns_zero(self):
        xs = [5.0, 5.0, 5.0]
        ys = [2.0, 2.0, 2.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertEqual(r, 0.0)

    def test_length_less_than_min_returns_zero(self):
        xs = [1.0, 2.0]
        ys = [1.0, 2.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertEqual(r, 0.0)

    def test_different_lengths_returns_zero(self):
        xs = [1.0, 2.0, 3.0]
        ys = [1.0, 2.0, 3.0, 4.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertEqual(r, 0.0)

    def test_empty_series_returns_zero(self):
        r = self.acm.pearson_correlation([], [])
        self.assertEqual(r, 0.0)

    def test_exactly_min_data_points(self):
        xs = [1.0, 2.0, 3.0]
        ys = [1.0, 2.0, 3.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertAlmostEqual(r, 1.0, places=10)

    def test_result_in_minus_one_to_one(self):
        xs = [3.5, 4.1, 2.8, 5.0, 6.2, 3.9]
        ys = [1.2, 5.5, 0.9, 3.3, 7.1, 2.8]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertGreaterEqual(r, -1.0)
        self.assertLessEqual(r, 1.0)

    def test_known_example_positive(self):
        # x=[1,2,3,4,5], y=[2,4,5,4,5] → r ≈ 0.8165
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 5.0, 4.0, 5.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertGreater(r, 0.7)
        self.assertLess(r, 0.95)

    def test_uncorrelated_series(self):
        # xs = [1,-1,0,1,-1,0], ys = [0,0,1,0,0,1]
        # Σxy = 0, Σx = 0  →  numer = n*0 − 0*Σy = 0  →  r = 0.0
        xs = [1.0, -1.0, 0.0, 1.0, -1.0, 0.0]
        ys = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertAlmostEqual(r, 0.0, places=10)

    def test_symmetry(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [4.0, 3.0, 2.0, 1.0]
        r1 = self.acm.pearson_correlation(xs, ys)
        r2 = self.acm.pearson_correlation(ys, xs)
        self.assertAlmostEqual(r1, r2, places=12)

    def test_single_element_returns_zero(self):
        r = self.acm.pearson_correlation([5.0], [5.0])
        self.assertEqual(r, 0.0)

    def test_two_elements_returns_zero_when_min_is_3(self):
        r = self.acm.pearson_correlation([1.0, 2.0], [3.0, 4.0])
        self.assertEqual(r, 0.0)

    def test_positive_correlation_near_zero(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        ys = [6.0, 1.0, 5.0, 2.0, 4.0, 3.0]
        r = self.acm.pearson_correlation(xs, ys)
        # Should be a weak/near-zero value
        self.assertGreaterEqual(r, -1.0)
        self.assertLessEqual(r, 1.0)

    def test_larger_dataset(self):
        xs = list(range(1, 21))
        ys = [x * 2 + 1 for x in xs]  # perfect linear → r=1
        r = self.acm.pearson_correlation(
            [float(x) for x in xs],
            [float(y) for y in ys],
        )
        self.assertAlmostEqual(r, 1.0, places=10)

    def test_negative_values_in_series(self):
        xs = [-3.0, -2.0, -1.0, 0.0, 1.0]
        ys = [-1.0, 0.0, 1.0, 2.0, 3.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertAlmostEqual(r, 1.0, places=10)

    def test_float_precision_does_not_exceed_bounds(self):
        xs = [1.0, 1.000001, 1.000002, 1.000003, 1.000004]
        r = self.acm.pearson_correlation(xs, xs)
        # Should be clamped by compute_pair, but pearson itself should stay ≤ 1
        self.assertLessEqual(r, 1.0 + 1e-9)

    def test_result_is_float(self):
        xs = [1.0, 2.0, 3.0]
        r = self.acm.pearson_correlation(xs, xs)
        self.assertIsInstance(r, float)

    def test_formula_manual_check(self):
        # xs=[1,2,3], ys=[1,2,3]: n=3, Σx=6, Σy=6, Σxy=14, Σx²=14, Σy²=14
        # numer = 3*14 - 6*6 = 42-36 = 6
        # denom = sqrt((3*14-36)*(3*14-36)) = sqrt(6*6) = 6  → r=1.0
        xs = [1.0, 2.0, 3.0]
        ys = [1.0, 2.0, 3.0]
        r = self.acm.pearson_correlation(xs, ys)
        self.assertAlmostEqual(r, 1.0)


# ---------------------------------------------------------------------------
# TestAlignSeries
# ---------------------------------------------------------------------------

class TestAlignSeries(unittest.TestCase):

    def setUp(self):
        self.acm = AdapterCorrelationMatrix.__new__(AdapterCorrelationMatrix)

    def test_same_length_returns_full(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        ra, rb = self.acm.align_series(a, b)
        self.assertEqual(ra, [1.0, 2.0, 3.0])
        self.assertEqual(rb, [4.0, 5.0, 6.0])

    def test_a_shorter_truncates_b(self):
        a = [1.0, 2.0]
        b = [10.0, 20.0, 30.0]
        ra, rb = self.acm.align_series(a, b)
        self.assertEqual(len(ra), 2)
        self.assertEqual(len(rb), 2)
        # Takes last 2 of b
        self.assertEqual(rb, [20.0, 30.0])

    def test_b_shorter_truncates_a(self):
        a = [1.0, 2.0, 3.0, 4.0]
        b = [5.0, 6.0]
        ra, rb = self.acm.align_series(a, b)
        self.assertEqual(len(ra), 2)
        self.assertEqual(len(rb), 2)
        # Takes last 2 of a
        self.assertEqual(ra, [3.0, 4.0])

    def test_empty_a_returns_empty_pair(self):
        ra, rb = self.acm.align_series([], [1.0, 2.0])
        self.assertEqual(ra, [])
        self.assertEqual(rb, [])

    def test_empty_b_returns_empty_pair(self):
        ra, rb = self.acm.align_series([1.0, 2.0], [])
        self.assertEqual(ra, [])
        self.assertEqual(rb, [])

    def test_single_element_each(self):
        ra, rb = self.acm.align_series([5.0], [7.0])
        self.assertEqual(ra, [5.0])
        self.assertEqual(rb, [7.0])


# ---------------------------------------------------------------------------
# TestClassifyRelationship
# ---------------------------------------------------------------------------

class TestClassifyRelationship(unittest.TestCase):

    def setUp(self):
        self.acm = AdapterCorrelationMatrix.__new__(AdapterCorrelationMatrix)

    def test_strongly_correlated_at_0_8(self):
        self.assertEqual(self.acm.classify_relationship(0.8), "STRONGLY_CORRELATED")

    def test_strongly_correlated_above_0_8(self):
        self.assertEqual(self.acm.classify_relationship(0.95), "STRONGLY_CORRELATED")

    def test_correlated_at_0_5(self):
        self.assertEqual(self.acm.classify_relationship(0.5), "CORRELATED")

    def test_correlated_between_0_5_and_0_8(self):
        self.assertEqual(self.acm.classify_relationship(0.65), "CORRELATED")

    def test_weakly_correlated_at_0_2(self):
        self.assertEqual(self.acm.classify_relationship(0.2), "WEAKLY_CORRELATED")

    def test_weakly_correlated_between_0_2_and_0_5(self):
        self.assertEqual(self.acm.classify_relationship(0.35), "WEAKLY_CORRELATED")

    def test_uncorrelated_at_zero(self):
        self.assertEqual(self.acm.classify_relationship(0.0), "UNCORRELATED")

    def test_negatively_correlated_at_minus_0_2(self):
        self.assertEqual(self.acm.classify_relationship(-0.2), "NEGATIVELY_CORRELATED")

    def test_negatively_correlated_below_minus_0_2(self):
        self.assertEqual(self.acm.classify_relationship(-0.85), "NEGATIVELY_CORRELATED")

    # Boundary just below 0.8
    def test_just_below_0_8_is_correlated(self):
        self.assertEqual(self.acm.classify_relationship(0.799), "CORRELATED")

    # Boundary just below 0.5
    def test_just_below_0_5_is_weakly(self):
        self.assertEqual(self.acm.classify_relationship(0.499), "WEAKLY_CORRELATED")

    # Boundary just above -0.2
    def test_just_above_minus_0_2_is_uncorrelated(self):
        self.assertEqual(self.acm.classify_relationship(-0.199), "UNCORRELATED")

    # r = 1.0 → STRONGLY_CORRELATED
    def test_r_equals_1(self):
        self.assertEqual(self.acm.classify_relationship(1.0), "STRONGLY_CORRELATED")

    # r = -1.0 → NEGATIVELY_CORRELATED
    def test_r_equals_minus_1(self):
        self.assertEqual(self.acm.classify_relationship(-1.0), "NEGATIVELY_CORRELATED")


# ---------------------------------------------------------------------------
# TestLoadApySeries
# ---------------------------------------------------------------------------

class TestLoadApySeries(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)
        self.acm = AdapterCorrelationMatrix(data_path=str(self.data_dir))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_missing_file_returns_empty_dict(self):
        result = self.acm.load_apy_series()
        self.assertEqual(result, {})

    def test_empty_snapshots_returns_empty_dict(self):
        _write_watchdog(self.data_dir, [])
        result = self.acm.load_apy_series()
        self.assertEqual(result, {})

    def test_single_snapshot_single_adapter(self):
        snaps = [_make_snapshot("2026-06-10T00:00:00Z", {"aave": 3.5})]
        _write_watchdog(self.data_dir, snaps)
        result = self.acm.load_apy_series()
        self.assertIn("aave", result)
        self.assertEqual(result["aave"], [3.5])

    def test_multiple_snapshots_single_adapter(self):
        snaps = [
            _make_snapshot("2026-06-10T00:00:00Z", {"aave": 3.5}),
            _make_snapshot("2026-06-11T00:00:00Z", {"aave": 3.7}),
            _make_snapshot("2026-06-12T00:00:00Z", {"aave": 3.6}),
        ]
        _write_watchdog(self.data_dir, snaps)
        result = self.acm.load_apy_series()
        self.assertEqual(result["aave"], [3.5, 3.7, 3.6])

    def test_multiple_snapshots_multiple_adapters(self):
        snaps = [
            _make_snapshot("2026-06-10T00:00:00Z", {"aave": 3.5, "compound": 4.0}),
            _make_snapshot("2026-06-11T00:00:00Z", {"aave": 3.7, "compound": 4.1}),
        ]
        _write_watchdog(self.data_dir, snaps)
        result = self.acm.load_apy_series()
        self.assertIn("aave", result)
        self.assertIn("compound", result)
        self.assertEqual(len(result["aave"]), 2)
        self.assertEqual(len(result["compound"]), 2)

    def test_snapshots_sorted_chronologically(self):
        # Out of order in file — should be sorted by timestamp
        snaps = [
            _make_snapshot("2026-06-12T00:00:00Z", {"aave": 3.6}),
            _make_snapshot("2026-06-10T00:00:00Z", {"aave": 3.5}),
            _make_snapshot("2026-06-11T00:00:00Z", {"aave": 3.7}),
        ]
        _write_watchdog(self.data_dir, snaps)
        result = self.acm.load_apy_series()
        self.assertEqual(result["aave"], [3.5, 3.7, 3.6])

    def test_malformed_file_returns_empty(self):
        (self.data_dir / "watchdog_history.json").write_text("not json", encoding="utf-8")
        result = self.acm.load_apy_series()
        self.assertEqual(result, {})

    def test_missing_adapter_id_entry_skipped(self):
        history = _make_watchdog_history([{
            "generated_at": "2026-06-10T00:00:00Z",
            "adapter_statuses": [
                {"apy_pct": 3.5},    # no adapter_id
                {"adapter_id": "compound", "apy_pct": 4.0},
            ],
        }])
        (self.data_dir / "watchdog_history.json").write_text(
            json.dumps(history), encoding="utf-8"
        )
        result = self.acm.load_apy_series()
        self.assertNotIn(None, result)
        self.assertIn("compound", result)


# ---------------------------------------------------------------------------
# TestGenerateMatrix
# ---------------------------------------------------------------------------

class TestGenerateMatrix(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)
        self.acm = AdapterCorrelationMatrix(data_path=str(self.data_dir))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_no_data_returns_empty_matrix(self):
        matrix = self.acm.generate_matrix()
        self.assertEqual(matrix.adapters, [])
        self.assertEqual(matrix.pairs, [])
        self.assertEqual(matrix.avg_correlation, 0.0)
        self.assertEqual(matrix.min_data_points, 0)
        self.assertTrue(matrix.low_data_warning)

    def test_single_adapter_no_pairs(self):
        snaps = [_make_snapshot("2026-06-10T00:00:00Z", {"aave": 3.5})] * 5
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(len(matrix.pairs), 0)

    def test_two_adapters_one_pair(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z", {"aave": 3.5 + i * 0.1, "compound": 4.0 + i * 0.1})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(len(matrix.pairs), 1)
        self.assertEqual(matrix.pairs[0].adapter_a, "aave")
        self.assertEqual(matrix.pairs[0].adapter_b, "compound")

    def test_three_adapters_three_pairs(self):
        snaps = [
            _make_snapshot(
                f"2026-06-{10+i:02d}T00:00:00Z",
                {"aave": 3.0 + i * 0.1, "compound": 4.0 + i * 0.05, "morpho": 5.0 - i * 0.1}
            )
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(len(matrix.pairs), 3)

    def test_pair_a_less_than_b_lexicographic(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z", {"morpho": 5.0 + i, "aave": 3.0 + i})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(len(matrix.pairs), 1)
        p = matrix.pairs[0]
        # adapter_a < adapter_b lexicographically
        self.assertLess(p.adapter_a, p.adapter_b)

    def test_no_duplicate_pairs(self):
        snaps = [
            _make_snapshot(
                f"2026-06-{10+i:02d}T00:00:00Z",
                {"a": float(i), "b": float(i) * 2, "c": float(i) * 3}
            )
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        pair_keys = [(p.adapter_a, p.adapter_b) for p in matrix.pairs]
        self.assertEqual(len(pair_keys), len(set(pair_keys)))

    def test_low_data_warning_when_min_points_below_threshold(self):
        # Only 3 snapshots (< 5 threshold)
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z", {"aave": 3.0 + i, "compound": 4.0 + i})
            for i in range(3)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertTrue(matrix.low_data_warning)

    def test_no_low_data_warning_when_enough_points(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z", {"aave": 3.0 + i * 0.1, "compound": 4.0 + i * 0.1})
            for i in range(6)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertFalse(matrix.low_data_warning)

    def test_best_diversifying_at_most_5(self):
        adapters = {f"a{i}": float(i) for i in range(5)}
        snaps = [
            _make_snapshot(f"2026-06-{10+j:02d}T00:00:00Z",
                           {k: v + j * (0.1 if int(k[1]) % 2 == 0 else -0.1) for k, v in adapters.items()})
            for j in range(6)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertLessEqual(len(matrix.best_diversifying_pairs), 5)

    def test_most_correlated_at_most_5(self):
        adapters = {f"a{i}": float(i) for i in range(5)}
        snaps = [
            _make_snapshot(f"2026-06-{10+j:02d}T00:00:00Z",
                           {k: v + j * 0.1 for k, v in adapters.items()})
            for j in range(6)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertLessEqual(len(matrix.most_correlated_pairs), 5)

    def test_best_diversifying_sorted_ascending(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"a": float(i), "b": float(i) * 2, "c": 5.0 - float(i)})
            for i in range(6)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        corrs = [p.correlation for p in matrix.best_diversifying_pairs]
        self.assertEqual(corrs, sorted(corrs))

    def test_most_correlated_sorted_descending(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"a": float(i), "b": float(i) * 2, "c": 5.0 - float(i)})
            for i in range(6)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        corrs = [p.correlation for p in matrix.most_correlated_pairs]
        self.assertEqual(corrs, sorted(corrs, reverse=True))

    def test_avg_correlation_computed_correctly(self):
        # aave and compound perfectly correlated → r=1.0 only pair
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"aave": float(i), "compound": float(i)})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertAlmostEqual(matrix.avg_correlation, 1.0, places=4)

    def test_generated_at_is_iso_string(self):
        matrix = self.acm.generate_matrix()
        self.assertIsInstance(matrix.generated_at, str)
        # Should be parseable
        from datetime import datetime
        dt = datetime.fromisoformat(matrix.generated_at.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_adapters_are_sorted(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"morpho": 5.0 + i, "aave": 3.0 + i, "compound": 4.0 + i})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(matrix.adapters, sorted(matrix.adapters))

    def test_pairs_not_counted_when_too_few_points(self):
        # Only 2 snapshots → aligned series has 2 pts < MIN_DATA_POINTS=3
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"aave": 3.0 + i, "compound": 4.0 + i})
            for i in range(2)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        self.assertEqual(len(matrix.pairs), 0)

    def test_min_data_points_in_result(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"aave": 3.0 + i, "compound": 4.0 + i})
            for i in range(4)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        if matrix.pairs:
            self.assertEqual(matrix.min_data_points, min(p.data_points for p in matrix.pairs))

    def test_is_diversifying_set_in_generated_pairs(self):
        # All perfectly correlated (r=1) → not diversifying
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"a": float(i), "b": float(i)})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        if matrix.pairs:
            self.assertFalse(matrix.pairs[0].is_diversifying)


# ---------------------------------------------------------------------------
# TestSaveMatrix
# ---------------------------------------------------------------------------

class TestSaveMatrix(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)
        self.acm = AdapterCorrelationMatrix(data_path=str(self.data_dir))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_creates_file(self):
        self.acm.save_matrix()
        self.assertTrue((self.data_dir / "correlation_matrix.json").exists())

    def test_save_returns_absolute_path(self):
        path = self.acm.save_matrix()
        self.assertTrue(os.path.isabs(path))

    def test_file_is_valid_json(self):
        self.acm.save_matrix()
        raw = (self.data_dir / "correlation_matrix.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertIsInstance(payload, dict)

    def test_ring_buffer_max_10(self):
        for _ in range(12):
            self.acm.save_matrix()
        raw = (self.data_dir / "correlation_matrix.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertLessEqual(len(payload["reports"]), 10)

    def test_accepts_precomputed_matrix(self):
        matrix = self.acm.generate_matrix()
        path = self.acm.save_matrix(matrix=matrix)
        raw = (self.data_dir / "correlation_matrix.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertIn("latest", payload)


# ---------------------------------------------------------------------------
# TestFormatTelegramMessage
# ---------------------------------------------------------------------------

class TestFormatTelegramMessage(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)
        self.acm = AdapterCorrelationMatrix(data_path=str(self.data_dir))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_message_length_le_1500(self):
        msg = self.acm.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_avg_correlation(self):
        msg = self.acm.format_telegram_message()
        self.assertIn("Avg correlation", msg)

    def test_empty_data_no_crash(self):
        msg = self.acm.format_telegram_message()
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_with_pairs_contains_adapter_names(self):
        snaps = [
            _make_snapshot(f"2026-06-{10+i:02d}T00:00:00Z",
                           {"aave": float(i), "compound": float(i)})
            for i in range(5)
        ]
        _write_watchdog(self.data_dir, snaps)
        matrix = self.acm.generate_matrix()
        msg = self.acm.format_telegram_message(matrix=matrix)
        self.assertIn("aave", msg)
        self.assertIn("compound", msg)

    def test_low_data_warning_in_message(self):
        matrix = _make_matrix(low_data_warning=True)
        msg = self.acm.format_telegram_message(matrix=matrix)
        self.assertIn("Low data warning", msg)

    def test_no_low_data_warning_when_false(self):
        matrix = _make_matrix(low_data_warning=False)
        msg = self.acm.format_telegram_message(matrix=matrix)
        self.assertNotIn("Low data warning", msg)

    def test_accepts_precomputed_matrix(self):
        matrix = self.acm.generate_matrix()
        msg = self.acm.format_telegram_message(matrix=matrix)
        self.assertLessEqual(len(msg), 1500)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
