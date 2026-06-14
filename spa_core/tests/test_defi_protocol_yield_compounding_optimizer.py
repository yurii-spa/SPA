"""
MP-1134 Tests: DeFiProtocolYieldCompoundingOptimizer

Run: python3 -m unittest spa_core.tests.test_defi_protocol_yield_compounding_optimizer -v
"""

import json
import math
import os
import tempfile
import unittest
from typing import Any, Dict, List

from spa_core.analytics.defi_protocol_yield_compounding_optimizer import (
    DeFiProtocolYieldCompoundingOptimizer,
    _effective_apy,
    _optimal_label,
    main,
)

# ── helpers ──────────────────────────────────────────────────────────────────

BASE_FREQS = [1, 4, 12, 26, 52, 365]


def run(
    base_apy: float = 8.0,
    position: float = 50_000.0,
    gas: float = 5.0,
    freqs: List[int] = None,
    protocol: str = "test-protocol",
    cfg: Dict[str, Any] = None,
) -> Dict[str, Any]:
    if freqs is None:
        freqs = BASE_FREQS
    if cfg is None:
        cfg = {}
    opt = DeFiProtocolYieldCompoundingOptimizer()
    return opt.analyze(
        base_apy_pct=base_apy,
        position_size_usd=position,
        gas_cost_per_compound_usd=gas,
        compounding_frequencies=freqs,
        protocol_name=protocol,
        config=cfg,
    )


def freq_result(output: Dict[str, Any], freq: int) -> Dict[str, Any]:
    for r in output["results"]:
        if r["frequency"] == freq:
            return r
    raise KeyError(f"freq {freq} not found in results")


# ── TestOutputShape ───────────────────────────────────────────────────────────

class TestOutputShape(unittest.TestCase):
    def setUp(self):
        self.out = run()

    def test_top_level_keys_present(self):
        expected = {
            "protocol_name", "base_apy_pct", "position_size_usd",
            "gas_cost_per_compound_usd", "results",
            "optimal_frequency", "optimal_net_apy_pct",
            "optimal_label", "gas_drag_at_optimal_pct", "timestamp",
        }
        self.assertEqual(expected, set(self.out.keys()))

    def test_results_length_matches_frequencies(self):
        freqs = [1, 12, 52]
        out = run(freqs=freqs)
        self.assertEqual(len(out["results"]), 3)

    def test_results_empty_on_no_frequencies(self):
        out = run(freqs=[])
        self.assertEqual(out["results"], [])

    def test_result_row_keys(self):
        row = self.out["results"][0]
        expected = {
            "frequency", "effective_apy_pct", "annual_gas_cost_usd",
            "net_apy_pct", "net_annual_yield_usd",
        }
        self.assertEqual(expected, set(row.keys()))

    def test_optimal_frequency_is_int(self):
        self.assertIsInstance(self.out["optimal_frequency"], int)

    def test_optimal_net_apy_is_float(self):
        self.assertIsInstance(self.out["optimal_net_apy_pct"], float)

    def test_optimal_label_is_str(self):
        self.assertIsInstance(self.out["optimal_label"], str)

    def test_gas_drag_at_optimal_is_float(self):
        self.assertIsInstance(self.out["gas_drag_at_optimal_pct"], float)

    def test_timestamp_present_and_nonempty(self):
        self.assertTrue(self.out["timestamp"])

    def test_protocol_name_echoed(self):
        out = run(protocol="Aave-USDC")
        self.assertEqual(out["protocol_name"], "Aave-USDC")

    def test_base_apy_echoed(self):
        out = run(base_apy=12.5)
        self.assertAlmostEqual(out["base_apy_pct"], 12.5, places=4)

    def test_position_size_echoed(self):
        out = run(position=75_000.0)
        self.assertAlmostEqual(out["position_size_usd"], 75_000.0, places=2)

    def test_gas_per_compound_echoed(self):
        out = run(gas=10.0)
        self.assertAlmostEqual(out["gas_cost_per_compound_usd"], 10.0, places=4)

    def test_each_result_frequency_present_in_input(self):
        freqs = [1, 4, 12, 26, 52, 365]
        out = run(freqs=freqs)
        result_freqs = [r["frequency"] for r in out["results"]]
        self.assertEqual(sorted(result_freqs), sorted(freqs))


# ── TestEffectiveApyFormula ───────────────────────────────────────────────────

class TestEffectiveApyFormula(unittest.TestCase):
    """Verify effective_apy = ((1 + base/100/freq)^freq - 1)*100"""

    def _expected(self, base: float, freq: int) -> float:
        return ((1.0 + base / 100.0 / freq) ** freq - 1.0) * 100.0

    def test_annual_compounding_freq1(self):
        base = 10.0
        result = _effective_apy(base, 1)
        self.assertAlmostEqual(result, self._expected(base, 1), places=6)

    def test_quarterly_compounding_freq4(self):
        base = 8.0
        self.assertAlmostEqual(_effective_apy(base, 4), self._expected(base, 4), places=6)

    def test_monthly_compounding_freq12(self):
        base = 6.0
        self.assertAlmostEqual(_effective_apy(base, 12), self._expected(base, 12), places=6)

    def test_biweekly_compounding_freq26(self):
        base = 5.0
        self.assertAlmostEqual(_effective_apy(base, 26), self._expected(base, 26), places=6)

    def test_weekly_compounding_freq52(self):
        base = 4.0
        self.assertAlmostEqual(_effective_apy(base, 52), self._expected(base, 52), places=6)

    def test_daily_compounding_freq365(self):
        base = 8.0
        self.assertAlmostEqual(_effective_apy(base, 365), self._expected(base, 365), places=6)

    def test_higher_freq_yields_higher_effective_apy(self):
        base = 10.0
        apy_1 = _effective_apy(base, 1)
        apy_12 = _effective_apy(base, 12)
        apy_365 = _effective_apy(base, 365)
        self.assertLess(apy_1, apy_12)
        self.assertLess(apy_12, apy_365)

    def test_freq1_effective_apy_equals_base_apy(self):
        # ((1 + r)^1 - 1) * 100 == r * 100 == base_apy
        base = 7.5
        self.assertAlmostEqual(_effective_apy(base, 1), base, places=6)

    def test_daily_close_to_continuous_compounding(self):
        base = 10.0
        daily = _effective_apy(base, 365)
        continuous = (math.exp(base / 100.0) - 1.0) * 100.0
        self.assertAlmostEqual(daily, continuous, delta=0.01)

    def test_zero_base_apy_effective_is_zero(self):
        self.assertAlmostEqual(_effective_apy(0.0, 12), 0.0, places=6)

    def test_freq_zero_returns_base_apy(self):
        self.assertAlmostEqual(_effective_apy(8.0, 0), 8.0, places=6)

    def test_results_match_helper_for_all_freqs(self):
        out = run(base_apy=10.0, gas=0.0)  # zero gas to isolate formula
        for row in out["results"]:
            freq = row["frequency"]
            expected = self._expected(10.0, freq)
            self.assertAlmostEqual(row["effective_apy_pct"], expected, places=4)

    def test_large_base_apy_no_crash(self):
        result = _effective_apy(200.0, 52)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 200.0)

    def test_small_base_apy_no_crash(self):
        result = _effective_apy(0.01, 365)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)

    def test_effective_apy_monotone_in_freq_for_positive_base(self):
        base = 5.0
        freqs = [1, 2, 4, 12, 52, 365]
        apys = [_effective_apy(base, f) for f in freqs]
        for i in range(len(apys) - 1):
            self.assertLessEqual(apys[i], apys[i + 1])


# ── TestAnnualGasCost ─────────────────────────────────────────────────────────

class TestAnnualGasCost(unittest.TestCase):
    """annual_gas = freq * gas_cost_per_compound_usd"""

    def test_annual_freq1_gas(self):
        out = run(gas=10.0, freqs=[1])
        self.assertAlmostEqual(out["results"][0]["annual_gas_cost_usd"], 10.0, places=4)

    def test_monthly_freq12_gas(self):
        out = run(gas=5.0, freqs=[12])
        self.assertAlmostEqual(out["results"][0]["annual_gas_cost_usd"], 60.0, places=4)

    def test_weekly_freq52_gas(self):
        out = run(gas=2.0, freqs=[52])
        self.assertAlmostEqual(out["results"][0]["annual_gas_cost_usd"], 104.0, places=4)

    def test_daily_freq365_gas(self):
        out = run(gas=1.0, freqs=[365])
        self.assertAlmostEqual(out["results"][0]["annual_gas_cost_usd"], 365.0, places=4)

    def test_zero_gas_per_compound_no_gas_cost(self):
        out = run(gas=0.0, freqs=[52])
        self.assertAlmostEqual(out["results"][0]["annual_gas_cost_usd"], 0.0, places=4)

    def test_annual_gas_proportional_to_freq(self):
        out = run(gas=3.0, freqs=[4, 12, 52])
        gas_costs = {r["frequency"]: r["annual_gas_cost_usd"] for r in out["results"]}
        self.assertAlmostEqual(gas_costs[4],  12.0, places=4)
        self.assertAlmostEqual(gas_costs[12], 36.0, places=4)
        self.assertAlmostEqual(gas_costs[52], 156.0, places=4)

    def test_gas_drag_pct_formula(self):
        # gas_drag = annual_gas / position * 100
        out = run(gas=5.0, position=10_000.0, freqs=[12])
        row = out["results"][0]
        # 5*12=60; 60/10000*100 = 0.60%
        expected_drag = 60.0 / 10_000.0 * 100.0
        self.assertAlmostEqual(row["effective_apy_pct"] - row["net_apy_pct"], expected_drag, places=4)

    def test_gas_drag_at_optimal_matches_optimal_freq_gas(self):
        out = run(gas=5.0, position=50_000.0)
        opt_freq = out["optimal_frequency"]
        opt_row = freq_result(out, opt_freq)
        expected = opt_row["annual_gas_cost_usd"] / 50_000.0 * 100.0
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], expected, places=4)

    def test_annual_gas_greater_for_higher_freq(self):
        out = run(gas=5.0, freqs=[1, 52])
        gas_1 = freq_result(out, 1)["annual_gas_cost_usd"]
        gas_52 = freq_result(out, 52)["annual_gas_cost_usd"]
        self.assertLess(gas_1, gas_52)

    def test_multiple_gas_values(self):
        for gas in [0.5, 1.0, 5.0, 20.0, 100.0]:
            out = run(gas=gas, freqs=[12])
            row = out["results"][0]
            self.assertAlmostEqual(row["annual_gas_cost_usd"], gas * 12, places=4)


# ── TestNetApy ────────────────────────────────────────────────────────────────

class TestNetApy(unittest.TestCase):
    """net_apy = effective_apy - annual_gas / position * 100"""

    def test_net_apy_positive_for_large_position(self):
        out = run(base_apy=8.0, position=1_000_000.0, gas=5.0, freqs=[12])
        self.assertGreater(out["results"][0]["net_apy_pct"], 0.0)

    def test_net_apy_can_be_negative_for_small_position(self):
        out = run(base_apy=5.0, position=100.0, gas=100.0, freqs=[52])
        self.assertLess(out["results"][0]["net_apy_pct"], 0.0)

    def test_net_apy_equals_effective_when_no_gas(self):
        out = run(base_apy=8.0, gas=0.0, freqs=[12])
        row = out["results"][0]
        self.assertAlmostEqual(row["net_apy_pct"], row["effective_apy_pct"], places=6)

    def test_net_apy_formula_spot_check(self):
        # base=10%, gas=$5, freq=12, position=$100_000
        # eff_apy = ((1+0.1/12)^12-1)*100 ≈ 10.4713%
        # annual_gas = 60; drag = 60/100000*100 = 0.06%
        # net ≈ 10.4713 - 0.06 = 10.4113%
        out = run(base_apy=10.0, gas=5.0, position=100_000.0, freqs=[12])
        row = out["results"][0]
        eff = ((1.0 + 10.0 / 100.0 / 12.0) ** 12 - 1.0) * 100.0
        drag = 60.0 / 100_000.0 * 100.0
        self.assertAlmostEqual(row["net_apy_pct"], eff - drag, places=4)

    def test_net_apy_decreases_as_gas_increases(self):
        out_low = run(base_apy=8.0, gas=1.0, position=50_000.0, freqs=[12])
        out_high = run(base_apy=8.0, gas=50.0, position=50_000.0, freqs=[12])
        self.assertGreater(
            out_low["results"][0]["net_apy_pct"],
            out_high["results"][0]["net_apy_pct"],
        )

    def test_net_apy_increases_as_position_increases(self):
        out_small = run(base_apy=8.0, gas=5.0, position=1_000.0, freqs=[12])
        out_large = run(base_apy=8.0, gas=5.0, position=1_000_000.0, freqs=[12])
        self.assertGreater(
            out_large["results"][0]["net_apy_pct"],
            out_small["results"][0]["net_apy_pct"],
        )

    def test_net_apy_row_consistency(self):
        out = run()
        for row in out["results"]:
            freq = row["frequency"]
            eff = _effective_apy(8.0, freq)
            drag = (5.0 * freq / 50_000.0) * 100.0
            expected_net = eff - drag
            self.assertAlmostEqual(row["net_apy_pct"], expected_net, places=4)

    def test_net_yield_usd_formula(self):
        # net_yield_usd = net_apy / 100 * position
        out = run(base_apy=8.0, gas=5.0, position=50_000.0, freqs=[1])
        row = out["results"][0]
        expected = row["net_apy_pct"] / 100.0 * 50_000.0
        self.assertAlmostEqual(row["net_annual_yield_usd"], expected, places=4)

    def test_net_yield_usd_positive_large_position(self):
        out = run(position=1_000_000.0, gas=1.0, freqs=[1])
        self.assertGreater(out["results"][0]["net_annual_yield_usd"], 0.0)

    def test_net_yield_usd_can_be_negative(self):
        out = run(base_apy=1.0, position=10.0, gas=1000.0, freqs=[365])
        self.assertLess(out["results"][0]["net_annual_yield_usd"], 0.0)


# ── TestOptimalFrequency ──────────────────────────────────────────────────────

class TestOptimalFrequency(unittest.TestCase):

    def test_optimal_frequency_in_input_list(self):
        out = run()
        self.assertIn(out["optimal_frequency"], BASE_FREQS)

    def test_optimal_net_apy_is_maximum(self):
        out = run()
        net_apys = [r["net_apy_pct"] for r in out["results"]]
        self.assertAlmostEqual(out["optimal_net_apy_pct"], max(net_apys), places=4)

    def test_zero_gas_optimal_is_highest_freq(self):
        # With no gas cost, more compounding is always better.
        out = run(gas=0.0, freqs=[1, 4, 12, 52, 365])
        self.assertEqual(out["optimal_frequency"], 365)

    def test_very_high_gas_optimal_is_lowest_freq(self):
        # Gas is huge relative to position; compound as rarely as possible.
        out = run(base_apy=5.0, position=1_000.0, gas=500.0, freqs=[1, 4, 12, 52])
        self.assertEqual(out["optimal_frequency"], 1)

    def test_optimal_single_frequency(self):
        out = run(freqs=[12])
        self.assertEqual(out["optimal_frequency"], 12)

    def test_empty_frequencies_optimal_zero(self):
        out = run(freqs=[])
        self.assertEqual(out["optimal_frequency"], 0)

    def test_optimal_matches_row_net_apy(self):
        out = run()
        opt_row = freq_result(out, out["optimal_frequency"])
        self.assertAlmostEqual(out["optimal_net_apy_pct"], opt_row["net_apy_pct"], places=6)

    def test_all_negative_net_apy_picks_least_bad(self):
        # Tiny position, huge gas → all negative; optimal = least negative
        out = run(base_apy=5.0, position=1.0, gas=500.0, freqs=[1, 4, 12])
        net_apys = {r["frequency"]: r["net_apy_pct"] for r in out["results"]}
        opt_freq = out["optimal_frequency"]
        for freq, net in net_apys.items():
            if freq != opt_freq:
                self.assertLessEqual(net, net_apys[opt_freq])

    def test_optimal_gas_drag_nonnegative(self):
        out = run()
        self.assertGreaterEqual(out["gas_drag_at_optimal_pct"], 0.0)

    def test_gas_drag_at_optimal_correct(self):
        out = run(gas=5.0, position=50_000.0)
        opt_freq = out["optimal_frequency"]
        opt_row = freq_result(out, opt_freq)
        expected = opt_row["annual_gas_cost_usd"] / 50_000.0 * 100.0
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], expected, places=4)

    def test_breakeven_position_behavior(self):
        # At position > certain threshold, higher freq is better; below, lower freq wins
        out_big = run(base_apy=8.0, gas=5.0, position=10_000_000.0, freqs=[1, 365])
        out_tiny = run(base_apy=8.0, gas=500.0, position=10.0, freqs=[1, 365])
        self.assertEqual(out_big["optimal_frequency"], 365)
        self.assertEqual(out_tiny["optimal_frequency"], 1)

    def test_optimal_frequency_type_int(self):
        out = run()
        self.assertIsInstance(out["optimal_frequency"], int)

    def test_optimal_net_apy_pct_type_float(self):
        out = run()
        self.assertIsInstance(out["optimal_net_apy_pct"], float)

    def test_base_apy_zero_no_crash(self):
        out = run(base_apy=0.0)
        self.assertIsInstance(out["optimal_frequency"], int)
        self.assertIsInstance(out["optimal_net_apy_pct"], float)

    def test_large_position_no_crash(self):
        out = run(position=1e9)
        self.assertIsInstance(out["optimal_frequency"], int)


# ── TestOptimalLabel ──────────────────────────────────────────────────────────

class TestOptimalLabel(unittest.TestCase):

    def test_label_daily_freq365(self):
        self.assertEqual(_optimal_label(365), "DAILY")

    def test_label_daily_freq730(self):
        self.assertEqual(_optimal_label(730), "DAILY")

    def test_label_weekly_freq52(self):
        self.assertEqual(_optimal_label(52), "WEEKLY")

    def test_label_weekly_freq100(self):
        self.assertEqual(_optimal_label(100), "WEEKLY")

    def test_label_biweekly_freq26(self):
        self.assertEqual(_optimal_label(26), "BIWEEKLY")

    def test_label_biweekly_freq30(self):
        self.assertEqual(_optimal_label(30), "BIWEEKLY")

    def test_label_monthly_freq12(self):
        self.assertEqual(_optimal_label(12), "MONTHLY")

    def test_label_monthly_freq15(self):
        self.assertEqual(_optimal_label(15), "MONTHLY")

    def test_label_quarterly_freq4(self):
        self.assertEqual(_optimal_label(4), "QUARTERLY")

    def test_label_quarterly_freq6(self):
        self.assertEqual(_optimal_label(6), "QUARTERLY")

    def test_label_annually_freq1(self):
        self.assertEqual(_optimal_label(1), "ANNUALLY")

    def test_label_annually_freq3(self):
        self.assertEqual(_optimal_label(3), "ANNUALLY")

    def test_output_optimal_label_daily_when_zero_gas(self):
        out = run(gas=0.0, freqs=[1, 4, 12, 52, 365])
        self.assertEqual(out["optimal_label"], "DAILY")

    def test_output_optimal_label_annually_when_huge_gas(self):
        out = run(base_apy=5.0, position=100.0, gas=1000.0, freqs=[1, 4, 12])
        self.assertEqual(out["optimal_label"], "ANNUALLY")

    def test_valid_labels_set(self):
        valid = {"DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY", "QUARTERLY", "ANNUALLY"}
        for freq in [1, 4, 12, 26, 52, 365, 730]:
            self.assertIn(_optimal_label(freq), valid)

    def test_label_boundary_52_is_weekly(self):
        self.assertEqual(_optimal_label(52), "WEEKLY")

    def test_label_boundary_51_is_biweekly(self):
        # 51 < 52, so falls to BIWEEKLY (>=26)
        self.assertEqual(_optimal_label(51), "BIWEEKLY")


# ── TestGasDragAtOptimal ──────────────────────────────────────────────────────

class TestGasDragAtOptimal(unittest.TestCase):

    def test_gas_drag_zero_when_no_gas(self):
        out = run(gas=0.0)
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], 0.0, places=6)

    def test_gas_drag_positive_with_gas(self):
        out = run(gas=10.0, position=50_000.0)
        self.assertGreater(out["gas_drag_at_optimal_pct"], 0.0)

    def test_gas_drag_at_optimal_consistent_with_row(self):
        out = run(gas=5.0, position=50_000.0)
        opt_freq = out["optimal_frequency"]
        opt_row = freq_result(out, opt_freq)
        expected = opt_row["annual_gas_cost_usd"] / 50_000.0 * 100.0
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], expected, places=4)

    def test_gas_drag_increases_with_gas_cost(self):
        out1 = run(gas=1.0, freqs=[12])
        out2 = run(gas=20.0, freqs=[12])
        self.assertLess(out1["gas_drag_at_optimal_pct"], out2["gas_drag_at_optimal_pct"])

    def test_gas_drag_decreases_with_larger_position(self):
        out1 = run(gas=10.0, position=1_000.0, freqs=[12])
        out2 = run(gas=10.0, position=10_000_000.0, freqs=[12])
        self.assertGreater(out1["gas_drag_at_optimal_pct"], out2["gas_drag_at_optimal_pct"])

    def test_gas_drag_formula_spot(self):
        # optimal_freq=12, gas=$5, position=$10_000 → drag = 60/10000*100 = 0.60%
        out = run(base_apy=10.0, gas=5.0, position=10_000.0, freqs=[1, 4, 12])
        opt_freq = out["optimal_frequency"]
        opt_row = freq_result(out, opt_freq)
        expected = opt_row["annual_gas_cost_usd"] / 10_000.0 * 100.0
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], expected, places=4)

    def test_gas_drag_at_optimal_nonnegative(self):
        for gas in [0.0, 1.0, 100.0]:
            out = run(gas=gas)
            self.assertGreaterEqual(out["gas_drag_at_optimal_pct"], 0.0)

    def test_empty_frequencies_gas_drag_zero(self):
        out = run(freqs=[])
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], 0.0, places=6)

    def test_gas_drag_pct_is_float(self):
        out = run()
        self.assertIsInstance(out["gas_drag_at_optimal_pct"], float)

    def test_position_zero_gas_drag_zero(self):
        out = run(position=0.0, gas=10.0, freqs=[12])
        self.assertAlmostEqual(out["gas_drag_at_optimal_pct"], 0.0, places=6)


# ── TestEdgeCases ─────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_position_zero_no_crash(self):
        out = run(position=0.0)
        self.assertIsInstance(out["optimal_frequency"], int)

    def test_gas_zero_no_crash(self):
        out = run(gas=0.0)
        self.assertIsInstance(out["optimal_net_apy_pct"], float)

    def test_empty_frequencies_returns_valid_structure(self):
        out = run(freqs=[])
        self.assertEqual(out["results"], [])
        self.assertEqual(out["optimal_frequency"], 0)
        self.assertAlmostEqual(out["optimal_net_apy_pct"], 0.0, places=6)

    def test_single_frequency_is_optimal(self):
        out = run(freqs=[26])
        self.assertEqual(out["optimal_frequency"], 26)
        self.assertEqual(len(out["results"]), 1)

    def test_negative_base_apy_no_crash(self):
        out = run(base_apy=-5.0)
        self.assertIsInstance(out, dict)

    def test_very_large_gas_all_negative_net_apy(self):
        out = run(base_apy=5.0, position=100.0, gas=10_000.0, freqs=[1, 4, 12])
        for row in out["results"]:
            self.assertLess(row["net_apy_pct"], 0.0)

    def test_very_high_base_apy_no_overflow(self):
        out = run(base_apy=500.0, freqs=[365])
        self.assertIsInstance(out["results"][0]["effective_apy_pct"], float)

    def test_freq_one_in_list(self):
        out = run(freqs=[1])
        row = out["results"][0]
        self.assertAlmostEqual(row["effective_apy_pct"], row["effective_apy_pct"], places=6)

    def test_float_frequencies_converted_to_int(self):
        out = run(freqs=[1.0, 12.0, 52.0])  # type: ignore[arg-type]
        for row in out["results"]:
            self.assertIsInstance(row["frequency"], int)

    def test_string_protocol_name_empty(self):
        out = run(protocol="")
        self.assertEqual(out["protocol_name"], "")

    def test_identical_net_apy_picks_first(self):
        # zero base_apy and zero gas → all net_apy = 0; first freq wins
        out = run(base_apy=0.0, gas=0.0, freqs=[4, 12, 52])
        self.assertEqual(out["optimal_frequency"], 4)

    def test_position_float_precision(self):
        out = run(position=12345.67)
        self.assertAlmostEqual(out["position_size_usd"], 12345.67, places=2)

    def test_result_order_preserved(self):
        freqs = [365, 1, 52, 12]
        out = run(freqs=freqs)
        result_freqs = [r["frequency"] for r in out["results"]]
        self.assertEqual(result_freqs, freqs)

    def test_gas_drag_pct_small_position(self):
        out = run(position=10.0, gas=5.0, freqs=[12])
        row = out["results"][0]
        self.assertGreater(row["net_apy_pct"], -1e9)  # doesn't blow up

    def test_helper_result_for_freq_returns_none_on_missing(self):
        opt = DeFiProtocolYieldCompoundingOptimizer()
        out = run(freqs=[1, 12])
        result = opt.result_for_freq(out, 52)
        self.assertIsNone(result)

    def test_helper_result_for_freq_returns_row(self):
        opt = DeFiProtocolYieldCompoundingOptimizer()
        out = run(freqs=[12, 52])
        row = opt.result_for_freq(out, 12)
        self.assertIsNotNone(row)
        self.assertEqual(row["frequency"], 12)


# ── TestLogWriting ────────────────────────────────────────────────────────────

class TestLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "yield_compounding_optimizer_log.json")

    def _cfg(self) -> Dict[str, Any]:
        return {"write_log": True, "log_path": self.log_path}

    def test_log_file_created_on_write(self):
        run(cfg=self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_keys(self):
        run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        for key in ("ts", "protocol_name", "optimal_frequency", "optimal_net_apy_pct",
                    "optimal_label", "gas_drag_at_optimal_pct"):
            self.assertIn(key, entry)

    def test_no_log_without_write_log(self):
        run()  # no write_log → no file
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_appends_multiple_entries(self):
        for _ in range(3):
            run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_enforced(self):
        cfg = {"write_log": True, "log_path": self.log_path, "log_cap": 5}
        for _ in range(8):
            run(cfg=cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 5)

    def test_ring_buffer_keeps_newest_entries(self):
        cfg = {"write_log": True, "log_path": self.log_path, "log_cap": 3}
        for i in range(5):
            run(protocol=f"proto-{i}", cfg=cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        names = [e["protocol_name"] for e in data]
        self.assertIn("proto-4", names)
        self.assertNotIn("proto-0", names)

    def test_atomic_write_no_tmp_file_remaining(self):
        run(cfg=self._cfg())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_log_entry_optimal_frequency_correct(self):
        run(gas=0.0, freqs=[1, 365], cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["optimal_frequency"], 365)

    def test_log_entry_protocol_name(self):
        run(protocol="my-protocol", cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_name"], "my-protocol")

    def test_corrupt_log_file_reset(self):
        with open(self.log_path, "w") as fh:
            fh.write("not valid json!!!")
        run(cfg=self._cfg())  # should not crash
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)


# ── TestCLI ───────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):

    def test_main_check_exits_zero(self):
        rc = main(["--check"])
        self.assertEqual(rc, 0)

    def test_main_no_args_exits_zero(self):
        rc = main([])
        self.assertEqual(rc, 0)

    def test_main_run_writes_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main(["--run", "--data-dir", tmp])
            self.assertEqual(rc, 0)
            log_path = os.path.join(tmp, "yield_compounding_optimizer_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_main_invalid_arg_exits_zero(self):
        rc = main(["--unknown-flag-xyz"])
        self.assertEqual(rc, 0)

    def test_main_run_log_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            main(["--run", "--data-dir", tmp])
            log_path = os.path.join(tmp, "yield_compounding_optimizer_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)


# ── TestNetAnnualYield ────────────────────────────────────────────────────────

class TestNetAnnualYield(unittest.TestCase):

    def test_net_yield_formula(self):
        out = run(base_apy=10.0, gas=5.0, position=100_000.0, freqs=[12])
        row = out["results"][0]
        expected = row["net_apy_pct"] / 100.0 * 100_000.0
        self.assertAlmostEqual(row["net_annual_yield_usd"], expected, places=4)

    def test_zero_position_zero_net_yield(self):
        out = run(position=0.0, freqs=[12])
        row = out["results"][0]
        self.assertAlmostEqual(row["net_annual_yield_usd"], 0.0, places=4)

    def test_net_yield_scales_with_position(self):
        out1 = run(position=10_000.0, gas=0.0, base_apy=8.0, freqs=[12])
        out2 = run(position=100_000.0, gas=0.0, base_apy=8.0, freqs=[12])
        yield1 = out1["results"][0]["net_annual_yield_usd"]
        yield2 = out2["results"][0]["net_annual_yield_usd"]
        self.assertAlmostEqual(yield2 / yield1, 10.0, places=2)

    def test_net_yield_positive_for_profitable_scenario(self):
        out = run(base_apy=10.0, gas=1.0, position=1_000_000.0, freqs=[12])
        self.assertGreater(out["results"][0]["net_annual_yield_usd"], 0.0)

    def test_net_yield_consistent_across_frequencies(self):
        out = run(base_apy=8.0, gas=0.0, position=50_000.0)
        for row in out["results"]:
            expected = row["net_apy_pct"] / 100.0 * 50_000.0
            self.assertAlmostEqual(row["net_annual_yield_usd"], expected, places=4)

    def test_optimal_net_apy_matches_max_net_yield(self):
        out = run()
        best_yield_row = max(out["results"], key=lambda r: r["net_annual_yield_usd"])
        best_apy_row = max(out["results"], key=lambda r: r["net_apy_pct"])
        # For same position, max net_apy == max net_yield_usd
        self.assertEqual(best_yield_row["frequency"], best_apy_row["frequency"])


if __name__ == "__main__":
    unittest.main()
