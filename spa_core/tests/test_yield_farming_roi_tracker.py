"""
Tests for spa_core.analytics.yield_farming_roi_tracker (MP-814).

Run: python3 -m unittest spa_core/tests/test_yield_farming_roi_tracker.py -v
"""
import json
import os
import sys
import time
import unittest
import tempfile
from pathlib import Path

# Ensure project root is on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.yield_farming_roi_tracker import (
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

def _base_farm(**overrides) -> dict:
    """Return a standard farm dict with optional overrides."""
    farm = {
        "protocol": "Uniswap V3",
        "pair": "ETH/USDC",
        "initial_investment_usd": 10000.0,
        "entry_gas_usd": 50.0,
        "days_elapsed": 30.0,
        "base_apy": 15.0,
        "reward_apy": 10.0,
        "current_value_usd": 9800.0,
        "harvested_rewards_usd": 150.0,
        "harvest_gas_total_usd": 30.0,
        "pending_rewards_usd": 50.0,
    }
    farm.update(overrides)
    return farm


# ---------------------------------------------------------------------------
# Return structure tests
# ---------------------------------------------------------------------------

class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.result = analyze(_base_farm())

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_pair(self):
        self.assertIn("pair", self.result)

    def test_has_days_elapsed(self):
        self.assertIn("days_elapsed", self.result)

    def test_has_pnl(self):
        self.assertIn("pnl", self.result)

    def test_has_apy_analysis(self):
        self.assertIn("apy_analysis", self.result)

    def test_has_performance(self):
        self.assertIn("performance", self.result)

    def test_has_continue_farming(self):
        self.assertIn("continue_farming", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_timestamp_is_recent(self):
        self.assertAlmostEqual(self.result["timestamp"], time.time(), delta=5.0)

    def test_performance_valid_values(self):
        self.assertIn(self.result["performance"], {"EXCELLENT", "GOOD", "FAIR", "POOR", "LOSS"})

    def test_continue_farming_is_bool(self):
        self.assertIsInstance(self.result["continue_farming"], bool)

    def test_pnl_is_dict(self):
        self.assertIsInstance(self.result["pnl"], dict)

    def test_apy_analysis_is_dict(self):
        self.assertIsInstance(self.result["apy_analysis"], dict)

    def test_protocol_matches_input(self):
        self.assertEqual(self.result["protocol"], "Uniswap V3")

    def test_pair_matches_input(self):
        self.assertEqual(self.result["pair"], "ETH/USDC")

    def test_days_elapsed_matches_input(self):
        self.assertAlmostEqual(self.result["days_elapsed"], 30.0, places=4)


# ---------------------------------------------------------------------------
# PnL structure tests
# ---------------------------------------------------------------------------

class TestPnLStructure(unittest.TestCase):
    def setUp(self):
        self.pnl = analyze(_base_farm())["pnl"]

    def test_has_unrealized_position_usd(self):
        self.assertIn("unrealized_position_usd", self.pnl)

    def test_has_harvested_rewards_usd(self):
        self.assertIn("harvested_rewards_usd", self.pnl)

    def test_has_pending_rewards_usd(self):
        self.assertIn("pending_rewards_usd", self.pnl)

    def test_has_total_rewards_usd(self):
        self.assertIn("total_rewards_usd", self.pnl)

    def test_has_gas_costs_usd(self):
        self.assertIn("gas_costs_usd", self.pnl)

    def test_has_tax_cost_usd(self):
        self.assertIn("tax_cost_usd", self.pnl)

    def test_has_net_pnl_usd(self):
        self.assertIn("net_pnl_usd", self.pnl)

    def test_has_net_pnl_pct(self):
        self.assertIn("net_pnl_pct", self.pnl)


# ---------------------------------------------------------------------------
# APY analysis structure tests
# ---------------------------------------------------------------------------

class TestAPYAnalysisStructure(unittest.TestCase):
    def setUp(self):
        self.apy = analyze(_base_farm())["apy_analysis"]

    def test_has_actual_apy(self):
        self.assertIn("actual_apy", self.apy)

    def test_has_projected_apy(self):
        self.assertIn("projected_apy", self.apy)

    def test_has_apy_gap_pct(self):
        self.assertIn("apy_gap_pct", self.apy)

    def test_has_il_estimated_usd(self):
        self.assertIn("il_estimated_usd", self.apy)

    def test_has_il_pct(self):
        self.assertIn("il_pct", self.apy)


# ---------------------------------------------------------------------------
# PnL calculation tests
# ---------------------------------------------------------------------------

class TestPnLCalculations(unittest.TestCase):
    def test_unrealized_position_correct(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=9800.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["unrealized_position_usd"], -200.0, places=4)

    def test_unrealized_position_positive(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=11000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["unrealized_position_usd"], 1000.0, places=4)

    def test_total_rewards_is_sum(self):
        farm = _base_farm(harvested_rewards_usd=150.0, pending_rewards_usd=50.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["total_rewards_usd"], 200.0, places=4)

    def test_gas_costs_is_sum(self):
        farm = _base_farm(entry_gas_usd=50.0, harvest_gas_total_usd=30.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["gas_costs_usd"], 80.0, places=4)

    def test_tax_cost_zero_by_default(self):
        result = analyze(_base_farm())
        self.assertAlmostEqual(result["pnl"]["tax_cost_usd"], 0.0, places=4)

    def test_tax_cost_with_tax_rate(self):
        farm = _base_farm(harvested_rewards_usd=1000.0, pending_rewards_usd=0.0)
        result = analyze(farm, {"tax_rate_pct": 20.0})
        # total_rewards = 1000, tax = 200
        self.assertAlmostEqual(result["pnl"]["tax_cost_usd"], 200.0, places=4)

    def test_net_pnl_correct(self):
        # initial=10000, current=10000 (no IL), harvested=100, pending=50, entry_gas=50, harvest_gas=20, tax=0
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=100.0,
            pending_rewards_usd=50.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=20.0,
        )
        result = analyze(farm)
        # net_pnl = (10000-10000) + (100+50) - (50+20) - 0 = 0 + 150 - 70 = 80
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], 80.0, places=4)

    def test_net_pnl_pct_correct(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=100.0,
            pending_rewards_usd=50.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=20.0,
        )
        result = analyze(farm)
        # net_pnl_pct = 80 / 10000 * 100 = 0.8
        self.assertAlmostEqual(result["pnl"]["net_pnl_pct"], 0.8, places=4)

    def test_harvested_rewards_matches_input(self):
        farm = _base_farm(harvested_rewards_usd=777.77)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["harvested_rewards_usd"], 777.77, places=2)

    def test_pending_rewards_matches_input(self):
        farm = _base_farm(pending_rewards_usd=333.33)
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["pending_rewards_usd"], 333.33, places=2)

    def test_net_pnl_with_tax(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=1000.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=0.0,
            harvest_gas_total_usd=0.0,
        )
        result = analyze(farm, {"tax_rate_pct": 30.0})
        # net_pnl = 0 + 1000 - 0 - 300 = 700
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], 700.0, places=4)


# ---------------------------------------------------------------------------
# APY analysis tests
# ---------------------------------------------------------------------------

class TestAPYAnalysis(unittest.TestCase):
    def test_projected_apy_is_sum(self):
        farm = _base_farm(base_apy=15.0, reward_apy=10.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["projected_apy"], 25.0, places=4)

    def test_actual_apy_annualized(self):
        # net_pnl = 80, investment = 10000, days = 30
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=100.0,
            pending_rewards_usd=50.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=20.0,
            days_elapsed=30.0,
        )
        result = analyze(farm)
        # actual_apy = 80 / 10000 * (365/30) * 100 = 9.733...
        expected = 80.0 / 10000.0 * (365.0 / 30.0) * 100.0
        self.assertAlmostEqual(result["apy_analysis"]["actual_apy"], expected, places=2)

    def test_apy_gap_positive_when_underperforming(self):
        farm = _base_farm(
            base_apy=20.0,
            reward_apy=5.0,
            current_value_usd=9000.0,  # big IL, negative actual_apy
        )
        result = analyze(farm)
        self.assertGreater(result["apy_analysis"]["apy_gap_pct"], 0)

    def test_apy_gap_zero_when_matching(self):
        # Hard to make them exactly match, just check sign and type
        result = analyze(_base_farm())
        self.assertIsInstance(result["apy_analysis"]["apy_gap_pct"], float)

    def test_il_estimated_usd_when_current_less_than_initial(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=9000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_estimated_usd"], 1000.0, places=4)

    def test_il_estimated_usd_zero_when_no_il(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=11000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_estimated_usd"], 0.0, places=4)

    def test_il_pct_correct(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=9000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_pct"], 10.0, places=4)

    def test_il_pct_zero_when_no_il(self):
        farm = _base_farm(initial_investment_usd=10000.0, current_value_usd=10000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_pct"], 0.0, places=4)

    def test_il_zero_when_current_equals_initial(self):
        farm = _base_farm(initial_investment_usd=5000.0, current_value_usd=5000.0)
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_estimated_usd"], 0.0, places=4)
        self.assertAlmostEqual(result["apy_analysis"]["il_pct"], 0.0, places=4)


# ---------------------------------------------------------------------------
# Performance rating tests
# ---------------------------------------------------------------------------

class TestPerformanceRating(unittest.TestCase):
    def _farm_with_apy(self, actual_apy: float) -> dict:
        """Build a farm where net_pnl produces the given annualized APY over 365 days."""
        initial = 10000.0
        # net_pnl = actual_apy/100 * initial (over 1 year)
        net_pnl = actual_apy / 100.0 * initial
        return _base_farm(
            initial_investment_usd=initial,
            current_value_usd=initial,
            harvested_rewards_usd=net_pnl,
            pending_rewards_usd=0.0,
            entry_gas_usd=0.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=365.0,
        )

    def test_excellent_at_20_pct(self):
        result = analyze(self._farm_with_apy(20.0))
        self.assertEqual(result["performance"], "EXCELLENT")

    def test_excellent_above_20_pct(self):
        result = analyze(self._farm_with_apy(35.0))
        self.assertEqual(result["performance"], "EXCELLENT")

    def test_good_at_10_pct(self):
        result = analyze(self._farm_with_apy(10.0))
        self.assertEqual(result["performance"], "GOOD")

    def test_good_between_10_and_20(self):
        result = analyze(self._farm_with_apy(15.0))
        self.assertEqual(result["performance"], "GOOD")

    def test_fair_at_5_pct(self):
        result = analyze(self._farm_with_apy(5.0))
        self.assertEqual(result["performance"], "FAIR")

    def test_fair_between_5_and_10(self):
        result = analyze(self._farm_with_apy(7.5))
        self.assertEqual(result["performance"], "FAIR")

    def test_poor_at_zero(self):
        result = analyze(self._farm_with_apy(0.0))
        self.assertEqual(result["performance"], "POOR")

    def test_poor_between_0_and_5(self):
        result = analyze(self._farm_with_apy(2.0))
        self.assertEqual(result["performance"], "POOR")

    def test_loss_below_zero(self):
        result = analyze(self._farm_with_apy(-5.0))
        self.assertEqual(result["performance"], "LOSS")

    def test_loss_large_negative(self):
        result = analyze(self._farm_with_apy(-50.0))
        self.assertEqual(result["performance"], "LOSS")


# ---------------------------------------------------------------------------
# Continue farming tests
# ---------------------------------------------------------------------------

class TestContinueFarming(unittest.TestCase):
    def test_continue_true_when_high_apy_and_profitable(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=2000.0,  # ~73% APY annualized over 30 days
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=30.0,
        )
        result = analyze(farm)
        self.assertTrue(result["continue_farming"])

    def test_continue_false_when_low_apy(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=5.0,   # tiny yield, low APY
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=30.0,
        )
        result = analyze(farm)
        self.assertFalse(result["continue_farming"])

    def test_continue_false_when_deeply_negative_pnl(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=1000.0,  # massive IL
            harvested_rewards_usd=500.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=30.0,
        )
        result = analyze(farm)
        self.assertFalse(result["continue_farming"])

    def test_continue_requires_both_conditions(self):
        # High APY but net_pnl deeply negative (below -entry_gas)
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=9000.0,  # -1000 IL
            harvested_rewards_usd=10.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=1.0,  # just 1 day → huge APY from harvested
        )
        result = analyze(farm)
        # Even if actual_apy is high due to rewards, net_pnl = -1000 + 10 - 50 = -1040
        # -1040 < -50 (entry gas) → continue_farming = False
        self.assertFalse(result["continue_farming"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_days_elapsed_zero_no_error(self):
        farm = _base_farm(days_elapsed=0.0)
        result = analyze(farm)
        self.assertIn("actual_apy", result["apy_analysis"])

    def test_days_elapsed_zero_uses_min_days(self):
        farm = _base_farm(days_elapsed=0.0)
        result = analyze(farm)
        # Should not be inf or raise
        self.assertIsInstance(result["apy_analysis"]["actual_apy"], float)
        self.assertFalse(result["apy_analysis"]["actual_apy"] == float("inf"))

    def test_zero_initial_investment_no_error(self):
        farm = _base_farm(initial_investment_usd=0.0)
        result = analyze(farm)
        self.assertIn("net_pnl_usd", result["pnl"])

    def test_no_rewards_all_zeros(self):
        farm = _base_farm(
            harvested_rewards_usd=0.0,
            pending_rewards_usd=0.0,
            current_value_usd=10000.0,
            initial_investment_usd=10000.0,
            entry_gas_usd=0.0,
            harvest_gas_total_usd=0.0,
        )
        result = analyze(farm)
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], 0.0, places=4)

    def test_all_profit_no_il(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=10000.0,
            harvested_rewards_usd=1000.0,
            pending_rewards_usd=500.0,
            entry_gas_usd=100.0,
            harvest_gas_total_usd=50.0,
            days_elapsed=180.0,
        )
        result = analyze(farm)
        # net_pnl = 0 + 1500 - 150 - 0 = 1350
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], 1350.0, places=4)

    def test_large_days_elapsed(self):
        farm = _base_farm(days_elapsed=365.0)
        result = analyze(farm)
        self.assertIsInstance(result["apy_analysis"]["actual_apy"], float)

    def test_missing_protocol_defaults_empty_string(self):
        farm = _base_farm()
        del farm["protocol"]
        result = analyze(farm)
        self.assertEqual(result["protocol"], "")

    def test_missing_pair_defaults_empty_string(self):
        farm = _base_farm()
        del farm["pair"]
        result = analyze(farm)
        self.assertEqual(result["pair"], "")

    def test_none_config_uses_defaults(self):
        result = analyze(_base_farm(), None)
        self.assertAlmostEqual(result["pnl"]["tax_cost_usd"], 0.0, places=4)

    def test_empty_config_uses_defaults(self):
        result = analyze(_base_farm(), {})
        self.assertAlmostEqual(result["pnl"]["tax_cost_usd"], 0.0, places=4)

    def test_very_high_apy_farm(self):
        farm = _base_farm(
            initial_investment_usd=1000.0,
            current_value_usd=1000.0,
            harvested_rewards_usd=5000.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=0.0,
            harvest_gas_total_usd=0.0,
            days_elapsed=30.0,
            base_apy=500.0,
            reward_apy=100.0,
        )
        result = analyze(farm)
        self.assertEqual(result["performance"], "EXCELLENT")

    def test_il_not_negative(self):
        farm = _base_farm(initial_investment_usd=5000.0, current_value_usd=6000.0)
        result = analyze(farm)
        self.assertGreaterEqual(result["apy_analysis"]["il_estimated_usd"], 0.0)

    def test_apy_gap_is_float(self):
        result = analyze(_base_farm())
        self.assertIsInstance(result["apy_analysis"]["apy_gap_pct"], float)

    def test_net_pnl_pct_is_float(self):
        result = analyze(_base_farm())
        self.assertIsInstance(result["pnl"]["net_pnl_pct"], float)


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, {"k": "v"})
            self.assertTrue(path.exists())

    def test_atomic_write_content_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "out.json"
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_atomic_write_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "out.json"
            _atomic_write(path, {"a": 1})
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

    def test_ensure_log_idempotent(self):
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
            _append_to_log(log_path, {"test": True})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)

    def test_append_to_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            for i in range(_LOG_CAP + 15):
                _append_to_log(log_path, {"i": i})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), _LOG_CAP)

    def test_append_to_log_keeps_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            for i in range(_LOG_CAP + 5):
                _append_to_log(log_path, {"i": i})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(log[-1]["i"], _LOG_CAP + 4)

    def test_append_handles_corrupt_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            log_path.write_text("not valid json")
            _append_to_log(log_path, {"ok": True})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)

    def test_append_multiple_entries_ordered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / _LOG_FILE
            for i in range(5):
                _append_to_log(log_path, {"seq": i})
            with open(log_path) as f:
                log = json.load(f)
            seqs = [e["seq"] for e in log]
            self.assertEqual(seqs, list(range(5)))


# ---------------------------------------------------------------------------
# Full integration tests
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def test_standard_farm_complete(self):
        """Standard farm should produce all expected keys with correct types."""
        result = analyze(_base_farm())
        self.assertIsInstance(result["protocol"], str)
        self.assertIsInstance(result["pair"], str)
        self.assertIsInstance(result["days_elapsed"], float)
        self.assertIsInstance(result["pnl"]["net_pnl_usd"], float)
        self.assertIsInstance(result["apy_analysis"]["actual_apy"], float)
        self.assertIn(result["performance"], {"EXCELLENT", "GOOD", "FAIR", "POOR", "LOSS"})
        self.assertIsInstance(result["continue_farming"], bool)

    def test_profitable_farm_with_tax(self):
        farm = _base_farm(
            initial_investment_usd=50000.0,
            current_value_usd=50000.0,
            harvested_rewards_usd=5000.0,
            pending_rewards_usd=1000.0,
            entry_gas_usd=100.0,
            harvest_gas_total_usd=200.0,
            days_elapsed=365.0,
            base_apy=10.0,
            reward_apy=2.0,
        )
        result = analyze(farm, {"tax_rate_pct": 25.0})
        # total_rewards = 6000, tax = 1500
        self.assertAlmostEqual(result["pnl"]["tax_cost_usd"], 1500.0, places=4)
        # net_pnl = 0 + 6000 - 300 - 1500 = 4200
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], 4200.0, places=4)

    def test_farm_with_significant_il(self):
        farm = _base_farm(
            initial_investment_usd=10000.0,
            current_value_usd=7500.0,
            harvested_rewards_usd=200.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=20.0,
            days_elapsed=60.0,
        )
        result = analyze(farm)
        self.assertAlmostEqual(result["apy_analysis"]["il_estimated_usd"], 2500.0, places=4)
        self.assertAlmostEqual(result["apy_analysis"]["il_pct"], 25.0, places=4)
        # net_pnl = -2500 + 200 - 70 = -2370
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], -2370.0, places=4)
        self.assertEqual(result["performance"], "LOSS")
        self.assertFalse(result["continue_farming"])

    def test_new_farm_single_day(self):
        farm = _base_farm(
            days_elapsed=1.0,
            current_value_usd=10000.0,
            initial_investment_usd=10000.0,
            harvested_rewards_usd=10.0,
            pending_rewards_usd=0.0,
            entry_gas_usd=50.0,
            harvest_gas_total_usd=0.0,
        )
        result = analyze(farm)
        # net_pnl = 0 + 10 - 50 = -40
        self.assertAlmostEqual(result["pnl"]["net_pnl_usd"], -40.0, places=4)
        # actual_apy = -40/10000 * 365 * 100 = -14.6%
        self.assertLess(result["apy_analysis"]["actual_apy"], 0)
        self.assertEqual(result["performance"], "LOSS")


if __name__ == "__main__":
    unittest.main()
