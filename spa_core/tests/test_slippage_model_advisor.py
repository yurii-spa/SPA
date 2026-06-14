"""Tests for spa_core/analytics/slippage_model_advisor.py — MP-650.

≥ 60 tests covering:
  * SlippageEstimate dataclass
  * Module-level constants
  * SlippageModelAdvisor._slippage_bps
  * SlippageModelAdvisor._grade
  * SlippageModelAdvisor._recommendation
  * SlippageModelAdvisor.estimate  (correctness, edge cases)
  * SlippageModelAdvisor.estimate_batch
  * SlippageModelAdvisor.worst_slippage
  * SlippageModelAdvisor.total_cost_usd
  * SlippageModelAdvisor.save_estimates  (ring-buffer + atomic write)
  * SlippageModelAdvisor.load_history
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.slippage_model_advisor import (
    SLIPPAGE_CONST,
    MAX_SLIPPAGE_BPS,
    MIN_TVL,
    MAX_ENTRIES,
    GRADE_A_MAX,
    GRADE_B_MAX,
    GRADE_C_MAX,
    PROCEED_MAX,
    SPLIT_MAX,
    SPLIT_MIN_TRANCHES,
    SPLIT_MAX_TRANCHES,
    SlippageEstimate,
    SlippageModelAdvisor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_advisor(tmp_dir: str) -> SlippageModelAdvisor:
    return SlippageModelAdvisor(
        data_file=Path(tmp_dir) / "slippage_advisory_log.json"
    )


def _make_estimate(
    adapter_id: str = "a1",
    protocol: str = "TestP",
    trade: float = 1_000.0,
    tvl: float = 1_000_000.0,
) -> SlippageEstimate:
    return SlippageModelAdvisor().estimate(adapter_id, protocol, trade, tvl)


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_slippage_const(self):
        self.assertAlmostEqual(SLIPPAGE_CONST, 0.002)

    def test_max_slippage_bps(self):
        self.assertAlmostEqual(MAX_SLIPPAGE_BPS, 200.0)

    def test_min_tvl(self):
        self.assertAlmostEqual(MIN_TVL, 1.0)

    def test_max_entries(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_grade_boundaries_ordering(self):
        self.assertLess(GRADE_A_MAX, GRADE_B_MAX)
        self.assertLess(GRADE_B_MAX, GRADE_C_MAX)

    def test_recommendation_boundaries_ordering(self):
        self.assertLess(PROCEED_MAX, SPLIT_MAX)

    def test_tranche_limits(self):
        self.assertEqual(SPLIT_MIN_TRANCHES, 2)
        self.assertEqual(SPLIT_MAX_TRANCHES, 4)


# ---------------------------------------------------------------------------
# Test _slippage_bps
# ---------------------------------------------------------------------------

class TestSlippageBps(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_tvl_zero_returns_zero(self):
        self.assertEqual(self.adv._slippage_bps(10_000, 0.0), 0.0)

    def test_trade_zero_returns_zero(self):
        self.assertEqual(self.adv._slippage_bps(0.0, 1_000_000), 0.0)

    def test_trade_negative_returns_zero(self):
        self.assertEqual(self.adv._slippage_bps(-100, 1_000_000), 0.0)

    def test_tvl_below_min_tvl_returns_zero(self):
        self.assertEqual(self.adv._slippage_bps(1_000, 0.5), 0.0)

    def test_tvl_exactly_min_tvl(self):
        # tvl=1.0 >= MIN_TVL → compute (not return 0)
        val = self.adv._slippage_bps(0.01, MIN_TVL)
        self.assertGreater(val, 0.0)

    def test_small_trade_large_tvl_near_zero(self):
        # 1 000 / 500 000 000 = 2e-6; sqrt very small → tiny bps
        val = self.adv._slippage_bps(1_000, 500_000_000)
        self.assertLess(val, 1.0)

    def test_trade_equals_tvl_gives_20_bps(self):
        # trade/tvl = 1.0; sqrt(1)=1; 0.002 * 1 * 10000 = 20 bps
        val = self.adv._slippage_bps(100_000, 100_000)
        self.assertAlmostEqual(val, 20.0, places=4)

    def test_cap_at_max_slippage_bps(self):
        # Very large trade relative to TVL → should cap at 200
        val = self.adv._slippage_bps(1_000_000, 1_000)
        self.assertEqual(val, MAX_SLIPPAGE_BPS)

    def test_sqrt_model_formula(self):
        trade, tvl = 10_000.0, 1_000_000.0
        expected = SLIPPAGE_CONST * math.sqrt(trade / tvl) * 10_000
        self.assertAlmostEqual(self.adv._slippage_bps(trade, tvl), expected, places=6)

    def test_result_non_negative(self):
        for trade, tvl in [(100, 1_000_000), (0, 1_000_000), (1_000, 0)]:
            self.assertGreaterEqual(self.adv._slippage_bps(trade, tvl), 0.0)


# ---------------------------------------------------------------------------
# Test _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_grade_a_below_5(self):
        self.assertEqual(self.adv._grade(0.0), "A")
        self.assertEqual(self.adv._grade(4.99), "A")

    def test_grade_a_boundary_exactly_5(self):
        # 5.0 is NOT < 5 → should be B
        self.assertEqual(self.adv._grade(5.0), "B")

    def test_grade_b_range(self):
        self.assertEqual(self.adv._grade(5.0), "B")
        self.assertEqual(self.adv._grade(10.0), "B")
        self.assertEqual(self.adv._grade(14.99), "B")

    def test_grade_b_boundary_exactly_15(self):
        self.assertEqual(self.adv._grade(15.0), "C")

    def test_grade_c_range(self):
        self.assertEqual(self.adv._grade(15.0), "C")
        self.assertEqual(self.adv._grade(25.0), "C")
        self.assertEqual(self.adv._grade(29.99), "C")

    def test_grade_c_boundary_exactly_30(self):
        self.assertEqual(self.adv._grade(30.0), "D")

    def test_grade_d_range(self):
        self.assertEqual(self.adv._grade(30.0), "D")
        self.assertEqual(self.adv._grade(100.0), "D")
        self.assertEqual(self.adv._grade(200.0), "D")


# ---------------------------------------------------------------------------
# Test _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_proceed_for_low_bps(self):
        rec, tranches = self.adv._recommendation(5.0, 0.001)
        self.assertEqual(rec, "PROCEED")
        self.assertIsNone(tranches)

    def test_proceed_just_below_threshold(self):
        rec, tranches = self.adv._recommendation(PROCEED_MAX - 0.01, 0.001)
        self.assertEqual(rec, "PROCEED")
        self.assertIsNone(tranches)

    def test_split_at_exactly_proceed_max(self):
        # bps == PROCEED_MAX is NOT < PROCEED_MAX → SPLIT
        rec, tranches = self.adv._recommendation(PROCEED_MAX, 0.05)
        self.assertEqual(rec, "SPLIT")
        self.assertIsNotNone(tranches)

    def test_split_returns_int_tranches(self):
        _, tranches = self.adv._recommendation(20.0, 0.05)
        self.assertIsInstance(tranches, int)

    def test_split_tranches_in_range(self):
        for bps in (16.0, 25.0, 40.0):
            for pct in (0.01, 0.05, 0.10, 0.20, 0.50):
                _, tranches = self.adv._recommendation(bps, pct)
                self.assertGreaterEqual(tranches, SPLIT_MIN_TRANCHES)
                self.assertLessEqual(tranches, SPLIT_MAX_TRANCHES)

    def test_avoid_at_exactly_split_max(self):
        rec, tranches = self.adv._recommendation(SPLIT_MAX, 0.10)
        self.assertEqual(rec, "AVOID")
        self.assertIsNone(tranches)

    def test_avoid_high_bps(self):
        rec, tranches = self.adv._recommendation(150.0, 0.50)
        self.assertEqual(rec, "AVOID")
        self.assertIsNone(tranches)

    def test_avoid_at_max_slippage(self):
        rec, tranches = self.adv._recommendation(MAX_SLIPPAGE_BPS, 1.0)
        self.assertEqual(rec, "AVOID")
        self.assertIsNone(tranches)


# ---------------------------------------------------------------------------
# Test estimate
# ---------------------------------------------------------------------------

class TestEstimate(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_basic_correctness_grade_a(self):
        # trade=1 000, tvl=100 000 → pct=0.01, bps=0.002*sqrt(0.01)*10000=2.0 bps → A
        e = self.adv.estimate("aave", "Aave", 1_000.0, 100_000.0)
        self.assertAlmostEqual(e.estimated_slippage_bps, 2.0, places=4)
        self.assertEqual(e.grade, "A")

    def test_trade_pct_of_tvl_correct(self):
        e = self.adv.estimate("a", "P", 5_000, 100_000)
        self.assertAlmostEqual(e.trade_pct_of_tvl, 0.05, places=6)

    def test_cost_usd_equals_trade_times_bps_over_10000(self):
        e = self.adv.estimate("a", "P", 1_000, 100_000)
        expected_cost = round(e.trade_size_usd * (e.estimated_slippage_bps / 10_000), 4)
        self.assertAlmostEqual(e.slippage_cost_usd, expected_cost, places=4)

    def test_tvl_below_min_tvl_slippage_zero(self):
        e = self.adv.estimate("a", "P", 1_000, 0.5)
        self.assertEqual(e.estimated_slippage_bps, 0.0)
        self.assertEqual(e.slippage_cost_usd, 0.0)

    def test_tvl_zero_slippage_zero(self):
        e = self.adv.estimate("a", "P", 1_000, 0.0)
        self.assertEqual(e.estimated_slippage_bps, 0.0)

    def test_result_fields_populated(self):
        e = self.adv.estimate("my_adapter", "MyProtocol", 5_000, 1_000_000)
        self.assertEqual(e.adapter_id, "my_adapter")
        self.assertEqual(e.protocol, "MyProtocol")
        self.assertIsInstance(e.grade, str)
        self.assertIn(e.recommendation, ("PROCEED", "SPLIT", "AVOID"))

    def test_large_trade_avoidance_recommendation(self):
        # pct = 50 000 / 5 000 = 10; bps = 0.002 * sqrt(10) * 10000 ≈ 63 bps → AVOID
        e = self.adv.estimate("a", "P", 50_000, 5_000)
        self.assertEqual(e.recommendation, "AVOID")
        self.assertIsNone(e.split_tranches)

    def test_medium_trade_split_recommendation(self):
        # Choose a trade that puts bps in [15, 50) range
        # bps = 0.002 * sqrt(pct) * 10000; target ~20 bps → pct ~ 1.0 → trade=tvl
        e = self.adv.estimate("a", "P", 50_000, 50_000)
        # bps = 20.0 → SPLIT
        self.assertEqual(e.recommendation, "SPLIT")
        self.assertIsNotNone(e.split_tranches)

    def test_small_trade_proceed_recommendation(self):
        e = self.adv.estimate("a", "P", 100, 10_000_000)
        self.assertEqual(e.recommendation, "PROCEED")
        self.assertIsNone(e.split_tranches)

    def test_trade_size_rounded_to_2dp(self):
        e = self.adv.estimate("a", "P", 1234.567, 1_000_000)
        self.assertEqual(e.trade_size_usd, round(1234.567, 2))

    def test_tvl_rounded_to_2dp(self):
        e = self.adv.estimate("a", "P", 1_000, 999_999.999)
        self.assertEqual(e.tvl_usd, round(999_999.999, 2))

    def test_slippage_bps_rounded_to_4dp(self):
        e = self.adv.estimate("a", "P", 1_000, 100_000)
        self.assertEqual(e.estimated_slippage_bps, round(e.estimated_slippage_bps, 4))

    def test_result_is_slippage_estimate(self):
        e = self.adv.estimate("a", "P", 1_000, 1_000_000)
        self.assertIsInstance(e, SlippageEstimate)


# ---------------------------------------------------------------------------
# Test estimate_batch
# ---------------------------------------------------------------------------

class TestEstimateBatch(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_empty_list_returns_empty(self):
        self.assertEqual(self.adv.estimate_batch([]), [])

    def test_single_entry(self):
        result = self.adv.estimate_batch([
            {"adapter_id": "a", "protocol": "P", "trade_size_usd": 1_000, "tvl_usd": 1_000_000},
        ])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], SlippageEstimate)

    def test_multiple_entries(self):
        data = [
            {"adapter_id": f"a{i}", "protocol": f"P{i}", "trade_size_usd": i * 1000, "tvl_usd": 1_000_000}
            for i in range(1, 6)
        ]
        result = self.adv.estimate_batch(data)
        self.assertEqual(len(result), 5)

    def test_batch_matches_individual(self):
        data = [
            {"adapter_id": "a", "protocol": "P", "trade_size_usd": 5_000, "tvl_usd": 500_000},
            {"adapter_id": "b", "protocol": "Q", "trade_size_usd": 20_000, "tvl_usd": 200_000},
        ]
        batch = self.adv.estimate_batch(data)
        for i, d in enumerate(data):
            single = self.adv.estimate(d["adapter_id"], d["protocol"], d["trade_size_usd"], d["tvl_usd"])
            self.assertAlmostEqual(batch[i].estimated_slippage_bps, single.estimated_slippage_bps)

    def test_result_types(self):
        data = [{"adapter_id": "x", "protocol": "Y", "trade_size_usd": 1_000, "tvl_usd": 1_000_000}]
        result = self.adv.estimate_batch(data)
        self.assertIsInstance(result[0], SlippageEstimate)


# ---------------------------------------------------------------------------
# Test worst_slippage / total_cost_usd
# ---------------------------------------------------------------------------

class TestAggregators(unittest.TestCase):

    def setUp(self):
        self.adv = SlippageModelAdvisor()

    def test_worst_slippage_empty_returns_none(self):
        self.assertIsNone(self.adv.worst_slippage([]))

    def test_worst_slippage_single_item(self):
        e = _make_estimate(trade=1_000, tvl=1_000_000)
        self.assertEqual(self.adv.worst_slippage([e]), e)

    def test_worst_slippage_picks_highest_bps(self):
        e_small = _make_estimate("a1", trade=1_000,   tvl=1_000_000)
        e_large = _make_estimate("a2", trade=100_000, tvl=100_000)
        result = self.adv.worst_slippage([e_small, e_large])
        self.assertEqual(result.adapter_id, "a2")

    def test_worst_slippage_ordering_invariant(self):
        e1 = _make_estimate("a1", trade=5_000, tvl=50_000)
        e2 = _make_estimate("a2", trade=500,   tvl=1_000_000)
        e3 = _make_estimate("a3", trade=50_000, tvl=100_000)
        for perm in ([e1, e2, e3], [e3, e1, e2], [e2, e3, e1]):
            worst = self.adv.worst_slippage(perm)
            self.assertGreaterEqual(
                worst.estimated_slippage_bps,
                max(x.estimated_slippage_bps for x in perm) - 1e-9,
            )

    def test_total_cost_usd_empty_returns_zero(self):
        self.assertEqual(self.adv.total_cost_usd([]), 0.0)

    def test_total_cost_usd_sums_correctly(self):
        estimates = [
            _make_estimate("a", trade=1_000, tvl=1_000_000),
            _make_estimate("b", trade=5_000, tvl=500_000),
        ]
        expected = round(sum(e.slippage_cost_usd for e in estimates), 4)
        self.assertAlmostEqual(self.adv.total_cost_usd(estimates), expected, places=4)

    def test_total_cost_usd_single_item(self):
        e = _make_estimate(trade=10_000, tvl=200_000)
        self.assertAlmostEqual(self.adv.total_cost_usd([e]), e.slippage_cost_usd, places=4)


# ---------------------------------------------------------------------------
# Test save_estimates / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def test_load_history_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            self.assertEqual(adv.load_history(), [])

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            adv.save_estimates([_make_estimate()])
            self.assertTrue(adv.data_file.exists())

    def test_save_one_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            e = _make_estimate("aave", "Aave")
            adv.save_estimates([e])
            history = adv.load_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["adapter_id"], "aave")

    def test_save_multiple_estimates(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            estimates = [_make_estimate(f"a{i}") for i in range(5)]
            adv.save_estimates(estimates)
            self.assertEqual(len(adv.load_history()), 5)

    def test_ring_buffer_max_entries(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            for _ in range(MAX_ENTRIES + 15):
                adv.save_estimates([_make_estimate()])
            self.assertEqual(len(adv.load_history()), MAX_ENTRIES)

    def test_atomic_no_tmp_file_after_save(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            adv.save_estimates([_make_estimate()])
            tmp = adv.data_file.with_suffix(".tmp")
            self.assertFalse(tmp.exists())

    def test_save_stores_required_keys(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            adv.save_estimates([_make_estimate()])
            entry = adv.load_history()[0]
            for key in ("timestamp", "adapter_id", "estimated_slippage_bps", "grade", "recommendation"):
                self.assertIn(key, entry)

    def test_load_history_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            adv.data_file.parent.mkdir(parents=True, exist_ok=True)
            adv.data_file.write_text("{bad json{{")
            self.assertEqual(adv.load_history(), [])

    def test_save_empty_list_creates_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            adv = _make_advisor(d)
            adv.save_estimates([])
            history = adv.load_history()
            self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
