"""
Tests for MP-658: BasisTradeAnalyzer
≥60 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_basis_trade_analyzer -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer,
    BasisTradeInput,
    BasisTradeResult,
    MAX_ENTRIES,
)


def make_input(
    asset="ETH",
    spot_yield=0.05,
    perp_funding=0.10,
    exec_cost=20.0,
    capital=100_000.0,
):
    return BasisTradeInput(
        asset=asset,
        spot_yield_annual=spot_yield,
        perp_funding_annual=perp_funding,
        execution_cost_bps=exec_cost,
        capital_usd=capital,
    )


class TestGrossSpreadBps(unittest.TestCase):
    """_gross_spread_bps: (spot + perp) * 10000."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_standard_case(self):
        # spot=0.10, perp=0.20 → (0.30)*10000 = 3000
        self.assertAlmostEqual(self.a._gross_spread_bps(0.10, 0.20), 3000.0, places=4)

    def test_perp_negative_reduces_spread(self):
        # spot=0.10, perp=-0.05 → 0.05*10000 = 500
        self.assertAlmostEqual(self.a._gross_spread_bps(0.10, -0.05), 500.0, places=4)

    def test_both_zero(self):
        self.assertAlmostEqual(self.a._gross_spread_bps(0.0, 0.0), 0.0, places=4)

    def test_negative_sum(self):
        # spot=0.02, perp=-0.10 → -0.08*10000 = -800
        self.assertAlmostEqual(self.a._gross_spread_bps(0.02, -0.10), -800.0, places=4)

    def test_small_values(self):
        self.assertAlmostEqual(self.a._gross_spread_bps(0.01, 0.01), 200.0, places=4)

    def test_result_rounded_4dp(self):
        result = self.a._gross_spread_bps(0.10001, 0.20001)
        self.assertEqual(result, round((0.10001 + 0.20001) * 10000, 4))


class TestEdgeQuality(unittest.TestCase):
    """_edge_quality: EXCELLENT/GOOD/MARGINAL/UNATTRACTIVE thresholds."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_excellent_above_100(self):
        self.assertEqual(self.a._edge_quality(150.0), "EXCELLENT")

    def test_excellent_at_boundary_100(self):
        self.assertEqual(self.a._edge_quality(100.0), "EXCELLENT")

    def test_good_above_50(self):
        self.assertEqual(self.a._edge_quality(75.0), "GOOD")

    def test_good_at_boundary_50(self):
        self.assertEqual(self.a._edge_quality(50.0), "GOOD")

    def test_good_just_below_100(self):
        self.assertEqual(self.a._edge_quality(99.9), "GOOD")

    def test_marginal_above_10(self):
        self.assertEqual(self.a._edge_quality(30.0), "MARGINAL")

    def test_marginal_at_boundary_10(self):
        self.assertEqual(self.a._edge_quality(10.0), "MARGINAL")

    def test_marginal_just_below_50(self):
        self.assertEqual(self.a._edge_quality(49.9), "MARGINAL")

    def test_unattractive_below_10(self):
        self.assertEqual(self.a._edge_quality(5.0), "UNATTRACTIVE")

    def test_unattractive_zero(self):
        self.assertEqual(self.a._edge_quality(0.0), "UNATTRACTIVE")

    def test_unattractive_negative(self):
        self.assertEqual(self.a._edge_quality(-50.0), "UNATTRACTIVE")

    def test_unattractive_just_below_10(self):
        self.assertEqual(self.a._edge_quality(9.9), "UNATTRACTIVE")


class TestAction(unittest.TestCase):
    """_action: ENTER/MONITOR/SKIP."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_enter_above_50(self):
        self.assertEqual(self.a._action(100.0), "ENTER")

    def test_enter_at_boundary_50(self):
        self.assertEqual(self.a._action(50.0), "ENTER")

    def test_monitor_above_10(self):
        self.assertEqual(self.a._action(30.0), "MONITOR")

    def test_monitor_at_boundary_10(self):
        self.assertEqual(self.a._action(10.0), "MONITOR")

    def test_monitor_just_below_50(self):
        self.assertEqual(self.a._action(49.9), "MONITOR")

    def test_skip_below_10(self):
        self.assertEqual(self.a._action(5.0), "SKIP")

    def test_skip_zero(self):
        self.assertEqual(self.a._action(0.0), "SKIP")

    def test_skip_negative(self):
        self.assertEqual(self.a._action(-20.0), "SKIP")

    def test_skip_just_below_10(self):
        self.assertEqual(self.a._action(9.9), "SKIP")


class TestAnalyze(unittest.TestCase):
    """analyze(): net spread, pnl, is_profitable, fields."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_returns_result_instance(self):
        inp = make_input()
        self.assertIsInstance(self.a.analyze(inp), BasisTradeResult)

    def test_asset_preserved(self):
        inp = make_input(asset="BTC")
        self.assertEqual(self.a.analyze(inp).asset, "BTC")

    def test_net_equals_gross_minus_execution_cost(self):
        inp = make_input(spot_yield=0.05, perp_funding=0.10, exec_cost=20.0)
        r = self.a.analyze(inp)
        expected_gross = round((0.05 + 0.10) * 10000, 4)
        expected_net = round(expected_gross - 20.0, 4)
        self.assertAlmostEqual(r.net_spread_bps, expected_net, places=4)

    def test_annual_pnl_formula(self):
        inp = make_input(spot_yield=0.05, perp_funding=0.10, exec_cost=20.0, capital=100_000.0)
        r = self.a.analyze(inp)
        expected_pnl = round(100_000.0 * r.net_spread_bps / 10000, 4)
        self.assertAlmostEqual(r.annual_pnl_usd, expected_pnl, places=2)

    def test_is_profitable_true_when_net_positive(self):
        inp = make_input(spot_yield=0.10, perp_funding=0.10, exec_cost=10.0)
        r = self.a.analyze(inp)
        self.assertTrue(r.is_profitable)

    def test_is_profitable_false_when_net_zero(self):
        # net = 0: execution_cost equals gross
        inp = make_input(spot_yield=0.05, perp_funding=0.0, exec_cost=500.0)
        r = self.a.analyze(inp)
        self.assertFalse(r.is_profitable)

    def test_is_profitable_false_when_net_negative(self):
        inp = make_input(spot_yield=0.01, perp_funding=0.01, exec_cost=300.0)
        r = self.a.analyze(inp)
        self.assertFalse(r.is_profitable)

    def test_zero_execution_cost_net_equals_gross(self):
        inp = make_input(spot_yield=0.05, perp_funding=0.10, exec_cost=0.0)
        r = self.a.analyze(inp)
        self.assertAlmostEqual(r.net_spread_bps, r.gross_spread_bps, places=4)

    def test_execution_cost_exceeds_gross_net_negative(self):
        inp = make_input(spot_yield=0.01, perp_funding=0.01, exec_cost=5000.0)
        r = self.a.analyze(inp)
        self.assertLess(r.net_spread_bps, 0)
        self.assertFalse(r.is_profitable)

    def test_edge_quality_assigned(self):
        inp = make_input(spot_yield=0.10, perp_funding=0.10, exec_cost=10.0)
        r = self.a.analyze(inp)
        self.assertIn(r.edge_quality, ("EXCELLENT", "GOOD", "MARGINAL", "UNATTRACTIVE"))

    def test_recommended_action_assigned(self):
        inp = make_input(spot_yield=0.10, perp_funding=0.10, exec_cost=10.0)
        r = self.a.analyze(inp)
        self.assertIn(r.recommended_action, ("ENTER", "MONITOR", "SKIP"))

    def test_capital_preserved_rounded(self):
        inp = make_input(capital=123456.789)
        r = self.a.analyze(inp)
        self.assertAlmostEqual(r.capital_usd, 123456.79, places=2)


class TestAnalyzeBatch(unittest.TestCase):
    """analyze_batch(): empty list and multiple entries."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_empty_returns_empty(self):
        self.assertEqual(self.a.analyze_batch([]), [])

    def test_single_entry(self):
        result = self.a.analyze_batch([make_input()])
        self.assertEqual(len(result), 1)

    def test_multiple_entries(self):
        inputs = [make_input(f"A{i}") for i in range(5)]
        results = self.a.analyze_batch(inputs)
        self.assertEqual(len(results), 5)
        for i, r in enumerate(results):
            self.assertEqual(r.asset, f"A{i}")

    def test_results_in_input_order(self):
        inputs = [make_input("ETH"), make_input("BTC"), make_input("SOL")]
        results = self.a.analyze_batch(inputs)
        self.assertEqual([r.asset for r in results], ["ETH", "BTC", "SOL"])


class TestTopOpportunities(unittest.TestCase):
    """top_opportunities(): sorted desc by net_spread_bps, n capped."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_empty_returns_empty(self):
        self.assertEqual(self.a.top_opportunities([]), [])

    def test_n_1_returns_best(self):
        r1 = self.a.analyze(make_input("ETH", 0.05, 0.10, 10.0))
        r2 = self.a.analyze(make_input("BTC", 0.10, 0.20, 10.0))
        top = self.a.top_opportunities([r1, r2], n=1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].asset, "BTC")

    def test_sorted_descending_by_net_spread(self):
        r_low = self.a.analyze(make_input("L", 0.01, 0.01, 10.0))
        r_mid = self.a.analyze(make_input("M", 0.05, 0.05, 10.0))
        r_high = self.a.analyze(make_input("H", 0.10, 0.10, 10.0))
        top = self.a.top_opportunities([r_low, r_high, r_mid], n=3)
        self.assertEqual(top[0].asset, "H")
        self.assertEqual(top[1].asset, "M")
        self.assertEqual(top[2].asset, "L")

    def test_n_greater_than_results_returns_all(self):
        results = [self.a.analyze(make_input(f"X{i}")) for i in range(3)]
        top = self.a.top_opportunities(results, n=10)
        self.assertEqual(len(top), 3)

    def test_default_n_is_3(self):
        results = [self.a.analyze(make_input(f"X{i}")) for i in range(5)]
        top = self.a.top_opportunities(results)
        self.assertEqual(len(top), 3)


class TestTotalAnnualPnl(unittest.TestCase):
    """total_annual_pnl(): sum including negatives."""

    def setUp(self):
        self.a = BasisTradeAnalyzer()

    def test_empty_returns_zero(self):
        self.assertEqual(self.a.total_annual_pnl([]), 0.0)

    def test_single_result(self):
        r = self.a.analyze(make_input(spot_yield=0.05, perp_funding=0.10, exec_cost=10.0, capital=100_000.0))
        total = self.a.total_annual_pnl([r])
        self.assertAlmostEqual(total, r.annual_pnl_usd, places=4)

    def test_sums_correctly(self):
        r1 = self.a.analyze(make_input("A", 0.05, 0.10, 10.0, 100_000.0))
        r2 = self.a.analyze(make_input("B", 0.03, 0.08, 10.0, 50_000.0))
        total = self.a.total_annual_pnl([r1, r2])
        self.assertAlmostEqual(total, round(r1.annual_pnl_usd + r2.annual_pnl_usd, 4), places=2)

    def test_includes_negative_pnl(self):
        r_pos = self.a.analyze(make_input("P", 0.10, 0.10, 10.0, 100_000.0))
        r_neg = self.a.analyze(make_input("N", 0.01, 0.01, 500.0, 100_000.0))
        total = self.a.total_annual_pnl([r_pos, r_neg])
        self.assertAlmostEqual(total, round(r_pos.annual_pnl_usd + r_neg.annual_pnl_usd, 4), places=2)


class TestSaveAndLoad(unittest.TestCase):
    """save_results / load_history: atomic write + ring-buffer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "test_basis_log.json"
        self.a = BasisTradeAnalyzer(data_file=self.data_file)

    def _make_result(self, asset="ETH"):
        return self.a.analyze(make_input(asset))

    def test_save_creates_file(self):
        self.a.save_results([self._make_result()])
        self.assertTrue(self.data_file.exists())

    def test_save_is_valid_json(self):
        self.a.save_results([self._make_result()])
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_saved_entry_has_required_keys(self):
        self.a.save_results([self._make_result()])
        entry = json.loads(self.data_file.read_text())[0]
        for key in ("timestamp", "asset", "net_spread_bps", "edge_quality", "recommended_action", "annual_pnl_usd"):
            self.assertIn(key, entry)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.a.load_history(), [])

    def test_load_history_returns_saved(self):
        self.a.save_results([self._make_result("ETH"), self._make_result("BTC")])
        hist = self.a.load_history()
        self.assertEqual(len(hist), 2)

    def test_ring_buffer_max_100(self):
        results = [self._make_result(f"X{i}") for i in range(110)]
        self.a.save_results(results)
        self.assertLessEqual(len(self.a.load_history()), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for batch in range(2):
            results = [self._make_result(f"B{batch}_{i}") for i in range(60)]
            self.a.save_results(results)
        self.assertEqual(len(self.a.load_history()), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.a.save_results([self._make_result()])
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_save_appends_across_calls(self):
        self.a.save_results([self._make_result("ETH")])
        self.a.save_results([self._make_result("BTC")])
        self.assertEqual(len(self.a.load_history()), 2)


if __name__ == "__main__":
    unittest.main()
