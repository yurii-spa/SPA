"""
Tests for MP-779: RebalanceCostEstimator
spa_core/tests/test_rebalance_cost_estimator.py

≥ 65 tests covering:
  - estimate_rebalance_cost() stateless function
  - RebalanceCostEstimator class
  - get_total_cost()
  - is_rebalance_worthwhile()
  - Gas cost math
  - Slippage cost math
  - Ring-buffer log (cap 100)
  - Atomic write
  - Edge cases: no trades, zero portfolio, threshold, missing protocols
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from spa_core.analytics.rebalance_cost_estimator import (
    DEFAULT_ETH_PRICE_USD,
    DEFAULT_GAS_UNITS_PER_TRADE,
    DEFAULT_MIN_REBALANCE_THRESHOLD_PCT,
    LOG_MAX_ENTRIES,
    RebalanceCostEstimator,
    _atomic_write,
    _load_log,
    estimate_rebalance_cost,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(
    current: dict = None,
    target: dict = None,
    portfolio_value: float = 100_000.0,
    gas_gwei: float = 20.0,
    slippage_bps: float = 5.0,
    eth_price: float = 3_500.0,
    threshold: float = 1.0,
) -> dict:
    if current is None:
        current = {"Aave": 50.0, "Compound": 50.0}
    if target is None:
        target = {"Aave": 40.0, "Compound": 60.0}
    return {
        "current_allocations": current,
        "target_allocations": target,
        "portfolio_value_usd": portfolio_value,
        "gas_price_gwei": gas_gwei,
        "avg_slippage_bps": slippage_bps,
        "eth_price_usd": eth_price,
        "min_rebalance_threshold_pct": threshold,
    }


def _base_result(**kwargs) -> dict:
    """Call estimate_rebalance_cost with sensible defaults."""
    return estimate_rebalance_cost(
        current_allocations=kwargs.get("current", {"Aave": 50.0, "Compound": 50.0}),
        target_allocations=kwargs.get("target", {"Aave": 40.0, "Compound": 60.0}),
        portfolio_value_usd=kwargs.get("portfolio_value", 100_000.0),
        gas_price_gwei=kwargs.get("gas_gwei", 20.0),
        avg_slippage_bps=kwargs.get("slippage_bps", 5.0),
        eth_price_usd=kwargs.get("eth_price", 3_500.0),
        min_rebalance_threshold_pct=kwargs.get("threshold", 1.0),
    )


# ---------------------------------------------------------------------------
# 1. estimate_rebalance_cost() — stateless function, return structure
# ---------------------------------------------------------------------------

class TestEstimateReturnStructure(unittest.TestCase):

    def test_required_keys_present(self):
        result = _base_result()
        required = {
            "trades_needed", "n_trades", "gas_cost_usd", "slippage_cost_usd",
            "total_cost_usd", "cost_as_pct_of_portfolio",
            "rebalance_worthwhile", "inputs_snapshot", "timestamp_utc",
        }
        self.assertTrue(required.issubset(result.keys()))

    def test_rebalance_worthwhile_is_none_by_default(self):
        result = _base_result()
        self.assertIsNone(result["rebalance_worthwhile"])

    def test_trades_needed_is_list(self):
        result = _base_result()
        self.assertIsInstance(result["trades_needed"], list)

    def test_n_trades_matches_trades_needed_len(self):
        result = _base_result()
        self.assertEqual(result["n_trades"], len(result["trades_needed"]))

    def test_timestamp_utc_is_positive_float(self):
        result = _base_result()
        self.assertIsInstance(result["timestamp_utc"], float)
        self.assertGreater(result["timestamp_utc"], 0)

    def test_inputs_snapshot_contains_portfolio_value(self):
        result = _base_result(portfolio_value=200_000.0)
        self.assertEqual(result["inputs_snapshot"]["portfolio_value_usd"], 200_000.0)

    def test_inputs_snapshot_contains_gas_price(self):
        result = _base_result(gas_gwei=30.0)
        self.assertEqual(result["inputs_snapshot"]["gas_price_gwei"], 30.0)

    def test_inputs_snapshot_contains_slippage(self):
        result = _base_result(slippage_bps=10.0)
        self.assertEqual(result["inputs_snapshot"]["avg_slippage_bps"], 10.0)


# ---------------------------------------------------------------------------
# 2. Trades identification
# ---------------------------------------------------------------------------

class TestTradesIdentification(unittest.TestCase):

    def test_no_trades_when_allocations_same(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.0, "Compound": 50.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertEqual(result["n_trades"], 0)

    def test_no_trades_within_threshold(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.5, "Compound": 49.5}  # diff = 0.5% < default 1%
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertEqual(result["n_trades"], 0)

    def test_trade_above_threshold(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}  # diff = 10%
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertEqual(result["n_trades"], 2)

    def test_new_protocol_in_target(self):
        current = {"Aave": 100.0}
        target = {"Aave": 70.0, "Morpho": 30.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        # Aave moves -30%, Morpho moves +30% → 2 trades
        self.assertEqual(result["n_trades"], 2)

    def test_protocol_removed_from_target(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 100.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        # Aave +50%, Compound -50% → 2 trades
        self.assertEqual(result["n_trades"], 2)

    def test_trade_value_usd_correct(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        # Aave: diff 10%, on 100k = $10k; Compound: diff 10% = $10k
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        for trade in result["trades_needed"]:
            self.assertAlmostEqual(trade["trade_value_usd"], 10_000.0, places=2)

    def test_trade_dict_keys(self):
        result = _base_result()
        if result["trades_needed"]:
            trade = result["trades_needed"][0]
            for key in ("protocol", "from_pct", "to_pct", "diff_pct", "trade_value_usd"):
                self.assertIn(key, trade)

    def test_diff_pct_sign_correct(self):
        current = {"Aave": 50.0}
        target = {"Aave": 70.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5, min_rebalance_threshold_pct=1.0)
        trade = result["trades_needed"][0]
        self.assertGreater(trade["diff_pct"], 0)  # increasing

    def test_diff_pct_negative_when_decreasing(self):
        current = {"Aave": 70.0}
        target = {"Aave": 50.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5, min_rebalance_threshold_pct=1.0)
        trade = result["trades_needed"][0]
        self.assertLess(trade["diff_pct"], 0)

    def test_custom_threshold_filters_small_move(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 44.0, "Compound": 56.0}  # diff = 6%
        # With threshold=10%, no trades
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5, min_rebalance_threshold_pct=10.0)
        self.assertEqual(result["n_trades"], 0)


# ---------------------------------------------------------------------------
# 3. Gas cost math
# ---------------------------------------------------------------------------

class TestGasCostMath(unittest.TestCase):

    def test_gas_cost_zero_trades(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.0, "Compound": 50.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertAlmostEqual(result["gas_cost_usd"], 0.0, places=4)

    def test_gas_cost_formula(self):
        # gas_cost = gas_gwei * 200000 * n_trades / 1e9 * eth_price
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        gas_gwei = 20.0
        eth_price = 3_500.0
        n_trades = 2
        expected = gas_gwei * 200_000 * n_trades / 1_000_000_000 * eth_price
        result = estimate_rebalance_cost(current, target, 100_000, gas_gwei, 5, eth_price_usd=eth_price)
        self.assertAlmostEqual(result["gas_cost_usd"], expected, places=4)

    def test_gas_cost_scales_with_trades(self):
        current = {"A": 33.0, "B": 33.0, "C": 34.0}
        target = {"A": 20.0, "B": 50.0, "C": 30.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 0)
        gas_per_trade = 20.0 * 200_000 / 1_000_000_000 * DEFAULT_ETH_PRICE_USD
        expected = gas_per_trade * result["n_trades"]
        self.assertAlmostEqual(result["gas_cost_usd"], expected, places=4)

    def test_gas_cost_higher_gwei_higher_cost(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        r1 = estimate_rebalance_cost(current, target, 100_000, 10, 5)
        r2 = estimate_rebalance_cost(current, target, 100_000, 40, 5)
        self.assertGreater(r2["gas_cost_usd"], r1["gas_cost_usd"])

    def test_gas_cost_higher_eth_higher_cost(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        r1 = estimate_rebalance_cost(current, target, 100_000, 20, 5, eth_price_usd=2_000)
        r2 = estimate_rebalance_cost(current, target, 100_000, 20, 5, eth_price_usd=5_000)
        self.assertGreater(r2["gas_cost_usd"], r1["gas_cost_usd"])


# ---------------------------------------------------------------------------
# 4. Slippage cost math
# ---------------------------------------------------------------------------

class TestSlippageCostMath(unittest.TestCase):

    def test_slippage_zero_bps(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 0)
        self.assertAlmostEqual(result["slippage_cost_usd"], 0.0, places=4)

    def test_slippage_formula(self):
        # slippage = sum(trade_value) * slippage_bps / 10000
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        portfolio_value = 100_000.0
        slippage_bps = 5.0
        # Each trade moves 10% of 100k = $10k; 2 trades → total $20k
        total_trade_value = 20_000.0
        expected_slippage = total_trade_value * slippage_bps / 10_000
        result = estimate_rebalance_cost(current, target, portfolio_value, 0, slippage_bps)
        self.assertAlmostEqual(result["slippage_cost_usd"], expected_slippage, places=4)

    def test_slippage_scales_with_bps(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        r1 = estimate_rebalance_cost(current, target, 100_000, 0, 5)
        r2 = estimate_rebalance_cost(current, target, 100_000, 0, 10)
        self.assertAlmostEqual(r2["slippage_cost_usd"], r1["slippage_cost_usd"] * 2, places=4)

    def test_slippage_scales_with_portfolio_value(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        r1 = estimate_rebalance_cost(current, target, 100_000, 0, 5)
        r2 = estimate_rebalance_cost(current, target, 200_000, 0, 5)
        self.assertAlmostEqual(r2["slippage_cost_usd"], r1["slippage_cost_usd"] * 2, places=4)


# ---------------------------------------------------------------------------
# 5. Total cost and cost_as_pct
# ---------------------------------------------------------------------------

class TestTotalCost(unittest.TestCase):

    def test_total_cost_equals_gas_plus_slippage(self):
        result = _base_result()
        expected = result["gas_cost_usd"] + result["slippage_cost_usd"]
        self.assertAlmostEqual(result["total_cost_usd"], expected, places=4)

    def test_total_cost_zero_when_no_trades(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.0, "Compound": 50.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertAlmostEqual(result["total_cost_usd"], 0.0, places=4)

    def test_cost_pct_of_portfolio(self):
        result = _base_result(portfolio_value=100_000)
        expected_pct = result["total_cost_usd"] / 100_000 * 100
        self.assertAlmostEqual(result["cost_as_pct_of_portfolio"], expected_pct, places=4)

    def test_cost_pct_zero_when_no_trades(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.0, "Compound": 50.0}
        result = estimate_rebalance_cost(current, target, 100_000, 20, 5)
        self.assertAlmostEqual(result["cost_as_pct_of_portfolio"], 0.0, places=6)

    def test_cost_pct_zero_portfolio_value(self):
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 40.0, "Compound": 60.0}
        result = estimate_rebalance_cost(current, target, 0.0, 20, 5)
        self.assertAlmostEqual(result["cost_as_pct_of_portfolio"], 0.0, places=6)

    def test_total_cost_nonnegative(self):
        result = _base_result()
        self.assertGreaterEqual(result["total_cost_usd"], 0.0)


# ---------------------------------------------------------------------------
# 6. RebalanceCostEstimator class
# ---------------------------------------------------------------------------

class TestRebalanceCostEstimatorClass(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.est = RebalanceCostEstimator(data_dir=self.tmpdir)

    def test_estimate_returns_dict(self):
        data = _make_data()
        result = self.est.estimate(data)
        self.assertIsInstance(result, dict)

    def test_get_total_cost_before_estimate(self):
        self.assertAlmostEqual(self.est.get_total_cost(), 0.0)

    def test_get_total_cost_after_estimate(self):
        self.est.estimate(_make_data())
        cost = self.est.get_total_cost()
        self.assertGreaterEqual(cost, 0.0)

    def test_get_total_cost_matches_result(self):
        result = self.est.estimate(_make_data())
        self.assertAlmostEqual(self.est.get_total_cost(), result["total_cost_usd"])

    def test_last_result_is_none_before_estimate(self):
        self.assertIsNone(self.est.last_result)

    def test_last_result_after_estimate(self):
        self.est.estimate(_make_data())
        self.assertIsNotNone(self.est.last_result)

    def test_estimate_overwrites_previous(self):
        self.est.estimate(_make_data(portfolio_value=100_000))
        cost1 = self.est.get_total_cost()
        self.est.estimate(_make_data(portfolio_value=200_000))
        cost2 = self.est.get_total_cost()
        # Costs should differ (higher portfolio = higher slippage)
        self.assertNotEqual(cost1, cost2)

    def test_estimate_picks_up_all_keys(self):
        data = {
            "current_allocations": {"Aave": 60.0, "Compound": 40.0},
            "target_allocations": {"Aave": 40.0, "Compound": 60.0},
            "portfolio_value_usd": 50_000.0,
            "gas_price_gwei": 15.0,
            "avg_slippage_bps": 3.0,
            "eth_price_usd": 4_000.0,
            "min_rebalance_threshold_pct": 2.0,
        }
        result = self.est.estimate(data)
        self.assertEqual(result["inputs_snapshot"]["eth_price_usd"], 4_000.0)

    def test_estimate_default_eth_price_when_missing(self):
        data = _make_data()
        del data["eth_price_usd"]
        result = self.est.estimate(data)
        self.assertEqual(result["inputs_snapshot"]["eth_price_usd"], DEFAULT_ETH_PRICE_USD)

    def test_estimate_default_threshold_when_missing(self):
        data = _make_data()
        del data["min_rebalance_threshold_pct"]
        result = self.est.estimate(data)
        self.assertEqual(
            result["inputs_snapshot"]["min_rebalance_threshold_pct"],
            DEFAULT_MIN_REBALANCE_THRESHOLD_PCT,
        )

    def test_save_creates_file(self):
        self.est.estimate(_make_data())
        log_path = self.est.save()
        self.assertTrue(os.path.exists(log_path))

    def test_save_valid_json(self):
        self.est.estimate(_make_data())
        log_path = self.est.save()
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_save_without_estimate_raises(self):
        with self.assertRaises(RuntimeError):
            self.est.save()

    def test_save_appends_entry(self):
        self.est.estimate(_make_data(portfolio_value=100_000))
        self.est.save()
        self.est.estimate(_make_data(portfolio_value=200_000))
        self.est.save()
        log_path = os.path.join(self.tmpdir, "rebalance_cost_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_estimate_and_save_combined(self):
        result = self.est.estimate_and_save(_make_data())
        self.assertIn("trades_needed", result)
        log_path = os.path.join(self.tmpdir, "rebalance_cost_log.json")
        self.assertTrue(os.path.exists(log_path))


# ---------------------------------------------------------------------------
# 7. is_rebalance_worthwhile
# ---------------------------------------------------------------------------

class TestIsRebalanceWorthwhile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.est = RebalanceCostEstimator(data_dir=self.tmpdir)

    def test_worthwhile_when_gain_exceeds_cost(self):
        self.est.estimate(_make_data(gas_gwei=1.0, slippage_bps=1.0, portfolio_value=100_000))
        cost = self.est.get_total_cost()
        worthwhile = self.est.is_rebalance_worthwhile(cost + 1000.0)
        self.assertTrue(worthwhile)

    def test_not_worthwhile_when_gain_less_than_cost(self):
        self.est.estimate(_make_data(gas_gwei=100.0, slippage_bps=50.0, portfolio_value=100_000))
        cost = self.est.get_total_cost()
        worthwhile = self.est.is_rebalance_worthwhile(0.01)
        self.assertFalse(worthwhile)

    def test_not_worthwhile_when_gain_equals_cost(self):
        self.est.estimate(_make_data())
        cost = self.est.get_total_cost()
        worthwhile = self.est.is_rebalance_worthwhile(cost)
        self.assertFalse(worthwhile)  # gain > cost, not >=

    def test_worthwhile_updates_last_result(self):
        self.est.estimate(_make_data())
        self.est.is_rebalance_worthwhile(5000.0)
        self.assertIsNotNone(self.est.last_result["rebalance_worthwhile"])

    def test_worthwhile_stores_expected_gain(self):
        self.est.estimate(_make_data())
        self.est.is_rebalance_worthwhile(1234.56)
        self.assertAlmostEqual(self.est.last_result["expected_annual_gain_usd"], 1234.56, places=2)

    def test_worthwhile_returns_bool(self):
        self.est.estimate(_make_data())
        result = self.est.is_rebalance_worthwhile(500.0)
        self.assertIsInstance(result, bool)

    def test_zero_cost_always_worthwhile(self):
        # Same allocations → no trades → zero cost
        current = {"Aave": 50.0, "Compound": 50.0}
        target = {"Aave": 50.0, "Compound": 50.0}
        self.est.estimate({
            "current_allocations": current,
            "target_allocations": target,
            "portfolio_value_usd": 100_000,
            "gas_price_gwei": 20.0,
            "avg_slippage_bps": 5.0,
        })
        worthwhile = self.est.is_rebalance_worthwhile(0.01)
        self.assertTrue(worthwhile)

    def test_negative_gain_not_worthwhile(self):
        self.est.estimate(_make_data())
        worthwhile = self.est.is_rebalance_worthwhile(-100.0)
        self.assertFalse(worthwhile)


# ---------------------------------------------------------------------------
# 8. Ring-buffer
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_ring_buffer_capped_at_100(self):
        est = RebalanceCostEstimator(data_dir=self.tmpdir)
        for _ in range(110):
            est.estimate(_make_data())
            est.save()
        log_path = os.path.join(self.tmpdir, "rebalance_cost_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)

    def test_ring_buffer_exactly_100(self):
        est = RebalanceCostEstimator(data_dir=self.tmpdir)
        for _ in range(100):
            est.estimate(_make_data())
            est.save()
        log_path = os.path.join(self.tmpdir, "rebalance_cost_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        est = RebalanceCostEstimator(data_dir=self.tmpdir)
        # First 5 with specific portfolio value
        for _ in range(5):
            est.estimate(_make_data(portfolio_value=99_999.0))
            est.save()
        # Then 100 more with different value
        for _ in range(100):
            est.estimate(_make_data(portfolio_value=50_000.0))
            est.save()
        log_path = os.path.join(self.tmpdir, "rebalance_cost_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)
        for entry in data:
            self.assertEqual(entry["inputs_snapshot"]["portfolio_value_usd"], 50_000.0)


# ---------------------------------------------------------------------------
# 9. Atomic write helpers
# ---------------------------------------------------------------------------

class TestAtomicWriteHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, [{"key": "val"}])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_no_tmp_file_left(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, [])
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_atomic_write_round_trip(self):
        path = os.path.join(self.tmpdir, "out.json")
        payload = [{"a": 1, "b": "two"}]
        _atomic_write(path, payload)
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, payload)

    def test_atomic_write_overwrites(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, [1, 2, 3])
        _atomic_write(path, [4, 5])
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, [4, 5])

    def test_load_log_empty_for_missing(self):
        path = os.path.join(self.tmpdir, "nope.json")
        self.assertEqual(_load_log(path), [])

    def test_load_log_empty_for_bad_json(self):
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as fh:
            fh.write("{{{{NOT JSON")
        self.assertEqual(_load_log(path), [])

    def test_load_log_empty_for_non_list(self):
        path = os.path.join(self.tmpdir, "obj.json")
        with open(path, "w") as fh:
            json.dump({"key": "val"}, fh)
        self.assertEqual(_load_log(path), [])

    def test_load_log_returns_list(self):
        path = os.path.join(self.tmpdir, "log.json")
        payload = [{"x": 1}, {"y": 2}]
        with open(path, "w") as fh:
            json.dump(payload, fh)
        self.assertEqual(_load_log(path), payload)


# ---------------------------------------------------------------------------
# 10. Edge cases and constants
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_allocations_no_trades(self):
        result = estimate_rebalance_cost({}, {}, 100_000, 20, 5)
        self.assertEqual(result["n_trades"], 0)
        self.assertAlmostEqual(result["total_cost_usd"], 0.0, places=4)

    def test_large_portfolio_higher_slippage(self):
        r1 = estimate_rebalance_cost(
            {"A": 50.0, "B": 50.0}, {"A": 40.0, "B": 60.0},
            100_000, 0, 5
        )
        r2 = estimate_rebalance_cost(
            {"A": 50.0, "B": 50.0}, {"A": 40.0, "B": 60.0},
            1_000_000, 0, 5
        )
        self.assertGreater(r2["slippage_cost_usd"], r1["slippage_cost_usd"])

    def test_default_eth_price_constant(self):
        self.assertEqual(DEFAULT_ETH_PRICE_USD, 3_500.0)

    def test_default_gas_units_constant(self):
        self.assertEqual(DEFAULT_GAS_UNITS_PER_TRADE, 200_000)

    def test_default_threshold_constant(self):
        self.assertEqual(DEFAULT_MIN_REBALANCE_THRESHOLD_PCT, 1.0)

    def test_log_max_entries_constant(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)

    def test_single_trade_cost_calculation(self):
        # Only one protocol changes significantly
        current = {"Aave": 100.0}
        target = {"Aave": 60.0, "Morpho": 40.0}
        gas_gwei = 10.0
        eth_price = 4_000.0
        slippage_bps = 5.0
        portfolio = 100_000.0
        result = estimate_rebalance_cost(
            current, target, portfolio, gas_gwei, slippage_bps,
            eth_price_usd=eth_price, min_rebalance_threshold_pct=1.0
        )
        # 2 trades: Aave -40%, Morpho +40%
        n = 2
        expected_gas = gas_gwei * 200_000 * n / 1e9 * eth_price
        total_trade_val = 2 * 0.40 * portfolio  # 40% each side
        expected_slip = total_trade_val * slippage_bps / 10_000
        self.assertAlmostEqual(result["gas_cost_usd"], expected_gas, places=4)
        self.assertAlmostEqual(result["slippage_cost_usd"], expected_slip, places=4)

    def test_cost_as_pct_is_float(self):
        result = _base_result()
        self.assertIsInstance(result["cost_as_pct_of_portfolio"], float)

    def test_trade_value_nonnegative(self):
        result = _base_result()
        for trade in result["trades_needed"]:
            self.assertGreaterEqual(trade["trade_value_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
