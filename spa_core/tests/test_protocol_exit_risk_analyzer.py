"""
Tests for MP-810 ProtocolExitRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_exit_risk_analyzer -v
"""

import json
import os
import sys
import time
import unittest
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_exit_risk_analyzer import (
    analyze,
    analyze_and_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(
    protocol="Aave V3",
    position_usd=50_000.0,
    lock_remaining_days=0,
    early_exit_penalty_pct=0.0,
    token="USDC",
):
    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "lock_remaining_days": lock_remaining_days,
        "early_exit_penalty_pct": early_exit_penalty_pct,
        "token": token,
    }


def _mkt(
    pool_tvl_usd=1_000_000.0,
    daily_withdrawal_usd=10_000.0,
    slippage_1pct_depth_usd=100_000.0,
    withdrawal_fee_pct=0.1,
    gas_cost_usd=25.0,
):
    return {
        "pool_tvl_usd": pool_tvl_usd,
        "daily_withdrawal_usd": daily_withdrawal_usd,
        "slippage_1pct_depth_usd": slippage_1pct_depth_usd,
        "withdrawal_fee_pct": withdrawal_fee_pct,
        "gas_cost_usd": gas_cost_usd,
    }


# ---------------------------------------------------------------------------
# 1. Return-structure tests
# ---------------------------------------------------------------------------
class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.result = analyze(_pos(), _mkt())

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_position_usd(self):
        self.assertIn("position_usd", self.result)

    def test_has_is_locked(self):
        self.assertIn("is_locked", self.result)

    def test_has_lock_remaining_days(self):
        self.assertIn("lock_remaining_days", self.result)

    def test_has_costs(self):
        self.assertIn("costs", self.result)

    def test_costs_has_early_exit_penalty_usd(self):
        self.assertIn("early_exit_penalty_usd", self.result["costs"])

    def test_costs_has_withdrawal_fee_usd(self):
        self.assertIn("withdrawal_fee_usd", self.result["costs"])

    def test_costs_has_estimated_slippage_usd(self):
        self.assertIn("estimated_slippage_usd", self.result["costs"])

    def test_costs_has_gas_cost_usd(self):
        self.assertIn("gas_cost_usd", self.result["costs"])

    def test_costs_has_total_exit_cost_usd(self):
        self.assertIn("total_exit_cost_usd", self.result["costs"])

    def test_costs_has_exit_cost_pct(self):
        self.assertIn("exit_cost_pct", self.result["costs"])

    def test_has_liquidity(self):
        self.assertIn("liquidity", self.result)

    def test_liquidity_has_days_to_exit(self):
        self.assertIn("days_to_exit", self.result["liquidity"])

    def test_liquidity_has_can_exit_without_slippage(self):
        self.assertIn("can_exit_without_slippage", self.result["liquidity"])

    def test_liquidity_has_position_as_pct_of_pool(self):
        self.assertIn("position_as_pct_of_pool", self.result["liquidity"])

    def test_liquidity_has_liquidity_risk(self):
        self.assertIn("liquidity_risk", self.result["liquidity"])

    def test_has_exit_strategy(self):
        self.assertIn("exit_strategy", self.result)

    def test_has_recommended_exit_size_usd(self):
        self.assertIn("recommended_exit_size_usd", self.result)

    def test_has_reason(self):
        self.assertIn("reason", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_reason_is_string(self):
        self.assertIsInstance(self.result["reason"], str)

    def test_reason_nonempty(self):
        self.assertGreater(len(self.result["reason"]), 0)

    def test_is_locked_is_bool(self):
        self.assertIsInstance(self.result["is_locked"], bool)


# ---------------------------------------------------------------------------
# 2. Lock / is_locked tests
# ---------------------------------------------------------------------------
class TestLockBehavior(unittest.TestCase):

    def test_not_locked_when_zero_days(self):
        r = analyze(_pos(lock_remaining_days=0), _mkt())
        self.assertFalse(r["is_locked"])

    def test_locked_when_positive_days(self):
        r = analyze(_pos(lock_remaining_days=7), _mkt())
        self.assertTrue(r["is_locked"])

    def test_early_exit_penalty_zero_when_not_locked(self):
        r = analyze(_pos(lock_remaining_days=0, early_exit_penalty_pct=5.0), _mkt())
        self.assertEqual(r["costs"]["early_exit_penalty_usd"], 0.0)

    def test_early_exit_penalty_computed_when_locked(self):
        r = analyze(_pos(position_usd=10_000, lock_remaining_days=30, early_exit_penalty_pct=2.0), _mkt())
        self.assertAlmostEqual(r["costs"]["early_exit_penalty_usd"], 200.0)

    def test_lock_remaining_days_preserved(self):
        r = analyze(_pos(lock_remaining_days=14), _mkt())
        self.assertEqual(r["lock_remaining_days"], 14)


# ---------------------------------------------------------------------------
# 3. Cost computation tests
# ---------------------------------------------------------------------------
class TestCostComputation(unittest.TestCase):

    def test_withdrawal_fee_computed(self):
        r = analyze(_pos(position_usd=10_000), _mkt(withdrawal_fee_pct=1.0))
        self.assertAlmostEqual(r["costs"]["withdrawal_fee_usd"], 100.0)

    def test_gas_cost_preserved(self):
        r = analyze(_pos(), _mkt(gas_cost_usd=50.0))
        self.assertAlmostEqual(r["costs"]["gas_cost_usd"], 50.0)

    def test_no_slippage_when_position_within_depth(self):
        r = analyze(_pos(position_usd=50_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertEqual(r["costs"]["estimated_slippage_usd"], 0.0)

    def test_slippage_on_excess_at_2pct(self):
        # position=120_000, depth=100_000 → excess=20_000 → 2% → 400
        r = analyze(_pos(position_usd=120_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertAlmostEqual(r["costs"]["estimated_slippage_usd"], 400.0)

    def test_total_cost_sums_all_components(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=0, early_exit_penalty_pct=0.0),
            _mkt(withdrawal_fee_pct=1.0, gas_cost_usd=50.0, slippage_1pct_depth_usd=100_000)
        )
        expected = 100.0 + 50.0  # fee + gas, no slippage, no penalty
        self.assertAlmostEqual(r["costs"]["total_exit_cost_usd"], expected)

    def test_exit_cost_pct_formula(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=0),
            _mkt(withdrawal_fee_pct=1.0, gas_cost_usd=0.0, slippage_1pct_depth_usd=100_000)
        )
        # total_cost = 100, position=10_000 → 1.0%
        self.assertAlmostEqual(r["costs"]["exit_cost_pct"], 1.0)

    def test_exit_cost_pct_zero_when_position_zero(self):
        r = analyze(_pos(position_usd=0), _mkt())
        self.assertEqual(r["costs"]["exit_cost_pct"], 0.0)

    def test_penalty_included_in_total_when_locked(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=30, early_exit_penalty_pct=5.0),
            _mkt(withdrawal_fee_pct=0.0, gas_cost_usd=0.0, slippage_1pct_depth_usd=100_000)
        )
        # penalty=500, fee=0, gas=0, slippage=0 → total=500
        self.assertAlmostEqual(r["costs"]["total_exit_cost_usd"], 500.0)


# ---------------------------------------------------------------------------
# 4. Liquidity tests
# ---------------------------------------------------------------------------
class TestLiquidity(unittest.TestCase):

    def test_days_to_exit_basic(self):
        # position=50_000, daily=10_000 → 5 days
        r = analyze(_pos(position_usd=50_000), _mkt(daily_withdrawal_usd=10_000))
        self.assertAlmostEqual(r["liquidity"]["days_to_exit"], 5.0)

    def test_days_to_exit_minimum_one(self):
        # position=100, daily=100_000 → raw=0.001 → min 1
        r = analyze(_pos(position_usd=100), _mkt(daily_withdrawal_usd=100_000))
        self.assertAlmostEqual(r["liquidity"]["days_to_exit"], 1.0)

    def test_can_exit_without_slippage_true(self):
        r = analyze(_pos(position_usd=50_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertTrue(r["liquidity"]["can_exit_without_slippage"])

    def test_can_exit_without_slippage_false(self):
        r = analyze(_pos(position_usd=150_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertFalse(r["liquidity"]["can_exit_without_slippage"])

    def test_can_exit_without_slippage_exactly_at_depth(self):
        r = analyze(_pos(position_usd=100_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertTrue(r["liquidity"]["can_exit_without_slippage"])

    def test_position_as_pct_of_pool_basic(self):
        r = analyze(_pos(position_usd=100_000), _mkt(pool_tvl_usd=1_000_000))
        self.assertAlmostEqual(r["liquidity"]["position_as_pct_of_pool"], 10.0)

    def test_position_as_pct_of_pool_zero_when_tvl_zero(self):
        r = analyze(_pos(position_usd=50_000), _mkt(pool_tvl_usd=0))
        self.assertEqual(r["liquidity"]["position_as_pct_of_pool"], 0.0)

    def test_liquidity_risk_low(self):
        # days=1, pct=5% → LOW
        r = analyze(_pos(position_usd=50_000), _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=50_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "LOW")

    def test_liquidity_risk_medium_by_days(self):
        # days=5 > 3
        r = analyze(_pos(position_usd=50_000), _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=10_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "MEDIUM")

    def test_liquidity_risk_medium_by_pool_pct(self):
        # pct=7% > 5% but ≤ 10%, days ≤ 3
        r = analyze(_pos(position_usd=70_000), _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=100_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "MEDIUM")

    def test_liquidity_risk_high_by_days(self):
        # days=10 > 7
        r = analyze(_pos(position_usd=100_000), _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=10_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "HIGH")

    def test_liquidity_risk_high_by_pool_pct(self):
        # pct=15% > 10% ≤ 20%, days low
        r = analyze(_pos(position_usd=150_000), _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=200_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "HIGH")

    def test_liquidity_risk_critical_by_days(self):
        # days=40 > 30
        r = analyze(_pos(position_usd=400_000), _mkt(pool_tvl_usd=100_000_000, daily_withdrawal_usd=10_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "CRITICAL")

    def test_liquidity_risk_critical_by_pool_pct(self):
        # pct=25% > 20%
        r = analyze(_pos(position_usd=250_000), _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=1_000_000))
        self.assertEqual(r["liquidity"]["liquidity_risk"], "CRITICAL")


# ---------------------------------------------------------------------------
# 5. Exit strategy tests
# ---------------------------------------------------------------------------
class TestExitStrategy(unittest.TestCase):

    def _exit_now_pos(self):
        """Position that should EXIT_NOW: unlocked, low cost, low liquidity risk."""
        return _pos(position_usd=10_000, lock_remaining_days=0, early_exit_penalty_pct=0.0)

    def _exit_now_mkt(self):
        return _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=1_000_000,
                    slippage_1pct_depth_usd=1_000_000, withdrawal_fee_pct=0.1, gas_cost_usd=5.0)

    def test_exit_now_basic(self):
        r = analyze(self._exit_now_pos(), self._exit_now_mkt())
        self.assertEqual(r["exit_strategy"], "EXIT_NOW")

    def test_exit_now_recommended_size_full_position(self):
        r = analyze(self._exit_now_pos(), self._exit_now_mkt())
        self.assertAlmostEqual(r["recommended_exit_size_usd"], r["position_usd"])

    def test_wait_unlock_when_penalty_exceeds_fee_plus_gas(self):
        # penalty=500 > fee(10) + gas(25) = 35
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=30, early_exit_penalty_pct=5.0),
            _mkt(withdrawal_fee_pct=0.1, gas_cost_usd=25.0, slippage_1pct_depth_usd=1_000_000,
                 daily_withdrawal_usd=1_000_000, pool_tvl_usd=10_000_000),
        )
        self.assertEqual(r["exit_strategy"], "WAIT_UNLOCK")

    def test_wait_unlock_recommended_size_is_zero(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=30, early_exit_penalty_pct=5.0),
            _mkt(withdrawal_fee_pct=0.1, gas_cost_usd=25.0, slippage_1pct_depth_usd=1_000_000,
                 daily_withdrawal_usd=1_000_000, pool_tvl_usd=10_000_000),
        )
        self.assertEqual(r["recommended_exit_size_usd"], 0.0)

    def test_partial_exit_when_high_liquidity_risk_unlocked(self):
        # pct=25% → CRITICAL liquidity, not locked
        r = analyze(
            _pos(position_usd=250_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=1_000_000,
                 slippage_1pct_depth_usd=100_000, withdrawal_fee_pct=0.1, gas_cost_usd=25.0),
        )
        self.assertEqual(r["exit_strategy"], "PARTIAL_EXIT")

    def test_partial_exit_recommended_size_min_depth_or_half(self):
        # depth=100_000, half of 250_000=125_000 → min=100_000
        r = analyze(
            _pos(position_usd=250_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=1_000_000,
                 slippage_1pct_depth_usd=100_000, withdrawal_fee_pct=0.1, gas_cost_usd=25.0),
        )
        self.assertAlmostEqual(r["recommended_exit_size_usd"], 100_000.0)

    def test_partial_exit_when_half_smaller_than_depth(self):
        # position=50_000, half=25_000, depth=100_000 → min=25_000
        r = analyze(
            _pos(position_usd=50_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=100_000, daily_withdrawal_usd=5_000,
                 slippage_1pct_depth_usd=100_000, withdrawal_fee_pct=0.1, gas_cost_usd=25.0),
        )
        # days=10 → HIGH, pct=50% → CRITICAL
        self.assertEqual(r["exit_strategy"], "PARTIAL_EXIT")
        self.assertAlmostEqual(r["recommended_exit_size_usd"], 25_000.0)

    def test_hold_when_cost_too_high_unlocked(self):
        # exit_cost_pct >= 3%, LOW liquidity risk
        # position=10_000, fee=5%, gas=300 → cost=500+300=800=8% > 3%
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=0, early_exit_penalty_pct=0.0),
            _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=5_000_000,
                 slippage_1pct_depth_usd=1_000_000, withdrawal_fee_pct=5.0, gas_cost_usd=300.0),
        )
        self.assertEqual(r["exit_strategy"], "HOLD")

    def test_hold_recommended_size_is_zero(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=5_000_000,
                 slippage_1pct_depth_usd=1_000_000, withdrawal_fee_pct=5.0, gas_cost_usd=300.0),
        )
        self.assertEqual(r["recommended_exit_size_usd"], 0.0)

    def test_not_locked_penalty_zero(self):
        r = analyze(_pos(lock_remaining_days=0, early_exit_penalty_pct=10.0), _mkt())
        self.assertEqual(r["costs"]["early_exit_penalty_usd"], 0.0)

    def test_exit_strategy_values_valid(self):
        valid = {"EXIT_NOW", "WAIT_UNLOCK", "PARTIAL_EXIT", "HOLD"}
        r = analyze(_pos(), _mkt())
        self.assertIn(r["exit_strategy"], valid)

    def test_liquidity_risk_values_valid(self):
        valid = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        r = analyze(_pos(), _mkt())
        self.assertIn(r["liquidity"]["liquidity_risk"], valid)


# ---------------------------------------------------------------------------
# 6. Protocol / position field tests
# ---------------------------------------------------------------------------
class TestFields(unittest.TestCase):

    def test_protocol_preserved(self):
        r = analyze(_pos(protocol="Morpho Blue"), _mkt())
        self.assertEqual(r["protocol"], "Morpho Blue")

    def test_position_usd_preserved(self):
        r = analyze(_pos(position_usd=99_999.0), _mkt())
        self.assertAlmostEqual(r["position_usd"], 99_999.0)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_pos(), _mkt())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_config_none_uses_defaults(self):
        r1 = analyze(_pos(), _mkt(), config=None)
        r2 = analyze(_pos(), _mkt(), config={})
        self.assertEqual(r1["exit_strategy"], r2["exit_strategy"])

    def test_extra_config_ignored(self):
        r = analyze(_pos(), _mkt(), config={"unknown": 42})
        self.assertIn("exit_strategy", r)


# ---------------------------------------------------------------------------
# 7. Slippage edge cases
# ---------------------------------------------------------------------------
class TestSlippageEdgeCases(unittest.TestCase):

    def test_slippage_exactly_at_depth_is_zero(self):
        r = analyze(_pos(position_usd=100_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertEqual(r["costs"]["estimated_slippage_usd"], 0.0)

    def test_slippage_one_unit_above_depth(self):
        r = analyze(_pos(position_usd=100_001), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertAlmostEqual(r["costs"]["estimated_slippage_usd"], 0.02, places=2)

    def test_slippage_large_excess(self):
        # position=300_000, depth=100_000 → excess=200_000 × 2% = 4_000
        r = analyze(_pos(position_usd=300_000), _mkt(slippage_1pct_depth_usd=100_000))
        self.assertAlmostEqual(r["costs"]["estimated_slippage_usd"], 4_000.0)

    def test_zero_depth_all_slippage(self):
        # depth=0 → all is excess → 2% of position
        r = analyze(_pos(position_usd=10_000), _mkt(slippage_1pct_depth_usd=0))
        self.assertAlmostEqual(r["costs"]["estimated_slippage_usd"], 200.0)


# ---------------------------------------------------------------------------
# 8. Log / IO tests
# ---------------------------------------------------------------------------
class TestLogging(unittest.TestCase):

    def test_log_result_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            r = analyze(_pos(), _mkt())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_result_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            r = analyze(_pos(), _mkt())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_appends_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            for i in range(5):
                r = analyze(_pos(protocol=f"P{i}"), _mkt())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            for i in range(120):
                r = analyze(_pos(protocol=f"P{i}"), _mkt())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_most_recent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            for i in range(110):
                r = analyze(_pos(protocol=f"PROTO_{i}"), _mkt())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[-1]["protocol"], "PROTO_109")
            self.assertEqual(data[0]["protocol"], "PROTO_10")

    def test_analyze_and_log_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = analyze_and_log(_pos(), _mkt(), log_path=path)
            self.assertIn("protocol", r)

    def test_analyze_and_log_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            analyze_and_log(_pos(), _mkt(), log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_handles_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "exit_log.json")
            with open(path, "w") as f:
                f.write("{invalid json}}}")
            r = analyze(_pos(), _mkt())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 9. Reason string tests
# ---------------------------------------------------------------------------
class TestReasonString(unittest.TestCase):

    def test_exit_now_reason_mentions_cost(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=10_000_000, daily_withdrawal_usd=5_000_000,
                 slippage_1pct_depth_usd=1_000_000, withdrawal_fee_pct=0.1, gas_cost_usd=5.0),
        )
        # Should be EXIT_NOW; reason mentions cost
        if r["exit_strategy"] == "EXIT_NOW":
            self.assertIn("cost", r["reason"].lower())

    def test_wait_unlock_reason_mentions_lock(self):
        r = analyze(
            _pos(position_usd=10_000, lock_remaining_days=30, early_exit_penalty_pct=5.0),
            _mkt(withdrawal_fee_pct=0.1, gas_cost_usd=25.0, slippage_1pct_depth_usd=1_000_000,
                 daily_withdrawal_usd=1_000_000, pool_tvl_usd=10_000_000),
        )
        self.assertIn("lock", r["reason"].lower())

    def test_partial_exit_reason_mentions_liquidity(self):
        r = analyze(
            _pos(position_usd=250_000, lock_remaining_days=0),
            _mkt(pool_tvl_usd=1_000_000, daily_withdrawal_usd=1_000_000,
                 slippage_1pct_depth_usd=100_000, withdrawal_fee_pct=0.1, gas_cost_usd=25.0),
        )
        self.assertEqual(r["exit_strategy"], "PARTIAL_EXIT")
        self.assertIn("liquidit", r["reason"].lower())

    def test_reason_always_nonempty(self):
        for locked in [0, 30]:
            r = analyze(_pos(lock_remaining_days=locked), _mkt())
            self.assertGreater(len(r["reason"]), 0)


# ---------------------------------------------------------------------------
# 10. Numeric edge cases
# ---------------------------------------------------------------------------
class TestNumericEdgeCases(unittest.TestCase):

    def test_zero_position_usd(self):
        r = analyze(_pos(position_usd=0), _mkt())
        self.assertEqual(r["position_usd"], 0.0)
        self.assertEqual(r["costs"]["exit_cost_pct"], 0.0)

    def test_zero_daily_withdrawal_gives_large_days(self):
        r = analyze(_pos(position_usd=10_000), _mkt(daily_withdrawal_usd=0))
        self.assertEqual(r["liquidity"]["days_to_exit"], float("inf"))

    def test_very_large_position(self):
        r = analyze(_pos(position_usd=1e9), _mkt(pool_tvl_usd=1e9, daily_withdrawal_usd=1e6))
        self.assertIn(r["liquidity"]["liquidity_risk"], {"HIGH", "CRITICAL"})

    def test_withdrawal_fee_pct_zero(self):
        r = analyze(_pos(position_usd=10_000), _mkt(withdrawal_fee_pct=0.0, gas_cost_usd=0.0,
                                                    slippage_1pct_depth_usd=1_000_000))
        self.assertAlmostEqual(r["costs"]["withdrawal_fee_usd"], 0.0)
        self.assertAlmostEqual(r["costs"]["total_exit_cost_usd"], 0.0)

    def test_gas_cost_zero(self):
        r = analyze(_pos(), _mkt(gas_cost_usd=0.0))
        self.assertAlmostEqual(r["costs"]["gas_cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
