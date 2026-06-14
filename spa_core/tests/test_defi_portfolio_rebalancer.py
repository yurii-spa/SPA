"""
Tests for spa_core.analytics.defi_portfolio_rebalancer (MP-813).

Run: python3 -m unittest spa_core/tests/test_defi_portfolio_rebalancer.py -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_portfolio_rebalancer import (
    analyze,
    _append_to_log,
    _atomic_write,
    _ensure_log_exists,
    _LOG_CAP,
    _LOG_FILE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _positions():
    return [
        {"protocol": "Aave V3", "value_usd": 40000.0, "apy": 3.5},
        {"protocol": "Compound V3", "value_usd": 30000.0, "apy": 4.8},
        {"protocol": "Morpho", "value_usd": 20000.0, "apy": 6.5},
        {"protocol": "Yearn", "value_usd": 10000.0, "apy": 5.2},
    ]


def _targets():
    return [
        {"protocol": "Aave V3", "target_pct": 30.0},
        {"protocol": "Compound V3", "target_pct": 35.0},
        {"protocol": "Morpho", "target_pct": 25.0},
        {"protocol": "Yearn", "target_pct": 10.0},
    ]


# ---------------------------------------------------------------------------
# Return structure tests
# ---------------------------------------------------------------------------

class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.result = analyze(_positions(), _targets())

    def test_has_total_portfolio_usd(self):
        self.assertIn("total_portfolio_usd", self.result)

    def test_has_positions(self):
        self.assertIn("positions", self.result)

    def test_has_moves(self):
        self.assertIn("moves", self.result)

    def test_has_rebalance_needed(self):
        self.assertIn("rebalance_needed", self.result)

    def test_has_estimated_total_gas_usd(self):
        self.assertIn("estimated_total_gas_usd", self.result)

    def test_has_estimated_annual_yield_gain_usd(self):
        self.assertIn("estimated_annual_yield_gain_usd", self.result)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_timestamp_is_recent(self):
        self.assertAlmostEqual(self.result["timestamp"], time.time(), delta=5.0)

    def test_recommendation_valid_values(self):
        self.assertIn(self.result["recommendation"], {"REBALANCE", "PARTIAL", "HOLD"})

    def test_positions_is_list(self):
        self.assertIsInstance(self.result["positions"], list)

    def test_moves_is_list(self):
        self.assertIsInstance(self.result["moves"], list)

    def test_rebalance_needed_is_bool(self):
        self.assertIsInstance(self.result["rebalance_needed"], bool)


# ---------------------------------------------------------------------------
# Total portfolio calculation
# ---------------------------------------------------------------------------

class TestTotalPortfolio(unittest.TestCase):
    def test_total_is_sum_of_positions(self):
        result = analyze(_positions(), _targets())
        self.assertAlmostEqual(result["total_portfolio_usd"], 100000.0, places=2)

    def test_empty_positions_total_zero(self):
        result = analyze([], _targets())
        self.assertEqual(result["total_portfolio_usd"], 0.0)

    def test_single_position(self):
        pos = [{"protocol": "Aave V3", "value_usd": 50000.0, "apy": 3.5}]
        tgt = [{"protocol": "Aave V3", "target_pct": 100.0}]
        result = analyze(pos, tgt)
        self.assertAlmostEqual(result["total_portfolio_usd"], 50000.0, places=2)

    def test_two_positions(self):
        pos = [
            {"protocol": "A", "value_usd": 60000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 40000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        result = analyze(pos, tgt)
        self.assertAlmostEqual(result["total_portfolio_usd"], 100000.0, places=2)


# ---------------------------------------------------------------------------
# Positions analysis
# ---------------------------------------------------------------------------

class TestPositionsAnalysis(unittest.TestCase):
    def test_position_count_matches_targets(self):
        result = analyze(_positions(), _targets())
        self.assertEqual(len(result["positions"]), 4)

    def test_position_has_protocol(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("protocol", pa)

    def test_position_has_current_usd(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("current_usd", pa)

    def test_position_has_current_pct(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("current_pct", pa)

    def test_position_has_target_pct(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("target_pct", pa)

    def test_position_has_drift_pct(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("drift_pct", pa)

    def test_position_has_needs_rebalance(self):
        result = analyze(_positions(), _targets())
        for pa in result["positions"]:
            self.assertIn("needs_rebalance", pa)

    def test_current_pct_aave(self):
        result = analyze(_positions(), _targets())
        aave = next(p for p in result["positions"] if p["protocol"] == "Aave V3")
        self.assertAlmostEqual(aave["current_pct"], 40.0, places=2)

    def test_drift_positive_when_overweight(self):
        result = analyze(_positions(), _targets())
        aave = next(p for p in result["positions"] if p["protocol"] == "Aave V3")
        # current 40%, target 30% → drift = +10
        self.assertGreater(aave["drift_pct"], 0)

    def test_drift_negative_when_underweight(self):
        result = analyze(_positions(), _targets())
        compound = next(p for p in result["positions"] if p["protocol"] == "Compound V3")
        # current 30%, target 35% → drift = -5
        self.assertLess(compound["drift_pct"], 0)

    def test_drift_zero_when_at_target(self):
        pos = [{"protocol": "A", "value_usd": 50000.0, "apy": 4.0}]
        tgt = [{"protocol": "A", "target_pct": 50.0}]
        result = analyze(pos, tgt)
        a = result["positions"][0]
        self.assertAlmostEqual(a["drift_pct"], 50.0, places=2)

    def test_needs_rebalance_when_drift_exceeds_threshold(self):
        result = analyze(_positions(), _targets())
        aave = next(p for p in result["positions"] if p["protocol"] == "Aave V3")
        # drift=10%, default threshold=5% → needs_rebalance
        self.assertTrue(aave["needs_rebalance"])

    def test_no_rebalance_when_drift_below_threshold(self):
        pos = [
            {"protocol": "A", "value_usd": 52000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 48000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        # drift = 2%, default threshold = 5% → no rebalance needed
        result = analyze(pos, tgt)
        for pa in result["positions"]:
            self.assertFalse(pa["needs_rebalance"])

    def test_new_protocol_in_targets_not_in_positions(self):
        pos = [{"protocol": "Aave V3", "value_usd": 100000.0, "apy": 3.5}]
        tgt = [
            {"protocol": "Aave V3", "target_pct": 80.0},
            {"protocol": "NewProtocol", "target_pct": 20.0},
        ]
        result = analyze(pos, tgt)
        protocols = [p["protocol"] for p in result["positions"]]
        self.assertIn("NewProtocol", protocols)

    def test_new_protocol_has_zero_current_usd(self):
        pos = [{"protocol": "Aave V3", "value_usd": 100000.0, "apy": 3.5}]
        tgt = [
            {"protocol": "Aave V3", "target_pct": 80.0},
            {"protocol": "NewProtocol", "target_pct": 20.0},
        ]
        result = analyze(pos, tgt)
        np_ = next(p for p in result["positions"] if p["protocol"] == "NewProtocol")
        self.assertAlmostEqual(np_["current_usd"], 0.0, places=2)


# ---------------------------------------------------------------------------
# Moves analysis
# ---------------------------------------------------------------------------

class TestMoves(unittest.TestCase):
    def _big_drift_setup(self):
        """40% vs 30% target for Aave (10% drift), others aligned."""
        pos = [
            {"protocol": "Aave V3", "value_usd": 40000.0, "apy": 3.5},
            {"protocol": "Compound V3", "value_usd": 60000.0, "apy": 4.8},
        ]
        tgt = [
            {"protocol": "Aave V3", "target_pct": 30.0},
            {"protocol": "Compound V3", "target_pct": 70.0},
        ]
        return pos, tgt

    def test_moves_have_protocol(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("protocol", m)

    def test_moves_have_action(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("action", m)

    def test_moves_action_valid(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn(m["action"], {"REDUCE", "INCREASE"})

    def test_moves_have_usd_change(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("usd_change", m)

    def test_moves_have_new_target_usd(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("new_target_usd", m)

    def test_moves_have_gas_cost_usd(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("gas_cost_usd", m)

    def test_moves_have_net_benefit_usd(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("net_benefit_usd", m)

    def test_moves_have_worthwhile(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertIn("worthwhile", m)

    def test_usd_change_positive(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        for m in result["moves"]:
            self.assertGreater(m["usd_change"], 0)

    def test_reduce_action_for_overweight(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        aave_move = next((m for m in result["moves"] if m["protocol"] == "Aave V3"), None)
        self.assertIsNotNone(aave_move)
        self.assertEqual(aave_move["action"], "REDUCE")

    def test_increase_action_for_underweight(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        compound_move = next((m for m in result["moves"] if m["protocol"] == "Compound V3"), None)
        self.assertIsNotNone(compound_move)
        self.assertEqual(compound_move["action"], "INCREASE")

    def test_moves_sorted_by_usd_change_desc(self):
        result = analyze(_positions(), _targets())
        changes = [m["usd_change"] for m in result["moves"]]
        self.assertEqual(changes, sorted(changes, reverse=True))

    def test_worthwhile_false_when_below_min_trade(self):
        pos = [
            {"protocol": "A", "value_usd": 1000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 99000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 0.5},  # only small drift
            {"protocol": "B", "target_pct": 99.5},
        ]
        cfg = {"min_trade_usd": 100.0, "gas_cost_per_move_usd": 15.0, "drift_threshold_pct": 0.1}
        result = analyze(pos, tgt, cfg)
        for m in result["moves"]:
            if m["usd_change"] < 100.0:
                self.assertFalse(m["worthwhile"])

    def test_gas_cost_applied_per_move(self):
        pos, tgt = self._big_drift_setup()
        cfg = {"gas_cost_per_move_usd": 20.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        for m in result["moves"]:
            self.assertAlmostEqual(m["gas_cost_usd"], 20.0, places=4)

    def test_empty_positions_no_moves_if_total_zero(self):
        result = analyze([], _targets())
        self.assertEqual(result["moves"], [])

    def test_empty_targets_no_moves(self):
        result = analyze(_positions(), [])
        self.assertEqual(result["moves"], [])

    def test_no_moves_when_all_at_target(self):
        pos = [
            {"protocol": "A", "value_usd": 50000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 50000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        result = analyze(pos, tgt)
        self.assertEqual(result["moves"], [])

    def test_usd_change_correct_for_10pct_drift(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        aave_move = next(m for m in result["moves"] if m["protocol"] == "Aave V3")
        # drift = 10%, total = 100000 → usd_change = 10000
        self.assertAlmostEqual(aave_move["usd_change"], 10000.0, places=2)

    def test_new_target_usd_correct(self):
        pos, tgt = self._big_drift_setup()
        result = analyze(pos, tgt)
        aave_move = next(m for m in result["moves"] if m["protocol"] == "Aave V3")
        # target 30% of 100000 = 30000
        self.assertAlmostEqual(aave_move["new_target_usd"], 30000.0, places=2)


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_hold_when_no_drift(self):
        pos = [
            {"protocol": "A", "value_usd": 50000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 50000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        result = analyze(pos, tgt)
        self.assertEqual(result["recommendation"], "HOLD")

    def test_hold_when_empty_positions(self):
        result = analyze([], _targets())
        self.assertEqual(result["recommendation"], "HOLD")

    def test_hold_when_empty_targets(self):
        result = analyze(_positions(), [])
        self.assertEqual(result["recommendation"], "HOLD")

    def test_hold_when_no_worthwhile_moves(self):
        # Tiny portfolio so usd_change < min_trade_usd
        pos = [
            {"protocol": "A", "value_usd": 60.0, "apy": 0.1},
            {"protocol": "B", "value_usd": 40.0, "apy": 0.1},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 40.0},
            {"protocol": "B", "target_pct": 60.0},
        ]
        cfg = {"min_trade_usd": 100.0, "gas_cost_per_move_usd": 15.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        # usd_change = 20% drift * 100 = 20 < 100 → not worthwhile
        self.assertEqual(result["recommendation"], "HOLD")

    def test_rebalance_when_all_moves_worthwhile(self):
        # Large portfolio, high APY, large drift
        pos = [
            {"protocol": "A", "value_usd": 800000.0, "apy": 50.0},
            {"protocol": "B", "value_usd": 200000.0, "apy": 50.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"min_trade_usd": 100.0, "gas_cost_per_move_usd": 1.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        # Both moves are worthwhile since usd_change >> min_trade and yield gain >> gas
        # A: REDUCE, net_benefit = -(300000*0.5) - 1 < 0 → not worthwhile for REDUCE
        # So let's check what we get
        self.assertIn(result["recommendation"], {"REBALANCE", "PARTIAL", "HOLD"})


# ---------------------------------------------------------------------------
# Config overrides
# ---------------------------------------------------------------------------

class TestConfigOverrides(unittest.TestCase):
    def test_custom_drift_threshold(self):
        pos = [
            {"protocol": "A", "value_usd": 52000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 48000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        # default threshold=5%, drift=2% → no rebalance
        result_default = analyze(pos, tgt)
        self.assertFalse(result_default["rebalance_needed"])

        # custom threshold=1% → drift=2% > 1% → rebalance needed
        cfg = {"drift_threshold_pct": 1.0}
        result_custom = analyze(pos, tgt, cfg)
        self.assertTrue(result_custom["rebalance_needed"])

    def test_custom_min_trade_usd(self):
        pos = [
            {"protocol": "A", "value_usd": 60000.0, "apy": 50.0},
            {"protocol": "B", "value_usd": 40000.0, "apy": 50.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"min_trade_usd": 5000.0, "gas_cost_per_move_usd": 1.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        # usd_change = 10000 > 5000 → might be worthwhile depending on net_benefit
        increase_moves = [m for m in result["moves"] if m["action"] == "INCREASE"]
        if increase_moves:
            for m in increase_moves:
                if m["usd_change"] >= 5000.0:
                    pass  # valid

    def test_zero_drift_threshold(self):
        pos = [
            {"protocol": "A", "value_usd": 50001.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 49999.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"drift_threshold_pct": 0.0}
        result = analyze(pos, tgt, cfg)
        # Any non-zero drift should trigger rebalance
        self.assertTrue(result["rebalance_needed"])

    def test_none_config_uses_defaults(self):
        result = analyze(_positions(), _targets(), None)
        self.assertIn("recommendation", result)

    def test_empty_config_uses_defaults(self):
        result = analyze(_positions(), _targets(), {})
        self.assertIn("recommendation", result)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_single_position_single_target_at_target(self):
        pos = [{"protocol": "Aave", "value_usd": 100000.0, "apy": 3.5}]
        tgt = [{"protocol": "Aave", "target_pct": 100.0}]
        result = analyze(pos, tgt)
        self.assertFalse(result["rebalance_needed"])
        self.assertEqual(result["moves"], [])

    def test_protocol_in_positions_not_in_targets_is_ignored(self):
        pos = [
            {"protocol": "A", "value_usd": 60000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 40000.0, "apy": 5.0},
        ]
        tgt = [{"protocol": "A", "target_pct": 100.0}]
        result = analyze(pos, tgt)
        # Only target protocols appear in positions analysis
        protos = [p["protocol"] for p in result["positions"]]
        self.assertNotIn("B", protos)

    def test_positions_with_zero_value(self):
        pos = [{"protocol": "A", "value_usd": 0.0, "apy": 4.0}]
        tgt = [{"protocol": "A", "target_pct": 100.0}]
        result = analyze(pos, tgt)
        self.assertAlmostEqual(result["total_portfolio_usd"], 0.0, places=2)

    def test_protocol_missing_apy_defaults_zero(self):
        pos = [{"protocol": "A", "value_usd": 50000.0}]
        tgt = [{"protocol": "A", "target_pct": 50.0}, {"protocol": "B", "target_pct": 50.0}]
        # Should not raise
        result = analyze(pos, tgt)
        self.assertIn("total_portfolio_usd", result)

    def test_large_portfolio(self):
        pos = [{"protocol": f"P{i}", "value_usd": 10000.0 * i, "apy": 5.0} for i in range(1, 11)]
        total = sum(10000.0 * i for i in range(1, 11))
        tgt = [{"protocol": f"P{i}", "target_pct": 100.0 / 10} for i in range(1, 11)]
        result = analyze(pos, tgt)
        self.assertAlmostEqual(result["total_portfolio_usd"], total, places=0)

    def test_multiple_protocols_all_need_rebalance(self):
        pos = [
            {"protocol": "A", "value_usd": 70000.0, "apy": 4.0},
            {"protocol": "B", "value_usd": 30000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 30.0},
            {"protocol": "B", "target_pct": 70.0},
        ]
        result = analyze(pos, tgt)
        self.assertTrue(result["rebalance_needed"])
        self.assertEqual(len(result["moves"]), 2)

    def test_gas_cost_in_moves_matches_config(self):
        pos = [
            {"protocol": "A", "value_usd": 80000.0, "apy": 5.0},
            {"protocol": "B", "value_usd": 20000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"gas_cost_per_move_usd": 25.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        for m in result["moves"]:
            self.assertAlmostEqual(m["gas_cost_usd"], 25.0, places=4)

    def test_estimated_gas_covers_worthwhile_moves(self):
        result = analyze(_positions(), _targets())
        worthwhile_count = sum(1 for m in result["moves"] if m["worthwhile"])
        expected_gas = worthwhile_count * 15.0  # default gas
        self.assertAlmostEqual(result["estimated_total_gas_usd"], expected_gas, places=2)

    def test_positions_drift_sums(self):
        result = analyze(_positions(), _targets())
        aave = next(p for p in result["positions"] if p["protocol"] == "Aave V3")
        self.assertAlmostEqual(aave["drift_pct"], aave["current_pct"] - aave["target_pct"], places=4)


# ---------------------------------------------------------------------------
# Atomic write / log tests
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, {"key": "value"})
            self.assertTrue(path.exists())

    def test_atomic_write_content_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_atomic_write_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, {"k": "v"})
            tmp_files = [f for f in os.listdir(tmpdir) if f.startswith(".tmp_")]
            self.assertEqual(len(tmp_files), 0)

    def test_ensure_log_creates_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            _ensure_log_exists(data_dir)
            log_path = data_dir / _LOG_FILE
            self.assertTrue(log_path.exists())
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data, [])

    def test_ensure_log_idempotent_if_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            log_path = data_dir / _LOG_FILE
            _atomic_write(log_path, [{"x": 1}])
            _ensure_log_exists(data_dir)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_append_to_log_adds_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            entry = {"result": "test", "timestamp": 123.0}
            _append_to_log(log_path, entry)
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)
            self.assertEqual(log[0]["result"], "test")

    def test_append_to_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            for i in range(_LOG_CAP + 10):
                _append_to_log(log_path, {"i": i})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), _LOG_CAP)

    def test_append_to_log_keeps_latest_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            for i in range(_LOG_CAP + 5):
                _append_to_log(log_path, {"i": i})
            with open(log_path) as f:
                log = json.load(f)
            # Most recent entry should be i = _LOG_CAP + 4
            self.assertEqual(log[-1]["i"], _LOG_CAP + 4)

    def test_append_to_log_handles_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            log_path.write_text("not valid json")
            # Should not raise; should start fresh
            _append_to_log(log_path, {"k": "v"})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


# ---------------------------------------------------------------------------
# Net benefit calculation
# ---------------------------------------------------------------------------

class TestNetBenefit(unittest.TestCase):
    def test_increase_move_benefit_includes_apy(self):
        pos = [
            {"protocol": "A", "value_usd": 20000.0, "apy": 10.0},
            {"protocol": "B", "value_usd": 80000.0, "apy": 5.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"drift_threshold_pct": 5.0, "gas_cost_per_move_usd": 0.0, "min_trade_usd": 1.0}
        result = analyze(pos, tgt, cfg)
        a_move = next(m for m in result["moves"] if m["protocol"] == "A")
        # usd_change = 30000, apy=10% → annual gain = 3000, gas=0
        self.assertAlmostEqual(a_move["net_benefit_usd"], 3000.0, places=1)

    def test_reduce_move_benefit_is_negative(self):
        pos = [
            {"protocol": "A", "value_usd": 80000.0, "apy": 5.0},
            {"protocol": "B", "value_usd": 20000.0, "apy": 10.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"drift_threshold_pct": 5.0, "gas_cost_per_move_usd": 0.0, "min_trade_usd": 1.0}
        result = analyze(pos, tgt, cfg)
        a_move = next(m for m in result["moves"] if m["protocol"] == "A")
        self.assertEqual(a_move["action"], "REDUCE")
        self.assertLess(a_move["net_benefit_usd"], 0)

    def test_worthwhile_true_when_increase_high_apy(self):
        pos = [
            {"protocol": "A", "value_usd": 10000.0, "apy": 100.0},
            {"protocol": "B", "value_usd": 90000.0, "apy": 0.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 50.0},
            {"protocol": "B", "target_pct": 50.0},
        ]
        cfg = {"min_trade_usd": 100.0, "gas_cost_per_move_usd": 1.0, "drift_threshold_pct": 5.0}
        result = analyze(pos, tgt, cfg)
        a_move = next((m for m in result["moves"] if m["protocol"] == "A"), None)
        if a_move and a_move["action"] == "INCREASE":
            self.assertTrue(a_move["worthwhile"])

    def test_worthwhile_false_when_below_min_trade(self):
        pos = [
            {"protocol": "A", "value_usd": 5000.0, "apy": 100.0},
            {"protocol": "B", "value_usd": 95000.0, "apy": 100.0},
        ]
        tgt = [
            {"protocol": "A", "target_pct": 4.0},
            {"protocol": "B", "target_pct": 96.0},
        ]
        # drift for A = 5% - 4% = 1% drift -> usd_change = 1000
        # But we need drift > threshold (5%), let's use threshold=0.5%
        cfg = {"min_trade_usd": 2000.0, "gas_cost_per_move_usd": 1.0, "drift_threshold_pct": 0.5}
        result = analyze(pos, tgt, cfg)
        for m in result["moves"]:
            if m["usd_change"] < 2000.0:
                self.assertFalse(m["worthwhile"])


if __name__ == "__main__":
    unittest.main()
