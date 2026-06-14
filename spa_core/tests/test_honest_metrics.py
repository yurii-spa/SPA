#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.honest_metrics (MP-138).

Coverage
--------
compute_sortino   — 14 tests
compute_sharpe    — 12 tests
bootstrap_ci      —  9 tests
confidence_label  —  9 tests
evaluate_strategy — 15 tests
run_honest_metrics—  7 tests

Total ≥ 66 tests.  Pure stdlib unittest — no pytest dependency.
Run with:
    python3 -m pytest spa_core/tests/test_honest_metrics.py -v
  or:
    python3 -m unittest spa_core.tests.test_honest_metrics -v
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from spa_core.paper_trading.honest_metrics import (
    bootstrap_ci,
    compute_sharpe,
    compute_sortino,
    confidence_label,
    evaluate_strategy,
    run_honest_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_equity(n_days: int, start: float = 100_000.0, daily_gain: float = 13.0) -> List[float]:
    """Monotonically rising equity: n_days+1 equity values → n_days returns."""
    eq = [start]
    for _ in range(n_days):
        eq.append(eq[-1] + daily_gain)
    return eq


def _make_volatile_equity(n: int, seed: int = 0) -> List[float]:
    """Equity with both gains and losses."""
    import random
    rng = random.Random(seed)
    eq = [100_000.0]
    for _ in range(n):
        change = rng.gauss(5, 100)
        eq.append(max(1.0, eq[-1] + change))
    return eq


def _write_shadow(data_dir: Path, history: list) -> None:
    """Write a minimal shadow_portfolio.json for testing."""
    payload = {
        "date": "2026-06-12",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "source": "shadow_runner",
        "advisory_only": True,
        "initial_capital": 100_000.0,
        "real_equity_usd": 100_000.0,
        "strategies": {},
        "history": history,
    }
    (data_dir / "shadow_portfolio.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _three_day_history() -> list:
    return [
        {"date": "2026-06-10", "S0": 100_013.54, "S1": 100_012.00},
        {"date": "2026-06-11", "S0": 100_026.49, "S1": 100_024.00},
        {"date": "2026-06-12", "S0": 100_039.51, "S1": 100_036.00},
    ]


def _sharpe_fn(r: List[float]) -> Optional[float]:
    return compute_sharpe(r)["sharpe"]


def _sortino_fn(r: List[float]) -> Optional[float]:
    return compute_sortino(r)["sortino"]


# ============================================================
# compute_sortino  (14 tests)
# ============================================================

class TestComputeSortino(unittest.TestCase):

    def test_empty_list_none(self):
        r = compute_sortino([])
        self.assertIsNone(r["sortino"])
        self.assertEqual(r["n"], 0)
        self.assertEqual(r["downside_returns"], 0)

    def test_single_element_none(self):
        r = compute_sortino([-0.01])
        self.assertIsNone(r["sortino"])
        self.assertEqual(r["n"], 1)

    def test_two_elements_none(self):
        r = compute_sortino([-0.01, -0.02])
        self.assertIsNone(r["sortino"])
        self.assertEqual(r["n"], 2)

    def test_all_zeros_no_downside_none(self):
        r = compute_sortino([0.0, 0.0, 0.0, 0.0])
        self.assertIsNone(r["sortino"])
        self.assertEqual(r["downside_returns"], 0)

    def test_all_positive_no_downside_none(self):
        r = compute_sortino([0.01, 0.02, 0.005, 0.001])
        self.assertIsNone(r["sortino"])
        self.assertEqual(r["downside_returns"], 0)

    def test_normal_data_finite_sortino(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r = compute_sortino(returns)
        self.assertIsNotNone(r["sortino"])
        self.assertTrue(math.isfinite(r["sortino"]))
        self.assertEqual(r["n"], 5)

    def test_downside_count_correct(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r = compute_sortino(returns)
        self.assertEqual(r["downside_returns"], 2)

    def test_all_negative_sortino_negative(self):
        returns = [-0.01, -0.02, -0.005]
        r = compute_sortino(returns)
        self.assertIsNotNone(r["sortino"])
        self.assertLess(r["sortino"], 0)

    def test_nonzero_target_increases_downside_count(self):
        returns = [0.001, 0.002, -0.001, 0.0005, -0.002]
        r_zero = compute_sortino(returns, target=0.0)
        r_nonzero = compute_sortino(returns, target=0.001)
        self.assertGreaterEqual(r_nonzero["downside_returns"], r_zero["downside_returns"])

    def test_annualize_false_ratio(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r_ann = compute_sortino(returns, annualize=True)
        r_raw = compute_sortino(returns, annualize=False)
        self.assertIsNotNone(r_ann["sortino"])
        self.assertIsNotNone(r_raw["sortino"])
        ratio = r_ann["sortino"] / r_raw["sortino"]
        self.assertAlmostEqual(ratio, math.sqrt(252), places=8)

    def test_formula_manual_verification(self):
        """Verify against hand-computed value (full-N denominator)."""
        returns = [0.02, -0.01, 0.01]
        n = 3
        dd = [-0.01]
        mean_sq = sum(d * d for d in dd) / n
        dd_dev = math.sqrt(mean_sq)
        mean_ret = sum(returns) / n
        expected = mean_ret / dd_dev * math.sqrt(252)
        r = compute_sortino(returns, annualize=True)
        self.assertAlmostEqual(r["sortino"], expected, places=9)

    def test_n_lt_3_always_none(self):
        r = compute_sortino([-0.01, 0.02])
        self.assertIsNone(r["sortino"])

    def test_dict_keys(self):
        r = compute_sortino([0.01, -0.005, 0.02])
        self.assertEqual(set(r.keys()), {"sortino", "n", "downside_returns"})

    def test_large_positive_high_sortino(self):
        returns = [0.01] * 50 + [-0.001] * 5
        r = compute_sortino(returns)
        self.assertIsNotNone(r["sortino"])
        self.assertGreater(r["sortino"], 5)


# ============================================================
# compute_sharpe  (12 tests)
# ============================================================

class TestComputeSharpe(unittest.TestCase):

    def test_empty_none(self):
        r = compute_sharpe([])
        self.assertIsNone(r["sharpe"])
        self.assertEqual(r["n"], 0)

    def test_single_none(self):
        r = compute_sharpe([0.01])
        self.assertIsNone(r["sharpe"])

    def test_two_none(self):
        r = compute_sharpe([0.01, 0.02])
        self.assertIsNone(r["sharpe"])

    def test_all_equal_std_zero_none(self):
        r = compute_sharpe([0.01, 0.01, 0.01, 0.01])
        self.assertIsNone(r["sharpe"])

    def test_normal_data_finite(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r = compute_sharpe(returns)
        self.assertIsNotNone(r["sharpe"])
        self.assertTrue(math.isfinite(r["sharpe"]))

    def test_n_correct(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r = compute_sharpe(returns)
        self.assertEqual(r["n"], 5)

    def test_higher_rf_lower_sharpe(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r_zero = compute_sharpe(returns, risk_free_daily=0.0)
        r_rf = compute_sharpe(returns, risk_free_daily=0.001)
        self.assertLess(r_rf["sharpe"], r_zero["sharpe"])

    def test_annualize_ratio(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003]
        r_ann = compute_sharpe(returns, annualize=True)
        r_raw = compute_sharpe(returns, annualize=False)
        ratio = r_ann["sharpe"] / r_raw["sharpe"]
        self.assertAlmostEqual(ratio, math.sqrt(252), places=8)

    def test_formula_manual(self):
        import statistics as st
        returns = [0.01, -0.01, 0.02, -0.005, 0.003]
        expected = (st.mean(returns) / st.stdev(returns)) * math.sqrt(252)
        r = compute_sharpe(returns)
        self.assertAlmostEqual(r["sharpe"], expected, places=9)

    def test_all_negative_negative_sharpe(self):
        returns = [-0.01, -0.02, -0.005]
        r = compute_sharpe(returns)
        self.assertIsNotNone(r["sharpe"])
        self.assertLess(r["sharpe"], 0)

    def test_dict_keys(self):
        r = compute_sharpe([0.01, -0.005, 0.02])
        self.assertEqual(set(r.keys()), {"sharpe", "n"})

    def test_large_positive_high_sharpe(self):
        returns = [0.005] * 90 + [-0.001] * 10
        r = compute_sharpe(returns)
        self.assertIsNotNone(r["sharpe"])
        self.assertGreater(r["sharpe"], 3)


# ============================================================
# bootstrap_ci  (9 tests)
# ============================================================

class TestBootstrapCI(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(bootstrap_ci(_sharpe_fn, []))

    def test_seed_reproducibility(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002]
        r1 = bootstrap_ci(_sharpe_fn, returns, seed=42)
        r2 = bootstrap_ci(_sharpe_fn, returns, seed=42)
        self.assertEqual(r1, r2)

    def test_different_seeds_different_result(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002]
        r1 = bootstrap_ci(_sharpe_fn, returns, seed=42)
        r2 = bootstrap_ci(_sharpe_fn, returns, seed=99)
        self.assertNotEqual(r1, r2)

    def test_lower_lt_upper(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002, 0.015, -0.003]
        r = bootstrap_ci(_sharpe_fn, returns, seed=42)
        self.assertIsNotNone(r)
        self.assertLess(r["lower"], r["upper"])

    def test_metric_always_none_returns_none(self):
        def always_none(r):
            return None
        self.assertIsNone(bootstrap_ci(always_none, [0.01] * 10, seed=42))

    def test_returns_correct_keys(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002]
        r = bootstrap_ci(_sharpe_fn, returns, seed=42)
        self.assertIsNotNone(r)
        self.assertEqual(set(r.keys()), {"lower", "upper", "n_valid"})

    def test_n_valid_at_most_n_bootstrap(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002]
        r = bootstrap_ci(_sharpe_fn, returns, n_bootstrap=100, seed=42)
        self.assertIsNotNone(r)
        self.assertLessEqual(r["n_valid"], 100)

    def test_wider_ci_level_wider_interval(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, 0.007, -0.002, 0.015, -0.003]
        r95 = bootstrap_ci(_sharpe_fn, returns, ci_level=0.95, seed=42)
        r80 = bootstrap_ci(_sharpe_fn, returns, ci_level=0.80, seed=42)
        self.assertIsNotNone(r95)
        self.assertIsNotNone(r80)
        self.assertGreaterEqual(r95["upper"] - r95["lower"], r80["upper"] - r80["lower"])

    def test_sortino_bootstrap_works(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.003, -0.008, 0.007]
        r = bootstrap_ci(_sortino_fn, returns, seed=42)
        self.assertIsNotNone(r)
        self.assertLess(r["lower"], r["upper"])


# ============================================================
# confidence_label  (9 tests)
# ============================================================

class TestConfidenceLabel(unittest.TestCase):

    def test_zero_insufficient(self):
        self.assertEqual(confidence_label(0), "INSUFFICIENT")

    def test_one_insufficient(self):
        self.assertEqual(confidence_label(1), "INSUFFICIENT")

    def test_six_insufficient(self):
        self.assertEqual(confidence_label(6), "INSUFFICIENT")

    def test_seven_low_confidence(self):
        self.assertEqual(confidence_label(7), "LOW_CONFIDENCE")

    def test_twenty_nine_low_confidence(self):
        self.assertEqual(confidence_label(29), "LOW_CONFIDENCE")

    def test_thirty_moderate(self):
        self.assertEqual(confidence_label(30), "MODERATE")

    def test_eighty_nine_moderate(self):
        self.assertEqual(confidence_label(89), "MODERATE")

    def test_ninety_high(self):
        self.assertEqual(confidence_label(90), "HIGH")

    def test_365_high(self):
        self.assertEqual(confidence_label(365), "HIGH")


# ============================================================
# evaluate_strategy  (15 tests)
# ============================================================

class TestEvaluateStrategy(unittest.TestCase):

    def test_empty_list(self):
        s = evaluate_strategy([])
        self.assertEqual(s["n_days"], 0)
        self.assertIsNone(s["sharpe"])
        self.assertIsNone(s["sortino"])
        self.assertEqual(s["total_return_pct"], 0.0)
        self.assertEqual(s["confidence"], "INSUFFICIENT")

    def test_single_float_value(self):
        s = evaluate_strategy([100_000.0])
        self.assertEqual(s["n_days"], 0)
        self.assertIsNone(s["sharpe"])

    def test_two_equity_values_one_return(self):
        s = evaluate_strategy([100_000.0, 100_013.0])
        self.assertEqual(s["n_days"], 1)
        self.assertEqual(s["confidence"], "INSUFFICIENT")
        self.assertIsNone(s["sharpe"])

    def test_dict_input_format(self):
        history = [
            {"date": "2026-06-10", "equity": 100_000.0},
            {"date": "2026-06-11", "equity": 100_013.0},
            {"date": "2026-06-12", "equity": 100_026.0},
            {"date": "2026-06-13", "equity": 100_010.0},
            {"date": "2026-06-14", "equity": 100_030.0},
        ]
        s = evaluate_strategy(history)
        self.assertEqual(s["n_days"], 4)

    def test_float_input_format(self):
        equities = [100_000.0, 100_013.0, 100_026.0, 100_010.0, 100_030.0]
        s = evaluate_strategy(equities)
        self.assertEqual(s["n_days"], 4)

    def test_7_days_low_confidence_with_warning(self):
        equities = _make_equity(7)
        s = evaluate_strategy(equities)
        self.assertEqual(s["confidence"], "LOW_CONFIDENCE")
        self.assertIsNotNone(s["warning"])

    def test_30_days_moderate_no_warning(self):
        equities = _make_volatile_equity(30)
        s = evaluate_strategy(equities)
        self.assertEqual(s["confidence"], "MODERATE")
        self.assertIsNone(s["warning"])

    def test_90_days_high_no_warning(self):
        equities = _make_volatile_equity(90)
        s = evaluate_strategy(equities)
        self.assertEqual(s["confidence"], "HIGH")
        self.assertIsNone(s["warning"])

    def test_total_return_pct_correct(self):
        equities = [100_000.0, 101_000.0]
        s = evaluate_strategy(equities)
        self.assertAlmostEqual(s["total_return_pct"], 1.0, places=6)

    def test_max_drawdown_zero_monotone_rise(self):
        equities = _make_equity(20)
        s = evaluate_strategy(equities)
        self.assertAlmostEqual(s["max_drawdown_pct"], 0.0, places=6)

    def test_max_drawdown_nonzero_volatile(self):
        equities = [100_000.0, 105_000.0, 95_000.0, 98_000.0]
        s = evaluate_strategy(equities)
        expected_dd = (105_000.0 - 95_000.0) / 105_000.0 * 100.0
        self.assertAlmostEqual(s["max_drawdown_pct"], expected_dd, places=6)

    def test_annualized_return_none_lt_30(self):
        equities = _make_equity(10)
        s = evaluate_strategy(equities)
        self.assertIsNone(s["annualized_return_pct"])

    def test_annualized_return_present_ge_30(self):
        equities = _make_equity(30)
        s = evaluate_strategy(equities)
        self.assertIsNotNone(s["annualized_return_pct"])

    def test_calmar_none_when_no_drawdown(self):
        equities = _make_equity(30)
        s = evaluate_strategy(equities)
        self.assertIsNone(s["calmar"])  # drawdown=0 → cannot compute

    def test_scorecard_keys_complete(self):
        equities = _make_volatile_equity(30)
        s = evaluate_strategy(equities)
        expected_keys = {
            "n_days", "confidence", "sharpe", "sortino", "calmar",
            "max_drawdown_pct", "total_return_pct", "annualized_return_pct",
            "sharpe_ci_95", "sortino_ci_95", "warning",
        }
        self.assertEqual(set(s.keys()), expected_keys)


# ============================================================
# run_honest_metrics  (7 tests)
# ============================================================

class TestRunHonestMetrics(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_file_returns_error(self):
        result = run_honest_metrics(self.data_dir)
        self.assertIn("error", result)
        self.assertEqual(result["strategies"], {})

    def test_valid_history_scores_all_strategies(self):
        _write_shadow(self.data_dir, _three_day_history())
        result = run_honest_metrics(self.data_dir)
        self.assertNotIn("error", result)
        self.assertIn("S0", result["strategies"])
        self.assertIn("S1", result["strategies"])

    def test_output_file_created(self):
        _write_shadow(self.data_dir, _three_day_history())
        run_honest_metrics(self.data_dir)
        self.assertTrue((self.data_dir / "honest_metrics.json").exists())

    def test_output_file_valid_json(self):
        _write_shadow(self.data_dir, _three_day_history())
        run_honest_metrics(self.data_dir)
        data = json.loads((self.data_dir / "honest_metrics.json").read_text())
        self.assertIn("strategies", data)
        self.assertTrue(data["advisory_only"])

    def test_n_strategies_count(self):
        _write_shadow(self.data_dir, _three_day_history())
        result = run_honest_metrics(self.data_dir)
        self.assertEqual(result["n_strategies"], 2)

    def test_custom_output_path(self):
        _write_shadow(self.data_dir, _three_day_history())
        custom_out = self.data_dir / "custom_out.json"
        run_honest_metrics(self.data_dir, output_path=custom_out)
        self.assertTrue(custom_out.exists())

    def test_corrupt_json_returns_error(self):
        (self.data_dir / "shadow_portfolio.json").write_text("{bad json{{", encoding="utf-8")
        result = run_honest_metrics(self.data_dir)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
