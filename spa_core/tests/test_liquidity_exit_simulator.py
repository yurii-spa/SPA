"""Tests for spa_core/analytics/liquidity_exit_simulator.py — MP-630.

≥ 40 tests covering:
  * ExitScenario dataclass
  * _feasibility helper
  * Constants
  * LiquidityExitSimulator.estimate_exit — all feasibility tiers, edge cases
  * LiquidityExitSimulator.estimate_portfolio_exit
  * LiquidityExitSimulator.get_worst_case_exit
  * LiquidityExitSimulator.compute_exit_risk_score
  * LiquidityExitSimulator.generate_report
  * LiquidityExitSimulator.log_simulation — ring-buffer 50
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from spa_core.analytics.liquidity_exit_simulator import (
    BLOCK_TIME_SECONDS,
    BLOCKS_PER_MINUTE,
    MAX_PER_BLOCK_PCT,
    SLIPPAGE_BPS_PER_BLOCK,
    ExitScenario,
    LiquidityExitSimulator,
    _feasibility,
)


# ---------------------------------------------------------------------------
# 1. ExitScenario dataclass
# ---------------------------------------------------------------------------


class TestExitScenarioDataclass(unittest.TestCase):
    """Tests for the ExitScenario dataclass (5 tests)."""

    def _make(self, **kwargs) -> ExitScenario:
        defaults = dict(
            adapter_id="aave_v3",
            position_size_usd=50_000.0,
            pool_tvl_usd=2_000_000_000.0,
            estimated_exit_blocks=1,
            estimated_exit_time_minutes=0.2,
            exit_slippage_bps=5.0,
            exit_feasibility="INSTANT",
            can_exit_in_one_block=True,
        )
        defaults.update(kwargs)
        return ExitScenario(**defaults)

    def test_fields_exist(self):
        s = self._make()
        self.assertEqual(s.adapter_id, "aave_v3")
        self.assertEqual(s.position_size_usd, 50_000.0)
        self.assertEqual(s.pool_tvl_usd, 2_000_000_000.0)
        self.assertEqual(s.estimated_exit_blocks, 1)
        self.assertAlmostEqual(s.estimated_exit_time_minutes, 0.2)
        self.assertAlmostEqual(s.exit_slippage_bps, 5.0)
        self.assertEqual(s.exit_feasibility, "INSTANT")
        self.assertTrue(s.can_exit_in_one_block)

    def test_can_exit_false(self):
        s = self._make(estimated_exit_blocks=10, can_exit_in_one_block=False)
        self.assertFalse(s.can_exit_in_one_block)

    def test_risky_feasibility(self):
        s = self._make(exit_feasibility="RISKY")
        self.assertEqual(s.exit_feasibility, "RISKY")

    def test_float_slippage(self):
        s = self._make(exit_slippage_bps=37.5)
        self.assertIsInstance(s.exit_slippage_bps, float)

    def test_int_blocks(self):
        s = self._make(estimated_exit_blocks=150)
        self.assertIsInstance(s.estimated_exit_blocks, int)


# ---------------------------------------------------------------------------
# 2. Constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Tests for module-level constants (6 tests)."""

    def test_block_time_seconds(self):
        self.assertEqual(BLOCK_TIME_SECONDS, 12.0)

    def test_blocks_per_minute(self):
        self.assertAlmostEqual(BLOCKS_PER_MINUTE, 5.0, places=8)

    def test_max_per_block_pct(self):
        self.assertEqual(MAX_PER_BLOCK_PCT, 0.02)

    def test_slippage_bps_per_block(self):
        self.assertEqual(SLIPPAGE_BPS_PER_BLOCK, 5.0)

    def test_blocks_per_minute_formula(self):
        self.assertAlmostEqual(BLOCKS_PER_MINUTE, 60.0 / BLOCK_TIME_SECONDS, places=8)

    def test_max_per_block_pct_is_two_percent(self):
        self.assertAlmostEqual(MAX_PER_BLOCK_PCT * 100, 2.0, places=8)


# ---------------------------------------------------------------------------
# 3. _feasibility helper
# ---------------------------------------------------------------------------


class TestFeasibilityHelper(unittest.TestCase):
    """Tests for the _feasibility tier helper (8 tests)."""

    def test_one_block_is_instant(self):
        self.assertEqual(_feasibility(1), "INSTANT")

    def test_two_blocks_is_fast(self):
        self.assertEqual(_feasibility(2), "FAST")

    def test_five_blocks_is_fast(self):
        self.assertEqual(_feasibility(5), "FAST")

    def test_six_blocks_is_moderate(self):
        self.assertEqual(_feasibility(6), "MODERATE")

    def test_twenty_blocks_is_moderate(self):
        self.assertEqual(_feasibility(20), "MODERATE")

    def test_twenty_one_blocks_is_slow(self):
        self.assertEqual(_feasibility(21), "SLOW")

    def test_hundred_blocks_is_slow(self):
        self.assertEqual(_feasibility(100), "SLOW")

    def test_hundred_one_blocks_is_risky(self):
        self.assertEqual(_feasibility(101), "RISKY")


# ---------------------------------------------------------------------------
# 4. LiquidityExitSimulator.estimate_exit — all tiers + edges
# ---------------------------------------------------------------------------


class TestEstimateExit(unittest.TestCase):
    """Core estimate_exit tests covering all feasibility tiers (15 tests)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.sim = LiquidityExitSimulator(data_dir=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_instant_feasibility(self):
        # position << tvl * 0.02 → 1 block → INSTANT
        est = self.sim.estimate_exit("aave_v3", 100.0, 2_000_000_000.0)
        self.assertEqual(est.exit_feasibility, "INSTANT")
        self.assertEqual(est.estimated_exit_blocks, 1)
        self.assertTrue(est.can_exit_in_one_block)

    def test_fast_feasibility(self):
        # position = 2 * capacity_per_block → 2 blocks → FAST
        tvl = 10_000_000.0
        capacity = tvl * 0.02  # 200_000
        position = 2.0 * capacity + 1.0  # just over 2 blocks
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertEqual(est.exit_feasibility, "FAST")
        self.assertFalse(est.can_exit_in_one_block)

    def test_moderate_feasibility(self):
        # 10 blocks
        tvl = 10_000_000.0
        capacity = tvl * 0.02  # 200_000
        position = 10.0 * capacity  # exactly 10 blocks
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertEqual(est.exit_feasibility, "MODERATE")

    def test_slow_feasibility(self):
        # 50 blocks
        tvl = 10_000_000.0
        capacity = tvl * 0.02
        position = 50.0 * capacity
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertEqual(est.exit_feasibility, "SLOW")

    def test_risky_feasibility(self):
        # > 100 blocks
        tvl = 10_000_000.0
        capacity = tvl * 0.02
        position = 101.0 * capacity
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertEqual(est.exit_feasibility, "RISKY")

    def test_zero_position_is_one_block(self):
        est = self.sim.estimate_exit("aave_v3", 0.0, 1_000_000_000.0)
        self.assertEqual(est.estimated_exit_blocks, 1)
        self.assertTrue(est.can_exit_in_one_block)

    def test_zero_tvl_uses_guard(self):
        # TVL = 0 → treated as 1.0 to avoid ZeroDivisionError
        est = self.sim.estimate_exit("bad_pool", 1000.0, 0.0)
        self.assertIsInstance(est.estimated_exit_blocks, int)
        self.assertGreater(est.estimated_exit_blocks, 0)

    def test_blocks_is_ceiling(self):
        # position = 1.5 × capacity_per_block → ceil = 2
        tvl = 1_000_000.0
        capacity = tvl * 0.02  # 20_000
        position = 1.5 * capacity  # 30_000
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertEqual(est.estimated_exit_blocks, 2)

    def test_exit_time_formula(self):
        tvl = 100_000_000.0
        capacity = tvl * 0.02  # 2_000_000
        position = 3.0 * capacity  # 3 blocks
        est = self.sim.estimate_exit("proto", position, tvl)
        expected_time = 3 * 12.0 / 60.0
        self.assertAlmostEqual(est.estimated_exit_time_minutes, expected_time, places=4)

    def test_slippage_bps_formula(self):
        tvl = 100_000_000.0
        capacity = tvl * 0.02
        position = 4.0 * capacity
        est = self.sim.estimate_exit("proto", position, tvl)
        expected_bps = 5.0 * 4  # 20 bps
        self.assertAlmostEqual(est.exit_slippage_bps, expected_bps, places=4)

    def test_can_exit_in_one_block_true_for_small_position(self):
        est = self.sim.estimate_exit("proto", 1.0, 100_000_000.0)
        self.assertTrue(est.can_exit_in_one_block)

    def test_can_exit_in_one_block_false_for_large_position(self):
        tvl = 1_000_000.0
        capacity = tvl * 0.02  # 20_000
        position = capacity * 3.0
        est = self.sim.estimate_exit("proto", position, tvl)
        self.assertFalse(est.can_exit_in_one_block)

    def test_adapter_id_preserved(self):
        est = self.sim.estimate_exit("morpho_steakhouse", 10_000.0, 80_000_000.0)
        self.assertEqual(est.adapter_id, "morpho_steakhouse")

    def test_returns_exit_scenario_type(self):
        est = self.sim.estimate_exit("aave_v3", 50_000.0, 1_000_000_000.0)
        self.assertIsInstance(est, ExitScenario)

    def test_one_block_boundary_exactly(self):
        # position = exactly 1 × capacity_per_block → ceil = 1
        tvl = 10_000_000.0
        capacity = tvl * 0.02  # 200_000
        est = self.sim.estimate_exit("proto", capacity, tvl)
        self.assertEqual(est.estimated_exit_blocks, 1)


# ---------------------------------------------------------------------------
# 5. LiquidityExitSimulator.estimate_portfolio_exit
# ---------------------------------------------------------------------------


class TestEstimatePortfolioExit(unittest.TestCase):
    """Tests for estimate_portfolio_exit (5 tests)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.sim = LiquidityExitSimulator(data_dir=self._tmp)
        self.positions = {
            "aave_v3": 50_000.0,
            "compound_v3": 30_000.0,
            "morpho_steakhouse": 20_000.0,
        }
        self.tvl_map = {
            "aave_v3": 2_000_000_000.0,
            "compound_v3": 500_000_000.0,
            "morpho_steakhouse": 80_000_000.0,
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_list(self):
        result = self.sim.estimate_portfolio_exit(self.positions, self.tvl_map)
        self.assertIsInstance(result, list)

    def test_length_matches_positions(self):
        result = self.sim.estimate_portfolio_exit(self.positions, self.tvl_map)
        self.assertEqual(len(result), 3)

    def test_all_scenarios_are_exit_scenario(self):
        result = self.sim.estimate_portfolio_exit(self.positions, self.tvl_map)
        for s in result:
            self.assertIsInstance(s, ExitScenario)

    def test_empty_positions(self):
        result = self.sim.estimate_portfolio_exit({}, self.tvl_map)
        self.assertEqual(result, [])

    def test_missing_tvl_defaults_to_zero(self):
        result = self.sim.estimate_portfolio_exit({"unknown": 10_000.0}, {})
        self.assertEqual(len(result), 1)
        # guard: TVL 0 → 1 USD
        self.assertIsInstance(result[0].estimated_exit_blocks, int)


# ---------------------------------------------------------------------------
# 6. LiquidityExitSimulator.get_worst_case_exit
# ---------------------------------------------------------------------------


class TestGetWorstCaseExit(unittest.TestCase):
    """Tests for get_worst_case_exit (4 tests)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.sim = LiquidityExitSimulator(data_dir=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scen(self, adapter_id: str, blocks: int) -> ExitScenario:
        return ExitScenario(
            adapter_id=adapter_id,
            position_size_usd=1000.0,
            pool_tvl_usd=1_000_000.0,
            estimated_exit_blocks=blocks,
            estimated_exit_time_minutes=blocks * 12.0 / 60.0,
            exit_slippage_bps=blocks * 5.0,
            exit_feasibility=_feasibility(blocks),
            can_exit_in_one_block=(blocks == 1),
        )

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(self.sim.get_worst_case_exit([]))

    def test_single_scenario_is_worst(self):
        s = self._scen("aave_v3", 3)
        worst = self.sim.get_worst_case_exit([s])
        self.assertEqual(worst.adapter_id, "aave_v3")

    def test_selects_highest_blocks(self):
        s1 = self._scen("a", 2)
        s2 = self._scen("b", 150)
        s3 = self._scen("c", 7)
        worst = self.sim.get_worst_case_exit([s1, s2, s3])
        self.assertEqual(worst.adapter_id, "b")

    def test_worst_has_max_blocks(self):
        scenarios = [self._scen(f"p{i}", i * 10 + 1) for i in range(5)]
        worst = self.sim.get_worst_case_exit(scenarios)
        max_blocks = max(s.estimated_exit_blocks for s in scenarios)
        self.assertEqual(worst.estimated_exit_blocks, max_blocks)


# ---------------------------------------------------------------------------
# 7. LiquidityExitSimulator.compute_exit_risk_score
# ---------------------------------------------------------------------------


class TestComputeExitRiskScore(unittest.TestCase):
    """Tests for compute_exit_risk_score (6 tests)."""

    def _scen(self, blocks: int) -> ExitScenario:
        return ExitScenario(
            adapter_id="x",
            position_size_usd=0,
            pool_tvl_usd=0,
            estimated_exit_blocks=blocks,
            estimated_exit_time_minutes=0,
            exit_slippage_bps=0,
            exit_feasibility="SLOW",
            can_exit_in_one_block=False,
        )

    def test_empty_returns_zero(self):
        self.assertEqual(LiquidityExitSimulator.compute_exit_risk_score([]), 0.0)

    def test_one_block_scenarios_score_low(self):
        scenarios = [self._scen(1)] * 5
        score = LiquidityExitSimulator.compute_exit_risk_score(scenarios)
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_hundred_blocks_scores_100(self):
        scenarios = [self._scen(100)]
        score = LiquidityExitSimulator.compute_exit_risk_score(scenarios)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_above_hundred_blocks_capped_at_100(self):
        scenarios = [self._scen(200)]
        score = LiquidityExitSimulator.compute_exit_risk_score(scenarios)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_average_of_multiple_scenarios(self):
        scenarios = [self._scen(10), self._scen(50)]
        score = LiquidityExitSimulator.compute_exit_risk_score(scenarios)
        expected = (10 + 50) / 2.0  # = 30.0, < 100 so not capped
        self.assertAlmostEqual(score, expected, places=4)

    def test_score_range_zero_to_100(self):
        for n in [1, 5, 20, 50, 100, 200]:
            score = LiquidityExitSimulator.compute_exit_risk_score([self._scen(n)])
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)


# ---------------------------------------------------------------------------
# 8. LiquidityExitSimulator.generate_report
# ---------------------------------------------------------------------------


class TestGenerateReport(unittest.TestCase):
    """Tests for generate_report (7 tests)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.sim = LiquidityExitSimulator(data_dir=self._tmp)
        self.positions = {"aave_v3": 50_000.0, "compound_v3": 30_000.0}
        self.tvl_map = {
            "aave_v3": 2_000_000_000.0,
            "compound_v3": 500_000_000.0,
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_dict(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        self.assertIsInstance(report, dict)

    def test_required_keys(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        for key in ("scenarios", "worst_case", "exit_risk_score", "total_positions", "advisory"):
            self.assertIn(key, report)

    def test_advisory_text(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        self.assertEqual(report["advisory"], "Exit scenarios are estimates only.")

    def test_total_positions_matches_input(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        self.assertEqual(report["total_positions"], 2)

    def test_scenarios_list_of_dicts(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        self.assertIsInstance(report["scenarios"], list)
        for item in report["scenarios"]:
            self.assertIsInstance(item, dict)

    def test_empty_positions_report(self):
        report = self.sim.generate_report({}, {})
        self.assertEqual(report["scenarios"], [])
        self.assertIsNone(report["worst_case"])
        self.assertEqual(report["exit_risk_score"], 0.0)
        self.assertEqual(report["total_positions"], 0)

    def test_worst_case_is_dict_or_none(self):
        report = self.sim.generate_report(self.positions, self.tvl_map)
        if report["worst_case"] is not None:
            self.assertIsInstance(report["worst_case"], dict)
            self.assertIn("adapter_id", report["worst_case"])


# ---------------------------------------------------------------------------
# 9. LiquidityExitSimulator.log_simulation — ring-buffer 50
# ---------------------------------------------------------------------------


class TestLogSimulation(unittest.TestCase):
    """Tests for log_simulation ring-buffer behaviour (8 tests)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.sim = LiquidityExitSimulator(data_dir=self._tmp)
        self._log_path = os.path.join(self._tmp, "exit_simulation_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sample_report(self, tag: str = "test") -> dict:
        return {
            "scenarios": [],
            "worst_case": None,
            "exit_risk_score": 0.0,
            "total_positions": 0,
            "advisory": "Exit scenarios are estimates only.",
            "_tag": tag,
        }

    def test_creates_log_file(self):
        self.sim.log_simulation(self._sample_report())
        self.assertTrue(os.path.exists(self._log_path))

    def test_log_is_valid_json(self):
        self.sim.log_simulation(self._sample_report())
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_first_entry_is_appended(self):
        self.sim.log_simulation(self._sample_report("first"))
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["_tag"], "first")

    def test_multiple_appends(self):
        for i in range(5):
            self.sim.log_simulation(self._sample_report(f"entry_{i}"))
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_50(self):
        for i in range(60):
            self.sim.log_simulation(self._sample_report(f"entry_{i}"))
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 50)

    def test_ring_buffer_keeps_latest_50(self):
        for i in range(60):
            self.sim.log_simulation(self._sample_report(f"entry_{i}"))
        with open(self._log_path) as f:
            data = json.load(f)
        # The last entry should be entry_59
        self.assertEqual(data[-1]["_tag"], "entry_59")
        # The first entry in the buffer should be entry_10 (60-50=10)
        self.assertEqual(data[0]["_tag"], "entry_10")

    def test_logged_at_field_added(self):
        self.sim.log_simulation(self._sample_report())
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIn("logged_at", data[0])

    def test_creates_data_dir_if_missing(self):
        sub_dir = os.path.join(self._tmp, "new_data_subdir")
        sim2 = LiquidityExitSimulator(data_dir=sub_dir)
        sim2.log_simulation(self._sample_report("subdir_test"))
        self.assertTrue(os.path.exists(sub_dir))
        log = os.path.join(sub_dir, "exit_simulation_log.json")
        self.assertTrue(os.path.exists(log))


if __name__ == "__main__":
    unittest.main()
