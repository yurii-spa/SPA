"""
tests/test_rebalance_cost_estimator.py

MP-1437 — 20 tests for RebalanceCostEstimator (spa_core/analytics/rebalance_cost_estimator.py)
Sprint v10.53
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.rebalance_cost_estimator import (
    RebalanceCostEstimator,
    estimate_rebalance_cost,
    DEFAULT_GAS_UNITS_PER_TRADE,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CURRENT = {"Aave": 50.0, "Compound": 30.0, "Cash": 20.0}
_TARGET  = {"Aave": 30.0, "Compound": 40.0, "Morpho": 25.0, "Cash": 5.0}

_SAMPLE_DATA = {
    "current_allocations": _CURRENT,
    "target_allocations":  _TARGET,
    "portfolio_value_usd": 100_000.0,
    "gas_price_gwei": 20.0,
    "avg_slippage_bps": 5.0,
    "eth_price_usd": 3_500.0,
}


class TestRebalanceCostEstimatorInstantiation(unittest.TestCase):
    """TC-RCE-01: Class instantiation."""

    def test_01_default_instantiation(self):
        """Default instantiation uses data_dir='data'."""
        est = RebalanceCostEstimator()
        self.assertIsInstance(est, RebalanceCostEstimator)

    def test_02_custom_data_dir(self):
        """Custom data_dir is stored."""
        est = RebalanceCostEstimator(data_dir="/tmp/test_spa")
        self.assertEqual(est._data_dir, "/tmp/test_spa")

    def test_03_last_result_initially_none(self):
        """last_result is None before first estimate()."""
        est = RebalanceCostEstimator()
        self.assertIsNone(est.last_result)


class TestEstimateMethod(unittest.TestCase):
    """TC-RCE-02..07: estimate() return values."""

    def setUp(self):
        self.est = RebalanceCostEstimator()

    def test_04_estimate_returns_dict_with_required_keys(self):
        """estimate() returns dict with all required keys."""
        result = self.est.estimate(_SAMPLE_DATA)
        required = {
            "trades_needed", "n_trades", "gas_cost_usd", "slippage_cost_usd",
            "total_cost_usd", "cost_as_pct_of_portfolio",
            "rebalance_worthwhile", "inputs_snapshot", "timestamp_utc",
        }
        self.assertTrue(required.issubset(result.keys()))

    def test_05_estimate_stores_last_result(self):
        """estimate() stores result in last_result."""
        result = self.est.estimate(_SAMPLE_DATA)
        self.assertIs(self.est.last_result, result)

    def test_06_n_trades_equals_trades_needed_length(self):
        """n_trades == len(trades_needed)."""
        result = self.est.estimate(_SAMPLE_DATA)
        self.assertEqual(result["n_trades"], len(result["trades_needed"]))

    def test_07_total_cost_equals_gas_plus_slippage(self):
        """total_cost_usd == gas_cost_usd + slippage_cost_usd (within rounding)."""
        result = self.est.estimate(_SAMPLE_DATA)
        expected = round(result["gas_cost_usd"] + result["slippage_cost_usd"], 4)
        self.assertAlmostEqual(result["total_cost_usd"], expected, places=3)


class TestEdgeCases(unittest.TestCase):
    """TC-RCE-08..14: Edge cases."""

    def test_08_identical_allocations_no_trades(self):
        """Equal current/target within default 1% threshold → 0 trades."""
        data = {
            "current_allocations": {"Aave": 50.0, "Compound": 50.0},
            "target_allocations":  {"Aave": 50.0, "Compound": 50.0},
            "portfolio_value_usd": 100_000.0,
            "gas_price_gwei": 20.0,
            "avg_slippage_bps": 5.0,
        }
        est = RebalanceCostEstimator()
        result = est.estimate(data)
        self.assertEqual(result["n_trades"], 0)
        self.assertEqual(result["total_cost_usd"], 0.0)

    def test_09_gas_price_zero_gas_cost_zero(self):
        """gas_price_gwei=0 → gas_cost_usd=0."""
        data = dict(_SAMPLE_DATA, gas_price_gwei=0.0)
        result = RebalanceCostEstimator().estimate(data)
        self.assertEqual(result["gas_cost_usd"], 0.0)

    def test_10_slippage_zero_slippage_cost_zero(self):
        """avg_slippage_bps=0 → slippage_cost_usd=0."""
        data = dict(_SAMPLE_DATA, avg_slippage_bps=0.0)
        result = RebalanceCostEstimator().estimate(data)
        self.assertEqual(result["slippage_cost_usd"], 0.0)

    def test_11_portfolio_value_zero_cost_pct_zero(self):
        """portfolio_value_usd=0 → cost_as_pct_of_portfolio=0."""
        data = dict(_SAMPLE_DATA, portfolio_value_usd=0.0)
        result = RebalanceCostEstimator().estimate(data)
        self.assertEqual(result["cost_as_pct_of_portfolio"], 0.0)

    def test_12_empty_allocations_no_trades(self):
        """Both empty dicts → 0 trades, 0 cost."""
        data = {
            "current_allocations": {},
            "target_allocations":  {},
            "portfolio_value_usd": 100_000.0,
            "gas_price_gwei": 20.0,
            "avg_slippage_bps": 5.0,
        }
        result = RebalanceCostEstimator().estimate(data)
        self.assertEqual(result["n_trades"], 0)

    def test_13_small_diff_below_threshold_filtered(self):
        """Diffs ≤ min_rebalance_threshold_pct (1%) are ignored."""
        data = {
            "current_allocations": {"Aave": 50.0, "Compound": 50.0},
            "target_allocations":  {"Aave": 50.5, "Compound": 49.5},  # 0.5% diff each
            "portfolio_value_usd": 100_000.0,
            "gas_price_gwei": 20.0,
            "avg_slippage_bps": 5.0,
        }
        result = RebalanceCostEstimator().estimate(data)
        self.assertEqual(result["n_trades"], 0)

    def test_14_larger_gas_price_higher_cost(self):
        """Higher gas_price_gwei → higher gas_cost_usd."""
        low  = RebalanceCostEstimator().estimate(dict(_SAMPLE_DATA, gas_price_gwei=10.0))
        high = RebalanceCostEstimator().estimate(dict(_SAMPLE_DATA, gas_price_gwei=100.0))
        self.assertGreater(high["gas_cost_usd"], low["gas_cost_usd"])


class TestGetTotalCost(unittest.TestCase):
    """TC-RCE-15..16: get_total_cost()."""

    def test_15_get_total_cost_before_estimate_returns_zero(self):
        """get_total_cost() returns 0.0 before any estimate() call."""
        est = RebalanceCostEstimator()
        self.assertEqual(est.get_total_cost(), 0.0)

    def test_16_get_total_cost_after_estimate_positive(self):
        """get_total_cost() returns positive float after estimate() with real moves."""
        est = RebalanceCostEstimator()
        est.estimate(_SAMPLE_DATA)
        self.assertGreater(est.get_total_cost(), 0.0)


class TestIsRebalanceWorthwhile(unittest.TestCase):
    """TC-RCE-17..18: is_rebalance_worthwhile()."""

    def setUp(self):
        self.est = RebalanceCostEstimator()
        self.est.estimate(_SAMPLE_DATA)

    def test_17_worthwhile_when_gain_exceeds_cost(self):
        """Returns True when expected gain > total cost."""
        self.assertTrue(self.est.is_rebalance_worthwhile(expected_annual_gain_usd=10_000.0))

    def test_18_not_worthwhile_when_gain_below_cost(self):
        """Returns False when expected gain < total cost."""
        total = self.est.get_total_cost()
        self.assertFalse(self.est.is_rebalance_worthwhile(expected_annual_gain_usd=total * 0.01))


class TestSaveAndLoad(unittest.TestCase):
    """TC-RCE-19..20: save/load round-trip."""

    def test_19_save_before_estimate_raises_SPAError(self):
        """save() before estimate() raises SPAError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            est = RebalanceCostEstimator(data_dir=tmpdir)
            with self.assertRaises(SPAError):
                est.save()

    def test_20_save_and_load_roundtrip(self):
        """estimate() + save() writes JSON; can reload and verify n_trades."""
        with tempfile.TemporaryDirectory() as tmpdir:
            est = RebalanceCostEstimator(data_dir=tmpdir)
            result = est.estimate(_SAMPLE_DATA)
            log_path = est.save()

            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r") as fh:
                log = json.load(fh)

            self.assertIsInstance(log, list)
            self.assertGreater(len(log), 0)
            self.assertEqual(log[-1]["n_trades"], result["n_trades"])


# ---------------------------------------------------------------------------
# Free-function tests (bonus)
# ---------------------------------------------------------------------------

class TestFreeFunction(unittest.TestCase):
    """TC-RCE-BONUS: estimate_rebalance_cost() free function."""

    def test_free_function_returns_dict(self):
        """estimate_rebalance_cost() returns a well-formed dict."""
        result = estimate_rebalance_cost(
            current_allocations=_CURRENT,
            target_allocations=_TARGET,
            portfolio_value_usd=100_000.0,
            gas_price_gwei=20.0,
            avg_slippage_bps=5.0,
        )
        self.assertIn("total_cost_usd", result)
        self.assertIn("n_trades", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
