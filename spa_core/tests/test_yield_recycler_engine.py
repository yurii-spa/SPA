"""Unit tests for spa_core.analytics.yield_recycler_engine (MP-698).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_yield_recycler_engine -v
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_recycler_engine import (
    MAX_ENTRIES,
    RecycleComparison,
    RecycleScenario,
    YieldRecyclerEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scenario(
    scenario_id: str = "test",
    initial_capital: float = 100_000.0,
    base_apy_pct: float = 5.0,
    recycle_into_apy_pct: float = 5.0,
    recycle_frequency_days: int = 30,
    simulation_days: int = 365,
    gas_cost_per_recycle: float = 0.0,
    reinvest_pct: float = 100.0,
) -> RecycleScenario:
    return RecycleScenario(
        scenario_id=scenario_id,
        initial_capital=initial_capital,
        base_apy_pct=base_apy_pct,
        recycle_into_apy_pct=recycle_into_apy_pct,
        recycle_frequency_days=recycle_frequency_days,
        simulation_days=simulation_days,
        gas_cost_per_recycle=gas_cost_per_recycle,
        reinvest_pct=reinvest_pct,
    )


ENGINE = YieldRecyclerEngine()


# ---------------------------------------------------------------------------
# 1. SIMPLE_HOLD simulation
# ---------------------------------------------------------------------------

class TestSimpleHold(unittest.TestCase):

    def test_hold_final_capital_5pct_365d(self):
        """5% APY, 365 days: final ≈ 100000 * (1 + 0.05/365)^365."""
        s = _scenario(base_apy_pct=5.0, simulation_days=365, initial_capital=100_000)
        result = ENGINE._simulate_hold(s)
        expected = 100_000 * (1 + 0.05 / 365) ** 365
        self.assertAlmostEqual(result.final_capital, expected, places=4)

    def test_hold_total_yield_equals_final_minus_initial(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertAlmostEqual(
            result.total_yield_usd, result.final_capital - s.initial_capital, places=6
        )

    def test_hold_gas_zero(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertEqual(result.total_gas_cost_usd, 0.0)

    def test_hold_num_recycles_zero(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertEqual(result.num_recycles, 0)

    def test_hold_net_yield_equals_total_yield(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertAlmostEqual(result.net_yield_usd, result.total_yield_usd, places=6)

    def test_hold_strategy_label(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertEqual(result.strategy, "SIMPLE_HOLD")

    def test_hold_effective_apy_approx_base_apy_365d(self):
        """Over 365 days, effective APY is slightly above nominal APY due to daily
        compounding (e.g., 5% nominal → ~5.13% effective).  Accept ±0.2%."""
        s = _scenario(base_apy_pct=5.0, simulation_days=365)
        result = ENGINE._simulate_hold(s)
        # Effective APY should be >= nominal (compounding) and within 0.2% above it
        self.assertGreaterEqual(result.effective_apy_pct, 5.0)
        self.assertAlmostEqual(result.effective_apy_pct, 5.0, delta=0.2)

    def test_hold_effective_apy_10pct(self):
        """10% nominal → ~10.52% effective APY (daily compounding). Accept ±0.6%."""
        s = _scenario(base_apy_pct=10.0, simulation_days=365)
        result = ENGINE._simulate_hold(s)
        self.assertGreaterEqual(result.effective_apy_pct, 10.0)
        self.assertAlmostEqual(result.effective_apy_pct, 10.0, delta=0.6)

    def test_hold_improvement_over_hold_is_zero(self):
        s = _scenario()
        result = ENGINE._simulate_hold(s)
        self.assertEqual(result.improvement_over_hold_pct, 0.0)

    def test_hold_scenario_id_preserved(self):
        s = _scenario(scenario_id="abc-123")
        result = ENGINE._simulate_hold(s)
        self.assertEqual(result.scenario_id, "abc-123")

    def test_hold_higher_apy_higher_yield(self):
        s5 = _scenario(base_apy_pct=5.0)
        s10 = _scenario(base_apy_pct=10.0)
        r5 = ENGINE._simulate_hold(s5)
        r10 = ENGINE._simulate_hold(s10)
        self.assertGreater(r10.total_yield_usd, r5.total_yield_usd)

    def test_hold_longer_period_higher_yield(self):
        s1 = _scenario(simulation_days=180)
        s2 = _scenario(simulation_days=365)
        r1 = ENGINE._simulate_hold(s1)
        r2 = ENGINE._simulate_hold(s2)
        self.assertGreater(r2.total_yield_usd, r1.total_yield_usd)

    def test_hold_zero_apy(self):
        s = _scenario(base_apy_pct=0.0)
        result = ENGINE._simulate_hold(s)
        self.assertAlmostEqual(result.total_yield_usd, 0.0, places=6)


# ---------------------------------------------------------------------------
# 2. ACTIVE_RECYCLE simulation
# ---------------------------------------------------------------------------

class TestActiveRecycle(unittest.TestCase):

    def test_recycle_strategy_label(self):
        s = _scenario()
        result = ENGINE._simulate_recycle(s)
        self.assertEqual(result.strategy, "ACTIVE_RECYCLE")

    def test_recycle_num_recycles_equals_days_div_freq(self):
        """Use an exact-divisor scenario: 364 / 7 = 52 complete intervals."""
        s = _scenario(simulation_days=364, recycle_frequency_days=7)
        result = ENGINE._simulate_recycle(s)
        expected = 364 // 7   # 52
        self.assertEqual(result.num_recycles, expected)

    def test_recycle_monthly_num_recycles(self):
        """360 / 30 = 12 complete monthly intervals."""
        s = _scenario(simulation_days=360, recycle_frequency_days=30)
        result = ENGINE._simulate_recycle(s)
        expected = 360 // 30   # 12
        self.assertEqual(result.num_recycles, expected)

    def test_recycle_zero_gas_100pct_reinvest_beats_hold(self):
        """Zero gas + 100% reinvest into higher-APY pool beats simple hold.
        recycle_into_apy_pct > base_apy_pct is what creates the outperformance."""
        s = _scenario(
            base_apy_pct=5.0,
            recycle_into_apy_pct=8.0,   # recycle yield into higher-yield pool
            recycle_frequency_days=7,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        )
        hold = ENGINE._simulate_hold(s)
        recycle = ENGINE._simulate_recycle(s)
        self.assertGreater(recycle.net_yield_usd, hold.net_yield_usd)

    def test_recycle_high_gas_low_yield_hold_wins(self):
        """Gas >> yield benefit → net_yield < hold."""
        s = _scenario(
            initial_capital=1_000,
            base_apy_pct=2.0,
            recycle_frequency_days=7,
            gas_cost_per_recycle=100.0,
            reinvest_pct=100.0,
        )
        hold = ENGINE._simulate_hold(s)
        recycle = ENGINE._simulate_recycle(s)
        self.assertLess(recycle.net_yield_usd, hold.net_yield_usd)

    def test_recycle_total_gas_equals_gas_per_recycle_times_num(self):
        gas_per = 10.0
        s = _scenario(
            simulation_days=365,
            recycle_frequency_days=30,
            gas_cost_per_recycle=gas_per,
        )
        result = ENGINE._simulate_recycle(s)
        self.assertAlmostEqual(
            result.total_gas_cost_usd,
            gas_per * result.num_recycles,
            places=6,
        )

    def test_recycle_net_yield_equals_total_minus_gas(self):
        s = _scenario(gas_cost_per_recycle=5.0)
        result = ENGINE._simulate_recycle(s)
        self.assertAlmostEqual(
            result.net_yield_usd,
            result.total_yield_usd - result.total_gas_cost_usd,
            places=4,
        )

    def test_recycle_zero_reinvest_less_yield_than_hold(self):
        """0% reinvest: pool_base is fixed (no compounding).  Hold compounds daily,
        so hold.total_yield > recycle.total_yield in the dual-pool model."""
        s = _scenario(
            base_apy_pct=5.0,
            simulation_days=360,
            recycle_frequency_days=30,
            gas_cost_per_recycle=0.0,
            reinvest_pct=0.0,
        )
        hold = ENGINE._simulate_hold(s)
        recycle = ENGINE._simulate_recycle(s)
        # No reinvestment → recycle earns simple (fixed-pool) yield ≤ compounding hold
        self.assertLessEqual(recycle.total_yield_usd, hold.total_yield_usd)

    def test_recycle_scenario_id_preserved(self):
        s = _scenario(scenario_id="xyz-789")
        result = ENGINE._simulate_recycle(s)
        self.assertEqual(result.scenario_id, "xyz-789")

    def test_recycle_50pct_reinvest_less_yield_than_100pct(self):
        s100 = _scenario(reinvest_pct=100.0, gas_cost_per_recycle=0.0)
        s50 = _scenario(reinvest_pct=50.0, gas_cost_per_recycle=0.0)
        r100 = ENGINE._simulate_recycle(s100)
        r50 = ENGINE._simulate_recycle(s50)
        self.assertGreater(r100.net_yield_usd, r50.net_yield_usd)

    def test_recycle_more_frequent_more_yield_zero_gas(self):
        """Daily recycle beats monthly with same rates and zero gas.
        Both use sim_days=360 so daily (360 intervals) vs monthly (12 intervals).
        Daily pools reinvested capital faster → more total yield."""
        s_daily = _scenario(
            simulation_days=360, recycle_frequency_days=1,
            gas_cost_per_recycle=0.0, reinvest_pct=100.0,
        )
        s_monthly = _scenario(
            simulation_days=360, recycle_frequency_days=30,
            gas_cost_per_recycle=0.0, reinvest_pct=100.0,
        )
        r_daily = ENGINE._simulate_recycle(s_daily)
        r_monthly = ENGINE._simulate_recycle(s_monthly)
        self.assertGreater(r_daily.net_yield_usd, r_monthly.net_yield_usd)

    def test_recycle_num_recycles_exact_divisor(self):
        s = _scenario(simulation_days=360, recycle_frequency_days=30)
        result = ENGINE._simulate_recycle(s)
        self.assertEqual(result.num_recycles, 12)

    def test_recycle_large_gas_capital_stays_nonnegative(self):
        s = _scenario(
            initial_capital=100.0,
            gas_cost_per_recycle=1000.0,
            simulation_days=10,
            recycle_frequency_days=1,
        )
        result = ENGINE._simulate_recycle(s)
        self.assertGreaterEqual(result.final_capital, 0.0)


# ---------------------------------------------------------------------------
# 3. compare() — RecycleComparison
# ---------------------------------------------------------------------------

class TestCompare(unittest.TestCase):

    def test_compare_returns_comparison_object(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertIsInstance(cmp, RecycleComparison)

    def test_compare_winner_recycle_zero_gas(self):
        """Weekly recycle into higher-APY pool (8%) with zero gas → RECYCLE wins."""
        s = _scenario(
            base_apy_pct=5.0,
            recycle_into_apy_pct=8.0,
            recycle_frequency_days=7,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        )
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.winner, "RECYCLE")

    def test_compare_winner_hold_high_gas(self):
        s = _scenario(
            initial_capital=1_000,
            base_apy_pct=2.0,
            gas_cost_per_recycle=200.0,
            recycle_frequency_days=7,
        )
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.winner, "HOLD")

    def test_compare_net_improvement_recycle_wins(self):
        s = _scenario(
            base_apy_pct=5.0,
            recycle_into_apy_pct=8.0,
            recycle_frequency_days=7,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        )
        cmp = ENGINE.compare(s)
        self.assertGreater(cmp.net_improvement_usd, 0.0)

    def test_compare_net_improvement_hold_wins(self):
        s = _scenario(
            initial_capital=1_000,
            base_apy_pct=1.0,
            gas_cost_per_recycle=500.0,
            recycle_frequency_days=7,
        )
        cmp = ENGINE.compare(s)
        self.assertLess(cmp.net_improvement_usd, 0.0)

    def test_compare_net_improvement_equals_recycle_minus_hold(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertAlmostEqual(
            cmp.net_improvement_usd,
            cmp.recycle.net_yield_usd - cmp.hold.net_yield_usd,
            places=6,
        )

    def test_compare_hold_result_is_simple_hold(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.hold.strategy, "SIMPLE_HOLD")

    def test_compare_recycle_result_is_active_recycle(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.recycle.strategy, "ACTIVE_RECYCLE")

    def test_compare_scenario_id_propagated(self):
        s = _scenario(scenario_id="compare-001")
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.scenario_id, "compare-001")
        self.assertEqual(cmp.hold.scenario_id, "compare-001")
        self.assertEqual(cmp.recycle.scenario_id, "compare-001")

    def test_compare_recommendation_recycle_contains_keyword(self):
        """When RECYCLE wins, recommendation contains 'Recycle wins'."""
        s = _scenario(
            base_apy_pct=5.0,
            recycle_into_apy_pct=8.0,
            recycle_frequency_days=7,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        )
        cmp = ENGINE.compare(s)
        self.assertIn("Recycle", cmp.recommendation)

    def test_compare_recommendation_hold_contains_keyword(self):
        s = _scenario(
            initial_capital=500,
            base_apy_pct=1.0,
            gas_cost_per_recycle=1000.0,
            recycle_frequency_days=7,
        )
        cmp = ENGINE.compare(s)
        self.assertIn("hold", cmp.recommendation.lower())

    def test_compare_break_even_no_advantage_is_inf(self):
        """When gas > yield benefit, break_even should be inf."""
        s = _scenario(
            initial_capital=500,
            base_apy_pct=1.0,
            gas_cost_per_recycle=500.0,
            recycle_frequency_days=7,
        )
        cmp = ENGINE.compare(s)
        self.assertTrue(math.isinf(cmp.break_even_days))

    def test_compare_break_even_positive_when_recycle_wins(self):
        s = _scenario(gas_cost_per_recycle=5.0, reinvest_pct=100.0)
        cmp = ENGINE.compare(s)
        # if recycle wins, break_even is either finite positive or inf
        if cmp.winner == "RECYCLE":
            self.assertGreaterEqual(cmp.break_even_days, 0.0)

    def test_compare_hold_improvement_always_zero(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.hold.improvement_over_hold_pct, 0.0)

    def test_compare_recommendation_contains_reinvest_pct(self):
        """Recycle recommendation mentions reinvest %."""
        s = _scenario(gas_cost_per_recycle=0.0, reinvest_pct=75.0)
        cmp = ENGINE.compare(s)
        if cmp.winner == "RECYCLE":
            self.assertIn("75", cmp.recommendation)

    def test_compare_recommendation_contains_sim_days(self):
        """Recycle recommendation mentions simulation_days."""
        s = _scenario(gas_cost_per_recycle=0.0, simulation_days=180)
        cmp = ENGINE.compare(s)
        if cmp.winner == "RECYCLE":
            self.assertIn("180", cmp.recommendation)

    def test_compare_recycle_improvement_pct_positive_when_wins(self):
        s = _scenario(gas_cost_per_recycle=0.0)
        cmp = ENGINE.compare(s)
        if cmp.winner == "RECYCLE":
            self.assertGreater(cmp.recycle.improvement_over_hold_pct, 0.0)


# ---------------------------------------------------------------------------
# 4. compare_batch()
# ---------------------------------------------------------------------------

class TestCompareBatch(unittest.TestCase):

    def test_batch_empty_returns_empty_list(self):
        result = ENGINE.compare_batch([])
        self.assertEqual(result, [])

    def test_batch_single_scenario(self):
        scenarios = [_scenario()]
        result = ENGINE.compare_batch(scenarios)
        self.assertEqual(len(result), 1)

    def test_batch_multiple_scenarios(self):
        scenarios = [
            _scenario(scenario_id="s1", gas_cost_per_recycle=0.0),
            _scenario(scenario_id="s2", gas_cost_per_recycle=100.0, initial_capital=500),
            _scenario(scenario_id="s3", base_apy_pct=10.0),
        ]
        result = ENGINE.compare_batch(scenarios)
        self.assertEqual(len(result), 3)

    def test_batch_ids_match_order(self):
        scenarios = [
            _scenario(scenario_id="first"),
            _scenario(scenario_id="second"),
        ]
        result = ENGINE.compare_batch(scenarios)
        self.assertEqual(result[0].scenario_id, "first")
        self.assertEqual(result[1].scenario_id, "second")

    def test_batch_all_return_comparison_type(self):
        scenarios = [_scenario(), _scenario(gas_cost_per_recycle=10.0)]
        result = ENGINE.compare_batch(scenarios)
        for cmp in result:
            self.assertIsInstance(cmp, RecycleComparison)


# ---------------------------------------------------------------------------
# 5. _effective_apy()
# ---------------------------------------------------------------------------

class TestEffectiveApy(unittest.TestCase):

    def test_effective_apy_same_initial_final_zero(self):
        apy = YieldRecyclerEngine._effective_apy(100_000, 100_000, 365)
        self.assertAlmostEqual(apy, 0.0, places=6)

    def test_effective_apy_double_one_year(self):
        """Doubling capital in 1 year → 100% APY."""
        apy = YieldRecyclerEngine._effective_apy(100_000, 200_000, 365)
        self.assertAlmostEqual(apy, 100.0, places=4)

    def test_effective_apy_known_5pct(self):
        """5% daily-compounded over 365 days gives ~5.127% effective APY.
        We verify the formula is internally consistent (round-trip)."""
        daily = 0.05 / 365
        final = 100_000 * (1 + daily) ** 365
        apy = YieldRecyclerEngine._effective_apy(100_000, final, 365)
        # Daily compounding of 5% nominal → effective APY slightly above 5%
        self.assertGreater(apy, 5.0)
        self.assertLess(apy, 5.5)

    def test_effective_apy_zero_days_returns_zero(self):
        apy = YieldRecyclerEngine._effective_apy(100_000, 110_000, 0)
        self.assertEqual(apy, 0.0)

    def test_effective_apy_zero_initial_returns_zero(self):
        apy = YieldRecyclerEngine._effective_apy(0, 110_000, 365)
        self.assertEqual(apy, 0.0)

    def test_effective_apy_positive_when_final_greater(self):
        apy = YieldRecyclerEngine._effective_apy(100_000, 105_000, 365)
        self.assertGreater(apy, 0.0)


# ---------------------------------------------------------------------------
# 6. save_results() / load_history()
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _tmp_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # delete so save_results starts fresh
        return Path(path)

    def test_load_history_missing_file_returns_empty(self):
        p = Path("/tmp/nonexistent_recycler_XYZ.json")
        result = ENGINE.load_history(data_file=p)
        self.assertEqual(result, [])

    def test_save_creates_file(self):
        p = self._tmp_file()
        s = _scenario()
        cmp = ENGINE.compare(s)
        ENGINE.save_results([cmp], data_file=p)
        self.assertTrue(p.exists())
        p.unlink()

    def test_save_valid_json(self):
        p = self._tmp_file()
        s = _scenario()
        cmp = ENGINE.compare(s)
        ENGINE.save_results([cmp], data_file=p)
        with open(p) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        p.unlink()

    def test_save_and_load_round_trip(self):
        p = self._tmp_file()
        s = _scenario(scenario_id="round-trip")
        cmp = ENGINE.compare(s)
        ENGINE.save_results([cmp], data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["scenario_id"], "round-trip")
        p.unlink()

    def test_ring_buffer_max_entries(self):
        p = self._tmp_file()
        # Save MAX_ENTRIES + 5 entries
        for i in range(MAX_ENTRIES + 5):
            s = _scenario(scenario_id=f"s{i}")
            cmp = ENGINE.compare(s)
            ENGINE.save_results([cmp], data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        self.assertLessEqual(len(loaded), MAX_ENTRIES)
        p.unlink()

    def test_ring_buffer_keeps_latest(self):
        p = self._tmp_file()
        for i in range(MAX_ENTRIES + 3):
            s = _scenario(scenario_id=f"s{i}")
            cmp = ENGINE.compare(s)
            ENGINE.save_results([cmp], data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        # Last entry should be the most recent one
        self.assertEqual(loaded[-1]["scenario_id"], f"s{MAX_ENTRIES + 2}")
        p.unlink()

    def test_save_atomic_no_tmp_leftover(self):
        p = self._tmp_file()
        s = _scenario()
        cmp = ENGINE.compare(s)
        ENGINE.save_results([cmp], data_file=p)
        tmp = Path(str(p) + ".tmp")
        self.assertFalse(tmp.exists())
        p.unlink()

    def test_save_multiple_comparisons(self):
        p = self._tmp_file()
        scenarios = [_scenario(scenario_id=f"s{i}") for i in range(5)]
        comparisons = ENGINE.compare_batch(scenarios)
        ENGINE.save_results(comparisons, data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        self.assertEqual(len(loaded), 5)
        p.unlink()

    def test_load_corrupt_json_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"not valid json {{{")
        os.close(fd)
        p = Path(path)
        result = ENGINE.load_history(data_file=p)
        self.assertEqual(result, [])
        p.unlink()

    def test_load_non_list_json_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b'{"key": "value"}')
        os.close(fd)
        p = Path(path)
        result = ENGINE.load_history(data_file=p)
        self.assertEqual(result, [])
        p.unlink()

    def test_saved_entry_has_saved_at_field(self):
        p = self._tmp_file()
        s = _scenario()
        cmp = ENGINE.compare(s)
        ENGINE.save_results([cmp], data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        self.assertIn("saved_at", loaded[0])
        p.unlink()

    def test_save_results_appends_to_existing(self):
        p = self._tmp_file()
        s1 = _scenario(scenario_id="first")
        s2 = _scenario(scenario_id="second")
        ENGINE.save_results([ENGINE.compare(s1)], data_file=p)
        ENGINE.save_results([ENGINE.compare(s2)], data_file=p)
        loaded = ENGINE.load_history(data_file=p)
        ids = [e["scenario_id"] for e in loaded]
        self.assertIn("first", ids)
        self.assertIn("second", ids)
        p.unlink()


# ---------------------------------------------------------------------------
# 7. Edge cases / regression
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_very_small_capital(self):
        s = _scenario(initial_capital=0.01, gas_cost_per_recycle=0.001)
        cmp = ENGINE.compare(s)
        self.assertIsInstance(cmp, RecycleComparison)

    def test_single_day_simulation(self):
        s = _scenario(simulation_days=1, recycle_frequency_days=1)
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.recycle.num_recycles, 1)

    def test_recycle_freq_greater_than_sim_days(self):
        """freq > sim_days → floor(10/30) = 0 complete intervals, zero recycles."""
        s = _scenario(simulation_days=10, recycle_frequency_days=30)
        result = ENGINE._simulate_recycle(s)
        self.assertEqual(result.num_recycles, 0)

    def test_zero_reinvest_pct_high_gas(self):
        """0% reinvest: capital decreases by gas each cycle."""
        s = _scenario(
            initial_capital=10_000,
            gas_cost_per_recycle=10.0,
            reinvest_pct=0.0,
            recycle_frequency_days=30,
        )
        result = ENGINE._simulate_recycle(s)
        # Capital should be initial - total_gas (no reinvest → no growth)
        expected_capital = s.initial_capital - result.total_gas_cost_usd
        self.assertAlmostEqual(result.final_capital, expected_capital, delta=1.0)

    def test_winner_field_is_string(self):
        s = _scenario()
        cmp = ENGINE.compare(s)
        self.assertIn(cmp.winner, ("RECYCLE", "HOLD"))

    def test_hold_simulation_days_180(self):
        s = _scenario(simulation_days=180, base_apy_pct=8.0)
        result = ENGINE._simulate_hold(s)
        daily = 0.08 / 365
        expected = 100_000 * (1 + daily) ** 180
        self.assertAlmostEqual(result.final_capital, expected, places=2)

    def test_recycle_with_very_high_apy(self):
        """Very high recycle_into_apy + weekly recycling + zero gas → RECYCLE wins."""
        s = _scenario(
            base_apy_pct=5.0,
            recycle_into_apy_pct=50.0,
            recycle_frequency_days=7,
            gas_cost_per_recycle=0.0,
            reinvest_pct=100.0,
        )
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.winner, "RECYCLE")

    def test_compare_consistent_scenario_id_across_fields(self):
        s = _scenario(scenario_id="consistency-check")
        cmp = ENGINE.compare(s)
        self.assertEqual(cmp.scenario_id, cmp.hold.scenario_id)
        self.assertEqual(cmp.scenario_id, cmp.recycle.scenario_id)


if __name__ == "__main__":
    unittest.main()
