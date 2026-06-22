"""Tests for GasOptimizationEngine (MP-700).

≥ 65 test methods covering:
- build_quotes ordering and structure
- CRITICAL/HIGH/NORMAL/LOW urgency selection & recommendations
- l2_savings_pct formula
- batch_savings_pct
- optimal_window thresholds
- compare_strategies structure and costs
- save/load round-trip
- ring-buffer cap
- edge cases (0 base_fee, 0 gas_units, 0 eth_price)
- reasoning non-empty for all urgency levels
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.gas_optimization_engine import (
    BLOCK_SLOW,
    CONF_FAST,
    MAX_ENTRIES,
    TIP_FAST,
    TIP_NORMAL,
    TIP_SLOW,
    GasOptimizationEngine,
    GasQuote,
    _result_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine(tmp_dir: str) -> GasOptimizationEngine:
    return GasOptimizationEngine(data_dir=tmp_dir)


def _basic_optimize(engine, urgency="NORMAL", base_fee=30.0, eth_price=3000.0, gas_units=150_000):
    return engine.optimize("swap", urgency, base_fee, eth_price, gas_units)


# ---------------------------------------------------------------------------
# 1. build_quotes — structure & ordering
# ---------------------------------------------------------------------------

class TestBuildQuotes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_returns_exactly_three_quotes(self):
        quotes = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertEqual(len(quotes), 3)

    def test_quotes_are_gas_quote_instances(self):
        for q in self.engine.build_quotes(30.0, 3000.0, "NORMAL"):
            self.assertIsInstance(q, GasQuote)

    def test_slow_has_lowest_tip(self):
        slow, normal, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertLess(slow.priority_fee_gwei, normal.priority_fee_gwei)
        self.assertLess(normal.priority_fee_gwei, fast.priority_fee_gwei)

    def test_slow_has_lowest_max_fee(self):
        slow, normal, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertLess(slow.max_fee_gwei, normal.max_fee_gwei)
        self.assertLess(normal.max_fee_gwei, fast.max_fee_gwei)

    def test_slow_tip_value(self):
        slow, _, _ = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertAlmostEqual(slow.priority_fee_gwei, TIP_SLOW)

    def test_normal_tip_value(self):
        _, normal, _ = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertAlmostEqual(normal.priority_fee_gwei, TIP_NORMAL)

    def test_fast_tip_value(self):
        _, _, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertAlmostEqual(fast.priority_fee_gwei, TIP_FAST)

    def test_max_fee_formula(self):
        base = 40.0
        slow, normal, fast = self.engine.build_quotes(base, 3000.0, "NORMAL")
        self.assertAlmostEqual(slow.max_fee_gwei, base * 2 + TIP_SLOW)
        self.assertAlmostEqual(normal.max_fee_gwei, base * 2 + TIP_NORMAL)
        self.assertAlmostEqual(fast.max_fee_gwei, base * 2 + TIP_FAST)

    def test_slow_has_block_target_2(self):
        slow, _, _ = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertEqual(slow.block_target, BLOCK_SLOW)

    def test_fast_has_highest_confidence(self):
        slow, normal, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertGreater(fast.confidence, normal.confidence)
        self.assertGreater(normal.confidence, slow.confidence)

    def test_fast_confidence_value(self):
        _, _, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertAlmostEqual(fast.confidence, CONF_FAST)

    def test_estimated_cost_positive_when_price_nonzero(self):
        for q in self.engine.build_quotes(30.0, 3000.0, "NORMAL"):
            self.assertGreater(q.estimated_cost_usd, 0)

    def test_estimated_cost_zero_when_eth_price_zero(self):
        for q in self.engine.build_quotes(30.0, 0.0, "NORMAL"):
            self.assertEqual(q.estimated_cost_usd, 0.0)

    def test_cost_increases_with_tip(self):
        slow, normal, fast = self.engine.build_quotes(30.0, 3000.0, "NORMAL")
        self.assertLess(slow.estimated_cost_usd, normal.estimated_cost_usd)
        self.assertLess(normal.estimated_cost_usd, fast.estimated_cost_usd)


# ---------------------------------------------------------------------------
# 2. CRITICAL urgency
# ---------------------------------------------------------------------------

class TestCriticalUrgency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_critical_selects_fast_quote(self):
        result = self.engine.optimize("deposit", "CRITICAL", 50.0, 3000.0, 200_000)
        _, _, fast = self.engine.build_quotes(50.0, 3000.0, "CRITICAL", 200_000)
        self.assertAlmostEqual(result.selected_quote.max_fee_gwei, fast.max_fee_gwei)

    def test_critical_recommendation_use_now(self):
        result = _basic_optimize(self.engine, "CRITICAL", base_fee=200.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_critical_recommendation_use_now_low_gas(self):
        result = _basic_optimize(self.engine, "CRITICAL", base_fee=5.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_critical_has_reasoning(self):
        result = _basic_optimize(self.engine, "CRITICAL", base_fee=50.0)
        self.assertGreater(len(result.reasoning), 0)

    def test_critical_batch_savings_zero(self):
        result = _basic_optimize(self.engine, "CRITICAL", base_fee=50.0)
        self.assertEqual(result.batch_savings_pct, 0.0)

    def test_critical_urgency_stored_correctly(self):
        result = _basic_optimize(self.engine, "CRITICAL")
        self.assertEqual(result.urgency, "CRITICAL")


# ---------------------------------------------------------------------------
# 3. HIGH urgency
# ---------------------------------------------------------------------------

class TestHighUrgency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_high_low_base_fee_use_now(self):
        result = _basic_optimize(self.engine, "HIGH", base_fee=30.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_high_above_threshold_wait_low(self):
        result = _basic_optimize(self.engine, "HIGH", base_fee=90.0)
        self.assertEqual(result.selected_quote.recommendation, "WAIT_LOW")

    def test_high_exactly_at_threshold_still_use_now(self):
        # base_fee == 80 → NOT > 80 → USE_NOW
        result = _basic_optimize(self.engine, "HIGH", base_fee=80.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_high_batch_savings_zero(self):
        result = _basic_optimize(self.engine, "HIGH", base_fee=50.0)
        self.assertEqual(result.batch_savings_pct, 0.0)

    def test_high_reasoning_nonempty(self):
        result = _basic_optimize(self.engine, "HIGH", base_fee=100.0)
        self.assertGreater(len(result.reasoning), 0)


# ---------------------------------------------------------------------------
# 4. NORMAL urgency
# ---------------------------------------------------------------------------

class TestNormalUrgency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_normal_low_gas_use_now(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=20.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_normal_medium_gas_wait_low(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=60.0)
        self.assertEqual(result.selected_quote.recommendation, "WAIT_LOW")

    def test_normal_high_gas_use_l2(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=120.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_L2")

    def test_normal_exactly_100_use_l2(self):
        # 100 > 100 is False → WAIT_LOW
        result = _basic_optimize(self.engine, "NORMAL", base_fee=100.0)
        self.assertEqual(result.selected_quote.recommendation, "WAIT_LOW")

    def test_normal_101_use_l2(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=101.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_L2")

    def test_normal_batch_savings_15(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=30.0)
        self.assertAlmostEqual(result.batch_savings_pct, 15.0)

    def test_normal_reasoning_nonempty(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=30.0)
        self.assertGreater(len(result.reasoning), 0)


# ---------------------------------------------------------------------------
# 5. LOW urgency
# ---------------------------------------------------------------------------

class TestLowUrgency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_low_high_gas_batch_later(self):
        result = _basic_optimize(self.engine, "LOW", base_fee=50.0)
        self.assertEqual(result.selected_quote.recommendation, "BATCH_LATER")

    def test_low_low_gas_use_now(self):
        result = _basic_optimize(self.engine, "LOW", base_fee=10.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_low_exactly_30_use_now(self):
        # 30 > 30 is False → USE_NOW
        result = _basic_optimize(self.engine, "LOW", base_fee=30.0)
        self.assertEqual(result.selected_quote.recommendation, "USE_NOW")

    def test_low_selects_slow_quote(self):
        result = self.engine.optimize("harvest", "LOW", 50.0, 3000.0, 150_000)
        slow, _, _ = self.engine.build_quotes(50.0, 3000.0, "LOW", 150_000)
        self.assertAlmostEqual(result.selected_quote.priority_fee_gwei, slow.priority_fee_gwei)

    def test_low_batch_savings_15(self):
        result = _basic_optimize(self.engine, "LOW", base_fee=50.0)
        self.assertAlmostEqual(result.batch_savings_pct, 15.0)

    def test_low_reasoning_nonempty(self):
        result = _basic_optimize(self.engine, "LOW", base_fee=50.0)
        self.assertGreater(len(result.reasoning), 0)


# ---------------------------------------------------------------------------
# 6. l2_savings_pct formula
# ---------------------------------------------------------------------------

class TestL2Savings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_below_threshold_zero(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=30.0)
        self.assertEqual(result.l2_savings_pct, 0.0)

    def test_at_threshold_zero(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=40.0)
        self.assertEqual(result.l2_savings_pct, 0.0)

    def test_base_fee_50_formula(self):
        # (50 - 2) / 50 * 100 = 96.0, capped to 95.0
        pct = self.engine._l2_savings_pct(50.0)
        expected = min(95.0, (50.0 - 2.0) / 50.0 * 100.0)
        self.assertAlmostEqual(pct, expected, places=4)

    def test_base_fee_100_formula(self):
        pct = self.engine._l2_savings_pct(100.0)
        expected = min(95.0, (100.0 - 2.0) / 100.0 * 100.0)
        self.assertAlmostEqual(pct, expected, places=4)

    def test_base_fee_200_capped_at_95(self):
        pct = self.engine._l2_savings_pct(200.0)
        self.assertLessEqual(pct, 95.0)

    def test_base_fee_41_above_zero(self):
        pct = self.engine._l2_savings_pct(41.0)
        self.assertGreater(pct, 0.0)

    def test_l2_savings_in_result_matches_helper(self):
        base = 80.0
        result = _basic_optimize(self.engine, "NORMAL", base_fee=base)
        self.assertAlmostEqual(result.l2_savings_pct, self.engine._l2_savings_pct(base), places=4)


# ---------------------------------------------------------------------------
# 7. batch_savings_pct
# ---------------------------------------------------------------------------

class TestBatchSavings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_critical_batch_zero(self):
        self.assertEqual(self.engine._batch_savings_pct("CRITICAL"), 0.0)

    def test_high_batch_zero(self):
        self.assertEqual(self.engine._batch_savings_pct("HIGH"), 0.0)

    def test_normal_batch_15(self):
        self.assertAlmostEqual(self.engine._batch_savings_pct("NORMAL"), 15.0)

    def test_low_batch_15(self):
        self.assertAlmostEqual(self.engine._batch_savings_pct("LOW"), 15.0)


# ---------------------------------------------------------------------------
# 8. optimal_window thresholds
# ---------------------------------------------------------------------------

class TestOptimalWindow(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_very_low_now(self):
        self.assertEqual(self.engine._optimal_window(10.0), "NOW")

    def test_below_now_threshold(self):
        self.assertEqual(self.engine._optimal_window(19.9), "NOW")

    def test_exactly_20_next_30min(self):
        self.assertEqual(self.engine._optimal_window(20.0), "NEXT_30MIN")

    def test_30_next_30min(self):
        self.assertEqual(self.engine._optimal_window(30.0), "NEXT_30MIN")

    def test_49_next_30min(self):
        self.assertEqual(self.engine._optimal_window(49.9), "NEXT_30MIN")

    def test_50_next_4h(self):
        self.assertEqual(self.engine._optimal_window(50.0), "NEXT_4H")

    def test_80_next_4h(self):
        self.assertEqual(self.engine._optimal_window(80.0), "NEXT_4H")

    def test_99_next_4h(self):
        self.assertEqual(self.engine._optimal_window(99.9), "NEXT_4H")

    def test_100_weekend(self):
        self.assertEqual(self.engine._optimal_window(100.0), "WEEKEND")

    def test_120_weekend(self):
        self.assertEqual(self.engine._optimal_window(120.0), "WEEKEND")


# ---------------------------------------------------------------------------
# 9. compare_strategies
# ---------------------------------------------------------------------------

class TestCompareStrategies(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_returns_four_strategies(self):
        result = self.engine.compare_strategies(40.0, 3000.0)
        self.assertEqual(len(result), 4)

    def test_all_four_keys_present(self):
        result = self.engine.compare_strategies(40.0, 3000.0)
        for key in ("EXECUTE_NOW", "WAIT", "L2", "BATCH"):
            self.assertIn(key, result)

    def test_l2_cheapest(self):
        result = self.engine.compare_strategies(60.0, 3000.0)
        l2_cost = result["L2"]["estimated_cost_usd"]
        for key in ("EXECUTE_NOW", "WAIT", "BATCH"):
            self.assertLess(l2_cost, result[key]["estimated_cost_usd"])

    def test_all_costs_positive_nonzero(self):
        result = self.engine.compare_strategies(40.0, 3000.0)
        for key, val in result.items():
            self.assertGreater(val["estimated_cost_usd"], 0, f"{key} cost should be > 0")

    def test_batch_cheaper_than_now(self):
        result = self.engine.compare_strategies(40.0, 3000.0)
        self.assertLess(result["BATCH"]["estimated_cost_usd"], result["EXECUTE_NOW"]["estimated_cost_usd"])

    def test_wait_cheaper_than_now(self):
        result = self.engine.compare_strategies(60.0, 3000.0)
        self.assertLess(result["WAIT"]["estimated_cost_usd"], result["EXECUTE_NOW"]["estimated_cost_usd"])

    def test_descriptions_present(self):
        result = self.engine.compare_strategies(40.0, 3000.0)
        for val in result.values():
            self.assertIn("description", val)
            self.assertIsInstance(val["description"], str)
            self.assertGreater(len(val["description"]), 0)

    def test_zero_eth_price_all_zero(self):
        result = self.engine.compare_strategies(40.0, 0.0)
        for val in result.values():
            self.assertEqual(val["estimated_cost_usd"], 0.0)


# ---------------------------------------------------------------------------
# 10. save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_empty_history_returns_empty_list(self):
        self.assertEqual(self.engine.load_history(), [])

    def test_save_and_load_one_result(self):
        result = _basic_optimize(self.engine, "NORMAL", 30.0)
        self.engine.save_results(result)
        history = self.engine.load_history()
        self.assertEqual(len(history), 1)

    def test_saved_entry_has_timestamp(self):
        result = _basic_optimize(self.engine, "NORMAL", 30.0)
        self.engine.save_results(result)
        entry = self.engine.load_history()[0]
        self.assertIn("timestamp", entry)
        self.assertIsInstance(entry["timestamp"], str)

    def test_saved_entry_has_urgency(self):
        result = _basic_optimize(self.engine, "HIGH", 50.0)
        self.engine.save_results(result)
        entry = self.engine.load_history()[0]
        self.assertEqual(entry["urgency"], "HIGH")

    def test_multiple_saves_accumulate(self):
        for bf in [10.0, 20.0, 30.0]:
            self.engine.save_results(_basic_optimize(self.engine, "NORMAL", bf))
        self.assertEqual(len(self.engine.load_history()), 3)

    def test_saved_entry_has_selected_quote(self):
        result = _basic_optimize(self.engine, "CRITICAL", 50.0)
        self.engine.save_results(result)
        entry = self.engine.load_history()[0]
        self.assertIn("selected_quote", entry)
        self.assertIn("max_fee_gwei", entry["selected_quote"])

    def test_saved_entry_has_alternative_quotes(self):
        result = _basic_optimize(self.engine)
        self.engine.save_results(result)
        entry = self.engine.load_history()[0]
        self.assertIn("alternative_quotes", entry)
        self.assertEqual(len(entry["alternative_quotes"]), 3)

    def test_log_file_is_valid_json(self):
        self.engine.save_results(_basic_optimize(self.engine))
        raw = Path(self.tmp, "gas_optimization_log.json").read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, list)


# ---------------------------------------------------------------------------
# 11. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_cap_at_max_entries(self):
        for i in range(MAX_ENTRIES + 10):
            self.engine.save_results(_basic_optimize(self.engine, base_fee=float(i + 1)))
        history = self.engine.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_latest_entries_kept(self):
        for i in range(MAX_ENTRIES + 5):
            r = self.engine.optimize("swap", "NORMAL", float(i + 1), 3000.0, 150_000)
            self.engine.save_results(r)
        history = self.engine.load_history()
        # Last entry should have base_fee = MAX_ENTRIES + 5
        last_bf = history[-1]["selected_quote"]["base_fee_gwei"]
        self.assertAlmostEqual(last_bf, float(MAX_ENTRIES + 5))


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_base_fee_zero(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=0.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.l2_savings_pct, 0.0)

    def test_gas_units_zero(self):
        result = self.engine.optimize("swap", "NORMAL", 30.0, 3000.0, 0)
        for q in result.alternative_quotes:
            self.assertEqual(q.estimated_cost_usd, 0.0)

    def test_eth_price_zero(self):
        result = _basic_optimize(self.engine, "NORMAL", eth_price=0.0)
        self.assertEqual(result.selected_quote.estimated_cost_usd, 0.0)

    def test_very_high_base_fee_capped_l2(self):
        pct = self.engine._l2_savings_pct(10_000.0)
        self.assertLessEqual(pct, 95.0)

    def test_result_always_has_reasoning_critical(self):
        result = _basic_optimize(self.engine, "CRITICAL")
        self.assertGreater(len(result.reasoning), 0)

    def test_result_always_has_reasoning_high(self):
        result = _basic_optimize(self.engine, "HIGH", base_fee=100.0)
        self.assertGreater(len(result.reasoning), 0)

    def test_result_always_has_reasoning_normal(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=60.0)
        self.assertGreater(len(result.reasoning), 0)

    def test_result_always_has_reasoning_low(self):
        result = _basic_optimize(self.engine, "LOW", base_fee=50.0)
        self.assertGreater(len(result.reasoning), 0)

    def test_result_to_dict_has_all_keys(self):
        result = _basic_optimize(self.engine)
        d = _result_to_dict(result)
        for key in ("transaction_type", "urgency", "selected_quote",
                    "alternative_quotes", "l2_savings_pct", "batch_savings_pct",
                    "optimal_window", "reasoning", "saved_to"):
            self.assertIn(key, d)

    def test_transaction_type_stored(self):
        result = self.engine.optimize("harvest", "LOW", 30.0, 3000.0, 100_000)
        self.assertEqual(result.transaction_type, "harvest")

    def test_optimal_window_in_result(self):
        result = _basic_optimize(self.engine, "NORMAL", base_fee=10.0)
        self.assertEqual(result.optimal_window, "NOW")


if __name__ == "__main__":
    unittest.main()
