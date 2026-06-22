"""Tests for MP-689 RebalanceCostOptimizer.

Run with:
    python3 -m unittest spa_core.tests.test_rebalance_cost_optimizer -v

Covers ≥60 test cases:
  - apy_improvement_pct: target - current
  - annual_gain_usd: correct formula
  - break_even_days: inf when no gain
  - break_even_days: correct formula
  - net_annual_benefit_usd: gain - cost
  - roi_pct: 0 when no cost
  - verdict: SKIP / DEFER / EXECUTE thresholds
  - rationale: correct text for each verdict
  - analyze() full field verification
  - build_plan() empty / mixed / execution_order / totals
  - save_results() ring-buffer + atomic write
  - load_history() missing file → []
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.rebalance_cost_optimizer import (
    MAX_ENTRIES,
    RebalanceCandidate,
    RebalanceCostOptimizer,
    RebalanceDecision,
    RebalancePlan,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _candidate(
    *,
    position_id="P1",
    from_protocol="Aave",
    to_protocol="Morpho",
    move_amount_usd=100_000.0,
    current_apy_pct=3.0,
    target_apy_pct=5.0,
    gas_cost_usd=50.0,
    slippage_cost_usd=25.0,
    lock_period_days=0,
) -> RebalanceCandidate:
    return RebalanceCandidate(
        position_id=position_id,
        from_protocol=from_protocol,
        to_protocol=to_protocol,
        move_amount_usd=move_amount_usd,
        current_apy_pct=current_apy_pct,
        target_apy_pct=target_apy_pct,
        gas_cost_usd=gas_cost_usd,
        slippage_cost_usd=slippage_cost_usd,
        lock_period_days=lock_period_days,
    )


def _optimizer(tmp_dir=None) -> RebalanceCostOptimizer:
    if tmp_dir:
        data_file = Path(tmp_dir) / "rebalance_cost_log.json"
        return RebalanceCostOptimizer(data_file=data_file)
    return RebalanceCostOptimizer()


# ─── apy_improvement_pct ──────────────────────────────────────────────────────

class TestAPYImprovement(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_improvement_positive(self):
        c = _candidate(current_apy_pct=3.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.apy_improvement_pct, 2.0, places=6)

    def test_improvement_zero(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.apy_improvement_pct, 0.0, places=6)

    def test_improvement_negative(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=3.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.apy_improvement_pct, -2.0, places=6)

    def test_improvement_large(self):
        c = _candidate(current_apy_pct=1.0, target_apy_pct=20.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.apy_improvement_pct, 19.0, places=6)


# ─── annual_gain_usd ──────────────────────────────────────────────────────────

class TestAnnualGain(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_annual_gain_basic(self):
        # 100_000 * 2.0 / 100 = 2000
        c = _candidate(move_amount_usd=100_000, current_apy_pct=3.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.annual_gain_usd, 2_000.0, places=4)

    def test_annual_gain_zero_improvement(self):
        c = _candidate(current_apy_pct=4.0, target_apy_pct=4.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.annual_gain_usd, 0.0, places=6)

    def test_annual_gain_negative(self):
        c = _candidate(move_amount_usd=50_000, current_apy_pct=6.0, target_apy_pct=4.0)
        d = self.opt.analyze(c)
        # 50_000 * (-2) / 100 = -1000
        self.assertAlmostEqual(d.annual_gain_usd, -1_000.0, places=4)

    def test_annual_gain_small_amount(self):
        c = _candidate(move_amount_usd=1_000, current_apy_pct=0.0, target_apy_pct=10.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.annual_gain_usd, 100.0, places=6)


# ─── total_cost_usd ───────────────────────────────────────────────────────────

class TestTotalCost(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_total_cost_sum(self):
        c = _candidate(gas_cost_usd=50.0, slippage_cost_usd=25.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.total_cost_usd, 75.0, places=6)

    def test_total_cost_zero_slippage(self):
        c = _candidate(gas_cost_usd=30.0, slippage_cost_usd=0.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.total_cost_usd, 30.0, places=6)

    def test_total_cost_zero_gas(self):
        c = _candidate(gas_cost_usd=0.0, slippage_cost_usd=20.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.total_cost_usd, 20.0, places=6)

    def test_total_cost_both_zero(self):
        c = _candidate(gas_cost_usd=0.0, slippage_cost_usd=0.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.total_cost_usd, 0.0, places=6)


# ─── break_even_days ──────────────────────────────────────────────────────────

class TestBreakEvenDays(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_break_even_infinite_when_no_gain(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=5.0,
                       gas_cost_usd=50.0, slippage_cost_usd=25.0)
        d = self.opt.analyze(c)
        self.assertEqual(d.break_even_days, float("inf"))

    def test_break_even_infinite_when_negative_gain(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=3.0)
        d = self.opt.analyze(c)
        self.assertEqual(d.break_even_days, float("inf"))

    def test_break_even_formula(self):
        # annual_gain = 100_000 * 2 / 100 = 2000
        # total_cost = 50 + 25 = 75
        # be_days = 75 / (2000/365) = 75 * 365 / 2000 = 13.6875
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=3.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=25.0,
        )
        d = self.opt.analyze(c)
        expected = 75.0 / (2_000.0 / 365.0)
        self.assertAlmostEqual(d.break_even_days, expected, places=4)

    def test_break_even_small_cost(self):
        # annual_gain = 100_000 * 5 / 100 = 5000; cost = 1
        # be = 1 / (5000/365) ≈ 0.073 days
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=0.5,
            slippage_cost_usd=0.5,
        )
        d = self.opt.analyze(c)
        expected = 1.0 / (5_000.0 / 365.0)
        self.assertAlmostEqual(d.break_even_days, expected, places=6)

    def test_break_even_large_cost(self):
        # annual_gain = 100_000 * 0.01 / 100 = 10 USD
        # cost = 365; be = 365 / (10/365) = 365 * 365 / 10 = 13322.5 days
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=0.01,
            gas_cost_usd=182.5,
            slippage_cost_usd=182.5,
        )
        d = self.opt.analyze(c)
        expected = 365.0 / (10.0 / 365.0)
        self.assertAlmostEqual(d.break_even_days, expected, places=2)


# ─── net_annual_benefit_usd ───────────────────────────────────────────────────

class TestNetAnnualBenefit(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_net_benefit_positive(self):
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=3.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=25.0,
        )
        d = self.opt.analyze(c)
        # gain=2000, cost=75 → net=1925
        self.assertAlmostEqual(d.net_annual_benefit_usd, 1_925.0, places=4)

    def test_net_benefit_negative_when_cost_exceeds_gain(self):
        c = _candidate(
            move_amount_usd=1_000,
            current_apy_pct=0.0,
            target_apy_pct=1.0,
            gas_cost_usd=500.0,
            slippage_cost_usd=0.0,
        )
        d = self.opt.analyze(c)
        # gain = 10, cost = 500, net = -490
        self.assertAlmostEqual(d.net_annual_benefit_usd, -490.0, places=4)

    def test_net_benefit_zero_cost(self):
        c = _candidate(gas_cost_usd=0.0, slippage_cost_usd=0.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.net_annual_benefit_usd, d.annual_gain_usd, places=6)


# ─── roi_pct ──────────────────────────────────────────────────────────────────

class TestROIPct(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_roi_zero_when_no_cost(self):
        c = _candidate(gas_cost_usd=0.0, slippage_cost_usd=0.0)
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.roi_pct, 0.0, places=6)

    def test_roi_formula(self):
        # gain=2000, cost=75 → net=1925, roi = 1925/75 * 100 = 2566.67%
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=3.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=25.0,
        )
        d = self.opt.analyze(c)
        expected = (1_925.0 / 75.0) * 100.0
        self.assertAlmostEqual(d.roi_pct, expected, places=3)

    def test_roi_negative_when_cost_exceeds_gain(self):
        c = _candidate(
            move_amount_usd=1_000,
            current_apy_pct=0.0,
            target_apy_pct=1.0,
            gas_cost_usd=500.0,
            slippage_cost_usd=0.0,
        )
        d = self.opt.analyze(c)
        self.assertLess(d.roi_pct, 0.0)


# ─── verdict ──────────────────────────────────────────────────────────────────

class TestVerdict(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_verdict_skip_no_improvement(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertEqual(d.verdict, "SKIP")

    def test_verdict_skip_negative_improvement(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=3.0)
        d = self.opt.analyze(c)
        self.assertEqual(d.verdict, "SKIP")

    def test_verdict_skip_break_even_over_180(self):
        # annual_gain tiny, cost large → break_even > 180
        c = _candidate(
            move_amount_usd=1_000,
            current_apy_pct=0.0,
            target_apy_pct=0.1,   # gain = 1 USD/yr
            gas_cost_usd=500.0,
            slippage_cost_usd=0.0,
        )
        d = self.opt.analyze(c)
        self.assertGreater(d.break_even_days, 180)
        self.assertEqual(d.verdict, "SKIP")

    def test_verdict_defer_break_even_61_to_180(self):
        # break_even around 90 days → DEFER
        # daily_gain = gain/365; cost = daily_gain * 90
        # gain = 1000; cost = 1000/365 * 90 ≈ 246.57
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=1.0,   # gain = 1000/yr
            gas_cost_usd=123.28,
            slippage_cost_usd=123.29,  # total cost ≈ 246.57 → be ≈ 90d
        )
        d = self.opt.analyze(c)
        self.assertGreater(d.break_even_days, 60)
        self.assertLessEqual(d.break_even_days, 180)
        self.assertEqual(d.verdict, "DEFER")

    def test_verdict_execute_break_even_at_60(self):
        # gain=1000, be=60: cost = 1000/365 * 60 ≈ 164.38
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=1.0,
            gas_cost_usd=82.19,
            slippage_cost_usd=82.19,  # total ≈ 164.38 → be ≈ 60d
        )
        d = self.opt.analyze(c)
        self.assertLessEqual(d.break_even_days, 60)
        self.assertEqual(d.verdict, "EXECUTE")

    def test_verdict_execute_break_even_very_low(self):
        # High gain, low cost → EXECUTE quickly
        c = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        d = self.opt.analyze(c)
        self.assertEqual(d.verdict, "EXECUTE")

    def test_verdict_execute_boundary_exactly_60(self):
        # be = cost / (gain/365) = 60 → cost = 60 * gain / 365
        gain = 365.0  # annual gain = 365
        cost = 60.0   # be = 60 / (365/365) = 60 exactly
        c = _candidate(
            move_amount_usd=10_000,
            current_apy_pct=0.0,
            target_apy_pct=3.65,   # gain = 365
            gas_cost_usd=30.0,
            slippage_cost_usd=30.0,  # total=60, be=60*(365/365)=60
        )
        d = self.opt.analyze(c)
        self.assertAlmostEqual(d.break_even_days, 60.0, places=1)
        self.assertEqual(d.verdict, "EXECUTE")


# ─── rationale ────────────────────────────────────────────────────────────────

class TestRationale(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_rationale_skip_contains_no_benefit(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertIn("No benefit", d.rationale)

    def test_rationale_skip_shows_apy_values(self):
        c = _candidate(current_apy_pct=3.0, target_apy_pct=3.0)
        d = self.opt.analyze(c)
        self.assertIn("3.0%", d.rationale)

    def test_rationale_skip_shows_break_even(self):
        c = _candidate(current_apy_pct=5.0, target_apy_pct=5.0)
        d = self.opt.analyze(c)
        self.assertIn("break-even", d.rationale)

    def test_rationale_defer_contains_long_payback(self):
        c = _candidate(
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=1.0,
            gas_cost_usd=123.28,
            slippage_cost_usd=123.29,
        )
        d = self.opt.analyze(c)
        self.assertEqual(d.verdict, "DEFER")
        self.assertIn("Long payback", d.rationale)

    def test_rationale_execute_contains_execute(self):
        c = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        d = self.opt.analyze(c)
        self.assertEqual(d.verdict, "EXECUTE")
        self.assertIn("Execute", d.rationale)

    def test_rationale_execute_contains_apy_improvement(self):
        c = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=1.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        d = self.opt.analyze(c)
        self.assertIn("+4.00% APY", d.rationale)

    def test_rationale_execute_contains_payback(self):
        c = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        d = self.opt.analyze(c)
        self.assertIn("payback", d.rationale)


# ─── analyze() full field verification ───────────────────────────────────────

class TestAnalyzeFull(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_analyze_known_execute(self):
        c = _candidate(
            position_id="POS_A",
            from_protocol="Compound",
            to_protocol="Morpho",
            move_amount_usd=100_000,
            current_apy_pct=3.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=25.0,
        )
        d = self.opt.analyze(c)
        self.assertEqual(d.position_id, "POS_A")
        self.assertEqual(d.from_protocol, "Compound")
        self.assertEqual(d.to_protocol, "Morpho")
        self.assertAlmostEqual(d.move_amount_usd, 100_000.0, places=2)
        self.assertAlmostEqual(d.apy_improvement_pct, 2.0, places=6)
        self.assertAlmostEqual(d.annual_gain_usd, 2_000.0, places=4)
        self.assertAlmostEqual(d.total_cost_usd, 75.0, places=6)
        expected_be = 75.0 / (2_000.0 / 365.0)
        self.assertAlmostEqual(d.break_even_days, expected_be, places=4)
        self.assertAlmostEqual(d.net_annual_benefit_usd, 1_925.0, places=4)
        self.assertAlmostEqual(d.roi_pct, 1_925.0 / 75.0 * 100.0, places=3)
        self.assertEqual(d.verdict, "EXECUTE")
        self.assertIsInstance(d.rationale, str)

    def test_analyze_returns_decision_type(self):
        d = self.opt.analyze(_candidate())
        self.assertIsInstance(d, RebalanceDecision)

    def test_analyze_lock_period_stored_in_candidate(self):
        # lock_period_days does not affect decision math but is stored on candidate
        c = _candidate(lock_period_days=7)
        self.assertEqual(c.lock_period_days, 7)

    def test_analyze_default_priority_zero_before_build_plan(self):
        # analyze() alone sets priority=0; build_plan sets it properly
        c = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        d = self.opt.analyze(c)
        self.assertEqual(d.priority, 0)


# ─── build_plan() ─────────────────────────────────────────────────────────────

class TestBuildPlan(unittest.TestCase):

    def setUp(self):
        self.opt = _optimizer()

    def test_build_plan_empty_candidates(self):
        plan = self.opt.build_plan([])
        self.assertFalse(plan.should_rebalance)
        self.assertEqual(plan.execution_order, [])
        self.assertEqual(plan.total_cost_usd, 0.0)
        self.assertEqual(plan.total_annual_gain_usd, 0.0)
        self.assertEqual(plan.net_annual_benefit_usd, 0.0)
        self.assertEqual(plan.candidates, [])

    def test_build_plan_all_skip(self):
        cs = [
            _candidate(position_id="S1", current_apy_pct=5.0, target_apy_pct=5.0),
            _candidate(position_id="S2", current_apy_pct=4.0, target_apy_pct=3.0),
        ]
        plan = self.opt.build_plan(cs)
        self.assertFalse(plan.should_rebalance)
        self.assertEqual(plan.execution_order, [])
        self.assertAlmostEqual(plan.total_cost_usd, 0.0, places=6)

    def test_build_plan_mixed_execution_order_contains_only_execute(self):
        skip = _candidate(position_id="SKIP1", current_apy_pct=5.0, target_apy_pct=5.0)
        execute = _candidate(
            position_id="EXEC1",
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        plan = self.opt.build_plan([skip, execute])
        self.assertTrue(plan.should_rebalance)
        self.assertIn("EXEC1", plan.execution_order)
        self.assertNotIn("SKIP1", plan.execution_order)

    def test_build_plan_execution_order_sorted_by_annual_gain_desc(self):
        # Low gain execute
        e_low = _candidate(
            position_id="LOW",
            move_amount_usd=10_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,   # gain = 500
            gas_cost_usd=5.0,
            slippage_cost_usd=5.0,
        )
        # High gain execute
        e_high = _candidate(
            position_id="HIGH",
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,   # gain = 50_000
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        plan = self.opt.build_plan([e_low, e_high])
        self.assertEqual(plan.execution_order, ["HIGH", "LOW"])

    def test_build_plan_total_cost_only_execute(self):
        execute = _candidate(
            position_id="E1",
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        skip = _candidate(
            position_id="S1",
            current_apy_pct=5.0,
            target_apy_pct=5.0,
            gas_cost_usd=100.0,
            slippage_cost_usd=100.0,
        )
        plan = self.opt.build_plan([execute, skip])
        # only E1 costs should be counted
        self.assertAlmostEqual(plan.total_cost_usd, 100.0, places=6)

    def test_build_plan_total_annual_gain_only_execute(self):
        e1 = _candidate(
            position_id="E1",
            move_amount_usd=100_000,
            current_apy_pct=0.0,
            target_apy_pct=2.0,   # gain=2000
            gas_cost_usd=10.0,
            slippage_cost_usd=5.0,
        )
        e2 = _candidate(
            position_id="E2",
            move_amount_usd=200_000,
            current_apy_pct=0.0,
            target_apy_pct=2.0,   # gain=4000
            gas_cost_usd=10.0,
            slippage_cost_usd=5.0,
        )
        plan = self.opt.build_plan([e1, e2])
        self.assertAlmostEqual(plan.total_annual_gain_usd, 6_000.0, places=4)

    def test_build_plan_net_benefit_equals_gain_minus_cost(self):
        e1 = _candidate(
            position_id="E1",
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        plan = self.opt.build_plan([e1])
        self.assertAlmostEqual(
            plan.net_annual_benefit_usd,
            plan.total_annual_gain_usd - plan.total_cost_usd,
            places=4,
        )

    def test_build_plan_should_rebalance_true_with_execute(self):
        e = _candidate(
            move_amount_usd=1_000_000,
            current_apy_pct=0.0,
            target_apy_pct=5.0,
            gas_cost_usd=50.0,
            slippage_cost_usd=50.0,
        )
        plan = self.opt.build_plan([e])
        self.assertTrue(plan.should_rebalance)

    def test_build_plan_plan_type(self):
        plan = self.opt.build_plan([_candidate()])
        self.assertIsInstance(plan, RebalancePlan)

    def test_build_plan_priority_1_highest_gain(self):
        low = _candidate(position_id="LOW", move_amount_usd=10_000,
                         current_apy_pct=0.0, target_apy_pct=5.0,
                         gas_cost_usd=5.0, slippage_cost_usd=0.0)
        high = _candidate(position_id="HIGH", move_amount_usd=1_000_000,
                          current_apy_pct=0.0, target_apy_pct=5.0,
                          gas_cost_usd=50.0, slippage_cost_usd=0.0)
        plan = self.opt.build_plan([low, high])
        decisions_by_id = {d.position_id: d for d in plan.candidates}
        self.assertEqual(decisions_by_id["HIGH"].priority, 1)
        self.assertEqual(decisions_by_id["LOW"].priority, 2)


# ─── save_results / load_history ──────────────────────────────────────────────

class TestPersistence(unittest.TestCase):

    def _make_decision(self, pos_id="D1") -> RebalanceDecision:
        return RebalanceDecision(
            position_id=pos_id,
            from_protocol="Aave",
            to_protocol="Morpho",
            move_amount_usd=100_000.0,
            apy_improvement_pct=2.0,
            annual_gain_usd=2_000.0,
            total_cost_usd=75.0,
            break_even_days=13.69,
            net_annual_benefit_usd=1_925.0,
            roi_pct=2566.67,
            verdict="EXECUTE",
            priority=1,
            rationale="Execute: +2.00% APY, 14d payback, +$2000/yr",
        )

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            opt.save_results([self._make_decision()])
            self.assertTrue(opt.data_file.exists())

    def test_save_stores_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            opt.save_results([self._make_decision("PX1")])
            history = opt.load_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["position_id"], "PX1")

    def test_save_appends_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            opt.save_results([self._make_decision("A")])
            opt.save_results([self._make_decision("B")])
            history = opt.load_history()
            self.assertEqual(len(history), 2)

    def test_save_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            for i in range(MAX_ENTRIES + 10):
                opt.save_results([self._make_decision(f"D{i}")])
            history = opt.load_history()
            self.assertEqual(len(history), MAX_ENTRIES)

    def test_save_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            for i in range(MAX_ENTRIES + 5):
                opt.save_results([self._make_decision(f"D{i}")])
            history = opt.load_history()
            self.assertEqual(history[-1]["position_id"], f"D{MAX_ENTRIES + 4}")

    def test_save_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            opt.save_results([self._make_decision()])
            tmp_file = opt.data_file.with_suffix(".tmp")
            self.assertFalse(tmp_file.exists())

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            result = opt.load_history()
            self.assertEqual(result, [])

    def test_load_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            opt.data_file.parent.mkdir(parents=True, exist_ok=True)
            opt.data_file.write_text("{{NOT JSON")
            result = opt.load_history()
            self.assertEqual(result, [])

    def test_save_inf_break_even_serialised_as_minus_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            d = self._make_decision()
            d.break_even_days = float("inf")
            opt.save_results([d])
            raw = json.loads(opt.data_file.read_text())
            self.assertEqual(raw[0]["break_even_days"], -1)

    def test_save_batch_multiple(self):
        with tempfile.TemporaryDirectory() as tmp:
            opt = _optimizer(tmp)
            decisions = [self._make_decision(f"D{i}") for i in range(5)]
            opt.save_results(decisions)
            history = opt.load_history()
            self.assertEqual(len(history), 5)


if __name__ == "__main__":
    unittest.main()
