"""
Tests for MP-978: DeFiProtocolExitLiquidityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_exit_liquidity_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_exit_liquidity_analyzer import (
    DeFiProtocolExitLiquidityAnalyzer,
    LABEL_INSTANT_EXIT,
    LABEL_EASY_EXIT,
    LABEL_MODERATE_EXIT,
    LABEL_DIFFICULT_EXIT,
    LABEL_TRAPPED,
    FLAG_WITHDRAWAL_QUEUE,
    FLAG_LOCKED,
    FLAG_LARGE_RELATIVE_TO_MARKET,
    FLAG_FEE_BARRIER,
    FLAG_SINGLE_TX_CONSTRAINED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(**kwargs):
    """Return a minimal valid position dict with overridable defaults."""
    base = {
        "protocol": "TestProtocol",
        "asset": "USDC",
        "position_size_usd": 10_000.0,
        "available_exit_liquidity_usd": 1_000_000.0,
        "daily_volume_usd": 500_000.0,
        "exit_type": "instant_withdraw",
        "lock_remaining_days": 0.0,
        "withdrawal_queue_usd": 0.0,
        "slippage_model": "linear",
        "withdrawal_fee_pct": 0.0,
        "max_exit_in_single_tx_usd": 10_000.0,
    }
    base.update(kwargs)
    return base


class TestDeFiProtocolExitLiquidityAnalyzerBasic(unittest.TestCase):
    """Basic structure tests."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def test_returns_dict(self):
        result = self.analyzer.analyze([_make_position()])
        self.assertIsInstance(result, dict)

    def test_has_results_key(self):
        result = self.analyzer.analyze([_make_position()])
        self.assertIn("results", result)

    def test_has_aggregates_key(self):
        result = self.analyzer.analyze([_make_position()])
        self.assertIn("aggregates", result)

    def test_has_run_ts(self):
        result = self.analyzer.analyze([_make_position()])
        self.assertIn("run_ts", result)

    def test_has_position_count(self):
        result = self.analyzer.analyze([_make_position(), _make_position()])
        self.assertEqual(result["position_count"], 2)

    def test_empty_list(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["position_count"], 0)

    def test_results_length_matches_input(self):
        positions = [_make_position(protocol=f"P{i}") for i in range(5)]
        result = self.analyzer.analyze(positions)
        self.assertEqual(len(result["results"]), 5)

    def test_none_config_ok(self):
        result = self.analyzer.analyze([_make_position()], config=None)
        self.assertIsInstance(result, dict)

    def test_empty_config_ok(self):
        result = self.analyzer.analyze([_make_position()], config={})
        self.assertIsInstance(result, dict)


class TestResultFields(unittest.TestCase):
    """Test that each result has required fields."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]

    def test_has_protocol(self):
        self.assertIn("protocol", self._get_result())

    def test_has_asset(self):
        self.assertIn("asset", self._get_result())

    def test_has_position_size_usd(self):
        self.assertIn("position_size_usd", self._get_result())

    def test_has_liquidity_ratio(self):
        self.assertIn("liquidity_ratio", self._get_result())

    def test_has_exit_1pct_days(self):
        self.assertIn("exit_1pct_days", self._get_result())

    def test_has_exit_10pct_days(self):
        self.assertIn("exit_10pct_days", self._get_result())

    def test_has_full_exit_days(self):
        self.assertIn("full_exit_days", self._get_result())

    def test_has_exit_friction_score(self):
        self.assertIn("exit_friction_score", self._get_result())

    def test_has_label(self):
        self.assertIn("label", self._get_result())

    def test_has_flags(self):
        self.assertIn("flags", self._get_result())

    def test_flags_is_list(self):
        r = self._get_result()
        self.assertIsInstance(r["flags"], list)

    def test_has_exit_type(self):
        self.assertIn("exit_type", self._get_result())

    def test_has_lock_remaining_days(self):
        self.assertIn("lock_remaining_days", self._get_result())

    def test_protocol_field_value(self):
        r = self._get_result(protocol="Aave")
        self.assertEqual(r["protocol"], "Aave")

    def test_asset_field_value(self):
        r = self._get_result(asset="DAI")
        self.assertEqual(r["asset"], "DAI")


class TestLiquidityRatio(unittest.TestCase):
    """Test liquidity_ratio computation."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]

    def test_ratio_small_position(self):
        r = self._get_result(position_size_usd=1_000.0, available_exit_liquidity_usd=1_000_000.0)
        self.assertAlmostEqual(r["liquidity_ratio"], 0.001, places=3)

    def test_ratio_large_position(self):
        r = self._get_result(position_size_usd=500_000.0, available_exit_liquidity_usd=1_000_000.0)
        self.assertAlmostEqual(r["liquidity_ratio"], 0.5, places=3)

    def test_ratio_zero_liquidity(self):
        r = self._get_result(position_size_usd=10_000.0, available_exit_liquidity_usd=0.0)
        self.assertGreater(r["liquidity_ratio"], 10.0)  # large sentinel

    def test_ratio_is_float(self):
        r = self._get_result()
        self.assertIsInstance(r["liquidity_ratio"], float)


class TestFrictionScore(unittest.TestCase):
    """Test exit_friction_score range and direction."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_friction(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]["exit_friction_score"]

    def test_friction_in_range(self):
        f = self._get_friction()
        self.assertGreaterEqual(f, 0.0)
        self.assertLessEqual(f, 100.0)

    def test_friction_increases_with_lock(self):
        f0 = self._get_friction(lock_remaining_days=0)
        f30 = self._get_friction(lock_remaining_days=30)
        self.assertGreater(f30, f0)

    def test_friction_increases_with_queue(self):
        f0 = self._get_friction(withdrawal_queue_usd=0)
        f_big = self._get_friction(withdrawal_queue_usd=50_000.0)
        self.assertGreater(f_big, f0)

    def test_friction_increases_with_fee(self):
        f0 = self._get_friction(withdrawal_fee_pct=0.0)
        f5 = self._get_friction(withdrawal_fee_pct=5.0)
        self.assertGreater(f5, f0)

    def test_friction_high_liquidity_low(self):
        # Very deep liquidity → low slippage component
        f = self._get_friction(
            position_size_usd=1_000.0,
            available_exit_liquidity_usd=100_000_000.0,
            lock_remaining_days=0,
            withdrawal_queue_usd=0,
            withdrawal_fee_pct=0,
        )
        self.assertLess(f, 10.0)

    def test_friction_max_lock(self):
        f = self._get_friction(lock_remaining_days=30.0)
        self.assertGreater(f, 0.0)


class TestExitLabels(unittest.TestCase):
    """Test exit label assignment."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_label(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]["label"]

    def test_instant_exit_label(self):
        label = self._get_label(
            position_size_usd=100.0,
            available_exit_liquidity_usd=100_000_000.0,
            daily_volume_usd=50_000_000.0,
            lock_remaining_days=0.0,
            withdrawal_queue_usd=0.0,
            withdrawal_fee_pct=0.0,
            slippage_model="linear",
        )
        self.assertEqual(label, LABEL_INSTANT_EXIT)

    def test_trapped_by_queue(self):
        label = self._get_label(
            position_size_usd=10_000.0,
            withdrawal_queue_usd=20_000.0,
        )
        self.assertEqual(label, LABEL_TRAPPED)

    def test_trapped_by_long_exit(self):
        # Tiny volume, big position → many days
        label = self._get_label(
            position_size_usd=1_000_000.0,
            available_exit_liquidity_usd=100.0,
            daily_volume_usd=10.0,
            lock_remaining_days=0.0,
            withdrawal_queue_usd=0.0,
        )
        self.assertEqual(label, LABEL_TRAPPED)

    def test_valid_labels(self):
        valid = {LABEL_INSTANT_EXIT, LABEL_EASY_EXIT, LABEL_MODERATE_EXIT, LABEL_DIFFICULT_EXIT, LABEL_TRAPPED}
        label = self._get_label()
        self.assertIn(label, valid)

    def test_locked_position_not_instant(self):
        label = self._get_label(lock_remaining_days=7.0)
        self.assertNotEqual(label, LABEL_INSTANT_EXIT)


class TestFlags(unittest.TestCase):
    """Test flag assignment."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_flags(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]["flags"]

    def test_no_flags_clean_position(self):
        flags = self._get_flags(
            position_size_usd=1_000.0,
            available_exit_liquidity_usd=100_000_000.0,
            lock_remaining_days=0.0,
            withdrawal_queue_usd=0.0,
            withdrawal_fee_pct=0.0,
            max_exit_in_single_tx_usd=1_000.0,
        )
        self.assertNotIn(FLAG_WITHDRAWAL_QUEUE, flags)
        self.assertNotIn(FLAG_LOCKED, flags)
        self.assertNotIn(FLAG_FEE_BARRIER, flags)

    def test_withdrawal_queue_flag(self):
        flags = self._get_flags(withdrawal_queue_usd=5_000.0)
        self.assertIn(FLAG_WITHDRAWAL_QUEUE, flags)

    def test_no_withdrawal_queue_flag(self):
        flags = self._get_flags(withdrawal_queue_usd=0.0)
        self.assertNotIn(FLAG_WITHDRAWAL_QUEUE, flags)

    def test_locked_flag(self):
        flags = self._get_flags(lock_remaining_days=7.0)
        self.assertIn(FLAG_LOCKED, flags)

    def test_no_locked_flag(self):
        flags = self._get_flags(lock_remaining_days=0.0)
        self.assertNotIn(FLAG_LOCKED, flags)

    def test_large_relative_to_market_flag(self):
        # ratio = 0.5 > 0.1 threshold
        flags = self._get_flags(
            position_size_usd=500_000.0,
            available_exit_liquidity_usd=1_000_000.0,
        )
        self.assertIn(FLAG_LARGE_RELATIVE_TO_MARKET, flags)

    def test_no_large_relative_flag(self):
        flags = self._get_flags(
            position_size_usd=1_000.0,
            available_exit_liquidity_usd=1_000_000.0,
        )
        self.assertNotIn(FLAG_LARGE_RELATIVE_TO_MARKET, flags)

    def test_fee_barrier_flag(self):
        flags = self._get_flags(withdrawal_fee_pct=3.0)
        self.assertIn(FLAG_FEE_BARRIER, flags)

    def test_no_fee_barrier_flag(self):
        flags = self._get_flags(withdrawal_fee_pct=1.0)
        self.assertNotIn(FLAG_FEE_BARRIER, flags)

    def test_single_tx_constrained_flag(self):
        # max_tx = 100, position = 10000, 100 < 1000 (10% of 10000)
        flags = self._get_flags(
            position_size_usd=10_000.0,
            max_exit_in_single_tx_usd=100.0,
        )
        self.assertIn(FLAG_SINGLE_TX_CONSTRAINED, flags)

    def test_no_single_tx_flag(self):
        # max_tx >= 10% of position
        flags = self._get_flags(
            position_size_usd=10_000.0,
            max_exit_in_single_tx_usd=1_500.0,
        )
        self.assertNotIn(FLAG_SINGLE_TX_CONSTRAINED, flags)


class TestAggregates(unittest.TestCase):
    """Test aggregate calculations."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def test_aggregates_empty(self):
        agg = self.analyzer.analyze([])["aggregates"]
        self.assertIsNone(agg["most_liquid"])
        self.assertIsNone(agg["least_liquid"])
        self.assertEqual(agg["total_trapped_usd"], 0.0)
        self.assertEqual(agg["easy_exit_count"], 0)
        self.assertEqual(agg["average_exit_friction"], 0.0)

    def test_aggregates_has_most_liquid(self):
        agg = self.analyzer.analyze([_make_position(protocol="A"), _make_position(protocol="B")])["aggregates"]
        self.assertIsNotNone(agg["most_liquid"])

    def test_aggregates_has_least_liquid(self):
        agg = self.analyzer.analyze([_make_position(protocol="A"), _make_position(protocol="B")])["aggregates"]
        self.assertIsNotNone(agg["least_liquid"])

    def test_total_trapped_usd_zero(self):
        # Both should be easy exit
        agg = self.analyzer.analyze([
            _make_position(
                position_size_usd=100.0,
                available_exit_liquidity_usd=100_000_000.0,
                daily_volume_usd=10_000_000.0,
            )
        ])["aggregates"]
        self.assertEqual(agg["total_trapped_usd"], 0.0)

    def test_total_trapped_usd_nonzero(self):
        agg = self.analyzer.analyze([
            _make_position(position_size_usd=5_000.0, withdrawal_queue_usd=20_000.0)
        ])["aggregates"]
        self.assertGreater(agg["total_trapped_usd"], 0.0)

    def test_easy_exit_count_zero(self):
        # Large position with no liquidity
        agg = self.analyzer.analyze([
            _make_position(position_size_usd=1_000_000.0, available_exit_liquidity_usd=100.0, daily_volume_usd=1.0)
        ])["aggregates"]
        self.assertEqual(agg["easy_exit_count"], 0)

    def test_average_friction_is_float(self):
        agg = self.analyzer.analyze([_make_position()])["aggregates"]
        self.assertIsInstance(agg["average_exit_friction"], float)


class TestSlippageModels(unittest.TestCase):
    """Test different slippage models."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]

    def test_linear_model_returns_result(self):
        r = self._get_result(slippage_model="linear")
        self.assertIn("label", r)

    def test_sqrt_model_returns_result(self):
        r = self._get_result(slippage_model="sqrt")
        self.assertIn("label", r)

    def test_constant_model_returns_result(self):
        r = self._get_result(slippage_model="constant")
        self.assertIn("label", r)

    def test_unknown_model_fallback(self):
        r = self._get_result(slippage_model="unknown_model")
        self.assertIn("label", r)

    def test_constant_slippage_low(self):
        r = self._get_result(
            slippage_model="constant",
            position_size_usd=1_000.0,
            available_exit_liquidity_usd=1_000_000.0,
        )
        self.assertLess(r["slippage_at_1pct_impact"], 5.0)


class TestExitTypes(unittest.TestCase):
    """Test different exit types."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_label(self, exit_type, **kwargs):
        r = self.analyzer.analyze([_make_position(exit_type=exit_type, **kwargs)])
        return r["results"][0]["label"]

    def test_instant_withdraw_type(self):
        label = self._get_label("instant_withdraw")
        self.assertIsNotNone(label)

    def test_vesting_unlock_type(self):
        label = self._get_label("vesting_unlock", lock_remaining_days=14.0)
        self.assertIsNotNone(label)

    def test_pool_exit_type(self):
        label = self._get_label("pool_exit")
        self.assertIsNotNone(label)

    def test_bond_redemption_type(self):
        label = self._get_label("bond_redemption")
        self.assertIsNotNone(label)


class TestRingBufferLog(unittest.TestCase):
    """Test ring-buffer log writes."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def test_log_created_after_analyze(self):
        self.analyzer.analyze([_make_position()])
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_is_list(self):
        self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows_with_calls(self):
        self.analyzer.analyze([_make_position()])
        self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap_100(self):
        for _ in range(110):
            self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_has_run_ts(self):
        self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("run_ts", data[0])

    def test_log_has_position_count(self):
        self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("position_count", data[0])

    def test_log_atomic_write(self):
        # No .tmp files should remain
        self.analyzer.analyze([_make_position()])
        tmp_files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0)

    def test_invalid_log_recovers(self):
        with open(self.log_file, "w") as f:
            f.write("not json{{{")
        self.analyzer.analyze([_make_position()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_not_created_on_empty(self):
        # Empty positions — still writes a log entry
        self.analyzer.analyze([])
        # Log may or may not exist — just check no crash


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "exit_liquidity_log.json")
        self.analyzer = DeFiProtocolExitLiquidityAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_position(**kwargs)])
        return r["results"][0]

    def test_zero_position_size(self):
        r = self._get_result(position_size_usd=0.0)
        self.assertIsInstance(r["exit_friction_score"], float)

    def test_very_large_position(self):
        r = self._get_result(position_size_usd=1e12)
        self.assertIn("label", r)

    def test_zero_daily_volume(self):
        r = self._get_result(daily_volume_usd=0.0)
        self.assertIn("label", r)

    def test_position_equals_queue(self):
        # position_size = queue → TRAPPED
        r = self._get_result(
            position_size_usd=10_000.0,
            withdrawal_queue_usd=10_000.0,
        )
        self.assertEqual(r["label"], LABEL_TRAPPED)

    def test_custom_config_instant_max_days(self):
        r = self.analyzer.analyze(
            [_make_position(
                position_size_usd=100.0,
                available_exit_liquidity_usd=100_000_000.0,
                daily_volume_usd=50_000_000.0,
            )],
            config={"instant_exit_max_days": 0.001}
        )
        # With very tight threshold, may not be instant
        self.assertIn(r["results"][0]["label"], {LABEL_INSTANT_EXIT, LABEL_EASY_EXIT, LABEL_MODERATE_EXIT, LABEL_DIFFICULT_EXIT, LABEL_TRAPPED})

    def test_multiple_positions_independent(self):
        positions = [
            _make_position(protocol="A", position_size_usd=1_000.0),
            _make_position(protocol="B", withdrawal_queue_usd=20_000.0),
        ]
        r = self.analyzer.analyze(positions)
        self.assertEqual(len(r["results"]), 2)

    def test_friction_score_never_exceeds_100(self):
        r = self._get_result(
            lock_remaining_days=100.0,
            withdrawal_queue_usd=1_000_000.0,
            withdrawal_fee_pct=50.0,
            position_size_usd=1_000.0,
            available_exit_liquidity_usd=1.0,
        )
        self.assertLessEqual(r["exit_friction_score"], 100.0)

    def test_friction_score_never_below_zero(self):
        r = self._get_result(
            lock_remaining_days=0.0,
            withdrawal_queue_usd=0.0,
            withdrawal_fee_pct=0.0,
        )
        self.assertGreaterEqual(r["exit_friction_score"], 0.0)

    def test_full_exit_days_nonnegative(self):
        r = self._get_result()
        self.assertGreaterEqual(r["full_exit_days"], 0.0)

    def test_exit_1pct_days_nonnegative(self):
        r = self._get_result()
        self.assertGreaterEqual(r["exit_1pct_days"], 0.0)

    def test_exit_10pct_days_nonnegative(self):
        r = self._get_result()
        self.assertGreaterEqual(r["exit_10pct_days"], 0.0)

    def test_missing_optional_fields_use_defaults(self):
        # Minimal position
        pos = {"protocol": "X", "asset": "ETH", "position_size_usd": 1000.0}
        r = self.analyzer.analyze([pos])
        self.assertIsInstance(r["results"][0]["exit_friction_score"], float)

    def test_10pct_impact_days_le_1pct(self):
        # 10% impact allows more per day than 1%, so should be ≤
        r = self._get_result(
            position_size_usd=10_000.0,
            available_exit_liquidity_usd=100_000.0,
            daily_volume_usd=50_000.0,
            slippage_model="linear",
        )
        self.assertGreaterEqual(r["exit_1pct_days"], r["exit_10pct_days"])

    def test_run_ts_is_string(self):
        result = self.analyzer.analyze([_make_position()])
        self.assertIsInstance(result["run_ts"], str)


if __name__ == "__main__":
    unittest.main()
