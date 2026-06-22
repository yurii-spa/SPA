"""
Tests for MP-861 DeFiCrossChainYieldComparator
≥ 65 unittest cases covering calculations, labels, edge cases, chain summary,
ring-buffer log, and all recommendation strings.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root on path
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_cross_chain_yield_comparator import (
    analyze,
    _efficiency_label,
    _recommendation,
    _LOG_CAP,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

def _opp(
    protocol="Proto",
    chain="ethereum",
    gross_apy_pct=10.0,
    bridge_cost_usd=0.0,
    gas_cost=1.0,
    interactions=2,
    capital=100_000.0,
    days=90,
):
    return {
        "protocol": protocol,
        "chain": chain,
        "gross_apy_pct": gross_apy_pct,
        "bridge_cost_usd": bridge_cost_usd,
        "gas_cost_per_interaction_usd": gas_cost,
        "interactions_per_month": interactions,
        "capital_usd": capital,
        "holding_period_days": days,
    }


class TestEmptyInput(unittest.TestCase):
    def test_empty_list_returns_dict(self):
        r = analyze([])
        self.assertIsInstance(r, dict)

    def test_empty_best_net_yield_is_none(self):
        r = analyze([])
        self.assertIsNone(r["best_net_yield"])

    def test_empty_best_net_apy_is_none(self):
        r = analyze([])
        self.assertIsNone(r["best_net_apy"])

    def test_empty_reference_chain_net_apy_is_none(self):
        r = analyze([])
        self.assertIsNone(r["reference_chain_net_apy"])

    def test_empty_chain_summary_is_dict(self):
        r = analyze([])
        self.assertEqual(r["chain_summary"], {})

    def test_empty_opportunities_list(self):
        r = analyze([])
        self.assertEqual(r["opportunities"], [])

    def test_empty_has_timestamp(self):
        before = time.time()
        r = analyze([])
        self.assertGreaterEqual(r["timestamp"], before)


class TestGrossYieldCalculation(unittest.TestCase):
    def _gross(self, capital, apy, days):
        return capital * (apy / 100.0) * (days / 365.0)

    def test_basic_gross_yield(self):
        r = analyze([_opp(capital=100_000, gross_apy_pct=10.0, days=365,
                          gas_cost=0, interactions=0, bridge_cost_usd=0)])
        e = r["opportunities"][0]
        expected = 100_000 * 0.10
        self.assertAlmostEqual(e["gross_yield_usd"], expected, places=4)

    def test_gross_yield_90_days(self):
        r = analyze([_opp(capital=50_000, gross_apy_pct=4.0, days=90,
                          gas_cost=0, interactions=0, bridge_cost_usd=0)])
        e = r["opportunities"][0]
        expected = 50_000 * 0.04 * (90 / 365)
        self.assertAlmostEqual(e["gross_yield_usd"], expected, places=4)

    def test_gross_yield_zero_capital(self):
        r = analyze([_opp(capital=0, gross_apy_pct=10.0, days=90)])
        e = r["opportunities"][0]
        self.assertEqual(e["gross_yield_usd"], 0.0)

    def test_gross_yield_zero_days(self):
        r = analyze([_opp(capital=100_000, gross_apy_pct=10.0, days=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["gross_yield_usd"], 0.0)

    def test_gross_apy_zero(self):
        r = analyze([_opp(gross_apy_pct=0.0, bridge_cost_usd=0, gas_cost=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["gross_yield_usd"], 0.0)


class TestGasOverheadCalculation(unittest.TestCase):
    def test_gas_overhead_basic(self):
        r = analyze([_opp(gas_cost=10.0, interactions=2, days=30,
                          bridge_cost_usd=0, gross_apy_pct=20)])
        e = r["opportunities"][0]
        expected = 10.0 * 2 * (30 / 30)
        self.assertAlmostEqual(e["gas_overhead_usd"], expected, places=4)

    def test_gas_overhead_60_days(self):
        r = analyze([_opp(gas_cost=5.0, interactions=4, days=60,
                          bridge_cost_usd=0, gross_apy_pct=20)])
        e = r["opportunities"][0]
        expected = 5.0 * 4 * (60 / 30)
        self.assertAlmostEqual(e["gas_overhead_usd"], expected, places=4)

    def test_gas_overhead_zero_days(self):
        r = analyze([_opp(gas_cost=10.0, interactions=2, days=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["gas_overhead_usd"], 0.0)

    def test_gas_overhead_zero_interactions(self):
        r = analyze([_opp(gas_cost=10.0, interactions=0, days=90)])
        e = r["opportunities"][0]
        self.assertEqual(e["gas_overhead_usd"], 0.0)

    def test_gas_overhead_fractional_months(self):
        r = analyze([_opp(gas_cost=10.0, interactions=1, days=15)])
        e = r["opportunities"][0]
        expected = 10.0 * 1 * (15 / 30)
        self.assertAlmostEqual(e["gas_overhead_usd"], expected, places=4)


class TestNetYieldCalculation(unittest.TestCase):
    def test_net_yield_no_costs(self):
        r = analyze([_opp(bridge_cost_usd=0, gas_cost=0, interactions=0,
                          capital=10_000, gross_apy_pct=10.0, days=365)])
        e = r["opportunities"][0]
        self.assertAlmostEqual(e["net_yield_usd"], 1000.0, places=4)

    def test_net_yield_with_bridge_cost(self):
        r = analyze([_opp(bridge_cost_usd=100, gas_cost=0, interactions=0,
                          capital=10_000, gross_apy_pct=10.0, days=365)])
        e = r["opportunities"][0]
        self.assertAlmostEqual(e["net_yield_usd"], 900.0, places=4)

    def test_net_yield_negative(self):
        r = analyze([_opp(bridge_cost_usd=5000, gas_cost=0, interactions=0,
                          capital=10_000, gross_apy_pct=1.0, days=30)])
        e = r["opportunities"][0]
        self.assertLess(e["net_yield_usd"], 0)

    def test_net_yield_with_gas_and_bridge(self):
        # gross = 100000 * 0.05 * (90/365) = 1232.877
        # gas = 2 * 3 * (90/30) = 18
        # net = 1232.877 - 50 - 18
        r = analyze([_opp(capital=100_000, gross_apy_pct=5.0, days=90,
                          bridge_cost_usd=50, gas_cost=2.0, interactions=3)])
        e = r["opportunities"][0]
        gross = 100_000 * 0.05 * (90 / 365)
        gas = 2.0 * 3 * (90 / 30)
        expected = gross - 50 - gas
        self.assertAlmostEqual(e["net_yield_usd"], expected, places=4)


class TestNetAPYCalculation(unittest.TestCase):
    def test_net_apy_no_costs(self):
        r = analyze([_opp(bridge_cost_usd=0, gas_cost=0, interactions=0,
                          capital=100_000, gross_apy_pct=5.0, days=365)])
        e = r["opportunities"][0]
        self.assertAlmostEqual(e["net_apy_pct"], 5.0, places=4)

    def test_net_apy_zero_capital(self):
        r = analyze([_opp(capital=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["net_apy_pct"], 0.0)

    def test_net_apy_zero_days(self):
        r = analyze([_opp(days=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["net_apy_pct"], 0.0)

    def test_net_apy_reduced_by_costs(self):
        r = analyze([_opp(capital=100_000, gross_apy_pct=10.0, days=365,
                          bridge_cost_usd=500, gas_cost=0, interactions=0)])
        e = r["opportunities"][0]
        # net_yield = 10000 - 500 = 9500; net_apy = 9500/100000 * 100 = 9.5
        self.assertAlmostEqual(e["net_apy_pct"], 9.5, places=4)


class TestBreakEvenDays(unittest.TestCase):
    def test_break_even_no_costs(self):
        r = analyze([_opp(bridge_cost_usd=0, gas_cost=0, interactions=0,
                          capital=100_000, gross_apy_pct=10.0, days=90)])
        e = r["opportunities"][0]
        # total_fixed_costs = 0, so break_even = 0/daily_yield = 0
        self.assertAlmostEqual(e["break_even_days"], 0.0, places=4)

    def test_break_even_with_costs(self):
        # gross_yield = 100000 * 0.10 * (90/365) = 2465.75
        # daily_yield = 2465.75 / 90 = 27.397
        # gas_overhead = 1*2*(90/30) = 6
        # total_fixed = 10 + 6 = 16
        # break_even = 16 / 27.397 = 0.584
        r = analyze([_opp(capital=100_000, gross_apy_pct=10.0, days=90,
                          bridge_cost_usd=10, gas_cost=1.0, interactions=2)])
        e = r["opportunities"][0]
        gross = 100_000 * 0.10 * (90 / 365)
        daily = gross / 90
        gas_oh = 1.0 * 2 * (90 / 30)
        expected_be = (10 + gas_oh) / daily
        self.assertAlmostEqual(e["break_even_days"], expected_be, places=2)

    def test_break_even_zero_gross_yield(self):
        r = analyze([_opp(capital=0, gross_apy_pct=10.0, days=90,
                          bridge_cost_usd=100)])
        e = r["opportunities"][0]
        self.assertEqual(e["break_even_days"], 99999.0)

    def test_break_even_zero_days(self):
        r = analyze([_opp(capital=100_000, gross_apy_pct=10.0, days=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["break_even_days"], 99999.0)

    def test_break_even_inf_stored_as_99999(self):
        r = analyze([_opp(capital=100_000, gross_apy_pct=0.0, days=90,
                          bridge_cost_usd=100)])
        e = r["opportunities"][0]
        self.assertEqual(e["break_even_days"], 99999.0)


class TestEfficiencyLabel(unittest.TestCase):
    def test_excellent(self):
        # net/gross = 0.95
        self.assertEqual(_efficiency_label(9.5, 10.0), "EXCELLENT")

    def test_good(self):
        self.assertEqual(_efficiency_label(7.6, 10.0), "GOOD")

    def test_fair(self):
        self.assertEqual(_efficiency_label(6.0, 10.0), "FAIR")

    def test_poor(self):
        self.assertEqual(_efficiency_label(3.0, 10.0), "POOR")

    def test_unviable_ratio(self):
        self.assertEqual(_efficiency_label(2.0, 10.0), "UNVIABLE")

    def test_unviable_negative_net(self):
        self.assertEqual(_efficiency_label(-1.0, 10.0), "UNVIABLE")

    def test_zero_gross_apy(self):
        # efficiency = 1.0 when gross=0; but net_apy=0 → UNVIABLE
        self.assertEqual(_efficiency_label(0.0, 0.0), "UNVIABLE")

    def test_excellent_boundary_exactly_09(self):
        self.assertEqual(_efficiency_label(9.0, 10.0), "EXCELLENT")

    def test_good_boundary_exactly_075(self):
        self.assertEqual(_efficiency_label(7.5, 10.0), "GOOD")

    def test_fair_boundary_exactly_05(self):
        self.assertEqual(_efficiency_label(5.0, 10.0), "FAIR")

    def test_poor_boundary_exactly_025(self):
        self.assertEqual(_efficiency_label(2.5, 10.0), "POOR")


class TestChainEfficiencyLabelInResult(unittest.TestCase):
    def test_excellent_label_full_capital(self):
        # No costs, should be EXCELLENT
        r = analyze([_opp(bridge_cost_usd=0, gas_cost=0, interactions=0,
                          capital=1_000_000, gross_apy_pct=10.0, days=365)])
        e = r["opportunities"][0]
        self.assertEqual(e["chain_efficiency_label"], "EXCELLENT")

    def test_unviable_label_negative_net(self):
        r = analyze([_opp(bridge_cost_usd=100_000, gas_cost=0, interactions=0,
                          capital=1_000, gross_apy_pct=5.0, days=30)])
        e = r["opportunities"][0]
        self.assertEqual(e["chain_efficiency_label"], "UNVIABLE")


class TestRecommendationStrings(unittest.TestCase):
    def test_excellent_recommendation(self):
        rec = _recommendation("EXCELLENT", "ethereum", 9.5, 0.0, 90, 0.0, 950.0)
        self.assertIn("Deploy on ethereum", rec)
        self.assertIn("9.50%", rec)

    def test_good_recommendation(self):
        rec = _recommendation("GOOD", "arbitrum", 8.0, 5.0, 60, 5.0, 800.0)
        self.assertIn("arbitrum viable", rec)
        self.assertIn("8.00%", rec)
        self.assertIn("60d", rec)

    def test_fair_recommendation(self):
        rec = _recommendation("FAIR", "base", 5.0, 50.0, 90, 45.0, 100.0)
        self.assertIn("Marginal on base", rec)
        self.assertIn("45", rec)  # break_even_days

    def test_poor_recommendation(self):
        rec = _recommendation("POOR", "optimism", 3.0, 100.0, 90, 200.0, 50.0)
        self.assertIn("High overhead on optimism", rec)

    def test_unviable_recommendation(self):
        rec = _recommendation("UNVIABLE", "ethereum", -5.0, 500.0, 30, 99999.0, -100.0)
        self.assertIn("Costs exceed yield on ethereum", rec)
        self.assertIn("-100", rec)


class TestReferenceChainNetAPY(unittest.TestCase):
    def test_reference_chain_found(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 8.0, 5, 0.5, 2, 100_000, 365),
        ]
        r = analyze(opps)
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)

    def test_reference_chain_not_found(self):
        opps = [_opp("A", "arbitrum", 8.0, 5, 0.5, 2, 100_000, 365)]
        r = analyze(opps, config={"reference_chain": "ethereum"})
        self.assertIsNone(r["reference_chain_net_apy"])

    def test_reference_chain_first_match(self):
        # Two ethereum entries — should pick the first
        opps = [
            _opp("A", "ethereum", 3.0, 0, 0, 0, 100_000, 365),
            _opp("B", "ethereum", 6.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        self.assertAlmostEqual(r["reference_chain_net_apy"], 3.0, places=3)

    def test_reference_chain_custom(self):
        opps = [
            _opp("A", "ethereum", 4.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 7.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps, config={"reference_chain": "arbitrum"})
        self.assertAlmostEqual(r["reference_chain_net_apy"], 7.0, places=3)

    def test_reference_chain_case_insensitive(self):
        opps = [_opp("A", "Ethereum", 5.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps, config={"reference_chain": "ethereum"})
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)


class TestVsReferenceChainPct(unittest.TestCase):
    def test_reference_chain_vs_is_none(self):
        opps = [_opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps)
        self.assertIsNone(r["opportunities"][0]["vs_reference_chain_pct"])

    def test_non_reference_has_vs_value(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 8.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        vs = r["opportunities"][1]["vs_reference_chain_pct"]
        self.assertIsNotNone(vs)
        self.assertAlmostEqual(vs, 3.0, places=3)

    def test_no_reference_all_none(self):
        opps = [_opp("A", "arbitrum", 8.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps, config={"reference_chain": "ethereum"})
        self.assertIsNone(r["opportunities"][0]["vs_reference_chain_pct"])


class TestBestNetYieldAndAPY(unittest.TestCase):
    def test_best_net_yield_label(self):
        opps = [
            _opp("HighYield", "arbitrum", 20.0, 0, 0, 0, 1_000_000, 365),
            _opp("LowYield", "ethereum", 2.0, 0, 0, 0, 10_000, 365),
        ]
        r = analyze(opps)
        self.assertIn("HighYield", r["best_net_yield"])
        self.assertIn("arbitrum", r["best_net_yield"])

    def test_best_net_apy_label(self):
        opps = [
            _opp("HighAPY", "base", 30.0, 0, 0, 0, 100_000, 365),
            _opp("LowAPY", "ethereum", 3.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        self.assertIn("HighAPY", r["best_net_apy"])

    def test_single_opportunity_is_best(self):
        opps = [_opp("Solo", "ethereum", 5.0, 0, 0, 0, 100_000, 90)]
        r = analyze(opps)
        self.assertIn("Solo", r["best_net_yield"])
        self.assertIn("Solo", r["best_net_apy"])


class TestChainSummary(unittest.TestCase):
    def test_chain_summary_count(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "ethereum", 6.0, 0, 0, 0, 100_000, 365),
            _opp("C", "arbitrum", 8.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        cs = r["chain_summary"]
        self.assertEqual(cs["ethereum"]["count"], 2)
        self.assertEqual(cs["arbitrum"]["count"], 1)

    def test_chain_summary_avg_net_apy(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "ethereum", 7.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        cs = r["chain_summary"]["ethereum"]
        self.assertAlmostEqual(cs["avg_net_apy"], 6.0, places=3)

    def test_chain_summary_best_net_apy(self):
        opps = [
            _opp("A", "ethereum", 3.0, 0, 0, 0, 100_000, 365),
            _opp("B", "ethereum", 9.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        cs = r["chain_summary"]["ethereum"]
        self.assertAlmostEqual(cs["best_net_apy"], 9.0, places=3)

    def test_chain_summary_keys_lowercase(self):
        opps = [_opp("A", "Ethereum", 5.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps)
        self.assertIn("ethereum", r["chain_summary"])

    def test_chain_summary_multiple_chains(self):
        opps = [
            _opp("A", "ethereum", 4.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 6.0, 0, 0, 0, 100_000, 365),
            _opp("C", "base", 8.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        self.assertEqual(len(r["chain_summary"]), 3)


class TestOutputStructure(unittest.TestCase):
    def test_all_top_level_keys_present(self):
        r = analyze([_opp()])
        for k in ("opportunities", "best_net_yield", "best_net_apy",
                   "reference_chain_net_apy", "chain_summary", "timestamp"):
            self.assertIn(k, r)

    def test_opportunity_keys(self):
        r = analyze([_opp()])
        e = r["opportunities"][0]
        for k in ("protocol", "chain", "gross_apy_pct", "gross_yield_usd",
                   "bridge_cost_usd", "gas_overhead_usd", "net_yield_usd",
                   "net_apy_pct", "break_even_days", "chain_efficiency_label",
                   "vs_reference_chain_pct", "recommendation"):
            self.assertIn(k, e)

    def test_timestamp_is_float(self):
        r = analyze([_opp()])
        self.assertIsInstance(r["timestamp"], float)

    def test_chain_lowercase_in_result(self):
        r = analyze([_opp(chain="Ethereum")])
        e = r["opportunities"][0]
        self.assertEqual(e["chain"], "ethereum")


class TestPersistLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_persist_creates_file(self):
        analyze([_opp()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        self.assertTrue(os.path.exists(path))

    def test_persist_appends_entries(self):
        for _ in range(3):
            analyze([_opp()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap(self):
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        # Write 105 entries
        for _ in range(_LOG_CAP + 5):
            analyze([_opp()], persist=True, data_dir=self.tmpdir)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_no_persist_no_file(self):
        analyze([_opp()], persist=False, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        self.assertFalse(os.path.exists(path))

    def test_log_entry_has_timestamp(self):
        analyze([_opp()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_is_valid_json(self):
        analyze([_opp()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "cross_chain_yield_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestMultipleOpportunities(unittest.TestCase):
    def test_three_chains(self):
        opps = [
            _opp("A", "ethereum", 3.5, 0.0, 15.0, 2, 100_000, 90),
            _opp("B", "arbitrum", 4.6, 5.0, 0.5, 4, 100_000, 90),
            _opp("C", "base", 5.2, 8.0, 0.3, 4, 100_000, 90),
        ]
        r = analyze(opps)
        self.assertEqual(len(r["opportunities"]), 3)
        self.assertIsNotNone(r["best_net_yield"])
        self.assertIsNotNone(r["best_net_apy"])

    def test_vs_reference_set_for_non_ethereum(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 7.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        eth = r["opportunities"][0]
        arb = r["opportunities"][1]
        self.assertIsNone(eth["vs_reference_chain_pct"])
        self.assertIsNotNone(arb["vs_reference_chain_pct"])


class TestEdgeCases(unittest.TestCase):
    def test_very_high_bridge_cost(self):
        r = analyze([_opp(bridge_cost_usd=1_000_000, capital=1_000,
                          gross_apy_pct=100.0, days=365)])
        e = r["opportunities"][0]
        self.assertLess(e["net_yield_usd"], 0)
        self.assertEqual(e["chain_efficiency_label"], "UNVIABLE")

    def test_zero_gross_apy_label(self):
        r = analyze([_opp(gross_apy_pct=0.0, bridge_cost_usd=0, gas_cost=0)])
        e = r["opportunities"][0]
        self.assertEqual(e["chain_efficiency_label"], "UNVIABLE")

    def test_large_capital(self):
        r = analyze([_opp(capital=10_000_000, gross_apy_pct=5.0, days=365,
                          bridge_cost_usd=0, gas_cost=0, interactions=0)])
        e = r["opportunities"][0]
        self.assertAlmostEqual(e["net_yield_usd"], 500_000.0, places=2)

    def test_one_day_holding(self):
        r = analyze([_opp(days=1, capital=100_000, gross_apy_pct=10.0,
                          bridge_cost_usd=0, gas_cost=0, interactions=0)])
        e = r["opportunities"][0]
        expected_gross = 100_000 * 0.10 / 365
        self.assertAlmostEqual(e["gross_yield_usd"], expected_gross, places=4)

    def test_protocol_field_preserved(self):
        r = analyze([_opp(protocol="MorphoSteakhouse")])
        e = r["opportunities"][0]
        self.assertEqual(e["protocol"], "MorphoSteakhouse")


class TestConfigOptions(unittest.TestCase):
    def test_default_reference_chain_is_ethereum(self):
        opps = [
            _opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 7.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps)
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)

    def test_custom_reference_chain_base(self):
        opps = [
            _opp("A", "base", 5.0, 0, 0, 0, 100_000, 365),
            _opp("B", "arbitrum", 7.0, 0, 0, 0, 100_000, 365),
        ]
        r = analyze(opps, config={"reference_chain": "base"})
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)
        # arbitrum should have vs_reference_chain_pct set
        arb = r["opportunities"][1]
        self.assertAlmostEqual(arb["vs_reference_chain_pct"], 2.0, places=3)

    def test_none_config_uses_defaults(self):
        opps = [_opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps, config=None)
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)

    def test_empty_config_uses_defaults(self):
        opps = [_opp("A", "ethereum", 5.0, 0, 0, 0, 100_000, 365)]
        r = analyze(opps, config={})
        self.assertAlmostEqual(r["reference_chain_net_apy"], 5.0, places=3)


class TestBreakEvenDaysEdge(unittest.TestCase):
    def test_break_even_zero_costs_zero(self):
        r = analyze([_opp(bridge_cost_usd=0, gas_cost=0, interactions=0,
                          capital=100_000, gross_apy_pct=10.0, days=90)])
        e = r["opportunities"][0]
        self.assertAlmostEqual(e["break_even_days"], 0.0, places=6)

    def test_break_even_is_float(self):
        r = analyze([_opp()])
        e = r["opportunities"][0]
        self.assertIsInstance(e["break_even_days"], float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
