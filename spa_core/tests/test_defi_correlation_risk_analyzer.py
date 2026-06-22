"""
Tests for MP-835 DeFiCorrelationRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_correlation_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap so the module is importable from repo root
# ---------------------------------------------------------------------------
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_correlation_risk_analyzer import (
    _pearson,
    _position_risk_label,
    _portfolio_risk_label,
    _diversification_score,
    analyze,
    log_result,
    _atomic_write,
    _init_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(protocol="Proto", alloc=25.0, asset="USDC",
                   category="lending", returns=None):
    if returns is None:
        returns = [0.01, 0.02, -0.01, 0.03, 0.00] * 6
    return {
        "protocol": protocol,
        "allocation_pct": alloc,
        "underlying_asset": asset,
        "category": category,
        "returns_30d": returns,
    }


def _identical_returns(n=30, val=0.01):
    return [val] * n


def _alternating(n=30):
    return [0.01 if i % 2 == 0 else -0.01 for i in range(n)]


def _ramp(n=30, start=0.001):
    return [start * (i + 1) for i in range(n)]


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestPearson(unittest.TestCase):
    """25 tests for _pearson helper."""

    def test_identical_series_returns_1(self):
        a = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(_pearson(a, a), 1.0, places=6)

    def test_perfectly_anti_correlated(self):
        a = [1, 2, 3, 4, 5]
        b = [5, 4, 3, 2, 1]
        self.assertAlmostEqual(_pearson(a, b), -1.0, places=6)

    def test_zero_variance_a_returns_zero(self):
        a = [1, 1, 1, 1, 1]
        b = [1, 2, 3, 4, 5]
        self.assertEqual(_pearson(a, b), 0.0)

    def test_zero_variance_b_returns_zero(self):
        a = [1, 2, 3, 4, 5]
        b = [3, 3, 3, 3, 3]
        self.assertEqual(_pearson(a, b), 0.0)

    def test_both_zero_variance_returns_zero(self):
        a = [5, 5, 5]
        b = [5, 5, 5]
        self.assertEqual(_pearson(a, b), 0.0)

    def test_too_short_returns_zero(self):
        self.assertEqual(_pearson([0.01], [0.01]), 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(_pearson([], []), 0.0)

    def test_minimum_length_2(self):
        a = [1.0, 2.0]
        b = [1.0, 2.0]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=6)

    def test_result_clamped_to_minus_1(self):
        # floating-point edge — ensure clamp works
        a = [1.0, -1.0]
        b = [-1.0, 1.0]
        self.assertGreaterEqual(_pearson(a, b), -1.0)

    def test_result_clamped_to_plus_1(self):
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]
        self.assertLessEqual(_pearson(a, b), 1.0)

    def test_mismatched_lengths_uses_shorter(self):
        a = [1, 2, 3, 4, 5]
        b = [1, 2, 3]
        result = _pearson(a, b)
        expected = _pearson([1, 2, 3], [1, 2, 3])
        self.assertAlmostEqual(result, expected, places=6)

    def test_uncorrelated_near_zero(self):
        import random
        random.seed(42)
        a = [random.gauss(0, 1) for _ in range(100)]
        b = [random.gauss(0, 1) for _ in range(100)]
        result = _pearson(a, b)
        self.assertLess(abs(result), 0.4)  # not perfectly correlated

    def test_known_value(self):
        # hand-computed: a=[1,2,3], b=[1,3,2]
        # means: 2, 2; deviations: (-1,0,1),(-1,1,0)
        # num = 1 + 0 + 0 = 1; den_a=sqrt(2), den_b=sqrt(2) -> 1/2 = 0.5
        a = [1, 2, 3]
        b = [1, 3, 2]
        self.assertAlmostEqual(_pearson(a, b), 0.5, places=6)

    def test_negatives_in_series(self):
        a = [-1, -2, -3, -4]
        b = [-1, -2, -3, -4]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=6)

    def test_float_precision(self):
        a = [0.0001, 0.0002, 0.0003]
        b = [0.0001, 0.0002, 0.0003]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=5)

    def test_large_values(self):
        a = [1e6, 2e6, 3e6]
        b = [1e6, 2e6, 3e6]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=5)

    def test_opposite_alternating(self):
        a = _alternating(10)
        b = [-x for x in a]
        self.assertAlmostEqual(_pearson(a, b), -1.0, places=6)

    def test_single_element_returns_zero(self):
        self.assertEqual(_pearson([5.0], [5.0]), 0.0)

    def test_ramp_vs_ramp(self):
        a = _ramp(20)
        b = _ramp(20, start=0.002)
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=5)

    def test_ramp_vs_negative_ramp(self):
        a = _ramp(10)
        b = [-x for x in _ramp(10)]
        self.assertAlmostEqual(_pearson(a, b), -1.0, places=5)

    def test_returns_float(self):
        result = _pearson([1, 2, 3], [1, 2, 3])
        self.assertIsInstance(result, float)

    def test_three_elements_positive(self):
        a = [1, 2, 3]
        b = [4, 5, 6]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=6)

    def test_partial_correlation(self):
        a = [0, 1, 0, 1, 0]
        b = [1, 1, 0, 0, 0]
        result = _pearson(a, b)
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, -1.0)
        self.assertLessEqual(result, 1.0)

    def test_symmetry(self):
        a = [0.01, 0.03, -0.01, 0.02]
        b = [0.02, 0.01, 0.00, -0.01]
        self.assertAlmostEqual(_pearson(a, b), _pearson(b, a), places=10)

    def test_longer_b_uses_shorter_a(self):
        a = [1, 2]
        b = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(_pearson(a, b), 1.0, places=6)


class TestClassifiers(unittest.TestCase):
    """15 tests for label/score helper functions."""

    def test_critical_at_0_8(self):
        self.assertEqual(_position_risk_label(0.8), "CRITICAL")

    def test_critical_above_0_8(self):
        self.assertEqual(_position_risk_label(0.95), "CRITICAL")

    def test_high_at_0_6(self):
        self.assertEqual(_position_risk_label(0.6), "HIGH")

    def test_high_at_0_79(self):
        self.assertEqual(_position_risk_label(0.79), "HIGH")

    def test_medium_at_0_4(self):
        self.assertEqual(_position_risk_label(0.4), "MEDIUM")

    def test_medium_at_0_59(self):
        self.assertEqual(_position_risk_label(0.59), "MEDIUM")

    def test_low_below_0_4(self):
        self.assertEqual(_position_risk_label(0.3), "LOW")

    def test_low_at_zero(self):
        self.assertEqual(_position_risk_label(0.0), "LOW")

    def test_portfolio_well_diversified(self):
        self.assertEqual(_portfolio_risk_label(0.1), "WELL_DIVERSIFIED")

    def test_portfolio_moderate(self):
        self.assertEqual(_portfolio_risk_label(0.4), "MODERATE")

    def test_portfolio_concentrated(self):
        self.assertEqual(_portfolio_risk_label(0.6), "CONCENTRATED")

    def test_portfolio_highly_correlated(self):
        self.assertEqual(_portfolio_risk_label(0.7), "HIGHLY_CORRELATED")

    def test_diversification_score_zero_corr(self):
        self.assertEqual(_diversification_score(0.0), 100)

    def test_diversification_score_full_corr(self):
        self.assertEqual(_diversification_score(1.0), 0)

    def test_diversification_score_clamped(self):
        # corr > 1 should not go negative (guard)
        self.assertGreaterEqual(_diversification_score(1.5), 0)


class TestAnalyze(unittest.TestCase):
    """25 tests for the main analyze() function."""

    # ---- return structure ---------------------------------------------------

    def test_returns_dict(self):
        result = analyze([_make_position()])
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        result = analyze([_make_position()])
        for key in ("positions", "portfolio_metrics", "category_breakdown",
                    "asset_breakdown", "skipped_protocols", "timestamp"):
            self.assertIn(key, result)

    def test_portfolio_metrics_keys(self):
        result = analyze([_make_position()])
        pm = result["portfolio_metrics"]
        for key in ("avg_pairwise_correlation", "high_correlation_pairs",
                    "portfolio_diversification_score", "risk_label"):
            self.assertIn(key, pm)

    def test_position_result_keys(self):
        result = analyze([_make_position("A"), _make_position("B")])
        p = result["positions"][0]
        for key in ("protocol", "avg_correlation", "max_correlation",
                    "max_corr_partner", "correlation_risk"):
            self.assertIn(key, p)

    def test_timestamp_is_float(self):
        result = analyze([_make_position()])
        self.assertIsInstance(result["timestamp"], float)

    # ---- empty / edge cases -------------------------------------------------

    def test_empty_positions(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["portfolio_metrics"]["avg_pairwise_correlation"], 0.0)
        self.assertEqual(result["portfolio_metrics"]["portfolio_diversification_score"], 100)
        self.assertEqual(result["portfolio_metrics"]["risk_label"], "WELL_DIVERSIFIED")
        self.assertEqual(result["skipped_protocols"], [])

    def test_single_valid_position(self):
        result = analyze([_make_position("OnlyOne")])
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["portfolio_metrics"]["avg_pairwise_correlation"], 0.0)
        self.assertEqual(result["portfolio_metrics"]["portfolio_diversification_score"], 100)
        self.assertEqual(result["portfolio_metrics"]["risk_label"], "WELL_DIVERSIFIED")

    def test_all_skipped_positions(self):
        p1 = _make_position("A", returns=[0.01])  # too short
        result = analyze([p1])
        self.assertIn("A", result["skipped_protocols"])
        self.assertEqual(result["positions"], [])

    def test_skipped_goes_into_breakdown(self):
        p1 = _make_position("A", asset="ETH", category="staking", returns=[0.01])
        result = analyze([p1])
        self.assertIn("ETH", result["asset_breakdown"])
        self.assertIn("staking", result["category_breakdown"])

    def test_empty_returns_skipped(self):
        p = _make_position("X", returns=[])
        result = analyze([p])
        self.assertIn("X", result["skipped_protocols"])

    # ---- perfect correlation -------------------------------------------------

    def test_perfectly_correlated_two(self):
        r = [0.01, 0.02, 0.03, 0.01, 0.02] * 6
        p1 = _make_position("A", returns=r)
        p2 = _make_position("B", returns=r)
        result = analyze([p1, p2])
        pm = result["portfolio_metrics"]
        self.assertAlmostEqual(pm["avg_pairwise_correlation"], 1.0, places=4)
        self.assertEqual(pm["risk_label"], "HIGHLY_CORRELATED")

    def test_perfectly_correlated_flags_pair(self):
        r = [0.01, 0.02, 0.03, -0.01, 0.02] * 6
        p1 = _make_position("A", returns=r)
        p2 = _make_position("B", returns=r)
        result = analyze([p1, p2], config={"high_correlation_threshold": 0.7})
        pairs = result["portfolio_metrics"]["high_correlation_pairs"]
        self.assertTrue(len(pairs) > 0)

    # ---- diversification score ----------------------------------------------

    def test_score_between_0_and_100(self):
        positions = [_make_position(f"P{i}", returns=[0.01 * i] * 10 + [0.0] * 20)
                     for i in range(1, 4)]
        result = analyze(positions)
        score = result["portfolio_metrics"]["portfolio_diversification_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    # ---- anti-correlated positions ------------------------------------------

    def test_anticorrelated_positions(self):
        r = list(range(1, 31))
        neg_r = [-x for x in r]
        p1 = _make_position("Long", returns=[float(x) for x in r])
        p2 = _make_position("Short", returns=[float(x) for x in neg_r])
        result = analyze([p1, p2])
        pm = result["portfolio_metrics"]
        self.assertAlmostEqual(pm["avg_pairwise_correlation"], -1.0, places=4)
        self.assertEqual(pm["risk_label"], "WELL_DIVERSIFIED")
        self.assertEqual(pm["portfolio_diversification_score"], 100)

    # ---- high_correlation_pairs ordering ------------------------------------

    def test_high_corr_pairs_sorted_descending(self):
        r1 = [float(i) for i in range(1, 31)]
        r2 = [float(i) * 1.001 for i in range(1, 31)]
        r3 = [-float(i) for i in range(1, 31)]
        p1 = _make_position("A", returns=r1)
        p2 = _make_position("B", returns=r2)
        p3 = _make_position("C", returns=r3)
        result = analyze([p1, p2, p3], config={"high_correlation_threshold": 0.5})
        pairs = result["portfolio_metrics"]["high_correlation_pairs"]
        corrs = [p["correlation"] for p in pairs]
        self.assertEqual(corrs, sorted(corrs, reverse=True))

    def test_high_corr_threshold_custom(self):
        r = [float(i) for i in range(1, 31)]
        p1 = _make_position("A", returns=r)
        p2 = _make_position("B", returns=r)
        result = analyze([p1, p2], config={"high_correlation_threshold": 0.99})
        pairs = result["portfolio_metrics"]["high_correlation_pairs"]
        for pair in pairs:
            self.assertGreaterEqual(pair["correlation"], 0.99)

    # ---- per-position fields -------------------------------------------------

    def test_position_risk_label_present(self):
        r = [float(i) for i in range(30)]
        p1 = _make_position("A", returns=r)
        p2 = _make_position("B", returns=r)
        result = analyze([p1, p2])
        labels = {p["correlation_risk"] for p in result["positions"]}
        self.assertTrue(labels.issubset({"LOW", "MEDIUM", "HIGH", "CRITICAL"}))

    def test_max_corr_partner_names_other_protocol(self):
        r = [float(i) for i in range(30)]
        p1 = _make_position("Alpha", returns=r)
        p2 = _make_position("Beta", returns=r)
        result = analyze([p1, p2])
        for pos in result["positions"]:
            self.assertNotEqual(pos["protocol"], pos["max_corr_partner"])

    def test_avg_correlation_within_range(self):
        positions = [_make_position(f"P{i}") for i in range(3)]
        result = analyze(positions)
        for pos in result["positions"]:
            self.assertGreaterEqual(pos["avg_correlation"], -1.0)
            self.assertLessEqual(pos["avg_correlation"], 1.0)

    # ---- category / asset breakdowns ----------------------------------------

    def test_category_breakdown(self):
        p1 = _make_position("A", category="lending")
        p2 = _make_position("B", category="staking")
        p3 = _make_position("C", category="lending")
        result = analyze([p1, p2, p3])
        self.assertEqual(result["category_breakdown"]["lending"], 2)
        self.assertEqual(result["category_breakdown"]["staking"], 1)

    def test_asset_breakdown(self):
        p1 = _make_position("A", asset="USDC")
        p2 = _make_position("B", asset="ETH")
        result = analyze([p1, p2])
        self.assertEqual(result["asset_breakdown"]["USDC"], 1)
        self.assertEqual(result["asset_breakdown"]["ETH"], 1)

    # ---- config defaults ----------------------------------------------------

    def test_default_config_none(self):
        result = analyze([_make_position("A"), _make_position("B")])
        self.assertIn("risk_label", result["portfolio_metrics"])

    def test_custom_min_returns(self):
        # min_returns=3 → length-2 series is skipped
        p = _make_position("Short", returns=[0.01, 0.02])
        result = analyze([p], config={"min_returns": 3})
        self.assertIn("Short", result["skipped_protocols"])

    def test_min_returns_2_accepts_2(self):
        p = _make_position("TwoPoints", returns=[0.01, 0.02])
        result = analyze([p], config={"min_returns": 2})
        self.assertNotIn("TwoPoints", result["skipped_protocols"])

    # ---- three-way portfolio -------------------------------------------------

    def test_three_way_portfolio(self):
        r = [float(i) for i in range(30)]
        positions = [
            _make_position("A", returns=r),
            _make_position("B", returns=r),
            _make_position("C", returns=[-x for x in r]),
        ]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 3)
        self.assertIn("A", [p["protocol"] for p in result["positions"]])


class TestLogResult(unittest.TestCase):
    """10 tests for log_result and atomic write helpers."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmp_dir, "test_log.json")

    def test_log_creates_file(self):
        result = analyze([_make_position()])
        log_result(result, self._log_path)
        self.assertTrue(os.path.exists(self._log_path))

    def test_log_is_list(self):
        result = analyze([_make_position()])
        log_result(result, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entry(self):
        for _ in range(3):
            log_result(analyze([_make_position()]), self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_caps_at_100(self):
        for i in range(105):
            log_result({"i": i, "timestamp": float(i)}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_keeps_newest_entries(self):
        for i in range(105):
            log_result({"i": i, "timestamp": float(i)}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 5)
        self.assertEqual(data[-1]["i"], 104)

    def test_init_log_creates_empty_list(self):
        path = os.path.join(self._tmp_dir, "new_log.json")
        _init_log(path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_does_not_overwrite_existing(self):
        path = os.path.join(self._tmp_dir, "existing.json")
        _atomic_write(path, [{"existing": True}])
        _init_log(path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_atomic_write_produces_valid_json(self):
        path = os.path.join(self._tmp_dir, "atomic.json")
        _atomic_write(path, {"key": "value", "n": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")
        self.assertEqual(data["n"], 42)

    def test_log_result_full_result_stored(self):
        result = analyze([_make_position("TestProtocol")])
        log_result(result, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIn("positions", data[0])
        self.assertIn("portfolio_metrics", data[0])

    def test_log_handles_corrupt_file_gracefully(self):
        path = os.path.join(self._tmp_dir, "corrupt.json")
        with open(path, "w") as f:
            f.write("NOT JSON {{{")
        # Should not raise
        log_result({"x": 1}, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
