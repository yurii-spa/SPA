"""Tests for spa_core/analytics/liquidity_stress_simulator.py — MP-649.

≥ 65 tests covering:
  * AdapterLiquidity / StressResult dataclasses
  * LiquidityStressSimulator._liquid_capital
  * LiquidityStressSimulator._locked_capital
  * LiquidityStressSimulator._at_risk
  * LiquidityStressSimulator._verdict
  * LiquidityStressSimulator.simulate  (all 4 scenarios + edge cases)
  * LiquidityStressSimulator.simulate_all
  * LiquidityStressSimulator.save_result  (ring-buffer + atomic write)
  * LiquidityStressSimulator.load_history
  * Module-level constants (SCENARIOS, MAX_ENTRIES)
  * CLI smoke (_run helper)
"""
from __future__ import annotations

import json
import math
import os
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.liquidity_stress_simulator import (
    SCENARIOS,
    MAX_ENTRIES,
    CONCENTRATION_TVL_PCT,
    SAFE_COVERAGE,
    WATCH_COVERAGE,
    AdapterLiquidity,
    StressResult,
    LiquidityStressSimulator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(
    adapter_id: str = "a1",
    capital: float = 10_000.0,
    tier: str = "T1",
    lock_days: int = 0,
    tvl: float = 1_000_000.0,
    wl_pct: float = 0.10,
) -> AdapterLiquidity:
    return AdapterLiquidity(
        adapter_id=adapter_id,
        capital_deployed=capital,
        tier=tier,
        lock_days=lock_days,
        tvl_usd=tvl,
        withdrawal_limit_pct=wl_pct,
    )


def _make_sim(tmp_dir: str) -> LiquidityStressSimulator:
    return LiquidityStressSimulator(
        data_file=Path(tmp_dir) / "liquidity_stress_log.json"
    )


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_scenarios_has_four_entries(self):
        self.assertEqual(len(SCENARIOS), 4)

    def test_scenario_keys(self):
        self.assertIn("MILD", SCENARIOS)
        self.assertIn("MODERATE", SCENARIOS)
        self.assertIn("SEVERE", SCENARIOS)
        self.assertIn("EXTREME", SCENARIOS)

    def test_scenario_haircuts(self):
        self.assertAlmostEqual(SCENARIOS["MILD"]["haircut"],     0.10)
        self.assertAlmostEqual(SCENARIOS["MODERATE"]["haircut"], 0.25)
        self.assertAlmostEqual(SCENARIOS["SEVERE"]["haircut"],   0.50)
        self.assertAlmostEqual(SCENARIOS["EXTREME"]["haircut"],  0.80)

    def test_scenario_labels_non_empty(self):
        for name, cfg in SCENARIOS.items():
            self.assertTrue(len(cfg["label"]) > 0, f"Empty label for {name}")

    def test_max_entries(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_concentration_tvl_pct(self):
        self.assertAlmostEqual(CONCENTRATION_TVL_PCT, 0.05)

    def test_coverage_thresholds_ordering(self):
        self.assertGreater(SAFE_COVERAGE, WATCH_COVERAGE)
        self.assertGreater(WATCH_COVERAGE, 0)


# ---------------------------------------------------------------------------
# Test _liquid_capital
# ---------------------------------------------------------------------------

class TestLiquidCapital(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()

    def test_empty_list_returns_zero(self):
        self.assertEqual(self.sim._liquid_capital([]), 0.0)

    def test_all_locked_returns_zero(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=7),
            _make_adapter("a2", 20_000, lock_days=30),
        ]
        self.assertEqual(self.sim._liquid_capital(adapters), 0.0)

    def test_all_liquid_returns_sum(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=0),
            _make_adapter("a2", 20_000, lock_days=0),
            _make_adapter("a3",  5_000, lock_days=0),
        ]
        self.assertAlmostEqual(self.sim._liquid_capital(adapters), 35_000.0)

    def test_mixed_only_counts_liquid(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=0),
            _make_adapter("a2", 20_000, lock_days=7),
            _make_adapter("a3",  5_000, lock_days=0),
        ]
        self.assertAlmostEqual(self.sim._liquid_capital(adapters), 15_000.0)

    def test_single_liquid(self):
        self.assertAlmostEqual(
            self.sim._liquid_capital([_make_adapter("a1", 12_345, lock_days=0)]),
            12_345.0,
        )

    def test_zero_capital_liquid(self):
        a = _make_adapter("a1", capital=0.0, lock_days=0)
        self.assertAlmostEqual(self.sim._liquid_capital([a]), 0.0)


# ---------------------------------------------------------------------------
# Test _locked_capital
# ---------------------------------------------------------------------------

class TestLockedCapital(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()

    def test_empty_list_returns_zero(self):
        self.assertEqual(self.sim._locked_capital([]), 0.0)

    def test_all_liquid_returns_zero(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=0),
            _make_adapter("a2", 20_000, lock_days=0),
        ]
        self.assertEqual(self.sim._locked_capital(adapters), 0.0)

    def test_all_locked_returns_sum(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=7),
            _make_adapter("a2", 20_000, lock_days=30),
        ]
        self.assertAlmostEqual(self.sim._locked_capital(adapters), 30_000.0)

    def test_mixed_only_counts_locked(self):
        adapters = [
            _make_adapter("a1", 10_000, lock_days=0),
            _make_adapter("a2", 20_000, lock_days=7),
            _make_adapter("a3",  5_000, lock_days=0),
        ]
        self.assertAlmostEqual(self.sim._locked_capital(adapters), 20_000.0)

    def test_liquid_plus_locked_equal_total(self):
        adapters = [
            _make_adapter("a1", 30_000, lock_days=0),
            _make_adapter("a2", 70_000, lock_days=5),
        ]
        total = sum(a.capital_deployed for a in adapters)
        liquid = self.sim._liquid_capital(adapters)
        locked = self.sim._locked_capital(adapters)
        self.assertAlmostEqual(liquid + locked, total)


# ---------------------------------------------------------------------------
# Test _at_risk
# ---------------------------------------------------------------------------

class TestAtRisk(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()

    def test_empty_returns_empty(self):
        self.assertEqual(self.sim._at_risk([]), [])

    def test_tvl_zero_no_false_positive(self):
        a = _make_adapter("a1", capital=50_000, tvl=0.0)
        self.assertNotIn("a1", self.sim._at_risk([a]))

    def test_tvl_negative_no_false_positive(self):
        a = _make_adapter("a1", capital=50_000, tvl=-1.0)
        self.assertNotIn("a1", self.sim._at_risk([a]))

    def test_capital_exactly_five_pct_not_flagged(self):
        # 5 % boundary: capital == 5 % TVL → not > 5 %, so NOT at risk
        a = _make_adapter("a1", capital=5_000, tvl=100_000)
        self.assertNotIn("a1", self.sim._at_risk([a]))

    def test_capital_just_above_five_pct_flagged(self):
        a = _make_adapter("a1", capital=5_001, tvl=100_000)
        self.assertIn("a1", self.sim._at_risk([a]))

    def test_capital_well_below_five_pct_not_flagged(self):
        a = _make_adapter("a1", capital=1_000, tvl=1_000_000)
        self.assertNotIn("a1", self.sim._at_risk([a]))

    def test_capital_well_above_five_pct_flagged(self):
        a = _make_adapter("a1", capital=100_000, tvl=100_000)
        self.assertIn("a1", self.sim._at_risk([a]))

    def test_multiple_adapters_partial_flagging(self):
        adapters = [
            _make_adapter("safe",  capital=1_000, tvl=1_000_000),
            _make_adapter("risky", capital=60_000, tvl=100_000),
        ]
        result = self.sim._at_risk(adapters)
        self.assertNotIn("safe",  result)
        self.assertIn("risky",    result)

    def test_returns_correct_ids(self):
        adapters = [
            _make_adapter("x", capital=10_000, tvl=50_000),   # 20 % — flagged
            _make_adapter("y", capital=1_000,  tvl=500_000),  # 0.2 % — safe
        ]
        result = self.sim._at_risk(adapters)
        self.assertEqual(result, ["x"])


# ---------------------------------------------------------------------------
# Test _verdict
# ---------------------------------------------------------------------------

class TestVerdict(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()

    def test_safe_at_exact_threshold(self):
        self.assertEqual(self.sim._verdict(SAFE_COVERAGE), "SAFE")

    def test_safe_above_threshold(self):
        self.assertEqual(self.sim._verdict(0.50), "SAFE")
        self.assertEqual(self.sim._verdict(1.00), "SAFE")

    def test_safe_just_above_threshold(self):
        self.assertEqual(self.sim._verdict(SAFE_COVERAGE + 0.001), "SAFE")

    def test_watch_just_below_safe_threshold(self):
        self.assertEqual(self.sim._verdict(SAFE_COVERAGE - 0.001), "WATCH")

    def test_watch_at_watch_threshold(self):
        self.assertEqual(self.sim._verdict(WATCH_COVERAGE), "WATCH")

    def test_watch_mid_range(self):
        mid = (SAFE_COVERAGE + WATCH_COVERAGE) / 2
        self.assertEqual(self.sim._verdict(mid), "WATCH")

    def test_critical_just_below_watch_threshold(self):
        self.assertEqual(self.sim._verdict(WATCH_COVERAGE - 0.001), "CRITICAL")

    def test_critical_at_zero(self):
        self.assertEqual(self.sim._verdict(0.0), "CRITICAL")

    def test_critical_small_positive(self):
        self.assertEqual(self.sim._verdict(0.01), "CRITICAL")


# ---------------------------------------------------------------------------
# Test simulate — individual scenarios
# ---------------------------------------------------------------------------

class TestSimulate(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()
        # Standard portfolio: 60 % liquid, 40 % locked; total = 100 000
        self.adapters = [
            _make_adapter("liquid_a", 40_000, lock_days=0),
            _make_adapter("liquid_b", 20_000, lock_days=0),
            _make_adapter("locked_c", 40_000, lock_days=30),
        ]

    # -- Basic field correctness --

    def test_total_deployed(self):
        r = self.sim.simulate(self.adapters, "MILD")
        self.assertAlmostEqual(r.total_deployed, 100_000.0)

    def test_liquid_capital_field(self):
        r = self.sim.simulate(self.adapters, "MILD")
        self.assertAlmostEqual(r.liquid_capital, 60_000.0)

    def test_locked_capital_field(self):
        r = self.sim.simulate(self.adapters, "MILD")
        self.assertAlmostEqual(r.locked_capital, 40_000.0)

    def test_scenario_name_in_result(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        self.assertEqual(r.scenario, "MODERATE")

    def test_scenario_label_in_result(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        self.assertEqual(r.scenario_label, SCENARIOS["MODERATE"]["label"])

    # -- MILD scenario --

    def test_mild_withdrawable(self):
        r = self.sim.simulate(self.adapters, "MILD")
        # liquid=60 000, haircut=10 % → 54 000
        self.assertAlmostEqual(r.withdrawable_stress, 54_000.0)

    def test_mild_coverage(self):
        r = self.sim.simulate(self.adapters, "MILD")
        expected = 54_000.0 / 100_000.0
        self.assertAlmostEqual(r.coverage_ratio, round(expected, 6))

    def test_mild_verdict_safe(self):
        r = self.sim.simulate(self.adapters, "MILD")
        self.assertEqual(r.verdict, "SAFE")

    # -- MODERATE scenario --

    def test_moderate_withdrawable(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        # liquid=60 000, haircut=25 % → 45 000
        self.assertAlmostEqual(r.withdrawable_stress, 45_000.0)

    def test_moderate_coverage(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        expected = 45_000.0 / 100_000.0
        self.assertAlmostEqual(r.coverage_ratio, round(expected, 6))

    def test_moderate_verdict_safe(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        self.assertEqual(r.verdict, "SAFE")

    # -- SEVERE scenario --

    def test_severe_withdrawable(self):
        r = self.sim.simulate(self.adapters, "SEVERE")
        # liquid=60 000, haircut=50 % → 30 000
        self.assertAlmostEqual(r.withdrawable_stress, 30_000.0)

    def test_severe_coverage(self):
        r = self.sim.simulate(self.adapters, "SEVERE")
        expected = 30_000.0 / 100_000.0
        self.assertAlmostEqual(r.coverage_ratio, round(expected, 6))

    def test_severe_verdict_safe(self):
        r = self.sim.simulate(self.adapters, "SEVERE")
        self.assertEqual(r.verdict, "SAFE")

    # -- EXTREME scenario --

    def test_extreme_withdrawable(self):
        r = self.sim.simulate(self.adapters, "EXTREME")
        # liquid=60 000, haircut=80 % → 12 000
        self.assertAlmostEqual(r.withdrawable_stress, 12_000.0)

    def test_extreme_coverage(self):
        r = self.sim.simulate(self.adapters, "EXTREME")
        expected = 12_000.0 / 100_000.0
        self.assertAlmostEqual(r.coverage_ratio, round(expected, 6))

    def test_extreme_verdict_watch(self):
        r = self.sim.simulate(self.adapters, "EXTREME")
        # 12 % < 15 % → CRITICAL
        self.assertEqual(r.verdict, "CRITICAL")

    # -- Edge cases --

    def test_total_zero_no_division_error(self):
        r = self.sim.simulate([], "MODERATE")
        self.assertEqual(r.coverage_ratio, 0.0)
        self.assertEqual(r.total_deployed, 0.0)

    def test_all_locked_withdrawable_zero(self):
        locked = [
            _make_adapter("a", 50_000, lock_days=7),
            _make_adapter("b", 50_000, lock_days=30),
        ]
        r = self.sim.simulate(locked, "MILD")
        self.assertAlmostEqual(r.withdrawable_stress, 0.0)
        self.assertAlmostEqual(r.coverage_ratio, 0.0)

    def test_all_liquid_full_coverage_mild(self):
        liquid = [
            _make_adapter("a", 50_000, lock_days=0),
            _make_adapter("b", 50_000, lock_days=0),
        ]
        r = self.sim.simulate(liquid, "MILD")
        # withdrawable = 100 000 * 0.90 = 90 000; coverage = 0.90
        self.assertAlmostEqual(r.withdrawable_stress, 90_000.0)
        self.assertGreater(r.coverage_ratio, SAFE_COVERAGE)
        self.assertEqual(r.verdict, "SAFE")

    def test_unknown_scenario_defaults_to_moderate(self):
        r = self.sim.simulate(self.adapters, "NONEXISTENT")
        self.assertEqual(r.scenario, "MODERATE")

    def test_at_risk_adapters_populated(self):
        # capital = 10 % of TVL → flagged
        a = _make_adapter("risky", capital=5_000, tvl=50_000, lock_days=0)
        r = self.sim.simulate([a], "MILD")
        self.assertIn("risky", r.at_risk_adapters)

    def test_at_risk_empty_when_no_concentration(self):
        a = _make_adapter("safe", capital=1_000, tvl=10_000_000, lock_days=0)
        r = self.sim.simulate([a], "MILD")
        self.assertEqual(r.at_risk_adapters, [])

    def test_result_type(self):
        r = self.sim.simulate(self.adapters, "MILD")
        self.assertIsInstance(r, StressResult)

    def test_coverage_ratio_rounds_to_6dp(self):
        r = self.sim.simulate(self.adapters, "MODERATE")
        # round() to 6 decimal places
        self.assertEqual(r.coverage_ratio, round(r.coverage_ratio, 6))

    def test_extreme_critical_small_liquid_portfolio(self):
        """Only 10 % liquid capital → EXTREME yields very low coverage → CRITICAL."""
        adapters = [
            _make_adapter("liq", 10_000, lock_days=0),
            _make_adapter("loc", 90_000, lock_days=7),
        ]
        r = self.sim.simulate(adapters, "EXTREME")
        # withdrawable = 10 000 * 0.20 = 2 000; coverage = 2 %
        self.assertAlmostEqual(r.withdrawable_stress, 2_000.0)
        self.assertEqual(r.verdict, "CRITICAL")


# ---------------------------------------------------------------------------
# Test simulate_all
# ---------------------------------------------------------------------------

class TestSimulateAll(unittest.TestCase):

    def setUp(self):
        self.sim = LiquidityStressSimulator()
        self.adapters = [
            _make_adapter("a", 60_000, lock_days=0),
            _make_adapter("b", 40_000, lock_days=14),
        ]

    def test_returns_four_scenarios(self):
        results = self.sim.simulate_all(self.adapters)
        self.assertEqual(len(results), 4)

    def test_all_scenario_keys_present(self):
        results = self.sim.simulate_all(self.adapters)
        for key in SCENARIOS:
            self.assertIn(key, results)

    def test_each_value_is_stress_result(self):
        results = self.sim.simulate_all(self.adapters)
        for r in results.values():
            self.assertIsInstance(r, StressResult)

    def test_consistent_with_individual_simulate(self):
        results = self.sim.simulate_all(self.adapters)
        for scenario_name in SCENARIOS:
            individual = self.sim.simulate(self.adapters, scenario_name)
            batch = results[scenario_name]
            self.assertAlmostEqual(batch.coverage_ratio, individual.coverage_ratio)
            self.assertEqual(batch.verdict, individual.verdict)
            self.assertAlmostEqual(batch.withdrawable_stress, individual.withdrawable_stress)

    def test_withdrawable_decreases_with_severity(self):
        results = self.sim.simulate_all(self.adapters)
        order = ["MILD", "MODERATE", "SEVERE", "EXTREME"]
        for i in range(len(order) - 1):
            self.assertGreater(
                results[order[i]].withdrawable_stress,
                results[order[i + 1]].withdrawable_stress,
            )

    def test_empty_adapters_all_zero_coverage(self):
        results = self.sim.simulate_all([])
        for r in results.values():
            self.assertEqual(r.coverage_ratio, 0.0)


# ---------------------------------------------------------------------------
# Test save_result / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _result(self, scenario: str = "MODERATE") -> StressResult:
        sim = LiquidityStressSimulator()
        adapters = [_make_adapter("a", 80_000, lock_days=0)]
        return sim.simulate(adapters, scenario)

    def test_load_history_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            self.assertEqual(sim.load_history(), [])

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            sim.save_result(self._result())
            self.assertTrue(sim.data_file.exists())

    def test_save_result_persists_one_entry(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            sim.save_result(self._result("MILD"))
            history = sim.load_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["scenario"], "MILD")

    def test_save_result_multiple_entries(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            for scenario in SCENARIOS:
                sim.save_result(self._result(scenario))
            history = sim.load_history()
            self.assertEqual(len(history), 4)

    def test_save_result_ring_buffer_max_100(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            for _ in range(MAX_ENTRIES + 10):
                sim.save_result(self._result("MILD"))
            history = sim.load_history()
            self.assertEqual(len(history), MAX_ENTRIES)

    def test_save_result_atomic_no_tmp_file_after(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            sim.save_result(self._result())
            tmp = sim.data_file.with_suffix(".tmp")
            self.assertFalse(tmp.exists())

    def test_save_result_stores_required_keys(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            sim.save_result(self._result("SEVERE"))
            entry = sim.load_history()[0]
            for key in ("timestamp", "scenario", "coverage_ratio", "verdict", "withdrawable_stress"):
                self.assertIn(key, entry)

    def test_save_result_verdict_correct(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            r = self._result("MODERATE")
            sim.save_result(r)
            entry = sim.load_history()[0]
            self.assertEqual(entry["verdict"], r.verdict)

    def test_load_history_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            sim.data_file.parent.mkdir(parents=True, exist_ok=True)
            sim.data_file.write_text("{{not valid json")
            self.assertEqual(sim.load_history(), [])

    def test_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as d:
            sim = _make_sim(d)
            # Fill above limit; last scenario should be EXTREME
            scenarios = list(SCENARIOS.keys())
            for i in range(MAX_ENTRIES + 4):
                scen = scenarios[i % len(scenarios)]
                sim.save_result(self._result(scen))
            history = sim.load_history()
            self.assertEqual(len(history), MAX_ENTRIES)
            # Most recent entry is the last scenario pushed
            last_scen = scenarios[(MAX_ENTRIES + 3) % len(scenarios)]
            self.assertEqual(history[-1]["scenario"], last_scen)


if __name__ == "__main__":
    unittest.main()
