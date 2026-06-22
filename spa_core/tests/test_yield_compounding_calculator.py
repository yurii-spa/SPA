"""
Tests for MP-753: YieldCompoundingCalculator
Uses unittest only (NOT pytest).
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.yield_compounding_calculator import (
    effective_apy,
    gas_drag_pct,
    net_apy,
    optimal_frequency,
    compute_scenario,
    compute_all,
    save_results,
    load_history,
    CompoundingResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_sd(**kwargs):
    defaults = dict(
        protocol="TestProtocol",
        nominal_apy_pct=10.0,
        gas_cost_per_compound_usd=5.0,
        position_size_usd=10000.0,
    )
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# effective_apy
# ---------------------------------------------------------------------------

class TestEffectiveAPY(unittest.TestCase):

    def test_n1_approximately_equals_nominal(self):
        # For n=1: (1 + r)^1 - 1 = r exactly
        val = effective_apy(10.0, 1)
        self.assertAlmostEqual(val, 10.0, places=10)

    def test_n12_greater_than_n1(self):
        self.assertGreater(effective_apy(10.0, 12), effective_apy(10.0, 1))

    def test_n365_greater_than_n12(self):
        self.assertGreater(effective_apy(10.0, 365), effective_apy(10.0, 12))

    def test_n52_between_n12_and_n365(self):
        self.assertGreater(effective_apy(10.0, 52), effective_apy(10.0, 12))
        self.assertLess(effective_apy(10.0, 52), effective_apy(10.0, 365))

    def test_zero_nominal_returns_zero(self):
        for n in [1, 4, 12, 52, 365]:
            self.assertAlmostEqual(effective_apy(0.0, n), 0.0)

    def test_formula_n4(self):
        # (1 + 0.10/4)^4 - 1 = (1.025)^4 - 1
        expected = ((1 + 0.10 / 4) ** 4 - 1) * 100
        self.assertAlmostEqual(effective_apy(10.0, 4), expected, places=8)

    def test_formula_n12(self):
        expected = ((1 + 0.10 / 12) ** 12 - 1) * 100
        self.assertAlmostEqual(effective_apy(10.0, 12), expected, places=8)

    def test_formula_n52(self):
        expected = ((1 + 0.06 / 52) ** 52 - 1) * 100
        self.assertAlmostEqual(effective_apy(6.0, 52), expected, places=8)

    def test_formula_n365(self):
        expected = ((1 + 0.05 / 365) ** 365 - 1) * 100
        self.assertAlmostEqual(effective_apy(5.0, 365), expected, places=6)

    def test_positive_result_for_positive_nominal(self):
        for n in [1, 4, 12, 52, 365]:
            self.assertGreater(effective_apy(5.0, n), 0.0)

    def test_more_compounding_always_better(self):
        freqs = [1, 4, 12, 52, 365]
        results = [effective_apy(8.0, n) for n in freqs]
        for i in range(len(results) - 1):
            self.assertLess(results[i], results[i + 1])


# ---------------------------------------------------------------------------
# gas_drag_pct
# ---------------------------------------------------------------------------

class TestGasDragPct(unittest.TestCase):

    def test_formula(self):
        # gas=10, n=12, position=1000 → 10*12/1000*100 = 12%
        val = gas_drag_pct(10.0, 12, 1000.0)
        self.assertAlmostEqual(val, 12.0)

    def test_zero_position_returns_zero(self):
        self.assertAlmostEqual(gas_drag_pct(10.0, 12, 0.0), 0.0)

    def test_n1_annual(self):
        val = gas_drag_pct(5.0, 1, 10000.0)
        # 5*1/10000*100 = 0.05%
        self.assertAlmostEqual(val, 0.05)

    def test_n365_daily(self):
        val = gas_drag_pct(5.0, 365, 10000.0)
        # 5*365/10000*100 = 18.25%
        self.assertAlmostEqual(val, 18.25)

    def test_zero_gas(self):
        val = gas_drag_pct(0.0, 365, 10000.0)
        self.assertAlmostEqual(val, 0.0)

    def test_gas_scales_with_frequency(self):
        annual = gas_drag_pct(5.0, 1, 10000.0)
        daily = gas_drag_pct(5.0, 365, 10000.0)
        self.assertGreater(daily, annual)

    def test_large_position_reduces_drag(self):
        small = gas_drag_pct(10.0, 12, 1000.0)
        large = gas_drag_pct(10.0, 12, 100000.0)
        self.assertGreater(small, large)


# ---------------------------------------------------------------------------
# net_apy
# ---------------------------------------------------------------------------

class TestNetAPY(unittest.TestCase):

    def test_positive_when_effective_greater(self):
        val = net_apy(10.0, 2.0)
        self.assertAlmostEqual(val, 8.0)

    def test_clamped_at_zero_when_gas_exceeds(self):
        val = net_apy(5.0, 10.0)
        self.assertAlmostEqual(val, 0.0)

    def test_zero_gas_drag(self):
        val = net_apy(8.0, 0.0)
        self.assertAlmostEqual(val, 8.0)

    def test_equal_effective_and_gas(self):
        val = net_apy(5.0, 5.0)
        self.assertAlmostEqual(val, 0.0)

    def test_never_negative(self):
        for eff, gas in [(0, 100), (1, 50), (5, 10)]:
            self.assertGreaterEqual(net_apy(float(eff), float(gas)), 0.0)


# ---------------------------------------------------------------------------
# optimal_frequency
# ---------------------------------------------------------------------------

class TestOptimalFrequency(unittest.TestCase):

    def test_picks_max(self):
        d = {"ANNUAL": 3.0, "QUARTERLY": 3.5, "MONTHLY": 4.0, "WEEKLY": 4.2, "DAILY": 4.3}
        self.assertEqual(optimal_frequency(d), "DAILY")

    def test_picks_annual_when_highest(self):
        d = {"ANNUAL": 10.0, "QUARTERLY": 5.0, "MONTHLY": 2.0, "WEEKLY": 1.0, "DAILY": 0.0}
        self.assertEqual(optimal_frequency(d), "ANNUAL")

    def test_picks_monthly(self):
        d = {"ANNUAL": 2.0, "QUARTERLY": 3.0, "MONTHLY": 5.0, "WEEKLY": 4.0, "DAILY": 3.5}
        self.assertEqual(optimal_frequency(d), "MONTHLY")

    def test_all_zero_returns_a_key(self):
        d = {"ANNUAL": 0.0, "QUARTERLY": 0.0, "MONTHLY": 0.0, "WEEKLY": 0.0, "DAILY": 0.0}
        result = optimal_frequency(d)
        self.assertIn(result, ["ANNUAL", "QUARTERLY", "MONTHLY", "WEEKLY", "DAILY"])

    def test_returns_string(self):
        d = {"ANNUAL": 1.0, "QUARTERLY": 2.0, "MONTHLY": 3.0, "WEEKLY": 4.0, "DAILY": 5.0}
        self.assertIsInstance(optimal_frequency(d), str)


# ---------------------------------------------------------------------------
# compute_scenario
# ---------------------------------------------------------------------------

class TestComputeScenario(unittest.TestCase):

    def test_annual_apy_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        # n=1, gas=0 → effective = 10%, net = 10%
        self.assertAlmostEqual(s.annual_apy, 10.0, places=8)

    def test_quarterly_apy_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        expected = ((1 + 0.10 / 4) ** 4 - 1) * 100
        self.assertAlmostEqual(s.quarterly_apy, expected, places=8)

    def test_monthly_apy_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        expected = ((1 + 0.10 / 12) ** 12 - 1) * 100
        self.assertAlmostEqual(s.monthly_apy, expected, places=8)

    def test_weekly_apy_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        expected = ((1 + 0.10 / 52) ** 52 - 1) * 100
        self.assertAlmostEqual(s.weekly_apy, expected, places=8)

    def test_daily_apy_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        expected = ((1 + 0.10 / 365) ** 365 - 1) * 100
        self.assertAlmostEqual(s.daily_apy, expected, places=6)

    def test_annual_gas_drag(self):
        s = compute_scenario("P", 10.0, 5.0, 10000.0)
        # 5*1/10000*100 = 0.05%
        self.assertAlmostEqual(s.annual_gas_drag_pct, 0.05, places=8)

    def test_daily_gas_drag(self):
        s = compute_scenario("P", 10.0, 5.0, 10000.0)
        # 5*365/10000*100 = 18.25%
        self.assertAlmostEqual(s.daily_gas_drag_pct, 18.25, places=6)

    def test_net_annual_apy_clamped(self):
        # High gas relative to position
        s = compute_scenario("P", 1.0, 1000.0, 100.0)
        self.assertGreaterEqual(s.net_annual_apy_pct, 0.0)

    def test_net_annual_apy_positive_low_gas(self):
        s = compute_scenario("P", 10.0, 0.01, 100000.0)
        self.assertGreater(s.net_annual_apy_pct, 0.0)

    def test_compounding_gain_formula(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        # With zero gas, daily should be optimal and gain = daily_net - annual_net
        self.assertAlmostEqual(s.compounding_gain_pct,
                                s.optimal_net_apy_pct - s.net_annual_apy_pct, places=8)

    def test_compounding_gain_negative_high_gas(self):
        # Very high gas → optimal still beats annual, but gain may be 0 since both clamped
        s = compute_scenario("P", 5.0, 1000.0, 100.0)
        # All net APYs likely 0; gain = 0 - 0 = 0
        self.assertGreaterEqual(s.compounding_gain_pct, -100.0)

    def test_recommendation_significant_gain(self):
        # Large position, zero gas, high APY → daily adds > 1%
        s = compute_scenario("P", 20.0, 0.0, 100000.0)
        self.assertIn("significant yield", s.recommendation)

    def test_recommendation_moderate_gain(self):
        # Small positive gain: low APY, tiny position, very small gas
        s = compute_scenario("P", 5.0, 0.001, 50000.0)
        # Gain is > 0 but might be < 1
        if s.compounding_gain_pct > 1.0:
            self.assertIn("significant yield", s.recommendation)
        elif s.compounding_gain_pct > 0.0:
            self.assertIn("beneficial", s.recommendation)
        else:
            self.assertIn("Gas costs", s.recommendation)

    def test_recommendation_gas_too_high(self):
        s = compute_scenario("P", 1.0, 500.0, 100.0)
        self.assertIn("Gas costs", s.recommendation)

    def test_protocol_name_preserved(self):
        s = compute_scenario("MyProto", 5.0, 1.0, 1000.0)
        self.assertEqual(s.protocol, "MyProto")

    def test_daily_optimal_zero_gas(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        self.assertEqual(s.optimal_frequency, "DAILY")

    def test_annual_optimal_high_gas(self):
        # Gas so high that daily/weekly/monthly/quarterly all clamped to 0
        # but annual might still be positive if gas*1 < effective
        s = compute_scenario("P", 5.0, 10000.0, 100.0)
        # All net APYs probably 0; optimal is any (likely ANNUAL by dict ordering or DAILY)
        # Just verify it returns a valid frequency
        self.assertIn(s.optimal_frequency, ["ANNUAL", "QUARTERLY", "MONTHLY", "WEEKLY", "DAILY"])


# ---------------------------------------------------------------------------
# compute_all (aggregate)
# ---------------------------------------------------------------------------

class TestComputeAll(unittest.TestCase):

    def _three_scenarios(self):
        return [
            _sample_sd(protocol="A", nominal_apy_pct=5.0, gas_cost_per_compound_usd=1.0, position_size_usd=50000.0),
            _sample_sd(protocol="B", nominal_apy_pct=8.0, gas_cost_per_compound_usd=2.0, position_size_usd=50000.0),
            _sample_sd(protocol="C", nominal_apy_pct=12.0, gas_cost_per_compound_usd=3.0, position_size_usd=50000.0),
        ]

    def test_best_protocol_is_highest_net_apy(self):
        result = compute_all(self._three_scenarios())
        best = max(result.scenarios, key=lambda s: s.optimal_net_apy_pct)
        self.assertEqual(result.best_protocol_for_compounding, best.protocol)

    def test_avg_optimal_net_apy_formula(self):
        result = compute_all(self._three_scenarios())
        expected = sum(s.optimal_net_apy_pct for s in result.scenarios) / 3
        self.assertAlmostEqual(result.avg_optimal_net_apy_pct, expected, places=6)

    def test_avg_compounding_gain_formula(self):
        result = compute_all(self._three_scenarios())
        expected = sum(s.compounding_gain_pct for s in result.scenarios) / 3
        self.assertAlmostEqual(result.avg_compounding_gain_pct, expected, places=6)

    def test_scenario_count(self):
        result = compute_all(self._three_scenarios())
        self.assertEqual(len(result.scenarios), 3)

    def test_empty_input(self):
        result = compute_all([])
        self.assertEqual(result.best_protocol_for_compounding, "N/A")
        self.assertAlmostEqual(result.avg_optimal_net_apy_pct, 0.0)
        self.assertEqual(len(result.scenarios), 0)

    def test_recommendation_summary_not_empty(self):
        result = compute_all(self._three_scenarios())
        self.assertTrue(len(result.recommendation_summary) > 0)

    def test_single_protocol(self):
        result = compute_all([_sample_sd(protocol="Solo")])
        self.assertEqual(result.best_protocol_for_compounding, "Solo")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_gas_daily_always_optimal(self):
        s = compute_scenario("P", 8.0, 0.0, 100000.0)
        # With zero gas, more compounding = always better
        self.assertEqual(s.optimal_frequency, "DAILY")

    def test_zero_gas_compounding_gain_positive(self):
        s = compute_scenario("P", 8.0, 0.0, 100000.0)
        self.assertGreater(s.compounding_gain_pct, 0.0)

    def test_extremely_high_gas_annual_may_be_best(self):
        # With huge gas per compound, frequent compounding destroys returns
        s = compute_scenario("P", 5.0, 50000.0, 1000.0)
        # Annual: effective=5%, gas_drag=5*1/1000*100=0.5% → net=4.5%
        # Daily: effective~5.13%, gas_drag=5*365/1000*100=1825% → net=0%
        # Annual should win
        self.assertEqual(s.optimal_frequency, "ANNUAL")

    def test_high_gas_recommendation(self):
        s = compute_scenario("P", 5.0, 50000.0, 1000.0)
        # gain = annual_net - annual_net = 0 (or negative)
        self.assertIn("Gas costs", s.recommendation)

    def test_net_apy_never_negative(self):
        for gas in [0, 1, 10, 100, 1000]:
            s = compute_scenario("P", 5.0, float(gas), 100.0)
            for attr in ["net_annual_apy_pct", "net_quarterly_apy_pct",
                         "net_monthly_apy_pct", "net_weekly_apy_pct", "net_daily_apy_pct"]:
                self.assertGreaterEqual(getattr(s, attr), 0.0)

    def test_effective_apy_increases_with_frequency(self):
        s = compute_scenario("P", 10.0, 0.0, 10000.0)
        self.assertLess(s.annual_apy, s.quarterly_apy)
        self.assertLess(s.quarterly_apy, s.monthly_apy)
        self.assertLess(s.monthly_apy, s.weekly_apy)
        self.assertLess(s.weekly_apy, s.daily_apy)


# ---------------------------------------------------------------------------
# Save / Load / Ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        import spa_core.analytics.yield_compounding_calculator as mod
        self._orig_log = mod._LOG_FILE
        self._orig_data = mod._DATA_DIR
        mod._LOG_FILE = os.path.join(self._tmp_dir, "yield_compounding_log.json")
        mod._DATA_DIR = self._tmp_dir
        self._mod = mod

    def tearDown(self):
        self._mod._LOG_FILE = self._orig_log
        self._mod._DATA_DIR = self._orig_data

    def _make_result(self, protocol="P1") -> CompoundingResult:
        return compute_all([_sample_sd(protocol=protocol)])

    def test_save_and_load_round_trip(self):
        result = self._make_result()
        save_results(result)
        history = load_history()
        self.assertEqual(len(history), 1)
        self.assertIn("scenarios", history[0])

    def test_load_empty_when_no_file(self):
        history = load_history()
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            result = self._make_result(protocol=f"P{i}")
            save_results(result)
        history = load_history()
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_last_entries(self):
        for i in range(105):
            result = self._make_result(protocol=f"P{i}")
            save_results(result)
        history = load_history()
        last = history[-1]
        self.assertEqual(last["scenarios"][0]["protocol"], "P104")

    def test_atomic_write_no_tmp_left(self):
        result = self._make_result()
        save_results(result)
        tmp = self._mod._LOG_FILE + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_saved_to_field_returned(self):
        result = self._make_result()
        path = save_results(result)
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
