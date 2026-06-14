"""
MP-1066 tests — DeFiProtocolSandwichAttackExposureAnalyzer
Unit tests: python3 -m unittest spa_core.tests.test_defi_protocol_sandwich_attack_exposure_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_sandwich_attack_exposure_analyzer import (
    DeFiProtocolSandwichAttackExposureAnalyzer,
    _clamp,
    _atomic_write,
    _load_ring_buffer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_input(**overrides):
    """Return a valid base input dict with optional overrides."""
    inp = {
        "protocol_name": "TestProtocol",
        "pool_tvl_usd": 10_000_000.0,
        "trade_size_usd": 10_000.0,
        "slippage_tolerance_pct": 0.5,
        "mempool_visibility": False,
        "has_commit_reveal": False,
        "uses_private_rpc": False,
        "avg_block_time_seconds": 12.0,
        "mev_bot_activity_score": 50.0,
        "gas_priority_fee_gwei": 10.0,
    }
    inp.update(overrides)
    return inp


class TestClampHelper(unittest.TestCase):
    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below_zero(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_clamp_above_hundred(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_clamp_at_zero(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_at_hundred(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_clamp_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 10.0, 20.0), 10.0)

    def test_clamp_custom_upper(self):
        self.assertEqual(_clamp(25.0, 10.0, 20.0), 20.0)


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, [{"a": 1}])
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            data = [{"key": "value", "num": 42}]
            _atomic_write(path, data)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_atomic_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "subdir", "test.json")
            _atomic_write(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, [1, 2])
            _atomic_write(path, [3, 4])
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, [3, 4])


class TestLoadRingBuffer(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        result = _load_ring_buffer("/nonexistent/path/file.json", 100)
        self.assertEqual(result, [])

    def test_load_valid_list(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "buf.json")
            _atomic_write(path, [1, 2, 3])
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [1, 2, 3])

    def test_load_respects_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "buf.json")
            _atomic_write(path, list(range(200)))
            result = _load_ring_buffer(path, 10)
            self.assertEqual(len(result), 10)
            self.assertEqual(result[-1], 199)

    def test_load_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w") as f:
                f.write("not json")
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [])

    def test_load_non_list_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "obj.json")
            _atomic_write(path, {"a": 1})
            result = _load_ring_buffer(path, 100)
            self.assertEqual(result, [])


class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_result_has_max_sandwich_profit(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("max_sandwich_profit_usd", r)

    def test_result_has_attack_feasibility_score(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("attack_feasibility_score", r)

    def test_result_has_user_loss_estimate_pct(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("user_loss_estimate_pct", r)

    def test_result_has_protection_score(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("protection_score", r)

    def test_result_has_exposure_label(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("exposure_label", r)

    def test_result_has_metadata_module(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertEqual(r["module"], "DeFiProtocolSandwichAttackExposureAnalyzer")

    def test_result_has_metadata_mp(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertEqual(r["mp"], "MP-1066")

    def test_result_has_timestamp(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIn("timestamp", r)
        self.assertIn("T", r["timestamp"])

    def test_result_echoes_protocol_name(self):
        r = self.analyzer.analyze(_base_input(protocol_name="Uniswap"), write_log=False)
        self.assertEqual(r["protocol_name"], "Uniswap")

    def test_result_echoes_trade_size(self):
        r = self.analyzer.analyze(_base_input(trade_size_usd=99_999.0), write_log=False)
        self.assertAlmostEqual(r["trade_size_usd"], 99_999.0)


class TestScoreBounds(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def _check_bounds(self, inp):
        r = self.analyzer.analyze(inp, write_log=False)
        self.assertGreaterEqual(r["attack_feasibility_score"], 0.0)
        self.assertLessEqual(r["attack_feasibility_score"], 100.0)
        self.assertGreaterEqual(r["protection_score"], 0.0)
        self.assertLessEqual(r["protection_score"], 100.0)
        self.assertGreaterEqual(r["user_loss_estimate_pct"], 0.0)
        self.assertGreaterEqual(r["max_sandwich_profit_usd"], 0.0)

    def test_bounds_with_all_protections_on(self):
        self._check_bounds(_base_input(
            has_commit_reveal=True, uses_private_rpc=True, mempool_visibility=False,
            mev_bot_activity_score=0.0, gas_priority_fee_gwei=1.0
        ))

    def test_bounds_with_all_risks_max(self):
        self._check_bounds(_base_input(
            mempool_visibility=True, mev_bot_activity_score=100.0,
            gas_priority_fee_gwei=200.0, slippage_tolerance_pct=10.0
        ))

    def test_bounds_zero_tvl(self):
        self._check_bounds(_base_input(pool_tvl_usd=0.0))

    def test_bounds_zero_trade_size(self):
        self._check_bounds(_base_input(trade_size_usd=0.0))

    def test_bounds_zero_slippage(self):
        self._check_bounds(_base_input(slippage_tolerance_pct=0.0))

    def test_bounds_zero_gas(self):
        self._check_bounds(_base_input(gas_priority_fee_gwei=0.0))

    def test_bounds_zero_mev_bots(self):
        self._check_bounds(_base_input(mev_bot_activity_score=0.0))

    def test_bounds_max_mev_bots(self):
        self._check_bounds(_base_input(mev_bot_activity_score=100.0))

    def test_user_loss_not_exceed_slippage(self):
        slippage = 2.0
        r = self.analyzer.analyze(_base_input(
            slippage_tolerance_pct=slippage,
            mempool_visibility=True,
            mev_bot_activity_score=100.0,
        ), write_log=False)
        self.assertLessEqual(r["user_loss_estimate_pct"], slippage)


class TestSandwichProfitLogic(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_profit_zero_trade(self):
        r = self.analyzer.analyze(_base_input(trade_size_usd=0.0), write_log=False)
        self.assertEqual(r["max_sandwich_profit_usd"], 0.0)

    def test_profit_increases_with_trade_size(self):
        r1 = self.analyzer.analyze(_base_input(trade_size_usd=10_000), write_log=False)
        r2 = self.analyzer.analyze(_base_input(trade_size_usd=100_000), write_log=False)
        self.assertGreater(r2["max_sandwich_profit_usd"], r1["max_sandwich_profit_usd"])

    def test_profit_decreases_with_larger_tvl(self):
        r1 = self.analyzer.analyze(_base_input(pool_tvl_usd=100_000), write_log=False)
        r2 = self.analyzer.analyze(_base_input(pool_tvl_usd=500_000_000), write_log=False)
        self.assertGreater(r1["max_sandwich_profit_usd"], r2["max_sandwich_profit_usd"])

    def test_profit_increases_with_slippage(self):
        r1 = self.analyzer.analyze(_base_input(slippage_tolerance_pct=0.1), write_log=False)
        r2 = self.analyzer.analyze(_base_input(slippage_tolerance_pct=5.0), write_log=False)
        self.assertGreater(r2["max_sandwich_profit_usd"], r1["max_sandwich_profit_usd"])

    def test_profit_non_negative(self):
        r = self.analyzer.analyze(_base_input(
            pool_tvl_usd=1_000_000_000, trade_size_usd=1, slippage_tolerance_pct=0.01
        ), write_log=False)
        self.assertGreaterEqual(r["max_sandwich_profit_usd"], 0.0)

    def test_profit_large_trade_small_pool(self):
        r = self.analyzer.analyze(_base_input(
            pool_tvl_usd=100_000, trade_size_usd=50_000, slippage_tolerance_pct=5.0
        ), write_log=False)
        self.assertGreater(r["max_sandwich_profit_usd"], 0.0)


class TestProtectionScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_protection_with_private_rpc(self):
        r = self.analyzer.analyze(_base_input(uses_private_rpc=True), write_log=False)
        self.assertGreaterEqual(r["protection_score"], 35.0)

    def test_protection_with_commit_reveal(self):
        r = self.analyzer.analyze(_base_input(has_commit_reveal=True), write_log=False)
        self.assertGreaterEqual(r["protection_score"], 35.0)

    def test_protection_no_mempool(self):
        r = self.analyzer.analyze(_base_input(mempool_visibility=False), write_log=False)
        self.assertGreaterEqual(r["protection_score"], 20.0)

    def test_protection_low_mev_bots(self):
        r = self.analyzer.analyze(_base_input(mev_bot_activity_score=10.0), write_log=False)
        self.assertGreaterEqual(r["protection_score"], 10.0)

    def test_max_protection_all_on(self):
        r = self.analyzer.analyze(_base_input(
            uses_private_rpc=True, has_commit_reveal=True,
            mempool_visibility=False, mev_bot_activity_score=10.0
        ), write_log=False)
        self.assertGreaterEqual(r["protection_score"], 90.0)

    def test_no_protection_base(self):
        r = self.analyzer.analyze(_base_input(
            uses_private_rpc=False, has_commit_reveal=False,
            mempool_visibility=True, mev_bot_activity_score=80.0
        ), write_log=False)
        self.assertEqual(r["protection_score"], 0.0)

    def test_protection_increases_with_private_rpc_and_commit_reveal(self):
        r1 = self.analyzer.analyze(_base_input(uses_private_rpc=True), write_log=False)
        r2 = self.analyzer.analyze(_base_input(
            uses_private_rpc=True, has_commit_reveal=True
        ), write_log=False)
        self.assertGreater(r2["protection_score"], r1["protection_score"])


class TestFeasibilityScore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_mempool_increases_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(mempool_visibility=False), write_log=False)
        r2 = self.analyzer.analyze(_base_input(mempool_visibility=True), write_log=False)
        self.assertGreater(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_commit_reveal_decreases_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(has_commit_reveal=False), write_log=False)
        r2 = self.analyzer.analyze(_base_input(has_commit_reveal=True), write_log=False)
        self.assertLess(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_private_rpc_decreases_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(uses_private_rpc=False), write_log=False)
        r2 = self.analyzer.analyze(_base_input(uses_private_rpc=True), write_log=False)
        self.assertLess(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_mev_bots_increase_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(mev_bot_activity_score=0.0), write_log=False)
        r2 = self.analyzer.analyze(_base_input(mev_bot_activity_score=100.0), write_log=False)
        self.assertGreater(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_high_gas_increases_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(gas_priority_fee_gwei=5.0), write_log=False)
        r2 = self.analyzer.analyze(_base_input(gas_priority_fee_gwei=120.0), write_log=False)
        self.assertGreater(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_high_slippage_increases_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(slippage_tolerance_pct=0.1), write_log=False)
        r2 = self.analyzer.analyze(_base_input(slippage_tolerance_pct=5.0), write_log=False)
        self.assertGreater(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_fast_blocks_decrease_feasibility(self):
        r1 = self.analyzer.analyze(_base_input(avg_block_time_seconds=12.0), write_log=False)
        r2 = self.analyzer.analyze(_base_input(avg_block_time_seconds=0.5), write_log=False)
        self.assertLess(r2["attack_feasibility_score"], r1["attack_feasibility_score"])

    def test_feasibility_always_in_bounds(self):
        for mev in [0, 25, 50, 75, 100]:
            r = self.analyzer.analyze(_base_input(mev_bot_activity_score=mev), write_log=False)
            self.assertGreaterEqual(r["attack_feasibility_score"], 0.0)
            self.assertLessEqual(r["attack_feasibility_score"], 100.0)


class TestExposureLabels(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def _label(self, **kwargs):
        return self.analyzer.analyze(_base_input(**kwargs), write_log=False)["exposure_label"]

    def test_mev_protected_label(self):
        label = self._label(
            uses_private_rpc=True, has_commit_reveal=True,
            mempool_visibility=False, mev_bot_activity_score=5.0
        )
        self.assertEqual(label, "MEV_PROTECTED")

    def test_sandwich_target_label(self):
        label = self._label(
            mempool_visibility=True, mev_bot_activity_score=100.0,
            slippage_tolerance_pct=10.0, gas_priority_fee_gwei=200.0,
            has_commit_reveal=False, uses_private_rpc=False,
            avg_block_time_seconds=12.0
        )
        self.assertEqual(label, "SANDWICH_TARGET")

    def test_low_exposure_label(self):
        # uses_private_rpc=True drops feasibility to 0; protection (65) < 75
        # → LOW_EXPOSURE (not MEV_PROTECTED, not MODERATE/HIGH)
        label = self._label(
            mempool_visibility=False, mev_bot_activity_score=0.0,
            slippage_tolerance_pct=0.1, gas_priority_fee_gwei=1.0,
            has_commit_reveal=False, uses_private_rpc=True,
            avg_block_time_seconds=0.5
        )
        self.assertEqual(label, "LOW_EXPOSURE")

    def test_label_is_valid_string(self):
        valid_labels = {
            "MEV_PROTECTED", "LOW_EXPOSURE", "MODERATE_EXPOSURE",
            "HIGH_EXPOSURE", "SANDWICH_TARGET"
        }
        for _ in range(5):
            r = self.analyzer.analyze(_base_input(), write_log=False)
            self.assertIn(r["exposure_label"], valid_labels)

    def test_all_labels_reachable(self):
        valid_labels = {
            "MEV_PROTECTED", "LOW_EXPOSURE", "MODERATE_EXPOSURE",
            "HIGH_EXPOSURE", "SANDWICH_TARGET"
        }
        seen = set()
        test_cases = [
            _base_input(uses_private_rpc=True, has_commit_reveal=True, mempool_visibility=False, mev_bot_activity_score=5.0),
            _base_input(mempool_visibility=False, mev_bot_activity_score=0.0, slippage_tolerance_pct=0.1, gas_priority_fee_gwei=1.0, avg_block_time_seconds=0.5),
            _base_input(mempool_visibility=True, mev_bot_activity_score=30.0, slippage_tolerance_pct=0.5),
            _base_input(mempool_visibility=True, mev_bot_activity_score=70.0, slippage_tolerance_pct=2.0),
            _base_input(mempool_visibility=True, mev_bot_activity_score=100.0, slippage_tolerance_pct=10.0, gas_priority_fee_gwei=200.0),
        ]
        for tc in test_cases:
            r = self.analyzer.analyze(tc, write_log=False)
            seen.add(r["exposure_label"])
        self.assertTrue(seen.issubset(valid_labels))
        self.assertGreaterEqual(len(seen), 3)


class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_log_file_created(self):
        self.analyzer.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        self.analyzer.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_appended(self):
        for _ in range(3):
            self.analyzer.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_entry_has_required_fields(self):
        self.analyzer.analyze(_base_input(protocol_name="Curve"), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("timestamp", entry)
        self.assertIn("attack_feasibility_score", entry)
        self.assertIn("exposure_label", entry)

    def test_log_respects_ring_buffer_cap(self):
        for _ in range(110):
            self.analyzer.analyze(_base_input(), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_no_log_when_write_log_false(self):
        self.analyzer.analyze(_base_input(), write_log=False)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        self.assertFalse(os.path.exists(log_path))

    def test_log_protocol_name_recorded(self):
        self.analyzer.analyze(_base_input(protocol_name="Balancer"), write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_name"], "Balancer")


class TestBatchAnalysis(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_batch_returns_list(self):
        results = self.analyzer.analyze_batch([_base_input(), _base_input()], write_log=False)
        self.assertIsInstance(results, list)

    def test_batch_returns_correct_count(self):
        inputs = [_base_input(protocol_name=f"P{i}") for i in range(5)]
        results = self.analyzer.analyze_batch(inputs, write_log=False)
        self.assertEqual(len(results), 5)

    def test_batch_each_result_has_label(self):
        results = self.analyzer.analyze_batch([_base_input(), _base_input()], write_log=False)
        for r in results:
            self.assertIn("exposure_label", r)

    def test_batch_empty_input(self):
        results = self.analyzer.analyze_batch([], write_log=False)
        self.assertEqual(results, [])

    def test_batch_log_written_once(self):
        inputs = [_base_input() for _ in range(5)]
        self.analyzer.analyze_batch(inputs, write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_batch_log_has_batch_size(self):
        inputs = [_base_input() for _ in range(4)]
        self.analyzer.analyze_batch(inputs, write_log=True)
        log_path = os.path.join(self.td, "sandwich_attack_exposure_log.json")
        with open(log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["batch_size"], 4)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def test_missing_all_fields(self):
        r = self.analyzer.analyze({}, write_log=False)
        self.assertIn("exposure_label", r)
        self.assertIn("attack_feasibility_score", r)

    def test_negative_tvl_no_crash(self):
        r = self.analyzer.analyze(_base_input(pool_tvl_usd=-1.0), write_log=False)
        self.assertGreaterEqual(r["max_sandwich_profit_usd"], 0.0)

    def test_very_large_gas(self):
        r = self.analyzer.analyze(_base_input(gas_priority_fee_gwei=10_000.0), write_log=False)
        self.assertLessEqual(r["attack_feasibility_score"], 100.0)

    def test_zero_slippage_zero_profit(self):
        r = self.analyzer.analyze(_base_input(slippage_tolerance_pct=0.0), write_log=False)
        self.assertEqual(r["max_sandwich_profit_usd"], 0.0)

    def test_zero_slippage_zero_user_loss(self):
        r = self.analyzer.analyze(_base_input(slippage_tolerance_pct=0.0), write_log=False)
        self.assertEqual(r["user_loss_estimate_pct"], 0.0)

    def test_very_fast_block_time(self):
        r = self.analyzer.analyze(_base_input(avg_block_time_seconds=0.01), write_log=False)
        self.assertGreaterEqual(r["attack_feasibility_score"], 0.0)

    def test_protection_score_capped_at_100(self):
        r = self.analyzer.analyze(_base_input(
            uses_private_rpc=True, has_commit_reveal=True,
            mempool_visibility=False, mev_bot_activity_score=0.0
        ), write_log=False)
        self.assertLessEqual(r["protection_score"], 100.0)

    def test_result_type_float_scores(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIsInstance(r["attack_feasibility_score"], float)
        self.assertIsInstance(r["protection_score"], float)
        self.assertIsInstance(r["user_loss_estimate_pct"], float)
        self.assertIsInstance(r["max_sandwich_profit_usd"], float)

    def test_result_type_str_label(self):
        r = self.analyzer.analyze(_base_input(), write_log=False)
        self.assertIsInstance(r["exposure_label"], str)

    def test_custom_data_dir_used(self):
        with tempfile.TemporaryDirectory() as custom_dir:
            az = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=custom_dir)
            az.analyze(_base_input(), write_log=True)
            log_path = os.path.join(custom_dir, "sandwich_attack_exposure_log.json")
            self.assertTrue(os.path.exists(log_path))


class TestScoringScenarios(unittest.TestCase):
    """Integration-style scenarios verifying end-to-end consistency."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolSandwichAttackExposureAnalyzer(data_dir=self.td)

    def _r(self, **kw):
        return self.analyzer.analyze(_base_input(**kw), write_log=False)

    def test_private_rpc_reduces_feasibility_and_increases_protection(self):
        without = self._r(uses_private_rpc=False)
        with_ = self._r(uses_private_rpc=True)
        self.assertLess(with_["attack_feasibility_score"], without["attack_feasibility_score"])
        self.assertGreater(with_["protection_score"], without["protection_score"])

    def test_commit_reveal_reduces_feasibility_and_increases_protection(self):
        without = self._r(has_commit_reveal=False)
        with_ = self._r(has_commit_reveal=True)
        self.assertLess(with_["attack_feasibility_score"], without["attack_feasibility_score"])
        self.assertGreater(with_["protection_score"], without["protection_score"])

    def test_high_mev_activity_increases_feasibility(self):
        low = self._r(mev_bot_activity_score=10.0)
        high = self._r(mev_bot_activity_score=90.0)
        self.assertGreater(high["attack_feasibility_score"], low["attack_feasibility_score"])

    def test_mempool_visibility_increases_feasibility(self):
        no_mem = self._r(mempool_visibility=False)
        mem = self._r(mempool_visibility=True)
        self.assertGreater(mem["attack_feasibility_score"], no_mem["attack_feasibility_score"])

    def test_user_loss_higher_when_feasibility_higher(self):
        low = self._r(mempool_visibility=False, mev_bot_activity_score=0.0)
        high = self._r(mempool_visibility=True, mev_bot_activity_score=100.0)
        self.assertGreaterEqual(high["user_loss_estimate_pct"], low["user_loss_estimate_pct"])

    def test_fully_protected_pool_gives_protected_label(self):
        r = self._r(
            uses_private_rpc=True, has_commit_reveal=True,
            mempool_visibility=False, mev_bot_activity_score=5.0
        )
        self.assertEqual(r["exposure_label"], "MEV_PROTECTED")

    def test_worst_case_scenario(self):
        r = self._r(
            mempool_visibility=True,
            mev_bot_activity_score=100.0,
            gas_priority_fee_gwei=200.0,
            slippage_tolerance_pct=10.0,
            has_commit_reveal=False,
            uses_private_rpc=False,
            avg_block_time_seconds=12.0,
        )
        self.assertGreaterEqual(r["attack_feasibility_score"], 75.0)
        self.assertEqual(r["exposure_label"], "SANDWICH_TARGET")

    def test_best_case_scenario(self):
        r = self._r(
            uses_private_rpc=True,
            has_commit_reveal=True,
            mempool_visibility=False,
            mev_bot_activity_score=0.0,
            slippage_tolerance_pct=0.1,
            gas_priority_fee_gwei=1.0,
        )
        self.assertEqual(r["exposure_label"], "MEV_PROTECTED")
        self.assertGreaterEqual(r["protection_score"], 75.0)

    def test_medium_scenario(self):
        r = self._r(
            mempool_visibility=True,
            mev_bot_activity_score=50.0,
            slippage_tolerance_pct=1.0,
            uses_private_rpc=False,
            has_commit_reveal=False,
        )
        valid = {"MODERATE_EXPOSURE", "HIGH_EXPOSURE", "SANDWICH_TARGET"}
        self.assertIn(r["exposure_label"], valid)

    def test_slippage_above_3pct_increases_feasibility_vs_below_1pct(self):
        low = self._r(slippage_tolerance_pct=0.5)
        high = self._r(slippage_tolerance_pct=4.0)
        self.assertGreater(high["attack_feasibility_score"], low["attack_feasibility_score"])

    def test_gas_above_100_gwei_increases_feasibility(self):
        low = self._r(gas_priority_fee_gwei=5.0)
        high = self._r(gas_priority_fee_gwei=150.0)
        self.assertGreater(high["attack_feasibility_score"], low["attack_feasibility_score"])


if __name__ == "__main__":
    unittest.main()
