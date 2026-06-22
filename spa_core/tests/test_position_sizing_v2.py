"""Tests for spa_core.paper_trading.position_sizing_v2 (MP-133).

Covers:
- invert_matrix: 1×1, 2×2, 3×3 known inverses; singular raises ValueError; 4×4
- compute_kelly_weights: positive mu → positive weight, cap enforcement,
  normalization, all-negative mu fallback, single protocol, empty
- compute_mv_weights: weights sum to 1, min/max clipping, singular fallback,
  single protocol, equal-signal tie
- compare_weights: flagging at threshold, no flags, verdict strings, explanation
- run_optimizer: end-to-end with 2 and 3 protocols
- _compute_cov_matrix: symmetry, diagonal = variance
- _normalize_weights: basic normalization, all-zero fallback
- _apply_cap_and_renormalize: cap enforcement
- AST lint: no external (non-stdlib) imports
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

# Ensure the repo root is on sys.path so we can import spa_core
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.position_sizing_v2 import (
    _apply_cap_and_renormalize,
    _compute_cov_matrix,
    _normalize_weights,
    compare_weights,
    compute_kelly_weights,
    compute_mv_weights,
    invert_matrix,
    run_optimizer,
)

_SINGULAR_EPS = 1e-12
_TOL = 1e-9  # floating-point tolerance for matrix tests


def _is_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _matrices_close(A, B, tol=1e-6):
    n = len(A)
    for i in range(n):
        for j in range(n):
            if abs(A[i][j] - B[i][j]) > tol:
                return False
    return True


# ============================================================
# invert_matrix tests
# ============================================================

class TestInvertMatrix(unittest.TestCase):

    def test_1x1_trivial(self):
        result = invert_matrix([[4.0]])
        self.assertAlmostEqual(result[0][0], 0.25, places=10)

    def test_1x1_negative(self):
        result = invert_matrix([[-2.0]])
        self.assertAlmostEqual(result[0][0], -0.5, places=10)

    def test_2x2_identity(self):
        result = invert_matrix([[1.0, 0.0], [0.0, 1.0]])
        self.assertTrue(_matrices_close(result, [[1.0, 0.0], [0.0, 1.0]]))

    def test_2x2_known(self):
        # [[1,2],[3,4]] → [[-2, 1],[1.5, -0.5]]
        A = [[1.0, 2.0], [3.0, 4.0]]
        inv = invert_matrix(A)
        expected = [[-2.0, 1.0], [1.5, -0.5]]
        self.assertTrue(_matrices_close(inv, expected, tol=1e-9))

    def test_2x2_round_trip(self):
        A = [[2.0, 1.0], [5.0, 3.0]]
        inv = invert_matrix(A)
        # A @ inv = I
        n = 2
        for i in range(n):
            for j in range(n):
                val = sum(A[i][k] * inv[k][j] for k in range(n))
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(val, expected, places=10)

    def test_3x3_identity(self):
        I3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = invert_matrix(I3)
        self.assertTrue(_matrices_close(result, I3))

    def test_3x3_known(self):
        # A simple 3×3 with known inverse
        A = [[1.0, 2.0, 0.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]]
        inv = invert_matrix(A)
        n = 3
        for i in range(n):
            for j in range(n):
                val = sum(A[i][k] * inv[k][j] for k in range(n))
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(val, expected, places=10,
                    msg=f"A@inv[{i}][{j}] = {val} != {expected}")

    def test_3x3_round_trip_random(self):
        A = [[4.0, 7.0, 2.0], [3.0, 1.0, 5.0], [0.0, 6.0, 9.0]]
        inv = invert_matrix(A)
        n = 3
        for i in range(n):
            for j in range(n):
                val = sum(A[i][k] * inv[k][j] for k in range(n))
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(val, expected, places=8)

    def test_singular_2x2_raises(self):
        # Rows are linearly dependent
        with self.assertRaises(ValueError):
            invert_matrix([[1.0, 2.0], [2.0, 4.0]])

    def test_singular_3x3_raises(self):
        # All-zero matrix
        with self.assertRaises(ValueError):
            invert_matrix([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])

    def test_singular_nearly_zero_pivot(self):
        with self.assertRaises(ValueError):
            invert_matrix([[0.0, 1.0], [0.0, 2.0]])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            invert_matrix([])

    def test_non_square_raises(self):
        with self.assertRaises(ValueError):
            invert_matrix([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

    def test_4x4_round_trip(self):
        # Diagonally dominant 4×4 — guaranteed non-singular
        A = [
            [10.0,  1.0,  2.0,  3.0],
            [ 1.0, 10.0,  0.0,  1.0],
            [ 2.0,  0.0, 10.0,  2.0],
            [ 3.0,  1.0,  2.0, 10.0],
        ]
        inv = invert_matrix(A)
        n = 4
        for i in range(n):
            for j in range(n):
                val = sum(A[i][k] * inv[k][j] for k in range(n))
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(val, expected, places=8)


# ============================================================
# compute_kelly_weights tests
# ============================================================

class TestComputeKellyWeights(unittest.TestCase):

    def _make_returns(self, mu: float, n: int = 30, noise: float = 0.0001):
        """Construct a synthetic return series with given mean."""
        # Alternating pattern to get controlled variance
        rets = []
        for i in range(n):
            rets.append(mu + noise * (1 if i % 2 == 0 else -1))
        return rets

    def test_empty_returns_gives_empty(self):
        result = compute_kelly_weights({})
        self.assertEqual(result, {})

    def test_single_protocol_weight_is_one(self):
        rets = self._make_returns(0.001)
        result = compute_kelly_weights({"aave": rets})
        self.assertAlmostEqual(result["aave"], 1.0, places=6)

    def test_positive_mu_gives_positive_weight(self):
        rets = self._make_returns(0.002)
        result = compute_kelly_weights({"aave": rets, "comp": self._make_returns(0.001)})
        self.assertGreater(result["aave"], 0.0)
        self.assertGreater(result["comp"], 0.0)

    def test_weights_sum_to_one(self):
        returns = {
            "aave": self._make_returns(0.002),
            "comp": self._make_returns(0.001),
            "morpho": self._make_returns(0.0015),
        }
        result = compute_kelly_weights(returns)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=6)

    def test_cap_enforced(self):
        # Give one protocol a very high return to ensure it hits the cap.
        # Use 4 protocols so cap=0.25 is feasible (4 × 0.25 = 1.0).
        returns = {
            "aave":   self._make_returns(0.01),    # very high mu → high Kelly
            "comp":   self._make_returns(0.0001),
            "morpho": self._make_returns(0.0001),
            "euler":  self._make_returns(0.0001),
        }
        result = compute_kelly_weights(returns, cap=0.25)
        for w in result.values():
            self.assertLessEqual(w, 0.25 + 1e-9)

    def test_cap_0p5_relaxed(self):
        returns = {
            "aave": self._make_returns(0.01),
            "comp": self._make_returns(0.0001),
        }
        result = compute_kelly_weights(returns, cap=0.50)
        for w in result.values():
            self.assertLessEqual(w, 0.50 + 1e-9)

    def test_all_negative_mu_falls_back_to_equal(self):
        # If all returns are below rf, Kelly fractions all become 0
        rf_daily = 0.04 / 252.0
        returns = {
            "a": [rf_daily * 0.1] * 30,  # well below rf
            "b": [rf_daily * 0.05] * 30,
        }
        result = compute_kelly_weights(returns, risk_free_rate=0.04)
        self.assertAlmostEqual(result["a"], 0.5, places=6)
        self.assertAlmostEqual(result["b"], 0.5, places=6)

    def test_zero_variance_gets_zero_fraction(self):
        # All identical returns → variance = 0 → Kelly fraction = 0
        # Other protocol dominates
        returns = {
            "flat": [0.001] * 30,    # constant → variance=0 → Kelly=0
            "noisy": self._make_returns(0.001),  # has variance
        }
        result = compute_kelly_weights(returns)
        # flat should have zero weight (or very small after equal-weight fallback)
        # Because flat has 0 variance, it gets Kelly=0; the other dominates
        self.assertGreater(result["noisy"], result["flat"] - 1e-6)

    def test_empty_returns_list_for_protocol(self):
        returns = {
            "good": self._make_returns(0.001),
            "empty": [],
        }
        result = compute_kelly_weights(returns)
        self.assertIn("good", result)
        self.assertIn("empty", result)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=6)

    def test_single_observation_no_crash(self):
        returns = {"a": [0.001], "b": [0.002]}
        result = compute_kelly_weights(returns)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=6)

    def test_higher_mu_gets_higher_weight(self):
        """Higher excess return should yield higher Kelly weight, all else equal.

        Use a relaxed cap (0.80) so the 2-protocol constraint cap ≥ 0.50 is not
        binding and the dominant protocol can actually receive more weight.
        """
        noise = 0.0002
        returns = {
            "low":  [0.0005 + noise * (1 if i % 2 == 0 else -1) for i in range(60)],
            "high": [0.003  + noise * (1 if i % 2 == 0 else -1) for i in range(60)],
        }
        result = compute_kelly_weights(returns, cap=0.80)
        self.assertGreater(result["high"], result["low"])


# ============================================================
# compute_mv_weights tests
# ============================================================

class TestComputeMVWeights(unittest.TestCase):

    def _make_returns(self, mu: float, n: int = 50, noise: float = 0.0002):
        return [mu + noise * (1 if i % 2 == 0 else -1) for i in range(n)]

    def test_empty_returns_gives_empty(self):
        result = compute_mv_weights({})
        self.assertEqual(result, {})

    def test_single_protocol(self):
        result = compute_mv_weights({"aave": self._make_returns(0.001)})
        self.assertAlmostEqual(result["aave"], 1.0, places=6)

    def test_weights_sum_to_one(self):
        returns = {
            "aave": self._make_returns(0.002),
            "comp": self._make_returns(0.0015),
            "morpho": self._make_returns(0.001),
        }
        result = compute_mv_weights(returns)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=5)

    def test_min_weight_enforced(self):
        returns = {
            "aave": self._make_returns(0.003),
            "comp": self._make_returns(0.0001),
        }
        result = compute_mv_weights(returns, min_weight=0.05)
        for w in result.values():
            self.assertGreaterEqual(w, 0.05 - 1e-9)

    def test_max_weight_enforced(self):
        returns = {
            "aave": self._make_returns(0.01),
            "comp": self._make_returns(0.0001),
            "morpho": self._make_returns(0.00005),
        }
        result = compute_mv_weights(returns, max_weight=0.40)
        for w in result.values():
            self.assertLessEqual(w, 0.40 + 1e-9)

    def test_singular_covariance_falls_back_to_equal(self):
        # Identical return series → singular covariance matrix
        rets = [0.001] * 50
        returns = {"a": rets[:], "b": rets[:], "c": rets[:]}
        result = compute_mv_weights(returns)
        # Should not raise; should return (approximately) equal weights
        self.assertAlmostEqual(sum(result.values()), 1.0, places=5)
        for w in result.values():
            self.assertGreater(w, 0.0)

    def test_two_protocols_weights_sum(self):
        returns = {
            "a": self._make_returns(0.002, noise=0.0003),
            "b": self._make_returns(0.001, noise=0.0001),
        }
        result = compute_mv_weights(returns)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=5)

    def test_all_weights_nonneg_by_default(self):
        returns = {
            "a": self._make_returns(0.002),
            "b": self._make_returns(0.0005),
            "c": self._make_returns(0.0001),
        }
        result = compute_mv_weights(returns, min_weight=0.0)
        for w in result.values():
            self.assertGreaterEqual(w, -1e-9)

    def test_result_contains_all_protocols(self):
        protocols = ["aave", "comp", "euler"]
        returns = {p: self._make_returns(0.001 * (i + 1)) for i, p in enumerate(protocols)}
        result = compute_mv_weights(returns)
        for p in protocols:
            self.assertIn(p, result)

    def test_no_numpy_pandas_in_output(self):
        """Weights must be plain Python floats."""
        returns = {
            "a": self._make_returns(0.002),
            "b": self._make_returns(0.001),
        }
        result = compute_mv_weights(returns)
        for v in result.values():
            self.assertIsInstance(v, float)


# ============================================================
# compare_weights tests
# ============================================================

class TestCompareWeights(unittest.TestCase):

    def test_optimal_verdict_when_close(self):
        current = {"a": 0.5, "b": 0.5}
        kelly = {"a": 0.5, "b": 0.5}
        mv = {"a": 0.5, "b": 0.5}
        result = compare_weights(current, kelly, mv, threshold_pp=20.0)
        self.assertEqual(result["verdict"], "OPTIMAL")
        self.assertFalse(result["any_flagged"])

    def test_rebalance_verdict_when_large_deviation(self):
        current = {"a": 0.8, "b": 0.2}
        kelly = {"a": 0.5, "b": 0.5}
        mv = {"a": 0.5, "b": 0.5}
        result = compare_weights(current, kelly, mv, threshold_pp=20.0)
        self.assertEqual(result["verdict"], "REBALANCE_RECOMMENDED")
        self.assertTrue(result["any_flagged"])

    def test_flagging_at_exact_threshold(self):
        # deviation exactly at threshold → NOT flagged (> not >=)
        current = {"a": 0.70, "b": 0.30}
        kelly = {"a": 0.50, "b": 0.50}
        mv = {"a": 0.50, "b": 0.50}
        # deviation = 20 pp → threshold_pp = 20 → NOT flagged (20 > 20 is False)
        result = compare_weights(current, kelly, mv, threshold_pp=20.0)
        self.assertFalse(result["deviations"][0]["flagged"])

    def test_flagging_just_above_threshold(self):
        current = {"a": 0.701, "b": 0.299}
        kelly = {"a": 0.500, "b": 0.500}
        mv = {"a": 0.500, "b": 0.500}
        result = compare_weights(current, kelly, mv, threshold_pp=20.0)
        self.assertTrue(result["deviations"][0]["flagged"])

    def test_deviations_list_structure(self):
        current = {"a": 0.6, "b": 0.4}
        kelly = {"a": 0.5, "b": 0.5}
        mv = {"a": 0.5, "b": 0.5}
        result = compare_weights(current, kelly, mv)
        self.assertIn("deviations", result)
        for d in result["deviations"]:
            self.assertIn("protocol", d)
            self.assertIn("current_pct", d)
            self.assertIn("kelly_pct", d)
            self.assertIn("mv_pct", d)
            self.assertIn("max_deviation_pp", d)
            self.assertIn("flagged", d)

    def test_explanation_text_present(self):
        current = {"a": 0.5, "b": 0.5}
        kelly = {"a": 0.5, "b": 0.5}
        mv = {"a": 0.5, "b": 0.5}
        result = compare_weights(current, kelly, mv)
        self.assertIn("explanation", result)
        self.assertIsInstance(result["explanation"], str)
        self.assertGreater(len(result["explanation"]), 10)

    def test_protocols_in_kelly_but_not_current(self):
        current = {"a": 1.0}
        kelly = {"a": 0.7, "b": 0.3}
        mv = {"a": 0.6, "b": 0.4}
        result = compare_weights(current, kelly, mv, threshold_pp=10.0)
        protocols_in_result = {d["protocol"] for d in result["deviations"]}
        self.assertIn("a", protocols_in_result)
        self.assertIn("b", protocols_in_result)

    def test_max_deviation_is_max_of_kelly_and_mv(self):
        current = {"a": 0.8, "b": 0.2}
        kelly = {"a": 0.6, "b": 0.4}   # deviation 20 pp
        mv = {"a": 0.5, "b": 0.5}       # deviation 30 pp
        result = compare_weights(current, kelly, mv, threshold_pp=25.0)
        dev_a = next(d for d in result["deviations"] if d["protocol"] == "a")
        self.assertAlmostEqual(dev_a["max_deviation_pp"], 30.0, places=3)

    def test_verdict_strings_valid(self):
        for curr in [{"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.1}]:
            kelly = {"a": 0.5, "b": 0.5}
            mv = {"a": 0.5, "b": 0.5}
            result = compare_weights(curr, kelly, mv)
            self.assertIn(result["verdict"], {"OPTIMAL", "REBALANCE_RECOMMENDED"})

    def test_any_flagged_bool(self):
        current = {"a": 0.5, "b": 0.5}
        kelly = {"a": 0.5, "b": 0.5}
        mv = {"a": 0.5, "b": 0.5}
        result = compare_weights(current, kelly, mv)
        self.assertIsInstance(result["any_flagged"], bool)

    def test_rebalance_explanation_mentions_protocol(self):
        current = {"alpha": 0.95, "beta": 0.05}
        kelly = {"alpha": 0.5, "beta": 0.5}
        mv = {"alpha": 0.5, "beta": 0.5}
        result = compare_weights(current, kelly, mv, threshold_pp=10.0)
        self.assertIn("alpha", result["explanation"])

    def test_empty_weights(self):
        result = compare_weights({}, {}, {})
        self.assertFalse(result["any_flagged"])
        self.assertEqual(result["verdict"], "OPTIMAL")


# ============================================================
# run_optimizer end-to-end tests
# ============================================================

class TestRunOptimizer(unittest.TestCase):

    def _make_state(self, n: int = 3):
        protocols = ["aave_v3", "compound_v3", "morpho_blue"][:n]
        mus = [0.002, 0.0015, 0.001][:n]
        weights = [0.60, 0.25, 0.15][:n]
        state = {}
        for i, p in enumerate(protocols):
            noise = 0.0002
            rets = [mus[i] + noise * (1 if j % 2 == 0 else -1) for j in range(60)]
            state[p] = {"current_weight": weights[i], "daily_returns": rets}
        return state

    def test_e2e_three_protocols_returns_all_keys(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        self.assertIn("kelly", result)
        self.assertIn("mv", result)
        self.assertIn("comparison", result)

    def test_e2e_kelly_weights_sum_to_one(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        self.assertAlmostEqual(sum(result["kelly"].values()), 1.0, places=5)

    def test_e2e_mv_weights_sum_to_one(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        self.assertAlmostEqual(sum(result["mv"].values()), 1.0, places=5)

    def test_e2e_comparison_has_verdict(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        self.assertIn(result["comparison"]["verdict"], {"OPTIMAL", "REBALANCE_RECOMMENDED"})

    def test_e2e_two_protocols(self):
        state = self._make_state(2)
        result = run_optimizer(state)
        self.assertAlmostEqual(sum(result["kelly"].values()), 1.0, places=5)
        self.assertAlmostEqual(sum(result["mv"].values()), 1.0, places=5)

    def test_e2e_all_protocols_present_in_kelly(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        for p in state:
            self.assertIn(p, result["kelly"])

    def test_e2e_all_protocols_present_in_mv(self):
        state = self._make_state(3)
        result = run_optimizer(state)
        for p in state:
            self.assertIn(p, result["mv"])

    def test_e2e_no_crash_with_minimal_returns(self):
        """run_optimizer should not raise even with very short series."""
        state = {
            "a": {"current_weight": 0.5, "daily_returns": [0.001, 0.002]},
            "b": {"current_weight": 0.5, "daily_returns": [0.0005, 0.0008]},
        }
        result = run_optimizer(state)
        self.assertIn("kelly", result)
        self.assertIn("mv", result)

    def test_e2e_empty_daily_returns(self):
        state = {
            "a": {"current_weight": 0.5, "daily_returns": []},
            "b": {"current_weight": 0.5, "daily_returns": []},
        }
        result = run_optimizer(state)
        self.assertAlmostEqual(sum(result["kelly"].values()), 1.0, places=5)


# ============================================================
# _compute_cov_matrix tests
# ============================================================

class TestComputeCovMatrix(unittest.TestCase):

    def test_symmetric(self):
        a = [0.001 * i for i in range(20)]
        b = [0.002 * i for i in range(20)]
        cov = _compute_cov_matrix([a, b])
        self.assertAlmostEqual(cov[0][1], cov[1][0], places=12)

    def test_diagonal_equals_variance(self):
        rets = [0.001, 0.003, 0.002, 0.004, 0.002]
        cov = _compute_cov_matrix([rets])
        mean = sum(rets) / len(rets)
        expected_var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        self.assertAlmostEqual(cov[0][0], expected_var, places=12)

    def test_2x2_shape(self):
        a = [0.001] * 10
        b = [0.002] * 10
        cov = _compute_cov_matrix([a, b])
        self.assertEqual(len(cov), 2)
        self.assertEqual(len(cov[0]), 2)

    def test_identical_series_singular(self):
        rets = [0.001 * i for i in range(30)]
        cov = _compute_cov_matrix([rets, rets])
        # cov[0][0] == cov[1][1] == cov[0][1] == cov[1][0]
        self.assertAlmostEqual(cov[0][0], cov[0][1], places=12)


# ============================================================
# _normalize_weights tests
# ============================================================

class TestNormalizeWeights(unittest.TestCase):

    def test_basic_normalization(self):
        w = {"a": 2.0, "b": 3.0, "c": 5.0}
        result = _normalize_weights(w)
        self.assertAlmostEqual(result["a"], 0.2, places=12)
        self.assertAlmostEqual(result["b"], 0.3, places=12)
        self.assertAlmostEqual(result["c"], 0.5, places=12)

    def test_already_normalized(self):
        w = {"a": 0.4, "b": 0.6}
        result = _normalize_weights(w)
        self.assertAlmostEqual(result["a"], 0.4, places=12)

    def test_all_zero_gives_equal(self):
        w = {"a": 0.0, "b": 0.0, "c": 0.0}
        result = _normalize_weights(w)
        for v in result.values():
            self.assertAlmostEqual(v, 1.0 / 3, places=10)

    def test_empty_dict(self):
        result = _normalize_weights({})
        self.assertEqual(result, {})

    def test_sum_is_one(self):
        w = {"a": 3.14, "b": 2.72, "c": 1.41}
        result = _normalize_weights(w)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=12)


# ============================================================
# _apply_cap_and_renormalize tests
# ============================================================

class TestApplyCapAndRenormalize(unittest.TestCase):

    def test_no_cap_needed(self):
        w = {"a": 0.2, "b": 0.3, "c": 0.5}
        result = _apply_cap_and_renormalize(w, cap=0.6)
        for k, v in w.items():
            self.assertAlmostEqual(result[k], v, places=10)

    def test_cap_applied(self):
        # 4 protocols so cap=0.25 is feasible (4 × 0.25 = 1.0)
        w = {"a": 0.7, "b": 0.1, "c": 0.1, "d": 0.1}
        result = _apply_cap_and_renormalize(w, cap=0.25)
        self.assertLessEqual(result["a"], 0.25 + 1e-9)

    def test_cap_all_protocols(self):
        w = {"a": 0.6, "b": 0.4}
        result = _apply_cap_and_renormalize(w, cap=0.5)
        for v in result.values():
            self.assertLessEqual(v, 0.50 + 1e-9)


# ============================================================
# AST lint: no external imports
# ============================================================

class TestASTLint(unittest.TestCase):

    # Stdlib module names (non-exhaustive but covers common ones)
    _STDLIB_NAMES = {
        "abc", "argparse", "ast", "asyncio", "base64", "builtins", "calendar",
        "collections", "contextlib", "copy", "csv", "datetime", "decimal",
        "enum", "errno", "fnmatch", "fractions", "functools", "glob", "gzip",
        "hashlib", "heapq", "html", "http", "importlib", "inspect", "io",
        "itertools", "json", "logging", "math", "mimetypes", "operator", "os",
        "pathlib", "pickle", "platform", "pprint", "queue", "random", "re",
        "shutil", "signal", "socket", "sqlite3", "statistics", "string",
        "struct", "subprocess", "sys", "tempfile", "textwrap", "threading",
        "time", "timeit", "tkinter", "traceback", "typing", "unicodedata",
        "unittest", "urllib", "uuid", "warnings", "weakref", "xml", "zipfile",
        "__future__",
    }

    _MODULE_PATH = Path(__file__).resolve().parent.parent / "paper_trading" / "position_sizing_v2.py"

    def test_module_file_exists(self):
        self.assertTrue(
            self._MODULE_PATH.exists(),
            f"Module not found at {self._MODULE_PATH}"
        )

    def test_no_external_imports(self):
        source = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(self._MODULE_PATH))

        bad_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in self._STDLIB_NAMES:
                        bad_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in self._STDLIB_NAMES and top != "spa_core":
                        bad_imports.append(node.module)

        self.assertEqual(
            bad_imports,
            [],
            f"Non-stdlib/spa_core imports found: {bad_imports}",
        )

    def test_no_numpy_reference(self):
        source = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import np", source)
        self.assertNotIn("from numpy", source)

    def test_no_scipy_reference(self):
        source = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import scipy", source)
        self.assertNotIn("from scipy", source)

    def test_no_pandas_reference(self):
        source = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import pandas", source)
        self.assertNotIn("from pandas", source)

    def test_module_imports_only_stdlib(self):
        """All top-level imports are stdlib or internal spa_core."""
        source = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertIn(
                        top,
                        self._STDLIB_NAMES,
                        f"Found non-stdlib import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    top = node.module.split(".")[0]
                    self.assertIn(
                        top,
                        self._STDLIB_NAMES | {"spa_core"},
                        f"Found non-stdlib import: {node.module}"
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
