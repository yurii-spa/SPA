"""
Tests for MP-865 DeFiPositionRebalancingTrigger
Run with: python3 -m unittest spa_core.tests.test_defi_position_rebalancing_trigger
"""
import json
import os
import sys
import time
import unittest
import tempfile

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_position_rebalancing_trigger import (
    analyze,
    log_result,
    _merge_config,
    _compute_position,
    _DEFAULT_CONFIG,
)


def _make_pos(
    protocol="Proto",
    current_pct=30.0,
    target_pct=30.0,
    current_apy=5.0,
    initial_apy=5.0,
    cost=10.0,
    value=30000.0,
):
    return {
        "protocol": protocol,
        "current_allocation_pct": current_pct,
        "target_allocation_pct": target_pct,
        "current_apy_pct": current_apy,
        "initial_apy_pct": initial_apy,
        "rebalance_cost_usd": cost,
        "position_value_usd": value,
    }


class TestMergeConfig(unittest.TestCase):

    def test_defaults_returned_when_none(self):
        cfg = _merge_config(None)
        self.assertEqual(cfg["drift_threshold_pct"], 5.0)
        self.assertEqual(cfg["yield_degradation_threshold"], 0.25)
        self.assertEqual(cfg["max_concentration_pct"], 40.0)

    def test_override_drift_threshold(self):
        cfg = _merge_config({"drift_threshold_pct": 10.0})
        self.assertEqual(cfg["drift_threshold_pct"], 10.0)
        self.assertEqual(cfg["yield_degradation_threshold"], 0.25)

    def test_override_yield_degradation(self):
        cfg = _merge_config({"yield_degradation_threshold": 0.5})
        self.assertEqual(cfg["yield_degradation_threshold"], 0.5)

    def test_override_max_concentration(self):
        cfg = _merge_config({"max_concentration_pct": 50.0})
        self.assertEqual(cfg["max_concentration_pct"], 50.0)

    def test_override_all(self):
        cfg = _merge_config({"drift_threshold_pct": 3.0, "yield_degradation_threshold": 0.1, "max_concentration_pct": 35.0})
        self.assertEqual(cfg["drift_threshold_pct"], 3.0)
        self.assertEqual(cfg["yield_degradation_threshold"], 0.1)
        self.assertEqual(cfg["max_concentration_pct"], 35.0)

    def test_unknown_keys_ignored(self):
        cfg = _merge_config({"unknown_key": 999})
        self.assertEqual(cfg, dict(_DEFAULT_CONFIG))

    def test_string_values_coerced_to_float(self):
        cfg = _merge_config({"drift_threshold_pct": "7.5"})
        self.assertAlmostEqual(cfg["drift_threshold_pct"], 7.5)


class TestEmpty(unittest.TestCase):

    def test_empty_positions_returns_zeros(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        s = result["portfolio_summary"]
        self.assertEqual(s["total_portfolio_value_usd"], 0.0)
        self.assertEqual(s["positions_needing_rebalance"], 0)
        self.assertEqual(s["total_drift_magnitude_pct"], 0.0)
        self.assertIsNone(s["highest_drift_protocol"])
        self.assertEqual(s["total_rebalance_cost_usd"], 0.0)
        self.assertFalse(s["rebalance_recommended"])

    def test_empty_has_timestamp(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAllocationDrift(unittest.TestCase):

    def test_drift_zero_when_on_target(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["allocation_drift_pct"], 0.0)
        self.assertAlmostEqual(p["drift_magnitude_pct"], 0.0)

    def test_positive_drift_overweight(self):
        pos = _make_pos(current_pct=40.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["allocation_drift_pct"], 10.0)
        self.assertAlmostEqual(p["drift_magnitude_pct"], 10.0)

    def test_negative_drift_underweight(self):
        pos = _make_pos(current_pct=20.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["allocation_drift_pct"], -10.0)
        self.assertAlmostEqual(p["drift_magnitude_pct"], 10.0)

    def test_is_overweight_flag(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertTrue(p["is_overweight"])
        self.assertFalse(p["is_underweight"])

    def test_is_underweight_flag(self):
        pos = _make_pos(current_pct=24.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertFalse(p["is_overweight"])
        self.assertTrue(p["is_underweight"])

    def test_exactly_at_threshold_not_overweight(self):
        # drift = exactly 5.0 — NOT > threshold, so NOT overweight
        pos = _make_pos(current_pct=35.0, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertFalse(p["is_overweight"])

    def test_just_above_threshold_is_overweight(self):
        pos = _make_pos(current_pct=35.01, target_pct=30.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertTrue(p["is_overweight"])

    def test_custom_drift_threshold(self):
        pos = _make_pos(current_pct=37.0, target_pct=30.0)
        result = analyze([pos], config={"drift_threshold_pct": 10.0})
        p = result["positions"][0]
        self.assertFalse(p["is_overweight"])


class TestYieldDegradation(unittest.TestCase):

    def test_no_degradation_when_apy_stable(self):
        pos = _make_pos(current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["yield_degradation_pct"], 0.0)
        self.assertFalse(p["yield_degraded"])

    def test_degradation_computed_correctly(self):
        # (5 - 3) / 5 * 100 = 40%
        pos = _make_pos(current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["yield_degradation_pct"], 40.0)

    def test_yield_degraded_flag_true_above_threshold(self):
        # default threshold 25% → degradation 40% → degraded
        pos = _make_pos(current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertTrue(p["yield_degraded"])

    def test_yield_degraded_flag_false_below_threshold(self):
        # (5 - 4) / 5 * 100 = 20% < 25%
        pos = _make_pos(current_apy=4.0, initial_apy=5.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertFalse(p["yield_degraded"])

    def test_initial_apy_zero_no_degradation(self):
        pos = _make_pos(current_apy=5.0, initial_apy=0.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["yield_degradation_pct"], 0.0)
        self.assertFalse(p["yield_degraded"])

    def test_improved_apy_negative_degradation(self):
        # current > initial → degradation < 0 → not degraded
        pos = _make_pos(current_apy=6.0, initial_apy=5.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertLess(p["yield_degradation_pct"], 0.0)
        self.assertFalse(p["yield_degraded"])

    def test_custom_yield_threshold(self):
        # degradation 20%, custom threshold 10% → degraded
        pos = _make_pos(current_apy=4.0, initial_apy=5.0)
        result = analyze([pos], config={"yield_degradation_threshold": 0.10})
        p = result["positions"][0]
        self.assertTrue(p["yield_degraded"])


class TestConcentration(unittest.TestCase):

    def test_overconcentrated_above_threshold(self):
        pos = _make_pos(current_pct=45.0, target_pct=40.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertTrue(p["is_overconcentrated"])

    def test_not_overconcentrated_at_threshold(self):
        pos = _make_pos(current_pct=40.0, target_pct=40.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertFalse(p["is_overconcentrated"])

    def test_not_overconcentrated_below_threshold(self):
        pos = _make_pos(current_pct=39.9, target_pct=35.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertFalse(p["is_overconcentrated"])

    def test_custom_concentration_threshold(self):
        pos = _make_pos(current_pct=38.0, target_pct=35.0)
        result = analyze([pos], config={"max_concentration_pct": 35.0})
        p = result["positions"][0]
        self.assertTrue(p["is_overconcentrated"])


class TestUrgency(unittest.TestCase):

    def test_hold_when_within_params(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0, current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "HOLD")

    def test_soon_when_overweight_no_yield_issue(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0, current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "SOON")

    def test_soon_when_underweight_no_yield_issue(self):
        pos = _make_pos(current_pct=24.0, target_pct=30.0, current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "SOON")

    def test_monitor_when_yield_degraded_no_drift(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "MONITOR")

    def test_immediate_when_overweight_and_yield_degraded(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "IMMEDIATE")

    def test_immediate_when_underweight_and_yield_degraded(self):
        pos = _make_pos(current_pct=24.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "IMMEDIATE")

    def test_immediate_when_overconcentrated(self):
        # overconcentrated forces IMMEDIATE regardless of drift/yield
        pos = _make_pos(current_pct=45.0, target_pct=40.0, current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "IMMEDIATE")

    def test_immediate_overconcentrated_no_drift(self):
        # on target but overconcentrated → IMMEDIATE
        pos = _make_pos(current_pct=45.0, target_pct=45.0, current_apy=5.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["rebalance_urgency"], "IMMEDIATE")


class TestRecommendations(unittest.TestCase):

    def test_hold_recommendation(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0)
        result = analyze([pos])
        rec = result["positions"][0]["recommendation"]
        self.assertIn("within parameters", rec)
        self.assertIn("+0.0%", rec)

    def test_soon_recommendation(self):
        pos = _make_pos(protocol="Aave", current_pct=36.0, target_pct=30.0)
        result = analyze([pos])
        rec = result["positions"][0]["recommendation"]
        self.assertIn("Schedule rebalance", rec)
        self.assertIn("Aave", rec)
        self.assertIn("+6.0%", rec)

    def test_monitor_recommendation(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        rec = result["positions"][0]["recommendation"]
        self.assertIn("Yield degraded", rec)
        self.assertIn("Monitor", rec)

    def test_immediate_recommendation(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        rec = result["positions"][0]["recommendation"]
        self.assertIn("Rebalance NOW", rec)
        self.assertIn("yield degraded", rec)

    def test_recommendation_underweight_sign(self):
        pos = _make_pos(protocol="Comp", current_pct=24.0, target_pct=30.0)
        result = analyze([pos])
        rec = result["positions"][0]["recommendation"]
        self.assertIn("-6.0%", rec)


class TestEstimatedValueToMove(unittest.TestCase):

    def test_value_to_move_computed(self):
        # drift = 10%, portfolio = 100000
        pos = _make_pos(current_pct=40.0, target_pct=30.0, value=100000.0)
        result = analyze([pos])
        p = result["positions"][0]
        # total_portfolio = 100000, drift = 10/100 * 100000 = 10000
        self.assertAlmostEqual(p["estimated_value_to_move_usd"], 10000.0)

    def test_value_to_move_zero_when_no_drift(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0, value=50000.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["estimated_value_to_move_usd"], 0.0)

    def test_value_to_move_zero_when_total_portfolio_zero(self):
        pos = _make_pos(current_pct=40.0, target_pct=30.0, value=0.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["estimated_value_to_move_usd"], 0.0)

    def test_value_to_move_uses_total_portfolio(self):
        # Two positions: 60k + 40k = 100k total
        pos1 = _make_pos(protocol="A", current_pct=60.0, target_pct=50.0, value=60000.0)
        pos2 = _make_pos(protocol="B", current_pct=40.0, target_pct=50.0, value=40000.0)
        result = analyze([pos1, pos2])
        # drift for pos1 = 10%, 10/100 * 100000 = 10000
        self.assertAlmostEqual(result["positions"][0]["estimated_value_to_move_usd"], 10000.0)
        # drift for pos2 = -10%, 10/100 * 100000 = 10000
        self.assertAlmostEqual(result["positions"][1]["estimated_value_to_move_usd"], 10000.0)


class TestPortfolioSummary(unittest.TestCase):

    def test_total_portfolio_value(self):
        positions = [
            _make_pos(protocol="A", value=50000.0),
            _make_pos(protocol="B", value=30000.0),
            _make_pos(protocol="C", value=20000.0),
        ]
        result = analyze(positions)
        self.assertAlmostEqual(result["portfolio_summary"]["total_portfolio_value_usd"], 100000.0)

    def test_positions_needing_rebalance_count(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0)  # SOON
        pos2 = _make_pos(protocol="B", current_pct=30.0, target_pct=30.0)  # HOLD
        pos3 = _make_pos(protocol="C", current_pct=24.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)  # IMMEDIATE
        result = analyze([pos1, pos2, pos3])
        self.assertEqual(result["portfolio_summary"]["positions_needing_rebalance"], 2)

    def test_total_drift_magnitude_sum(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0)  # drift=6
        pos2 = _make_pos(protocol="B", current_pct=22.0, target_pct=30.0)  # drift=8
        result = analyze([pos1, pos2])
        self.assertAlmostEqual(result["portfolio_summary"]["total_drift_magnitude_pct"], 14.0)

    def test_highest_drift_protocol(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0)  # drift_mag=6
        pos2 = _make_pos(protocol="B", current_pct=20.0, target_pct=30.0)  # drift_mag=10
        result = analyze([pos1, pos2])
        self.assertEqual(result["portfolio_summary"]["highest_drift_protocol"], "B")

    def test_total_rebalance_cost_only_immediate_soon(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0, cost=50.0)  # SOON
        pos2 = _make_pos(protocol="B", current_pct=30.0, target_pct=30.0, cost=40.0)  # HOLD
        pos3 = _make_pos(protocol="C", current_pct=24.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0, cost=30.0)  # IMMEDIATE
        result = analyze([pos1, pos2, pos3])
        self.assertAlmostEqual(result["portfolio_summary"]["total_rebalance_cost_usd"], 80.0)

    def test_rebalance_recommended_true_if_immediate(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertTrue(result["portfolio_summary"]["rebalance_recommended"])

    def test_rebalance_recommended_true_if_two_soon(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0)  # SOON
        pos2 = _make_pos(protocol="B", current_pct=24.0, target_pct=30.0)  # SOON
        result = analyze([pos1, pos2])
        self.assertTrue(result["portfolio_summary"]["rebalance_recommended"])

    def test_rebalance_recommended_false_if_one_soon(self):
        pos1 = _make_pos(protocol="A", current_pct=36.0, target_pct=30.0)  # SOON
        pos2 = _make_pos(protocol="B", current_pct=30.0, target_pct=30.0)  # HOLD
        result = analyze([pos1, pos2])
        self.assertFalse(result["portfolio_summary"]["rebalance_recommended"])

    def test_rebalance_recommended_false_if_only_monitor(self):
        pos = _make_pos(current_pct=30.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertFalse(result["portfolio_summary"]["rebalance_recommended"])

    def test_single_position_highest_drift(self):
        pos = _make_pos(protocol="Solo", current_pct=36.0, target_pct=30.0)
        result = analyze([pos])
        self.assertEqual(result["portfolio_summary"]["highest_drift_protocol"], "Solo")


class TestOutputStructure(unittest.TestCase):

    def test_position_keys_present(self):
        pos = _make_pos()
        result = analyze([pos])
        p = result["positions"][0]
        expected_keys = [
            "protocol", "current_allocation_pct", "target_allocation_pct",
            "allocation_drift_pct", "drift_magnitude_pct", "yield_degradation_pct",
            "is_overweight", "is_underweight", "yield_degraded", "is_overconcentrated",
            "rebalance_urgency", "rebalance_cost_usd", "estimated_value_to_move_usd",
            "recommendation",
        ]
        for k in expected_keys:
            self.assertIn(k, p, f"Missing key: {k}")

    def test_portfolio_summary_keys_present(self):
        result = analyze([_make_pos()])
        s = result["portfolio_summary"]
        expected_keys = [
            "total_portfolio_value_usd", "positions_needing_rebalance",
            "total_drift_magnitude_pct", "highest_drift_protocol",
            "total_rebalance_cost_usd", "rebalance_recommended",
        ]
        for k in expected_keys:
            self.assertIn(k, s, f"Missing key: {k}")

    def test_top_level_keys_present(self):
        result = analyze([_make_pos()])
        self.assertIn("positions", result)
        self.assertIn("portfolio_summary", result)
        self.assertIn("timestamp", result)

    def test_cost_passed_through(self):
        pos = _make_pos(cost=99.5)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["rebalance_cost_usd"], 99.5)

    def test_protocol_name_passed_through(self):
        pos = _make_pos(protocol="MySuperProtocol")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["protocol"], "MySuperProtocol")


class TestMultiPosition(unittest.TestCase):

    def test_three_positions_analyzed(self):
        positions = [
            _make_pos(protocol="A", current_pct=45.0, target_pct=40.0),
            _make_pos(protocol="B", current_pct=30.0, target_pct=30.0),
            _make_pos(protocol="C", current_pct=25.0, target_pct=30.0),
        ]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 3)

    def test_all_hold_gives_zero_needing_rebalance(self):
        positions = [
            _make_pos(protocol="A"),
            _make_pos(protocol="B"),
            _make_pos(protocol="C"),
        ]
        result = analyze(positions)
        self.assertEqual(result["portfolio_summary"]["positions_needing_rebalance"], 0)

    def test_mixed_urgencies_counted_correctly(self):
        positions = [
            _make_pos(protocol="A", current_pct=36.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0),  # IMMEDIATE
            _make_pos(protocol="B", current_pct=36.0, target_pct=30.0),  # SOON
            _make_pos(protocol="C", current_pct=30.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0),  # MONITOR
            _make_pos(protocol="D"),  # HOLD
        ]
        result = analyze(positions)
        self.assertEqual(result["portfolio_summary"]["positions_needing_rebalance"], 2)
        self.assertTrue(result["portfolio_summary"]["rebalance_recommended"])


class TestLogResult(unittest.TestCase):

    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            result = analyze([_make_pos()])
            log_result(result, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            result = analyze([_make_pos()])
            log_result(result, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            r1 = analyze([_make_pos(protocol="A")])
            r2 = analyze([_make_pos(protocol="B")])
            log_result(r1, log_path=path)
            log_result(r2, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            for _ in range(105):
                log_result(analyze([_make_pos()]), log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_log_atomic_on_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.json")
            with open(path, "w") as f:
                f.write("not json{{")
            result = analyze([_make_pos()])
            log_result(result, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):

    def test_zero_position_value(self):
        pos = _make_pos(current_pct=36.0, target_pct=30.0, value=0.0)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["estimated_value_to_move_usd"], 0.0)

    def test_negative_yield_degradation_not_flagged(self):
        # APY went up → degradation_pct negative → NOT degraded
        pos = _make_pos(current_apy=8.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertFalse(result["positions"][0]["yield_degraded"])

    def test_100_percent_yield_drop(self):
        pos = _make_pos(current_apy=0.0, initial_apy=5.0)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["yield_degradation_pct"], 100.0)
        self.assertTrue(result["positions"][0]["yield_degraded"])

    def test_all_fields_types(self):
        pos = _make_pos()
        result = analyze([pos])
        p = result["positions"][0]
        self.assertIsInstance(p["protocol"], str)
        self.assertIsInstance(p["is_overweight"], bool)
        self.assertIsInstance(p["is_underweight"], bool)
        self.assertIsInstance(p["yield_degraded"], bool)
        self.assertIsInstance(p["is_overconcentrated"], bool)
        self.assertIsInstance(p["rebalance_urgency"], str)
        self.assertIsInstance(p["recommendation"], str)
        self.assertIsInstance(p["allocation_drift_pct"], float)

    def test_urgency_values_are_valid(self):
        valid = {"IMMEDIATE", "SOON", "MONITOR", "HOLD"}
        positions = [
            _make_pos(protocol="A", current_pct=36.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0),
            _make_pos(protocol="B", current_pct=36.0, target_pct=30.0),
            _make_pos(protocol="C", current_pct=30.0, target_pct=30.0, current_apy=3.0, initial_apy=5.0),
            _make_pos(protocol="D"),
        ]
        result = analyze(positions)
        for p in result["positions"]:
            self.assertIn(p["rebalance_urgency"], valid)


if __name__ == "__main__":
    unittest.main()
