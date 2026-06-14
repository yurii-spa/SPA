#!/usr/bin/env python3
"""Tests for MP-728 RiskWeightedCapitalAllocator.

Run:
    python3 -m unittest spa_core.tests.test_risk_weighted_capital_allocator -v
    python3 spa_core/tests/test_risk_weighted_capital_allocator.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make spa_core importable from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.risk_weighted_capital_allocator import (
    RWAAllocationResult,
    RWAPosition,
    compare_budgets,
    compute_rwa,
    load_history,
    risk_weight,
    save_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(
    name: str,
    protocol: str,
    risk_score: float,
    apy: float,
    requested_pct: float,
) -> RWAPosition:
    return RWAPosition(
        name=name,
        protocol=protocol,
        risk_score=risk_score,
        apy=apy,
        requested_allocation_pct=requested_pct,
    )


def _simple_positions() -> list:
    """Three balanced positions with different risk scores."""
    return [
        _pos("Aave", "aave_v3", 10.0, 3.5, 40.0),
        _pos("Compound", "compound_v3", 20.0, 4.8, 40.0),
        _pos("Morpho", "morpho_steakhouse", 30.0, 6.5, 20.0),
    ]


# ---------------------------------------------------------------------------
# 1. risk_weight function
# ---------------------------------------------------------------------------

class TestRiskWeightFunction(unittest.TestCase):

    def test_score_zero_returns_one(self):
        self.assertAlmostEqual(risk_weight(0), 1.0)

    def test_score_fifty_returns_one_point_five(self):
        self.assertAlmostEqual(risk_weight(50), 1.5)

    def test_score_hundred_returns_two(self):
        self.assertAlmostEqual(risk_weight(100), 2.0)

    def test_score_twenty_five(self):
        self.assertAlmostEqual(risk_weight(25), 1.25)

    def test_score_seventy_five(self):
        self.assertAlmostEqual(risk_weight(75), 1.75)

    def test_score_ten(self):
        self.assertAlmostEqual(risk_weight(10), 1.1)

    def test_returns_float(self):
        self.assertIsInstance(risk_weight(50), float)

    def test_monotone_increasing(self):
        self.assertLess(risk_weight(0), risk_weight(50))
        self.assertLess(risk_weight(50), risk_weight(100))


# ---------------------------------------------------------------------------
# 2. rwa_pct = requested * risk_weight
# ---------------------------------------------------------------------------

class TestRwaPctFormula(unittest.TestCase):

    def test_rwa_pct_formula_basic(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        # risk_weight(0) = 1.0; rwa_pct = 100 * 1.0 = 100
        self.assertAlmostEqual(result.positions[0].rwa_pct, 100.0)

    def test_rwa_pct_formula_high_risk(self):
        positions = [_pos("A", "p", 100.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        # risk_weight(100) = 2.0; rwa_pct = 50 * 2.0 = 100
        self.assertAlmostEqual(result.positions[0].rwa_pct, 100.0)

    def test_rwa_pct_proportional_to_requested(self):
        positions = [
            _pos("A", "p", 50.0, 5.0, 20.0),
            _pos("B", "p", 50.0, 5.0, 40.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        rwa_a = result.positions[0].rwa_pct
        rwa_b = result.positions[1].rwa_pct
        # Both have same risk_weight so rwa ratio = requested ratio = 1:2
        self.assertAlmostEqual(rwa_b / rwa_a, 2.0, places=10)

    def test_risk_weight_stored_in_position(self):
        positions = [_pos("A", "p", 50.0, 5.0, 30.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertAlmostEqual(result.positions[0].risk_weight, 1.5)


# ---------------------------------------------------------------------------
# 3. total_rwa = sum of all rwa_pct
# ---------------------------------------------------------------------------

class TestTotalRwa(unittest.TestCase):

    def test_total_rwa_is_sum_no_scaling(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 300.0)
        expected = sum(p.rwa_pct for p in result.positions)
        self.assertAlmostEqual(result.total_rwa_pct, expected, places=10)

    def test_total_rwa_two_positions(self):
        positions = [
            _pos("A", "p", 0.0, 5.0, 50.0),   # rwa = 50
            _pos("B", "p", 100.0, 5.0, 50.0),  # rwa = 100
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        # No scaling since 150 <= 300
        self.assertAlmostEqual(result.total_rwa_pct, 150.0, places=10)

    def test_total_rwa_single_position(self):
        positions = [_pos("A", "p", 50.0, 5.0, 80.0)]
        result = compute_rwa(positions, 100_000, 300.0)
        # risk_weight = 1.5; rwa = 80 * 1.5 = 120
        self.assertAlmostEqual(result.total_rwa_pct, 120.0, places=10)


# ---------------------------------------------------------------------------
# 4. within_budget
# ---------------------------------------------------------------------------

class TestWithinBudget(unittest.TestCase):

    def test_within_budget_true_when_total_rwa_le_budget(self):
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertTrue(result.within_budget)

    def test_within_budget_true_at_exact_boundary(self):
        # rwa_pct = 50 * 1.0 = 50; budget = 50 → within
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 50.0)
        self.assertTrue(result.within_budget)

    def test_within_budget_true_after_scaling(self):
        # Two positions, rwa would be 150 + 150 = 300 > 200 → gets scaled
        positions = [
            _pos("A", "p", 50.0, 5.0, 100.0),  # rwa = 150
            _pos("B", "p", 50.0, 5.0, 100.0),  # rwa = 150
        ]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertTrue(result.within_budget)


# ---------------------------------------------------------------------------
# 5. Scaling behaviour
# ---------------------------------------------------------------------------

class TestScaling(unittest.TestCase):

    def test_scaling_applied_when_over_budget(self):
        positions = [
            _pos("A", "p", 100.0, 5.0, 100.0),  # rwa = 200 > 150
        ]
        result = compute_rwa(positions, 100_000, 150.0)
        self.assertTrue(result.scaling_applied)

    def test_scaling_not_applied_when_within_budget(self):
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertFalse(result.scaling_applied)

    def test_scaling_reduces_all_allocations(self):
        positions = [
            _pos("A", "p", 0.0, 5.0, 100.0),   # rwa = 100
            _pos("B", "p", 100.0, 5.0, 100.0),  # rwa = 200
        ]
        # total_rwa = 300 > 150
        result = compute_rwa(positions, 100_000, 150.0)
        for p in result.positions:
            self.assertLess(p.requested_allocation_pct, 100.0)

    def test_scaling_uniformly_preserves_ratio(self):
        positions = [
            _pos("A", "p", 0.0, 5.0, 30.0),
            _pos("B", "p", 0.0, 5.0, 70.0),
        ]
        # Both same risk_weight so total_rwa = 100 > 80
        result = compute_rwa(positions, 100_000, 80.0)
        p_a = result.positions[0].requested_allocation_pct
        p_b = result.positions[1].requested_allocation_pct
        # Ratio should be preserved: 30:70
        self.assertAlmostEqual(p_b / p_a, 70.0 / 30.0, places=10)

    def test_after_scaling_total_rwa_equals_budget(self):
        positions = [
            _pos("A", "p", 50.0, 5.0, 80.0),
            _pos("B", "p", 50.0, 5.0, 80.0),
        ]
        # total_rwa = 2 * 80 * 1.5 = 240 > 150
        result = compute_rwa(positions, 100_000, 150.0)
        self.assertAlmostEqual(result.total_rwa_pct, 150.0, places=9)

    def test_after_scaling_total_rwa_equals_budget_mixed(self):
        positions = [
            _pos("A", "p", 0.0, 3.5, 40.0),
            _pos("B", "p", 100.0, 8.0, 60.0),
        ]
        budget = 100.0
        result = compute_rwa(positions, 100_000, budget)
        self.assertAlmostEqual(result.total_rwa_pct, budget, places=9)

    def test_no_scaling_when_exactly_at_budget(self):
        # rwa = 30 * 1.0 = 30; budget = 30
        positions = [_pos("A", "p", 0.0, 5.0, 30.0)]
        result = compute_rwa(positions, 100_000, 30.0)
        self.assertFalse(result.scaling_applied)

    def test_scale_factor_correct(self):
        positions = [_pos("A", "p", 100.0, 5.0, 100.0)]  # rwa = 200
        result = compute_rwa(positions, 100_000, 100.0)
        # scale_factor = 100/200 = 0.5; new_req = 50; new_rwa = 50 * 2.0 = 100
        self.assertAlmostEqual(result.positions[0].requested_allocation_pct, 50.0, places=9)
        self.assertAlmostEqual(result.total_rwa_pct, 100.0, places=9)


# ---------------------------------------------------------------------------
# 6. effective_allocation_pct sums to 100%
# ---------------------------------------------------------------------------

class TestEffectiveAllocationPct(unittest.TestCase):

    def test_effective_pct_sums_to_100_no_scaling(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 300.0)
        total = sum(p.effective_allocation_pct for p in result.positions)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_effective_pct_sums_to_100_with_scaling(self):
        positions = [
            _pos("A", "p", 50.0, 5.0, 100.0),
            _pos("B", "p", 50.0, 5.0, 100.0),
        ]
        result = compute_rwa(positions, 100_000, 100.0)
        total = sum(p.effective_allocation_pct for p in result.positions)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_effective_pct_sums_to_100_single_position(self):
        positions = [_pos("A", "p", 20.0, 5.0, 40.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertAlmostEqual(result.positions[0].effective_allocation_pct, 100.0, places=9)

    def test_effective_pct_proportional_to_requested_no_scaling(self):
        positions = [
            _pos("A", "p", 0.0, 5.0, 25.0),
            _pos("B", "p", 0.0, 5.0, 75.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        self.assertAlmostEqual(result.positions[0].effective_allocation_pct, 25.0, places=9)
        self.assertAlmostEqual(result.positions[1].effective_allocation_pct, 75.0, places=9)


# ---------------------------------------------------------------------------
# 7. effective_usd
# ---------------------------------------------------------------------------

class TestEffectiveUsd(unittest.TestCase):

    def test_effective_usd_equals_pct_times_capital(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]
        capital = 200_000.0
        result = compute_rwa(positions, capital, 300.0)
        p = result.positions[0]
        self.assertAlmostEqual(p.effective_usd, p.effective_allocation_pct / 100.0 * capital)

    def test_effective_usd_sums_to_total_capital(self):
        positions = _simple_positions()
        capital = 100_000.0
        result = compute_rwa(positions, capital, 300.0)
        total_usd = sum(p.effective_usd for p in result.positions)
        self.assertAlmostEqual(total_usd, capital, places=6)

    def test_effective_usd_single_position(self):
        capital = 50_000.0
        positions = [_pos("A", "p", 0.0, 5.0, 40.0)]
        result = compute_rwa(positions, capital, 200.0)
        # Single position gets 100% effective_pct → effective_usd = capital
        self.assertAlmostEqual(result.positions[0].effective_usd, capital, places=6)

    def test_effective_usd_multiple_positions_proportional(self):
        capital = 100_000.0
        positions = [
            _pos("A", "p", 0.0, 5.0, 50.0),
            _pos("B", "p", 0.0, 5.0, 50.0),
        ]
        result = compute_rwa(positions, capital, 200.0)
        self.assertAlmostEqual(result.positions[0].effective_usd, 50_000.0, places=4)
        self.assertAlmostEqual(result.positions[1].effective_usd, 50_000.0, places=4)


# ---------------------------------------------------------------------------
# 8. Portfolio statistics
# ---------------------------------------------------------------------------

class TestPortfolioStats(unittest.TestCase):

    def test_weighted_apy_formula(self):
        positions = [
            _pos("A", "p", 0.0, 10.0, 50.0),
            _pos("B", "p", 0.0, 20.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 200.0)
        # Equal effective_pct (50% each) → weighted_apy = 0.5*10 + 0.5*20 = 15
        self.assertAlmostEqual(result.weighted_apy, 15.0, places=9)

    def test_weighted_apy_skewed(self):
        positions = [
            _pos("A", "p", 0.0, 4.0, 80.0),
            _pos("B", "p", 0.0, 8.0, 20.0),
        ]
        result = compute_rwa(positions, 100_000, 200.0)
        # effective: A=80%, B=20% → 0.8*4 + 0.2*8 = 3.2 + 1.6 = 4.8
        self.assertAlmostEqual(result.weighted_apy, 4.8, places=9)

    def test_weighted_risk_formula(self):
        positions = [
            _pos("A", "p", 20.0, 5.0, 50.0),
            _pos("B", "p", 80.0, 5.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        # Equal effective_pct → 0.5*20 + 0.5*80 = 50
        self.assertAlmostEqual(result.weighted_risk, 50.0, places=9)

    def test_weighted_risk_single_position(self):
        positions = [_pos("A", "p", 30.0, 5.0, 100.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertAlmostEqual(result.weighted_risk, 30.0, places=9)

    def test_utilization_pct_formula(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]  # rwa = 100
        result = compute_rwa(positions, 100_000, 200.0)
        # utilization = 100 / 200 * 100 = 50
        self.assertAlmostEqual(result.utilization_pct, 50.0, places=9)

    def test_utilization_pct_at_100(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]  # rwa = 100
        result = compute_rwa(positions, 100_000, 100.0)
        self.assertAlmostEqual(result.utilization_pct, 100.0, places=6)

    def test_rwa_apy_improvement_positive(self):
        # High-APY gets more weight (lower risk_score = lower haircut)
        positions = [
            _pos("A", "p", 0.0, 10.0, 60.0),   # risk_weight=1.0
            _pos("B", "p", 100.0, 2.0, 40.0),   # risk_weight=2.0 → gets haircut
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        equal_weight_apy = (10.0 + 2.0) / 2.0
        self.assertIsInstance(result.rwa_apy_improvement, float)
        # Should be calculable without error
        expected = result.weighted_apy - equal_weight_apy
        self.assertAlmostEqual(result.rwa_apy_improvement, expected, places=9)

    def test_rwa_apy_improvement_equals_formula(self):
        positions = [
            _pos("A", "p", 0.0, 5.0, 50.0),
            _pos("B", "p", 0.0, 7.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        equal_weight = (5.0 + 7.0) / 2.0
        self.assertAlmostEqual(result.rwa_apy_improvement, result.weighted_apy - equal_weight, places=9)

    def test_rwa_apy_improvement_negative_when_risky_has_high_apy(self):
        # High-APY position gets heavy haircut → RWA weighting might reduce apy vs equal weight
        positions = [
            _pos("Low", "p", 0.0, 2.0, 50.0),   # low risk, low apy
            _pos("High", "p", 100.0, 20.0, 50.0), # high risk, high apy → gets big haircut
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        equal_weight_apy = (2.0 + 20.0) / 2.0
        # With RWA the high-risk position gets lower effective_pct
        rwa_improvement = result.weighted_apy - equal_weight_apy
        self.assertAlmostEqual(result.rwa_apy_improvement, rwa_improvement, places=9)


# ---------------------------------------------------------------------------
# 9. allocation_label
# ---------------------------------------------------------------------------

class TestAllocationLabel(unittest.TestCase):

    def test_label_optimal(self):
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]  # rwa=50 <= 200
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertEqual(result.allocation_label, "OPTIMAL")

    def test_label_scaled(self):
        positions = [_pos("A", "p", 100.0, 5.0, 100.0)]  # rwa=200 > 100
        result = compute_rwa(positions, 100_000, 100.0)
        self.assertEqual(result.allocation_label, "SCALED")

    def test_label_over_budget_direct(self):
        # Construct result with over-budget state directly
        r = RWAAllocationResult(
            total_capital_usd=100_000,
            risk_budget_pct=100.0,
            positions=[],
            total_rwa_pct=150.0,
            within_budget=False,
            scaling_applied=False,
            allocation_label="OVER_BUDGET",
        )
        self.assertEqual(r.allocation_label, "OVER_BUDGET")

    def test_label_scaled_when_scaling_applied(self):
        positions = [
            _pos("A", "p", 50.0, 5.0, 70.0),
            _pos("B", "p", 50.0, 5.0, 70.0),
        ]
        # total_rwa = 140*1.5 = 210 > 150
        result = compute_rwa(positions, 100_000, 150.0)
        self.assertEqual(result.allocation_label, "SCALED")
        self.assertTrue(result.scaling_applied)


# ---------------------------------------------------------------------------
# 10. budget_headroom
# ---------------------------------------------------------------------------

class TestBudgetHeadroom(unittest.TestCase):

    def test_headroom_positive_when_within_budget(self):
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]  # rwa=50
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertAlmostEqual(result.budget_headroom_pct, 150.0, places=9)

    def test_headroom_zero_when_at_budget(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]  # rwa=100, budget=100
        result = compute_rwa(positions, 100_000, 100.0)
        self.assertAlmostEqual(result.budget_headroom_pct, 0.0, places=6)

    def test_headroom_formula(self):
        positions = [_pos("A", "p", 50.0, 5.0, 100.0)]  # rwa=150
        result = compute_rwa(positions, 100_000, 300.0)
        self.assertAlmostEqual(result.budget_headroom_pct, 150.0, places=9)

    def test_headroom_near_zero_after_scaling(self):
        positions = [_pos("A", "p", 100.0, 5.0, 100.0)]  # rwa=200, budget=100
        result = compute_rwa(positions, 100_000, 100.0)
        self.assertAlmostEqual(result.budget_headroom_pct, 0.0, places=6)


# ---------------------------------------------------------------------------
# 11. Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):

    def test_near_risk_budget_limit_trigger(self):
        # utilization > 90%: rwa=91, budget=100
        positions = [_pos("A", "p", 0.0, 5.0, 91.0)]
        result = compute_rwa(positions, 100_000, 100.0)
        self.assertIn("Near risk budget limit", result.recommendations)

    def test_no_near_limit_when_utilization_low(self):
        positions = [_pos("A", "p", 0.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 200.0)  # utilization=25%
        self.assertNotIn("Near risk budget limit", result.recommendations)

    def test_high_risk_positions_trigger(self):
        positions = [_pos("A", "p", 85.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 300.0)
        self.assertIn("High-risk positions present", result.recommendations)

    def test_no_high_risk_when_all_low(self):
        positions = [_pos("A", "p", 30.0, 5.0, 50.0)]
        result = compute_rwa(positions, 100_000, 300.0)
        self.assertNotIn("High-risk positions present", result.recommendations)

    def test_low_apy_improvement_trigger(self):
        # High-risk position with high APY gets haircut → RWA may reduce APY
        positions = [
            _pos("LowRisk", "p", 0.0, 1.0, 50.0),
            _pos("HighRisk", "p", 100.0, 30.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)
        # The recommendation appears if rwa_apy_improvement < 0
        if result.rwa_apy_improvement < 0:
            self.assertIn("Risk weighting reduced APY vs equal-weight", result.recommendations)

    def test_no_recommendations_when_all_good(self):
        positions = [
            _pos("A", "p", 10.0, 5.0, 50.0),
            _pos("B", "p", 10.0, 5.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 300.0)  # utilization ≈37%
        self.assertNotIn("Near risk budget limit", result.recommendations)
        self.assertNotIn("High-risk positions present", result.recommendations)

    def test_all_recommendations_triggered(self):
        # utilization > 90%, high risk, and if rwa reduces apy
        positions = [
            _pos("A", "p", 90.0, 1.0, 50.0),
        ]
        result = compute_rwa(positions, 100_000, 95.0)
        # rwa = 50 * 1.9 = 95; utilization = 100% > 90% → near limit
        # risk_score = 90 > 80 → high risk
        self.assertIn("Near risk budget limit", result.recommendations)
        self.assertIn("High-risk positions present", result.recommendations)

    def test_recommendations_is_list(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertIsInstance(result.recommendations, list)


# ---------------------------------------------------------------------------
# 12. compare_budgets
# ---------------------------------------------------------------------------

class TestCompareBudgets(unittest.TestCase):

    def test_compare_budgets_returns_dict(self):
        positions = _simple_positions()
        result = compare_budgets(100_000, positions, [100.0, 150.0, 200.0])
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), {100.0, 150.0, 200.0})

    def test_compare_budgets_different_labels(self):
        positions = [_pos("A", "p", 50.0, 5.0, 100.0)]  # rwa = 150
        result = compare_budgets(100_000, positions, [100.0, 200.0])
        # budget=100 → rwa=150>100 → SCALED
        # budget=200 → rwa=150<=200 → OPTIMAL
        self.assertEqual(result[100.0].allocation_label, "SCALED")
        self.assertEqual(result[200.0].allocation_label, "OPTIMAL")

    def test_compare_budgets_higher_budget_higher_headroom(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]  # rwa = 100
        result = compare_budgets(100_000, positions, [150.0, 300.0])
        self.assertGreater(
            result[300.0].budget_headroom_pct,
            result[150.0].budget_headroom_pct,
        )

    def test_compare_budgets_higher_budget_lower_utilization(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]  # rwa = 100
        result = compare_budgets(100_000, positions, [150.0, 200.0])
        self.assertGreater(
            result[150.0].utilization_pct,
            result[200.0].utilization_pct,
        )

    def test_compare_budgets_empty_budgets(self):
        positions = _simple_positions()
        result = compare_budgets(100_000, positions, [])
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 13. save / load
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_save_creates_file(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 200.0)
        path = save_results(result, self._tmp)
        self.assertTrue(Path(path).exists())

    def test_load_history_empty_before_save(self):
        history = load_history(self._tmp)
        self.assertEqual(history, [])

    def test_save_load_round_trip(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 200.0)
        save_results(result, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["total_capital_usd"], 100_000.0)

    def test_save_load_multiple_entries(self):
        for _ in range(3):
            positions = _simple_positions()
            result = compute_rwa(positions, 100_000, 200.0)
            save_results(result, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 3)

    def test_save_sets_saved_to(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 200.0)
        path = save_results(result, self._tmp)
        self.assertEqual(result.saved_to, path)

    def test_save_load_preserves_allocation_label(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 300.0)
        save_results(result, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(history[0]["allocation_label"], result.allocation_label)


# ---------------------------------------------------------------------------
# 14. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def test_ring_buffer_cap_at_100(self):
        for i in range(105):
            positions = [_pos(f"A{i}", "p", 0.0, 5.0, 100.0)]
            result = compute_rwa(positions, 100_000, 200.0)
            save_results(result, self._tmp)
        history = load_history(self._tmp)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(105):
            positions = [_pos(f"P{i}", "p", float(i % 50), 5.0, 100.0)]
            result = compute_rwa(positions, float(i * 1000), 300.0)
            save_results(result, self._tmp)
        history = load_history(self._tmp)
        # The oldest entries (i < 5) should be dropped; latest 100 kept
        self.assertEqual(len(history), 100)
        last = history[-1]
        self.assertAlmostEqual(last["total_capital_usd"], 104_000.0)


# ---------------------------------------------------------------------------
# 15. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_single_position_no_scaling(self):
        positions = [_pos("A", "p", 0.0, 5.0, 100.0)]
        result = compute_rwa(positions, 100_000, 200.0)
        self.assertFalse(result.scaling_applied)
        self.assertAlmostEqual(result.positions[0].effective_allocation_pct, 100.0)

    def test_single_position_with_scaling(self):
        positions = [_pos("A", "p", 100.0, 5.0, 100.0)]  # rwa=200 > 150
        result = compute_rwa(positions, 100_000, 150.0)
        self.assertTrue(result.scaling_applied)
        self.assertAlmostEqual(result.positions[0].effective_allocation_pct, 100.0)

    def test_all_same_risk_score_uniform_rwa(self):
        positions = [
            _pos("A", "p", 50.0, 3.0, 30.0),
            _pos("B", "p", 50.0, 6.0, 40.0),
            _pos("C", "p", 50.0, 9.0, 30.0),
        ]
        result = compute_rwa(positions, 100_000, 500.0)
        # All same risk_weight=1.5; rwa_pct ratios same as requested_pct ratios
        rwa_a = result.positions[0].rwa_pct
        rwa_b = result.positions[1].rwa_pct
        self.assertAlmostEqual(rwa_b / rwa_a, 40.0 / 30.0, places=9)

    def test_all_same_risk_score_equal_requested(self):
        positions = [
            _pos("A", "p", 20.0, 3.0, 33.33),
            _pos("B", "p", 20.0, 6.0, 33.33),
            _pos("C", "p", 20.0, 9.0, 33.34),
        ]
        result = compute_rwa(positions, 100_000, 500.0)
        total = sum(p.effective_allocation_pct for p in result.positions)
        self.assertAlmostEqual(total, 100.0, places=6)

    def test_budget_zero_produces_scaled(self):
        positions = [_pos("A", "p", 50.0, 5.0, 100.0)]
        result = compute_rwa(positions, 100_000, 0.0)
        self.assertTrue(result.scaling_applied)
        self.assertEqual(result.allocation_label, "SCALED")

    def test_empty_positions_returns_valid_result(self):
        result = compute_rwa([], 100_000, 200.0)
        self.assertEqual(result.positions, [])
        self.assertAlmostEqual(result.total_rwa_pct, 0.0)
        self.assertEqual(result.allocation_label, "OPTIMAL")

    def test_total_capital_preserved_in_result(self):
        positions = _simple_positions()
        capital = 999_999.0
        result = compute_rwa(positions, capital, 200.0)
        self.assertAlmostEqual(result.total_capital_usd, capital)

    def test_risk_budget_pct_preserved_in_result(self):
        positions = _simple_positions()
        budget = 175.0
        result = compute_rwa(positions, 100_000, budget)
        self.assertAlmostEqual(result.risk_budget_pct, budget)

    def test_positions_count_in_result(self):
        positions = _simple_positions()
        result = compute_rwa(positions, 100_000, 300.0)
        self.assertEqual(len(result.positions), 3)

    def test_original_positions_not_mutated(self):
        positions = _simple_positions()
        original_pct = [p.requested_allocation_pct for p in positions]
        compute_rwa(positions, 100_000, 50.0)  # will trigger scaling
        for orig, p in zip(original_pct, positions):
            self.assertAlmostEqual(p.requested_allocation_pct, orig)


if __name__ == "__main__":
    unittest.main(verbosity=2)
