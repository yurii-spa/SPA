"""
Tests for MP-782: WithdrawalQueueRiskAnalyzer
>=70 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.withdrawal_queue_risk_analyzer import (
    IMMEDIATE_DAYS,
    FAST_DAYS,
    SLOW_DAYS,
    MAX_ENTRIES,
    MIN_LIQUIDITY_COVERAGE,
    WithdrawalQueueRiskAnalyzer,
    WithdrawalQueueReport,
)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_frozen_overrides(self):
        self.assertEqual(self.a._classify(5.0, True), "FROZEN")

    def test_frozen_with_none(self):
        self.assertEqual(self.a._classify(None, True), "FROZEN")

    def test_none_days_unknown(self):
        self.assertEqual(self.a._classify(None, False), "UNKNOWN")

    def test_immediate_zero(self):
        self.assertEqual(self.a._classify(0.0, False), "IMMEDIATE")

    def test_immediate_boundary(self):
        self.assertEqual(self.a._classify(IMMEDIATE_DAYS, False), "IMMEDIATE")

    def test_immediate_below(self):
        self.assertEqual(self.a._classify(0.5, False), "IMMEDIATE")

    def test_fast_just_above_immediate(self):
        self.assertEqual(self.a._classify(1.0001, False), "FAST")

    def test_fast_boundary(self):
        self.assertEqual(self.a._classify(FAST_DAYS, False), "FAST")

    def test_fast_mid(self):
        self.assertEqual(self.a._classify(2.0, False), "FAST")

    def test_slow_just_above_fast(self):
        self.assertEqual(self.a._classify(3.0001, False), "SLOW")

    def test_slow_boundary(self):
        self.assertEqual(self.a._classify(SLOW_DAYS, False), "SLOW")

    def test_slow_mid(self):
        self.assertEqual(self.a._classify(7.0, False), "SLOW")

    def test_congested_just_above_slow(self):
        self.assertEqual(self.a._classify(14.0001, False), "CONGESTED")

    def test_congested_high(self):
        self.assertEqual(self.a._classify(60.0, False), "CONGESTED")

    def test_congested_boundary_30(self):
        self.assertEqual(self.a._classify(30.0, False), "CONGESTED")


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_zero_position_unknown(self):
        r = self.a.analyze(0.0, 100.0, 10.0)
        self.assertEqual(r.tier, "UNKNOWN")

    def test_negative_position_unknown(self):
        r = self.a.analyze(-50.0, 100.0, 10.0)
        self.assertEqual(r.tier, "UNKNOWN")

    def test_negative_queue_unknown(self):
        r = self.a.analyze(100.0, -1.0, 10.0)
        self.assertEqual(r.tier, "UNKNOWN")

    def test_negative_daily_unknown(self):
        r = self.a.analyze(100.0, 100.0, -10.0)
        self.assertEqual(r.tier, "UNKNOWN")

    def test_negative_cooldown_unknown(self):
        r = self.a.analyze(100.0, 100.0, 10.0, cooldown_days=-1.0)
        self.assertEqual(r.tier, "UNKNOWN")

    def test_unknown_advisory(self):
        r = self.a.analyze(0.0, 100.0, 10.0)
        self.assertTrue(any("Invalid input" in x for x in r.advisory))

    def test_unknown_none_metrics(self):
        r = self.a.analyze(0.0, 100.0, 10.0)
        self.assertIsNone(r.estimated_days_to_exit)
        self.assertIsNone(r.liquidity_coverage_ratio)
        self.assertIsNone(r.days_to_process)
        self.assertIsNone(r.position_pct_of_queue)

    def test_returns_report_type(self):
        self.assertIsInstance(self.a.analyze(100.0, 50.0, 25.0), WithdrawalQueueReport)

    def test_unknown_keeps_queue_ahead(self):
        r = self.a.analyze(0.0, 123.0, 10.0)
        self.assertEqual(r.queue_ahead_usd, 123.0)


class TestFrozen(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_frozen_daily_zero_with_queue(self):
        r = self.a.analyze(100.0, 1000.0, 0.0)
        self.assertEqual(r.tier, "FROZEN")

    def test_frozen_est_days_none(self):
        r = self.a.analyze(100.0, 1000.0, 0.0)
        self.assertIsNone(r.estimated_days_to_exit)

    def test_frozen_days_to_process_none(self):
        r = self.a.analyze(100.0, 1000.0, 0.0)
        self.assertIsNone(r.days_to_process)

    def test_frozen_advisory(self):
        r = self.a.analyze(100.0, 1000.0, 0.0)
        self.assertTrue(any("frozen" in x.lower() for x in r.advisory))

    def test_empty_queue_no_processing_not_frozen(self):
        # No queue and no processing -> 0 days, IMMEDIATE, not frozen.
        r = self.a.analyze(100.0, 0.0, 0.0)
        self.assertEqual(r.tier, "IMMEDIATE")
        self.assertEqual(r.days_to_process, 0.0)

    def test_empty_queue_no_processing_est_zero(self):
        r = self.a.analyze(100.0, 0.0, 0.0)
        self.assertEqual(r.estimated_days_to_exit, 0.0)


class TestTiers(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_immediate_small_queue(self):
        # queue 50, daily 100 -> 0.5 days
        r = self.a.analyze(100.0, 50.0, 100.0)
        self.assertEqual(r.tier, "IMMEDIATE")

    def test_immediate_exactly_one_day(self):
        r = self.a.analyze(100.0, 100.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 1.0)
        self.assertEqual(r.tier, "IMMEDIATE")

    def test_fast_two_days(self):
        r = self.a.analyze(100.0, 200.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 2.0)
        self.assertEqual(r.tier, "FAST")

    def test_fast_three_days(self):
        r = self.a.analyze(100.0, 300.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 3.0)
        self.assertEqual(r.tier, "FAST")

    def test_slow_ten_days(self):
        r = self.a.analyze(100.0, 1000.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 10.0)
        self.assertEqual(r.tier, "SLOW")

    def test_slow_fourteen_days(self):
        r = self.a.analyze(100.0, 1400.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 14.0)
        self.assertEqual(r.tier, "SLOW")

    def test_congested_twenty_days(self):
        r = self.a.analyze(100.0, 2000.0, 100.0)
        self.assertEqual(r.estimated_days_to_exit, 20.0)
        self.assertEqual(r.tier, "CONGESTED")

    def test_congested_hundred_days(self):
        r = self.a.analyze(100.0, 10000.0, 100.0)
        self.assertEqual(r.tier, "CONGESTED")

    def test_cooldown_adds_to_exit(self):
        # 1 day of processing + 5 day cooldown -> 6 days -> SLOW
        r = self.a.analyze(100.0, 100.0, 100.0, cooldown_days=5.0)
        self.assertEqual(r.estimated_days_to_exit, 6.0)
        self.assertEqual(r.tier, "SLOW")

    def test_cooldown_only_pushes_tier(self):
        # no queue, but a 7-day cooldown -> SLOW
        r = self.a.analyze(100.0, 0.0, 100.0, cooldown_days=7.0)
        self.assertEqual(r.estimated_days_to_exit, 7.0)
        self.assertEqual(r.tier, "SLOW")

    def test_cooldown_pushes_to_congested(self):
        r = self.a.analyze(100.0, 0.0, 100.0, cooldown_days=21.0)
        self.assertEqual(r.tier, "CONGESTED")


class TestDaysToProcess(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_basic_division(self):
        r = self.a.analyze(100.0, 500.0, 250.0)
        self.assertEqual(r.days_to_process, 2.0)

    def test_fractional(self):
        r = self.a.analyze(100.0, 150.0, 100.0)
        self.assertEqual(r.days_to_process, 1.5)

    def test_large_queue(self):
        r = self.a.analyze(50_000.0, 200_000_000.0, 80_000_000.0)
        self.assertEqual(r.days_to_process, 2.5)

    def test_empty_queue_zero(self):
        r = self.a.analyze(100.0, 0.0, 100.0)
        self.assertEqual(r.days_to_process, 0.0)

    def test_queue_ahead_equals_total(self):
        r = self.a.analyze(100.0, 777.0, 100.0)
        self.assertEqual(r.queue_ahead_usd, 777.0)


class TestLiquidityCoverage(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_full_coverage(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=100.0)
        self.assertEqual(r.liquidity_coverage_ratio, 1.0)

    def test_over_coverage(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=250.0)
        self.assertEqual(r.liquidity_coverage_ratio, 2.5)

    def test_under_coverage(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=40.0)
        self.assertEqual(r.liquidity_coverage_ratio, 0.4)

    def test_zero_available(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=0.0)
        self.assertEqual(r.liquidity_coverage_ratio, 0.0)

    def test_under_coverage_advisory(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=40.0)
        self.assertTrue(any("does not cover" in x for x in r.advisory))

    def test_full_coverage_no_advisory(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=100.0)
        self.assertFalse(any("does not cover" in x for x in r.advisory))

    def test_zero_available_advisory(self):
        r = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=0.0)
        self.assertTrue(any("does not cover" in x for x in r.advisory))

    def test_min_coverage_constant(self):
        self.assertEqual(MIN_LIQUIDITY_COVERAGE, 1.0)


class TestPositionPctOfQueue(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_half(self):
        r = self.a.analyze(100.0, 100.0, 100.0)
        self.assertEqual(r.position_pct_of_queue, 0.5)

    def test_small_fraction(self):
        r = self.a.analyze(100.0, 900.0, 100.0)
        self.assertEqual(r.position_pct_of_queue, 0.1)

    def test_empty_queue_full_pct(self):
        r = self.a.analyze(100.0, 0.0, 100.0)
        self.assertEqual(r.position_pct_of_queue, 1.0)

    def test_large_queue_tiny_pct(self):
        r = self.a.analyze(100.0, 9900.0, 100.0)
        self.assertEqual(r.position_pct_of_queue, 0.01)


class TestSlowExitWarning(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_warn_over_14_days(self):
        r = self.a.analyze(100.0, 2000.0, 100.0)
        self.assertTrue(any("exit horizon" in x for x in r.advisory))

    def test_no_warn_under_14(self):
        r = self.a.analyze(100.0, 500.0, 100.0)
        self.assertFalse(any("exit horizon" in x for x in r.advisory))

    def test_no_warn_at_14(self):
        r = self.a.analyze(100.0, 1400.0, 100.0)
        self.assertFalse(any("exit horizon" in x for x in r.advisory))

    def test_frozen_no_horizon_warn(self):
        r = self.a.analyze(100.0, 1000.0, 0.0)
        self.assertFalse(any("exit horizon" in x for x in r.advisory))


class TestAdvisoryContent(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_immediate_msg(self):
        r = self.a.analyze(100.0, 50.0, 100.0, available_liquidity_usd=200.0)
        self.assertTrue(any("immediate" in x.lower() for x in r.advisory))

    def test_fast_msg(self):
        r = self.a.analyze(100.0, 200.0, 100.0, available_liquidity_usd=200.0)
        self.assertTrue(any("fast" in x.lower() for x in r.advisory))

    def test_slow_msg(self):
        r = self.a.analyze(100.0, 1000.0, 100.0, available_liquidity_usd=200.0)
        self.assertTrue(any("slow" in x.lower() for x in r.advisory))

    def test_congested_msg(self):
        r = self.a.analyze(100.0, 3000.0, 100.0, available_liquidity_usd=200.0)
        self.assertTrue(any("congested" in x.lower() for x in r.advisory))

    def test_advisory_nonempty(self):
        r = self.a.analyze(100.0, 200.0, 100.0)
        self.assertGreaterEqual(len(r.advisory), 1)


class TestFields(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_label_propagated(self):
        r = self.a.analyze(100.0, 200.0, 100.0, label="stETH")
        self.assertEqual(r.label, "stETH")

    def test_generated_at_z(self):
        r = self.a.analyze(100.0, 200.0, 100.0)
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_position_recorded(self):
        r = self.a.analyze(123.45, 200.0, 100.0)
        self.assertEqual(r.position_size_usd, 123.45)

    def test_queue_recorded(self):
        r = self.a.analyze(100.0, 250.0, 100.0)
        self.assertEqual(r.queue_total_usd, 250.0)

    def test_daily_recorded(self):
        r = self.a.analyze(100.0, 200.0, 99.0)
        self.assertEqual(r.daily_processing_usd, 99.0)

    def test_cooldown_recorded(self):
        r = self.a.analyze(100.0, 200.0, 100.0, cooldown_days=3.5)
        self.assertEqual(r.cooldown_days, 3.5)

    def test_available_recorded(self):
        r = self.a.analyze(100.0, 200.0, 100.0, available_liquidity_usd=55.0)
        self.assertEqual(r.available_liquidity_usd, 55.0)

    def test_tier_in_known_set(self):
        r = self.a.analyze(100.0, 200.0, 100.0)
        self.assertIn(
            r.tier,
            {"IMMEDIATE", "FAST", "SLOW", "CONGESTED", "FROZEN", "UNKNOWN"},
        )


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_same_inputs_same_tier(self):
        r1 = self.a.analyze(100.0, 500.0, 100.0, cooldown_days=2.0)
        r2 = self.a.analyze(100.0, 500.0, 100.0, cooldown_days=2.0)
        self.assertEqual(r1.tier, r2.tier)

    def test_same_inputs_same_est_days(self):
        r1 = self.a.analyze(100.0, 500.0, 100.0)
        r2 = self.a.analyze(100.0, 500.0, 100.0)
        self.assertEqual(r1.estimated_days_to_exit, r2.estimated_days_to_exit)

    def test_same_inputs_same_coverage(self):
        r1 = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=80.0)
        r2 = self.a.analyze(100.0, 0.0, 100.0, available_liquidity_usd=80.0)
        self.assertEqual(
            r1.liquidity_coverage_ratio, r2.liquidity_coverage_ratio
        )


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_coverage_6dp(self):
        r = self.a.analyze(3.0, 0.0, 1.0, available_liquidity_usd=1.0)
        self.assertEqual(r.liquidity_coverage_ratio, round(1.0 / 3.0, 6))

    def test_pct_6dp(self):
        r = self.a.analyze(1.0, 2.0, 1.0)
        self.assertEqual(r.position_pct_of_queue, round(1.0 / 3.0, 6))

    def test_days_to_process_4dp(self):
        r = self.a.analyze(100.0, 1.0, 3.0)
        self.assertEqual(r.days_to_process, round(1.0 / 3.0, 4))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "wq.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.a.load_history(self.path), [])

    def test_save_then_load(self):
        self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        e = self.a.load_history(self.path)[0]
        self.assertIn("tier", e)
        self.assertIn("estimated_days_to_exit", e)
        self.assertIn("advisory", e)
        self.assertIn("liquidity_coverage_ratio", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        self.assertEqual(len(self.a.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.a.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "wq.json"
        self.a.save_report(self.a.analyze(100.0, 200.0, 100.0), nested)
        self.assertTrue(nested.exists())

    def test_save_unknown_report(self):
        self.a.save_report(self.a.analyze(0.0, 200.0, 100.0), self.path)
        e = self.a.load_history(self.path)[0]
        self.assertEqual(e["tier"], "UNKNOWN")

    def test_save_frozen_report(self):
        self.a.save_report(self.a.analyze(100.0, 500.0, 0.0), self.path)
        e = self.a.load_history(self.path)[0]
        self.assertEqual(e["tier"], "FROZEN")
        self.assertIsNone(e["estimated_days_to_exit"])


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.a = WithdrawalQueueRiskAnalyzer()

    def test_steth_like(self):
        r = self.a.analyze(
            50_000.0, 200_000_000.0, 80_000_000.0,
            cooldown_days=0.0, available_liquidity_usd=30_000.0, label="stETH",
        )
        self.assertEqual(r.days_to_process, 2.5)
        self.assertEqual(r.tier, "FAST")
        self.assertLess(r.liquidity_coverage_ratio, 1.0)

    def test_susde_cooldown_like(self):
        # sUSDe 7-day cooldown, ample processing
        r = self.a.analyze(
            10_000.0, 0.0, 1_000_000.0, cooldown_days=7.0,
            available_liquidity_usd=0.0, label="sUSDe",
        )
        self.assertEqual(r.estimated_days_to_exit, 7.0)
        self.assertEqual(r.tier, "SLOW")

    def test_frozen_protocol(self):
        r = self.a.analyze(5000.0, 1_000_000.0, 0.0, label="halted")
        self.assertEqual(r.tier, "FROZEN")
        self.assertTrue(len(r.advisory) >= 1)

    def test_healthy_immediate(self):
        r = self.a.analyze(
            1000.0, 100.0, 10_000.0, available_liquidity_usd=5000.0
        )
        self.assertEqual(r.tier, "IMMEDIATE")
        self.assertGreaterEqual(r.liquidity_coverage_ratio, 1.0)

    def test_tier_known_set_full(self):
        r = self.a.analyze(100.0, 5000.0, 100.0)
        self.assertIn(
            r.tier, {"IMMEDIATE", "FAST", "SLOW", "CONGESTED", "FROZEN", "UNKNOWN"}
        )


if __name__ == "__main__":
    unittest.main()
