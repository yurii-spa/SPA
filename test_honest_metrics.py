"""
Unit tests for spa_core.analytics.honest_metrics (Sprint B / v3.91).

Stdlib unittest only — no network, no file I/O. The bootstrap CI tests seed
``random`` for determinism.
"""
from __future__ import annotations

import math
import random
import unittest

from spa_core.analytics.honest_metrics import (
    compute_sortino,
    compute_sharpe_with_ci,
    compute_calmar,
    min_sample_check,
    label_metric,
    _confidence,
)


class TestSortino(unittest.TestCase):
    def test_downside_only_returns_value(self):
        # Mixed returns with real downside -> a finite Sortino.
        returns = [0.02, -0.01, 0.03, -0.02, 0.01, 0.015]
        res = compute_sortino(returns)
        self.assertIsNotNone(res["value"])
        self.assertIsInstance(res["value"], float)
        self.assertEqual(res["n"], len(returns))

    def test_sortino_matches_manual_formula(self):
        returns = [0.10, -0.05, 0.20, -0.10, 0.05]
        downside = [r for r in returns if r < 0]
        mu_down = sum(downside) / len(downside)
        dd = math.sqrt(sum((r - mu_down) ** 2 for r in downside) / len(downside))
        expected = (sum(returns) / len(returns)) / dd
        res = compute_sortino(returns)
        self.assertAlmostEqual(res["value"], expected, places=9)

    def test_no_negative_returns_value_none(self):
        returns = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
        res = compute_sortino(returns)
        self.assertIsNone(res["value"])
        self.assertNotEqual(res["confidence"], "insufficient_data")

    def test_insufficient_data_below_min_periods(self):
        res = compute_sortino([0.01, -0.01])  # n=2 < 5
        self.assertIsNone(res["value"])
        self.assertEqual(res["confidence"], "insufficient_data")
        self.assertEqual(res["n"], 2)

    def test_single_negative_point_no_spread(self):
        # exactly one negative -> downside std is 0 -> value None
        res = compute_sortino([0.01, 0.02, -0.03, 0.04, 0.05])
        self.assertIsNone(res["value"])

    def test_rf_shifts_value_down(self):
        returns = [0.05, -0.02, 0.04, -0.03, 0.06, 0.01]
        base = compute_sortino(returns, rf=0.0)["value"]
        with_rf = compute_sortino(returns, rf=0.02)["value"]
        self.assertLess(with_rf, base)


class TestSharpeWithCI(unittest.TestCase):
    def test_low_sample_warning_flag(self):
        returns = [0.01, -0.01, 0.02, -0.02, 0.015, 0.005, 0.0, -0.005, 0.012, 0.008]
        res = compute_sharpe_with_ci(returns)  # n=10 < 30
        self.assertTrue(res.get("low_sample_warning"))

    def test_below_bootstrap_min_value_none(self):
        res = compute_sharpe_with_ci([0.01, -0.01, 0.02])  # n=3 < 10
        self.assertIsNone(res["value"])
        self.assertIsNone(res["ci_lower"])
        self.assertIsNone(res["ci_upper"])
        self.assertTrue(res.get("low_sample_warning"))

    def test_ci_brackets_point_estimate(self):
        random.seed(123)
        # Clean positive-drift series with noise -> CI should straddle the point.
        returns = [0.01 + 0.005 * math.sin(i) for i in range(40)]
        res = compute_sharpe_with_ci(returns)
        self.assertIsNotNone(res["value"])
        self.assertIsNotNone(res["ci_lower"])
        self.assertIsNotNone(res["ci_upper"])
        self.assertLess(res["ci_lower"], res["value"])
        self.assertLess(res["value"], res["ci_upper"])

    def test_large_sample_no_warning_high_confidence(self):
        random.seed(7)
        returns = [0.01 if i % 2 == 0 else -0.005 for i in range(50)]
        res = compute_sharpe_with_ci(returns)
        self.assertNotIn("low_sample_warning", res)
        self.assertEqual(res["confidence"], "high")
        self.assertEqual(res["n"], 50)

    def test_ci_lower_below_upper(self):
        random.seed(99)
        returns = [0.02, -0.01, 0.03, -0.02, 0.01, 0.04, -0.03, 0.02, 0.01, -0.01, 0.05, 0.0]
        res = compute_sharpe_with_ci(returns)
        self.assertLessEqual(res["ci_lower"], res["ci_upper"])


class TestCalmar(unittest.TestCase):
    def test_zero_drawdown_returns_none(self):
        # Monotonically rising equity -> no drawdown -> value None
        curve = [{"equity": 100_000 + i * 100} for i in range(10)]
        res = compute_calmar(curve, period_days=10)
        self.assertIsNone(res["value"])
        self.assertEqual(res["max_drawdown_pct"], 0.0)

    def test_positive_calmar_with_drawdown(self):
        curve = [
            {"equity": 100_000},
            {"equity": 105_000},
            {"equity": 102_000},  # drawdown here
            {"equity": 110_000},
        ]
        res = compute_calmar(curve, period_days=30)
        self.assertIsNotNone(res["value"])
        self.assertGreater(res["value"], 0)
        self.assertGreater(res["max_drawdown_pct"], 0)

    def test_accepts_raw_number_curve(self):
        res = compute_calmar([100.0, 110.0, 105.0, 120.0], period_days=20)
        self.assertIsNotNone(res["value"])

    def test_too_short_curve_none(self):
        res = compute_calmar([{"equity": 100_000}], period_days=10)
        self.assertIsNone(res["value"])

    def test_invalid_period_days_none(self):
        curve = [{"equity": 100}, {"equity": 90}, {"equity": 95}]
        res = compute_calmar(curve, period_days=0)
        self.assertIsNone(res["value"])


class TestConfidenceThresholds(unittest.TestCase):
    def test_low_below_15(self):
        self.assertEqual(_confidence(5), "low")
        self.assertEqual(_confidence(14), "low")

    def test_medium_15_to_30(self):
        self.assertEqual(_confidence(15), "medium")
        self.assertEqual(_confidence(30), "medium")

    def test_high_above_30(self):
        self.assertEqual(_confidence(31), "high")
        self.assertEqual(_confidence(100), "high")

    def test_sortino_confidence_label_propagates(self):
        returns = [0.02, -0.01] * 10  # n=20 -> medium
        res = compute_sortino(returns)
        self.assertEqual(res["confidence"], "medium")


class TestMinSampleCheck(unittest.TestCase):
    def test_warns_below_30(self):
        msg = min_sample_check(20, "Sharpe")
        self.assertIn("n=20", msg)
        self.assertIn("LOW CONFIDENCE", msg)

    def test_empty_at_or_above_30(self):
        self.assertEqual(min_sample_check(30, "Sharpe"), "")
        self.assertEqual(min_sample_check(45, "Sortino"), "")


class TestLabelMetric(unittest.TestCase):
    def test_high_confidence_checkmark(self):
        out = label_metric({"value": 1.23, "n": 40, "confidence": "high"}, "Sortino")
        self.assertEqual(out, "Sortino: 1.23 ✓")

    def test_low_confidence_warning_with_n(self):
        out = label_metric({"value": -5.38, "n": 20, "confidence": "medium"}, "Sharpe")
        self.assertIn("-5.38", out)
        self.assertIn("⚠", out)
        self.assertIn("LOW CONFIDENCE", out)
        self.assertIn("n=20", out)

    def test_none_value_na(self):
        out = label_metric({"value": None, "n": 3}, "Sortino")
        self.assertIn("N/A", out)

    def test_accepts_bare_float(self):
        out = label_metric(2.5, "Calmar")
        self.assertIn("2.50", out)
        self.assertIn("✓", out)

    def test_low_sample_warning_flag_triggers_warning(self):
        out = label_metric(
            {"value": 0.9, "n": 12, "confidence": "low", "low_sample_warning": True},
            "Sharpe",
        )
        self.assertIn("⚠", out)


if __name__ == "__main__":
    unittest.main()
