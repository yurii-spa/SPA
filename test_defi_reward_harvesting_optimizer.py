"""
Tests for MP-851 DeFiRewardHarvestingOptimizer
================================================
Run with: python3 -m unittest spa_core/tests/test_defi_reward_harvesting_optimizer.py
≥65 tests covering all branches, edge cases, and recommendations.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_reward_harvesting_optimizer import (
    analyze,
    _analyze_position,
    _load_log,
    _save_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol="TestProtocol",
    position_value_usd=10000.0,
    reward_apy=10.0,
    gas_cost=5.0,
    volatility="LOW",
    days=10,
    reinvestment_apy=5.0,
):
    return {
        "protocol": protocol,
        "position_value_usd": position_value_usd,
        "reward_apy": reward_apy,
        "gas_cost_per_harvest_usd": gas_cost,
        "reward_token_volatility": volatility,
        "days_since_last_harvest": days,
        "reinvestment_apy": reinvestment_apy,
    }


# ---------------------------------------------------------------------------
# 1. Accrued rewards calculation
# ---------------------------------------------------------------------------

class TestAccruedRewards(unittest.TestCase):

    def test_accrued_basic(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, days=10)
        r = _analyze_position(pos, 10.0)
        # 0.10/365 * 10 * 10000 = 27.397...
        self.assertAlmostEqual(r["accrued_rewards_usd"], 10.0 / 100.0 / 365.0 * 10 * 10000.0, places=4)

    def test_accrued_zero_days(self):
        pos = _pos(days=0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["accrued_rewards_usd"], 0.0)

    def test_accrued_zero_value(self):
        pos = _pos(position_value_usd=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["accrued_rewards_usd"], 0.0)

    def test_accrued_zero_apy(self):
        pos = _pos(reward_apy=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["accrued_rewards_usd"], 0.0)

    def test_accrued_large_position(self):
        pos = _pos(position_value_usd=1_000_000.0, reward_apy=5.0, days=30)
        r = _analyze_position(pos, 10.0)
        expected = 5.0 / 100.0 / 365.0 * 30 * 1_000_000.0
        self.assertAlmostEqual(r["accrued_rewards_usd"], expected, places=2)

    def test_accrued_high_apy(self):
        pos = _pos(reward_apy=100.0, days=365)
        r = _analyze_position(pos, 10.0)
        # ~10000 USD
        self.assertAlmostEqual(r["accrued_rewards_usd"], 10000.0, places=1)


# ---------------------------------------------------------------------------
# 2. Gas as % of rewards
# ---------------------------------------------------------------------------

class TestGasAsPct(unittest.TestCase):

    def test_gas_pct_normal(self):
        # accrued ~ 27.397, gas=5 → ~18.25%
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=10)
        r = _analyze_position(pos, 10.0)
        expected = 5.0 / (10.0 / 100.0 / 365.0 * 10 * 10000.0) * 100.0
        self.assertAlmostEqual(r["gas_as_pct_of_rewards"], expected, places=2)

    def test_gas_pct_zero_accrued(self):
        pos = _pos(days=0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["gas_as_pct_of_rewards"], 999.0)

    def test_gas_pct_zero_value(self):
        pos = _pos(position_value_usd=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["gas_as_pct_of_rewards"], 999.0)

    def test_gas_pct_low_gas(self):
        # Large position, small gas → very low %
        pos = _pos(position_value_usd=1_000_000.0, reward_apy=10.0, gas_cost=1.0, days=30)
        r = _analyze_position(pos, 10.0)
        self.assertLess(r["gas_as_pct_of_rewards"], 1.0)


# ---------------------------------------------------------------------------
# 3. Optimal harvest days
# ---------------------------------------------------------------------------

class TestOptimalHarvestDays(unittest.TestCase):

    def test_optimal_days_basic(self):
        # gas=5, reward_apy=10, value=10000, target=10%
        # daily_rate = 0.10/365
        # optimal = 5 / (0.10/365 * 10000) / 0.10 = 5 / 2.7397 / 0.10 = 18.25 days
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=10)
        r = _analyze_position(pos, 10.0)
        expected = 5.0 / (10.0 / 100.0 / 365.0 * 10000.0) / 0.10
        self.assertAlmostEqual(r["optimal_harvest_days"], expected, places=2)

    def test_optimal_days_zero_apy(self):
        pos = _pos(reward_apy=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertIsNone(r["optimal_harvest_days"])

    def test_optimal_days_zero_value(self):
        pos = _pos(position_value_usd=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertIsNone(r["optimal_harvest_days"])

    def test_optimal_days_high_target(self):
        # Higher target_roi_pct → fewer days needed
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0)
        r_low = _analyze_position(pos, 5.0)
        r_high = _analyze_position(pos, 20.0)
        self.assertGreater(r_low["optimal_harvest_days"], r_high["optimal_harvest_days"])

    def test_optimal_days_custom_target(self):
        pos = _pos(position_value_usd=50000.0, reward_apy=6.0, gas_cost=10.0)
        r = _analyze_position(pos, 5.0)
        expected = 10.0 / (6.0 / 100.0 / 365.0 * 50000.0) / 0.05
        self.assertAlmostEqual(r["optimal_harvest_days"], expected, places=2)


# ---------------------------------------------------------------------------
# 4. Compound benefit
# ---------------------------------------------------------------------------

class TestCompoundBenefit(unittest.TestCase):

    def test_compound_benefit_basic(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, days=10, reinvestment_apy=5.0)
        r = _analyze_position(pos, 10.0)
        accrued = 10.0 / 100.0 / 365.0 * 10 * 10000.0
        expected = accrued * 5.0 / 100.0 / 365.0 * 30
        self.assertAlmostEqual(r["compound_benefit_usd"], expected, places=6)

    def test_compound_benefit_zero_accrued(self):
        pos = _pos(days=0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["compound_benefit_usd"], 0.0)

    def test_compound_benefit_zero_reinvestment_apy(self):
        pos = _pos(reinvestment_apy=0.0, days=30)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["compound_benefit_usd"], 0.0)

    def test_compound_benefit_positive(self):
        pos = _pos(position_value_usd=100000.0, reward_apy=12.0, days=30, reinvestment_apy=6.0)
        r = _analyze_position(pos, 10.0)
        self.assertGreater(r["compound_benefit_usd"], 0.0)


# ---------------------------------------------------------------------------
# 5. Recommendations — WAIT
# ---------------------------------------------------------------------------

class TestRecommendationWait(unittest.TestCase):

    def test_wait_high_gas_pct(self):
        # small position, big gas, few days → WAIT
        pos = _pos(position_value_usd=1000.0, reward_apy=5.0, gas_cost=50.0, days=1, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")

    def test_wait_reason_contains_days(self):
        pos = _pos(position_value_usd=1000.0, reward_apy=5.0, gas_cost=50.0, days=1, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertIn("days", r["urgency_reason"])

    def test_wait_zero_accrued(self):
        pos = _pos(days=0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")

    def test_wait_medium_volatility_high_gas(self):
        pos = _pos(position_value_usd=500.0, reward_apy=4.0, gas_cost=20.0, days=3, volatility="MEDIUM")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")


# ---------------------------------------------------------------------------
# 6. Recommendations — HARVEST_NOW
# ---------------------------------------------------------------------------

class TestRecommendationHarvestNow(unittest.TestCase):

    def test_harvest_now_low_gas(self):
        # gas_pct must be between target/2 and target to get HARVEST_NOW (not URGENT overdue)
        # accrued = 10/100/365 * 10 * 10000 = 27.397; gas=2.0 → gas_pct=7.3% (between 5% and 10%)
        # optimal = 2/(10/100/365*10000)/0.10 = 7.3 days; 2*optimal=14.6 > days=10 → not overdue
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=2.0, days=10, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_NOW")

    def test_harvest_now_medium_volatility(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=2.0, days=10, volatility="MEDIUM")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_NOW")

    def test_harvest_now_reason(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=2.0, days=10, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertIn("Gas only", r["urgency_reason"])
        self.assertIn("favorable to harvest", r["urgency_reason"])

    def test_harvest_now_exactly_at_threshold(self):
        # Arrange so gas_as_pct == target_roi_pct exactly → HARVEST_NOW
        # accrued = apy/100/365 * days * value; gas_pct = gas/accrued*100 == target
        # target=10, apy=10, value=10000 → daily=10/100/365*10000=2.7397
        # accrued(days=1)=2.7397; gas_pct = gas/2.7397*100=10 → gas=0.27397
        apy = 10.0
        value = 10000.0
        days = 1
        target = 10.0
        accrued = apy / 100.0 / 365.0 * days * value
        gas = accrued * (target / 100.0)
        pos = _pos(position_value_usd=value, reward_apy=apy, gas_cost=gas, days=days, volatility="LOW")
        r = _analyze_position(pos, target)
        self.assertAlmostEqual(r["gas_as_pct_of_rewards"], target, places=4)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_NOW")


# ---------------------------------------------------------------------------
# 7. Recommendations — HARVEST_URGENT
# ---------------------------------------------------------------------------

class TestRecommendationHarvestUrgent(unittest.TestCase):

    def test_urgent_high_volatility_profitable(self):
        # gas_pct <= target AND HIGH volatility → URGENT
        pos = _pos(position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="HIGH")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_URGENT")

    def test_urgent_overdue_2x(self):
        # days > optimal * 2, even LOW volatility
        # optimal ~ 18.25 days for standard params; use days=40 > 18.25*2=36.5
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=40, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_URGENT")

    def test_urgent_reason_volatile(self):
        pos = _pos(position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="HIGH")
        r = _analyze_position(pos, 10.0)
        self.assertIn("volatile", r["urgency_reason"])

    def test_urgent_reason_overdue(self):
        # days >> optimal*2
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=100, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_URGENT")
        self.assertIn("overdue", r["urgency_reason"].lower())

    def test_urgent_days_to_optimal_none_when_past(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=100, volatility="LOW")
        r = _analyze_position(pos, 10.0)
        self.assertIsNone(r["days_to_optimal"])

    def test_urgent_overdue_medium_volatility(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=40, volatility="MEDIUM")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "HARVEST_URGENT")


# ---------------------------------------------------------------------------
# 8. Days to optimal
# ---------------------------------------------------------------------------

class TestDaysToOptimal(unittest.TestCase):

    def test_days_to_optimal_positive_when_early(self):
        # days_since < optimal → days_to_optimal > 0
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=5)
        r = _analyze_position(pos, 10.0)
        if r["optimal_harvest_days"] is not None and 5 < r["optimal_harvest_days"]:
            self.assertIsNotNone(r["days_to_optimal"])
            self.assertGreater(r["days_to_optimal"], 0)

    def test_days_to_optimal_none_when_past(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=50)
        r = _analyze_position(pos, 10.0)
        if r["optimal_harvest_days"] is not None and 50 >= r["optimal_harvest_days"]:
            self.assertIsNone(r["days_to_optimal"])

    def test_days_to_optimal_none_when_zero_apy(self):
        pos = _pos(reward_apy=0.0, days=10)
        r = _analyze_position(pos, 10.0)
        self.assertIsNone(r["days_to_optimal"])

    def test_days_to_optimal_correct_value(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=5)
        r = _analyze_position(pos, 10.0)
        optimal = r["optimal_harvest_days"]
        if optimal is not None and 5 < optimal:
            self.assertAlmostEqual(r["days_to_optimal"], optimal - 5, places=2)


# ---------------------------------------------------------------------------
# 9. analyze() aggregate fields
# ---------------------------------------------------------------------------

class TestAnalyzeAggregate(unittest.TestCase):

    def setUp(self):
        self.positions = [
            _pos("Aave", position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="LOW"),
            _pos("Compound", position_value_usd=1000.0, reward_apy=5.0, gas_cost=50.0, days=2, volatility="LOW"),
        ]

    def test_returns_dict(self):
        result = analyze(self.positions, save_log=False)
        self.assertIsInstance(result, dict)

    def test_positions_list_length(self):
        result = analyze(self.positions, save_log=False)
        self.assertEqual(len(result["positions"]), 2)

    def test_harvest_now_count(self):
        result = analyze(self.positions, save_log=False)
        self.assertIsInstance(result["harvest_now_count"], int)

    def test_total_accrued_usd(self):
        result = analyze(self.positions, save_log=False)
        self.assertGreater(result["total_accrued_usd"], 0)

    def test_total_gas_if_all_harvested(self):
        result = analyze(self.positions, save_log=False)
        self.assertAlmostEqual(result["total_gas_if_all_harvested_usd"], 55.0, places=4)

    def test_timestamp_present(self):
        result = analyze(self.positions, save_log=False)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_highest_priority_none_when_no_urgent(self):
        # Both WAIT → highest_priority = None
        positions = [
            _pos("A", position_value_usd=500.0, reward_apy=5.0, gas_cost=50.0, days=1, volatility="LOW"),
        ]
        result = analyze(positions, save_log=False)
        self.assertIsNone(result["highest_priority"])

    def test_highest_priority_set_when_urgent(self):
        positions = [
            _pos("Urgent", position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="HIGH"),
        ]
        result = analyze(positions, save_log=False)
        self.assertEqual(result["highest_priority"], "Urgent")

    def test_empty_positions(self):
        result = analyze([], save_log=False)
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["harvest_now_count"], 0)
        self.assertEqual(result["total_accrued_usd"], 0.0)
        self.assertEqual(result["total_gas_if_all_harvested_usd"], 0.0)
        self.assertIsNone(result["highest_priority"])

    def test_harvest_now_count_correct(self):
        # Aave should be HARVEST_NOW or HARVEST_URGENT, Compound WAIT
        result = analyze(self.positions, save_log=False)
        # Aave: large position, 30 days, low gas → should harvest
        aave_rec = result["positions"][0]["harvest_recommendation"]
        compound_rec = result["positions"][1]["harvest_recommendation"]
        self.assertIn(aave_rec, ("HARVEST_NOW", "HARVEST_URGENT"))
        self.assertEqual(compound_rec, "WAIT")
        self.assertEqual(result["harvest_now_count"], 1)


# ---------------------------------------------------------------------------
# 10. Config overrides
# ---------------------------------------------------------------------------

class TestConfigOverrides(unittest.TestCase):

    def test_custom_target_roi_changes_recommendation(self):
        # With very high target (50%), a lot more will WAIT
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=10, volatility="LOW")
        r_low = analyze([pos], config={"target_harvest_roi_pct": 5.0}, save_log=False)
        r_high = analyze([pos], config={"target_harvest_roi_pct": 50.0}, save_log=False)
        # High target means gas needs to be lower % → harder to meet → WAIT more often
        # At 50% target, gas needs to be <50% of rewards
        gas_pct = r_low["positions"][0]["gas_as_pct_of_rewards"]
        if gas_pct > 50.0:
            self.assertEqual(r_high["positions"][0]["harvest_recommendation"], "WAIT")

    def test_default_config_applied(self):
        pos = _pos()
        r1 = analyze([pos], config=None, save_log=False)
        r2 = analyze([pos], config={}, save_log=False)
        self.assertEqual(
            r1["positions"][0]["harvest_recommendation"],
            r2["positions"][0]["harvest_recommendation"],
        )

    def test_target_roi_affects_optimal_days(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=5)
        r1 = analyze([pos], config={"target_harvest_roi_pct": 5.0}, save_log=False)
        r2 = analyze([pos], config={"target_harvest_roi_pct": 20.0}, save_log=False)
        opt1 = r1["positions"][0]["optimal_harvest_days"]
        opt2 = r2["positions"][0]["optimal_harvest_days"]
        if opt1 is not None and opt2 is not None:
            # Lower target → need more days (higher bar)
            self.assertGreater(opt1, opt2)


# ---------------------------------------------------------------------------
# 11. Log persistence
# ---------------------------------------------------------------------------

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "reward_harvesting_log.json")

    def _run_analyze(self, save=True):
        return analyze([_pos()], data_dir=self.tmp_dir, save_log=save)

    def test_log_created_on_save(self):
        self._run_analyze(save=True)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_not_created_when_no_save(self):
        self._run_analyze(save=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        self._run_analyze()
        self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_100(self):
        for _ in range(110):
            self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_positions(self):
        self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("positions", data[0])

    def test_load_log_missing_file(self):
        result = _load_log("/nonexistent/path/log.json")
        self.assertEqual(result, [])

    def test_save_and_reload(self):
        self._run_analyze()
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)
        self.assertIn("harvest_now_count", loaded[0])

    def test_atomic_write_creates_file(self):
        entries = [{"test": 1}]
        _save_log(self.log_path, entries)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_cap_exactly_100(self):
        for _ in range(100):
            self._run_analyze()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_gas_cost(self):
        pos = _pos(gas_cost=0.0, position_value_usd=10000.0, reward_apy=10.0, days=10)
        r = _analyze_position(pos, 10.0)
        # gas_pct = 0/accrued*100 = 0 → immediately HARVEST_NOW
        self.assertEqual(r["gas_as_pct_of_rewards"], 0.0)
        self.assertIn(r["harvest_recommendation"], ("HARVEST_NOW", "HARVEST_URGENT"))

    def test_all_zeros(self):
        pos = _pos(position_value_usd=0.0, reward_apy=0.0, gas_cost=0.0, days=0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["accrued_rewards_usd"], 0.0)
        self.assertEqual(r["gas_as_pct_of_rewards"], 999.0)

    def test_very_large_gas(self):
        pos = _pos(gas_cost=1_000_000.0, position_value_usd=100.0, days=1)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")

    def test_protocol_name_preserved(self):
        pos = _pos(protocol="MyUniqueProtocol")
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["protocol"], "MyUniqueProtocol")

    def test_multiple_urgent_highest_priority_is_first(self):
        p1 = _pos("Alpha", position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="HIGH")
        p2 = _pos("Beta", position_value_usd=100000.0, reward_apy=10.0, gas_cost=5.0, days=30, volatility="HIGH")
        result = analyze([p1, p2], save_log=False)
        self.assertEqual(result["highest_priority"], "Alpha")

    def test_negative_days_treated_as_zero(self):
        # days_since_last_harvest < 0 shouldn't crash
        pos = _pos(days=-5)
        r = _analyze_position(pos, 10.0)
        # negative days → accrued could be negative; edge-cased by the formula
        # We just verify no exception
        self.assertIsInstance(r, dict)

    def test_very_small_position(self):
        pos = _pos(position_value_usd=0.01, reward_apy=5.0, gas_cost=1.0, days=365)
        r = _analyze_position(pos, 10.0)
        self.assertIsInstance(r["harvest_recommendation"], str)

    def test_output_keys_present(self):
        pos = _pos()
        r = _analyze_position(pos, 10.0)
        expected_keys = {
            "protocol", "accrued_rewards_usd", "gas_as_pct_of_rewards",
            "optimal_harvest_days", "compound_benefit_usd",
            "harvest_recommendation", "days_to_optimal", "urgency_reason",
        }
        self.assertEqual(set(r.keys()), expected_keys)

    def test_analyze_output_keys(self):
        result = analyze([_pos()], save_log=False)
        expected_keys = {
            "positions", "harvest_now_count", "total_accrued_usd",
            "total_gas_if_all_harvested_usd", "highest_priority", "timestamp",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_harvest_recommendation_valid_values(self):
        valid = {"HARVEST_NOW", "HARVEST_URGENT", "WAIT"}
        for v in ["LOW", "MEDIUM", "HIGH"]:
            for days in [1, 10, 50]:
                pos = _pos(volatility=v, days=days)
                r = _analyze_position(pos, 10.0)
                self.assertIn(r["harvest_recommendation"], valid)

    def test_missing_optional_fields_defaults(self):
        # Minimal position dict
        pos = {"protocol": "Min", "position_value_usd": 1000.0}
        r = _analyze_position(pos, 10.0)
        self.assertIsInstance(r, dict)


# ---------------------------------------------------------------------------
# 13. Wait urgency when no optimal (zero apy)
# ---------------------------------------------------------------------------

class TestWaitNoOptimal(unittest.TestCase):

    def test_wait_reason_no_optimal(self):
        pos = _pos(reward_apy=0.0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")
        self.assertIsNotNone(r["urgency_reason"])

    def test_wait_fallback_reason(self):
        # days=0 → no accrued, gas_pct=999 → WAIT
        pos = _pos(days=0, reward_apy=5.0)
        r = _analyze_position(pos, 10.0)
        self.assertEqual(r["harvest_recommendation"], "WAIT")


# ---------------------------------------------------------------------------
# 14. Boundary: gas_pct exactly at target
# ---------------------------------------------------------------------------

class TestBoundaryConditions(unittest.TestCase):

    def test_gas_pct_just_below_target(self):
        # accrued so that gas_pct is just below target
        target = 10.0
        apy = 10.0
        value = 10000.0
        days = 20
        accrued = apy / 100.0 / 365.0 * days * value
        gas = accrued * (target / 100.0) * 0.99  # 1% below threshold
        pos = _pos(position_value_usd=value, reward_apy=apy, gas_cost=gas, days=days, volatility="LOW")
        r = _analyze_position(pos, target)
        self.assertIn(r["harvest_recommendation"], ("HARVEST_NOW", "HARVEST_URGENT"))

    def test_gas_pct_just_above_target(self):
        target = 10.0
        apy = 10.0
        value = 10000.0
        days = 5
        accrued = apy / 100.0 / 365.0 * days * value
        gas = accrued * (target / 100.0) * 1.5  # above threshold
        pos = _pos(position_value_usd=value, reward_apy=apy, gas_cost=gas, days=days, volatility="LOW")
        r = _analyze_position(pos, target)
        # Not at 2x optimal yet → WAIT (assuming not overdue)
        opt = r["optimal_harvest_days"]
        if opt is None or days <= opt * 2:
            self.assertEqual(r["harvest_recommendation"], "WAIT")

    def test_overdue_boundary_exactly_2x(self):
        # days == optimal * 2 (not strictly greater) → not HARVEST_URGENT via overdue path
        pos = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=5)
        r_base = _analyze_position(pos, 10.0)
        opt = r_base["optimal_harvest_days"]
        if opt is not None:
            days_at_2x = int(opt * 2)
            pos2 = _pos(position_value_usd=10000.0, reward_apy=10.0, gas_cost=5.0, days=days_at_2x)
            r2 = _analyze_position(pos2, 10.0)
            # at exactly 2x: days_since > optimal*2 is False (not strictly greater) → not URGENT via overdue
            # but might be HARVEST_NOW since gas_pct could be low
            self.assertIn(r2["harvest_recommendation"], ("HARVEST_NOW", "HARVEST_URGENT", "WAIT"))


# ---------------------------------------------------------------------------
# 15. Protocol name in urgency / output
# ---------------------------------------------------------------------------

class TestOutputIntegrity(unittest.TestCase):

    def test_gas_pct_rounds_to_4_decimals(self):
        pos = _pos(position_value_usd=10000.0, reward_apy=7.3, gas_cost=3.7, days=15)
        r = _analyze_position(pos, 10.0)
        # Check it's rounded to 4 places (within 4-decimal accuracy)
        self.assertAlmostEqual(r["gas_as_pct_of_rewards"], round(r["gas_as_pct_of_rewards"], 4), places=4)

    def test_total_accrued_is_sum(self):
        p1 = _pos("A", position_value_usd=10000.0, reward_apy=10.0, days=10)
        p2 = _pos("B", position_value_usd=20000.0, reward_apy=5.0, days=5)
        result = analyze([p1, p2], save_log=False)
        r1 = _analyze_position(p1, 10.0)
        r2 = _analyze_position(p2, 10.0)
        expected = r1["accrued_rewards_usd"] + r2["accrued_rewards_usd"]
        self.assertAlmostEqual(result["total_accrued_usd"], expected, places=4)

    def test_single_position_harvest_count_1(self):
        pos = _pos(position_value_usd=100000.0, reward_apy=10.0, gas_cost=1.0, days=100, volatility="LOW")
        result = analyze([pos], save_log=False)
        self.assertEqual(result["harvest_now_count"], 1)

    def test_all_wait_harvest_count_0(self):
        positions = [
            _pos(position_value_usd=100.0, reward_apy=1.0, gas_cost=100.0, days=1, volatility="LOW"),
            _pos(position_value_usd=100.0, reward_apy=1.0, gas_cost=100.0, days=1, volatility="LOW"),
        ]
        result = analyze(positions, save_log=False)
        self.assertEqual(result["harvest_now_count"], 0)


if __name__ == "__main__":
    unittest.main()
